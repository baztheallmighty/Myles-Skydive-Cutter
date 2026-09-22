"""The labeller's Qt interface: every track aligned under the video, zoomable, with review tools.

Builds on v3_poc/review.py (ReviewWindow) and v3_poc/_labeler.py (ManualVideoLabeler), which are shared with the older
tools and are not modified; everything here rearranges and extends them in the subclass.

Layout, top to bottom: video (with a one-line overlay), overview slider, toolbar (video, playback, checks, zoom), phase
chips (also the colour legend), a status line, then one aligned block of rows that share a time axis and zoom:
Your labels (editable), Final (cut), V4 video, Audio, Motion model, Motion (g), Agreement, Clips cut.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from app import system
import sys

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy, QToolButton, QVBoxLayout,
                               QWidget)

from cutter_v4 import ROOT

sys.path.insert(0, str(ROOT / 'v3_poc'))
import review as base  # noqa: E402  v3_poc/review.py
from common import FIELDS, annotation_fingerprint, read_csv, write_json  # noqa: E402

from cutter_v4.review import checks_from  # noqa: E402,F401  (also used by the tests)

labeler = base.labeler

LABEL_COLUMN = 110                          # width of the row titles
MARGIN = labeler.TIMELINE_TRACK_MARGIN_PX   # the editable timeline's own inner margin (8 px)
LEFT = LABEL_COLUMN + MARGIN                # x where time 0 (or the view start) is drawn, in every row
RIGHT = MARGIN
AGREEMENT_COLORS = {'agree': '#2e7d4f', 'disagree': '#e0a21b', 'unknown': '#3a4454'}
CLIP_COLOR, CLIP_HOVER = '#3b82c4', '#6fb0ea'
MIN_VIEW_SECONDS = 5.0


def clock(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f'{seconds // 60}:{seconds % 60:02d}'


class View:
    """The visible time window shared by every row. ``None`` start means the whole video."""

    def __init__(self):
        self.duration = 0.0
        self.start = None
        self.end = None
        self.listeners = []

    def window(self) -> tuple[float, float]:
        if self.start is None or self.duration <= 0:
            return 0.0, max(self.duration, 1e-6)
        return self.start, self.end

    def zoomed(self) -> bool:
        return self.start is not None

    def reset(self, duration: float) -> None:
        self.duration, self.start, self.end = float(duration or 0), None, None
        self.changed()

    def set(self, start: float, end: float) -> None:
        span = min(max(end - start, MIN_VIEW_SECONDS), self.duration)
        start = min(max(0.0, start), self.duration - span)
        if span >= self.duration - 1e-6:
            self.start = self.end = None
        else:
            self.start, self.end = start, start + span
        self.changed()

    def zoom(self, factor: float, anchor: float | None = None) -> None:
        start, end = self.window()
        anchor = (start + end) / 2 if anchor is None else anchor
        span = (end - start) * factor
        ratio = (anchor - start) / max(1e-6, end - start)
        self.set(anchor - ratio * span, anchor - ratio * span + span)

    def pan(self, seconds: float) -> None:
        if self.zoomed():
            self.set(self.start + seconds, self.end + seconds)

    def ensure_visible(self, seconds: float) -> None:
        start, end = self.window()
        if self.zoomed() and not start <= seconds <= end:
            span = end - start
            self.set(seconds - .2 * span, seconds + .8 * span)

    def changed(self) -> None:
        for listener in self.listeners:
            listener()


def wheel_to_view(view: View, event, seconds_at_mouse: float) -> bool:
    """Ctrl + wheel zooms around the mouse; the plain wheel pans when zoomed in."""
    steps = event.angleDelta().y() / 120
    if not steps:
        return False
    if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
        view.zoom(0.8 ** steps, seconds_at_mouse)
        return True
    if view.zoomed():
        start, end = view.window()
        view.pan(-steps * .15 * (end - start))
        return True
    return False


class ZoomTimeline(labeler.SegmentTimelineWidget):
    """The editable label timeline, drawn on the shared view so it lines up with every prediction row."""

    def __init__(self, view: View, parent=None):
        super().__init__(parent)
        self.view = view
        self.setMinimumHeight(34)

    def _window_ms(self):
        start, end = self.view.window()  # exactly the tracks' window, so every row shares one time axis
        return start * 1000.0, max(start * 1000.0 + 1.0, end * 1000.0)

    def track_width(self) -> float:
        return max(1, self.width() - 2 * MARGIN)

    def x_for_ms(self, ms: float) -> float:
        start, end = self._window_ms()
        return MARGIN + (ms - start) / (end - start) * self.track_width()

    def position_from_mouse_x(self, x: float) -> int:
        if self.duration_ms <= 0:
            return 0
        start, end = self._window_ms()
        ratio = max(0.0, min(1.0, (float(x) - MARGIN) / self.track_width()))
        return int(round(start + ratio * (end - start)))

    def nearest_divider_ms(self, x: float):
        if self.duration_ms <= 0:
            return None
        best, best_ms = 9999.0, None
        for start_sec, end_sec, _phase, _index in self.timeline_ranges:
            for boundary_sec in (start_sec, end_sec):
                boundary_ms = labeler.seconds_to_milliseconds(boundary_sec)
                if 0 < boundary_ms < self.duration_ms:
                    distance = abs(float(x) - self.x_for_ms(boundary_ms))
                    if distance < best:
                        best, best_ms = distance, boundary_ms
        return best_ms if best <= 8.0 else None

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        top, height = 9, max(14, self.height() - 18)
        width = self.track_width()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(40, 40, 40, 210))
        painter.drawRect(QRectF(MARGIN, top, width, height))
        painter.setClipRect(QRectF(MARGIN, top - 4, width, height + 8))
        dividers = set()
        if self.duration_ms > 0:
            for start_sec, end_sec, phase, index in self.timeline_ranges:
                start_ms, end_ms = labeler.seconds_to_milliseconds(start_sec), labeler.seconds_to_milliseconds(end_sec)
                if end_ms <= start_ms:
                    continue
                x, x_end = self.x_for_ms(start_ms), self.x_for_ms(end_ms)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(labeler.phase_color(phase, 220))
                painter.drawRect(QRectF(x, top, max(1.0, x_end - x), height))
                if x_end - x > 70:
                    painter.setPen(QColor('#ffffff'))
                    painter.drawText(QRectF(x + 3, top, x_end - x - 5, height), Qt.AlignmentFlag.AlignVCenter,
                                     phase.replace('_', ' '))
                if index == self.selected_segment_index:
                    painter.setPen(QPen(QColor('white'), 2))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(QRectF(x, top, max(1.0, x_end - x), height))
                dividers.update((start_ms, end_ms))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 245))
            for divider in sorted(dividers):
                if 0 < divider < self.duration_ms:
                    painter.drawRect(QRectF(self.x_for_ms(divider) - 2, top - 3, 4, height + 6))
            x = self.x_for_ms(self.playhead_ms)
            painter.setPen(QPen(QColor('#268bd2'), 3))
            painter.drawLine(QPointF(x, top - 5), QPointF(x, top + height + 5))
            painter.setPen(QPen(QColor('white'), 1))
            painter.drawLine(QPointF(x + 2, top - 4), QPointF(x + 2, top + height + 4))
        painter.setClipping(False)
        painter.setPen(QPen(QColor(230, 230, 230, 180), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(MARGIN, top, width, height))
        painter.end()

    def wheelEvent(self, event) -> None:
        seconds = self.position_from_mouse_x(event.position().x()) / 1000.0
        if not wheel_to_view(self.view, event, seconds):
            super().wheelEvent(event)


class PredictionTracks(QWidget):
    """Every source on the shared time axis, under the editable timeline. Click to jump; clips can be played."""
    seek = Signal(float)
    play_clip = Signal(object)
    ROWS = [('final', 'Final (cut)'), ('v4', 'V4 video'), ('audio', 'Audio'), ('motion', 'Motion model'),
            ('trace', 'Motion (g)'), ('people', 'People in view'), ('agreement', 'Agreement'), ('clips', 'Clips cut')]
    COLLAPSED = ['final', 'clips']

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result = None
        self.position = 0.
        self.expanded = True
        self.view = getattr(parent, 'view', None) or View()
        self.hover_clip = None
        self.setMouseTracking(True)
        self._resize()

    def rows(self):
        names = [n for n, _t in self.ROWS] if self.expanded else self.COLLAPSED
        return [(n, t) for n, t in self.ROWS if n in names]

    def row_height(self, name):
        return 48 if name in ('trace', 'people') else 22

    def _resize(self):
        self.setFixedHeight(sum(self.row_height(n) + 4 for n, _t in self.rows()) + 6)

    def set_expanded(self, enabled):
        self.expanded = enabled
        self._resize()
        self.update()

    def track_width(self):
        return max(1, self.width() - LEFT - RIGHT)

    def x_of(self, seconds):
        start, end = self.view.window()
        return LEFT + (seconds - start) / max(1e-6, end - start) * self.track_width()

    def seconds_at(self, x):
        start, end = self.view.window()
        return start + (x - LEFT) / self.track_width() * (end - start)

    def row_at(self, y):
        top = 3
        for name, title in self.rows():
            height = self.row_height(name)
            if top <= y < top + height + 4:
                return name, title, top, height
            top += height + 4
        return None, None, 0, 0

    def clip_at(self, x, y):
        name, _title, top, height = self.row_at(y)
        if name != 'clips' or not self.result:
            return None
        clips = self.result.get('clips') or []
        profiles = sorted({c['profile'] for c in clips})
        seconds = self.seconds_at(x)
        for clip in clips:
            lane_height = height / max(1, len(profiles))
            lane_top = top + profiles.index(clip['profile']) * lane_height
            if clip['start_sec'] <= seconds < clip['end_sec'] and lane_top <= y < lane_top + lane_height:
                return clip
        return None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#181e28'))
        top = 3
        for name, title in self.rows():
            height = self.row_height(name)
            painter.setPen(QColor('#edf1f7'))
            painter.drawText(QRectF(4, top, LABEL_COLUMN - 6, height), Qt.AlignmentFlag.AlignVCenter, title)
            painter.fillRect(QRectF(LEFT, top, self.track_width(), height), QColor('#202938'))
            if self.result:
                painter.save()
                painter.setClipRect(QRectF(LEFT, top, self.track_width(), height))
                self.paint_row(painter, name, top, height)
                x = self.x_of(self.position)
                painter.setPen(QColor('#ffffff'))
                painter.drawLine(QPointF(x, top), QPointF(x, top + height))
                painter.restore()
            top += height + 4
        painter.end()

    def note(self, painter, top, height, text):
        painter.setPen(QColor('#8d97a6'))
        painter.drawText(QRectF(LEFT + 6, top, 700, height), Qt.AlignmentFlag.AlignVCenter, text)

    def paint_row(self, painter, name, top, height):
        result = self.result
        if name in ('final', 'v4', 'audio', 'motion'):
            segments = result['tracks'].get(name) or []
            if not segments:
                self.note(painter, top, height, {'audio': 'No usable audio', 'motion': 'No motion data from this camera',
                                                 'final': 'Marked not skydiving: nothing is cut'}.get(name, 'Unavailable'))
            for s in segments:
                x, end = self.x_of(s['start_sec']), self.x_of(s['end_sec'])
                painter.fillRect(QRectF(x, top, max(1., end - x), height),
                                 QColor(labeler.PHASE_COLORS.get(s['phase'], '#586e75')))
                if end - x > 70:
                    painter.setPen(QColor('#ffffff'))
                    painter.drawText(QRectF(max(x, LEFT) + 3, top, end - max(x, LEFT) - 5, height),
                                     Qt.AlignmentFlag.AlignVCenter, s['phase'].replace('_', ' '))
        elif name == 'trace':
            motion = result.get('motion') or {}
            trace = motion.get('trace')
            if not motion.get('available') or not trace:
                self.note(painter, top, height, 'No motion data from this camera')
                return
            low, high = 0.0, 3.0  # g
            y = lambda g: top + height - (max(low, min(high, g)) - low) / (high - low) * height
            for g in (0.0, 1.0, 2.0, 3.0):
                painter.setPen(QPen(QColor('#5a6678' if g == 1.0 else '#343f50'), 1, Qt.PenStyle.DotLine))
                painter.drawLine(QPointF(LEFT, y(g)), QPointF(self.width() - RIGHT, y(g)))
                painter.setPen(QColor('#8d97a6'))
                painter.setFont(QFont('Segoe UI', 7))
                painter.drawText(QRectF(LEFT + 2, y(g) - 10 if g else y(g) - 11, 24, 10), Qt.AlignmentFlag.AlignLeft,
                                 f'{g:g} g')
            painter.setPen(QPen(QColor('#9fd3ff'), 1.3))
            points = [QPointF(self.x_of(t + .5), y(g)) for t, g in zip(trace['t'], trace['load_g'])]
            for a, b in zip(points, points[1:]):
                painter.drawLine(a, b)
            painter.setFont(QFont('Segoe UI', 8))
            for label, field, color in (('exit', 'exit_sec', '#f0703a'), ('opening shock', 'opening_shock_sec', '#a39bff'),
                                        ('landing', 'landing_sec', '#7ccf7c')):
                value = (motion.get('events') or {}).get(field)
                if value is not None:
                    x = self.x_of(value + .5)
                    painter.setPen(QPen(QColor(color), 2))
                    painter.drawLine(QPointF(x, top), QPointF(x, top + height))
                    painter.drawText(QRectF(x + 3, top, 100, 14), Qt.AlignmentFlag.AlignLeft, label)
        elif name == 'people':
            people = result.get('people') or {}
            if not people.get('t'):
                self.note(painter, top, height, 'People were not counted for this video')
                return
            requirement = people.get('requirement') or {}
            floor = float(requirement.get('min_area') or 0)
            high = max(40.0, min(float(people.get('max_area') or 0), 150.0))  # keep the usual range readable
            y = lambda area: top + height - min(high, max(0.0, area)) / high * height
            # Seconds that clear the people filter are shaded, so a gap in the clips explains itself.
            for second, ok in zip(people['t'], people['matched']):
                if ok:
                    x = self.x_of(second - .5)
                    painter.fillRect(QRectF(x, top, max(1., self.x_of(second + .5) - x), height), QColor('#24402f'))
            if floor:
                painter.setPen(QPen(QColor('#7f8b9c'), 1, Qt.PenStyle.DashLine))
                painter.drawLine(QPointF(LEFT, y(floor)), QPointF(self.width() - RIGHT, y(floor)))
                painter.setPen(QColor('#8d97a6'))
                painter.setFont(QFont('Segoe UI', 7))
                painter.drawText(QRectF(self.width() - RIGHT - 122, y(floor) - 11, 120, 10),
                                 Qt.AlignmentFlag.AlignRight,
                                 f"needs {requirement.get('min_count', 0):g} person, {floor:g}%")
            painter.setPen(QPen(QColor('#8ce0b0'), 1.3))
            points = [QPointF(self.x_of(t), y(area)) for t, area in zip(people['t'], people['area'])]
            for a, b in zip(points, points[1:]):
                painter.drawLine(a, b)
            painter.setFont(QFont('Segoe UI', 8))
            painter.setPen(QColor('#8d97a6'))
            painter.drawText(QRectF(LEFT + 6, top + 1, 340, 12), Qt.AlignmentFlag.AlignLeft,
                             f"up to {people.get('max_count', 0)} in view, {people.get('max_area', 0):.0f}% of frame"
                             if people.get('counted') else 'nobody was seen in this video')
        elif name == 'agreement':
            for run in result.get('agreement') or []:
                x, end = self.x_of(run['start_sec']), self.x_of(run['end_sec'])
                painter.fillRect(QRectF(x, top, max(1., end - x), height), QColor(AGREEMENT_COLORS[run['status']]))
            if result.get('labels_used') in ('reviewed', 'excluded'):
                self.note(painter, top, height, 'Not compared: this video is cut from your review')
            elif result.get('agreement_basis') == 'none':
                self.note(painter, top, height, 'Nothing to compare with (no motion or audio)')
        elif name == 'clips':
            clips = result.get('clips') or []
            if not clips:
                self.note(painter, top, height, 'No clips were cut from this video')
            profiles = sorted({c['profile'] for c in clips})
            for c in clips:
                lane_height = height / max(1, len(profiles))
                lane_top = top + profiles.index(c['profile']) * lane_height
                x, end = self.x_of(c['start_sec']), self.x_of(c['end_sec'])
                color = CLIP_HOVER if c is self.hover_clip else CLIP_COLOR
                painter.fillRect(QRectF(x, lane_top, max(2., end - x), lane_height - 1), QColor(color))
                if end - x > 90:
                    painter.setPen(QColor('#ffffff'))
                    painter.drawText(QRectF(max(x, LEFT) + 3, lane_top, end - max(x, LEFT) - 5, lane_height),
                                     Qt.AlignmentFlag.AlignVCenter, f"{c['profile']}  (click to play)")

    def mousePressEvent(self, event):
        if not self.result or event.position().x() < LEFT:
            return
        clip = self.clip_at(event.position().x(), event.position().y())
        if event.button() == Qt.MouseButton.RightButton and clip:
            self.clip_menu(clip, event.globalPosition().toPoint())
        elif event.button() == Qt.MouseButton.LeftButton and clip:
            self.play_clip.emit(clip)
        elif event.button() == Qt.MouseButton.LeftButton:
            self.seek.emit(max(0., min(self.result['duration_sec'], self.seconds_at(event.position().x()))))

    def build_clip_menu(self, clip):
        menu = QMenu(self)
        menu.addAction('Play this clip here', lambda: self.play_clip.emit(clip))
        menu.addAction('Open in my video player', lambda: open_file(clip['clip_path']))
        menu.addAction('Show in folder', lambda: show_in_folder(clip['clip_path']))
        return menu

    def clip_menu(self, clip, where):
        self.build_clip_menu(clip).exec(where)

    def wheelEvent(self, event):
        if not self.result or not wheel_to_view(self.view, event, self.seconds_at(event.position().x())):
            super().wheelEvent(event)

    def leaveEvent(self, event):
        if self.hover_clip is not None:
            self.hover_clip = None
            self.update()

    def mouseMoveEvent(self, event):
        if not self.result or event.position().x() < LEFT:
            return
        name, title, _top, _height = self.row_at(event.position().y())
        seconds = self.seconds_at(event.position().x())
        clip = self.clip_at(event.position().x(), event.position().y())
        if clip is not self.hover_clip:
            self.hover_clip = clip
            self.update()
        self.setCursor(Qt.CursorShape.PointingHandCursor if clip else Qt.CursorShape.ArrowCursor)
        text = f'{title} at {clock(seconds)}'
        if name in ('final', 'v4', 'audio', 'motion'):
            s = next((s for s in self.result['tracks'].get(name) or [] if s['start_sec'] <= seconds < s['end_sec']), None)
            text = (f"{title}: {s['phase'].replace('_', ' ')}, {s['start_sec']:.1f}-{s['end_sec']:.1f}s"
                    if s else text + ': none')
        elif name == 'agreement':
            s = next((s for s in self.result.get('agreement') or [] if s['start_sec'] <= seconds < s['end_sec']), None)
            if s:
                text = f"{s['status']} with {self.result.get('agreement_basis')}, {s['start_sec']:.0f}-{s['end_sec']:.0f}s"
        elif name == 'people':
            people = self.result.get('people') or {}
            if people.get('t'):
                index = min(range(len(people['t'])), key=lambda i: abs(people['t'][i] - seconds))
                kept = 'meets your people filter' if people['matched'][index] else 'below your people filter'
                text = (f"{people['count'][index]} in view, {people['area'][index]:.0f}% of the frame at "
                        f"{clock(seconds)} - {kept}")
        elif name == 'clips':
            text = (f"{clip['profile']}: {clip['start_sec']:.1f}-{clip['end_sec']:.1f}s\n{clip['clip_path']}\n"
                    'Click to play it here; right-click for more.' if clip else 'No clip here')
            self.setToolTip(text)
            return
        self.setToolTip(text + '\nClick to jump here. Ctrl + wheel zooms.')


def open_file(path):
    """Play a clip in whatever the person uses, on whichever platform they are on."""
    if Path(path).exists():
        system.open_file(path)


def show_in_folder(path):
    if Path(path).exists():
        system.show_in_folder(path)


base.ComparisonTracks = PredictionTracks


def drain(layout):
    """Empty a layout and its sub-layouts, keeping the widgets (they are re-added elsewhere)."""
    while layout.count():
        item = layout.takeAt(0)
        if item.layout() is not None:
            drain(item.layout())


def detach(widget):
    """Remove a widget from whatever layout currently holds it, so it can join another without warnings."""
    def remove(layout):
        if layout.indexOf(widget) >= 0:
            layout.removeWidget(widget)
            return True
        return any(layout.itemAt(i).layout() is not None and remove(layout.itemAt(i).layout())
                   for i in range(layout.count()))
    parent = widget.parentWidget()
    if parent is not None and parent.layout() is not None:
        remove(parent.layout())


def small_button(text, tip, slot, width=None):
    button = QToolButton()
    button.setText(text)
    button.setToolTip(tip)
    button.clicked.connect(slot)
    if width:
        button.setMinimumWidth(width)
    return button


class CutterReviewWindow(base.ReviewWindow):
    reviews_changed = Signal(str)   # a video was marked reviewed, excluded or restored: it can be re-cut now

    def __init__(self, run, embedded=False):
        super().__init__(run)
        self.view = View()
        self.view.listeners.append(self.view_changed)
        self.comparison.view = self.view
        self.overlay_visible = True
        self.clip_stop_ms = None
        self.checks: list[tuple[float, float]] = []
        self._check_counts = {}
        self.setWindowTitle('Skydive Cutter - review cuts and labels')
        self.restructure()
        self.comparison.play_clip.connect(self.play_clip)
        self.extra_tracks.setText('Show all predictions and sensors')
        self.extra_tracks.setChecked(True)
        for key, slot in (('C', self.next_check), ('Shift+C', self.previous_check), ('O', self.toggle_overlay),
                          ('=', lambda: self.view.zoom(.5, self.current_time_sec())),
                          ('-', lambda: self.view.zoom(2.0, self.current_time_sec())), ('0', self.view_fit)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(slot)
        self.labeller_shortcuts = self.findChildren(QShortcut)
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
            self.menuBar().hide()
        self.load_current_video()
        self.refresh_video_list()

    # ------------------------------------------------------------------------------------------------ layout
    def restructure(self):
        """Rearrange the base labeller: compact toolbar, phase chips, and one aligned, zoomable track block."""
        layout = self.top_panel.layout()
        drain(layout)
        for widget in (self.previous_video_button, self.next_video_button, self.back_5_button, self.back_1_button,
                       self.play_button, self.forward_1_button, self.forward_5_button, self.last_frame_button,
                       self.mute_button, self.review_button, self.exclude_button, *self.phase_buttons.values()):
            detach(widget)
        # The editable timeline on the shared view (replaces the base widget; same signals, same data).
        old = self.segment_timeline
        timeline = ZoomTimeline(self.view, self.top_panel)
        timeline.segmentClicked.connect(self.select_segment_from_timeline)
        timeline.emptyClicked.connect(self.prepare_new_segment_from_timeline)
        timeline.dividerDragStarted.connect(self.begin_timeline_divider_drag)
        timeline.dividerDragged.connect(self.drag_timeline_divider)
        timeline.dividerDragFinished.connect(self.finish_timeline_divider_drag)
        timeline.set_timeline_ranges(old.timeline_ranges, old.duration_ms, old.selected_segment_index, old.playhead_ms)
        self.segment_timeline = timeline
        old.setParent(None)
        old.deleteLater()

        layout.addWidget(self.video_view, 1)
        self.video_view.show()
        layout.addWidget(self.position_slider)
        self.position_slider.show()

        # Toolbar: video, playback, checks, zoom.
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)
        relabel = [(self.previous_video_button, '< Video', 'Previous video (P)'),
                   (self.next_video_button, 'Video >', 'Next video (N)'),
                   (self.back_5_button, '<< 5s', 'Back 5 seconds (Shift+Left)'),
                   (self.back_1_button, '< 1s', 'Back 1 second (Left)'),
                   (self.play_button, 'Play / Pause', 'Play or pause (Space)'),
                   (self.forward_1_button, '1s >', 'Forward 1 second (Right)'),
                   (self.forward_5_button, '5s >>', 'Forward 5 seconds (Shift+Right)'),
                   (self.last_frame_button, 'End', 'Last frame (End)'),
                   (self.mute_button, None, 'Mute or unmute (M)')]
        for index, (button, text, tip) in enumerate(relabel):
            if text:
                button.setText(text)
            button.setToolTip(tip)
            button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            button.show()
            toolbar.addWidget(button)
            if index in (1, 7):
                toolbar.addSpacing(14)
        toolbar.addSpacing(18)
        self.check_label = QLabel('No checks')
        self.check_label.setMinimumWidth(92)
        self.check_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        toolbar.addWidget(small_button('< Check', 'Previous stretch where the sources disagree (Shift+C)', self.previous_check))
        toolbar.addWidget(self.check_label)
        toolbar.addWidget(small_button('Check >', 'Next stretch where the sources disagree (C)', self.next_check))
        toolbar.addStretch()
        self.zoom_label = QLabel('Whole video')
        self.zoom_label.setObjectName('hint')
        toolbar.addWidget(self.zoom_label)
        toolbar.addWidget(small_button('-', 'Zoom out (-)', lambda: self.view.zoom(2.0, self.current_time_sec()), 26))
        toolbar.addWidget(small_button('Fit', 'Show the whole video (0)', self.view_fit))
        toolbar.addWidget(small_button('+', 'Zoom in (=, or Ctrl + mouse wheel)', lambda: self.view.zoom(.5, self.current_time_sec()), 26))
        layout.addLayout(toolbar)

        # Phase chips: set the phase being labelled, and the colour legend for every row.
        chips = QHBoxLayout()
        chips.setSpacing(3)
        chip_font = QFont('Segoe UI', 8)
        for key, phase, label in labeler.PHASE_BUTTONS:
            button = self.phase_buttons[phase]
            button.setText(f'{key} {label}')
            button.setFont(chip_font)
            button.setObjectName('chip')  # the app theme gives chips tight padding; the base restyles colours only
            button.setFixedHeight(26)
            button.setToolTip(f'Label from here as {label.lower()} (key {key})')
            button.show()
            chips.addWidget(button)
        layout.addLayout(chips)

        info = QHBoxLayout()
        for widget in (self.video_label, self.time_label, self.phase_label, self.segment_start_label,
                       self.segment_duration_label):
            widget.show()
            info.addWidget(widget)
        info.addStretch()
        layout.addLayout(info)
        self.review_banner.show()
        layout.addWidget(self.review_banner)

        # The aligned block: your labels, then every prediction, all on one time axis.
        labels_row = QHBoxLayout()
        labels_row.setContentsMargins(0, 0, 0, 0)
        labels_row.setSpacing(0)
        title = QLabel('Your labels')
        title.setFixedWidth(LABEL_COLUMN)
        title.setStyleSheet('font-weight: bold; padding-left: 4px;')
        title.setToolTip('Your editable labels. Drag a boundary to move it; click a phase chip, then Finish, to add one.')
        labels_row.addWidget(title)
        labels_row.addWidget(timeline, 1)
        block = QWidget()
        block_layout = QVBoxLayout(block)
        block_layout.setContentsMargins(0, 0, 0, 0)
        block_layout.setSpacing(0)
        block_layout.addLayout(labels_row)
        block_layout.addWidget(self.comparison)
        self.track_block = block
        self.comparison.show()
        layout.addWidget(block)

        actions = QHBoxLayout()
        self.extra_tracks.show()
        actions.addWidget(self.extra_tracks)
        actions.addStretch()
        for button in (self.review_button, self.exclude_button):
            button.setParent(self.top_panel)
            button.show()
            actions.addWidget(button)
        layout.addLayout(actions)

        # Editing tools stay in the lower panel, compact; tools the cutter does not use are hidden.
        for widget in (self.evaluate_button, self.open_folder_button, self.keep_checkbox, self.phase_combo,
                       self.save_button):
            widget.hide()
        for button, text in ((self.skip_button, 'Skip phase (Tab)'), (self.back_phase_button, 'Back a phase (B)'),
                             (self.delete_selected_button, 'Delete segment (Del)'),
                             (self.mark_boring_button, 'Whole video empty')):
            button.setText(text)
        self.main_splitter.setSizes([760, 240])
        self.content_splitter.setSizes([1130, 330])

    # ------------------------------------------------------------------------------------------------ zoom
    def view_changed(self):
        start, end = self.view.window()
        if hasattr(self, 'zoom_label'):
            self.zoom_label.setText(f'Showing {clock(start)}-{clock(end)}' if self.view.zoomed() else 'Whole video')
        self.segment_timeline.update()
        self.comparison.update()

    def view_fit(self):
        self.view.set(0, self.view.duration)

    # ------------------------------------------------------------------------------------------------ base hooks
    def refresh_ui(self):
        super().refresh_ui()
        if self.current_phase == labeler.PHASES[-1]:
            self.finish_button.setText(f'Finish {self.current_phase.replace("_", " ")} (Enter)')
        else:
            self.finish_button.setText(f'Finish {self.current_phase.replace("_", " ")}, next '
                                       f'{self.next_phase_name().replace("_", " ")} (Enter)')

    def load_current_video(self):
        super().load_current_video()
        view = getattr(self, 'view', None)
        if view is None:
            return
        source = self.current_video_path()
        result = self.results.get(base.key(source)) if source else None
        self.comparison.result = result
        view.reset(float(result['duration_sec']) if result else 0.0)
        self.checks = checks_from(result.get('agreement')) if result else []
        self.update_check_label()

    def update_comparison_position(self, milliseconds):
        super().update_comparison_position(milliseconds)
        seconds = milliseconds / 1000.
        if self.clip_stop_ms is not None and milliseconds >= self.clip_stop_ms:
            self.clip_stop_ms = None
            self.player.pause()
        view = getattr(self, 'view', None)
        if view is not None and view.zoomed():
            start, end = view.window()
            if seconds > end or seconds < start:
                view.ensure_visible(seconds)
        if hasattr(self, 'check_label'):
            self.update_check_label()

    def update_overlay_graphics(self):
        labeler.ManualVideoLabeler.update_overlay_graphics(self)
        source = self.current_video_path()
        result = self.results.get(base.key(source)) if source else None
        visible = getattr(self, 'overlay_visible', True) and result is not None
        self.overlay_rect.setVisible(visible)
        self.overlay_text.setVisible(visible)
        if not visible:
            return
        position = self.current_time_sec()

        def at(track):
            s = next((s for s in result['tracks'].get(track) or [] if s['start_sec'] <= position < s['end_sec']), None)
            return s['phase'].replace('_', ' ') if s else '-'
        font = QFont('Segoe UI', 10)
        font.setBold(True)
        self.overlay_text.setFont(font)
        people = result.get('people') or {}
        seen = ''
        if people.get('t'):
            index = min(range(len(people['t'])), key=lambda i: abs(people['t'][i] - position))
            seen = f"  |  {people['count'][index]} in view ({people['area'][index]:.0f}%)"
        self.overlay_text.setPlainText(f"{at('final')}  |  V4 {at('v4')}  |  Audio {at('audio')}  |  "
                                       f"Motion {at('motion')}{seen}  |  {labeler.seconds_to_label(position)}")
        rect = self.overlay_text.boundingRect()
        height = self.video_view.viewport().height()
        self.overlay_text.setPos(16, max(8, height - rect.height() - 14))
        self.overlay_rect.setRect(QRectF(8, max(4, height - rect.height() - 18), rect.width() + 16, rect.height() + 8))

    def toggle_overlay(self):
        self.overlay_visible = not self.overlay_visible
        self.update_overlay_graphics()

    # ------------------------------------------------------------------------------------------------ checks
    def update_check_label(self):
        if not self.checks:
            self.check_label.setText('No checks')
            return
        position = self.current_time_sec()
        inside = next((i for i, (start, end) in enumerate(self.checks) if start - 1.5 <= position < end), None)
        if inside is not None:
            self.check_label.setText(f'Check {inside + 1} of {len(self.checks)}')
        else:
            self.check_label.setText(f'{len(self.checks)} to check')

    def jump_to_check(self, index):
        start, end = self.checks[index]
        target = max(0.0, start - 1.0)
        self.seek_absolute_milliseconds(round(target * 1000))
        self.update_comparison_position(round(target * 1000))
        if self.view.zoomed():
            self.view.ensure_visible(target)
        self.check_label.setText(f'Check {index + 1} of {len(self.checks)}')

    def next_check(self):
        position = self.current_time_sec()
        index = next((i for i, (start, _end) in enumerate(self.checks) if start - 1.0 > position + .25), None)
        if index is not None:
            self.jump_to_check(index)

    def previous_check(self):
        position = self.current_time_sec()
        earlier = [i for i, (start, _end) in enumerate(self.checks) if start - 1.0 < position - .75]
        if earlier:
            self.jump_to_check(earlier[-1])

    def check_count(self, source):
        result = self.results.get(base.key(source)) or {}
        return len(checks_from(result.get('agreement')))

    def refresh_video_list(self):
        super().refresh_video_list()
        if not hasattr(self, 'results'):
            return
        for index, source in enumerate(self.videos):
            item = self.video_list.item(index)
            count = self.check_count(source)
            if item is not None and count:
                item.setText(f'{item.text()}  ({count} to check)')

    # ------------------------------------------------------------------------------------------------ clips
    def play_clip(self, clip):
        self.seek_absolute_milliseconds(round(clip['start_sec'] * 1000))
        self.clip_stop_ms = round(clip['end_sec'] * 1000)
        self.view.ensure_visible(clip['start_sec'])
        self.player.play()

    # ------------------------------------------------------------------------------------------------ reviews
    def set_shortcuts_enabled(self, enabled):
        """The labeller's keys (Space, Tab, digits...) must only act while the Review tab is showing."""
        for shortcut in self.labeller_shortcuts:
            shortcut.setEnabled(enabled)

    def mark_reviewed(self):
        source = self.current_video_path()
        was_reviewed = self.review_state.get(base.key(source)) if source else None
        super().mark_reviewed()
        rows = [dict(r) for r in self.rows_for(source)] if source else []  # after the final-section snap
        saved = self.review_state.get(base.key(source)) if source else None
        if saved and saved.get('fingerprint') == annotation_fingerprint(rows):
            saved['rows'] = [{k: r[k] for k in FIELDS} for r in rows]
            write_json(self.review_state_path, self.review_state)
            if saved is not was_reviewed:
                self.reviews_changed.emit(str(source))

    def toggle_exclusion(self):
        source = self.current_video_path()
        super().toggle_exclusion()
        if source is not None:
            self.reviews_changed.emit(str(source))

    def reload_run(self):
        """Pick up newly processed or re-cut videos without disturbing the video being reviewed."""
        from review_exclusions import read_mapping

        current = self.current_video_path()
        status = json.loads((self.run_directory / 'status.json').read_text(encoding='utf-8'))
        self.records = [r for r in status['records'] if r['status'] == 'success']
        self.results = {base.key(r['source_video']): json.loads((self.run_directory / r['result']).read_text(encoding='utf-8'))
                        for r in self.records}
        self.review_state = read_mapping(self.review_state_path)
        self.exclusions = read_mapping(self.exclusions_path)
        known = {base.key(s.source_video) for s in self.segments}
        for row in read_csv(self.run_directory / 'review.csv'):
            if base.key(row['source_video']) not in known:
                self.segments.append(labeler.Segment(row['source_video'], row['start_sec'], row['end_sec'],
                                                     row['phase'], row['keep'], row.get('notes', '')))
        self.videos = [Path(r['source_video']) for r in self.records]
        if current is not None:
            self.video_index = next((i for i, v in enumerate(self.videos) if base.key(v) == base.key(current)), 0)
        self.refresh_video_list()
        source = self.current_video_path()
        if source is not None and (current is None or base.key(source) != base.key(current)):
            self.load_current_video()
        elif source is not None:
            result = self.results.get(base.key(source))
            self.comparison.result = result
            self.checks = checks_from(result.get('agreement')) if result else []
            self.update_check_label()
            self.comparison.update()
            self.update_review_banner()

    def show_video(self, source):
        """Jump to a video by path, e.g. from the results list."""
        index = next((i for i, v in enumerate(self.videos) if base.key(v) == base.key(source)), None)
        if index is not None and index != self.video_index:
            self.save_csv_silent()
            self.video_index = index
            self.load_current_video()
            self.refresh_video_list()
        return index is not None

    def update_review_banner(self):
        source = self.current_video_path()
        if source is None:
            return
        result = self.results[base.key(source)]
        excluded = self.exclusions.get(base.key(source))
        used = result.get('labels_used', 'model')
        if excluded:
            status = 'NOT SKYDIVING - no clips' if used == 'excluded' else 'NOT SKYDIVING - its clips will be removed'
        elif self.reviewed(source):
            status = ('REVIEWED - clips were cut from your labels' if used == 'reviewed'
                      else 'REVIEWED - will be re-cut from your labels')
        elif used == 'reviewed':
            status = 'EDITED SINCE REVIEW - clips follow your last reviewed labels until you mark it again'
        else:
            status = 'NOT REVIEWED - clips follow the model'
        flags = ' '.join(result.get('review_flags') or [])
        clips = result.get('clips') or []
        self.review_button.setEnabled(not bool(excluded))
        self.exclude_button.setText('Restore video' if excluded else 'Not skydiving')
        self.review_banner.setText(f'<b>{status}</b> &nbsp;|&nbsp; {len(clips)} clip(s) cut'
                                   + (f' &nbsp;|&nbsp; {flags}' if flags else ''))
        self.review_banner.setToolTip('Your labels start from the Final track. Amber in Agreement marks stretches worth '
                                      'checking (C jumps to the next one). Marking a video reviewed re-cuts it from '
                                      'your labels.')
