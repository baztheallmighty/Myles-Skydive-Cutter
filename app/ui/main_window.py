"""Desktop controls. Classification and output decisions live outside this module."""
from collections import deque
from dataclasses import replace
from datetime import datetime
import importlib.util
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QThread, QTimer, Signal
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
from app.settings import (VIEW_MODES, KeepProfile, Settings, load_settings, profile_presets, save_settings,
                          state_directory, validate_settings)
from app.ui.profile_editor import ProfileEditor, decimal_spin
from app.ui.review_tab import ReviewTab
from app.ui.results import ResultsPanel
from app import PROJECT_ROOT
from app.eta import DurationProber, SpeedStore, describe
from app.ffmpeg_tools import find_executable
import time
from app.relocate import rebase_entries
from app.session import ProcessingSession
from v3_poc.common import RunLock, key


class VideoWorker(QThread):
    log = Signal(str)
    outcome = Signal(str, object)
    progress = Signal(str, float, float)

    def __init__(self, processor, source, signature, previous_entry=None, parent=None, moved_from=()):
        super().__init__(parent)
        self.processor, self.source, self.signature = processor, source, signature
        self.previous_entry = previous_entry
        self.moved_from = moved_from

    def run(self):
        self.processor.runner.log = self.log.emit
        self.processor.runner.progress = self.progress.emit
        try:
            result = self.processor.process(self.source, self.signature, self.previous_entry,
                                            moved_from=self.moved_from)
            self.outcome.emit('success', result)
        except Cancelled as exc:
            self.outcome.emit('cancelled', {'error': str(exc)})
        except Exception as exc:
            self.outcome.emit('failed', {'error': f'{type(exc).__name__}: {exc}'})


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
        self.setMinimumSize(1120, 720)
        self.setAcceptDrops(True)
        self.worker = None
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
        self.profiles = list(self.settings.profiles)
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
        self.build_columns()
        self.build_folders()
        self.build_profiles()
        self.build_advanced()
        self.build_actions()

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
        scroll.setMinimumWidth(520)
        self.results = ResultsPanel()
        self.results.open_in_review.connect(self.open_video_in_review)
        self.results.process_again.connect(self.process_again)
        self.results.setMinimumHeight(360)
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
        self.video_started = None

    def build_folders(self):
        """Input and Clips: the only two choices a first run needs."""
        # --- folders: the only two choices a first run needs ---------------------------------------------------
        folders = QGroupBox('Folders')
        form = QFormLayout(folders)
        self.folder_edits = {}
        self.folder_buttons = {}
        for name, label, hint in [('input_folder', 'Input videos', 'The folder with your jump videos (subfolders included)'),
                                  ('output_folder', 'Clips', 'Where the clips go (outside the input folder)')]:
            form.addRow(label, self.folder_row(name, hint))
        tip_row = QHBoxLayout()
        drop = QLabel('Tip: you can drag a folder from Explorer onto these boxes.')
        drop.setObjectName('hint')
        tip_row.addWidget(drop)
        tip_row.addStretch()
        self.advanced_toggle = QPushButton('Hide advanced settings')
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setChecked(True)
        self.advanced_toggle.setToolTip('Output mode, clip folders, where CSVs go, processing device and more.')
        self.advanced_toggle.toggled.connect(self.toggle_advanced)
        tip_row.addWidget(self.advanced_toggle)
        form.addRow(tip_row)
        self.column.addWidget(folders)

    def build_profiles(self):
        """The Keep profiles table and its buttons."""
        # --- keep profiles -----------------------------------------------------------------------------------------
        group = QGroupBox('Keep profiles')
        profiles_layout = QVBoxLayout(group)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['Enabled', 'Name', 'Phases', 'Min people', 'Min total area',
                                              'Extra before / after'])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setMinimumHeight(110)
        self.table.setMaximumHeight(150)
        self.table.cellDoubleClicked.connect(lambda *_: self.edit_profile())
        self.table.itemChanged.connect(self.profile_checked)
        profiles_layout.addWidget(self.table)
        row = QHBoxLayout()
        for label, action in [('Add', self.add_profile), ('Edit', self.edit_profile),
                              ('Duplicate', self.duplicate_profile), ('Remove', self.remove_profile)]:
            button = QPushButton(label)
            button.clicked.connect(action)
            row.addWidget(button)
        self.preset_button = QPushButton('Add preset')
        self.preset_menu = QMenu(self.preset_button)
        self.preset_button.setMenu(self.preset_menu)
        self.preset_menu.aboutToShow.connect(self.fill_presets)
        row.addWidget(self.preset_button)
        row.addStretch()
        profiles_layout.addLayout(row)
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
        self.output_mode.addItem('CSV files and clips', True)
        self.output_mode.addItem('CSV only - no clips', False)
        self.output_mode.setCurrentIndex(0 if self.settings.cut_enabled else 1)
        advanced.addRow('Create', self.output_mode)
        self.output_layout = QComboBox()
        for identifier, label in OUTPUT_LAYOUTS.items():
            self.output_layout.addItem(label, identifier)
        self.output_layout.setCurrentIndex(self.output_layout.findData(self.settings.output_layout))
        advanced.addRow('Clip folders', self.output_layout)
        self.layout_note = QLabel()
        self.layout_note.setObjectName('hint')
        self.layout_note.setWordWrap(False)
        self.layout_note.setTextFormat(Qt.PlainText)
        advanced.addRow(self.layout_note)
        csv_box = QVBoxLayout()
        self.csv_in_clips = QRadioButton('In the Clips folder (a "timelines" folder)')
        self.csv_elsewhere = QRadioButton('Somewhere else:')
        csv_box.addWidget(self.csv_in_clips)
        csv_box.addWidget(self.csv_elsewhere)
        csv_box.addLayout(self.folder_row('csv_folder', 'Choose the folder for timeline CSVs'))
        advanced.addRow('Timeline CSVs', csv_box)
        saved_csv, saved_clips = self.settings.csv_folder, self.settings.output_folder
        in_clips = not saved_csv or (bool(saved_clips) and Path(saved_csv) == Path(saved_clips) / 'timelines')
        (self.csv_in_clips if in_clips else self.csv_elsewhere).setChecked(True)
        if in_clips:
            self.folder_edits['csv_folder'].clear()
        self.csv_in_clips.toggled.connect(self.update_output_mode)
        self.output_note = QLabel()  # shown as the Create box's tooltip, to keep the column short

        advanced = self.sections['processing'].form
        self.phase_toggle = QCheckBox('Identify jump phases')
        self.phase_toggle.setChecked(self.settings.phases_enabled)
        advanced.addRow(self.phase_toggle)
        self.classifier = QComboBox()
        for classifier in available_classifiers():
            self.classifier.addItem(classifier.display_name, classifier.identifier)
        self.classifier.setCurrentIndex(max(0, self.classifier.findData(self.settings.phase_classifier)))
        advanced.addRow('Classifier', self.classifier)
        advanced.setRowVisible(self.classifier, self.classifier.count() > 1)  # nothing to choose from in the release
        self.device = QComboBox()
        for value, label in device_choices():
            self.device.addItem(label, value)
        self.device.setCurrentIndex(max(0, self.device.findData(self.settings.device)))
        advanced.addRow('Process on', self.device)
        self.batch_size = QSpinBox()
        self.batch_size.setRange(1, 64)
        self.batch_size.setValue(self.settings.batch_size)
        self.batch_size.setToolTip('Video windows per GPU batch. Lower it if a small graphics card runs out of memory.')
        advanced.addRow('Batch size', self.batch_size)
        self.view_mode = QComboBox()
        for identifier, label in VIEW_MODES.items():
            self.view_mode.addItem(label, identifier)
        self.view_mode.setCurrentIndex(max(0, self.view_mode.findData(self.settings.view_mode)))
        self.view_mode.setToolTip('GoPro MAX and other 360 cameras record all round. The front view is the one the '
                                  'models were trained on; the back view is everything behind the camera. '
                                  'Ordinary cameras ignore this.')
        advanced.addRow('360 videos', self.view_mode)
        self.recut = QCheckBox('Re-cut a video as soon as you mark it reviewed')
        self.recut.setToolTip('On the Review tab, "Mark reviewed" and "Not skydiving" cut the video again straight away.')
        self.recut.setChecked(self.settings.recut_on_review)
        advanced.addRow(self.recut)

        advanced = self.sections['people'].form
        self.people_toggle = QCheckBox('Count people and measure total frame coverage')
        self.people_available = people_installed(self.settings)
        self.people_toggle.setChecked(self.settings.people_enabled and self.people_available)
        advanced.addRow(self.people_toggle)
        self.sample_rate = decimal_spin(self.settings.sample_fps, maximum=60, minimum=.01)
        self.confidence = decimal_spin(self.settings.detection_confidence, maximum=1, minimum=.01)
        advanced.addRow('Samples per second', self.sample_rate)
        advanced.addRow('Detection threshold', self.confidence)
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
        self.keep_watching = QCheckBox('Keep watching for new videos')
        self.keep_watching.setChecked(self.settings.keep_watching)
        self.keep_watching.setToolTip('After the videos already in the folder, keep processing new ones as they are '
                                      'copied in, until you press Stop.')
        self.stop_button = QPushButton('Stop')
        self.stop_button.clicked.connect(self.stop_session)
        self.stop_button.setEnabled(False)
        self.review_labels_button = QPushButton('Review cuts in labeller')
        self.review_labels_button.setToolTip('Open the Review tab: every processed video with the model, audio and '
                                             'motion tracks lined up, and the clips that were cut.')
        self.review_labels_button.clicked.connect(lambda: self.tabs.setCurrentIndex(1))
        row.addWidget(self.process_button)
        row.addWidget(self.keep_watching)
        row.addWidget(self.stop_button)
        row.addStretch()
        row.addWidget(self.review_labels_button)
        self.outer.addLayout(row)
        self.status = QLabel('Ready. Process videos handles the videos in the input folder; tick "Keep watching" to '
                             'carry on with new ones as they arrive.')
        self.status.setWordWrap(True)
        self.outer.addWidget(self.status)
        self.queue_label = QLabel('Queue progress')
        self.outer.addWidget(self.queue_label)
        self.queue_bar = QProgressBar()
        self.queue_bar.setRange(0, 100)
        self.queue_bar.setValue(0)
        self.queue_bar.setFormat('Waiting for videos')
        self.outer.addWidget(self.queue_bar)
        self.video_label = QLabel('Current video')
        self.video_label.setWordWrap(True)
        self.outer.addWidget(self.video_label)
        self.video_bar = QProgressBar()
        self.video_bar.setRange(0, 100)
        self.video_bar.setValue(0)
        self.video_bar.setFormat('No video processing')
        self.outer.addWidget(self.video_bar)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(4000)
        self.log.setMinimumHeight(70)
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
        running = self.active or bool(self.worker)
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
        """Open at a size that suits this screen, or exactly where it was left last time."""
        screen = QApplication.primaryScreen()
        area = screen.availableGeometry() if screen else None
        if area:
            self.resize(min(max(int(area.width() * .85), 1120), 2400), min(max(int(area.height() * .85), 720), 1500))
            self.move(area.left() + (area.width() - self.width()) // 2,
                      area.top() + max(0, (area.height() - self.height()) // 3))
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
        self.advanced.setVisible(shown)
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

    def process_again(self, source_key):
        """Forget this video's completion so the next processing run (or the running one) handles it again."""
        if self.active:
            self.session.forget(source_key)
            self.append_log('Queued again; it will be processed after the videos already waiting.')
        else:
            state, _entries = self.current_entries()
            if state is None:
                return
            with RunLock(state, 'monitor.lock'):
                ledger = load_ledger(state / 'ledger.json')
                ledger['entries'].pop(source_key, None)
                save_ledger(state / 'ledger.json', ledger)
            self.status.setText('It will be processed the next time you click Process videos.')
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
        return replace(self.settings, **folders,
            phases_enabled=self.phase_toggle.isChecked(), people_enabled=self.people_toggle.isChecked(),
            cut_enabled=cut, phase_classifier=self.classifier.currentData(),
            output_layout=self.output_layout.currentData(), device=self.device.currentData(),
            view_mode=self.view_mode.currentData(),
            batch_size=self.batch_size.value(), keep_watching=self.keep_watching.isChecked(),
            recut_on_review=self.recut.isChecked(),
            sample_fps=self.sample_rate.value(), detection_confidence=self.confidence.value(),
            window_geometry=geometry, column_state=columns, open_sections=sections,
            profiles=tuple(self.profiles))

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
            'Choose the folder for timeline CSVs' if cutting else 'Required in CSV-only mode')
        example = ('Example: ' + layout_example(self.output_layout.currentData()) if cutting
                   else 'Timeline CSVs only; each name includes a unique video ID.')
        # One line always: a long example is shortened in the middle, with the whole path on hover.
        self.layout_note.setText(self.layout_note.fontMetrics().elidedText(
            example, Qt.TextElideMode.ElideMiddle, self.advanced.maximumWidth() - 40))
        self.layout_note.setToolTip(example)
        self.output_layout.setToolTip('Output names include a unique video ID, so repeated camera file names are safe. '
                                      'Your original files are never renamed.')
        self.output_note.setText(
            'Clips start at the nearest keyframe, so they can include a second or two extra.' if cutting else
            'No clips are made or changed; profiles still mark matching moments in the CSV.')
        self.output_mode.setToolTip(self.output_note.text())

    def check_gpu(self):
        """Importing torch takes a moment, so the window is already up when the answer lands."""
        self.cuda = cuda_available()
        self.refresh_health(cuda=self.cuda)

    def update_gates(self):
        phases, people = self.phase_toggle.isChecked(), self.people_toggle.isChecked()
        self.classifier.setEnabled(phases)
        self.sample_rate.setEnabled(people)
        self.confidence.setEnabled(people)
        notes = []
        if not phases:
            notes.append('Phase identification is off (Advanced settings): phase filters are ignored.')
        if not phases and not people:
            notes.append('Both classifiers are off: every sample matches each enabled profile.')
        self.gate_note.setText(' '.join(notes))
        self.gate_note.setVisible(bool(notes))
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
            for j, value in enumerate(values):
                item = QTableWidgetItem(value)
                if j == 0:
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked if p.enabled else Qt.Unchecked)
                self.table.setItem(i, j, item)
        self.table.blockSignals(False)

    def profile_checked(self, item):
        if item.column() == 0:
            i = item.row()
            self.profiles[i] = replace(self.profiles[i], enabled=item.checkState() == Qt.Checked)

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
        if self.worker:
            label = source_label(self.worker.source, self.settings.input_folder)
            self.status.setText(f'Queue: {len(self.queue)}   Current: {label} — {message[:150]}')

    def show_warning(self, message):
        self.warning.setText(message)
        self.warning.show()

    def update_queue_progress(self):
        value, label = self.queue_progress.display()
        estimate = self.estimate_text()
        self.queue_bar.setValue(value)
        self.queue_bar.setFormat(label + (f' · {estimate}' if estimate else ''))

    def estimate_text(self):
        if not self.active or (not self.worker and not self.queue):
            return ''
        if self.prober is None:
            return ''
        queued = [self.prober.get(key(p)) for p, _ in self.queue]
        current = self.prober.get(key(self.worker.source)) if self.worker else None
        elapsed = time.monotonic() - self.video_started if self.worker and self.video_started else 0.0
        return describe(self.speed.remaining_seconds(queued, current, elapsed))

    def update_video_progress(self, stage, done, total):
        value, label = video_progress(stage, done, total, self.settings)
        self.video_bar.setRange(0, 0 if value is None else 100)
        if value is not None:
            self.video_bar.setValue(value)
        self.video_bar.setFormat(label + (' · %p%' if value is not None else ''))
        if self.worker:
            name = source_label(self.worker.source, self.settings.input_folder)
            self.video_label.setText(f'{name} — {label}')

    def start_session(self, existing_only, only=None):
        """``only``: process just these files now (re-cut after a review), then stop."""
        try:
            settings = self.read_settings()
            self.session = ProcessingSession(settings, existing_only, only, processor_factory=VideoProcessor)
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
            ready = self.session.scan(busy=self.worker.source if self.worker else None)
            self.report_unreadable()
            for source, _signature in ready:
                if self.prober is None:
                    self.prober = DurationProber(find_executable('ffprobe'))
                self.prober.request(key(source), source)
            self.queue_progress.enqueue(len(ready))
            self.update_queue_progress()
            self.start_next()
            if not self.worker and self.session.finished():
                self.finish_session()
            if not self.worker and self.active:
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

    def start_next(self):
        if self.worker or not self.active or not self.queue:
            return
        source, signature, previous, moved = self.session.next_job()
        self.worker = VideoWorker(self.processor, source, signature, previous, self, moved_from=moved)
        self.worker.log.connect(self.append_log)
        self.worker.progress.connect(self.update_video_progress)
        self.worker.outcome.connect(self.job_outcome)
        self.worker.finished.connect(self.job_finished)
        self.video_label.setText(f'{source.name} — {source.parent}')
        self.update_video_progress('identify', 0, 0)
        self.video_started = time.monotonic()
        self.worker.start()

    def job_outcome(self, status, result):
        source, signature = self.worker.source, self.worker.signature
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
        if status == 'success' and result.get('ran_model') and self.video_started:
            self.speed.update(time.monotonic() - self.video_started, result.get('duration_sec'))
        self.queue_progress.settle(status)
        self.update_queue_progress()
        self.refresh_results()
        if status == 'success':
            self.review_tab.mark_stale()
            if self.tabs.currentIndex() == 1:
                self.review_tab.refresh(self.settings)
            self.update_video_progress('complete', 1, 1)
        else:
            self.video_bar.setRange(0, 100)
            self.video_bar.setValue(0)
            self.video_bar.setFormat(status.capitalize())
            self.video_label.setText(f'{name} — {status}')

    def job_finished(self):
        self.worker.deleteLater()
        self.worker = None
        if self.stopping:
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
        if self.worker:
            self.stop_button.setText('Cancel current video…')
            self.status.setText('Stopping — finishing the current video. Press again to cancel it.')
        else:
            self.finish_session()

    def stop_session(self):
        if not self.stopping:
            self.stop_enqueuing()
        elif self.worker:
            answer = QMessageBox.question(self, 'Cancel current video?',
                'Cancel processing the current video? Completed CSV files and clips will be kept. '
                'You can process this video again later.')
            if answer == QMessageBox.Yes:
                self.processor.runner.cancelled.set()
                self.stop_button.setEnabled(False)

    def finish_session(self):
        self.timer.stop()
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
        if self.worker:
            self.stop_enqueuing()
            self.show_warning('Finishing the current video. Use Cancel current video to stop it, then close the window.')
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
