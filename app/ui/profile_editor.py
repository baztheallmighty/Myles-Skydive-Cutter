from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QGridLayout, QLabel, QLineEdit, QMessageBox, QSpinBox, QVBoxLayout, QWidget)

from app.settings import KeepProfile, validate_profile
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
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.name = QLineEdit(profile.name)
        form.addRow('Name', self.name)
        self.enabled = QCheckBox('Enable this profile')
        self.enabled.setChecked(profile.enabled)
        form.addRow(self.enabled)
        phases_widget = QWidget()
        grid = QGridLayout(phases_widget)
        self.phase_checks = {}
        for index, phase in enumerate(PHASES):
            check = QCheckBox(phase.replace('_', ' ').capitalize())
            check.setChecked(phase in profile.phases)
            check.setEnabled(phases_enabled)
            self.phase_checks[phase] = check
            grid.addWidget(check, index // 3, index % 3)
        form.addRow('Keep phases', phases_widget)
        if not phases_enabled:
            form.addRow(QLabel('Phase classification is off. These phase filters will not be used.'))
        self.people = QSpinBox()
        self.people.setRange(0, 1000)
        self.people.setValue(profile.min_person_count)
        self.area = decimal_spin(profile.min_total_area_percent, maximum=10000)
        self.people.setEnabled(people_enabled)
        self.area.setEnabled(people_enabled)
        form.addRow('Minimum people', self.people)
        form.addRow('Minimum total person area (%)', self.area)
        if not people_enabled:
            form.addRow(QLabel('People counting is off. These people filters will not be used.'))
        self.margin_before = decimal_spin(profile.margin_before_seconds)
        self.margin_after = decimal_spin(profile.margin_after_seconds)
        self.minimum = decimal_spin(profile.min_span_seconds)
        self.gap = decimal_spin(profile.max_gap_seconds)
        form.addRow('Extra footage before (seconds)', self.margin_before)
        form.addRow('Extra footage after (seconds)', self.margin_after)
        form.addRow('Minimum span (seconds, before margin)', self.minimum)
        form.addRow('Bridge non-matching dips up to (seconds)', self.gap)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        profile = KeepProfile(self.name.text().strip(),
            frozenset(p for p, c in self.phase_checks.items() if c.isChecked()),
            self.people.value(), self.area.value(), self.margin_before.value(), self.margin_after.value(),
            self.minimum.value(), self.gap.value(), self.enabled.isChecked())
        try:
            validate_profile(profile)
        except ValueError as exc:
            QMessageBox.warning(self, 'Invalid profile', str(exc))
            return
        self.profile = profile
        super().accept()
