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
                           csv_folder=str(clips / 'timelines')), path)
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
        wanted = (max(1120, int(area.width() * .7)), max(720, int(area.height() * .7)))
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
