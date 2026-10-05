"""Draw the app's icon and save it as release/cutter/skydive-cutter.ico.

    python release/make_icon.py

Run it again only to change the picture. The .ico is kept in the repository, so building the package or the installer
does not need this. One file holds every size Windows asks for (16 to 256 pixels), each stored as a PNG.
"""
from __future__ import annotations

import os
from pathlib import Path
import struct
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
TARGET = Path(__file__).resolve().parent / 'cutter' / 'skydive-cutter.ico'
SIZES = (16, 24, 32, 48, 64, 128, 256)


def picture(size: int):
    """A parachute over a dark tile: a canopy in three cells, lines down to a jumper."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 64, size / 64)   # drawn on a 64 by 64 grid
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor('#181e28'))
    painter.drawRoundedRect(QRectF(2, 2, 60, 60), 13, 13)
    canopy = QRectF(9, 11, 46, 40)
    for cell, colour in enumerate(('#367eaf', '#8cc4ea', '#367eaf')):
        path = QPainterPath()
        path.moveTo(canopy.center().x(), canopy.center().y())
        path.arcTo(canopy, 180 - cell * 60, -60)
        path.closeSubpath()
        painter.setBrush(QColor(colour))
        painter.drawPath(path)
    painter.setBrush(QColor('#181e28'))
    painter.drawRect(QRectF(8, 31, 48, 22))   # the canopy's flat underside
    painter.setPen(QPen(QColor('#edf1f7'), 1.6))
    for x in (10.5, 24, 40, 53.5):
        painter.drawLine(QPointF(x, 31), QPointF(32, 49))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor('#f0703a'))
    painter.drawEllipse(QPointF(32, 51), 4.2, 4.2)
    painter.end()
    return image


def png(image) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, 'PNG')
    return bytes(data)


def icon_file(images: dict[int, bytes]) -> bytes:
    """The .ico container: a directory of entries, then each picture's PNG bytes."""
    header = struct.pack('<HHH', 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, body = b'', b''
    for size, data in images.items():
        entries += struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(data), offset)   # 256 is written as 0
        body += data
        offset += len(data)
    return header + entries + body


def main() -> int:
    from PySide6.QtGui import QGuiApplication
    application = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])   # noqa: F841 - painting needs one
    TARGET.write_bytes(icon_file({size: png(picture(size)) for size in SIZES}))
    print(f'{TARGET} ({TARGET.stat().st_size:,} bytes, {len(SIZES)} sizes)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
