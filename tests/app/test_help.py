"""Every setting says what it does: the words behind the "?" buttons, and the notes that appear beside a setting."""
import os
import sys
from dataclasses import fields
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from app import help_text  # noqa: E402
from app.settings import KeepProfile, Settings, profile_presets  # noqa: E402
from v3_poc.common import PHASES  # noqa: E402


class TestTheWords:
    def test_every_setting_a_person_can_change_is_explained(self):
        """A new setting must come with its explanation, or be listed as one that has no control of its own."""
        named = {f.name for f in fields(Settings)} | {f.name for f in fields(KeepProfile)}
        unexplained = named - set(help_text.HELP) - help_text.UNSEEN
        assert not unexplained, f'no help for: {sorted(unexplained)}'

    def test_every_explanation_has_a_name_and_says_something(self):
        for key, (label, body) in help_text.HELP.items():
            assert label.strip() and len(body) > 30, key
            assert not label.endswith('.'), f'{key}: a label is a name, not a sentence'

    def test_every_part_of_the_jump_is_described(self):
        assert set(help_text.PHASES) == set(PHASES)

    def test_settings_that_redo_a_library_say_so(self):
        """The warning follows the fingerprint, so it cannot go stale when a setting changes sides."""
        for key in ('sample_fps', 'detection_confidence', 'view_mode', 'min_person_count', 'margin_after_seconds'):
            assert help_text.REPROCESS_NOTE in help_text.text(key), key
        for key in ('device', 'batch_size', 'hardware_decode', 'parallel_videos', 'recut_on_review', 'input_folder'):
            assert help_text.REPROCESS_NOTE not in help_text.text(key), key

    def test_people_in_view_says_it_includes_you(self):
        assert 'INCLUDING YOU' in help_text.text('min_person_count')


class TestTheNotesBesideASetting:
    def test_the_includes_you_warning_appears_where_you_are_in_your_own_picture(self):
        by_name = {p.name: p for p in profile_presets()}
        assert 'includes you' in help_text.includes_you_warning(by_name['Landing'])
        assert help_text.includes_you_warning(by_name['Group freefall']) == '', 'in freefall you are not in shot'
        assert help_text.includes_you_warning(by_name['Canopy flight']) == '', 'it asks for nobody, so nothing to warn'
        canopy_with_people = KeepProfile(phases=frozenset({'canopy_flight'}), min_person_count=1)
        assert 'includes you' in help_text.includes_you_warning(canopy_with_people)

    def test_the_summary_says_what_a_profile_keeps(self):
        summary = help_text.profile_summary(KeepProfile())
        assert summary == ('Keeps exit and freefall while at least 1 person is in view and people fill 20% of the '
                           'picture; 1 s extra before and 2 s after.')
        assert 'whether or not anyone is in view' in help_text.profile_summary(KeepProfile(), people_enabled=False)
        assert help_text.profile_summary(KeepProfile(phases=frozenset())).startswith('Keeps nothing')
        assert help_text.profile_summary(KeepProfile(), phases_enabled=False).startswith('Keeps any part of the video')


@pytest.fixture
def application():
    from PySide6.QtWidgets import QApplication
    from app.ui import theme
    application = QApplication.instance() or QApplication([])
    theme.apply(application)
    return application


class TestTheButtons:
    def test_the_profile_editor_has_one_for_every_field(self, application):
        from app.ui.help import HelpButton
        from app.ui.profile_editor import ProfileEditor
        editor = ProfileEditor(KeepProfile())
        assert {button.key for button in editor.findChildren(HelpButton)} == {f.name for f in fields(KeepProfile)}

    def test_clicking_one_opens_its_note(self, application):
        from app.ui.help import HelpButton
        button = HelpButton('min_person_count')
        button.show()
        button.click()
        application.processEvents()
        assert button.note.isVisible() and 'INCLUDING YOU' in button.note.body.text()
        button.note.close()

    def test_the_editor_warns_and_summarises_as_you_change_it(self, application):
        from app.ui.profile_editor import ProfileEditor
        editor = ProfileEditor(KeepProfile())
        assert editor.includes_you.text() == ''
        editor.phase_checks['landing'].setChecked(True)
        assert 'includes you' in editor.includes_you.text()
        editor.people.setValue(0)
        assert editor.includes_you.text() == '' and 'landing' in editor.summary.text()
