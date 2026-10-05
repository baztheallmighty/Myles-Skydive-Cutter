"""Several videos side by side: the same results, one ledger, never more at once than asked for.

The processor is replaced by one that only waits, so what is measured is the scheduling: how many run together, that
each is recorded once, that one failure or a cancel does not disturb the others.
"""
import os
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from app.monitor import load_ledger  # noqa: E402
from app.session import ProcessingSession  # noqa: E402
from app.settings import state_directory  # noqa: E402
from conftest import make_settings  # noqa: E402
from test_window import window  # noqa: E402,F401 - the window fixture


class Counter:
    """How many videos were in progress at the same moment, at most."""

    def __init__(self):
        self.lock = threading.Lock()
        self.now = self.most = 0
        self.seen = []

    def __enter__(self):
        with self.lock:
            self.now += 1
            self.most = max(self.most, self.now)

    def __exit__(self, *_):
        with self.lock:
            self.now -= 1


def waiting_processor(counter, seconds=.25, fail=()):
    class Processor:
        def __init__(self, settings, runner):
            self.settings, self.runner = settings, runner

        def process(self, source, signature=None, previous=None, moved_from=()):
            with counter:
                counter.seen.append(source.name)
                self.runner.report_progress('phases', 0, 0)
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    self.runner.check_cancelled()
                    time.sleep(.01)
                if source.name in fail:
                    raise RuntimeError('this one cannot be read')
                return {'source_video': str(source), 'duration_sec': 6.0}
    return Processor


def fill(inputs, count):
    for index in range(count):
        (inputs / f'GX01000{index}.MP4').write_bytes(b'video ' * 100)


class TestTheSession:
    def test_never_more_at_once_than_asked_and_every_video_recorded_once(self, folders):
        inputs, clips = folders
        fill(inputs, 6)
        counter = Counter()
        settings = make_settings(inputs, clips, parallel_videos=3)
        session = ProcessingSession(settings, existing_only=True, processor_factory=waiting_processor(counter))
        try:
            outcomes = session.run()
        finally:
            session.close()
        assert counter.most == 3
        assert sorted(counter.seen) == sorted(p.name for p in inputs.iterdir()), 'each exactly once'
        assert [status for _, status, _ in outcomes] == ['success'] * 6
        entries = load_ledger(state_directory(settings) / 'ledger.json')['entries']
        assert len(entries) == 6 and all(entry['status'] == 'success' for entry in entries.values())

    def test_one_at_a_time_is_still_one_at_a_time(self, folders):
        inputs, clips = folders
        fill(inputs, 3)
        counter = Counter()
        session = ProcessingSession(make_settings(inputs, clips), existing_only=True,
                                    processor_factory=waiting_processor(counter, seconds=.05))
        try:
            session.run()
        finally:
            session.close()
        assert counter.most == 1

    def test_a_video_that_fails_does_not_stop_the_ones_beside_it(self, folders):
        inputs, clips = folders
        fill(inputs, 4)
        counter = Counter()
        session = ProcessingSession(make_settings(inputs, clips, parallel_videos=2), existing_only=True,
                                    processor_factory=waiting_processor(counter, fail={'GX010001.MP4'}))
        try:
            outcomes = session.run()
        finally:
            session.close()
        statuses = {source.name: status for source, status, _ in outcomes}
        assert statuses.pop('GX010001.MP4') == 'failed' and set(statuses.values()) == {'success'}

    def test_each_place_has_its_own_processor_and_runner(self, folders):
        inputs, clips = folders
        session = ProcessingSession(make_settings(inputs, clips), processor_factory=waiting_processor(Counter()))
        try:
            first, third = session.processor_for(0), session.processor_for(2)
            assert first is session.processor and third is session.processor_for(2)
            assert len({id(p.runner) for p in session.processors}) == 3, 'so progress and cancel never cross'
        finally:
            session.close()


def run_window(built, application, counter, seconds=20):
    """Drive a run to its end without waiting for the window's own five-second look at the folder."""
    built.cuda = True
    built.start_session(True)
    assert built.active, built.warning.text()
    deadline = time.monotonic() + seconds
    rows = 0
    while built.active or built.workers:
        application.processEvents()
        built.poll()
        rows = max(rows, sum(bar.isVisible() for bar in built.video_bars))
        assert time.monotonic() < deadline, built.log.toPlainText()
        time.sleep(.01)
    application.processEvents()
    return rows


class TestTheWindow:
    def choose(self, built, count):
        built.parallel.setCurrentIndex(built.parallel.findData(count))

    def test_two_at_once_shows_two_bars_and_finishes_everything(self, window, monkeypatch):  # noqa: F811
        from app.ui import main_window as window_module
        built, application, _path = window
        counter = Counter()
        monkeypatch.setattr(window_module, 'VideoProcessor', waiting_processor(counter))
        fill(Path(built.folder_edits['input_folder'].text()), 4)
        self.choose(built, 2)

        rows = run_window(built, application, counter)

        assert counter.most == 2 and len(counter.seen) == 4
        assert rows == 2, 'a second bar appeared while two were running'
        assert sum(bar.isVisible() for bar in built.video_bars) == 1, 'and went away afterwards'
        assert built.queue_progress.finished == 4 and built.queue_progress.failed == 0
        assert built.session.ledger['entries'] and len(built.session.ledger['entries']) == 4

    def test_one_at_a_time_is_unchanged(self, window, monkeypatch):  # noqa: F811
        from app.ui import main_window as window_module
        built, application, _path = window
        counter = Counter()
        monkeypatch.setattr(window_module, 'VideoProcessor', waiting_processor(counter, seconds=.05))
        fill(Path(built.folder_edits['input_folder'].text()), 3)

        rows = run_window(built, application, counter)

        assert counter.most == 1 and rows == 1 and built.queue_progress.finished == 3

    def test_automatic_adds_videos_only_while_the_machine_has_room(self, window, monkeypatch):  # noqa: F811
        from app import load
        from app.ui import main_window as window_module
        built, application, _path = window
        counter = Counter()
        monkeypatch.setattr(window_module, 'VideoProcessor', waiting_processor(counter))

        class RoomForThree:
            reason = 'the test says there is room'

            def __init__(self, **_):
                pass

            def may_start(self, running):
                return running < 3

            def started(self):
                pass
        monkeypatch.setattr(load, 'Pacer', RoomForThree)
        fill(Path(built.folder_edits['input_folder'].text()), 6)
        self.choose(built, 0)

        run_window(built, application, counter)

        assert counter.most == 3 and built.queue_progress.finished == 6
        assert 'Starting another video alongside' in built.log.toPlainText()

    def test_cancelling_stops_every_video_in_progress(self, window, monkeypatch):  # noqa: F811
        from PySide6.QtWidgets import QMessageBox
        from app.ui import main_window as window_module
        built, application, _path = window
        counter = Counter()
        monkeypatch.setattr(window_module, 'VideoProcessor', waiting_processor(counter, seconds=30))
        monkeypatch.setattr(QMessageBox, 'question', lambda *args, **kwargs: QMessageBox.Yes)
        fill(Path(built.folder_edits['input_folder'].text()), 4)
        self.choose(built, 2)
        built.cuda = True
        built.start_session(True)
        deadline = time.monotonic() + 10
        while len(built.workers) < 2:
            application.processEvents()
            built.poll()
            assert time.monotonic() < deadline
        built.stop_session()   # stop taking new videos
        assert 'videos in progress' in built.stop_button.text()
        built.stop_session()   # and cancel the two in progress
        while built.workers:
            application.processEvents()
            assert time.monotonic() < deadline + 10
            time.sleep(.01)
        application.processEvents()
        assert counter.most == 2 and len(counter.seen) == 2, 'the two waiting were never started'
        assert built.queue_progress.cancelled == 2 and not built.active
