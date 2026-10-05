"""Classify the jump phases of one video and write ``result.json``.

    python -m cutter_v4.engine --source VIDEO --out-dir FOLDER [--device auto|cpu|cuda]

Tracks written (all cover the whole video, in phase order):
  v4      the V4 video model: R3D-18 on 2 s windows every second, the T2 temporal head, ordered decoding
  audio   the V3 audio model on 3 s windows every second, ordered decoding (when the file has sound)
  motion  the motion-only classifier (when the camera recorded motion data)
  final   what the cutter uses: v4, plus one rule - on cameras without motion data, audio may carry freefall on past
          V4's end of freefall, over V4's break-off or opening, for up to 30 s
Plus the motion trace and events, and an agreement strip: where motion (or, without motion, audio) disagrees with the
final track. In testing on 318 held-out videos V4 was wrong on about 4% of seconds where the other source agreed.

The configuration is the one measured against human labels (release/cutter/docs/HOW_IT_WORKS.md): no boundary snap,
audio only extends freefall, motion is a check and never an override. Nothing is written beside the source video.
"""
from __future__ import annotations

import argparse
from collections import deque
from contextlib import contextmanager
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from cutter_v4 import ENGINE_REVISION, MODELS_DIR, ROOT

sys.path.insert(0, str(ROOT / 'v3_poc'))
os.environ.setdefault('NUMBA_CACHE_DIR', str(ROOT / 'cache' / 'numba'))

import numpy as np  # noqa: E402
import torch  # noqa: E402

from common import PHASES, intervals  # noqa: E402
from cutter_v4.media import (FPS, NO_WINDOW, PRIMARY_VIDEO_MAP, SIZE, VIEWS, build_proxy,  # noqa: E402,F401
                             hardware_decode, has_back_view, probe, refine_360_kind, resolve_view, video_map,
                             view_filter)

FRAMES, CLIP_SECONDS = 24, 2.0
KINETICS_MEAN = (0.43216, 0.394666, 0.37645)
KINETICS_STD = (0.22803, 0.22145, 0.216989)
AUDIO_FREEFALL_MAX_EXTENSION = 30
AFTER_FREEFALL = ('break_off', 'opening_parachutes')


def log(message: str) -> None:
    print(message, flush=True)


def monotonic(probabilities):
    """Ordered decoding: phases never go backwards, any phase may be absent. Same as the V3 pipeline."""
    if not len(probabilities):
        return []
    emission = np.log(np.maximum(probabilities, 1e-12))
    scores = emission[0].copy()
    previous = np.zeros(emission.shape, dtype=np.int64)
    for t in range(1, len(emission)):
        next_scores = np.empty_like(scores)
        for phase in range(emission.shape[1]):
            winner = int(np.argmax(scores[:phase + 1]))
            previous[t, phase] = winner
            next_scores[phase] = scores[winner] + emission[t, phase]
        scores = next_scores
    path = [int(np.argmax(scores))]
    for t in range(len(emission) - 1, 0, -1):
        path.append(int(previous[t, path[-1]]))
    return list(reversed(path))


def canonical(logits: torch.Tensor, class_names: list[str]) -> np.ndarray:
    """Softmax probabilities re-ordered into the chronological PHASES order."""
    values = torch.softmax(logits.float(), dim=-1).cpu().numpy()
    output = np.zeros((len(values), len(PHASES)), dtype=np.float64)
    for column, phase in enumerate(class_names):
        output[:, PHASES.index('inside_plane' if phase == 'other_groups_climbing_out' else phase)] += values[:, column]
    return output / output.sum(axis=1, keepdims=True)


def clean(segments: list[dict]) -> list[dict]:
    return [{'start_sec': round(float(s['start_sec']), 3), 'end_sec': round(float(s['end_sec']), 3),
             'phase': s['phase'], 'mean_model_probability': (None if s.get('mean_model_probability') is None
                                                             else round(float(s['mean_model_probability']), 4))}
            for s in segments]


def phase_name_at(segments: list[dict], t: float):
    """The phase covering ``t``, or None where the track does not reach. See app.timeline.segment_at for the
    other lookup: that one returns the segment itself and insists the track covers the time."""
    for segment in segments:
        if segment['start_sec'] <= t < segment['end_sec']:
            return segment['phase']
    return None


# ------------------------------------------------------------------------------------------------------ models
class Models:
    def __init__(self, device: torch.device):
        from networks import AudioHead  # v3_poc/networks.py

        from cutter_v4.networks import TemporalHead, visual_model

        self.device = device
        visual = torch.load(MODELS_DIR / 'visual.pt', map_location='cpu', weights_only=True)
        self.class_names = list(visual['class_names'])
        trunk, _head = visual_model(len(self.class_names))
        trunk.load_state_dict(visual['model'])
        self.head = trunk.fc
        trunk.fc = torch.nn.Identity()
        self.trunk, self.head = trunk.to(device).eval(), self.head.to(device).eval()
        temporal = torch.load(MODELS_DIR / 'temporal.pt', map_location='cpu', weights_only=True)
        if list(temporal['class_names']) != self.class_names:
            raise ValueError('The visual and temporal model files do not belong together.')
        self.temporal = TemporalHead(512, len(self.class_names), temporal['mean'], temporal['std'])
        self.temporal.load_state_dict(temporal['model'])
        self.temporal.eval()
        audio = torch.load(MODELS_DIR / 'audio.pt', map_location='cpu', weights_only=True)
        self.audio_classes = list(audio['class_names'])
        self.audio = AudioHead(audio['model']).to(device).eval()
        self.mean = torch.tensor(KINETICS_MEAN, device=device).view(1, 3, 1, 1, 1)
        self.std = torch.tensor(KINETICS_STD, device=device).view(1, 3, 1, 1, 1)


def visual_windows(ffmpeg: str, proxy: Path, models: Models, batch_size: int):
    """Embeddings and window logits for 2 s windows every second, decoded straight from the proxy."""
    frame_bytes = SIZE * SIZE * 3
    ring: deque = deque(maxlen=FRAMES)
    pending, features, logits, centres = [], [], [], []
    count, last_report = 0, time.monotonic()

    def flush():
        if not pending:
            return
        values = torch.from_numpy(np.stack(pending)).to(device=models.device, dtype=torch.float32)
        values = values.permute(0, 4, 1, 2, 3).div_(255.0)
        with torch.inference_mode(), torch.amp.autocast('cuda', enabled=models.device.type == 'cuda'):
            embedding = models.trunk((values - models.mean) / models.std)
            window_logits = models.head(embedding)
        features.append(embedding.float().cpu())
        logits.append(window_logits.float().cpu())
        pending.clear()

    command = [ffmpeg, '-hide_banner', '-nostdin', '-v', 'error', '-i', str(proxy), '-map', PRIMARY_VIDEO_MAP,
               '-an', '-sn', '-dn', '-vf', f'fps={FPS:g},format=rgb24', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1']
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=NO_WINDOW)
    try:
        while True:
            buffer = process.stdout.read(frame_bytes)
            if len(buffer) < frame_bytes:
                break
            ring.append(np.frombuffer(buffer, dtype=np.uint8).reshape(SIZE, SIZE, 3))
            count += 1
            if count >= FRAMES and (count - FRAMES) % round(FPS) == 0:
                pending.append(np.stack(ring))
                centres.append((count - FRAMES) / FPS + CLIP_SECONDS / 2)
                if len(pending) >= batch_size:
                    flush()
                if time.monotonic() - last_report > 2:
                    log(f'phases: {count / FPS:.1f}s decoded, {len(centres)} windows')
                    last_report = time.monotonic()
        flush()
        stderr = process.stderr.read().decode('utf-8', 'replace')
    finally:
        code = process.wait()
    if code or not features:
        raise RuntimeError(f'Video decode failed ({code}): {stderr[-500:]}')
    log(f'phases: {count / FPS:.1f}s decoded, {len(centres)} windows')
    return torch.cat(features), torch.cat(logits), np.asarray(centres, dtype=np.float64)


CACHE_LOCK_STALE_SECONDS = 600   # a holder that died leaves its lock; nobody takes this long to analyse one sound


def compile_cache_marker(folder: Path) -> Path:
    """The file that says this cache was filled, start to finish, by one process, for these library versions."""
    from importlib import metadata
    versions = []
    for package in ('numba', 'librosa'):
        try:
            versions.append(metadata.version(package))
        except metadata.PackageNotFoundError:
            versions.append('none')
    return folder / ('.filled-' + '-'.join(versions) + f'-py{sys.version_info.major}{sys.version_info.minor}')


@contextmanager
def compile_cache():
    """Hold the sound analysis's compile cache while it is being filled for the first time.

    The audio features use librosa, which compiles its inner loops on first use and saves them under
    NUMBA_CACHE_DIR. Several engines filling that folder at once (videos processed side by side on a fresh
    install) leave it damaged, and from then on every engine crashes the moment it analyses sound, even one at a
    time. So the first fill is done by one engine while any others wait; once the marker is there the cache is only
    read, which is safe side by side. A cache with no marker is not trusted: it is emptied and filled again.
    """
    folder = Path(os.environ['NUMBA_CACHE_DIR'])
    marker = compile_cache_marker(folder)
    if marker.is_file():
        yield
        return
    lock = folder.with_name(folder.name + '.filling')
    folder.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > CACHE_LOCK_STALE_SECONDS:
                    lock.rmdir()
                    continue
            except OSError:
                pass
            time.sleep(.5)
    try:
        if marker.is_file():   # another engine filled it while this one waited
            yield
            return
        log('audio: preparing the sound analysis for first use')
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True, exist_ok=True)
        yield
        marker.write_text('filled by one engine; safe to read side by side\n', encoding='utf-8')
    finally:
        try:
            lock.rmdir()
        except OSError:
            pass


def audio_track(source: Path, ffmpeg: str, work: Path, media: dict, models: Models):
    """The V3 audio model's ordered track, exactly as the V3 pipeline builds it."""
    if not media['audio_stream_count']:
        return [], 'no_audio_stream'

    try:
        with compile_cache():
            from cutter_v4.audio import audio_features
            values, centres, _duration = audio_features(source, ffmpeg, work, media['audio_offset_sec'] or 0.0)
    except Exception as exc:  # noqa: BLE001 - audio is optional; the video result stands without it
        log(f'audio unavailable: {exc}')
        return [], 'error'
    if not len(values):
        return [], 'shorter_than_3_seconds'
    with torch.inference_mode():
        probabilities = canonical(models.audio(torch.from_numpy(values).to(models.device)), models.audio_classes)
    segments = intervals(monotonic(probabilities), centres, media['duration_sec'], probabilities,
                         left=max(0., centres[0] - .5), right=centres[-1] + .5)
    return clean(segments), 'ok'


# ------------------------------------------------------------------------------------------------------ rules
def extend_freefall_with_audio(final: list[dict], audio: list[dict], duration: float) -> tuple[list[dict], int]:
    """Carry freefall on over V4's break-off/opening while audio still hears freefall, up to 30 s."""
    freefall = [s for s in final if s['phase'] == 'freefall']
    if not freefall or not audio:
        return final, 0
    end = freefall[-1]['end_sec']
    new_end, added = end, 0
    while (added < AUDIO_FREEFALL_MAX_EXTENSION and new_end < duration
           and phase_name_at(final, new_end + .5) in AFTER_FREEFALL and phase_name_at(audio, new_end + .5) == 'freefall'):
        new_end = min(duration, new_end + 1.0)
        added += 1
    if not added:
        return final, 0
    result = []
    for segment in final:
        if segment is freefall[-1]:
            result.append({**segment, 'end_sec': new_end})
        elif segment['end_sec'] <= end or segment['start_sec'] >= new_end:
            result.append(dict(segment))
        elif segment['end_sec'] > new_end:
            result.append({**segment, 'start_sec': new_end})
    return result, added


def agreement(final: list[dict], other: dict[int, str] | list[dict] | None, duration: float) -> list[dict]:
    """Per-second agree/disagree runs between the final track and a check source."""
    runs = []
    for k in range(int(duration)):
        t = k + .5
        mine = phase_name_at(final, t)
        theirs = other.get(k) if isinstance(other, dict) else phase_name_at(other or [], t)
        status = 'unknown' if mine is None or theirs is None else ('agree' if mine == theirs else 'disagree')
        if runs and runs[-1]['status'] == status and abs(runs[-1]['end_sec'] - k) < 1e-6:
            runs[-1]['end_sec'] = float(k + 1)
        else:
            runs.append({'start_sec': float(k), 'end_sec': float(k + 1), 'status': status})
    if runs:
        runs[-1]['end_sec'] = round(duration, 3)
    return runs


def segments_from_seconds(series: dict[int, str], duration: float) -> list[dict]:
    result = []
    for k in sorted(series):
        if result and result[-1]['phase'] == series[k] and abs(result[-1]['end_sec'] - k) < 1e-6:
            result[-1]['end_sec'] = float(k + 1)
        else:
            result.append({'start_sec': float(k), 'end_sec': float(k + 1), 'phase': series[k],
                           'mean_model_probability': None})
    if result:
        result[-1]['end_sec'] = min(result[-1]['end_sec'], round(duration, 3))
    return [s for s in result if s['end_sec'] > s['start_sec']]


# ------------------------------------------------------------------------------------------------------ main
def resolve_device(device: str) -> str:
    """What 'automatic' means here: an NVIDIA GPU, Apple's GPU, or the processor."""
    if device != 'auto':
        return device
    if torch.cuda.is_available():
        return 'cuda'
    if (not intel_mac() and getattr(torch.backends, 'mps', None) is not None
            and torch.backends.mps.is_available()):
        return 'mps'
    return 'cpu'


PROXY_WAIT_SECONDS = 6 * 3600   # longer than any read of one video; a caller that dies leaves its marker or nothing


def wait_for(proxy: Path) -> None:
    """Until the caller's read of the source has written the proxy. ``proxy.failed`` beside it means it never will."""
    gave_up, deadline = proxy.with_name('proxy.failed'), time.monotonic() + PROXY_WAIT_SECONDS
    while not proxy.is_file():
        if gave_up.exists():
            raise RuntimeError('The video could not be read, so there is nothing to classify.')
        if time.monotonic() > deadline:
            raise TimeoutError('The prepared proxy never arrived.')
        time.sleep(.1)


def intel_mac() -> bool:
    """Intel Macs use the processor automatically; their Apple GPU path is untested with these models."""
    import platform
    return sys.platform == 'darwin' and platform.machine() == 'x86_64'


def classify(source: Path, out_dir: Path, device: str, ffmpeg: str, ffprobe: str, batch_size: int = 8,
             view: str = 'front', hardware: str = 'auto', proxy_ready: bool = False) -> dict:
    """``proxy_ready``: the caller writes ``out_dir/proxy.mp4`` from its own read of the source (the app does, when
    it counts people from the same decode), so the source's picture is not read again here.

    The proxy need not exist yet. The engine is started alongside that read, loads its models and does the sound and
    the motion data while the read is still going, then waits for the proxy. The answers are the same in either
    order; only the waiting is shared out."""
    from cutter_v4 import motion as motion_module

    began = time.monotonic()
    stages, mark = {}, began

    def lap(name):
        nonlocal mark
        now = time.monotonic()
        stages[name] = round(now - mark, 1)
        mark = now
    out_dir.mkdir(parents=True, exist_ok=True)
    chosen = torch.device(resolve_device(device))
    if chosen.type == 'cuda' and not torch.cuda.is_available():
        raise RuntimeError('An NVIDIA GPU was requested but is not available. Choose the processor in the settings.')
    if chosen.type == 'mps' and not (getattr(torch.backends, 'mps', None) and torch.backends.mps.is_available()):
        raise RuntimeError('The Apple GPU was requested but is not available. Choose the processor in the settings.')
    media = probe(source, ffprobe)
    if media['duration_sec'] < CLIP_SECONDS:
        raise ValueError(f'The video is shorter than {CLIP_SECONDS:g} seconds.')
    media, view = resolve_view(source, ffmpeg, media, view)
    log(f'engine {ENGINE_REVISION} on {chosen}; {media["duration_sec"]:.1f}s {media["kind"]} video, {view} view')
    models = Models(chosen)
    lap('load_models')
    duration = media['duration_sec']

    def sound_and_motion():
        log('audio: analysing sound')
        track, status = audio_track(source, ffmpeg, out_dir, media, models)
        lap('audio')
        log('motion: reading camera motion data')
        try:
            found = motion_module.analyse(source, monotonic, motion_module.load_classifier())
        except Exception as exc:  # noqa: BLE001 - unreadable metadata only removes the motion check
            found = {'available': False, 'scan_status': f'error: {type(exc).__name__}'}
        lap('motion')
        return track, status, found

    proxy = out_dir / 'proxy.mp4'
    try:
        # The picture is read while the sound and the motion data are dealt with: by the caller when it is counting
        # people from the same read, otherwise on a thread here.
        reading, failed = None, []
        if not proxy_ready:
            log('phases: building proxy')

            def read_picture():
                try:
                    build_proxy(ffmpeg, source, media, proxy, view=view,
                                hardware=hardware_decode(ffmpeg, source, media, view, hardware))
                except BaseException as exc:  # noqa: BLE001 - raised below, on the thread that is waiting for it
                    failed.append(exc)
            reading = threading.Thread(target=read_picture, daemon=True)
            reading.start()
        audio, audio_status, motion = sound_and_motion()
        if reading is None:
            wait_for(proxy)
            lap('wait_for_video')
        else:
            reading.join()
            if failed:
                raise failed[0]
            lap('read_video')
        features, window_logits, centres = visual_windows(ffmpeg, proxy, models, batch_size)
    finally:
        proxy.unlink(missing_ok=True)
    with torch.inference_mode():
        temporal_logits = models.temporal(features)
    probabilities = canonical(temporal_logits, models.class_names)
    v4 = clean(intervals(monotonic(probabilities), centres, duration, probabilities))
    lap('video_model')
    motion_track = (segments_from_seconds(motion.get('phase_seconds', {}), duration)
                    if motion.get('available') and motion.get('phase_seconds') else [])

    final, extension = v4, 0
    if not motion.get('available'):
        # The rule was measured on cameras that record no motion data, so it keys on the camera, not the model.
        final, extension = extend_freefall_with_audio(v4, audio, duration)
    if motion_track:
        basis, strip = 'motion', agreement(final, motion.get('phase_seconds'), duration)
    elif audio:
        basis, strip = 'audio', agreement(final, audio, duration)
    else:
        basis, strip = 'none', agreement(final, None, duration)
    compared = sum(r['end_sec'] - r['start_sec'] for r in strip if r['status'] != 'unknown')
    disagree = sum(r['end_sec'] - r['start_sec'] for r in strip if r['status'] == 'disagree')

    flags = []
    if media['video_stream_count'] > 1 and media['kind'] != 'max_dual':
        flags.append('Several video streams; the first was used.')
    if audio_status != 'ok':
        flags.append(f'No usable audio ({audio_status.replace("_", " ")}).')
    if not motion.get('available'):
        flags.append('No camera motion data.')
    if compared and disagree / compared > .15:
        flags.append(f'Sources disagree on {100 * disagree / compared:.0f}% of the video; worth a look.')
    if extension:
        flags.append(f'Audio extended freefall by {extension}s.')
    motion.pop('phase_seconds', None)
    result = {
        'schema_version': 1, 'engine_revision': ENGINE_REVISION, 'source_video': str(source),
        'duration_sec': round(duration, 3), 'media': media,
        'tracks': {'final': final, 'v4': v4, 'audio': audio, 'motion': motion_track},
        'motion': motion, 'audio_status': audio_status,
        'agreement': strip, 'agreement_basis': basis,
        'disagreement_fraction': round(disagree / compared, 4) if compared else None,
        'rules': {'boundary_snap': False, 'audio_freefall_extension_sec': extension,
                  'audio_freefall_max_extension_sec': AUDIO_FREEFALL_MAX_EXTENSION},
        'review_flags': flags, 'timing_seconds': round(time.monotonic() - began, 1), 'stage_seconds': stages,
    }
    target = out_dir / 'result.json'
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, indent=1), encoding='utf-8')
    os.replace(temporary, target)
    log(f'done: {len(final)} phases, agreement basis {basis}, {result["timing_seconds"]}s')
    return result


def main() -> int:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--device', choices=['auto', 'cpu', 'cuda', 'mps'], default='auto')
    parser.add_argument('--ffmpeg', required=True)
    parser.add_argument('--ffprobe', required=True)
    parser.add_argument('--batch-size', type=int, default=8)
    parser.add_argument('--view', choices=VIEWS, default='front', help='which side of a 360 camera to classify')
    parser.add_argument('--hardware-decode', choices=['auto', 'off'], default='auto',
                        help='decode the video on the graphics hardware when that works for the file')
    parser.add_argument('--proxy-ready', action='store_true',
                        help='proxy.mp4 is already in the output folder; do not read the picture again')
    args = parser.parse_args()
    classify(args.source.resolve(), args.out_dir.resolve(), args.device, args.ffmpeg, args.ffprobe, args.batch_size,
             view=args.view, hardware=args.hardware_decode, proxy_ready=args.proxy_ready)
    return 0


if __name__ == '__main__':
    sys.exit(main())
