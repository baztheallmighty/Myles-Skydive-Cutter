"""What a video file holds, the view the models look through, and the one ffmpeg command that reads a source.

Nothing here needs torch, so the app can use it without loading the models. A source is read once: the same decode
feeds the phase model's small proxy and the frames the people counter looks at, and it runs on the graphics hardware
when that works for the file.
"""
from __future__ import annotations

import functools
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)  # never flash a console window over the app
SIZE, FPS = 160, 12.0
PEOPLE_SIZE = 640  # the longest side the person detector sees; the phase model uses the same view at 160
PRIMARY_VIDEO_MAP = '0:V:0'  # upper-case V skips cover images
VIEWS = ('front', 'back')
# A dual-fisheye frame is two circles side by side, so its corners are black; a stitched sphere fills them.
FISHEYE_CORNER_RATIO = 0.3
# Encoded exactly as the training proxies were.
PROXY_ENCODING = ['-c:v', 'libx264', '-threads', '2', '-preset', 'veryfast', '-crf', '23', '-g', '12',
                  '-keyint_min', '12', '-sc_threshold', '0', '-pix_fmt', 'yuv420p']
# Hardware decoders worth trying, best first. Each is tried on the file itself and dropped if it complains.
HARDWARE_METHODS = {'win32': ('cuda', 'd3d11va'), 'darwin': ('videotoolbox',)}
# What a frame decoded on an NVIDIA card looks like once copied to main memory, by the picture format of the file.
ON_CARD = ['-hwaccel_output_format', 'cuda']
DOWNLOADED = {'yuv420p': 'nv12', 'yuvj420p': 'nv12', 'nv12': 'nv12', 'yuv420p10le': 'p010le', 'p010le': 'p010le'}


def probe(source: Path, ffprobe: str) -> dict:
    result = subprocess.run([ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(source)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300,
                            creationflags=NO_WINDOW)
    if result.returncode:
        raise RuntimeError('Could not read this file as a video: ' + result.stderr[-600:])
    payload = json.loads(result.stdout)
    streams = payload.get('streams', [])
    videos = [s for s in streams if s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic')]
    audio = [s for s in streams if s.get('codec_type') == 'audio']
    if not videos:
        raise ValueError('The file has no video stream.')

    def number(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    stream = videos[0]
    duration = number(stream.get('duration'), number(payload.get('format', {}).get('duration')))
    width, height = int(stream.get('width') or 0), int(stream.get('height') or 0)
    if not (width and height and duration > 0):
        raise ValueError('Could not determine the video size and duration.')
    # These are the survey's rules, the ones the training proxies were built with.
    sizes = [(int(v.get('width') or 0), int(v.get('height') or 0)) for v in videos]
    kind = 'flat'
    if len(sizes) >= 2 and sizes[0] == sizes[1] and width > 2.5 * height:
        kind = 'max_dual'        # GoPro MAX: one lens per track, front first
    elif width == 2 * height and width >= 2000:
        kind = 'equirect'        # stitched 360
    elif width / height > 2.2:
        kind = 'equirect'
    elif height > width:
        kind = 'portrait'
    start = number(stream.get('start_time'))
    # A phone held upright stores a sideways picture and a note to turn it; ffmpeg turns it before any filter.
    turned = next((number(item.get('rotation')) for item in stream.get('side_data_list', []) if 'rotation' in item),
                  number(stream.get('tags', {}).get('rotate')))
    return {'duration_sec': duration, 'width': width, 'height': height, 'kind': kind,
            'pix_fmt': stream.get('pix_fmt') or '',
            'video_stream_count': len(videos), 'audio_stream_count': len(audio),
            'audio_offset_sec': number(audio[0].get('start_time')) - start if audio else None,
            'rotation': int(turned)}


def refine_360_kind(source: Path, ffmpeg: str, media: dict) -> dict:
    """Two-to-one footage is either a stitched sphere or two raw fisheye circles; only the pixels say which.

    This never changes ``kind``: the front view must stay the one the models were trained on. It only records
    whether the frame holds two fisheye circles, which is what the back view has to unwrap.
    """
    if media['kind'] != 'equirect' or 'dual_fisheye' in media:
        return media
    when = max(0.0, min(media['duration_sec'] * .3, media['duration_sec'] - 1))
    command = [ffmpeg, '-hide_banner', '-nostdin', '-loglevel', 'error', '-ss', f'{when:.3f}', '-i', str(source),
               '-map', PRIMARY_VIDEO_MAP, '-frames:v', '1', '-vf', 'scale=64:32,format=gray', '-f', 'rawvideo', 'pipe:1']
    result = subprocess.run(command, capture_output=True, creationflags=NO_WINDOW)
    if result.returncode or len(result.stdout) < 64 * 32:
        return media
    frame = np.frombuffer(result.stdout[:64 * 32], dtype=np.uint8).reshape(32, 64).astype(np.float32)
    halves = (frame[:, :32], frame[:, 32:])
    corners, centres = [], []
    for half in halves:
        corners += [half[:6, :6].mean(), half[:6, -6:].mean(), half[-6:, :6].mean(), half[-6:, -6:].mean()]
        centres.append(half[10:22, 10:22].mean())
    centre = float(np.mean(centres))
    return {**media, 'dual_fisheye': bool(centre > 20 and float(np.mean(corners)) < FISHEYE_CORNER_RATIO * centre)}


def has_back_view(media: dict) -> bool:
    """Only 360 footage has anything behind the camera to look at."""
    if media['kind'] == 'max_dual':
        return media['video_stream_count'] > 1
    return media['kind'] == 'equirect'


def resolve_view(source: Path, ffmpeg: str, media: dict, view: str) -> tuple[dict, str]:
    """The view the phases are read through for this file, and the media record that goes with it."""
    if view == 'back' and not has_back_view(media):
        view = 'front'   # an ordinary camera has nothing behind it to look at
    if view == 'back' and media['kind'] == 'equirect':
        media = refine_360_kind(source, ffmpeg, media)   # the back view needs to know which 360 layout this is
    return {**media, 'view': view}, view


def video_map(media: dict, view: str = 'front') -> str:
    """The MAX keeps one lens per track, so the back view is a different track, not a different crop."""
    if view == 'back' and media['kind'] == 'max_dual' and media['video_stream_count'] > 1:
        return '0:V:1'
    return PRIMARY_VIDEO_MAP


def view_filter(kind: str, width: int, height: int, view: str = 'front', fps: float = FPS, size: int = SIZE,
                dual_fisheye: bool = False, download: str = '') -> str:
    """The V4 view rules: 12 fps, fitted into 160x160 with black bars; front view for 360 footage.

    ``fps`` and ``size`` are for other callers (people counting) that need the same view at their own rate.
    ``download``: see ``downloaded``; it goes straight after the frames not wanted have been dropped.
    """
    fit = (f'scale={size}:{size}:force_original_aspect_ratio=decrease:flags=area,format=rgb24,'
           f'pad={size}:{size}:(ow-iw)/2:(oh-ih)/2:black')
    sample = f'fps={fps:g}{download}'
    if kind in {'flat', 'portrait'}:
        return f'{sample},{fit}'
    if kind == 'max_dual':
        crop_w = min(width, 2 * int(height * 16 / 9 / 2))
        return f'{sample},crop={crop_w}:{height}:{(width - crop_w) // 2}:0,{fit}'
    crop_w, crop_h = 2 * int(width * 160 / 360 / 2), 2 * int(height * 90 / 180 / 2)
    centre = f'crop={crop_w}:{crop_h}:{(width - crop_w) // 2}:{(height - crop_h) // 2}'
    if view == 'back':
        if dual_fisheye:
            # Two raw fisheye circles: unwrap the far lens, since there is no trained crop for that side.
            return (f'{sample},v360=dfisheye:flat:ih_fov=193:iv_fov=193:h_fov=120:v_fov=90:yaw=180:'
                    f'w={2 * (height // 2)}:h={2 * int(height * .75 / 2)},{fit}')
        # A stitched sphere: turn it 180 degrees, then take the window the front view uses.
        return f'{sample},v360=e:e:yaw=180,{centre},{fit}'
    return f'{sample},{centre},{fit}'


def people_frame_size(media: dict) -> tuple[int, int]:
    """Width and height of the frames the people counter is sent.

    An ordinary video keeps its own shape, shrunk so its longest side is PEOPLE_SIZE, so a person's share of the
    picture is their share of the frame. 360 footage is sent as the square view the phase model looks through.
    """
    if media['kind'] not in {'flat', 'portrait'}:
        return PEOPLE_SIZE, PEOPLE_SIZE
    width, height = media['width'], media['height']
    if abs(int(media.get('rotation') or 0)) % 180 == 90:
        width, height = height, width
    scale = min(1.0, PEOPLE_SIZE / max(width, height))
    return max(2, 2 * round(width * scale / 2)), max(2, 2 * round(height * scale / 2))


def people_filter(media: dict, view: str, fps: float, download: str = '') -> str:
    """Frames at the timeline's own times (0.5 s, then one every 1/fps), in the shape ``people_frame_size`` gives.

    Each is the first frame at or after its sample time. ffmpeg's fps filter is not used here: its frames sit half a
    sample early (measured against exact seeks on real footage), which shows people before they are in the timeline.
    """
    sample = f"select='gte(t,0.5+selected_n/{fps:g})'{download}"
    if media['kind'] in {'flat', 'portrait'}:
        width, height = people_frame_size(media)
        return f'{sample},scale={width}:{height}:flags=area,format=bgr24'
    look = view_filter(media['kind'], media['width'], media['height'], view, fps=fps, size=PEOPLE_SIZE,
                       dual_fisheye=bool(media.get('dual_fisheye')))
    return look.replace(f'fps={fps:g}', sample, 1).replace('format=rgb24', 'format=bgr24')


def downloaded(media: dict, hardware: tuple) -> str:
    """The filter steps that copy a frame from the graphics card to main memory, when frames are kept on the card.

    A 60 frames-a-second recording gives the phase model 12 of them a second and the people counter one. Left to
    itself ffmpeg copies every decoded frame back from the card and then throws most away; keeping them on the card
    until the unwanted ones are dropped copies a fifth as much, and what arrives is the same picture.
    """
    if '-hwaccel_output_format' not in hardware:
        return ''
    return f",hwdownload,format={DOWNLOADED[media['pix_fmt']]}"


@functools.lru_cache(maxsize=None)
def as_selected(ffmpeg: str) -> tuple:
    """The option that passes selected frames through untouched: its name changed in FFmpeg 5.1."""
    try:
        listing = subprocess.run([ffmpeg, '-hide_banner', '-h', 'long'], capture_output=True, text=True, timeout=60,
                                 encoding='utf-8', errors='replace', creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        listing = 'fps_mode'
    return ('-fps_mode', 'passthrough') if 'fps_mode' in listing else ('-vsync', 'passthrough')


def hardware_decode(ffmpeg: str, source: Path, media: dict, view: str = 'front', wanted: str = 'auto') -> tuple:
    """The ffmpeg input options that decode this file on the graphics hardware, or () to use the processor.

    Decoding 4K on the processor is the slow part of a video, and the picture that comes out is the same either way.
    Each method is tried on the first frames of the file itself; one that fails or complains is not used.
    """
    if wanted != 'auto':
        return ()
    for method in HARDWARE_METHODS.get(sys.platform, ('cuda',)):
        # On an NVIDIA card the frames stay on the card until the unwanted ones are dropped (see ``downloaded``).
        on_card = ON_CARD if method == 'cuda' and media.get('pix_fmt') in DOWNLOADED and not media.get('rotation') else []
        tries = [['-hwaccel', method, *on_card], ['-hwaccel', method]] if on_card else [['-hwaccel', method]]
        for options in tries:
            look = 'fps=2' + downloaded(media, tuple(options)) + ',scale=64:-2'
            command = [ffmpeg, '-hide_banner', '-nostdin', '-loglevel', 'error', *options, '-i', str(source),
                       '-map', video_map(media, view), '-vf', look, '-frames:v', '2', '-f', 'null', '-']
            try:
                result = subprocess.run(command, capture_output=True, timeout=60, creationflags=NO_WINDOW)
            except (OSError, subprocess.TimeoutExpired):
                continue
            if result.returncode == 0 and not result.stderr.strip():
                return tuple(options)
    return ()


def read_command(ffmpeg: str, source: Path, media: dict, view: str = 'front', proxy: Path | None = None,
                 people_fps: float | None = None, hardware: tuple = ()) -> list[str]:
    """One read of the source for everything that needs its picture.

    ``proxy``: write the phase model's proxy there. ``people_fps``: send frames for the people counter to standard
    output, raw BGR at ``people_frame_size``, that many a second. Either, or both from the same decode.
    """
    head = [ffmpeg, '-hide_banner', '-nostdin', '-loglevel', 'error', *hardware, '-i', str(source)]
    stream = video_map(media, view)
    download = downloaded(media, hardware)
    look = view_filter(media['kind'], media['width'], media['height'], view,
                       dual_fisheye=bool(media.get('dual_fisheye')), download=download)
    # Passed through as selected: no frames repeated or dropped to fill a constant rate.
    frames = ['-an', '-sn', '-dn', *as_selected(ffmpeg), '-f', 'rawvideo', '-pix_fmt', 'bgr24', 'pipe:1']
    if proxy is not None and people_fps:
        people = people_filter(media, view, people_fps, download)
        graph = f'[{stream}]split=2[a][b];[a]{look}[proxy];[b]{people}[people]'
        return head + ['-filter_complex', graph, '-map', '[proxy]', '-an', '-sn', *PROXY_ENCODING, '-y', str(proxy),
                       '-map', '[people]', *frames]
    if proxy is not None:
        return head + ['-map', stream, '-an', '-sn', '-vf', look, *PROXY_ENCODING, '-y', str(proxy)]
    return head + ['-map', stream, '-vf', people_filter(media, view, people_fps, download), *frames]


def build_proxy(ffmpeg: str, source: Path, media: dict, target: Path, view: str = 'front',
                hardware: tuple = ()) -> None:
    """A small 12 fps proxy. A hardware decode that fails part-way is done again on the processor."""
    temporary = target.with_suffix('.tmp.mp4')
    for attempt in ((hardware, ()) if hardware else ((),)):
        result = subprocess.run(read_command(ffmpeg, source, media, view, proxy=temporary, hardware=attempt),
                                capture_output=True, text=True, encoding='utf-8', errors='replace',
                                creationflags=NO_WINDOW)
        if not result.returncode:
            os.replace(temporary, target)
            return
        temporary.unlink(missing_ok=True)
    raise RuntimeError('Could not decode this video: ' + result.stderr[-600:])
