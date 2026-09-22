"""Shared fixtures for the app's own tests: tiny real videos, a stub classifier, and a quiet runner.

Nothing here needs a GPU or a trained model. The point is to exercise the process the app follows, so the model is
replaced by a stub that returns whatever phases a test asks for.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.classifiers import CLASSIFIERS, Classifier  # noqa: E402
from app.classifiers.contract import PhaseResult  # noqa: E402
from app.ffmpeg_tools import find_executable  # noqa: E402
from app.runtime import ProcessRunner  # noqa: E402

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


@pytest.fixture(scope='session')
def ffmpeg():
    return find_executable('ffmpeg')


@pytest.fixture
def make_video(ffmpeg, tmp_path):
    """A real, tiny video: colour bars with a tone, so ffprobe, cutting and the timeline all have something true."""
    def build(name='jump.mp4', seconds=6, size='160x120', rate=12, audio=True):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        argv = [ffmpeg, '-hide_banner', '-nostdin', '-v', 'error', '-y',
                '-f', 'lavfi', '-i', f'testsrc2=size={size}:rate={rate}:duration={seconds}']
        if audio:
            argv += ['-f', 'lavfi', '-i', f'sine=frequency=440:duration={seconds}']
        argv += ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-g', '12']
        if audio:
            argv += ['-c:a', 'aac', '-shortest']
        argv += [str(target)]
        result = subprocess.run(argv, capture_output=True, text=True, creationflags=NO_WINDOW)
        assert result.returncode == 0, result.stderr[-400:]
        return target
    return build


@pytest.fixture
def stub_classifier():
    """Register a classifier that returns fixed phases, so the process can run without a model.

    ``use(...)`` returns the identifier to put in Settings(phase_classifier=...).
    """
    added = []

    def use(segments=None, duration=6.0, identifier='stub', fail_with=None, agreement=None):
        def predict(source, settings, runner):
            runner.report_progress('phases', 1, 1)
            if fail_with:
                raise fail_with
            phases = segments if segments is not None else [
                {'start_sec': 0.0, 'end_sec': 2.0, 'phase': 'climbing_out', 'mean_model_probability': .9},
                {'start_sec': 2.0, 'end_sec': 4.0, 'phase': 'exit', 'mean_model_probability': .9},
                {'start_sec': 4.0, 'end_sec': duration, 'phase': 'freefall', 'mean_model_probability': .9}]
            # A real classifier leaves a run directory behind, and the reuse and review paths look for it.
            from app.settings import state_directory
            run = state_directory(settings) / 'classifier-runs' / f'{Path(source).stem}_{len(added)}'
            run.mkdir(parents=True, exist_ok=True)
            (run / 'result.json').write_text(json.dumps({
                'engine_revision': 'stub-1', 'source_video': str(source), 'duration_sec': duration,
                'media': {'kind': 'flat', 'width': 160, 'height': 120, 'video_stream_count': 1,
                          'audio_stream_count': 1, 'duration_sec': duration, 'view': 'front'},
                'tracks': {'final': phases, 'v4': phases, 'audio': [], 'motion': []},
                'agreement': agreement or [], 'audio_status': 'ok'}), encoding='utf-8')
            return PhaseResult(phases, duration, run, agreement)
        CLASSIFIERS[identifier] = Classifier(identifier, 'Stub', 'stub-1', predict, 0.0)
        added.append(identifier)
        return identifier

    yield use
    for identifier in added:
        CLASSIFIERS.pop(identifier, None)


@pytest.fixture
def runner():
    return ProcessRunner(log=lambda message: None)


@pytest.fixture
def folders(tmp_path):
    """The three folders a run needs, already created."""
    inputs, clips = tmp_path / 'input', tmp_path / 'clips'
    inputs.mkdir(parents=True, exist_ok=True)
    clips.mkdir(parents=True, exist_ok=True)
    return inputs, clips

def make_settings(inputs, clips, **extra):
    """A run that keeps the usual phases, with people counting off so no detector is needed."""
    from app.settings import KeepProfile, Settings
    profile = KeepProfile(phases=frozenset({'exit', 'freefall'}), min_person_count=0, min_total_area_percent=0.0,
                          margin_before_seconds=0.0, margin_after_seconds=0.0)
    return Settings(input_folder=str(inputs), output_folder=str(clips), csv_folder=str(clips / 'timelines'),
                    people_enabled=False, profiles=(profile,), **extra)


def process(settings, source, runner, previous=None):
    """One video through the real processor."""
    from app.monitor import VideoProcessor, file_signature
    return VideoProcessor(settings, runner).process(Path(source), file_signature(source), previous)


def clips_of(result):
    """The clips a run produced, read from its manifests."""
    import csv
    paths = []
    for manifest in result['manifests']:
        with open(manifest, encoding='utf-8', newline='') as handle:
            paths += [Path(row['clip_path']) for row in csv.DictReader(handle)]
    return paths


def timeline_rows(result):
    import csv
    with open(result['csv_path'], encoding='utf-8', newline='') as handle:
        return list(csv.DictReader(handle))
