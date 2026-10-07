"""Desktop controls. Classification and output decisions live outside this module."""
from collections import deque
from dataclasses import replace
from datetime import datetime
import importlib.util
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QProgressBar, QScrollArea, QSpinBox, QApplication, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QToolButton,
    QVBoxLayout, QWidget, QMenu, QRadioButton, QFrame)

from app.monitor import VideoProcessor, load_ledger, save_ledger
from app.classifiers import available_classifiers
from app.health import ERROR, WARNING, blocking, check_install, cuda_available, people_installed, summary
from app.outputs import OUTPUT_LAYOUTS, layout_example, source_label
from app.progress import QueueProgress, video_progress
from app.runtime import Cancelled
from app.system import device_choices, installer_argv, visible_console
from app.settings import (A_CANOPY, A_GRADE, B_GRADE, LANDING, MAX_PARALLEL_VIDEOS, MOST_SECONDS_EITHER_SIDE, TRIM,
                          VIEW_MODES, KeepProfile, Settings, available_detectors, built_in_profiles, load_settings,
                          profile_presets, save_settings, state_directory, validate_settings, with_built_ins)
from app import help_text
from app.ui.about import RulesDialog
from app.ui.help import HelpButton, with_help
from app.ui.profile_editor import ProfileEditor, decimal_spin
from app.ui.theme import GOOD_BACKGROUND, MUTED
from app.ui.review_tab import ReviewTab
from app.ui.results import ResultsPanel
from app import PROJECT_ROOT
from app.eta import DurationProber, SpeedStore, describe
from app.ffmpeg_tools import find_executable
import time
from app.relocate import rebase_entries
from app.session import ProcessingSession
from v3_poc.common import RunLock, key


# Room left for the title bar and borders when sizing a window before it is shown, when their size is not yet known.
FRAME_ALLOWANCE = (16, 40)
SHORT_WINDOW = 900   # below this height (a 1080p screen scaled to 125% or more) the pinned area is squeezed


class VideoWorker(QThread):
    """One video on its own thread. ``slot`` is which of the side-by-side places it holds; every signal carries it."""
    log = Signal(int, str)
    outcome = Signal(int, str, object)
    progress = Signal(int, str, float, float)

    def __init__(self, processor, source, signature, previous_entry=None, parent=None, moved_from=(), slot=0):
        super().__init__(parent)
        self.processor, self.source, self.signature = processor, source, signature
        self.previous_entry = previous_entry
        self.moved_from = moved_from
        self.slot = slot
        self.started_at = time.monotonic()

    def run(self):
        self.processor.runner.log = lambda message: self.log.emit(self.slot, message)
        self.processor.runner.progress = lambda stage, done, total: self.progress.emit(self.slot, stage, done, total)
        try:
            result = self.processor.process(self.source, self.signature, self.previous_entry,
                                            moved_from=self.moved_from)
            self.outcome.emit(self.slot, 'success', result)
        except Cancelled as exc:
            self.outcome.emit(self.slot, 'cancelled', {'error': str(exc)})
        except Exception as exc:
            self.outcome.emit(self.slot, 'failed', {'error': f'{type(exc).__name__}: {exc}'})


class UpdateCheck(QObject):
    """Asks, off the window's thread, whether a newer version is published. Silent unless there is one.

    A plain daemon thread, not a QThread: the app may be closed while the question is still out, and nothing should
    have to wait for an answer nobody will read.
    """
    found = Signal(str, str)
    answered = Signal(str, str)   # only when someone pressed the button: the answer, whatever it is

    def __init__(self, parent=None, always_answer=False):
        super().__init__(parent)
        self.always_answer = always_answer

    def start(self):
        import threading
        threading.Thread(target=self.ask, name='update-check', daemon=True).start()

    def ask(self):
        from app.update import NEWER, check
        answer, version, page = check()
        try:
            if answer == NEWER:
                self.found.emit(version, page)
            if self.always_answer:
                self.answered.emit(answer, version)
        except RuntimeError:   # the window went away first
            pass


class Section(QFrame):
    """One advanced group that folds away, so the settings column stays short until you need it."""
    folded = Signal()

    def __init__(self, key, title, parent=None):
        super().__init__(parent)
        self.key = key
        self.setObjectName('section')
        box = QVBoxLayout(self)
        box.setContentsMargins(4, 2, 4, 2)
        box.setSpacing(2)
        self.button = QToolButton()
        self.button.setObjectName('section')
        self.button.setText(title)
        self.button.setCheckable(True)
        self.button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.button.setArrowType(Qt.ArrowType.RightArrow)
        self.button.toggled.connect(self.set_open)
        self.note = QLabel()
        self.note.setObjectName('danger')
        self.note.setWordWrap(True)
        self.note.hide()
        header = QHBoxLayout()
        header.addWidget(self.button)
        header.addStretch()
        self.header = header
        box.addLayout(header)
        box.addWidget(self.note)
        self.body = QWidget()
        self.body.setObjectName('sectionBody')
        self.form = QFormLayout(self.body)
        self.form.setContentsMargins(14, 2, 0, 6)
        self.body.hide()
        box.addWidget(self.body)

    def set_open(self, shown):
        self.button.setChecked(shown)
        self.button.setArrowType(Qt.ArrowType.DownArrow if shown else Qt.ArrowType.RightArrow)
        self.body.setVisible(shown)
        self.folded.emit()

    def is_open(self):
        return self.button.isChecked()

    def set_state(self, state, detail=''):
        """Red when something it needs is missing, amber when it only slows things down."""
        self.setObjectName({'error': 'sectionDanger', 'warning': 'sectionWarning'}.get(state, 'section'))
        self.style().unpolish(self)
        self.style().polish(self)
        self.note.setText(detail)
        self.note.setVisible(bool(detail))


class MainWindow(QMainWindow):
    def __init__(self, open_review=False):
        super().__init__()
        self.open_review = open_review
        self.setWindowTitle('Skydive Cutter')
        self.settled = False   # set once the window has been shown and checked against its screen
        self.setAcceptDrops(True)
        self.workers = {}     # the videos in progress, by which side-by-side place each holds
        self.pacer = None     # with "Videos at once: Automatic", decides when the machine has room for another
        self.session = None   # the run in progress (app/session.py); the window only drives it
        self.active = False
        self.stopping = False
        self.queue_progress = QueueProgress()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.settings_error = None
        try:
            self.settings = load_settings()
        except (ValueError, TypeError, KeyError, OSError, AttributeError) as exc:
            self.settings = Settings()
            self.settings_error = f'Could not load settings; defaults shown: {exc}'
        # Basic mode is three ticks against the built-in profiles; advanced mode shows every profile. One list serves
        # both, so the built-in ones are always in it.
        fresh = not any(p.name in built_in_profiles() for p in self.settings.profiles)
        self.profiles = list(with_built_ins(self.settings.profiles))
        self.mode = self.settings.mode
        self.advanced_names = list(self.settings.advanced_enabled)
        if self.mode == 'basic':
            self.leave_advanced(opening=True)
            if fresh:   # a first run: trimming is the thing most people came for, and nothing else is in use
                self.set_built_in(TRIM, enabled=True)
                self.advanced_names = []
        self.restore_window()
        self.health_checks = []
        self.installer = None
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        process = QWidget()
        self.outer = outer = QVBoxLayout(process)
        self.tabs.addTab(process, 'Process')
        self.review_tab = ReviewTab()
        self.review_tab.go_to_process.connect(lambda: self.tabs.setCurrentIndex(0))
        self.review_tab.reviews_changed.connect(self.recut_now)
        self.tabs.addTab(self.review_tab, 'Review')
        self.tabs.currentChanged.connect(self.tab_changed)
        self.build_health_banner()
        self.build_mode_switch()
        self.build_columns()
        self.build_folders()
        self.build_basic()
        self.build_profiles()
        self.build_advanced()
        self.build_actions()
        self.show_mode()

    # --- basic and advanced: two screens over the same profiles ---------------------------------------------------
    def build_mode_switch(self):
        row = QHBoxLayout()
        self.mode_buttons = {}
        for mode, label, tip in (('basic', 'Basic', 'Three choices and two folders. Nothing else to set.'),
                                 ('advanced', 'Advanced', 'Every profile and every setting.')):
            button = QPushButton(label)
            button.setObjectName('modeBasic' if mode == 'basic' else 'modeAdvanced')
            button.setCheckable(True)
            button.setToolTip(tip)
            button.clicked.connect(lambda checked=False, m=mode: self.set_mode(m))
            self.mode_buttons[mode] = button
            row.addWidget(button)
        row.addStretch()
        self.rules_button = QPushButton(help_text.RULES_TITLE)
        self.rules_button.setToolTip('The rules the app follows that are not settings: the order of the parts of a '
                                     'jump, what sound may change, and how matches become clips.')
        self.rules_button.clicked.connect(lambda: RulesDialog(self).exec())
        self.check_button = QPushButton('Check for updates')
        self.check_button.setToolTip('Asks GitHub, where Skydive Cutter is published, whether a newer version is out. '
                                     'Nothing is downloaded or installed for you.')
        self.check_button.clicked.connect(self.check_now)
        row.addWidget(self.rules_button)
        row.addWidget(self.check_button)
        self.outer.addLayout(row)
        # No button of its own: it is for the day something looks wrong on a machine nobody else can see.
        QShortcut(QKeySequence('Ctrl+Shift+D'), self, activated=self.save_diagnostics)

    def save_diagnostics(self):
        from app.ui.about import save_diagnostics
        try:
            path = save_diagnostics(self)
        except OSError as exc:
            self.show_warning(f'The diagnostics file could not be written: {exc}')
            return
        QApplication.clipboard().setText(path.read_text(encoding='utf-8'))
        self.status.setText(f'Diagnostics saved as {path.name} in the app\'s logs folder, and copied so you can paste '
                            'them into a message.')

    def profile_named(self, name):
        return next((p for p in self.profiles if p.name == name), None)

    def set_built_in(self, name, **changes):
        """Change one built-in profile in place; it is put back if it was removed."""
        for index, profile in enumerate(self.profiles):
            if profile.name == name:
                self.profiles[index] = replace(profile, **changes)
                return
        self.profiles.append(replace(built_in_profiles()[name], **changes))

    def leave_advanced(self, opening=False):
        """Basic mode runs only the built-in profiles: the others are switched off, and remembered for coming back.

        ``opening``: the window is starting on the Basic screen, where they are already off and the list saved last
        time is the one to keep. Leaving Advanced by hand always replaces it, so a profile switched off there stays
        off.
        """
        built = built_in_profiles()
        own = [p.name for p in self.profiles if p.enabled and p.name not in built]
        if own or not opening:
            self.advanced_names = own
        self.profiles = [p if p.name in built else replace(p, enabled=False) for p in self.profiles]

    def set_mode(self, mode):
        if mode != self.mode:
            if mode == 'basic':
                self.leave_advanced()
            else:   # the profiles that were in use the last time this screen was showing come back on
                self.profiles = [replace(p, enabled=True) if p.name in self.advanced_names else p
                                 for p in self.profiles]
            self.mode = mode
            self.refresh_profiles()
        self.show_mode()

    def show_mode(self):
        basic = self.mode == 'basic'
        for mode, button in self.mode_buttons.items():
            button.setChecked(mode == self.mode)
        self.basic_panel.setVisible(basic)
        self.profile_group.setVisible(not basic)
        self.advanced_toggle.setVisible(not basic)
        self.advanced.setVisible(not basic and self.advanced_toggle.isChecked())
        self.load_basic()
        self.update_gates()

    def build_basic(self):
        """Three boxes, one per built-in choice, with the only settings a first run could want."""
        self.basic_panel = QWidget()
        box = QVBoxLayout(self.basic_panel)
        box.setContentsMargins(0, 2, 0, 2)
        box.setSpacing(6)
        self.cards = {}

        def card(key, name, help_key, words):
            frame = QFrame()
            frame.setObjectName(name)
            inner = QVBoxLayout(frame)
            inner.setContentsMargins(14, 7, 10, 7)
            head = QHBoxLayout()
            tick = QCheckBox(help_text.label(help_key))
            tick.setObjectName('cardTitle')
            tick.toggled.connect(self.basic_changed)
            head.addWidget(tick)
            head.addStretch()
            changed = QLabel('Changed in advanced mode')
            changed.setObjectName('hint')
            reset = QPushButton('Put back')
            reset.setObjectName('chip')
            reset.setToolTip('Return this choice to its built-in settings.')
            reset.clicked.connect(lambda checked=False, k=key: self.reset_built_in(k))
            head.addWidget(changed)
            head.addWidget(reset)
            head.addWidget(HelpButton(help_key))
            inner.addLayout(head)
            said = QLabel(words)
            said.setObjectName('hint')
            said.setWordWrap(True)
            inner.addWidget(said)
            self.cards[key] = {'tick': tick, 'changed': changed, 'reset': reset, 'frame': frame, 'layout': inner}
            box.addWidget(frame)
            return inner

        def seconds(value):
            spin = decimal_spin(value, maximum=MOST_SECONDS_EITHER_SIDE)
            spin.setDecimals(1)
            spin.setSingleStep(.5)
            spin.setFixedWidth(84)
            spin.valueChanged.connect(self.basic_changed)
            return spin

        inner = card(TRIM, 'cardTrim', 'basic_trim',
                     'Cuts each video down to the jump, so it takes up less space. The plane ride, the canopy '
                     'flight and the walk back are left out.')
        row = QHBoxLayout()
        self.trim_before = seconds(2.0)
        row.addWidget(QLabel('Start'))
        row.addWidget(self.trim_before)
        row.addWidget(QLabel('seconds before exit'))
        row.addStretch()
        inner.addLayout(row)
        row = QHBoxLayout()
        self.trim_landing = QCheckBox('Also keep the landing, with')
        self.trim_landing.toggled.connect(self.basic_changed)
        self.landing_seconds = seconds(5.0)
        row.addWidget(self.trim_landing)
        row.addWidget(self.landing_seconds)
        row.addWidget(QLabel('seconds either side'))
        row.addStretch()
        inner.addLayout(row)

        inner = card(A_GRADE, 'cardA', 'basic_a',
                     'The best video: someone close to the camera, filling at least 20% of the picture.')
        self.a_exit = QCheckBox('Include the exit')
        self.a_exit.toggled.connect(self.basic_changed)
        inner.addWidget(self.a_exit)
        self.a_canopy = QCheckBox('Include canopy flight with others in view (2 people, 20% of the picture)')
        self.a_canopy.toggled.connect(self.basic_changed)
        inner.addWidget(self.a_canopy)

        card(B_GRADE, 'cardB', 'basic_b',
             'Not as good, but worth keeping when A grade is not enough: people are smaller in the picture and '
             'the camera wanders.')
        self.basic_note = QLabel('Each choice gets its own folder inside your clips folder.')
        self.basic_note.setToolTip('The folders are Trimmed, A grade and B grade. Clips are named after the video '
                                   'they came from.')
        self.basic_note.setObjectName('hint')
        self.basic_note.setWordWrap(True)
        box.addWidget(self.basic_note)
        self.column.addWidget(self.basic_panel)

    def load_basic(self):
        """Show the built-in profiles' state in the boxes."""
        widgets = [card['tick'] for card in self.cards.values()] + [self.trim_before, self.trim_landing,
                                                                    self.landing_seconds, self.a_exit, self.a_canopy]
        for widget in widgets:
            widget.blockSignals(True)
        named = {name: self.profile_named(name) or built_in_profiles()[name] for name in built_in_profiles()}
        for name, card in self.cards.items():
            card['tick'].setChecked(named[name].enabled)
        self.trim_before.setValue(min(MOST_SECONDS_EITHER_SIDE, named[TRIM].margin_before_seconds))
        self.trim_landing.setChecked(named[LANDING].enabled and named[TRIM].enabled)
        self.landing_seconds.setValue(min(MOST_SECONDS_EITHER_SIDE, named[LANDING].margin_before_seconds))
        self.a_exit.setChecked('exit' in named[A_GRADE].phases)
        self.a_canopy.setChecked(named[A_CANOPY].enabled and named[A_GRADE].enabled)
        for widget in widgets:
            widget.blockSignals(False)
        self.update_basic()

    def update_basic(self):
        """Grey out a box's own settings while it is unticked, and say when a choice is no longer the built-in one."""
        trim, a_grade = self.cards[TRIM]['tick'].isChecked(), self.cards[A_GRADE]['tick'].isChecked()
        for widget in (self.trim_before, self.trim_landing):
            widget.setEnabled(trim)
        self.landing_seconds.setEnabled(trim and self.trim_landing.isChecked())
        self.a_exit.setEnabled(a_grade)
        self.a_canopy.setEnabled(a_grade)
        for name, card in self.cards.items():
            changed = self.customised(name)
            card['changed'].setVisible(changed)
            card['reset'].setVisible(changed)

    def customised(self, name):
        """True when a built-in profile, or its companion, no longer has its built-in settings.

        Whether it is in use, and what basic mode itself offers (the seconds, A grade's exit), are not counted as
        changes.
        """
        own = {'enabled': True, 'margin_before_seconds': 0.0, 'margin_after_seconds': 0.0}
        for each in {TRIM: (TRIM, LANDING), A_GRADE: (A_GRADE, A_CANOPY), B_GRADE: (B_GRADE,)}[name]:
            now = self.profile_named(each)
            fixed = dict(own) if each in (TRIM, LANDING) else {'enabled': True}
            if each == TRIM:
                fixed.pop('margin_after_seconds')
            if each == A_GRADE and now is not None:
                now = replace(now, phases=now.phases | {'exit'})
            if now is not None and replace(now, **fixed) != replace(built_in_profiles()[each], **fixed):
                return True
        return False

    def reset_built_in(self, name):
        for each in {TRIM: (TRIM, LANDING), A_GRADE: (A_GRADE, A_CANOPY), B_GRADE: (B_GRADE,)}[name]:
            now = self.profile_named(each)
            fresh = {k: v for k, v in built_in_profiles()[each].__dict__.items() if k != 'name'}
            self.set_built_in(each, **{**fresh, 'enabled': bool(now and now.enabled)})
        self.refresh_profiles()
        self.load_basic()

    def basic_changed(self, *_):
        """A box was ticked or a number changed: write it into the built-in profiles."""
        trim, a_grade = self.cards[TRIM]['tick'].isChecked(), self.cards[A_GRADE]['tick'].isChecked()
        either_side = self.landing_seconds.value()
        self.set_built_in(TRIM, enabled=trim, margin_before_seconds=self.trim_before.value())
        self.set_built_in(LANDING, enabled=trim and self.trim_landing.isChecked(),
                          margin_before_seconds=either_side, margin_after_seconds=either_side)
        phases = (self.profile_named(A_GRADE) or built_in_profiles()[A_GRADE]).phases
        self.set_built_in(A_GRADE, enabled=a_grade,
                          phases=phases | {'exit'} if self.a_exit.isChecked() else phases - {'exit'})
        self.set_built_in(A_CANOPY, enabled=a_grade and self.a_canopy.isChecked())
        self.set_built_in(B_GRADE, enabled=self.cards[B_GRADE]['tick'].isChecked())
        self.refresh_profiles()
        self.update_basic()

    def build_health_banner(self):
        """The banner that names anything this install is missing."""
        # --- what this install is missing, above everything else ---------------------------------------------------
        self.health_banner = QLabel()
        self.health_banner.setObjectName('banner')
        self.health_banner.setWordWrap(True)
        self.health_banner.setTextFormat(Qt.PlainText)
        self.fix_button = QPushButton('Install now')
        self.fix_button.setObjectName('fix')
        self.fix_button.clicked.connect(self.install_missing)
        self.details_button = QPushButton('Details')
        self.details_button.clicked.connect(self.show_health_details)
        banner = QHBoxLayout()
        banner.addWidget(self.health_banner, 1)
        banner.addWidget(self.fix_button)
        banner.addWidget(self.details_button)
        self.banner_widgets = [self.health_banner, self.fix_button, self.details_button]
        for widget in self.banner_widgets:
            widget.hide()
        self.outer.addLayout(banner)
        # --- a newer version, when there is one ---------------------------------------------------------------------
        self.update_page = ''
        self.update_checker = None
        self.update_banner = QLabel()
        self.update_banner.setObjectName('bannerUpdate')
        self.update_banner.setTextFormat(Qt.PlainText)
        self.update_button = QPushButton('Get the update')
        self.update_button.setObjectName('primary')
        self.update_button.setToolTip('Opens the download page in your browser. Nothing is installed for you.')
        self.update_button.clicked.connect(self.open_update_page)
        self.update_later = QPushButton('Not now')
        update = QHBoxLayout()
        update.addWidget(self.update_banner, 1)
        update.addWidget(self.update_button)
        update.addWidget(self.update_later)
        self.update_widgets = [self.update_banner, self.update_button, self.update_later]
        self.update_later.clicked.connect(lambda: [widget.hide() for widget in self.update_widgets])
        for widget in self.update_widgets:
            widget.hide()
        self.outer.addLayout(update)

    def check_for_update(self):
        """Ask once, in the background, whether a newer version is published. Off in a development folder."""
        from app.update import installed_version
        if not self.settings.check_updates or not installed_version() or self.update_checker is not None:
            return
        self.update_checker = UpdateCheck(self)
        self.update_checker.found.connect(self.show_update)
        self.update_checker.start()

    def check_now(self):
        """The Check for updates button: ask whatever the start-up setting says, and always give an answer."""
        from app.update import installed_version
        if not installed_version():
            self.status.setText('This copy runs from a development folder, so it has no version to compare.')
            return
        self.check_button.setEnabled(False)
        self.status.setText('Checking for a newer version…')
        self.asked_checker = UpdateCheck(self, always_answer=True)
        self.asked_checker.found.connect(self.show_update)
        self.asked_checker.answered.connect(self.update_answer)
        self.asked_checker.start()

    def update_answer(self, answer, version):
        from app.update import LATEST_INSTALLED, NEWER, installed_version
        self.check_button.setEnabled(True)
        self.status.setText(
            f'Skydive Cutter {version} is available. Get the update is at the top of the window.' if answer == NEWER
            else f'You have the latest version, {installed_version()}.' if answer == LATEST_INSTALLED
            else 'Could not check for a newer version. Check the internet connection and try again.')

    def show_update(self, version, page):
        from app.update import installed_version
        self.update_page = page
        self.update_banner.setText(f'Skydive Cutter {version} is available. You have {installed_version()}.')
        for widget in self.update_widgets:
            widget.show()

    def open_update_page(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(self.update_page))

    def build_columns(self):
        """The two columns and the scroll area that holds the settings."""
        # --- two columns: settings on the left, results on the right, one scrollbar for both -----------------------
        # The settings column scrolls on its own, so the results list beside it always fills the window.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.controls = QWidget()
        self.column = layout = QVBoxLayout(self.controls)
        self.column.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self.controls)
        scroll.setMinimumWidth(440)
        self.results = ResultsPanel()
        self.results.open_in_review.connect(self.open_video_in_review)
        self.results.process_again.connect(self.process_again)
        self.results.setMinimumHeight(170)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(scroll)
        splitter.addWidget(self.results)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 7)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([620, 860])
        if self.settings.column_state:
            try:
                splitter.restoreState(QByteArray.fromBase64(self.settings.column_state.encode('ascii')))
            except (ValueError, TypeError):
                pass
        self.outer.addWidget(splitter, 1)
        self.scroll = scroll
        self.splitter = splitter
        self.speed = SpeedStore(PROJECT_ROOT / 'app' / 'speed.json')
        self.prober = None

    def build_folders(self):
        """Input and Clips: the only two choices a first run needs."""
        # --- folders: the only two choices a first run needs ---------------------------------------------------
        folders = QGroupBox('Folders')
        form = QFormLayout(folders)
        self.folder_edits = {}
        self.folder_buttons = {}
        for name, hint in [('input_folder', 'The folder with your jump videos (folders inside it are included)'),
                           ('output_folder', 'Where the clips go (outside the videos folder)')]:
            form.addRow(help_text.label(name), with_help(self.folder_row(name, hint), name))
        tip_row = QHBoxLayout()
        drop = QLabel('Tip: you can drag a folder from Explorer onto these boxes.')
        drop.setObjectName('hint')
        tip_row.addWidget(drop)
        tip_row.addStretch()
        self.advanced_toggle = QPushButton('Hide advanced settings')
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setChecked(True)
        self.advanced_toggle.setToolTip('What is produced, how clips are organised, how fast it runs, and how people '
                                        'are counted.')
        self.advanced_toggle.toggled.connect(self.toggle_advanced)
        tip_row.addWidget(self.advanced_toggle)
        form.addRow(tip_row)
        self.column.addWidget(folders)

    def build_profiles(self):
        """The Keep profiles table and its buttons."""
        # --- keep profiles -----------------------------------------------------------------------------------------
        self.profile_group = group = QGroupBox(help_text.label('profiles'))
        profiles_layout = QVBoxLayout(group)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['In use', 'Name', 'Parts of the jump', 'People', 'Fill', 'Extra'])
        self.table.verticalHeader().setVisible(False)
        for column, name in enumerate(['enabled', 'name', 'phases', 'min_person_count', 'min_total_area_percent',
                                       'margin_before_seconds']):
            self.table.horizontalHeaderItem(column).setToolTip(help_text.text(name))
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setMinimumHeight(150)
        self.table.setMaximumHeight(240)
        self.table.cellDoubleClicked.connect(lambda *_: self.edit_profile())
        self.table.itemChanged.connect(self.profile_checked)
        profiles_layout.addWidget(self.table)
        row = QHBoxLayout()
        for label, action in [('Add', self.add_profile), ('Edit', self.edit_profile),
                              ('Duplicate', self.duplicate_profile), ('Remove', self.remove_profile)]:
            button = QPushButton(label)
            button.clicked.connect(action)
            row.addWidget(button)
        self.preset_button = QPushButton(help_text.label('presets'))
        self.preset_button.setToolTip(help_text.text('presets'))
        self.preset_menu = QMenu(self.preset_button)
        self.preset_button.setMenu(self.preset_menu)
        self.preset_menu.aboutToShow.connect(self.fill_presets)
        row.addWidget(self.preset_button)
        row.addStretch()
        row.addWidget(HelpButton('profiles'))
        profiles_layout.addLayout(row)
        # In words, what the ticked profiles add up to: the list above says which, this says what.
        self.keeping = QLabel()
        self.keeping.setWordWrap(True)
        self.keeping.setTextFormat(Qt.PlainText)
        profiles_layout.addWidget(self.keeping)
        self.gate_note = QLabel()
        self.gate_note.setObjectName('hint')
        self.gate_note.setWordWrap(True)
        profiles_layout.addWidget(self.gate_note)
        self.column.addWidget(group)

    def build_advanced(self):
        """Advanced settings: Output, Processing and People, each folding."""
        # --- advanced: folding sections under the profiles, in the same column --------------------------------
        self.advanced = QGroupBox('Advanced settings')
        advanced_box = QVBoxLayout(self.advanced)
        advanced_box.setContentsMargins(6, 4, 6, 6)
        advanced_box.setSpacing(2)
        self.sections = {}
        for key, title in (('output', 'Output'), ('processing', 'Processing'), ('people', 'People')):
            section = Section(key, title)
            section.folded.connect(self.sections_changed)
            self.sections[key] = section
            advanced_box.addWidget(section)

        advanced = self.sections['output'].form
        self.output_mode = QComboBox()
        self.output_mode.addItem('Clips and timelines', True)
        self.output_mode.addItem('Timelines only - no clips', False)
        self.output_mode.setCurrentIndex(0 if self.settings.cut_enabled else 1)
        advanced.addRow(help_text.label('cut_enabled'), with_help(self.output_mode, 'cut_enabled'))
        self.output_layout = QComboBox()
        for identifier, label in OUTPUT_LAYOUTS.items():
            self.output_layout.addItem(label, identifier)
        self.output_layout.setCurrentIndex(self.output_layout.findData(self.settings.output_layout))
        advanced.addRow(help_text.label('output_layout'), with_help(self.output_layout, 'output_layout'))
        self.layout_note = QLabel()
        self.layout_note.setObjectName('hint')
        self.layout_note.setWordWrap(False)
        self.layout_note.setTextFormat(Qt.PlainText)
        advanced.addRow(self.layout_note)
        csv_box = QVBoxLayout()
        self.csv_in_clips = QRadioButton('In the clips folder (a "timelines" folder)')
        self.csv_elsewhere = QRadioButton('Somewhere else:')
        csv_box.addWidget(self.csv_in_clips)
        csv_box.addWidget(self.csv_elsewhere)
        csv_box.addLayout(with_help(self.folder_row('csv_folder', 'Choose the folder for timelines'), 'csv_folder'))
        advanced.addRow(help_text.label('csv_folder'), csv_box)
        saved_csv, saved_clips = self.settings.csv_folder, self.settings.output_folder
        in_clips = not saved_csv or (bool(saved_clips) and Path(saved_csv) == Path(saved_clips) / 'timelines')
        (self.csv_in_clips if in_clips else self.csv_elsewhere).setChecked(True)
        if in_clips:
            self.folder_edits['csv_folder'].clear()
        self.csv_in_clips.toggled.connect(self.update_output_mode)
        self.output_note = QLabel()  # shown as the Create box's tooltip, to keep the column short

        advanced = self.sections['processing'].form
        self.phase_toggle = QCheckBox(help_text.label('phases_enabled'))
        self.phase_toggle.setChecked(self.settings.phases_enabled)
        advanced.addRow(with_help(self.phase_toggle, 'phases_enabled'))
        self.classifier = QComboBox()
        for classifier in available_classifiers():
            self.classifier.addItem(classifier.display_name, classifier.identifier)
        self.classifier.setCurrentIndex(max(0, self.classifier.findData(self.settings.phase_classifier)))
        classifier_row = with_help(self.classifier, 'phase_classifier')
        advanced.addRow(help_text.label('phase_classifier'), classifier_row)
        advanced.setRowVisible(classifier_row, self.classifier.count() > 1)  # nothing to choose from in the release
        self.device = QComboBox()
        for value, label in device_choices():
            self.device.addItem(label, value)
        self.device.setCurrentIndex(max(0, self.device.findData(self.settings.device)))
        self.device.currentIndexChanged.connect(lambda _index: self.refresh_health())
        advanced.addRow(help_text.label('device'), with_help(self.device, 'device'))
        self.parallel = QComboBox()
        for count in range(1, MAX_PARALLEL_VIDEOS + 1):
            self.parallel.addItem(str(count), count)
        self.parallel.addItem('Automatic', 0)
        self.parallel.setCurrentIndex(max(0, self.parallel.findData(self.settings.parallel_videos)))
        advanced.addRow(help_text.label('parallel_videos'), with_help(self.parallel, 'parallel_videos'))
        self.hardware_decode = QComboBox()
        self.hardware_decode.addItem('Automatic (graphics card when it can)', 'auto')
        self.hardware_decode.addItem('Processor only', 'off')
        self.hardware_decode.setCurrentIndex(max(0, self.hardware_decode.findData(self.settings.hardware_decode)))
        advanced.addRow(help_text.label('hardware_decode'), with_help(self.hardware_decode, 'hardware_decode'))
        self.batch_size = QSpinBox()
        self.batch_size.setRange(1, 64)
        self.batch_size.setValue(self.settings.batch_size)
        advanced.addRow(help_text.label('batch_size'), with_help(self.batch_size, 'batch_size'))
        self.view_mode = QComboBox()
        for identifier, label in VIEW_MODES.items():
            self.view_mode.addItem(label, identifier)
        self.view_mode.setCurrentIndex(max(0, self.view_mode.findData(self.settings.view_mode)))
        advanced.addRow(help_text.label('view_mode'), with_help(self.view_mode, 'view_mode'))
        self.recut = QCheckBox(help_text.label('recut_on_review'))
        self.recut.setChecked(self.settings.recut_on_review)
        advanced.addRow(with_help(self.recut, 'recut_on_review'))
        self.check_updates = QCheckBox(help_text.label('check_updates'))
        self.check_updates.setChecked(self.settings.check_updates)
        advanced.addRow(with_help(self.check_updates, 'check_updates'))

        advanced = self.sections['people'].form
        self.people_toggle = QCheckBox(help_text.label('people_enabled'))
        self.people_available = people_installed(self.settings)
        self.people_toggle.setChecked(self.settings.people_enabled and self.people_available)
        advanced.addRow(with_help(self.people_toggle, 'people_enabled'))
        self.sample_rate = decimal_spin(self.settings.sample_fps, maximum=60, minimum=.01)
        self.confidence = decimal_spin(self.settings.detection_confidence, maximum=1, minimum=.01)
        self.detector = QComboBox()
        for label, path in available_detectors(self.settings.yolo_model):
            self.detector.addItem(label, path)
        using = Path(self.settings.yolo_model).name.casefold()
        chosen = next((i for i in range(self.detector.count())
                       if Path(self.detector.itemData(i)).name.casefold() == using), 0)
        self.detector.setCurrentIndex(chosen)
        advanced.addRow(help_text.label('yolo_model'), with_help(self.detector, 'yolo_model'))
        advanced.addRow(help_text.label('sample_fps'), with_help(self.sample_rate, 'sample_fps'))
        advanced.addRow(help_text.label('detection_confidence'), with_help(self.confidence, 'detection_confidence'))
        self.people_note = QLabel('Installed with the app. Usage statistics are switched off.')
        self.people_note.setObjectName('hint')
        self.people_note.setWordWrap(True)
        advanced.addRow(self.people_note)

        self.column.addWidget(self.advanced)
        self.column.addStretch()
        for key in self.settings.open_sections or ():
            if key in self.sections:
                self.sections[key].set_open(True)

    def build_actions(self):
        """The run bar, progress bars and log, pinned under the columns."""
        # --- actions, progress and log (always visible) -------------------------------------------------------------
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setTextFormat(Qt.PlainText)
        self.warning.setStyleSheet('background: #573e18; color: #fff1cd; padding: 10px;')
        self.warning.hide()
        self.outer.addWidget(self.warning)
        row = QHBoxLayout()
        self.process_button = QPushButton('Process videos')
        self.process_button.setObjectName('primary')
        self.process_button.clicked.connect(lambda: self.start_session(not self.keep_watching.isChecked()))
        self.keep_watching = QCheckBox(help_text.label('keep_watching'))
        self.keep_watching.setChecked(self.settings.keep_watching)
        self.keep_watching.setToolTip(help_text.text('keep_watching'))
        self.stop_button = QPushButton('Stop')
        self.stop_button.setObjectName('stop')
        self.stop_button.clicked.connect(self.stop_session)
        self.stop_button.setEnabled(False)
        self.review_labels_button = QPushButton('Review cuts in labeller')
        self.review_labels_button.setToolTip('Open the Review tab: every processed video with the model, audio and '
                                             'motion tracks lined up, and the clips that were cut.')
        self.review_labels_button.clicked.connect(lambda: self.tabs.setCurrentIndex(1))
        row.addWidget(self.process_button)
        row.addWidget(self.keep_watching)
        row.addWidget(HelpButton('keep_watching'))
        row.addWidget(self.stop_button)
        row.addStretch()
        row.addWidget(self.review_labels_button)
        self.outer.addLayout(row)
        self.status = QLabel('Ready. Process videos handles the videos in the input folder; tick "Keep watching" to '
                             'carry on with new ones as they arrive.')
        self.status.setWordWrap(True)
        self.outer.addWidget(self.status)
        self.queue_bar = QProgressBar()
        self.queue_bar.setRange(0, 100)
        self.queue_bar.setValue(0)
        self.queue_bar.setFormat('Waiting for videos')
        self.outer.addWidget(self.queue_bar)
        # One name and bar for each video that can run side by side; only the first shows until more are running.
        self.video_labels, self.video_bars = [], []
        for slot in range(MAX_PARALLEL_VIDEOS):
            label = QLabel('Current video')
            label.setWordWrap(True)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setFormat('No video processing')
            for widget in (label, bar):
                self.outer.addWidget(widget)
                widget.setVisible(slot == 0)
            self.video_labels.append(label)
            self.video_bars.append(bar)
        self.video_label, self.video_bar = self.video_labels[0], self.video_bars[0]
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(4000)
        self.log.setMinimumHeight(44)
        self.log.setMaximumHeight(110)
        self.outer.addWidget(self.log)
        self.phase_toggle.toggled.connect(self.update_gates)
        self.people_toggle.toggled.connect(self.update_gates)
        self.output_mode.currentIndexChanged.connect(self.update_output_mode)
        self.output_layout.currentIndexChanged.connect(self.update_output_mode)
        self.cuda = None
        self.refresh_profiles()
        self.update_gates()
        self.update_output_mode()
        self.refresh_health(cuda=None)
        QTimer.singleShot(50, self.check_gpu)
        QTimer.singleShot(1500, self.check_for_update)
        if self.settings_error:
            self.show_warning(self.settings_error)
        self.folder_edits['output_folder'].editingFinished.connect(self.refresh_results)
        self.folder_edits['csv_folder'].editingFinished.connect(self.refresh_results)
        self.refresh_results()
        if self.open_review:
            self.tabs.setCurrentIndex(1)

    # --- the run in progress, seen through the window ---------------------------------------------------------------
    @property
    def ledger(self):
        return self.session.ledger if self.session else None

    @property
    def ledger_path(self):
        return self.session.ledger_path if self.session else None

    @property
    def queue(self):
        return self.session.queue if self.session else deque()

    @property
    def processor(self):
        return self.session.processor if self.session else None

    @property
    def worker(self):
        """A video in progress, or None when nothing is running."""
        return next(iter(self.workers.values()), None)

    def refresh_health(self, cuda=None):
        """Ask what this install has, then show it. The GPU answer costs an import, so it arrives separately."""
        settings = self.settings if not self.isVisible() else self.read_settings()
        self.health_checks = check_install(settings, cuda_available=cuda if cuda is not None else self.cuda)
        self.apply_health()

    def apply_health(self):
        stoppers = blocking(self.health_checks)
        message = summary(self.health_checks)
        worst = ERROR if stoppers else (WARNING if message else '')
        for check in self.health_checks:
            if check.section in self.sections:
                self.sections[check.section].set_state(check.state, check.detail if check.state != 'ok' else '')
                if check.state == ERROR:
                    self.open_section(check.section)
        self.health_banner.setObjectName('banner' if worst == ERROR else 'bannerWarning')
        self.health_banner.style().unpolish(self.health_banner)
        self.health_banner.style().polish(self.health_banner)
        held = '\nProcessing is held until this is fixed.'
        self.health_banner.setText(message + (held if stoppers else ''))
        repairable = any(check.repairable for check in stoppers)
        self.health_banner.setVisible(bool(message))
        self.details_button.setVisible(bool(message))
        self.fix_button.setVisible(repairable and self.installer is None)
        self.people_note.setText('Installed with the app. Usage statistics are switched off.' if self.people_available
                                 else 'The person detector is missing. Install it, or take the people filters out of '
                                      'your profiles.')
        self.people_toggle.setEnabled(self.people_available)
        if not self.people_available:
            self.people_toggle.setChecked(False)
        self.update_process_button()

    def update_process_button(self):
        stoppers = blocking(self.health_checks)
        running = self.active or bool(self.workers)
        self.process_button.setEnabled(not stoppers and not running)
        if stoppers:
            first = stoppers[0]
            self.process_button.setToolTip(f'{first.label}: {first.detail}')
            if first.key == 'people':
                self.status.setText('Install people detection first, or switch the people filters off in your profiles.')
            else:
                self.status.setText(f'{first.label}: {first.detail}')
        else:
            self.process_button.setToolTip('')

    def show_health_details(self):
        lines = []
        for check in self.health_checks:
            mark = {ERROR: 'x', WARNING: '!', 'ok': 'ok'}[check.state]
            lines.append(f'[{mark}] {check.label}: {check.detail}')
        QMessageBox.information(self, 'What this install has', '\n'.join(lines))

    def install_missing(self):
        """Run the installer that came with the app, in its own window, then look again."""
        argv, script = installer_argv(PROJECT_ROOT)
        if not script.is_file():
            QMessageBox.warning(self, 'Installer not found',
                                f'{script.name} is missing from the app folder. Unpack the download again.')
            return
        import subprocess
        self.installer = subprocess.Popen(argv, cwd=str(PROJECT_ROOT), **visible_console())
        self.fix_button.setVisible(False)
        self.status.setText('Installing the missing pieces. This window carries on when it finishes.')
        self.installer_timer = QTimer(self)
        self.installer_timer.timeout.connect(self.check_installer)
        self.installer_timer.start(1000)

    def check_installer(self):
        if self.installer is None or self.installer.poll() is None:
            return
        finished = self.installer.returncode
        self.installer_timer.stop()
        self.installer = None
        self.people_available = people_installed(self.read_settings())
        if self.people_available:
            self.people_toggle.setChecked(True)
        self.refresh_health()
        self.status.setText('Everything is installed. Process videos is ready.' if finished == 0 and
                            not blocking(self.health_checks) else
                            'The installer finished with problems. Open its window again, or see the logs folder.')

    def restore_window(self):
        """Open at a size that suits this screen, or exactly where it was left last time.

        Never larger than the screen has room for. A window asked to be bigger than its screen is cut off at the
        bottom on a small laptop, and on a Mac the system moves and shrinks it without the app being told.
        """
        screen = QApplication.primaryScreen()
        area = screen.availableGeometry() if screen else None
        if area:
            room_w, room_h = area.width() - FRAME_ALLOWANCE[0], area.height() - FRAME_ALLOWANCE[1]
            self.resize(min(max(int(area.width() * .85), 1120), 2400, room_w),
                        min(max(int(area.height() * .85), 720), 1500, room_h))
            self.move(area.left() + (area.width() - self.width()) // 2,
                      area.top() + max(0, (area.height() - self.height() - FRAME_ALLOWANCE[1]) // 3))
        else:
            self.resize(1600, 1000)
        if self.settings.window_geometry:
            try:
                blob = QByteArray.fromBase64(self.settings.window_geometry.encode('ascii'))
                if self.restoreGeometry(blob) and area and not area.intersects(self.geometry()):
                    self.restore_window_default(area)  # the monitor it was on is gone
            except (ValueError, TypeError):
                pass

    def restore_window_default(self, area):
        self.resize(min(1600, area.width() - 40), min(1000, area.height() - 60))
        self.move(area.left() + 40, area.top() + 40)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # On a short window the log gives its room to the settings and the results; it still scrolls.
        if hasattr(self, 'log'):
            self.log.setMaximumHeight(110 if self.height() >= SHORT_WINDOW else 56)

    def showEvent(self, event):
        super().showEvent(event)
        # Not without a real screen: the automated tests size the window for themselves on a pretend one.
        if not self.settled and QApplication.platformName() != 'offscreen':
            self.settled = True
            # Once it is really on a screen (only then is the size of its frame known), make sure all of it is.
            QTimer.singleShot(0, self.keep_on_screen)

    def keep_on_screen(self):
        """Bring an ordinary window wholly inside the screen it is on: smaller if it must be, then moved."""
        if self.windowState() & (Qt.WindowState.WindowMaximized | Qt.WindowState.WindowFullScreen
                                 | Qt.WindowState.WindowMinimized):
            return
        screen = self.screen() or QApplication.primaryScreen()
        if not screen:
            return
        area, frame, inside = screen.availableGeometry(), self.frameGeometry(), self.geometry()
        extra_w, extra_h = frame.width() - inside.width(), frame.height() - inside.height()
        width = min(inside.width(), area.width() - extra_w)
        height = min(inside.height(), area.height() - extra_h)
        if (width, height) != (inside.width(), inside.height()):
            self.resize(max(width, self.minimumWidth()), max(height, self.minimumHeight()))
            frame = self.frameGeometry()
        left = min(max(frame.left(), area.left()), max(area.left(), area.right() + 1 - frame.width()))
        top = min(max(frame.top(), area.top()), max(area.top(), area.bottom() + 1 - frame.height()))
        if (left, top) != (frame.left(), frame.top()):
            self.move(left, top)

    def window_state(self):
        return (bytes(self.saveGeometry().toBase64()).decode('ascii'),
                bytes(self.splitter.saveState().toBase64()).decode('ascii'),
                tuple(key for key, section in self.sections.items() if section.is_open()))


    def folder_row(self, name, hint):
        row = QHBoxLayout()
        edit = QLineEdit(getattr(self.settings, name))
        edit.setPlaceholderText(hint)
        button = QPushButton('Browse…')
        button.clicked.connect(lambda checked=False, e=edit: self.browse(e))
        row.addWidget(edit)
        row.addWidget(button)
        self.folder_edits[name] = edit
        self.folder_buttons[name] = button
        return row

    def toggle_advanced(self, shown):
        """The whole advanced box folds away when it is in the road; each section folds on its own."""
        self.advanced.setVisible(shown and self.mode != 'basic')
        self.advanced_toggle.setText('Hide advanced settings' if shown else 'Advanced settings')

    def sections_changed(self):
        pass  # open sections are read back in read_settings, so they are remembered between sessions

    def open_section(self, key):
        """Bring one section into view, for example the one a missing piece belongs to."""
        if key in self.sections:
            self.advanced_toggle.setChecked(True)
            self.sections[key].set_open(True)
            QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(self.sections[key]))

    def tab_changed(self, index):
        reviewing = index == 1
        if not reviewing:
            self.refresh_results()
        if reviewing:
            try:
                self.review_tab.open(self.read_settings())
            except Exception as exc:  # noqa: BLE001
                self.review_tab.show_message(f'Could not open the review: {exc}')
        self.review_tab.set_active(reviewing)

    # --- drag and drop: a folder dropped on a folder box sets it; anywhere else sets the input folder --------------
    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if (self.controls.isEnabled() and self.tabs.currentIndex() == 0 and urls
                and urls[0].isLocalFile() and Path(urls[0].toLocalFile()).is_dir()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        folder = str(Path(event.mimeData().urls()[0].toLocalFile()))
        target = self.childAt(event.position().toPoint())
        name = next((n for n, edit in self.folder_edits.items()
                     if target is not None and (target is edit or edit.isAncestorOf(target))), 'input_folder')
        if name == 'csv_folder':
            self.csv_elsewhere.setChecked(True)
        self.folder_edits[name].setText(folder)
        event.acceptProposedAction()

    # --- results list, reviewing and re-cutting --------------------------------------------------------------------
    def current_entries(self):
        settings = self.read_settings()
        folder = settings.output_folder if settings.cut_enabled else settings.csv_folder
        if not folder:
            return None, {}
        state = state_directory(settings)
        if self.active and self.settings == settings:
            return state, self.ledger['entries']
        path = state / 'ledger.json'
        try:
            entries = load_ledger(path)['entries'] if path.is_file() else {}
            return state, rebase_entries(entries, state, settings.csv_folder)
        except (OSError, ValueError):
            return state, {}

    def refresh_results(self):
        try:
            state, entries = self.current_entries()
            self.results.load(state, entries, self.read_settings().input_folder)
        except Exception as exc:  # noqa: BLE001 - the list is informational; never block the app
            self.results.summary.setText(f'Could not read the results: {exc}')

    def open_video_in_review(self, source):
        self.tabs.setCurrentIndex(1)
        if not self.review_tab.show_video(source):
            self.show_warning('That video is not in the review yet. Process it first.')

    def process_again(self, source_keys):
        """Forget these videos' completion so the next processing run (or the running one) handles them again."""
        keys = [source_keys] if isinstance(source_keys, str) else list(source_keys)
        many = f'{len(keys)} videos' if len(keys) > 1 else 'It'
        if self.active:
            for source_key in keys:
                self.session.forget(source_key)
            self.append_log(f'{many} queued again, after the videos already waiting.')
        else:
            state, _entries = self.current_entries()
            if state is None:
                return
            with RunLock(state, 'monitor.lock'):
                ledger = load_ledger(state / 'ledger.json')
                for source_key in keys:
                    ledger['entries'].pop(source_key, None)
                save_ledger(state / 'ledger.json', ledger)
            self.status.setText(f'{many} will be processed the next time you click Process videos.')
        self.refresh_results()

    def recut_now(self, source):
        """A video was marked reviewed or not skydiving in the Review tab: cut it again from those labels."""
        if not self.recut.isChecked():
            self.append_log('Review saved. It is used the next time you click Process videos.')
            return
        path = Path(source)
        if not path.is_file():
            return
        if self.active:
            self.session.requeue_first(path)
            self.queue_progress.enqueue(1)
            self.update_queue_progress()
            self.append_log(f'Re-cutting {path.name} next, from your labels.')
            self.start_next()
            return
        self.append_log(f'Re-cutting {path.name} from your labels…')
        self.start_session(True, only=[path])

    def browse(self, edit):
        folder = QFileDialog.getExistingDirectory(self, 'Choose folder', edit.text())
        if folder:
            edit.setText(folder)

    def read_settings(self):
        geometry, columns, sections = self.window_state()
        folders = {k: w.text().strip() for k, w in self.folder_edits.items()}
        cut = self.output_mode.currentData()
        if cut and self.csv_in_clips.isChecked():
            folders['csv_folder'] = str(Path(folders['output_folder']) / 'timelines') if folders['output_folder'] else ''
        chosen = replace(self.settings, **folders, mode=self.mode, advanced_enabled=tuple(self.advanced_names),
            phases_enabled=self.phase_toggle.isChecked(), people_enabled=self.people_toggle.isChecked(),
            cut_enabled=cut, phase_classifier=self.classifier.currentData(),
            output_layout=self.output_layout.currentData(), device=self.device.currentData(),
            view_mode=self.view_mode.currentData(),
            batch_size=self.batch_size.value(), keep_watching=self.keep_watching.isChecked(),
            hardware_decode=self.hardware_decode.currentData(), parallel_videos=self.parallel.currentData(),
            recut_on_review=self.recut.isChecked(), check_updates=self.check_updates.isChecked(),
            sample_fps=self.sample_rate.value(), detection_confidence=self.confidence.value(),
            yolo_model=self.detector.currentData() or self.settings.yolo_model,
            window_geometry=geometry, column_state=columns, open_sections=sections,
            profiles=tuple(self.profiles))
        if self.mode != 'basic':
            return chosen
        # Basic mode has no output choices: a folder per choice, clips named after the video, timelines beside them.
        wants_people = any(p.enabled and (p.min_person_count or p.min_total_area_percent) for p in self.profiles)
        clips = folders['output_folder']
        return replace(chosen, output_layout='by_profile', phases_enabled=True, cut_enabled=True,
                       people_enabled=wants_people and self.people_available,
                       csv_folder=str(Path(clips) / 'timelines') if clips else '')

    def update_output_mode(self):
        cutting = self.output_mode.currentData()
        self.folder_edits['output_folder'].setEnabled(cutting)
        self.folder_buttons['output_folder'].setEnabled(cutting)
        self.output_layout.setEnabled(cutting)
        if not cutting and self.csv_in_clips.isChecked():
            self.csv_elsewhere.setChecked(True)  # without clips there is no Clips folder to put them in
        self.csv_in_clips.setEnabled(cutting)
        elsewhere = self.csv_elsewhere.isChecked()
        self.folder_edits['csv_folder'].setEnabled(elsewhere)
        self.folder_buttons['csv_folder'].setEnabled(elsewhere)
        self.folder_edits['csv_folder'].setPlaceholderText(
            'Choose the folder for timelines' if cutting else 'Needed when only timelines are produced')
        example = ('Example: ' + layout_example(self.output_layout.currentData()) if cutting
                   else 'Timelines only; each name includes a short code for its video.')
        # One line always: a long example is shortened in the middle, with the whole path on hover.
        self.layout_note.setText(self.layout_note.fontMetrics().elidedText(
            example, Qt.TextElideMode.ElideMiddle, self.advanced.maximumWidth() - 40))
        self.layout_note.setToolTip(example)
        self.output_note.setText(
            'Clips start at the nearest keyframe, so they can include a second or two extra.' if cutting else
            'No clips are made or changed; profiles still mark matching moments in the timeline.')

    def check_gpu(self):
        """Importing torch takes a moment, so the window is already up when the answer lands."""
        self.cuda = cuda_available()
        self.refresh_health(cuda=self.cuda)

    def update_gates(self):
        phases, people = self.phase_toggle.isChecked(), self.people_toggle.isChecked()
        self.classifier.setEnabled(phases)
        self.sample_rate.setEnabled(people)
        self.confidence.setEnabled(people)
        self.detector.setEnabled(people)
        notes = []
        if not phases:
            notes.append('Working out the parts of each jump is off (Advanced settings), so profiles cannot choose '
                         'parts of the jump.')
        if not phases and not people:
            notes.append('Looking for people is off too: every moment matches each profile in use.')
        self.gate_note.setText(' '.join(notes))
        self.gate_note.setVisible(bool(notes))
        self.update_keeping()
        if self.health_checks:
            self.refresh_health()

    def refresh_profiles(self):
        if self.health_checks:
            QTimer.singleShot(0, self.refresh_health)  # people requirements may have changed
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.profiles))
        for i, p in enumerate(self.profiles):
            values = ['', p.name, ', '.join(phase.replace('_', ' ') for phase in sorted(p.phases)), str(p.min_person_count),
                      f'{p.min_total_area_percent:g}%', f'{p.margin_before_seconds:g}s / {p.margin_after_seconds:g}s']
            values[0] = 'In use' if p.enabled else 'Off'
            for j, value in enumerate(values):
                item = QTableWidgetItem(value)
                if j == 0:
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked if p.enabled else Qt.Unchecked)
                # A profile in use stands out in green; one that is off fades back.
                if p.enabled:
                    item.setBackground(QColor(GOOD_BACKGROUND))
                    item.setForeground(QColor('#ffffff'))
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                else:
                    item.setForeground(QColor(MUTED))
                item.setToolTip(help_text.profile_summary(p))   # the whole of it, whatever the columns cut short
                self.table.setItem(i, j, item)
        self.table.blockSignals(False)
        self.update_keeping()

    def update_keeping(self):
        """Say, in a sentence per profile in use, what a run will keep."""
        if not hasattr(self, 'keeping') or not hasattr(self, 'phase_toggle'):
            return
        phases, people = self.phase_toggle.isChecked(), self.people_toggle.isChecked()
        used = [p for p in self.profiles if p.enabled]
        self.keeping.setObjectName('keeping' if used else 'keepingNothing')
        self.keeping.style().unpolish(self.keeping)
        self.keeping.style().polish(self.keeping)
        self.keeping.setText('\n'.join(['A run will keep:'] + [
            f'  {p.name}: {help_text.profile_summary(p, phases, people)}' for p in used]) if used else
            'Nothing is in use, so a run would keep nothing. Tick "In use" on at least one profile.')

    def profile_checked(self, item):
        if item.column() == 0:
            i = item.row()
            self.profiles[i] = replace(self.profiles[i], enabled=item.checkState() == Qt.Checked)
            QTimer.singleShot(0, self.refresh_profiles)   # redraw the row in its new colours, once this click is done

    def show_editor(self, profile, index=None):
        dialog = ProfileEditor(profile, self.phase_toggle.isChecked(), self.people_toggle.isChecked(), self)
        if dialog.exec():
            proposed = list(self.profiles)
            if index is None:
                proposed.append(dialog.profile)
            else:
                proposed[index] = dialog.profile
            try:
                validate_settings(replace(self.read_settings(), profiles=tuple(proposed)))
            except ValueError as exc:
                QMessageBox.warning(self, 'Invalid profile', str(exc))
                return
            self.profiles = proposed
            self.refresh_profiles()

    def fill_presets(self):
        self.preset_menu.clear()
        for preset in profile_presets(self.people_available):
            phases = ', '.join(p.replace('_', ' ') for p in sorted(preset.phases))
            action = self.preset_menu.addAction(f'{preset.name}  ({phases}; {preset.margin_before_seconds:g}s / '
                                                f'{preset.margin_after_seconds:g}s)')
            action.triggered.connect(lambda checked=False, p=preset: self.add_preset(p))

    def add_preset(self, preset):
        names = {p.name for p in self.profiles}
        name, number = preset.name, 2
        while name in names:
            name, number = f'{preset.name} {number}', number + 1
        self.show_editor(replace(preset, name=name))

    def add_profile(self):
        self.show_editor(KeepProfile(name='New profile'))

    def edit_profile(self):
        index = self.table.currentRow()
        if index >= 0:
            self.show_editor(self.profiles[index], index)

    def duplicate_profile(self):
        index = self.table.currentRow()
        if index >= 0:
            self.show_editor(replace(self.profiles[index], name=self.profiles[index].name + ' copy'))

    def remove_profile(self):
        index = self.table.currentRow()
        if index >= 0:
            self.profiles.pop(index)
            self.refresh_profiles()

    def append_log(self, message):
        self.log.appendPlainText(f'[{datetime.now():%H:%M:%S}] {message}')
        if len(self.workers) == 1:
            label = source_label(self.worker.source, self.settings.input_folder)
            self.status.setText(f'Queue: {len(self.queue)}   Current: {label} — {message[:150]}')
        elif self.workers:
            self.status.setText(f'Queue: {len(self.queue)}   Processing {len(self.workers)} videos at once')

    def worker_log(self, slot, message):
        """A line from one of the videos in progress, named when there is more than one."""
        worker = self.workers.get(slot)
        self.append_log(f'{worker.source.name}: {message}' if worker and len(self.workers) > 1 else message)

    def show_warning(self, message):
        self.warning.setText(message)
        self.warning.show()

    def update_queue_progress(self):
        value, label = self.queue_progress.display()
        estimate = self.estimate_text()
        self.queue_bar.setValue(value)
        self.queue_bar.setFormat(label + (f' · {estimate}' if estimate else ''))

    def estimate_text(self):
        if not self.active or (not self.workers and not self.queue):
            return ''
        if self.prober is None:
            return ''
        queued = [self.prober.get(key(p)) for p, _ in self.queue]
        now = time.monotonic()
        running = [(self.prober.get(key(w.source)), now - w.started_at) for w in self.workers.values()]
        return describe(self.speed.remaining_seconds(queued, running=running, side_by_side=len(self.workers)))

    def update_video_progress(self, slot, stage, done, total):
        value, label = video_progress(stage, done, total, self.settings)
        bar = self.video_bars[slot]
        bar.setRange(0, 0 if value is None else 100)
        if value is not None:
            bar.setValue(value)
        bar.setFormat(label + (' · %p%' if value is not None else ''))
        if slot in self.workers:
            name = source_label(self.workers[slot].source, self.settings.input_folder)
            self.video_labels[slot].setText(f'{name} — {label}')

    def show_video_rows(self):
        """The first row always; another for each further video in progress."""
        for slot in range(1, MAX_PARALLEL_VIDEOS):
            for widget in (self.video_labels[slot], self.video_bars[slot]):
                widget.setVisible(slot in self.workers)

    def start_session(self, existing_only, only=None):
        """``only``: process just these files now (re-cut after a review), then stop."""
        try:
            settings = self.read_settings()
            if self.mode == 'basic' and not any(p.enabled for p in settings.profiles):
                self.show_warning('Tick at least one of Trim my video, A grade video or B grade video.')
                return
            # Check again here, whatever started this: the GPU answer may not have landed yet, the device may have
            # changed since, and a re-cut from the Review tab never passes the Process button.
            if self.cuda is None:
                self.cuda = cuda_available()
            self.health_checks = check_install(settings, cuda_available=self.cuda)
            self.apply_health()
            stoppers = blocking(self.health_checks)
            if stoppers:
                self.show_warning(f'Not started. {stoppers[0].label}: {stoppers[0].detail}')
                return
            self.session = ProcessingSession(settings, existing_only, only, processor_factory=VideoProcessor)
            from app.load import Pacer
            if self.pacer:
                self.pacer.close()
            self.pacer = Pacer(graphics_wanted=settings.device != 'cpu') if settings.parallel_videos == 0 else None
            self.unreadable_reported = False
            save_settings(settings)
            self.settings = settings
            self.queue_progress = QueueProgress()
            self.update_queue_progress()
            self.video_bar.setRange(0, 100)
            self.video_bar.setValue(0)
            self.video_bar.setFormat('Waiting for a video')
            self.video_label.setText('Current video')
            self.warning.hide()
            self.active, self.stopping = True, False
            self.controls.setEnabled(False)
            self.process_button.setEnabled(False)
            self.keep_watching.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.stop_button.setText('Stop')
            self.timer.start(max(100, round(settings.poll_seconds * 1000)))
            self.append_log('Checking the folder: each video is processed once its file has stopped changing.')
            self.poll()
        except Exception as exc:
            self.finish_session()
            self.show_warning(str(exc))

    def poll(self):
        if not self.active:
            return
        try:
            ready = self.session.scan(busy=[worker.source for worker in self.workers.values()])
            self.report_unreadable()
            for source, _signature in ready:
                if self.prober is None:
                    self.prober = DurationProber(find_executable('ffprobe'))
                self.prober.request(key(source), source)
            self.queue_progress.enqueue(len(ready))
            self.update_queue_progress()
            self.start_next()
            if not self.workers and self.session.finished():
                self.finish_session()
            if not self.workers and self.active:
                self.status.setText(f'Queue: {len(self.queue)}   Watching — {len(self.session.snapshot)} source files')
        except Exception as exc:
            self.show_warning(str(exc))
            self.stop_enqueuing()

    def report_unreadable(self):
        """Folders or videos the scan could not read, once per run: otherwise they would silently never appear."""
        problems = self.session.unreadable
        if not problems or self.unreadable_reported:
            return
        self.unreadable_reported = True
        for where, reason in problems:
            self.append_log(f'Could not read {where}: {reason}.')
        where, reason = problems[0]
        more = f' ({len(problems) - 1} more in the log.)' if len(problems) > 1 else ''
        self.show_warning(f'Some footage cannot be read, so it is left out. {where}: {reason}.{more}')

    def room_for_another(self):
        """True when one more video may start: under the number chosen, or, on Automatic, when the machine has room."""
        running = len(self.workers)
        if self.settings.parallel_videos:
            return running < self.settings.parallel_videos
        if running >= MAX_PARALLEL_VIDEOS:
            return False
        return running == 0 or (self.pacer is not None and self.pacer.may_start(running))

    def start_next(self):
        while self.active and self.queue and self.room_for_another():
            slot = next(s for s in range(MAX_PARALLEL_VIDEOS) if s not in self.workers)
            source, signature, previous, moved = self.session.next_job()
            if self.pacer and self.workers:
                self.append_log(f'Starting another video alongside: {self.pacer.reason}.')
            worker = VideoWorker(self.session.processor_for(slot), source, signature, previous, self,
                                 moved_from=moved, slot=slot)
            self.workers[slot] = worker
            worker.log.connect(self.worker_log)
            worker.progress.connect(self.update_video_progress)
            worker.outcome.connect(self.job_outcome)
            worker.finished.connect(self.job_finished)
            self.show_video_rows()
            self.video_labels[slot].setText(f'{source.name} — {source.parent}')
            self.update_video_progress(slot, 'identify', 0, 0)
            if self.pacer:
                self.pacer.started()
            worker.start()

    def job_outcome(self, slot, status, result):
        worker = self.workers[slot]
        source, signature = worker.source, worker.signature
        name = source_label(source, self.settings.input_folder)
        self.append_log(f'{name}: {status}' + (f' — {result["error"]}' if 'error' in result else ''))
        if status == 'failed':
            self.show_warning(f'{source.name}: {result["error"]}\nSelect it in Results and click "Process this video again" to retry.')
        try:
            status = self.session.record(source, signature, status, result)
        except Exception as exc:
            self.show_warning(f'Could not save completion ledger: {exc}')
            status = 'failed'
            self.stop_enqueuing()
        if status == 'success' and result.get('ran_model'):
            self.speed.update(time.monotonic() - worker.started_at, result.get('duration_sec'))
        self.queue_progress.settle(status)
        self.update_queue_progress()
        self.refresh_results()
        if status == 'success':
            self.review_tab.mark_stale()
            if self.tabs.currentIndex() == 1:
                self.review_tab.refresh(self.settings)
            self.update_video_progress(slot, 'complete', 1, 1)
        else:
            self.video_bars[slot].setRange(0, 100)
            self.video_bars[slot].setValue(0)
            self.video_bars[slot].setFormat(status.capitalize())
            self.video_labels[slot].setText(f'{name} — {status}')

    def job_finished(self):
        worker = self.sender()
        self.workers.pop(worker.slot, None)
        worker.deleteLater()
        self.show_video_rows()
        if self.stopping:
            if not self.workers:
                self.finish_session()
        else:
            self.start_next()
            if self.session and self.session.existing_only:
                self.poll()

    def stop_enqueuing(self):
        self.active = False
        self.stopping = True
        self.timer.stop()
        self.queue_progress.deferred += self.session.drain() if self.session else 0
        self.update_queue_progress()
        if self.workers:
            several = len(self.workers) > 1
            self.stop_button.setText('Cancel videos in progress…' if several else 'Cancel current video…')
            self.status.setText(f'Stopping — finishing the {len(self.workers)} videos in progress. Press again to '
                                'cancel them.' if several else
                                'Stopping — finishing the current video. Press again to cancel it.')
        else:
            self.finish_session()

    def stop_session(self):
        if not self.stopping:
            self.stop_enqueuing()
        elif self.workers:
            several = len(self.workers) > 1
            answer = QMessageBox.question(self, 'Cancel videos in progress?' if several else 'Cancel current video?',
                ('Cancel the videos being processed now? ' if several else 'Cancel processing the current video? ')
                + 'Completed timelines and clips will be kept. You can process '
                + ('them' if several else 'this video') + ' again later.')
            if answer == QMessageBox.Yes:
                for worker in self.workers.values():
                    worker.processor.runner.cancelled.set()
                self.stop_button.setEnabled(False)

    def finish_session(self):
        self.timer.stop()
        if self.pacer:
            self.pacer.close()
            self.pacer = None
        self.active = self.stopping = False
        if self.session:
            self.session.drain()
            self.session.close()   # its ledger stays readable for the results list; only the lock is released
        self.controls.setEnabled(True)
        self.keep_watching.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.stop_button.setText('Stop')
        self.status.setText('Stopped. Settings can be changed; Process videos handles any new or changed videos.')
        self.refresh_health()  # a run can end because something went missing

    def closeEvent(self, event):
        if self.workers:
            self.stop_enqueuing()
            self.show_warning('Finishing the video in progress. Press Stop again to cancel it, then close the window.')
            event.ignore()
            return
        self.finish_session()
        self.review_tab.close_labeller()
        try:
            save_settings(self.read_settings())
        except Exception as exc:
            self.show_warning(f'Could not save settings: {exc}')
            event.ignore()
            return
        event.accept()
