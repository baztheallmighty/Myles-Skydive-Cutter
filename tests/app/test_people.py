"""Counting people in a video: how its frames are read, and what happens at the very end of one.

The detector itself is not the subject here, so it is stubbed. What matters is that reading frames behaves: one read
of the source feeds the people counter and the phase model's proxy, a sample that lands in the last fraction of a
second must not throw away a whole jump, and a video that really cannot be read must still fail loudly.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.people import PeopleSampler  # noqa: E402
from app.timeline import canonical_grid  # noqa: E402
from conftest import make_settings  # noqa: E402


@pytest.fixture
def sampler(monkeypatch, tmp_path):
    """A PeopleSampler whose detector is a stub: every frame holds one person filling a tenth of it."""
    import app.detection as detection
    one_person = [detection.DetectionBox(confidence=0.9, x1=0, y1=0, x2=30, y2=40, frame_width=160, frame_height=120)]
    seen = []

    def detect(model, frame, confidence, ids):
        seen.append(frame.shape)
        return one_person
    monkeypatch.setattr(detection, 'load_yolo_model', lambda path: object())
    monkeypatch.setattr(detection, 'find_person_class_ids', lambda model: [0])
    monkeypatch.setattr(detection, 'detect_people', detect)
    weights = tmp_path / 'yolo11n.pt'
    weights.write_bytes(b'stub')
    people = PeopleSampler()
    people.seen = seen   # the (height, width, 3) of every frame the detector was shown
    return people, str(weights)


def frame_checksums(ffmpeg, video):
    """One checksum per decoded frame, so two files can be compared picture by picture."""
    result = subprocess.run([ffmpeg, '-v', 'error', '-i', str(video), '-f', 'framemd5', '-'],
                            capture_output=True, text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert result.returncode == 0, result.stderr
    return [line.rsplit(',', 1)[-1].strip() for line in result.stdout.splitlines() if not line.startswith('#')]


class TestOneReadOfTheSource:
    def test_every_sample_on_the_grid_is_counted(self, folders, make_video, runner, sampler):
        people, weights = sampler
        inputs, clips = folders
        source = make_video('jump.mp4', seconds=6, rate=12)
        rows = people.sample(source, 6.0, make_settings(inputs, clips, yolo_model=weights), runner)
        assert [row['time_sec'] for row in rows] == canonical_grid(6.0, 1.0)
        assert all(row['person_count'] == 1 for row in rows)

    def test_the_detector_sees_the_videos_own_shape(self, folders, make_video, runner, sampler):
        """A person's share of the frame must be their share of the picture, so no black bars are added."""
        people, weights = sampler
        inputs, clips = folders
        settings = make_settings(inputs, clips, yolo_model=weights)
        people.sample(make_video('wide.mp4', seconds=3, size='1280x720'), 3.0, settings, runner)
        assert set(people.seen) == {(360, 640, 3)}, 'shrunk to 640 on the long side'
        people.seen.clear()
        people.sample(make_video('small.mp4', seconds=3, size='160x120'), 3.0, settings, runner)
        assert set(people.seen) == {(120, 160, 3)}, 'never enlarged'

    def test_the_same_read_writes_the_phase_models_proxy(self, folders, make_video, runner, sampler, ffmpeg, tmp_path):
        """The proxy made alongside the people frames is, frame for frame, the one the engine builds on its own."""
        from app.ffmpeg_tools import find_executable
        from cutter_v4.media import build_proxy, probe
        people, weights = sampler
        inputs, clips = folders
        source = make_video('jump.mp4', seconds=6, size='320x240', rate=24)
        together, alone = tmp_path / 'together.mp4', tmp_path / 'alone.mp4'
        people.sample(source, 6.0, make_settings(inputs, clips, yolo_model=weights), runner, proxy=together)
        build_proxy(ffmpeg, source, probe(source, find_executable('ffprobe')), alone)
        assert together.is_file() and not together.with_suffix('.tmp.mp4').exists()
        checksums = frame_checksums(ffmpeg, together)
        assert len(checksums) == 72 and checksums == frame_checksums(ffmpeg, alone)

    def test_a_graphics_card_that_cannot_decode_falls_back_to_the_processor(self, folders, make_video, runner,
                                                                            sampler, ffmpeg, tmp_path):
        from app.ffmpeg_tools import find_executable
        from cutter_v4.media import probe
        people, weights = sampler
        inputs, clips = folders
        source = make_video('jump.mp4', seconds=4)
        said = []
        runner.log = said.append
        rows = people.sample_view(source, 4.0, make_settings(inputs, clips, yolo_model=weights), runner,
                                  probe(source, find_executable('ffprobe')), ffmpeg, proxy=tmp_path / 'proxy.mp4',
                                  hardware=('-hwaccel', 'no_such_decoder'))
        assert len(rows) == 4 and all(row['person_count'] == 1 for row in rows)
        assert (tmp_path / 'proxy.mp4').is_file()
        assert any('on the processor instead' in line for line in said)

    def test_a_cancelled_read_leaves_no_proxy(self, folders, make_video, runner, sampler, tmp_path):
        from app.runtime import Cancelled
        people, weights = sampler
        inputs, clips = folders
        source = make_video('jump.mp4', seconds=6)
        runner.cancelled.set()
        with pytest.raises(Cancelled):
            people.sample(source, 6.0, make_settings(inputs, clips, yolo_model=weights), runner,
                          proxy=tmp_path / 'proxy.mp4')
        assert list(tmp_path.glob('proxy*')) == []


class TestTheEndOfAVideo:
    """A video whose length lands just past a sample: the last sample is inside the video but after the last frame."""

    def test_a_sample_past_the_last_frame_uses_the_frame_before_it(self, folders, make_video, runner, sampler):
        """The real case: a 257.507 s GoPro is sampled at 257.5, inside the video but after every frame."""
        people, weights = sampler
        inputs, clips = folders
        source = make_video('GH011124.MP4', seconds=5.51, rate=12)
        duration = 5.51
        grid = canonical_grid(duration, 1.0)
        assert grid[-1] == 5.5, 'the last sample sits in the final hundredths of this video'

        rows = people.sample(source, duration, make_settings(inputs, clips, yolo_model=weights), runner)

        assert [row['time_sec'] for row in rows] == grid, 'every sample is still reported'
        assert all(row['person_count'] == 1 for row in rows), 'including the last, counted from the frame before it'

    def test_a_read_that_stops_short_leaves_the_tail_uncounted(self, folders, make_video, runner, sampler):
        """The file says it is longer than its picture: the missing seconds are nobody, not a failed video."""
        people, weights = sampler
        inputs, clips = folders
        source = make_video('short.mp4', seconds=4, rate=12)

        rows = people.sample(source, 8.0, make_settings(inputs, clips, yolo_model=weights), runner)

        assert [row['time_sec'] for row in rows] == canonical_grid(8.0, 1.0)
        assert [row['person_count'] for row in rows[:4]] == [1, 1, 1, 1]
        assert rows[-1]['person_count'] == 0 and rows[-1]['total_person_area_percent'] == 0.0

    def test_a_file_that_is_not_a_video_still_fails(self, folders, runner, sampler):
        people, weights = sampler
        inputs, clips = folders
        source = inputs / 'not-a-video.mp4'
        source.write_bytes(b'nonsense')
        settings = make_settings(inputs, clips, yolo_model=weights)
        with pytest.raises((ValueError, RuntimeError), match='Could not read'):
            people.sample(source, 6.0, settings, runner)
