"""Stream-copy clip planning and atomic manifest publication."""
import os
import csv
import tempfile
from pathlib import Path
from app.ffmpeg_tools import find_executable
from app.profiles import profile_spans
from app.timeline import write_atomic_csv
from app.outputs import (clip_destination, clip_manifest, clip_suffix, owned_clip, reserve_identity,
                         source_folder, thumbnail_path)
from app.runtime import Cancelled
from app.spans import clip_filename, dominant_phase, slugify
from v3_poc.common import key

MANIFEST_FIELDS = ['clip_index', 'clip_path', 'source_video', 'profile',
                   'start_sec', 'end_sec', 'duration_sec', 'dominant_phase',
                   'source_id', 'source_sha256', 'output_layout', 'source_folder']


def validate_manifest_owner(rows, source, identity=None):
    if any(key(row['source_video']) != key(source) for row in rows):
        raise ValueError(f'Clip manifest belongs to another source with the same stem: {source.stem}')
    if identity and any(r.get('source_id') != identity.identifier or
                        r.get('source_sha256') != identity.content_sha256 for r in rows):
        raise ValueError('Clip manifest belongs to a different version of this video.')


def ffmpeg_argv(ffmpeg, source, start, end, destination):
    if not 0 <= start < end:
        raise ValueError('Clip bounds must satisfy 0 <= start < end.')
    # A 360 file keeps one lens per track: copying only the first would leave half the sphere behind.
    spherical = bool(clip_suffix(source))
    # Every lens, but only the ordinary audio track: a MAX also carries ambisonic audio that MP4 cannot hold.
    streams = ['-map', '0:v', '-map', '0:a:0?'] if spherical else ['-map', '0:v:0', '-map', '0:a:0?']
    # .360 is an MP4 in disguise, and ffmpeg cannot guess a muxer from that name.
    container = ['-f', 'mp4'] if spherical else []
    return [str(ffmpeg), '-hide_banner', '-nostdin', '-y', '-ss', f'{start:.3f}',
            '-i', str(source), '-t', f'{end - start:.3f}', *streams, *container,
            '-c', 'copy', '-avoid_negative_ts', 'make_zero', str(destination)]


def plan_clips(source, rows, duration, profile, settings, identity):
    clips = []
    folder = source_folder(source, settings.input_folder) if settings.output_layout == 'mirror' else ''
    for index, (start, end) in enumerate(profile_spans(profile, rows, duration,
            settings.phases_enabled, settings.people_enabled), 1):
        phase = dominant_phase(rows, start, end) if settings.phases_enabled else 'all'
        path = clip_destination(settings.output_folder, settings.output_layout, identity.output_name,
                                profile.name, index, start, end, phase, folder=folder, source=source)
        clips.append(dict(clip_index=index, clip_path=str(path), source_video=str(source),
                          profile=profile.name, start_sec=start, end_sec=end,
                          duration_sec=end - start, dominant_phase=phase,
                          source_id=identity.identifier, source_sha256=identity.content_sha256,
                          output_layout=settings.output_layout, source_folder=folder))
    return clip_manifest(settings.output_folder, settings.output_layout, identity.output_name, profile.name), clips


def cut_profiles(source, rows, duration, settings, runner, identity):
    reserve_identity(settings.output_folder, identity)
    manifests = []
    plans = [(profile, *plan_clips(source, rows, duration, profile, settings, identity))
             for profile in settings.profiles if profile.enabled]
    total = sum(len(clips) for _, _, clips in plans)
    completed = 0
    runner.report_progress('cutting', 0, max(total, 1))
    for profile, manifest, clips in plans:
        old = []
        if manifest.exists():
            with manifest.open(encoding='utf-8', newline='') as stream:
                old = list(csv.DictReader(stream))
            validate_manifest_owner(old, source, identity)
        owned = {Path(r['clip_path']).resolve() for r in old if owned_clip(
            r, settings.output_folder, settings.output_layout, identity, profile.name)}
        for clip in clips:
            candidate = Path(clip['clip_path'])
            if candidate.exists() and candidate.resolve() not in owned:
                raise FileExistsError(f'A file already exists at the clip destination: {candidate}')
        # Stage the complete new set before replacing any previously published clips.
        manifest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.clips-', dir=manifest.parent) as staging:
            for clip in clips:
                runner.check_cancelled()
                final = Path(clip['clip_path'])
                temporary = Path(staging) / final.name
                runner.log(f'Cutting {profile.name}: {final.name}')
                runner.run(ffmpeg_argv(find_executable('ffmpeg'), source, clip['start_sec'],
                                      clip['end_sec'], temporary), echo=False)
                completed += 1
                runner.report_progress('cutting', completed, max(total, 1))
            runner.check_cancelled()
            for clip in clips:
                final = Path(clip['clip_path'])
                final.parent.mkdir(parents=True, exist_ok=True)
                os.replace(Path(staging) / final.name, final)
            write_atomic_csv(manifest, clips, MANIFEST_FIELDS)
            # Publish the new manifest before removing stale owned clips, so a locked
            # manifest cannot leave the old manifest pointing at deleted files.
            if old:
                retained = {Path(c['clip_path']).resolve() for c in clips}
                for row in old:
                    previous = Path(row['clip_path']).resolve()
                    if previous in owned and previous not in retained:
                        previous.unlink(missing_ok=True)
                        if settings.output_layout == 'per_clip':
                            try:
                                previous.parent.rmdir()  # Remove only an empty generated clip folder.
                            except OSError:
                                pass
        manifests.append(str(manifest))
        write_thumbnails(source, clips, settings, runner, identity, profile.name)
    runner.report_progress('cutting', 1, 1)
    return manifests


def write_thumbnails(source, clips, settings, runner, identity, profile_name):
    """A small still from the middle of each clip. Best effort: a failed still never fails the video."""
    from app.settings import state_directory
    state = state_directory(settings)
    wanted = set()
    for clip in clips:
        target = thumbnail_path(state, identity.output_name, profile_name, clip['clip_index'])
        wanted.add(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        middle = (float(clip['start_sec']) + float(clip['end_sec'])) / 2
        try:
            runner.run([str(find_executable('ffmpeg')), '-hide_banner', '-nostdin', '-v', 'error', '-y',
                        '-ss', f'{middle:.3f}', '-i', str(source), '-map', '0:V:0', '-frames:v', '1',
                        '-vf', 'scale=240:-2', '-q:v', '4', str(target)], timeout=60, echo=False)
        except Cancelled:
            raise
        except Exception:  # noqa: BLE001
            target.unlink(missing_ok=True)
    folder = thumbnail_path(state, identity.output_name, profile_name, 1).parent
    prefix = thumbnail_path(state, identity.output_name, profile_name, 1).name.rsplit('_', 1)[0] + '_'
    for stale in folder.glob(prefix + '*.jpg') if folder.is_dir() else ():
        if stale not in wanted:
            stale.unlink(missing_ok=True)
