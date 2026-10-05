from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QGridLayout, QLabel, QLineEdit, QMessageBox, QSpinBox, QVBoxLayout, QWidget)

from app import help_text
from app.settings import KeepProfile, validate_profile
from app.ui.help import with_help
from v3_poc.common import PHASES


def decimal_spin(value, maximum=3600.0, minimum=0.0):
    widget = QDoubleSpinBox()
    widget.setRange(minimum, maximum)
    widget.setDecimals(2)
    widget.setSingleStep(.1)
    widget.setValue(value)
    return widget


class ProfileEditor(QDialog):
    def __init__(self, profile, phases_enabled=True, people_enabled=True, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Keep profile')
        self.profile = profile
        self.phases_enabled, self.people_enabled = phases_enabled, people_enabled
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.name = QLineEdit(profile.name)
        form.addRow(help_text.label('name'), with_help(self.name, 'name'))
        self.enabled = QCheckBox(help_text.label('enabled'))
        self.enabled.setChecked(profile.enabled)
        form.addRow(with_help(self.enabled, 'enabled'))
        self.folder = QLineEdit(profile.folder)
        self.folder.setPlaceholderText('A folder named after the profile')
        form.addRow(help_text.label('folder'), with_help(self.folder, 'folder'))
        phases_widget = QWidget()
        grid = QGridLayout(phases_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        self.phase_checks = {}
        for index, phase in enumerate(PHASES):
            check = QCheckBox(phase.replace('_', ' ').capitalize())
            check.setChecked(phase in profile.phases)
            check.setEnabled(phases_enabled)
            check.setToolTip(help_text.PHASES[phase])
            check.toggled.connect(self.refresh_notes)
            self.phase_checks[phase] = check
            grid.addWidget(check, index // 3, index % 3)
        form.addRow(help_text.label('phases'), with_help(phases_widget, 'phases'))
        if not phases_enabled:
            form.addRow(QLabel('Working out the parts of each jump is off. These choices will not be used.'))
        self.people = QSpinBox()
        self.people.setRange(0, 1000)
        self.people.setValue(profile.min_person_count)
        self.area = decimal_spin(profile.min_total_area_percent, maximum=10000)
        self.people.setEnabled(people_enabled)
        self.area.setEnabled(people_enabled)
        form.addRow(help_text.label('min_person_count'), with_help(self.people, 'min_person_count'))
        # Said beside the number, not only behind the "?": this is the setting people most often misread.
        self.includes_you = QLabel()
        self.includes_you.setObjectName('hint')
        self.includes_you.setWordWrap(True)
        form.addRow(self.includes_you)
        form.addRow(help_text.label('min_total_area_percent'), with_help(self.area, 'min_total_area_percent'))
        if not people_enabled:
            form.addRow(QLabel('Looking for people is off. These people settings will not be used.'))
        self.margin_before = decimal_spin(profile.margin_before_seconds)
        self.margin_after = decimal_spin(profile.margin_after_seconds)
        self.minimum = decimal_spin(profile.min_span_seconds)
        self.gap = decimal_spin(profile.max_gap_seconds)
        self.people_gap = decimal_spin(profile.people_gap_seconds)
        self.people_gap_count = QSpinBox()
        self.people_gap_count.setRange(1, 1000)
        self.people_gap_count.setValue(profile.people_gap_count)
        for widget in (self.people_gap, self.people_gap_count):
            widget.setEnabled(people_enabled)
        for key, widget in (('margin_before_seconds', self.margin_before), ('margin_after_seconds', self.margin_after),
                            ('min_span_seconds', self.minimum), ('max_gap_seconds', self.gap),
                            ('people_gap_seconds', self.people_gap), ('people_gap_count', self.people_gap_count)):
            form.addRow(help_text.label(key), with_help(widget, key))
        # What the numbers above add up to, in a sentence that rewrites itself as they change.
        self.summary = QLabel()
        self.summary.setObjectName('summary')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        for widget in (self.people, self.area, self.margin_before, self.margin_after, self.minimum, self.gap,
                       self.people_gap, self.people_gap_count):
            widget.valueChanged.connect(self.refresh_notes)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh_notes()

    def read(self):
        return KeepProfile(self.name.text().strip(),
            frozenset(p for p, c in self.phase_checks.items() if c.isChecked()),
            self.people.value(), self.area.value(), self.margin_before.value(), self.margin_after.value(),
            self.minimum.value(), self.gap.value(), self.enabled.isChecked(),
            self.people_gap.value(), self.people_gap_count.value(), self.folder.text().strip())

    def refresh_notes(self, *_):
        profile = self.read()
        self.includes_you.setText(help_text.includes_you_warning(profile) if self.people_enabled else '')
        self.includes_you.setVisible(bool(self.includes_you.text()))
        self.summary.setText(help_text.profile_summary(profile, self.phases_enabled, self.people_enabled))

    def accept(self):
        profile = self.read()
        try:
            validate_profile(profile)
        except ValueError as exc:
            QMessageBox.warning(self, 'Invalid profile', str(exc))
            return
        self.profile = profile
        super().accept()
