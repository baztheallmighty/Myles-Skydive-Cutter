"""People in the review: how many were found and how much of the picture they fill are two separate things.

A moment can be left out because nobody was found, because too few were, or because the people found are too small
in the picture. The review has to say which, so each is a row of its own and every second carries its reason.
"""
import csv
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from app.settings import KeepProfile  # noqa: E402
from cutter_v4.review import REASONS, judge, people_track  # noqa: E402

FREEFALL = KeepProfile(name='Freefall', phases=frozenset({'freefall'}), min_person_count=1,
                       min_total_area_percent=20.0, margin_before_seconds=0.0, margin_after_seconds=0.0)


def timeline(*seconds):
    """Timeline rows from (phase, people found, percent of the picture) for each second."""
    return [{'time_sec': f'{index + .5:.3f}', 'phase': phase, 'person_count': str(count),
             'total_person_area_percent': str(area), 'matched_profiles': ''}
            for index, (phase, count, area) in enumerate(seconds)]


class TestTheReasonForEachSecond:
    def test_count_and_share_of_the_picture_are_separate_tests(self):
        rows = timeline(('exit', 2, 40), ('freefall', 0, 0), ('freefall', 1, 2), ('freefall', 1, 25), ('freefall', 2, 30))
        assert judge(FREEFALL, rows, 5.0) == ['phase', 'nobody', 'small', 'kept', 'kept']

    def test_somebody_there_but_not_enough_of_them(self):
        group = KeepProfile(name='Group', phases=frozenset({'freefall'}), min_person_count=2,
                            min_total_area_percent=10.0, margin_before_seconds=0.0, margin_after_seconds=0.0)
        rows = timeline(('freefall', 1, 50), ('freefall', 2, 5), ('freefall', 3, 30))
        assert judge(group, rows, 3.0) == ['few', 'small', 'kept']

    def test_a_match_too_short_to_keep_says_so(self):
        patient = KeepProfile(name='Long', phases=frozenset({'freefall'}), min_person_count=1,
                              min_total_area_percent=20.0, margin_before_seconds=0.0, margin_after_seconds=0.0,
                              min_span_seconds=3.0)
        rows = timeline(('freefall', 1, 30), ('freefall', 0, 0), ('freefall', 1, 30), ('freefall', 1, 30),
                        ('freefall', 1, 30))
        assert judge(patient, rows, 5.0) == ['short', 'nobody', 'kept', 'kept', 'kept']

    def test_extra_footage_and_joined_gaps_are_kept_but_not_matches(self):
        generous = KeepProfile(name='Generous', phases=frozenset({'freefall'}), min_person_count=1,
                               min_total_area_percent=20.0, margin_before_seconds=1.0, margin_after_seconds=0.0,
                               max_gap_seconds=1.0)
        rows = timeline(('exit', 0, 0), ('exit', 0, 0), ('freefall', 1, 30), ('freefall', 1, 3), ('freefall', 1, 30))
        assert judge(generous, rows, 5.0) == ['phase', 'extra', 'kept', 'extra', 'kept']

    def test_with_people_counting_off_only_the_part_of_the_jump_matters(self):
        rows = timeline(('exit', 0, 0), ('freefall', 0, 0))
        assert judge(FREEFALL, rows, 2.0, people_enabled=False) == ['phase', 'kept']

    def test_every_reason_has_words(self):
        assert set(REASONS) == {'kept', 'extra', 'joined', 'phase', 'nobody', 'few', 'small', 'short'}


def write_timeline(path, rows):
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


class TestWhatTheReviewIsGiven:
    def test_each_profile_in_use_is_judged(self, tmp_path):
        rows = timeline(('freefall', 1, 2), ('freefall', 1, 25))
        unused = KeepProfile(name='Off', enabled=False)
        easy = KeepProfile(name='Anyone', phases=frozenset({'freefall'}), min_person_count=0,
                           min_total_area_percent=0.0, margin_before_seconds=0.0, margin_after_seconds=0.0)
        track = people_track(write_timeline(tmp_path / 't.csv', rows), profiles=[FREEFALL, unused, easy], duration=2.0)
        assert [p['name'] for p in track['profiles']] == ['Freefall', 'Anyone']
        assert track['profiles'][0]['reason'] == ['small', 'kept'] and track['profiles'][0]['min_area'] == 20.0
        assert track['profiles'][1]['reason'] == ['kept', 'kept']
        assert track['count'] == [1, 1] and track['area'] == [2.0, 25.0]

    def test_a_timeline_without_people_columns_gives_nothing(self, tmp_path):
        path = tmp_path / 't.csv'
        path.write_text('time_sec,phase\n0.5,freefall\n', encoding='utf-8')
        assert people_track(path, profiles=[FREEFALL]) is None


@pytest.fixture
def tracks(tmp_path):
    """The rows under the video, with a twelve-second jump: nobody, then one person small, then two people large."""
    from PySide6.QtWidgets import QApplication
    from app.ui import theme
    from cutter_v4.review_ui import PredictionTracks
    application = QApplication.instance() or QApplication([])
    theme.apply(application)
    seconds = ([('climbing_out', 1, 30)] * 2 + [('freefall', 0, 0)] * 3 + [('freefall', 1, 2)] * 3
               + [('freefall', 2, 45)] * 4)
    group = KeepProfile(name='Group', phases=frozenset({'freefall'}), min_person_count=2,
                        min_total_area_percent=30.0, margin_before_seconds=0.0, margin_after_seconds=0.0)
    people = people_track(write_timeline(tmp_path / 't.csv', timeline(*seconds)), profiles=[FREEFALL, group],
                          duration=12.0)
    widget = PredictionTracks()
    widget.resize(1100, widget.height())
    widget.view.reset(12.0)
    widget.result = {'duration_sec': 12.0, 'people': people, 'agreement': [], 'clips': [], 'motion': {},
                     'tracks': {'final': [], 'v4': [], 'audio': [], 'motion': []}}
    widget.show()
    application.processEvents()
    return widget, application


def move_mouse(widget, application, row, seconds):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    top = 3
    for name, _title in widget.rows():
        if name == row:
            break
        top += widget.row_height(name) + 4
    where = QPointF(widget.x_of(seconds), top + widget.row_height(row) / 2)
    event = QMouseEvent(QEvent.Type.MouseMove, where, widget.mapToGlobal(where), Qt.MouseButton.NoButton,
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    widget.mouseMoveEvent(event)
    application.processEvents()
    return widget.hover_text


class TestTheRowsUnderTheVideo:
    def test_the_count_and_the_share_are_rows_of_their_own_shown_by_default(self, tracks):
        widget, _application = tracks
        names = dict(widget.ROWS)
        assert names['people'] == 'People found' and names['filled'] == 'Picture filled'
        assert names['why'] == 'Why not kept'
        assert {'people', 'filled', 'why'} <= set(widget.COLLAPSED), 'visible without expanding every track'

    def test_each_row_reads_its_own_number_at_the_playback_position(self, tracks):
        widget, _application = tracks
        widget.position = 6.5
        assert widget.readout('people', 6.5) == '1 person' and widget.readout('filled', 6.5) == '2%'
        assert widget.readout('why', 6.5) == 'people too small'
        assert widget.readout('people', 10.5) == '2 people' and widget.readout('filled', 10.5) == '45%'
        assert widget.subtitle('people') == 'needs 1' and widget.subtitle('filled') == 'needs 20%'

    def test_the_readout_beside_the_mouse_changes_every_time_it_moves(self, tracks):
        """An ordinary tooltip showed once and then never changed along the row."""
        widget, application = tracks
        first = move_mouse(widget, application, 'filled', 3.5)
        second = move_mouse(widget, application, 'filled', 6.5)
        third = move_mouse(widget, application, 'people', 10.5)
        assert len({first, second, third}) == 3
        assert '0 people found (needs 1)' in first and 'Not kept: nobody was found' in first
        assert '1 person found (needs 1)' in second and '2% of the picture filled (needs 20%)' in second
        assert 'Not kept: people fill 2% of the picture, needs 20%' in second
        assert '2 people found' in third and '45% of the picture filled' in third and 'Kept: it meets' in third
        assert widget.hover_x == pytest.approx(widget.x_of(10.5))

    def test_another_profile_gives_another_verdict_for_the_same_moment(self, tracks):
        widget, application = tracks
        assert 'people too small' == widget.readout('why', 6.5)
        widget.profile_index = 1   # Group: needs two people
        assert widget.readout('why', 6.5) == 'too few people' and widget.subtitle('people') == 'needs 2'
        assert 'Not kept: 1 found, needs 2' in move_mouse(widget, application, 'why', 6.5)

    def test_the_caption_on_the_video_says_both_and_why(self, tracks):
        widget, _application = tracks
        assert widget.people_caption(6.5) == ('1 person · 2% of picture · not kept: people fill 2% of the picture, '
                                              'needs 20%')
        assert widget.people_caption(10.5) == '2 people · 45% of picture'

    def test_it_draws_without_people_data_and_with_it(self, tracks):
        widget, application = tracks
        assert not widget.grab().isNull()
        widget.result = {**widget.result, 'people': None}
        widget.update()
        application.processEvents()
        assert not widget.grab().isNull() and widget.readout('people', 1.0) == ''
