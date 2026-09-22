"""A library that moved: a renamed folder, a drive back as another letter, the clip folder copied elsewhere.

What must survive is the expensive and the irreplaceable: the model's answer, your reviewed labels, and the clip names
you may already have shared. What must not happen is a second copy of every clip.
"""
import csv
import shutil
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.monitor import (REVIEWED_LABELS, VideoProcessor, file_signature, hidden_entry, ledger_entry,  # noqa: E402
                         needs_processing, same_signature, scan_folder)
from app.relocate import matching_move, moved_candidates, rebase_entries, rebased  # noqa: E402
from app.settings import accepted_fingerprints, state_directory  # noqa: E402
from cutter_v4.review import ReviewStore, review_directory  # noqa: E402
from v3_poc.common import annotation_fingerprint, key, read_csv, write_csv, write_json  # noqa: E402
from conftest import clips_of, make_settings, process  # noqa: E402

HOUR = 3600 * 1_000_000_000


def processed(folders, make_video, stub_classifier, runner, **extra):
    inputs, clips = folders
    (inputs / 'day1').mkdir(exist_ok=True)
    shutil.move(make_video('GX010001.MP4'), inputs / 'day1' / 'GX010001.MP4')
    source = inputs / 'day1' / 'GX010001.MP4'
    settings = make_settings(inputs, clips, phase_classifier=stub_classifier(), **extra)
    result = process(settings, source, runner)
    entries = {key(source): ledger_entry(file_signature(source), accepted_fingerprints(settings)[0], 'success',
                                         **result)}
    return settings, source, result, entries


def mark_reviewed(settings, source, sha256, segments):
    run = review_directory(state_directory(settings))
    run.mkdir(parents=True, exist_ok=True)
    rows = [{'source_video': str(source), 'start_sec': start, 'end_sec': end, 'phase': phase,
             'keep': True, 'notes': 'mine'} for start, end, phase in segments]
    write_csv(run / 'review.csv', rows)
    write_json(run / 'review_state.json', {key(source): {'fingerprint': annotation_fingerprint(read_csv(
        run / 'review.csv')), 'source_sha256': sha256}})


class TestAMovedVideo:
    def test_keeps_its_phases_clip_names_and_clips(self, folders, make_video, stub_classifier, runner):
        settings, source, first, entries = processed(folders, make_video, stub_classifier, runner)
        made = clips_of(first)
        moved = source.parent.parent / 'Boogie 2026' / source.name
        moved.parent.mkdir()
        source.parent.rename(moved.parent / '_tmp')
        (moved.parent / '_tmp' / source.name).rename(moved)

        candidates = moved_candidates(entries, moved)
        assert [old for old, _ in candidates] == [key(source)]
        result = VideoProcessor(settings, runner).process(moved, file_signature(moved), None, moved_from=candidates)

        assert result['relocated_from'] == key(source)
        assert result['ran_model'] is False, 'a moved file has the same answer; the model must not run again'
        assert result['output_name'] == first['output_name'], 'clip names you may have shared stay the same'
        assert clips_of(result) == made and all(path.is_file() for path in made)
        clip_files = [p for p in Path(settings.output_folder).rglob('*.mp4') if '_state' not in p.parts]
        assert len(clip_files) == len(made), 'no second copy of any clip'
        with open(result['manifests'][0], encoding='utf-8', newline='') as stream:
            assert {row['source_video'] for row in csv.DictReader(stream)} == {str(moved)}

    def test_brings_its_reviewed_labels(self, folders, make_video, stub_classifier, runner):
        settings, source, first, entries = processed(folders, make_video, stub_classifier, runner)
        mark_reviewed(settings, source, first['source_sha256'], [(0.0, 6.0, 'freefall')])
        moved = source.parent.parent / 'elsewhere' / source.name
        moved.parent.mkdir()
        shutil.move(source, moved)

        result = VideoProcessor(settings, runner).process(moved, file_signature(moved), None,
                                                          moved_from=moved_candidates(entries, moved))
        assert result['labels'] == REVIEWED_LABELS, 'your labels moved with the video'
        store = ReviewStore(state_directory(settings))
        assert store.segments_for(moved, first['source_sha256'], 6.0)
        assert store.fingerprint(moved).startswith('reviewed:')
        backups = list(review_directory(state_directory(settings)).glob('*.before-move-*'))
        assert backups, 'the review files were backed up before they were changed'

    def test_waits_while_the_review_is_open(self, folders, make_video, stub_classifier, runner):
        from app.relocate import ReviewBusy
        from v3_poc.common import RunLock
        settings, source, first, entries = processed(folders, make_video, stub_classifier, runner)
        mark_reviewed(settings, source, first['source_sha256'], [(0.0, 6.0, 'freefall')])
        moved = source.parent.parent / 'elsewhere' / source.name
        moved.parent.mkdir()
        shutil.move(source, moved)
        review = review_directory(state_directory(settings))
        before = (review / 'review_state.json').read_text(encoding='utf-8')
        with RunLock(review):
            with pytest.raises(ReviewBusy):
                VideoProcessor(settings, runner).process(moved, file_signature(moved), None,
                                                         moved_from=moved_candidates(entries, moved))
        assert (review / 'review_state.json').read_text(encoding='utf-8') == before, 'nothing changed'

    def test_a_copy_beside_the_original_is_a_new_video(self, folders, make_video, stub_classifier, runner):
        settings, source, first, entries = processed(folders, make_video, stub_classifier, runner)
        copy = source.parent.parent / 'copy' / source.name
        copy.parent.mkdir()
        shutil.copy2(source, copy)
        assert moved_candidates(entries, copy) == [], 'the original still exists, so this is not a move'

    def test_different_content_with_the_same_name_is_a_new_video(self, folders, make_video, stub_classifier, runner):
        settings, source, first, entries = processed(folders, make_video, stub_classifier, runner)
        source.unlink()
        other = make_video('other/GX010001.MP4', seconds=7)
        candidates = moved_candidates(entries, other)
        assert candidates and matching_move(candidates, 'f' * 64) is None
        result = VideoProcessor(settings, runner).process(other, file_signature(other), None, moved_from=candidates)
        assert 'relocated_from' not in result and result['ran_model'] is True


class TestAMovedClipFolder:
    def test_recorded_paths_follow_the_folder(self, folders, make_video, stub_classifier, runner, tmp_path):
        settings, source, first, entries = processed(folders, make_video, stub_classifier, runner)
        new_clips = tmp_path / 'new drive' / 'clips'
        new_clips.parent.mkdir()
        shutil.move(settings.output_folder, new_clips)
        moved = replace(settings, output_folder=str(new_clips), csv_folder=str(new_clips / 'timelines'))

        rebase_entries(entries, state_directory(moved), moved.csv_folder)
        entry = entries[key(source)]
        assert Path(entry['run_directory']).is_dir()
        assert all(Path(m).is_file() for m in entry['manifests'])
        assert Path(entry['csv_path']).is_file()
        assert not needs_processing(entry, file_signature(source), accepted_fingerprints(moved)), \
            'moving the clip folder reprocesses nothing'

    def test_windows_paths_read_on_a_mac(self):
        assert rebased(r'E:\Clips\_state\classifier-runs\x', '_state', '/Volumes/Clips') == \
            Path('/Volumes/Clips/_state/classifier-runs/x')
        assert rebased('/nothing/here', '_state', '/x') is None


class TestTimestamps:
    @pytest.mark.parametrize('shift', [HOUR, -HOUR, 2 * HOUR, HOUR // 2, 14 * HOUR, HOUR + 500_000_000])
    def test_a_daylight_saving_or_time_zone_shift_is_the_same_file(self, shift):
        assert same_signature((100, 10 * HOUR), (100, 10 * HOUR + shift))

    @pytest.mark.parametrize('recorded, current', [
        ((100, 10 * HOUR), (100, 10 * HOUR + 1)),           # any other change of time
        ((100, 10 * HOUR), (100, 10 * HOUR + HOUR // 3)),   # twenty minutes is not a zone
        ((100, 10 * HOUR), (101, 10 * HOUR + HOUR)),        # a different size is always a change
        ((100, 10 * HOUR), (100, 10 * HOUR + 15 * HOUR)),   # beyond any time zone
        ((100, None), (100, 10 * HOUR)),
    ])
    def test_anything_else_is_a_change(self, recorded, current):
        assert not same_signature(recorded, current)


class TestScanning:
    def test_mac_sidecars_and_system_folders_are_not_footage(self, folders):
        inputs, clips = folders
        for relative in ('GX010001.MP4', '._GX010001.MP4', '.Trashes/501/old.MP4', '$RECYCLE.BIN/x.mp4',
                         'System Volume Information/y.mp4', 'day/.hidden.mp4', 'day/GX020001.MP4'):
            path = inputs / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'x')
        found = {Path(path).name for path, _ in scan_folder(make_settings(inputs, clips)).values()}
        assert found == {'GX010001.MP4', 'GX020001.MP4'}

    def test_hidden_entry(self):
        assert hidden_entry(('._a.mp4',)) and hidden_entry(('System Volume Information', 'a.mp4'))
        assert not hidden_entry(('Boogie', 'GX010001.MP4'))


def test_keys_ignore_unicode_normalisation(tmp_path):
    composed, decomposed = 'Empuriabrava caf\u00e9', 'Empuriabrava cafe\u0301'
    assert key(tmp_path / composed) == key(tmp_path / decomposed)
