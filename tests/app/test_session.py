"""The run loop, with no window: what gets queued, what is remembered, and what happens when the world misbehaves.

The window only drives a ProcessingSession (timer, thread, progress bars), so everything that decides what is done
can be tested here in seconds: a network share, a full disk, a path longer than Windows allows, a drive unplugged
half way through.
"""
import errno
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.monitor import load_ledger  # noqa: E402
from app.session import ProcessingSession  # noqa: E402
from conftest import make_settings  # noqa: E402

WINDOWS = os.name == 'nt'


def library(folders, make_video, *names):
    inputs, _clips = folders
    for name in names:
        target = inputs / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(make_video(Path(name).name), target)
    return [inputs / name for name in names]


class TestARun:
    def test_everything_once_then_nothing(self, folders, make_video, stub_classifier, runner):
        inputs, clips = folders
        library(folders, make_video, 'a/GX010001.MP4', 'b/GX010002.MP4')
        settings = make_settings(inputs, clips, phase_classifier=stub_classifier())
        session = ProcessingSession(settings, existing_only=True, runner=runner)
        try:
            outcomes = session.run()
            assert [status for _, status, _ in outcomes] == ['success', 'success']
            assert session.finished()
        finally:
            session.close()
        again = ProcessingSession(settings, existing_only=True, runner=runner)
        try:
            assert again.run() == [], 'a second run over an unchanged library does nothing'
        finally:
            again.close()

    def test_one_destination_one_session(self, folders, stub_classifier, runner):
        inputs, clips = folders
        settings = make_settings(inputs, clips, phase_classifier=stub_classifier())
        first = ProcessingSession(settings, runner=runner)
        try:
            with pytest.raises(RuntimeError, match='Another process'):
                ProcessingSession(settings, runner=runner)
        finally:
            first.close()
        ProcessingSession(settings, runner=runner).close()   # free again once the first has closed

    def test_a_file_still_being_copied_waits(self, folders, make_video, stub_classifier, runner):
        inputs, clips = folders
        [source] = library(folders, make_video, 'GX010001.MP4')
        session = ProcessingSession(make_settings(inputs, clips, phase_classifier=stub_classifier()), runner=runner)
        try:
            assert session.scan() == [], 'one look is not enough'
            with source.open('ab') as stream:
                stream.write(b'more')   # still arriving
            assert session.scan() == []
            assert [path for path, _ in session.scan()] == [source], 'two identical looks make it ready'
        finally:
            session.close()


class TestAFullDisk:
    def test_a_clip_that_cannot_be_written_fails_that_video_only(self, folders, make_video, stub_classifier,
                                                                 runner, monkeypatch):
        import app.cutting as cutting
        inputs, clips = folders
        first, second = library(folders, make_video, 'GX010001.MP4', 'GX010002.MP4')
        real_replace = os.replace

        def replace(source, target):
            if 'GX010001' in str(target) and str(target).endswith('.mp4'):
                raise OSError(errno.ENOSPC, 'No space left on device')
            return real_replace(source, target)

        monkeypatch.setattr(cutting.os, 'replace', replace)
        session = ProcessingSession(make_settings(inputs, clips, phase_classifier=stub_classifier()),
                                    existing_only=True, runner=runner)
        try:
            outcomes = {path.name: (status, result) for path, status, result in session.run()}
        finally:
            session.close()
        assert outcomes['GX010001.MP4'][0] == 'failed' and 'No space' in outcomes['GX010001.MP4'][1]['error']
        assert outcomes['GX010002.MP4'][0] == 'success', 'the next video still runs'
        leftovers = [p for p in clips.rglob('*') if p.is_dir() and p.name.startswith('.clips-')]
        assert not leftovers, 'no half-written staging folders are left behind'

    def test_a_ledger_that_cannot_be_saved_keeps_the_old_one_whole(self, folders, make_video, stub_classifier,
                                                                   runner, monkeypatch):
        import v3_poc.common as common
        inputs, clips = folders
        library(folders, make_video, 'GX010001.MP4', 'GX010002.MP4')
        settings = make_settings(inputs, clips, phase_classifier=stub_classifier())
        session = ProcessingSession(settings, existing_only=True, runner=runner)
        try:
            session.scan()
            session.scan()
            job = session.next_job()
            session.record(job[0], job[1], *session.process(job))
            saved = session.ledger_path.read_text(encoding='utf-8')

            def full(*_args):
                raise OSError(errno.ENOSPC, 'No space left on device')

            monkeypatch.setattr(common.os, 'replace', full)
            job = session.next_job()
            status, result = session.process(job)
            with pytest.raises(OSError, match='No space'):
                session.record(job[0], job[1], status, result)
        finally:
            session.close()
        assert session.ledger_path.read_text(encoding='utf-8') == saved, 'the ledger on disk is the last good one'
        assert len(json.loads(saved)['entries']) == 1


class TestADriveThatGoesAway:
    def test_a_video_that_vanishes_mid_run_is_retried_next_session(self, folders, make_video, stub_classifier,
                                                                    runner):
        inputs, clips = folders
        [source] = library(folders, make_video, 'card/GX010001.MP4')
        settings = make_settings(inputs, clips, phase_classifier=stub_classifier())
        session = ProcessingSession(settings, existing_only=True, runner=runner)
        try:
            session.scan()
            session.scan()
            job = session.next_job()
            unplugged = inputs.parent / 'unplugged'
            inputs.rename(unplugged)                      # the drive disappears
            status, result = session.process(job)
            assert session.record(job[0], job[1], status, result) == 'failed'
            unplugged.rename(inputs)                      # and comes back
        finally:
            session.close()
        entries = load_ledger(clips / '_state' / 'ledger.json')['entries']
        assert [entry['status'] for entry in entries.values()] == ['failed']
        retry = ProcessingSession(settings, existing_only=True, runner=runner)
        try:
            assert [status for _, status, _ in retry.run()] == ['success']
        finally:
            retry.close()


@pytest.mark.skipif(not WINDOWS, reason='Windows network paths')
class TestANetworkShare:
    def unc(self, path):
        text = str(Path(path).resolve())
        return Path(f'\\\\localhost\\{text[0]}${text[2:]}')

    def test_a_library_on_a_share_is_processed(self, folders, make_video, stub_classifier, runner):
        inputs, clips = folders
        library(folders, make_video, 'GX010001.MP4')
        share = self.unc(inputs)
        if not share.is_dir():
            pytest.skip('this account cannot open the administrative share')
        settings = make_settings(share, self.unc(clips), phase_classifier=stub_classifier())
        session = ProcessingSession(settings, existing_only=True, runner=runner)
        try:
            outcomes = session.run()
        finally:
            session.close()
        assert [status for _, status, _ in outcomes] == ['success']
        assert list(clips.rglob('*.mp4')), 'the clips were written over the share'


@pytest.mark.skipif(not WINDOWS, reason='the 260-character limit is Windows only')
class TestAVeryLongPath:
    def long_folder(self, root):
        folder = Path(root)
        while len(str(folder)) < 270:
            folder = folder / ('Boogie footage from the big way camp ' + str(len(folder.parts)))
        return folder

    def test_one_unreadable_path_does_not_stop_the_library(self, folders, make_video, stub_classifier, runner):
        """Long paths are off by default on Windows. A video buried too deep must not stop the rest being found."""
        inputs, clips = folders
        library(folders, make_video, 'GX010001.MP4')
        deep = self.long_folder(inputs)
        os.makedirs('\\\\?\\' + str(deep))
        shutil.copyfile(make_video('deep.MP4'), '\\\\?\\' + str(deep / 'GX010002.MP4'))
        session = ProcessingSession(make_settings(inputs, clips, phase_classifier=stub_classifier()),
                                    existing_only=True, runner=runner)
        try:
            outcomes = session.run()
        finally:
            session.close()
        statuses = {path.name: status for path, status, _ in outcomes}
        assert statuses.get('GX010001.MP4') == 'success', 'the ordinary video is still processed'
        assert session.unreadable, 'the one it cannot read is reported, not silently left out'
        where, reason = session.unreadable[0]
        assert 'Boogie footage' in where and '260 characters' in reason
