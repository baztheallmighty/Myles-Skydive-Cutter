"""One dark theme for the whole app, including the labeller."""
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QAbstractSpinBox, QComboBox

BACKGROUND = '#181e28'
SURFACE = '#202938'
BASE = '#111722'
TEXT = '#edf1f7'
MUTED = '#9aa4b2'
BUTTON = '#293547'
ACCENT = '#367eaf'
ACCENT_TEXT = '#ffffff'
WARNING_BACKGROUND = '#573e18'
WARNING_TEXT = '#fff1cd'
DANGER = '#c2504b'          # a missing piece that stops the work
DANGER_BACKGROUND = '#40201e'
DANGER_TEXT = '#ffd9d5'
GOOD = '#3fae6a'            # in use, kept, the simple way
GOOD_BACKGROUND = '#1f3a2b'
HEADING = '#8cc4ea'         # section titles

CHECK = (Path(__file__).resolve().parent / 'check.svg').as_posix()  # the tick drawn in ticked boxes

STYLESHEET = f"""
QGroupBox {{ font-weight: bold; margin-top: 8px; padding-top: 12px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; color: {HEADING}; }}
QPushButton {{ padding: 6px 12px; }}
QPushButton#primary {{ background: {ACCENT}; color: {ACCENT_TEXT}; font-weight: bold; padding: 8px 18px; border-radius: 4px; }}
QPushButton#primary:disabled {{ background: #2a4557; color: #8fa3b3; }}
QLineEdit {{ padding: 5px; }}
QPushButton#chip {{ padding: 1px 4px; }}
QTabWidget::pane {{ border: 0; }}
QTabBar::tab {{ padding: 8px 22px; background: {BUTTON}; color: {TEXT}; border-top-left-radius: 4px;
               border-top-right-radius: 4px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {ACCENT}; color: {ACCENT_TEXT}; font-weight: bold; }}
QToolButton#disclosure {{ border: 0; font-weight: bold; padding: 4px 0; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid #7a8697; border-radius: 3px; background: {BASE}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: #8cc4ea; image: url({CHECK}); }}
QCheckBox::indicator:disabled {{ border-color: #4a5463; background: {SURFACE}; }}
QRadioButton::indicator {{ width: 14px; height: 14px; border: 1px solid #7a8697; border-radius: 8px; background: {BASE}; }}
QRadioButton::indicator:checked {{ border-color: #8cc4ea;
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 {ACCENT_TEXT}, stop:0.35 {ACCENT_TEXT},
                                stop:0.45 {ACCENT}, stop:1 {ACCENT}); }}
QRadioButton::indicator:disabled {{ border-color: #4a5463; background: {SURFACE}; }}
QLabel#hint {{ color: {MUTED}; }}
QLabel#danger {{ color: {DANGER_TEXT}; }}
QLabel#banner {{ background: {DANGER_BACKGROUND}; color: {DANGER_TEXT}; border: 1px solid {DANGER};
                 border-radius: 4px; padding: 9px 12px; }}
QLabel#bannerWarning {{ background: {WARNING_BACKGROUND}; color: {WARNING_TEXT}; border: 1px solid #a07a30;
                        border-radius: 4px; padding: 9px 12px; }}
QPushButton#fix {{ background: {DANGER}; color: #ffffff; font-weight: bold; padding: 6px 14px; border-radius: 4px; }}
QToolButton#section {{ border: 0; font-weight: bold; padding: 4px 2px; text-align: left; color: {TEXT}; }}
QToolButton#section:hover {{ color: #ffffff; }}
QWidget#sectionBody {{ padding-left: 4px; }}
QFrame#section {{ border: 1px solid transparent; border-radius: 5px; }}
QFrame#sectionDanger {{ border: 1px solid {DANGER}; border-radius: 5px; background: {DANGER_BACKGROUND}; }}
QFrame#sectionWarning {{ border: 1px solid #a07a30; border-radius: 5px; }}
QToolButton#help {{ border: 1px solid #5d6b80; border-radius: 10px; color: {MUTED}; font-weight: bold;
                    background: transparent; padding: 0; }}
QToolButton#help:hover {{ border-color: #8cc4ea; color: {ACCENT_TEXT}; background: {ACCENT}; }}
QFrame#helpNote {{ background: {SURFACE}; border: 1px solid #8cc4ea; border-radius: 6px; }}
QLabel#helpTitle {{ font-weight: bold; color: {ACCENT_TEXT}; padding-bottom: 4px; }}
QFrame#cardTrim, QFrame#cardA, QFrame#cardB {{ border-radius: 6px; background: {SURFACE}; }}
QFrame#cardTrim {{ border-left: 6px solid #3b82c4; }}
QFrame#cardA {{ border-left: 6px solid #3fae6a; }}
QFrame#cardB {{ border-left: 6px solid #d39a2c; }}
QCheckBox#cardTitle {{ font-size: 15px; font-weight: bold; }}
QPushButton#modeBasic, QPushButton#modeAdvanced {{ padding: 6px 18px; min-width: 84px; border-radius: 4px;
                                                     background: {BUTTON}; font-weight: bold; }}
QPushButton#modeBasic {{ border: 1px solid {GOOD}; color: #9fe0b8; }}
QPushButton#modeAdvanced {{ border: 1px solid {DANGER}; color: #f0aaa5; }}
QPushButton#modeBasic:checked {{ background: {GOOD}; color: #0d1a12; }}
QPushButton#modeAdvanced:checked {{ background: {DANGER}; color: #ffffff; }}
QPushButton#stop:enabled {{ border: 1px solid {DANGER}; color: {DANGER_TEXT}; }}
QLabel#keeping {{ background: {GOOD_BACKGROUND}; border-left: 4px solid {GOOD}; border-radius: 4px; padding: 8px 10px; }}
QLabel#keepingNothing {{ background: {WARNING_BACKGROUND}; color: {WARNING_TEXT}; border-left: 4px solid #a07a30;
                         border-radius: 4px; padding: 8px 10px; }}
QHeaderView::section {{ color: {HEADING}; }}
QLabel#summary {{ color: {TEXT}; background: {BASE}; border-radius: 4px; padding: 8px 10px; }}
"""


class WheelGuard(QObject):
    """Stops the mouse wheel changing a setting it merely happens to be over.

    Scrolling a long column of settings carries the pointer across drop-downs and number boxes, and each one would
    take the wheel and change its value. A drop-down or number box now answers the wheel only after it has been
    clicked; otherwise the wheel carries on scrolling the page.
    """
    GUARDED = (QComboBox, QAbstractSpinBox)

    def eventFilter(self, watched, event):
        if isinstance(watched, self.GUARDED):
            if event.type() == QEvent.Type.Polish:
                # Qt would otherwise hand a widget the focus for being wheeled over, which defeats the test below.
                watched.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            elif event.type() == QEvent.Type.Wheel and not watched.hasFocus():
                event.ignore()
                return True
        return False


def apply(application) -> None:
    """Fusion style, the dark palette and the shared stylesheet, for the app and the labeller alike."""
    if not getattr(application, 'wheel_guard', None):
        application.wheel_guard = WheelGuard(application)
        application.installEventFilter(application.wheel_guard)
    font_path = 'C:/Windows/Fonts/segoeui.ttf'
    try:
        QFontDatabase.addApplicationFont(font_path)  # explicit fallback also renders in offscreen tests
    except Exception:  # noqa: BLE001
        pass
    application.setStyle('Fusion')
    application.setFont(QFont('Segoe UI', 10))
    palette = QPalette()
    for role, color in [(QPalette.Window, BACKGROUND), (QPalette.WindowText, TEXT), (QPalette.Base, BASE),
                        (QPalette.AlternateBase, SURFACE), (QPalette.Text, TEXT), (QPalette.Button, BUTTON),
                        (QPalette.ButtonText, TEXT), (QPalette.Highlight, ACCENT),
                        (QPalette.HighlightedText, ACCENT_TEXT), (QPalette.ToolTipBase, SURFACE),
                        (QPalette.ToolTipText, TEXT), (QPalette.PlaceholderText, MUTED)]:
        palette.setColor(role, QColor(color))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor('#78818e'))
    application.setPalette(palette)
    application.setStyleSheet(STYLESHEET)
