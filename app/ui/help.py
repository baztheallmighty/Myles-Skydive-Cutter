"""The little "?" beside a setting, and the note it opens. The words live in app/help_text.py."""
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLayout, QToolButton, QVBoxLayout, QWidget

from app import help_text


NOTE_WIDTH = 420


class HelpNote(QFrame):
    """A note that sits beside its button until you click anywhere else."""

    def __init__(self, title, body, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName('helpNote')
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 10, 12, 12)
        heading = QLabel(title)
        heading.setObjectName('helpTitle')
        heading.setWordWrap(True)
        self.body = QLabel(body)
        self.body.setTextFormat(Qt.TextFormat.PlainText)
        self.body.setWordWrap(True)
        box.addWidget(heading)
        box.addWidget(self.body)
        self.setFixedWidth(NOTE_WIDTH)
        # A wrapped label does not tell its window how tall it will be, so a long explanation lost its last lines.
        inside = NOTE_WIDTH - 24
        heading.setFixedWidth(inside)
        self.body.setFixedWidth(inside)
        self.body.setMinimumHeight(self.body.heightForWidth(inside))
        heading.setMinimumHeight(heading.heightForWidth(inside))
        self.closed = None   # called when the note goes away

    def hideEvent(self, event):
        super().hideEvent(event)
        if self.closed:
            self.closed()

    def show_beside(self, button):
        self.adjustSize()
        corner = button.mapToGlobal(QPoint(button.width() + 6, 0))
        screen = QGuiApplication.screenAt(corner) or QGuiApplication.primaryScreen()
        if screen:   # never off the edge of the screen the button is on
            area = screen.availableGeometry()
            if corner.x() + self.width() > area.right():
                corner.setX(button.mapToGlobal(QPoint(0, 0)).x() - self.width() - 6)
            corner.setX(max(area.left(), corner.x()))
            corner.setY(max(area.top(), min(corner.y(), area.bottom() - self.height())))
        self.move(corner)
        self.show()


class HelpButton(QToolButton):
    def __init__(self, key, parent=None):
        super().__init__(parent)
        self.key = key
        self.note = None
        self.setText('?')
        self.setObjectName('help')
        self.setFixedSize(20, 20)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAccessibleName(f'Help: {help_text.label(key)}')
        self.setToolTip(help_text.text(key))
        self.clicked.connect(self.show_help)

    def show_help(self):
        self.note = HelpNote(help_text.label(self.key), help_text.text(self.key), self.window())
        self.note.closed = self.settle
        self.note.show_beside(self)

    def settle(self):
        """Back to plain once its note has gone: the note took the mouse, so the button never heard it leave."""
        self.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
        self.clearFocus()
        self.update()


def with_help(control, key):
    """The control with its "?" after it. A layout gets the button added; a widget is wrapped in a row."""
    if isinstance(control, QLayout):
        control.addWidget(HelpButton(key))
        return control
    row = QWidget()
    box = QHBoxLayout(row)
    box.setContentsMargins(0, 0, 0, 0)
    box.addWidget(control, 1)
    box.addWidget(HelpButton(key))
    return row
