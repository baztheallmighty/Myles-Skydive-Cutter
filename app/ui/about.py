"""The note behind "How video is chosen in basic mode", and the diagnostics file.

The diagnostics file is what the screen and the window look like to Qt, and how long the last videos took. It is
what to send when something looks wrong on a machine nobody else can see; Ctrl+Shift+D in the window writes it.
"""
from datetime import datetime
from html import escape
import platform
import sys

from PySide6.QtCore import Qt, qVersion
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFrame, QLabel, QScrollArea, QVBoxLayout,
                               QWidget)

from app import PROJECT_ROOT, help_text
from app.update import installed_version


def fitted(dialog, width, height):
    """Size a dialog for its words, but never larger than the screen it opens on."""
    screen = (dialog.parentWidget().screen() if dialog.parentWidget() else None) or QGuiApplication.primaryScreen()
    if screen:
        area = screen.availableGeometry()
        width, height = min(width, area.width() - 60), min(height, area.height() - 80)
    dialog.resize(width, height)


class RulesDialog(QDialog):
    """The rules nobody set and nobody can change, then what each built-in choice asks for."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(help_text.RULES_TITLE)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page = QWidget()
        box = QVBoxLayout(page)
        box.setSpacing(6)

        def heading(words):
            box.addSpacing(6)
            label = QLabel(words)
            label.setObjectName('rulesTitle')
            label.setWordWrap(True)
            box.addWidget(label)

        def body(words, rich=False, indent=0):
            label = QLabel(words)
            label.setTextFormat(Qt.TextFormat.RichText if rich else Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setContentsMargins(indent, 0, 0, 0)
            box.addWidget(label)

        def paragraph(words):
            """A paragraph, its opening sentence in bold when that sentence is one of the points being made."""
            lead = next((lead for lead in help_text.RULE_LEADS if words.startswith(lead)), '')
            if lead:
                body(f'<b>{escape(lead)}</b>{escape(words[len(lead):])}', rich=True)
            else:
                body(words)
            box.addSpacing(4)

        for kind, content in help_text.rules():
            if kind == 'title':
                heading(content)
            elif kind == 'list':
                for item in content:
                    body(item if item[:1].isdigit() else f'•  {item}', indent=18)
                box.addSpacing(4)
            elif kind == 'table':
                rows = ''.join(f'<tr><td style="padding: 1px 22px 1px 0;">{escape(left)}</td>'
                               f'<td>{escape(right)}</td></tr>' for left, right in content)
                body(f'<table>{rows}</table>', rich=True, indent=18)
                box.addSpacing(4)
            else:
                paragraph(content)
        for title, words in help_text.built_in_choices():
            body(f'<b>{escape(title)}:</b> {escape(words)}', rich=True)
            box.addSpacing(4)
        box.addStretch()
        scroll.setWidget(page)
        outer.addWidget(scroll, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        fitted(self, 760, 820)


def rectangle(rect):
    return f'{rect.width()}x{rect.height()} at ({rect.x()}, {rect.y()})'


def diagnostics(window):
    """Everything about this machine's screens and this window that could explain a layout or pointer problem,
    and the time each recent video took. No folder or file names: it is meant to be sent to someone else."""
    import PySide6
    application = QApplication.instance()
    lines = [f'Skydive Cutter diagnostics, {datetime.now():%Y-%m-%d %H:%M:%S}',
             f'Version: {installed_version() or "development folder"}',
             f'System: {platform.system()} {platform.release()} ({platform.version()}), {platform.machine()}',
             f'macOS: {platform.mac_ver()[0]}' if sys.platform == 'darwin' else '',
             f'Python {platform.python_version()}, PySide6 {PySide6.__version__}, Qt {qVersion()}',
             f'Qt platform: {QGuiApplication.platformName()}, style: {application.style().objectName()}, '
             f'font: {application.font().family()} {application.font().pointSizeF():g} pt',
             '', 'Screens:']
    for screen in QGuiApplication.screens():
        mark = ' (primary)' if screen is QGuiApplication.primaryScreen() else ''
        lines.append(f'  {rectangle(screen.geometry())}, usable {rectangle(screen.availableGeometry())}, '
                     f'scale {screen.devicePixelRatio():g}, {screen.logicalDotsPerInch():.0f} dpi{mark}')
    centre = window.centralWidget()
    corner = centre.mapToGlobal(centre.rect().topLeft())
    pointer = QCursor.pos()
    seen = window.mapFromGlobal(pointer)
    state = window.windowState()
    shown = ('full screen' if state & Qt.WindowState.WindowFullScreen else
             'maximised' if state & Qt.WindowState.WindowMaximized else 'ordinary window')
    on = window.screen()
    lines += ['', 'Window:',
              f'  shown as: {shown}',
              f'  inside: {rectangle(window.geometry())}',
              f'  with its frame: {rectangle(window.frameGeometry())}',
              f'  when not maximised: {rectangle(window.normalGeometry())}',
              f'  smallest allowed: {window.minimumSize().width()}x{window.minimumSize().height()}, '
              f'smallest its contents need: {window.minimumSizeHint().width()}x{window.minimumSizeHint().height()}',
              f'  on the screen that is {rectangle(on.geometry())}, scale {window.devicePixelRatioF():g}'
              if on else '  on no screen',
              f'  contents start at ({corner.x()}, {corner.y()}) on the screen, '
              f'{centre.width()}x{centre.height()}',
              f'  pointer at ({pointer.x()}, {pointer.y()}) on the screen, which the window reads as '
              f'({seen.x()}, {seen.y()})',
              f'  settings column {window.scroll.viewport().width()}x{window.scroll.viewport().height()} showing '
              f'{window.controls.width()}x{window.controls.height()}; results {window.results.width()}x'
              f'{window.results.height()}',
              f'  screen: {window.mode}; run on: {window.device.currentData()}; read videos with: '
              f'{window.hardware_decode.currentData()}; videos at once: {window.parallel.currentData() or "automatic"}']
    lines += ['', 'Install:'] + [f'  [{check.state}] {check.label}: {check.detail}' for check in window.health_checks]
    lines += ['', 'Recent videos (length, then seconds spent on each step):']
    try:
        _state, entries = window.current_entries()
    except Exception as exc:  # noqa: BLE001 - the timings are a bonus; the rest of the file still matters
        entries = {}
        lines.append(f'  could not be read: {type(exc).__name__}')
    timed = [entry for entry in entries.values() if isinstance(entry, dict) and entry.get('stage_seconds')]
    for number, entry in enumerate(timed[-30:], 1):
        stages = dict(entry['stage_seconds'])
        engine = stages.pop('engine', None) or {}
        spent = ', '.join(f'{name} {seconds:g}' for name, seconds in stages.items()
                          if isinstance(seconds, (int, float)))
        inside = ('; inside phases: ' + ', '.join(f'{name} {seconds:g}' for name, seconds in engine.items())
                  if engine else '')
        lines.append(f'  {number}. {float(entry.get("duration_sec") or 0):.0f} s video: {spent}{inside}')
    if not timed:
        lines.append('  none yet in the clips folder that is set')
    return '\n'.join(line for line in lines if line is not None) + '\n'


def save_diagnostics(window):
    """Write the diagnostics into the app's logs folder. Returns the file."""
    folder = PROJECT_ROOT / 'logs'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'diagnostics-{datetime.now():%Y%m%d-%H%M%S}.txt'
    path.write_text(diagnostics(window), encoding='utf-8')
    return path
