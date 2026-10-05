"""The changes made for speed, and the fault found on the way.

Frames not wanted are dropped while still on the graphics card; the classifier starts alongside the read of the
video instead of after it; and the sound analysis's compile cache is filled by one classifier at a time, because
several filling it together on a fresh install left it damaged for good.
"""
import os
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from cutter_v4 import media  # noqa: E402

FLAT = {'kind': 'flat', 'width': 3840, 'height': 2160, 'pix_fmt': 'yuv420p', 'video_stream_count': 1, 'rotation': 0}
ON_CARD = ('-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda')


class TestDroppingFramesOnTheCard:
    def test_frames_are_copied_back_only_after_the_unwanted_ones_are_dropped(self):
        command = media.read_command('ffmpeg', Path('jump.mp4'), FLAT, proxy=Path('proxy.mp4'), people_fps=1.0,
                                     hardware=ON_CARD)
        graph = command[command.index('-filter_complex') + 1]
        assert '[a]fps=12,hwdownload,format=nv12,scale=' in graph
        assert "selected_n/1)',hwdownload,format=nv12,scale=" in graph
        assert command[command.index('-i') - 2:command.index('-i')] == ['-hwaccel_output_format', 'cuda']

    def test_ten_bit_video_comes_back_in_its_own_format(self):
        ten_bit = {**FLAT, 'pix_fmt': 'yuv420p10le'}
        assert media.downloaded(ten_bit, ON_CARD) == ',hwdownload,format=p010le'

    def test_nothing_changes_without_the_card(self):
        for hardware in ((), ('-hwaccel', 'd3d11va'), ('-hwaccel', 'cuda')):
            assert media.downloaded(FLAT, hardware) == ''
            command = media.read_command('ffmpeg', Path('jump.mp4'), FLAT, proxy=Path('proxy.mp4'), hardware=hardware)
            assert 'hwdownload' not in ' '.join(command)

    def test_the_proxy_alone_and_people_alone_drop_first_too(self):
        proxy_only = media.read_command('ffmpeg', Path('jump.mp4'), FLAT, proxy=Path('proxy.mp4'), hardware=ON_CARD)
        assert proxy_only[proxy_only.index('-vf') + 1].startswith('fps=12,hwdownload,format=nv12,')
        people_only = media.read_command('ffmpeg', Path('jump.mp4'), FLAT, people_fps=2.0, hardware=ON_CARD)
        assert "selected_n/2)',hwdownload,format=nv12," in people_only[people_only.index('-vf') + 1]


class TestOlderFfmpeg:
    def listing(self, monkeypatch, text):
        class Result:
            stdout = text
        monkeypatch.setattr(media.subprocess, 'run', lambda *args, **kwargs: Result())
        media.as_selected.cache_clear()

    def test_the_option_is_called_by_the_name_this_ffmpeg_knows(self, monkeypatch):
        self.listing(monkeypatch, '-fps_mode  set framerate mode for matching video streams')
        assert media.as_selected('new-ffmpeg') == ('-fps_mode', 'passthrough')
        self.listing(monkeypatch, '-vsync  video sync method')
        assert media.as_selected('old-ffmpeg') == ('-vsync', 'passthrough')
        media.as_selected.cache_clear()

    def test_the_bundled_ffmpeg_reads_people_frames(self, make_video, ffmpeg):
        """End to end with the real program, whichever name it wants."""
        import subprocess
        from app.ffmpeg_tools import find_executable
        media.as_selected.cache_clear()
        source = make_video('jump.mp4', seconds=4)
        found = media.probe(source, find_executable('ffprobe'))
        frames = subprocess.run(media.read_command(ffmpeg, source, found, people_fps=1.0), capture_output=True)
        width, height = media.people_frame_size(found)
        assert frames.returncode == 0 and len(frames.stdout) == 4 * width * height * 3


@pytest.fixture
def engine(tmp_path, monkeypatch):
    from cutter_v4 import engine as module
    monkeypatch.setenv('NUMBA_CACHE_DIR', str(tmp_path / 'cache' / 'numba'))
    return module, tmp_path / 'cache' / 'numba'


class TestTheCompileCache:
    def test_a_cache_nobody_vouches_for_is_emptied_and_filled_once(self, engine):
        module, folder = engine
        folder.mkdir(parents=True)
        (folder / 'left_by_a_crash.nbi').write_bytes(b'damaged')
        with module.compile_cache():
            assert not (folder / 'left_by_a_crash.nbi').exists(), 'untrusted contents are thrown away first'
            (folder / 'compiled.nbi').write_bytes(b'good')
        assert module.compile_cache_marker(folder).is_file()
        with module.compile_cache():
            pass
        assert (folder / 'compiled.nbi').read_bytes() == b'good', 'once vouched for, it is only read'

    def test_only_one_fills_it_while_the_others_wait(self, engine):
        module, folder = engine
        inside, most, order = [0], [0], []
        guard = threading.Lock()

        def analyse(name):
            with module.compile_cache():
                filling = not module.compile_cache_marker(folder).is_file()
                with guard:
                    inside[0] += filling
                    most[0] = max(most[0], inside[0])
                    order.append((name, filling))
                time.sleep(.3 if filling else 0)
                with guard:
                    inside[0] -= filling
        threads = [threading.Thread(target=analyse, args=(n,)) for n in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert most[0] == 1 and sum(filling for _name, filling in order) == 1, order

    def test_a_filling_that_fails_leaves_no_marker_and_frees_the_next(self, engine):
        module, folder = engine
        with pytest.raises(RuntimeError):
            with module.compile_cache():
                raise RuntimeError('the sound could not be read')
        assert not module.compile_cache_marker(folder).is_file()
        with module.compile_cache():
            pass
        assert module.compile_cache_marker(folder).is_file()

    def test_a_lock_left_by_a_dead_process_is_taken_over(self, engine, monkeypatch):
        module, folder = engine
        lock = folder.with_name(folder.name + '.filling')
        lock.mkdir(parents=True)
        monkeypatch.setattr(module, 'CACHE_LOCK_STALE_SECONDS', 0)
        with module.compile_cache():
            pass
        assert module.compile_cache_marker(folder).is_file() and not lock.exists()


class TestWaitingForTheProxy:
    def test_it_returns_when_the_proxy_arrives(self, engine, tmp_path):
        module, _folder = engine
        proxy = tmp_path / 'proxy.mp4'
        threading.Timer(.3, lambda: proxy.write_bytes(b'video')).start()
        began = time.monotonic()
        module.wait_for(proxy)
        assert proxy.is_file() and time.monotonic() - began >= .25

    def test_it_stops_when_the_read_says_it_failed(self, engine, tmp_path):
        module, _folder = engine
        (tmp_path / 'proxy.failed').write_text('')
        with pytest.raises(RuntimeError, match='could not be read'):
            module.wait_for(tmp_path / 'proxy.mp4')


class TestClassifyingAlongsideTheRead:
    """A classifier that takes a prepared proxy is started when the read starts, not when it ends."""

    def classifier(self, events, tmp_path):
        from app.classifiers import CLASSIFIERS, Classifier
        from app.classifiers.contract import PhaseResult
        folder = tmp_path / 'run'

        def prepare(source, settings):
            folder.mkdir(exist_ok=True)
            return folder

        def predict(source, settings, runner, prepared=None):
            events.append('classifier started')
            deadline = time.monotonic() + 10
            while not (prepared / 'proxy.mp4').is_file():
                if (prepared / 'proxy.failed').exists():
                    events.append('classifier told to stop')
                    raise RuntimeError('nothing to classify')
                assert time.monotonic() < deadline
                time.sleep(.02)
            events.append('classifier saw the proxy')
            segments = [{'start_sec': 0.0, 'end_sec': 6.0, 'phase': 'freefall', 'mean_model_probability': .9}]
            return PhaseResult(segments, 6.0, None, None)
        CLASSIFIERS['alongside'] = Classifier('alongside', 'Alongside', 'test-1', predict, 0.0, prepare=prepare)

    def settings(self, folders):
        from app.settings import KeepProfile, Settings
        inputs, clips = folders
        return Settings(input_folder=str(inputs), output_folder=str(clips), csv_folder=str(clips / 'timelines'),
                        phase_classifier='alongside', cut_enabled=False,
                        profiles=(KeepProfile(min_person_count=0, min_total_area_percent=0.0),))

    def test_the_classifier_is_already_running_while_people_are_counted(self, folders, make_video, runner,
                                                                         monkeypatch, tmp_path):
        import shutil
        from app.classifiers import CLASSIFIERS
        from app.people import PeopleSampler
        from conftest import process
        events = []
        self.classifier(events, tmp_path)

        def sample(self, source, duration, settings, runner, media=None, proxy=None):
            time.sleep(.3)   # the read takes a while; the classifier should be up before it is done
            events.append('people counted')
            Path(proxy).write_bytes(b'proxy')
            return [{'time_sec': t + .5, 'person_count': 1, 'largest_person_area_percent': 30.0,
                     'total_person_area_percent': 30.0} for t in range(6)]
        monkeypatch.setattr(PeopleSampler, 'sample', sample)
        inputs, _clips = folders
        shutil.move(make_video('jump.mp4'), inputs / 'jump.mp4')
        try:
            result = process(self.settings(folders), inputs / 'jump.mp4', runner)
        finally:
            CLASSIFIERS.pop('alongside', None)
        assert events == ['classifier started', 'people counted', 'classifier saw the proxy']
        assert result['ran_model'] and Path(result['csv_path']).is_file()

    def test_a_read_that_fails_stops_the_classifier_and_reports_the_read(self, folders, make_video, runner,
                                                                         monkeypatch, tmp_path):
        import shutil
        from app.classifiers import CLASSIFIERS
        from app.people import PeopleSampler
        from conftest import process
        events = []
        self.classifier(events, tmp_path)

        def sample(self, source, duration, settings, runner, media=None, proxy=None):
            time.sleep(.2)
            raise ValueError('Could not read this video: damaged')
        monkeypatch.setattr(PeopleSampler, 'sample', sample)
        inputs, _clips = folders
        shutil.move(make_video('jump.mp4'), inputs / 'jump.mp4')
        try:
            with pytest.raises(ValueError, match='damaged'):
                process(self.settings(folders), inputs / 'jump.mp4', runner)
        finally:
            CLASSIFIERS.pop('alongside', None)
        assert events == ['classifier started', 'classifier told to stop']


class TestReusingThePeopleAlreadyCounted:
    """A changed profile changes what is kept, not who is in the picture: the video is not read again."""

    @pytest.fixture
    def counted(self, folders, make_video, stub_classifier, runner, monkeypatch):
        import shutil
        from app.monitor import file_signature, ledger_entry
        from app.people import PeopleSampler
        from app.settings import KeepProfile, Settings, settings_fingerprint
        from conftest import process
        reads = []

        def sample(self, source, duration, settings, runner, media=None, proxy=None):
            reads.append(settings.detection_confidence)
            return [{'time_sec': t + .5, 'person_count': t % 3, 'largest_person_area_percent': 10.0 * (t % 3),
                     'total_person_area_percent': 12.5 * (t % 3)} for t in range(6)]
        monkeypatch.setattr(PeopleSampler, 'sample', sample)
        inputs, clips = folders
        shutil.move(make_video('jump.mp4'), inputs / 'jump.mp4')
        settings = Settings(input_folder=str(inputs), output_folder=str(clips), csv_folder=str(clips / 'timelines'),
                            phase_classifier=stub_classifier(), profiles=(KeepProfile(),))
        source = inputs / 'jump.mp4'
        first = process(settings, source, runner)
        entry = ledger_entry(file_signature(source), settings_fingerprint(settings), 'success', **first)
        return settings, source, entry, reads, runner, first

    def test_a_changed_profile_recuts_without_reading_the_video(self, counted):
        from dataclasses import replace
        from app.settings import KeepProfile
        from conftest import process, timeline_rows
        settings, source, entry, reads, runner, first = counted
        before = [(r['person_count'], r['total_person_area_percent']) for r in timeline_rows(first)]
        said = []
        runner.log = said.append
        looser = replace(settings, profiles=(KeepProfile(min_total_area_percent=5.0),))
        again = process(looser, source, runner, previous=entry)
        assert len(reads) == 1, 'counted once, the first time only'
        assert [(r['person_count'], r['total_person_area_percent']) for r in timeline_rows(again)] == before
        assert any('Reusing the people already counted' in line for line in said)
        assert again['people_fingerprint'] == first['people_fingerprint'] != ''

    def test_anything_that_changes_who_is_found_counts_again(self, counted):
        from dataclasses import replace
        from conftest import process
        settings, source, entry, reads, runner, _first = counted
        process(replace(settings, detection_confidence=.2), source, runner, previous=entry)
        process(replace(settings, yolo_model=str(Path(settings.yolo_model).with_name('yolo26x.pt'))), source, runner,
                previous=entry)
        assert len(reads) == 3

    def test_a_record_from_before_this_existed_counts_once_more(self, counted):
        from conftest import process
        settings, source, entry, reads, runner, _first = counted
        older = {k: v for k, v in entry.items() if k != 'people_fingerprint'}
        process(settings, source, runner, previous=older)
        assert len(reads) == 2

    def test_a_timeline_that_was_changed_by_hand_is_not_trusted(self, counted):
        from conftest import process
        settings, source, entry, reads, runner, first = counted
        path = Path(first['csv_path'])
        lines = path.read_text(encoding='utf-8').splitlines()
        path.write_text('\n'.join(lines[:-2]) + '\n', encoding='utf-8')   # two rows gone
        process(settings, source, runner, previous=entry)
        assert len(reads) == 2
