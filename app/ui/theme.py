"""One dark theme for the whole app, including the labeller."""
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

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

CHECK = (Path(__file__).resolve().parent / 'check.svg').as_posix()  # the tick drawn in ticked boxes

STYLESHEET = f"""
QGroupBox {{ font-weight: bold; margin-top: 8px; padding-top: 12px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; }}
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
"""


def apply(application) -> None:
    """Fusion style, the dark palette and the shared stylesheet, for the app and the labeller alike."""
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
