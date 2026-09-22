"""The Review tab: the labeller, embedded in the main window, for the folders set on the Process tab."""
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QStackedLayout, QVBoxLayout, QWidget

from app.settings import state_directory


class ReviewTab(QWidget):
    go_to_process = Signal()
    reviews_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.window = None
        self.lock = None
        self.state = None
        self.active = False
        self.stale = False
        self.stack = QStackedLayout(self)
        placeholder = QWidget()
        layout = QVBoxLayout(placeholder)
        layout.addStretch()
        self.message = QLabel()
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        back = QPushButton('Go to Process')
        back.clicked.connect(self.go_to_process.emit)
        layout.addWidget(back, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()
        self.stack.addWidget(placeholder)
        self.host = QWidget()
        self.host_layout = QVBoxLayout(self.host)
        self.host_layout.setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(self.host)
        self.show_message('Nothing to review yet. Process some videos on the Process tab first.')

    def show_message(self, text):
        self.message.setText(text)
        self.stack.setCurrentIndex(0)

    def open(self, settings):
        """Show the labeller for these settings' output folder, reusing it when the folder has not changed."""
        folder = settings.output_folder if settings.cut_enabled else settings.csv_folder
        if not folder:
            self.close_labeller()
            self.show_message('Choose a clips folder on the Process tab, then process some videos.')
            return
        state = state_directory(settings)
        if not (state / 'ledger.json').is_file():
            self.close_labeller()
            self.show_message('Nothing has been processed into this folder yet. Process some videos first.')
            return
        if self.window is not None and self.state == state:
            if self.stale:
                self.refresh(settings)
            return
        self.close_labeller()
        from cutter_v4.review import build_review_run, review_directory, window_class
        from v3_poc.common import RunLock
        run = review_directory(state)
        run.mkdir(parents=True, exist_ok=True)
        lock = RunLock(run)
        try:
            lock.__enter__()
        except RuntimeError:
            self.show_message('This folder is already open in another labeller window. Close it, then come back here.')
            return
        try:
            build_review_run(state, settings.input_folder, locked=True, profiles=settings.profiles)
            window = window_class()(run, embedded=True)
        except Exception as exc:  # noqa: BLE001 - shown to the user instead of crashing the app
            lock.__exit__(None, None, None)
            self.show_message(f'Could not open the review: {exc}')
            return
        self.window, self.lock, self.state, self.stale = window, lock, state, False
        window.reviews_changed.connect(self.reviews_changed.emit)
        window.review_button.setText('Mark reviewed and re-cut' if settings.recut_on_review else 'Mark reviewed')
        window.review_button.setToolTip('Your labels become the cut for this video, then the next video opens.')
        self.host_layout.addWidget(window)
        window.set_shortcuts_enabled(self.active)
        self.stack.setCurrentIndex(1)

    def refresh(self, settings):
        if self.window is None:
            return
        from cutter_v4.review import build_review_run
        build_review_run(self.state, settings.input_folder, locked=True, profiles=settings.profiles)
        self.window.reload_run()
        self.stale = False

    def mark_stale(self):
        """A video finished processing; reload when the tab is next shown, so reviewing is never interrupted."""
        self.stale = True

    def set_active(self, active):
        self.active = active
        if self.window is not None:
            self.window.set_shortcuts_enabled(active)
            if not active:
                self.window.player.pause()

    def show_video(self, source):
        return self.window is not None and self.window.show_video(Path(source))

    def close_labeller(self):
        if self.window is not None:
            try:
                self.window.save_csv_silent()
                self.window.player.stop()
            finally:
                self.host_layout.removeWidget(self.window)
                self.window.deleteLater()
                self.window = None
        if self.lock is not None:
            self.lock.__exit__(None, None, None)
            self.lock = None
        self.state = None
