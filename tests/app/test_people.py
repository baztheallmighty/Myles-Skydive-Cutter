"""Counting people in a video: mainly, what happens at the very end of one.

The detector itself is not the subject here, so it is stubbed. What matters is that reading frames behaves: a sample
that lands in the last fraction of a second must not throw away a whole jump, while a video that really cannot be
read must still fail loudly.
"""
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
    monkeypatch.setattr(detection, 'load_yolo_model', lambda path: object())
    monkeypatch.setattr(detection, 'find_person_class_ids', lambda model: [0])
    monkeypatch.setattr(detection, 'detect_people', lambda model, frame, confidence, ids: one_person)
    weights = tmp_path / 'yolo11n.pt'
    weights.write_bytes(b'stub')
    return PeopleSampler(), str(weights)


class TestTheEndOfAVideo:
    """A video whose length lands just past a sample: the last sample is inside the video but after the last frame."""

    def blind_after(self, monkeypatch, cv2, seconds):
        """Make OpenCV read nothing from this point on, as it does once the position is past the last frame."""
        real_read = cv2.VideoCapture.read

        def read(capture):
            if capture.get(cv2.CAP_PROP_POS_MSEC) >= seconds * 1000:
                return False, None
            return real_read(capture)

        monkeypatch.setattr(cv2.VideoCapture, 'read', read)

    def test_a_sample_past_the_last_frame_uses_the_frame_before_it(self, folders, make_video, runner, sampler,
                                                                   monkeypatch):
        """The real case: a 257.507 s GoPro is sampled at 257.5, inside the video but after every frame."""
        import cv2
        people, weights = sampler
        inputs, clips = folders
        source = make_video('GH011124.MP4', seconds=5.51, rate=12)
        duration = 5.51
        grid = canonical_grid(duration, 1.0)
        assert grid[-1] == 5.5, 'the last sample sits in the final hundredths of this video'
        self.blind_after(monkeypatch, cv2, duration - 0.02)

        rows = people.sample_view(source, duration, make_settings(inputs, clips, yolo_model=weights), runner)

        assert [row['time_sec'] for row in rows] == grid, 'every sample is still reported'
        assert all(row['person_count'] == 1 for row in rows), 'including the last, counted from the frame before it'

    def test_an_unreadable_last_sample_counts_as_nobody(self, folders, make_video, runner, sampler, monkeypatch):
        """When even the frame before it cannot be read, the tail is uncounted rather than fatal."""
        import cv2
        people, weights = sampler
        inputs, clips = folders
        source = make_video('GH011124.MP4', seconds=5.51, rate=12)
        self.blind_after(monkeypatch, cv2, 5.3)

        rows = people.sample_view(source, 5.51, make_settings(inputs, clips, yolo_model=weights), runner)

        assert [row['time_sec'] for row in rows] == canonical_grid(5.51, 1.0)
        assert rows[-1]['person_count'] == 0 and rows[-1]['total_person_area_percent'] == 0.0
        assert all(row['person_count'] == 1 for row in rows[:-1]), 'the rest of the video is counted as before'

    def test_a_video_that_cannot_be_read_at_all_still_fails(self, folders, make_video, runner, sampler, monkeypatch):
        import cv2
        people, weights = sampler
        inputs, clips = folders
        source = make_video('broken.mp4', seconds=6, rate=12)
        monkeypatch.setattr(cv2.VideoCapture, 'read', lambda capture: (False, None))
        settings = make_settings(inputs, clips, yolo_model=weights)
        with pytest.raises(ValueError, match='Cannot decode person sample'):
            people.sample_view(source, 6.0, settings, runner)

    def test_a_file_that_is_not_a_video_still_fails(self, folders, runner, sampler):
        people, weights = sampler
        inputs, clips = folders
        source = inputs / 'not-a-video.mp4'
        source.write_bytes(b'nonsense')
        settings = make_settings(inputs, clips, yolo_model=weights)
        with pytest.raises(ValueError, match='Cannot open video'):
            people.sample_view(source, 6.0, settings, runner)
