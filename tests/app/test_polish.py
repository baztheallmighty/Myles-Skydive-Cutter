"""Small things that make the window safe and readable: the wheel, the help notes, the profile list, the results."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from app import help_text  # noqa: E402
from app.settings import MAX_PARALLEL_VIDEOS, KeepProfile  # noqa: E402
from test_window import window  # noqa: E402,F401 - the window fixture (advanced screen)


@pytest.fixture
def application():
    from PySide6.QtWidgets import QApplication
    from app.ui import theme
    application = QApplication.instance() or QApplication([])
    theme.apply(application)
    return application


def wheel(widget, application, notches=-1):
    """Turn the mouse wheel over a widget, as scrolling a page with the pointer above it does."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    centre = QPointF(widget.rect().center())
    event = QWheelEvent(centre, widget.mapToGlobal(centre), QPoint(0, 0), QPoint(0, 120 * notches),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    application.sendEvent(widget, event)
    application.processEvents()
    return event.isAccepted()


class TestTheWheel:
    def test_scrolling_past_a_drop_down_or_a_number_does_not_change_it(self, application):
        from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QVBoxLayout, QWidget
        holder = QWidget()
        box = QVBoxLayout(holder)
        choice, number = QComboBox(), QDoubleSpinBox()
        choice.addItems(['one', 'two', 'three'])
        number.setValue(5.0)
        other = QComboBox()
        for widget in (choice, number, other):
            box.addWidget(widget)
        holder.show()
        other.setFocus()
        application.processEvents()
        assert not wheel(choice, application) and choice.currentIndex() == 0, 'left for the page to scroll'
        assert not wheel(number, application) and number.value() == 5.0

    def test_once_clicked_it_answers_the_wheel(self, application):
        from PySide6.QtWidgets import QComboBox
        choice = QComboBox()
        choice.addItems(['one', 'two', 'three'])
        choice.show()
        choice.activateWindow()
        choice.setFocus()
        application.processEvents()
        if not choice.hasFocus():
            pytest.skip('this display gives no keyboard focus to test with')
        wheel(choice, application)
        assert choice.currentIndex() == 1


class TestHelpNotes:
    @pytest.mark.parametrize('key', sorted(help_text.HELP))
    def test_every_note_is_tall_enough_for_all_its_words(self, application, key):
        """The longest explanations used to lose their last lines."""
        from app.ui.help import HelpNote
        note = HelpNote(help_text.label(key), help_text.text(key))
        note.adjustSize()
        note.show()
        application.processEvents()
        needed = note.body.heightForWidth(note.body.width())
        assert note.body.height() >= needed, f'{key}: {note.body.height()} px for {needed} px of text'
        assert note.height() >= needed + 30
        note.close()

    def test_the_button_goes_back_to_plain_when_its_note_closes(self, application):
        from PySide6.QtCore import Qt
        from app.ui.help import HelpButton
        button = HelpButton('people_gap_seconds')
        button.move(400, 300)   # away from the corner, where this display parks the mouse
        button.show()
        button.click()
        application.processEvents()
        assert button.note.isVisible()
        from app.ui.help import HelpNote
        button.note.close()
        application.processEvents()
        assert not button.testAttribute(Qt.WidgetAttribute.WA_UnderMouse) and not button.hasFocus()
        assert button.note is None and button.window().findChildren(HelpNote) == [], 'the note is gone, not hidden'


class TestWhatToKeep:
    def test_profiles_in_use_stand_out_and_are_spelled_out(self, window):  # noqa: F811
        built, application, _path = window
        built.profiles = [KeepProfile(name='Mine'), KeepProfile(name='Spare', enabled=False)]
        built.refresh_profiles()
        application.processEvents()
        assert built.table.item(0, 0).text() == 'In use' and built.table.item(1, 0).text() == 'Off'
        assert built.table.item(0, 1).font().bold() and not built.table.item(1, 1).font().bold()
        assert built.keeping.text().startswith('A run will keep:') and 'Mine: Keeps exit and freefall' in built.keeping.text()
        assert 'Spare' not in built.keeping.text()

    def test_nothing_in_use_is_said_plainly(self, window):  # noqa: F811
        built, application, _path = window
        built.profiles = [KeepProfile(name='Spare', enabled=False)]
        built.refresh_profiles()
        assert 'Nothing is in use' in built.keeping.text() and built.keeping.objectName() == 'keepingNothing'

    def test_ticking_a_profile_updates_the_sentence(self, window):  # noqa: F811
        from PySide6.QtCore import Qt
        built, application, _path = window
        built.profiles = [KeepProfile(name='Spare', enabled=False)]
        built.refresh_profiles()
        built.table.item(0, 0).setCheckState(Qt.Checked)
        application.processEvents()
        assert 'Spare: Keeps' in built.keeping.text()


class TestVideosAtOnce:
    def test_up_to_ten_then_automatic(self, window):  # noqa: F811
        built, _application, _path = window
        offered = [built.parallel.itemData(i) for i in range(built.parallel.count())]
        assert MAX_PARALLEL_VIDEOS == 10 and offered == list(range(1, 11)) + [0]
        assert len(built.video_bars) == 10, 'a progress bar for each'


def row(name, status='Done', clips=1, checks=0, completed='2026-10-01T10:00:00+00:00', labels='Model'):
    return {'key': name.casefold(), 'source': f'D:/in/{name}', 'name': name, 'status': status, 'error': '',
            'labels': labels, 'clips': clips, 'checks': checks, 'disagreement': .1 * checks, 'notes': '',
            'processed': completed[5:16], 'completed': completed, 'thumbnail': None, 'csv_path': None,
            'clip_paths': []}


@pytest.fixture
def results(application):
    from app.ui.results import ResultsPanel
    panel = ResultsPanel()
    panel.rows = [row('b.mp4', clips=3, completed='2026-10-02T09:00:00+00:00'),
                  row('a.mp4', clips=1, checks=2, completed='2026-10-03T09:00:00+00:00'),
                  row('c.mp4', status='Failed', clips=0, completed='2026-10-01T09:00:00+00:00')]
    panel.resize(700, 400)
    panel.show()
    panel.show_rows()
    application.processEvents()
    return panel, application


def listed(panel):
    return [panel.table.item(index, 0).text() for index in range(panel.table.rowCount())]


class TestResults:
    def test_clicking_a_title_sorts_and_clicking_again_turns_it_round(self, results):
        panel, _application = results
        panel.sort_by(0)
        assert listed(panel) == ['a.mp4', 'b.mp4', 'c.mp4']
        panel.sort_by(0)
        assert listed(panel) == ['c.mp4', 'b.mp4', 'a.mp4']
        panel.sort_by(3)
        assert listed(panel) == ['c.mp4', 'a.mp4', 'b.mp4'], 'clips, as numbers'
        panel.sort_by(6)
        assert listed(panel) == ['c.mp4', 'b.mp4', 'a.mp4'], 'processed, by the real time not the text'

    def test_several_can_be_selected_and_processed_again_together(self, results):
        panel, application = results
        asked = []
        panel.process_again.connect(asked.append)
        panel.table.selectAll()
        application.processEvents()
        assert len(panel.selected_rows()) == 3 and panel.again_button.text() == 'Process these 3 again'
        assert not panel.review_button.isEnabled(), 'opening in Review is for one video'
        panel.again_button.click()
        assert sorted(asked[0]) == ['a.mp4', 'b.mp4', 'c.mp4']

    def test_the_selection_follows_the_video_through_a_sort(self, results):
        panel, application = results
        panel.sort_by(0)
        panel.table.selectRow(0)
        application.processEvents()
        assert [r['name'] for r in panel.selected_rows()] == ['a.mp4']
        panel.sort_by(0)
        assert [r['name'] for r in panel.selected_rows()] == ['a.mp4']

    def test_every_column_fits_inside_the_list_until_you_resize_one(self, results):
        panel, application = results
        for width in (700, 520, 1100):
            panel.resize(width, 400)
            application.processEvents()
            total = sum(panel.table.columnWidth(column) for column in range(panel.table.columnCount()))
            assert total <= panel.table.viewport().width() + 2, (width, total)
        last = panel.table.columnCount() - 1
        edge = panel.table.columnViewportPosition(last) + panel.table.columnWidth(last)
        assert edge <= panel.table.viewport().width() + 2, 'the processed date is on screen'
        panel.table.horizontalHeader().resizeSection(1, 200)
        panel.resize(900, 400)
        application.processEvents()
        assert panel.table.columnWidth(1) == 200, 'a width set by hand is kept'

    def test_the_window_forgets_every_selected_video_in_one_go(self, window):  # noqa: F811
        from app.monitor import load_ledger, save_ledger
        from app.settings import state_directory
        built, _application, _path = window
        state = state_directory(built.read_settings())
        state.mkdir(parents=True, exist_ok=True)
        save_ledger(state / 'ledger.json', {'schema_version': 1, 'entries': {
            'a': {'status': 'success'}, 'b': {'status': 'success'}, 'c': {'status': 'success'}}})
        built.process_again(['a', 'c'])
        assert set(load_ledger(state / 'ledger.json')['entries']) == {'b'}
        assert '2 videos will be processed' in built.status.text()
        built.process_again('b')
        assert load_ledger(state / 'ledger.json')['entries'] == {}
