"""What happens when things go wrong, and what happens with 360 footage.

Every case here is one a user can hit: a cancelled run, a second window on the same folder, a file still copying, a
damaged settings file, a video that changes under the app, and a GoPro MAX recording with a lens per track.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.monitor import VideoProcessor, file_signature, load_ledger, save_ledger  # noqa: E402
from app.runtime import Cancelled, ProcessRunner  # noqa: E402
from app.settings import Settings, load_settings, state_directory  # noqa: E402
from conftest import clips_of, make_settings, process  # noqa: E402
from v3_poc.common import RunLock  # noqa: E402

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


@pytest.fixture
def spherical_video(ffmpeg, tmp_path):
    """A stand-in for a GoPro MAX .360: one wide video track per lens, in one file."""
    def build(name='jump.360', seconds=6):
        target = tmp_path / name
        strip = f'testsrc2=size=640x210:rate=12:duration={seconds}'
        result = subprocess.run([ffmpeg, '-hide_banner', '-nostdin', '-v', 'error', '-y',
                                 '-f', 'lavfi', '-i', strip, '-f', 'lavfi', '-i', strip,
                                 '-f', 'lavfi', '-i', f'sine=frequency=440:duration={seconds}',
                                 '-map', '0:v', '-map', '1:v', '-map', '2:a',
                                 '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                                 '-f', 'mp4', str(target)], capture_output=True, text=True, creationflags=NO_WINDOW)
        assert result.returncode == 0, result.stderr[-400:]
        return target
    return build


def video_tracks(path, ffprobe):
    out = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'V', '-show_entries', 'stream=index',
                          '-of', 'json', str(path)], capture_output=True, text=True, creationflags=NO_WINDOW)
    return len(json.loads(out.stdout).get('streams', []))


class TestInterruptions:
    def test_cancelling_leaves_no_half_written_outputs(self, folders, make_video, stub_classifier):
        inputs, clips = folders
        shutil.move(make_video('jump.mp4'), inputs / 'jump.mp4')
        settings = make_settings(inputs, clips, phase_classifier=stub_classifier())
        runner = ProcessRunner(log=lambda message: None)

        def cancel_during(stage, done=0, total=0):
            if stage == 'timeline':
                runner.cancelled.set()
        runner.progress = cancel_during

        with pytest.raises(Cancelled):
            VideoProcessor(settings, runner).process(inputs / 'jump.mp4', file_signature(inputs / 'jump.mp4'), None)
        assert not list((clips / 'timelines').glob('*.csv')), 'a cancelled video must not leave a timeline behind'

    def test_a_video_that_changes_mid_run_is_not_published(self, folders, make_video, stub_classifier):
        inputs, clips = folders
        shutil.move(make_video('jump.mp4'), inputs / 'jump.mp4')
        settings = make_settings(inputs, clips, phase_classifier=stub_classifier())
        runner = ProcessRunner(log=lambda message: None)
        source = inputs / 'jump.mp4'

        def grow_during(stage, done=0, total=0):
            if stage == 'timeline':
                with source.open('ab') as handle:
                    handle.write(b'\0' * 1024)
        runner.progress = grow_during

        with pytest.raises(RuntimeError, match='changed while processing'):
            VideoProcessor(settings, runner).process(source, file_signature(source), None)

    def test_a_second_window_cannot_process_the_same_folder(self, folders, make_video, stub_classifier, runner):
        inputs, clips = folders
        shutil.move(make_video('jump.mp4'), inputs / 'jump.mp4')
        settings = make_settings(inputs, clips, phase_classifier=stub_classifier())
        state = state_directory(settings)
        state.mkdir(parents=True, exist_ok=True)
        with RunLock(state, 'monitor.lock'):
            with pytest.raises(RuntimeError):
                with RunLock(state, 'monitor.lock'):
                    pass


class TestDamagedState:
    def test_a_corrupt_settings_file_is_refused_not_silently_replaced(self, tmp_path):
        path = tmp_path / 'settings.json'
        path.write_text('{ this is not json', encoding='utf-8')
        with pytest.raises(ValueError):
            load_settings(path)

    def test_a_settings_file_that_is_not_an_object_is_refused(self, tmp_path):
        path = tmp_path / 'settings.json'
        path.write_text('[1, 2, 3]', encoding='utf-8')
        with pytest.raises(ValueError, match='JSON object'):
            load_settings(path)

    def test_a_damaged_ledger_does_not_lose_the_clips(self, folders, make_video, stub_classifier, runner):
        inputs, clips = folders
        shutil.move(make_video('jump.mp4'), inputs / 'jump.mp4')
        settings = make_settings(inputs, clips, phase_classifier=stub_classifier())
        result = process(settings, inputs / 'jump.mp4', runner)
        made = clips_of(result)
        ledger_path = state_directory(settings) / 'ledger.json'
        ledger_path.write_text('{ broken', encoding='utf-8')
        with pytest.raises(ValueError):
            load_ledger(ledger_path)
        assert made[0].is_file(), 'the clips on disk are not affected by a damaged ledger'

    def test_the_ledger_survives_being_written_again(self, tmp_path):
        path = tmp_path / 'ledger.json'
        save_ledger(path, {'schema_version': 1, 'entries': {'a': {'status': 'success'}}})
        save_ledger(path, {'schema_version': 1, 'entries': {'a': {'status': 'success'}, 'b': {'status': 'failed'}}})
        assert set(load_ledger(path)['entries']) == {'a', 'b'}


class TestSphericalFootage:
    def test_two_lens_tracks_are_recognised(self, spherical_video, ffmpeg):
        from app.ffmpeg_tools import find_executable
        from cutter_v4.engine import has_back_view, probe, video_map
        media = probe(spherical_video(), find_executable('ffprobe'))
        assert media['kind'] == 'max_dual' and media['video_stream_count'] == 2
        assert has_back_view(media)
        assert video_map(media, 'front') != video_map(media, 'back'), 'each lens is a different track'

    def test_a_clip_keeps_every_lens_and_stays_a_360_file(self, folders, spherical_video, stub_classifier, runner):
        from app.ffmpeg_tools import find_executable
        inputs, clips = folders
        shutil.move(spherical_video(), inputs / 'jump.360')
        settings = make_settings(inputs, clips, phase_classifier=stub_classifier())
        result = process(settings, inputs / 'jump.360', runner)
        cut = clips_of(result)
        assert len(cut) == 1 and cut[0].suffix == '.360'
        assert video_tracks(cut[0], find_executable('ffprobe')) == 2, 'both lenses must survive the cut'

    def test_an_ordinary_video_has_no_back_view(self, folders, make_video):
        from app.ffmpeg_tools import find_executable
        from cutter_v4.engine import has_back_view, probe
        media = probe(make_video('flat.mp4'), find_executable('ffprobe'))
        assert media['kind'] == 'flat' and not has_back_view(media)


class TestPeopleFiltering:
    """People counting is stubbed here: this is about what the timeline and the profiles do with the numbers."""

    def fake_people(self, monkeypatch, counts):
        from app.people import PeopleSampler

        def sample(self, source, duration, settings, runner, media=None):
            return [{'time_sec': t + .5, 'person_count': counts[t], 'largest_person_area_percent': 10.0 * counts[t],
                     'total_person_area_percent': 25.0 * counts[t]} for t in range(len(counts))]
        monkeypatch.setattr(PeopleSampler, 'sample', sample)

    def test_seconds_without_people_are_not_kept(self, folders, make_video, stub_classifier, runner, monkeypatch):
        from app.settings import KeepProfile
        inputs, clips = folders
        shutil.move(make_video('jump.mp4'), inputs / 'jump.mp4')
        self.fake_people(monkeypatch, [0, 0, 1, 1, 0, 0])
        profile = KeepProfile(phases=frozenset({'exit', 'freefall'}), min_person_count=1,
                              min_total_area_percent=20.0, margin_before_seconds=0.0, margin_after_seconds=0.0)
        settings = Settings(input_folder=str(inputs), output_folder=str(clips),
                            csv_folder=str(clips / 'timelines'), people_enabled=True, profiles=(profile,),
                            phase_classifier=stub_classifier())
        result = process(settings, inputs / 'jump.mp4', runner)
        import csv as csv_module
        with open(result['csv_path'], encoding='utf-8', newline='') as handle:
            rows = list(csv_module.DictReader(handle))
        matched = [row['time_sec'] for row in rows if row['matched_profiles']]
        assert matched == ['2.500', '3.500'], 'only the seconds with someone in view, inside the kept phases'
