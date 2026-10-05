"""The people join: a gap between two matches is filled while enough people are still in view.

For footage where the camera drifts off the group: several people are in shot but fill a few percent of the picture,
then the group comes back. The ordinary join works on time alone; this one asks who is still there.
"""
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.profiles import profile_spans  # noqa: E402
from app.settings import KeepProfile, Settings, load_settings, save_settings, settings_fingerprint, validate_profile  # noqa: E402
from cutter_v4.review import judge  # noqa: E402

B_GRADE = KeepProfile(name='B grade', phases=frozenset({'exit', 'freefall'}), min_person_count=1,
                      min_total_area_percent=10.0, margin_before_seconds=0.0, margin_after_seconds=0.0,
                      max_gap_seconds=2.0, people_gap_seconds=10.0, people_gap_count=3)


def looks(*seconds, every=2.0):
    """Timeline rows from (phase, people found, percent of the picture), one look every ``every`` seconds."""
    return [{'time_sec': f'{.5 + index * every:.3f}', 'phase': phase, 'person_count': str(count),
             'total_person_area_percent': str(area)} for index, (phase, count, area) in enumerate(seconds)]


# DJI_20260929085301_0041_D: a good exit, the camera drifts off the group and glances away, then freefall.
DRIFT = looks(('exit', 2, 149.6), ('exit', 2, 27.0), ('exit', 3, 4.5), ('exit', 5, 2.5), ('exit', 0, 0.0),
              ('freefall', 3, 6.3), ('freefall', 5, 11.0), ('freefall', 3, 11.2))


class TestTheRealCase:
    def test_the_drift_is_bridged_into_one_clip(self):
        assert profile_spans(B_GRADE, DRIFT, 16.0) == [(0.5, 16.0)]
        assert judge(B_GRADE, DRIFT, 16.0) == ['kept', 'kept', 'joined', 'joined', 'joined', 'joined', 'kept', 'kept']

    def test_without_the_people_join_it_stays_two_clips(self):
        assert len(profile_spans(replace(B_GRADE, people_gap_seconds=0.0), DRIFT, 16.0)) == 2

    def test_the_ordinary_join_alone_needs_the_whole_eight_seconds(self):
        time_only = replace(B_GRADE, people_gap_seconds=0.0)
        assert len(profile_spans(replace(time_only, max_gap_seconds=6.0), DRIFT, 16.0)) == 2
        assert len(profile_spans(replace(time_only, max_gap_seconds=8.0), DRIFT, 16.0)) == 1


class TestTheRule:
    def test_a_gap_longer_than_the_setting_is_left(self):
        assert len(profile_spans(replace(B_GRADE, people_gap_seconds=6.0), DRIFT, 16.0)) == 2

    def test_too_few_people_in_the_gap_is_not_still_in_view(self):
        """Needing four: the looks with three people are 'away', and that stretch is longer than a glance."""
        assert len(profile_spans(replace(B_GRADE, people_gap_count=4), DRIFT, 16.0)) == 2

    def test_a_look_away_is_only_let_through_up_to_the_ordinary_join(self):
        """With no ordinary join at all, the one look where nobody was found keeps the gap open."""
        assert len(profile_spans(replace(B_GRADE, max_gap_seconds=0.0), DRIFT, 16.0)) == 2

    def test_it_never_reaches_past_the_last_match(self):
        tail = looks(('freefall', 3, 30), ('freefall', 4, 3), ('freefall', 4, 3), ('freefall', 4, 3))
        assert profile_spans(B_GRADE, tail, 8.0) == [(0.5, 2.5)], 'people in view but small, and they never come back'

    def test_it_does_not_bridge_through_another_part_of_the_jump(self):
        through = looks(('freefall', 3, 30), ('break_off', 5, 3), ('break_off', 5, 3), ('break_off', 5, 3),
                        ('freefall', 3, 30))
        assert len(profile_spans(B_GRADE, through, 10.0)) == 2

    def test_with_people_counting_off_it_does_nothing(self):
        with_people = profile_spans(B_GRADE, DRIFT, 16.0, people_enabled=True)
        assert profile_spans(B_GRADE, DRIFT, 16.0, people_enabled=False) == with_people == [(0.5, 16.0)], \
            'off: every look in exit and freefall matches anyway'


class TestTheSetting:
    def test_it_is_off_by_default_and_changes_nothing(self):
        assert KeepProfile().people_gap_seconds == 0
        assert profile_spans(KeepProfile(), DRIFT, 16.0) == profile_spans(replace(KeepProfile(), people_gap_count=9),
                                                                         DRIFT, 16.0)

    def test_adding_it_to_the_app_reprocesses_nobodys_library(self):
        """While it is off it is not part of the fingerprint, whatever the count beside it says."""
        base = Settings(output_folder='C:/out', csv_folder='C:/out/timelines', yolo_model='C:/yolo.pt')
        other_count = replace(base, profiles=(KeepProfile(people_gap_count=7),))
        assert settings_fingerprint(other_count) == settings_fingerprint(base)
        from app.settings import profile_fingerprint
        assert 'people_gap_seconds' not in profile_fingerprint(KeepProfile())

    def test_turning_it_on_or_changing_it_recuts(self):
        base = Settings(output_folder='C:/out', csv_folder='C:/out/timelines', yolo_model='C:/yolo.pt')
        on = replace(base, profiles=(KeepProfile(people_gap_seconds=10.0),))
        more = replace(base, profiles=(KeepProfile(people_gap_seconds=10.0, people_gap_count=4),))
        assert len({settings_fingerprint(s) for s in (base, on, more)}) == 3

    def test_it_is_saved_and_read_back_and_old_files_still_load(self, tmp_path):
        path = tmp_path / 'settings.json'
        save_settings(Settings(profiles=(B_GRADE,)), path)
        assert load_settings(path).profiles[0] == B_GRADE
        import json
        data = json.loads(path.read_text(encoding='utf-8'))
        for name in ('people_gap_seconds', 'people_gap_count'):
            data['profiles'][0].pop(name)
        path.write_text(json.dumps(data), encoding='utf-8')
        assert load_settings(path).profiles[0].people_gap_seconds == 0, 'a settings file from before it existed'

    def test_bad_values_are_refused(self):
        with pytest.raises(ValueError, match='people_gap_seconds'):
            validate_profile(replace(B_GRADE, people_gap_seconds=-1.0))
        with pytest.raises(ValueError, match='at least 1 person'):
            validate_profile(replace(B_GRADE, people_gap_count=0))

    def test_the_editor_reads_it_back(self):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        from app.ui.profile_editor import ProfileEditor
        QApplication.instance() or QApplication([])
        editor = ProfileEditor(KeepProfile())
        editor.people_gap.setValue(10.0)
        editor.people_gap_count.setValue(3)
        profile = editor.read()
        assert (profile.people_gap_seconds, profile.people_gap_count) == (10.0, 3)
        assert 'gaps up to 10 s joined while at least 3 people are still in view' in editor.summary.text()
