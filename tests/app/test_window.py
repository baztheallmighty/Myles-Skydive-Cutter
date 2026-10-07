"""The window's own behaviour: what it remembers, what it blocks, and where a dropped folder lands.

These drive the real MainWindow with Qt's offscreen platform, so they need no screen, no GPU and no model. The
heavier interface checks (the Review tab, the labeller, screenshots) stay in release/tests/ui_test.py.
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture
def window(tmp_path, monkeypatch):
    """A window whose settings live in a temporary file, so a test never touches the real ones.

    The install is reported as healthy whatever this machine actually has, because these tests are about what the
    window does with an answer, not about what is installed here. Tests that want a problem ask for one.
    """
    from PySide6.QtWidgets import QApplication
    from app import health as health_module
    from app import settings as settings_module
    from app.settings import Settings, save_settings
    from app.ui import main_window as window_module, theme

    for module in (health_module, window_module):
        monkeypatch.setattr(module, 'people_installed', lambda s=None: True, raising=False)
    monkeypatch.setattr(health_module, 'missing_models', lambda: [])
    monkeypatch.setattr(health_module, 'missing_tools', lambda: [])
    monkeypatch.setattr(health_module, 'missing_packages', lambda: [])
    # The window asks the real GPU 50 ms after it opens. Left alone, that answer could land in the middle of a test
    # that set its own and overwrite it, depending on how quickly this machine built the window.
    monkeypatch.setattr(window_module.MainWindow, 'check_gpu', lambda self: None)

    path = tmp_path / 'settings.json'
    inputs, clips = tmp_path / 'input', tmp_path / 'clips'
    inputs.mkdir()
    clips.mkdir()
    save_settings(Settings(input_folder=str(inputs), output_folder=str(clips),
                           csv_folder=str(clips / 'timelines'), mode='advanced'), path)
    monkeypatch.setattr(window_module, 'load_settings', lambda: settings_module.load_settings(path))
    monkeypatch.setattr(window_module, 'save_settings', lambda s: settings_module.save_settings(s, path))

    application = QApplication.instance() or QApplication([])
    theme.apply(application)
    built = window_module.MainWindow()
    built.people_available = True
    built.resize(1500, 1000)
    built.show()
    built.refresh_health(cuda=True)
    application.processEvents()
    yield built, application, path
    built.close()


class TestWhatItRemembers:
    def test_open_sections_and_column_split_survive_a_restart(self, window):
        built, application, path = window
        from app.settings import load_settings, save_settings

        built.sections['people'].set_open(True)
        built.sections['output'].set_open(True)
        built.splitter.setSizes([700, 900])
        application.processEvents()
        save_settings(built.read_settings(), path)

        saved = load_settings(path)
        assert set(saved.open_sections) == {'output', 'people'}
        assert saved.column_state and saved.window_geometry

    def test_a_remembered_window_is_restored(self, window):
        built, application, path = window
        from app.settings import save_settings
        from app.ui.main_window import MainWindow

        # Pick a size that fits this screen, since Qt rightly refuses to restore a window that would not.
        area = application.primaryScreen().availableGeometry()
        wanted = (max(built.minimumWidth(), int(area.width() * .7)), max(built.minimumHeight(), int(area.height() * .7)))
        built.resize(*wanted)
        application.processEvents()
        save_settings(built.read_settings(), path)

        again = MainWindow()
        again.show()
        application.processEvents()
        assert abs(again.width() - wanted[0]) <= 40 and abs(again.height() - wanted[1]) <= 40
        again.close()

    def test_preferences_do_not_ask_for_reprocessing(self, window):
        """Remembering the window must never look like a settings change to the processor."""
        built, application, path = window
        from app.settings import settings_fingerprint
        before = settings_fingerprint(built.read_settings())
        built.sections['processing'].set_open(True)
        built.splitter.setSizes([500, 1000])
        built.resize(1200, 800)
        application.processEvents()
        assert settings_fingerprint(built.read_settings()) == before


class TestWhatItBlocks:
    def missing_people(self, built, monkeypatch):
        from app import health as health_module
        from app.ui import main_window as window_module
        monkeypatch.setattr(window_module, 'people_installed', lambda s=None: False)
        monkeypatch.setattr(health_module, 'people_installed', lambda s=None: False)
        built.people_available = False
        built.refresh_health(cuda=True)

    def test_a_missing_detector_stops_the_run_and_says_so(self, window, monkeypatch):
        built, application, _path = window
        self.missing_people(built, monkeypatch)
        application.processEvents()
        assert not built.process_button.isEnabled()
        assert built.health_banner.isVisible() and 'not installed' in built.health_banner.text()
        assert built.sections['people'].objectName() == 'sectionDanger'
        assert built.fix_button.isVisible()

    def test_no_gpu_warns_but_still_runs(self, window):
        built, application, _path = window
        built.refresh_health(cuda=False)
        application.processEvents()
        assert built.process_button.isEnabled()
        assert built.health_banner.objectName() == 'bannerWarning'
        assert 'NVIDIA' in built.health_banner.text()

    def test_a_healthy_install_says_nothing_at_all(self, window):
        built, application, _path = window
        built.refresh_health(cuda=True)
        application.processEvents()
        assert built.process_button.isEnabled() and not built.health_banner.isVisible()

    def choose_nvidia_without_a_gpu(self, built, application):
        built.cuda = False
        built.refresh_health(cuda=False)
        built.device.setCurrentIndex(built.device.findData('cuda'))
        application.processEvents()

    def test_choosing_a_gpu_that_is_not_there_blocks_at_once(self, window):
        """2.4.1: the check only ran at start-up, so choosing NVIDIA GPU afterwards let every video fail."""
        built, application, _path = window
        self.choose_nvidia_without_a_gpu(built, application)
        assert not built.process_button.isEnabled()
        assert 'NVIDIA GPU' in built.health_banner.text()

    def test_no_way_of_starting_gets_past_a_blocking_problem(self, window, tmp_path):
        """A re-cut from the Review tab calls start_session directly, never through the Process button."""
        built, application, _path = window
        self.choose_nvidia_without_a_gpu(built, application)
        video = tmp_path / 'input' / 'jump.mp4'
        video.write_bytes(b'')
        built.recut.setChecked(True)
        built.recut_now(str(video))
        assert built.session is None and not built.active
        assert 'Not started' in built.warning.text() and 'NVIDIA GPU' in built.warning.text()


class TestDroppingFolders:
    def drop(self, built, widget, folder):
        from PySide6.QtCore import QMimeData, QPointF, QUrl, Qt
        from PySide6.QtGui import QDropEvent
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(str(folder))])
        centre = widget.mapTo(built, widget.rect().center())
        built.dropEvent(QDropEvent(QPointF(centre), Qt.DropAction.CopyAction, data,
                                   Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))

    def test_a_folder_dropped_on_a_box_sets_that_box(self, window, tmp_path):
        built, application, _path = window
        built.scroll.verticalScrollBar().setValue(0)
        application.processEvents()
        dropped = tmp_path / 'dropped'
        dropped.mkdir()
        self.drop(built, built.folder_edits['output_folder'], dropped)
        assert Path(built.folder_edits['output_folder'].text()) == dropped

    def test_a_folder_dropped_anywhere_else_sets_the_input(self, window, tmp_path):
        built, application, _path = window
        dropped = tmp_path / 'elsewhere'
        dropped.mkdir()
        self.drop(built, built.process_button, dropped)
        assert Path(built.folder_edits['input_folder'].text()) == dropped


class TestOutputChoices:
    def test_csv_folder_follows_the_clips_folder_by_default(self, window):
        built, _application, _path = window
        settings = built.read_settings()
        assert Path(settings.csv_folder) == Path(settings.output_folder) / 'timelines'

    def test_csv_only_mode_needs_its_own_folder(self, window):
        built, application, _path = window
        built.output_mode.setCurrentIndex(1)          # CSV only
        application.processEvents()
        assert built.csv_elsewhere.isChecked() and not built.csv_in_clips.isEnabled()

    def test_every_360_view_is_offered_and_front_is_the_default(self, window):
        built, _application, _path = window
        views = [built.view_mode.itemData(i) for i in range(built.view_mode.count())]
        assert views == ['front', 'front_back', 'back']
        assert built.read_settings().view_mode == 'front'


class TestSmallScreens:
    """A 1080p screen scaled to 125% leaves about 1536x785 for the window, and scaled to 150% about 1280x641."""

    def test_the_window_can_be_as_small_as_a_scaled_1080p_screen(self, window):
        built, application, _path = window
        built.resize(1280, 641)
        application.processEvents()
        assert (built.width(), built.height()) == (1280, 641)
        for widget in (built.process_button, built.stop_button, built.queue_bar, built.log):
            bottom = widget.mapTo(built, widget.rect().bottomLeft()).y()
            assert widget.isVisible() and bottom <= built.height(), 'the run bar and log stay inside the window'

    def test_the_basic_screen_needs_no_scrolling_at_125_percent(self, window):
        built, application, _path = window
        built.set_mode('basic')
        built.resize(1536, 785)
        application.processEvents()
        assert built.controls.height() <= built.scroll.viewport().height()
        assert built.results.height() >= 300, 'and the results beside it are still a usable list'

    def test_a_window_bigger_than_its_screen_is_brought_inside_it(self, window):
        built, application, _path = window
        area = built.screen().availableGeometry()
        built.resize(area.width() + 600, area.height() + 400)
        built.move(area.left() - 50, area.top() - 50)
        application.processEvents()
        built.keep_on_screen()
        application.processEvents()
        frame = built.frameGeometry()
        assert frame.top() >= area.top() and frame.left() >= area.left()
        assert built.height() <= max(area.height(), built.minimumHeight())
        assert built.width() <= max(area.width(), built.minimumWidth())

    def test_a_first_window_is_never_sized_past_the_screen(self, window):
        built, application, path = window
        from dataclasses import replace
        from app.settings import load_settings, save_settings
        from app.ui.main_window import MainWindow
        save_settings(replace(load_settings(path), window_geometry=''), path)
        fresh = MainWindow()
        area = application.primaryScreen().availableGeometry()
        assert fresh.width() <= max(area.width(), fresh.minimumWidth())
        assert fresh.height() <= max(area.height(), fresh.minimumHeight())
        fresh.close()


class TestANewerVersion:
    def test_nothing_is_shown_or_asked_in_a_development_folder(self, window, monkeypatch):
        built, application, _path = window
        from app.ui import main_window as window_module
        monkeypatch.setattr(window_module.UpdateCheck, 'start', lambda self: pytest.fail('asked the internet'))
        built.check_for_update()
        assert not built.update_banner.isVisible()

    def test_an_installed_copy_asks_once_unless_told_not_to(self, window, monkeypatch):
        built, application, _path = window
        from dataclasses import replace
        from app import update
        from app.ui import main_window as window_module
        asked = []
        monkeypatch.setattr(update, 'installed_version', lambda *_: '2.6.0')
        monkeypatch.setattr(window_module.UpdateCheck, 'start', lambda self: asked.append(self))
        built.settings = replace(built.settings, check_updates=False)
        built.check_for_update()
        assert not asked, 'switched off means no request at all'
        built.settings = replace(built.settings, check_updates=True)
        built.check_for_update()
        built.check_for_update()
        assert len(asked) == 1

    def test_a_newer_version_shows_a_line_with_a_button_to_the_download_page(self, window, monkeypatch):
        built, application, _path = window
        from PySide6.QtGui import QDesktopServices
        from app import update
        opened = []
        monkeypatch.setattr(update, 'installed_version', lambda *_: '2.6.0')
        monkeypatch.setattr(QDesktopServices, 'openUrl', lambda url: opened.append(url.toString()))
        built.show_update('2.7.0', update.DOWNLOAD_PAGE)
        assert built.update_banner.isVisible() and '2.7.0' in built.update_banner.text()
        assert '2.6.0' in built.update_banner.text()
        built.update_button.click()
        assert opened == [update.DOWNLOAD_PAGE]
        built.update_later.click()
        assert not built.update_banner.isVisible() and not built.update_button.isVisible()

    def test_the_choice_to_check_is_remembered_and_never_reprocesses(self, window):
        built, application, path = window
        from app.settings import load_settings, save_settings, settings_fingerprint
        before = settings_fingerprint(built.read_settings())
        built.check_updates.setChecked(False)
        assert settings_fingerprint(built.read_settings()) == before
        save_settings(built.read_settings(), path)
        assert load_settings(path).check_updates is False


class TestTheRulesAndAbout:
    def test_the_rules_say_what_nobody_can_change(self, window):
        built, application, _path = window
        from PySide6.QtWidgets import QLabel
        from app import help_text
        from app.ui.about import RulesDialog
        dialog = RulesDialog(built)
        assert dialog.windowTitle() == 'How video is chosen in basic mode'
        shown = ' | '.join(label.text() for label in dialog.findChildren(QLabel))
        for said in ('The stages only go forwards.', 'The app expects one jump per video.', 'up to 30 more seconds',
                     'You (the camera person) count as a person.', 'Advanced mode', 'less than a second apart',
                     'keyframes', 'short matches that stand alone are dropped'):
            assert said in shown, said
        for title, words in help_text.built_in_choices():
            assert title in shown and words in shown, 'what each choice asks for comes from the profiles themselves'
        area = built.screen().availableGeometry()
        assert dialog.height() <= area.height() and dialog.width() <= area.width()
        dialog.close()

    def test_every_point_in_bold_is_a_sentence_the_note_really_opens_with(self):
        from app import help_text
        paragraphs = [content for kind, content in help_text.rules() if kind == 'text']
        for lead in help_text.RULE_LEADS:
            assert any(paragraph.startswith(lead) for paragraph in paragraphs), lead

    def test_the_seconds_sound_may_add_are_the_engines_own(self):
        from app import help_text
        source = (ROOT / 'cutter_v4' / 'engine.py').read_text(encoding='utf-8')
        line = next(line for line in source.splitlines() if line.startswith('AUDIO_FREEFALL_MAX_EXTENSION ='))
        assert int(line.split('=')[1]) == help_text.SOUND_EXTENDS_FREEFALL_SECONDS
        assert f'up to {help_text.SOUND_EXTENDS_FREEFALL_SECONDS} more seconds' in help_text.rules_text()

    def test_the_example_is_what_the_app_would_really_cut(self):
        """The worked example is run through the real clip rules, so the note cannot promise clips the app would not
        make."""
        from dataclasses import replace
        from app import help_text
        from app.profiles import profile_spans
        from app.settings import A_GRADE, TRIM, built_in_profiles
        rows = []
        for second in range(help_text.EXAMPLE_DURATION):
            t = second + .5
            close = any(start <= t < end for start, end in help_text.EXAMPLE_CLOSE)
            rows.append({'time_sec': t, 'phase': next(p for p, start, end in help_text.EXAMPLE_STAGES if start <= t < end),
                         'person_count': 1 if close else 0, 'total_person_area_percent': 25 if close else 0})
        built = built_in_profiles()
        text = help_text.rules_text()

        def clocks(profile, people):
            spans = profile_spans(replace(built[profile], enabled=True), rows, help_text.EXAMPLE_DURATION, True, people)
            return [(help_text.clock(start), help_text.clock(end)) for start, end in spans]

        assert clocks(TRIM, False) == [('3:08', '4:16')] and 'one clip from 3:08 to 4:16' in text
        assert clocks(A_GRADE, True) == [('3:08', '3:16'), ('3:23', '4:00')]
        assert '3:08 to 3:16 (the exit) and 3:23 to 4:00 (the freefall)' in text
        exit_left_out = replace(built[A_GRADE], enabled=True, phases=built[A_GRADE].phases - {'exit'})
        assert [help_text.clock(start) for start, _end in profile_spans(exit_left_out, rows, 360)] == ['3:23']

    def test_both_buttons_are_there_on_either_screen(self, window):
        built, application, _path = window
        for mode in ('basic', 'advanced'):
            built.set_mode(mode)
            application.processEvents()
            assert built.rules_button.isVisible() and built.check_button.isVisible()
        assert built.rules_button.text() == 'How video is chosen in basic mode'

    def test_check_for_updates_always_gives_an_answer(self, window, monkeypatch):
        built, application, _path = window
        from app import update
        from app.ui import main_window as window_module
        built.check_now()
        assert 'development folder' in built.status.text(), 'nothing to compare, and nothing asked'
        monkeypatch.setattr(update, 'installed_version', lambda *_: '2.6.0')
        started = []
        monkeypatch.setattr(window_module.UpdateCheck, 'start', lambda self: started.append(self))
        built.check_now()
        assert len(started) == 1 and started[0].always_answer and not built.check_button.isEnabled()
        built.update_answer(update.LATEST_INSTALLED, '2.6.0')
        assert built.check_button.isEnabled() and 'latest version, 2.6.0' in built.status.text()
        built.update_answer(update.UNKNOWN, '')
        assert 'Could not check' in built.status.text()

    def test_the_button_asks_even_when_the_start_up_check_is_off(self, window, monkeypatch):
        built, application, _path = window
        from dataclasses import replace
        from app import update
        from app.ui import main_window as window_module
        started = []
        monkeypatch.setattr(update, 'installed_version', lambda *_: '2.6.0')
        monkeypatch.setattr(window_module.UpdateCheck, 'start', lambda self: started.append(self))
        built.settings = replace(built.settings, check_updates=False)
        built.check_now()
        assert len(started) == 1

    def test_the_diagnostics_shortcut_saves_a_file_and_says_where(self, window, tmp_path, monkeypatch):
        built, application, _path = window
        from app.ui import about
        monkeypatch.setattr(about, 'PROJECT_ROOT', tmp_path)
        built.save_diagnostics()
        assert len(list((tmp_path / 'logs').glob('diagnostics-*.txt'))) == 1
        assert 'Diagnostics saved' in built.status.text()

    def test_the_diagnostics_describe_the_screen_and_name_no_folders(self, window, tmp_path, monkeypatch):
        built, application, _path = window
        from app.ui import about
        text = about.diagnostics(built)
        for said in ('Screens:', 'Window:', 'smallest allowed', 'pointer at', 'PySide6', 'Recent videos'):
            assert said in text, said
        assert str(tmp_path) not in text and tmp_path.name not in text
        monkeypatch.setattr(about, 'PROJECT_ROOT', tmp_path)
        saved = about.save_diagnostics(built)
        assert saved.parent == tmp_path / 'logs' and saved.read_text(encoding='utf-8').startswith('Skydive Cutter')
