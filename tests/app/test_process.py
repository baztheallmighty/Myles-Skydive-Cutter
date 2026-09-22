"""The whole process, with a stub model: scan, classify, write the timeline, cut, remember, re-cut, exclude.

These are the paths a user walks. They run in seconds because the model is stubbed and the videos are six seconds of
colour bars, so nothing here depends on a GPU or on the corpus.
"""
import csv
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.monitor import (EXCLUDED_LABELS, MODEL_LABELS, REVIEWED_LABELS, VideoProcessor, file_signature,
                         ledger_entry, load_ledger, needs_processing, save_ledger, scan_folder, stable_candidates)
from app.settings import KeepProfile, Settings, settings_fingerprint, state_directory
from v3_poc.common import key
from conftest import clips_of, make_settings, process, timeline_rows


class TestOneVideo:
    def test_timeline_clips_and_ledger(self, folders, make_video, stub_classifier, runner):
        inputs, clips = folders
        source = make_video('jump.mp4')
        shutil.move(source, inputs / 'jump.mp4')
        settings = make_settings(inputs, clips, phase_classifier=stub_classifier())
        result = process(settings, inputs / 'jump.mp4', runner)

        rows = timeline_rows(result)
        assert len(rows) == 6 and rows[0]['phase'] == 'climbing_out'
        assert [row['phase'] for row in rows][-1] == 'freefall'
        assert result['labels'] == MODEL_LABELS and result['ran_model'] is True

        cut = clips_of(result)
        assert len(cut) == 1 and cut[0].is_file()
        assert cut[0].suffix == '.mp4'

    def test_original_is_never_touched(self, folders, make_video, stub_classifier, runner):
        inputs, clips = folders
        source = make_video('jump.mp4')
        shutil.move(source, inputs / 'jump.mp4')
        before = file_signature(inputs / 'jump.mp4')
        settings = make_settings(inputs, clips, phase_classifier=stub_classifier())
        process(settings, inputs / 'jump.mp4', runner)
        assert file_signature(inputs / 'jump.mp4') == before

    def test_csv_only_writes_no_clips(self, folders, make_video, stub_classifier, runner):
        inputs, clips = folders
        source = make_video('jump.mp4')
        shutil.move(source, inputs / 'jump.mp4')
        settings = make_settings(inputs, clips, cut_enabled=False, phase_classifier=stub_classifier())
        result = process(settings, inputs / 'jump.mp4', runner)
        assert result['manifests'] == []
        assert Path(result['csv_path']).is_file()

    def test_a_failing_model_leaves_no_outputs(self, folders, make_video, stub_classifier, runner):
        inputs, clips = folders
        source = make_video('jump.mp4')
        shutil.move(source, inputs / 'jump.mp4')
        settings = make_settings(inputs, clips,
                                 phase_classifier=stub_classifier(fail_with=RuntimeError('model exploded')))
        with pytest.raises(RuntimeError):
            process(settings, inputs / 'jump.mp4', runner)
        assert not list((clips / 'timelines').glob('*.csv'))


class TestLayouts:
    @pytest.mark.parametrize('layout', ['per_video', 'per_clip', 'flat', 'mirror'])
    def test_every_layout_produces_a_playable_clip(self, folders, make_video, stub_classifier, runner, layout):
        inputs, clips = folders
        (inputs / 'day1').mkdir(exist_ok=True)
        source = make_video('jump.mp4')
        shutil.move(source, inputs / 'day1' / 'jump.mp4')
        settings = make_settings(inputs, clips, output_layout=layout, phase_classifier=stub_classifier())
        result = process(settings, inputs / 'day1' / 'jump.mp4', runner)
        cut = clips_of(result)
        assert len(cut) == 1 and cut[0].is_file() and cut[0].stat().st_size > 0
        if layout == 'mirror':
            assert cut[0].parent.name == 'day1'
        if layout == 'flat':
            assert cut[0].parent == clips

    def test_same_name_on_two_cards_stays_separate(self, folders, make_video, stub_classifier, runner):
        inputs, clips = folders
        for card in ('cardA', 'cardB'):
            (inputs / card).mkdir(exist_ok=True)
            source = make_video(f'{card}.mp4')
            shutil.move(source, inputs / card / 'GOPR0001.MP4')
        settings = make_settings(inputs, clips, phase_classifier=stub_classifier())
        first = process(settings, inputs / 'cardA' / 'GOPR0001.MP4', runner)
        second = process(settings, inputs / 'cardB' / 'GOPR0001.MP4', runner)
        assert first['output_name'] != second['output_name']
        assert set(clips_of(first)).isdisjoint(clips_of(second))
        assert first['csv_path'] != second['csv_path']


class TestRepeatRuns:
    def test_unchanged_video_is_not_processed_again(self, folders, make_video, stub_classifier, runner):
        inputs, clips = folders
        source = make_video('jump.mp4')
        shutil.move(source, inputs / 'jump.mp4')
        settings = make_settings(inputs, clips, phase_classifier=stub_classifier())
        signature = file_signature(inputs / 'jump.mp4')
        entry = ledger_entry(signature, settings_fingerprint(settings), 'success',
                             **process(settings, inputs / 'jump.mp4', runner))
        assert not needs_processing(entry, signature, settings_fingerprint(settings))

    def test_changing_a_setting_asks_for_another_run(self, folders, make_video, stub_classifier, runner):
        inputs, clips = folders
        source = make_video('jump.mp4')
        shutil.move(source, inputs / 'jump.mp4')
        identifier = stub_classifier()
        settings = make_settings(inputs, clips, phase_classifier=identifier)
        signature = file_signature(inputs / 'jump.mp4')
        entry = ledger_entry(signature, settings_fingerprint(settings), 'success',
                             **process(settings, inputs / 'jump.mp4', runner))
        wider = make_settings(inputs, clips, phase_classifier=identifier, output_layout='flat')
        assert needs_processing(entry, signature, settings_fingerprint(wider))

    def test_a_preference_does_not(self, folders, make_video, stub_classifier, runner):
        inputs, clips = folders
        source = make_video('jump.mp4')
        shutil.move(source, inputs / 'jump.mp4')
        identifier = stub_classifier()
        settings = make_settings(inputs, clips, phase_classifier=identifier)
        signature = file_signature(inputs / 'jump.mp4')
        entry = ledger_entry(signature, settings_fingerprint(settings), 'success',
                             **process(settings, inputs / 'jump.mp4', runner))
        same = make_settings(inputs, clips, phase_classifier=identifier, keep_watching=True, window_geometry='abc')
        assert not needs_processing(entry, signature, settings_fingerprint(same))


class TestReviewing:
    """Your labels replace the model for that exact file, and excluding it removes the clips."""

    def save_review(self, settings, source, sha256, segments):
        from v3_poc.common import annotation_fingerprint, key, write_json
        from cutter_v4.review import review_directory
        run = review_directory(state_directory(settings))
        run.mkdir(parents=True, exist_ok=True)
        rows = [{'source_video': str(source), 'start_sec': start, 'end_sec': end, 'phase': phase,
                 'keep': 'true', 'notes': 'mine'} for start, end, phase in segments]
        write_json(run / 'review_state.json',
                   {key(source): {'fingerprint': annotation_fingerprint(rows), 'source_sha256': sha256,
                                  'rows': rows}})

    def exclude(self, settings, source):
        from v3_poc.common import key, write_json
        from cutter_v4.review import review_directory
        run = review_directory(state_directory(settings))
        run.mkdir(parents=True, exist_ok=True)
        write_json(run / 'review_exclusions.json', {key(source): {'reason': 'not skydiving'}})

    def test_reviewed_labels_are_cut_instead_of_the_model(self, folders, make_video, stub_classifier, runner):
        inputs, clips = folders
        source = make_video('jump.mp4')
        shutil.move(source, inputs / 'jump.mp4')
        source = inputs / 'jump.mp4'
        settings = make_settings(inputs, clips, phase_classifier=stub_classifier())
        first = process(settings, source, runner)
        model_size = clips_of(first)[0].stat().st_size   # the re-cut replaces this file, so measure it now

        # The whole video is freefall according to me, so the clip should cover all six seconds.
        self.save_review(settings, source, first['source_sha256'], [(0.0, 6.0, 'freefall')])
        second = process(settings, source, runner, previous=dict(first, status='success'))
        assert second['labels'] == REVIEWED_LABELS
        assert second['ran_model'] is False, 'reviewing must not run the model again'
        rows = timeline_rows(second)
        assert {row['phase'] for row in rows} == {'freefall'}
        reviewed_clips = clips_of(second)
        assert len(reviewed_clips) == 1
        assert reviewed_clips[0].stat().st_size > model_size, 'a longer kept span should give a longer clip'

    def test_excluding_a_video_removes_its_clips(self, folders, make_video, stub_classifier, runner):
        inputs, clips = folders
        source = make_video('jump.mp4')
        shutil.move(source, inputs / 'jump.mp4')
        source = inputs / 'jump.mp4'
        settings = make_settings(inputs, clips, phase_classifier=stub_classifier())
        first = process(settings, source, runner)
        made = clips_of(first)          # the manifest is rewritten by the re-cut, so remember the paths now
        assert made and made[0].is_file()

        self.exclude(settings, source)
        second = process(settings, source, runner, previous=dict(first, status='success'))
        assert second['labels'] == EXCLUDED_LABELS
        assert clips_of(second) == []
        assert not made[0].is_file(), 'the clip it made before should be gone'

    def test_a_review_of_a_different_copy_is_ignored(self, folders, make_video, stub_classifier, runner):
        inputs, clips = folders
        source = make_video('jump.mp4')
        shutil.move(source, inputs / 'jump.mp4')
        source = inputs / 'jump.mp4'
        settings = make_settings(inputs, clips, phase_classifier=stub_classifier())
        first = process(settings, source, runner)
        self.save_review(settings, source, 'a' * 64, [(0.0, 6.0, 'freefall')])   # labels for other footage
        second = process(settings, source, runner, previous=dict(first, status='success'))
        assert second['labels'] == MODEL_LABELS


class TestScanning:
    def test_only_video_files_inside_the_input_folder(self, folders, make_video, stub_classifier):
        inputs, clips = folders
        source = make_video('jump.mp4')
        shutil.move(source, inputs / 'jump.mp4')
        (inputs / 'notes.txt').write_text('not a video', encoding='utf-8')
        (clips / 'already.mp4').write_bytes(b'x')
        settings = make_settings(inputs, clips, phase_classifier=stub_classifier())
        found = scan_folder(settings)
        assert [Path(path).name for path, _signature in found.values()] == ['jump.mp4']

    def test_a_file_still_copying_waits(self, folders, make_video, stub_classifier):
        inputs, clips = folders
        source = make_video('jump.mp4')
        shutil.move(source, inputs / 'jump.mp4')
        settings = make_settings(inputs, clips, phase_classifier=stub_classifier())
        first = scan_folder(settings)
        growing = {k: (path, (size + 1000, mtime)) for k, (path, (size, mtime)) in first.items()}
        assert stable_candidates({k: s for k, (_p, s) in first.items()},
                                 {k: s for k, (_p, s) in growing.items()}, {}, 'fingerprint') == []
        steady = {k: s for k, (_p, s) in first.items()}
        assert stable_candidates(steady, steady, {}, 'fingerprint') == sorted(steady)
