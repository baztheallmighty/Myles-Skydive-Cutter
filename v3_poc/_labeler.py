# FROZEN: inherited research code for the labelling window. It ships and runs, but is not maintained in place:
# fix behaviour in cutter_v4/review_ui.py or app/ui/review_tab.py, or replace this file wholesale.
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QTimer, QSizeF, QRectF, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QFont, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".mts",
    ".m2ts",
    ".wmv",
    ".mpg",
    ".mpeg",
}


PHASES = [
    "inside_plane",
    "other_groups_climbing_out",
    "climbing_out",
    "exit",
    "freefall",
    "break_off",
    "opening_parachutes",
    "canopy_flight",
    "landing",
    "landed",
]

EXTRA_PHASES = [
    "empty_or_boring",
    "unknown",
]

ALL_PHASES = PHASES + EXTRA_PHASES

DEFAULT_KEEP = {
    "inside_plane": False,
    "other_groups_climbing_out": False,
    "climbing_out": True,
    "exit": True,
    "freefall": True,
    "break_off": True,
    "opening_parachutes": False,
    "canopy_flight": False,
    "landing": True,
    "landed": False,
    "empty_or_boring": False,
    "unknown": False,
}

PHASE_COLORS = {
    "inside_plane": "#268bd2",
    "other_groups_climbing_out": "#2aa198",
    "climbing_out": "#b58900",
    "exit": "#cb4b16",
    "freefall": "#dc322f",
    "break_off": "#d33682",
    "opening_parachutes": "#6c71c4",
    "canopy_flight": "#859900",
    "landing": "#5f9f5f",
    "landed": "#657b83",
    "empty_or_boring": "#586e75",
    "unknown": "#93a1a1",
}

SEEK_SMALL_SECONDS = 1.0
SEEK_LARGE_SECONDS = 5.0
LAST_FRAME_SEEK_BACK_MS = 250
MIN_DRAGGED_SEGMENT_SECONDS = 0.05
TIMELINE_EPSILON_SECONDS = 0.001
SNAP_THRESHOLD_SECONDS = 0.25
TIMELINE_TRACK_MARGIN_PX = 8

PHASE_BUTTONS = [
    ("1", "inside_plane", "Inside Plane"),
    ("2", "other_groups_climbing_out", "Other Group"),
    ("3", "climbing_out", "Climb Out"),
    ("4", "exit", "Exit"),
    ("5", "freefall", "Freefall"),
    ("6", "break_off", "Break Off"),
    ("7", "opening_parachutes", "Opening"),
    ("8", "canopy_flight", "Canopy"),
    ("9", "landing", "Landing"),
    ("0", "landed", "Landed"),
    ("-", "empty_or_boring", "Empty/Boring"),
    ("=", "unknown", "Unknown"),
]


@dataclass
class Segment:
    source_video: str
    start_sec: float
    end_sec: float
    phase: str
    keep: bool
    notes: str = ""


@dataclass(frozen=True)
class TimelineIssue:
    level: str
    code: str
    message: str
    segment_indexes: tuple[int, ...] = ()


def seconds_to_label(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    minutes = int(seconds // 60)
    secs = seconds - (minutes * 60)
    return f"{minutes:02d}:{secs:06.3f}"


def milliseconds_to_seconds(milliseconds: int) -> float:
    return max(0.0, float(milliseconds) / 1000.0)


def seconds_to_milliseconds(seconds: float) -> int:
    return int(round(max(0.0, float(seconds)) * 1000.0))


def slider_position_from_mouse_x(
    x: float,
    width: int,
    minimum: int,
    maximum: int,
    margin: int = TIMELINE_TRACK_MARGIN_PX,
) -> int:
    if maximum <= minimum or width <= 0:
        return int(minimum)

    usable_width = max(1, int(width) - (int(margin) * 2))
    ratio = max(0.0, min(1.0, (float(x) - int(margin)) / usable_width))
    return int(minimum) + int(round(ratio * (int(maximum) - int(minimum))))


def slider_x_from_position(
    position: int,
    width: int,
    minimum: int,
    maximum: int,
    margin: int = TIMELINE_TRACK_MARGIN_PX,
) -> int:
    if maximum <= minimum or width <= 0:
        return int(margin)

    usable_width = max(1, int(width) - (int(margin) * 2))
    ratio = max(0.0, min(1.0, (int(position) - int(minimum)) / (int(maximum) - int(minimum))))
    return int(margin) + int(round(ratio * usable_width))


PHASE_INDEX = {phase: index for index, phase in enumerate(PHASES)}


def segment_source_key(source_video: str) -> str:
    try:
        return str(Path(source_video).expanduser().absolute()).replace("\\", "/").casefold()
    except Exception:
        return str(source_video).replace("\\", "/").casefold()


def segments_match_source(left: Segment, right: Segment) -> bool:
    return segment_source_key(left.source_video) == segment_source_key(right.source_video)


def clone_segment(segment: Segment, start_sec: float, end_sec: float) -> Segment:
    return Segment(
        source_video=segment.source_video,
        start_sec=round(start_sec, 3),
        end_sec=round(end_sec, 3),
        phase=segment.phase,
        keep=segment.keep,
        notes=segment.notes,
    )


def replace_overlapping_segments(
    segments: list[Segment],
    new_segment: Segment,
    ignore_index: int | None = None,
) -> list[Segment]:
    if new_segment.end_sec <= new_segment.start_sec:
        raise ValueError("segment end must be after segment start")

    replacement: list[Segment] = []

    for index, segment in enumerate(segments):
        if ignore_index is not None and index == ignore_index:
            continue

        if not segments_match_source(segment, new_segment):
            replacement.append(segment)
            continue

        if segment.end_sec <= new_segment.start_sec or segment.start_sec >= new_segment.end_sec:
            replacement.append(segment)
            continue

        if segment.start_sec < new_segment.start_sec:
            left_end = min(segment.end_sec, new_segment.start_sec)
            if left_end - segment.start_sec > TIMELINE_EPSILON_SECONDS:
                replacement.append(clone_segment(segment, segment.start_sec, left_end))

        if segment.end_sec > new_segment.end_sec:
            right_start = max(segment.start_sec, new_segment.end_sec)
            if segment.end_sec - right_start > TIMELINE_EPSILON_SECONDS:
                replacement.append(clone_segment(segment, right_start, segment.end_sec))

    replacement.append(new_segment)
    return replacement


def validate_segment_indexes(segments: list[Segment], indexes: list[int]) -> list[TimelineIssue]:
    issues: list[TimelineIssue] = []
    ordered_indexes = sorted(indexes, key=lambda index: (segments[index].start_sec, segments[index].end_sec, index))

    for index in ordered_indexes:
        segment = segments[index]
        if segment.end_sec <= segment.start_sec:
            issues.append(
                TimelineIssue(
                    level="error",
                    code="zero_or_negative",
                    message=(
                        f"{segment.phase} has end <= start "
                        f"({seconds_to_label(segment.start_sec)}-{seconds_to_label(segment.end_sec)})"
                    ),
                    segment_indexes=(index,),
                )
            )

    for previous_index, index in zip(ordered_indexes, ordered_indexes[1:]):
        previous = segments[previous_index]
        segment = segments[index]

        if segment.start_sec < previous.end_sec - TIMELINE_EPSILON_SECONDS:
            issues.append(
                TimelineIssue(
                    level="error",
                    code="overlap",
                    message=(
                        f"{previous.phase} overlaps {segment.phase} "
                        f"at {seconds_to_label(segment.start_sec)}"
                    ),
                    segment_indexes=(previous_index, index),
                )
            )
        elif segment.start_sec > previous.end_sec + TIMELINE_EPSILON_SECONDS:
            issues.append(
                TimelineIssue(
                    level="warning",
                    code="gap",
                    message=(
                        f"gap from {seconds_to_label(previous.end_sec)} "
                        f"to {seconds_to_label(segment.start_sec)}"
                    ),
                    segment_indexes=(previous_index, index),
                )
            )

        previous_order = PHASE_INDEX.get(previous.phase)
        current_order = PHASE_INDEX.get(segment.phase)
        if previous_order is not None and current_order is not None and current_order < previous_order:
            issues.append(
                TimelineIssue(
                    level="warning",
                    code="phase_order_backwards",
                    message=f"phase order goes backward: {previous.phase} -> {segment.phase}",
                    segment_indexes=(previous_index, index),
                )
            )

    phase_indexes: dict[str, list[int]] = {}
    for index in ordered_indexes:
        phase = segments[index].phase
        if phase in PHASE_INDEX:
            phase_indexes.setdefault(phase, []).append(index)

    for phase, duplicate_indexes in phase_indexes.items():
        if len(duplicate_indexes) > 1:
            issues.append(
                TimelineIssue(
                    level="warning",
                    code="duplicate_phase",
                    message=f"duplicate phase sections: {phase} x{len(duplicate_indexes)}",
                    segment_indexes=tuple(duplicate_indexes),
                )
            )

    return issues


def validate_segments_by_source(segments: list[Segment]) -> dict[str, list[TimelineIssue]]:
    grouped_indexes: dict[str, list[int]] = {}

    for index, segment in enumerate(segments):
        grouped_indexes.setdefault(segment_source_key(segment.source_video), []).append(index)

    return {
        source_key: validate_segment_indexes(segments, indexes)
        for source_key, indexes in grouped_indexes.items()
    }


def last_frame_preview_milliseconds(duration_ms: int) -> int:
    return max(0, int(duration_ms) - LAST_FRAME_SEEK_BACK_MS)


def effective_finish_end_seconds(current_sec: float, duration_sec: float, finish_at_video_end: bool) -> float:
    if finish_at_video_end and duration_sec > 0:
        return duration_sec
    return current_sec


def next_phase_after_phase(phase: str | None) -> str:
    if phase in PHASES:
        index = PHASES.index(phase)
        if index + 1 < len(PHASES):
            return PHASES[index + 1]
        return phase

    if phase in EXTRA_PHASES:
        return phase

    return PHASES[0]


def infer_next_phase_after(segments: list[Segment], indexes: list[int], time_sec: float) -> str:
    previous_phase: str | None = None

    for index in sorted(indexes, key=lambda value: (segments[value].start_sec, segments[value].end_sec, value)):
        segment = segments[index]
        if segment.end_sec <= time_sec + TIMELINE_EPSILON_SECONDS:
            previous_phase = segment.phase
        elif segment.start_sec > time_sec:
            break

    return next_phase_after_phase(previous_phase)


def previous_segment_end_at_or_before(segments: list[Segment], indexes: list[int], end_sec: float) -> float:
    latest = 0.0

    for index in indexes:
        segment = segments[index]
        if segment.end_sec <= end_sec + TIMELINE_EPSILON_SECONDS and segment.end_sec > latest:
            latest = segment.end_sec

    return round(latest, 3)


def snap_seconds(
    value: float,
    candidates: list[float],
    threshold_seconds: float = SNAP_THRESHOLD_SECONDS,
) -> float:
    best = float(value)
    best_distance = float(threshold_seconds)

    for candidate in candidates:
        distance = abs(float(candidate) - float(value))
        if distance <= best_distance:
            best = float(candidate)
            best_distance = distance

    return round(best, 3)


def boundary_snap_candidates(
    segments: list[Segment],
    indexes: list[int],
    dragged_refs: set[tuple[int, str]],
    playhead_sec: float,
    duration_sec: float,
) -> list[float]:
    candidates = [0.0, max(0.0, duration_sec), max(0.0, playhead_sec)]

    for index in indexes:
        segment = segments[index]
        if (index, "start") not in dragged_refs:
            candidates.append(segment.start_sec)
        if (index, "end") not in dragged_refs:
            candidates.append(segment.end_sec)

    return candidates


def phase_color(phase: str, alpha: int | None = None) -> QColor:
    color = QColor(PHASE_COLORS.get(phase, PHASE_COLORS["unknown"]))
    if alpha is not None:
        color.setAlpha(alpha)
    return color


def contrasting_text_color(color: QColor) -> str:
    luminance = (0.299 * color.red()) + (0.587 * color.green()) + (0.114 * color.blue())
    return "black" if luminance >= 150 else "white"


class VideoGraphicsView(QGraphicsView):
    def __init__(self, parent_window: "ManualVideoLabeler"):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.setMinimumHeight(360)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("background: black;")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.parent_window.resize_video_scene()


class SeekSlider(QSlider):
    seekRequested = Signal(int)

    def __init__(self, orientation: Qt.Orientation, parent=None):
        super().__init__(orientation, parent)
        self.setMinimumHeight(34)

    def position_from_mouse_x(self, x: float) -> int:
        return slider_position_from_mouse_x(x, self.width(), self.minimum(), self.maximum())

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            position = self.position_from_mouse_x(event.position().x())
            self.setSliderDown(True)
            self.setValue(position)
            self.seekRequested.emit(position)
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.isSliderDown() and event.buttons() & Qt.MouseButton.LeftButton:
            position = self.position_from_mouse_x(event.position().x())
            self.setValue(position)
            self.sliderMoved.emit(position)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self.isSliderDown() and event.button() == Qt.MouseButton.LeftButton:
            position = self.position_from_mouse_x(event.position().x())
            self.setValue(position)
            self.setSliderDown(False)
            self.seekRequested.emit(position)
            event.accept()
            return

        super().mouseReleaseEvent(event)


class SegmentTimelineWidget(QWidget):
    segmentClicked = Signal(int, int)
    emptyClicked = Signal(int)
    dividerDragStarted = Signal(int)
    dividerDragged = Signal(int)
    dividerDragFinished = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.timeline_ranges: list[tuple[float, float, str, int]] = []
        self.duration_ms = 0
        self.playhead_ms = 0
        self.selected_segment_index: int | None = None
        self.active_divider_ms: int | None = None
        self.setMinimumHeight(38)
        self.setMouseTracking(True)

    def set_timeline_ranges(
        self,
        ranges: list[tuple[float, float, str, int]],
        duration_ms: int,
        selected_segment_index: int | None = None,
        playhead_ms: int = 0,
    ) -> None:
        self.timeline_ranges = ranges
        self.duration_ms = max(0, int(duration_ms))
        self.selected_segment_index = selected_segment_index
        self.playhead_ms = max(0, min(int(playhead_ms), self.duration_ms)) if self.duration_ms > 0 else 0
        self.update()

    def set_playhead_milliseconds(self, playhead_ms: int, duration_ms: int | None = None) -> None:
        if duration_ms is not None:
            self.duration_ms = max(0, int(duration_ms))

        next_playhead_ms = max(0, min(int(playhead_ms), self.duration_ms)) if self.duration_ms > 0 else 0
        if next_playhead_ms == self.playhead_ms:
            return

        self.playhead_ms = next_playhead_ms
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            divider_ms = self.nearest_divider_ms(event.position().x())
            if divider_ms is not None:
                self.active_divider_ms = divider_ms
                self.dividerDragStarted.emit(divider_ms)
                event.accept()
                return

            position = self.position_from_mouse_x(event.position().x())
            segment_index = self.segment_index_from_mouse_x(event.position().x())
            if segment_index is None:
                self.emptyClicked.emit(position)
            else:
                self.segmentClicked.emit(segment_index, position)
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.active_divider_ms is not None and event.buttons() & Qt.MouseButton.LeftButton:
            position = self.position_from_mouse_x(event.position().x())
            self.dividerDragged.emit(position)
            event.accept()
            return

        if self.nearest_divider_ms(event.position().x()) is not None:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif self.segment_index_from_mouse_x(event.position().x()) is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self.active_divider_ms is not None and event.button() == Qt.MouseButton.LeftButton:
            position = self.position_from_mouse_x(event.position().x())
            self.dividerDragFinished.emit(position)
            self.active_divider_ms = None
            self.unsetCursor()
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def position_from_mouse_x(self, x: float) -> int:
        if self.duration_ms <= 0:
            return 0

        margin = TIMELINE_TRACK_MARGIN_PX
        usable_width = max(1, self.width() - (margin * 2))
        ratio = max(0.0, min(1.0, (float(x) - margin) / usable_width))
        return int(round(ratio * self.duration_ms))

    def segment_index_from_mouse_x(self, x: float) -> int | None:
        if self.duration_ms <= 0:
            return None

        position_ms = self.position_from_mouse_x(x)
        position_sec = milliseconds_to_seconds(position_ms)

        for start_sec, end_sec, _phase, segment_index in self.timeline_ranges:
            if start_sec <= position_sec <= end_sec:
                return segment_index

        return None

    def nearest_divider_ms(self, x: float) -> int | None:
        if self.duration_ms <= 0:
            return None

        margin = TIMELINE_TRACK_MARGIN_PX
        track_width = max(1, self.width() - (margin * 2))
        best_distance = 9999.0
        best_ms: int | None = None

        for start_sec, end_sec, _phase, segment_index in self.timeline_ranges:
            for boundary_sec in (start_sec, end_sec):
                boundary_ms = seconds_to_milliseconds(boundary_sec)
                if boundary_ms <= 0 or boundary_ms >= self.duration_ms:
                    continue
                boundary_x = margin + ((boundary_ms / self.duration_ms) * track_width)
                distance = abs(float(x) - boundary_x)
                if distance < best_distance:
                    best_distance = distance
                    best_ms = boundary_ms

        if best_distance <= 8.0:
            return best_ms

        return None

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        margin = TIMELINE_TRACK_MARGIN_PX
        track_left = margin
        track_width = max(1, self.width() - (margin * 2))
        track_top = 9
        track_height = max(14, self.height() - 18)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(40, 40, 40, 210))
        painter.drawRect(track_left, track_top, track_width, track_height)

        if self.duration_ms <= 0 or not self.timeline_ranges:
            painter.setPen(QPen(QColor(230, 230, 230, 180), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(track_left, track_top, track_width, track_height)
            self.paint_playhead_overlay(painter, track_left, track_width, track_top, track_height)
            return

        divider_positions: set[int] = set()

        for start_sec, end_sec, phase, segment_index in self.timeline_ranges:
            start_ms = seconds_to_milliseconds(start_sec)
            end_ms = seconds_to_milliseconds(end_sec)
            if end_ms <= start_ms:
                continue

            start_ratio = max(0.0, min(1.0, start_ms / self.duration_ms))
            end_ratio = max(0.0, min(1.0, end_ms / self.duration_ms))
            x = track_left + int(round(start_ratio * track_width))
            width = max(1, int(round((end_ratio - start_ratio) * track_width)))

            painter.setBrush(phase_color(phase, 220))
            painter.drawRect(x, track_top, width, track_height)

            if segment_index == self.selected_segment_index:
                painter.setPen(QPen(QColor("white"), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(x, track_top, width, track_height)
                painter.setPen(Qt.PenStyle.NoPen)

            divider_positions.add(start_ms)
            divider_positions.add(end_ms)

        painter.setBrush(QColor(0, 0, 0, 245))
        for divider_ms in sorted(divider_positions):
            if divider_ms <= 0 or divider_ms >= self.duration_ms:
                continue

            ratio = max(0.0, min(1.0, divider_ms / self.duration_ms))
            x = track_left + int(round(ratio * track_width))
            painter.drawRect(x - 2, track_top - 3, 4, track_height + 6)

        painter.setPen(QPen(QColor(230, 230, 230, 180), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(track_left, track_top, track_width, track_height)
        self.paint_playhead_overlay(painter, track_left, track_width, track_top, track_height)

    def paint_playhead_overlay(
        self,
        painter: QPainter,
        track_left: int,
        track_width: int,
        track_top: int,
        track_height: int,
    ) -> None:
        if self.duration_ms <= 0:
            return

        x = track_left + int(round((self.playhead_ms / self.duration_ms) * track_width))
        top = max(0, track_top - 7)
        bottom = min(self.height() - 1, track_top + track_height + 7)

        painter.setPen(QPen(QColor("#268bd2"), 3))
        painter.drawLine(x, top, x, bottom)
        painter.setPen(QPen(QColor("white"), 1))
        painter.drawLine(x + 2, top + 1, x + 2, bottom)


class ManualVideoLabeler(QMainWindow):
    def __init__(self, input_folder: Path | None, csv_path: Path):
        super().__init__()

        self.setWindowTitle("Skydiving Manual Video Phase Labeler")

        self.input_folder = input_folder
        self.csv_path = csv_path
        self.videos: list[Path] = []
        self.video_index = 0

        self.segments: list[Segment] = []

        self.current_phase_index = 0
        self.current_phase = PHASES[0]
        self.current_segment_start_sec = 0.0
        self.active_start_sec: float | None = None
        self.drag_boundary_refs: list[tuple[int, str]] = []
        self.drag_boundary_changed = False
        self.active_segment_index: int | None = None
        self.table_segment_indexes: list[int] = []
        self.refreshing_video_list = False
        self.syncing_from_timeline = False

        self.ignore_slider_updates = False
        self.is_muted = False
        self.last_volume = 0.5
        self.finish_at_video_end = False

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)

        self.scene = QGraphicsScene(self)
        self.video_item = QGraphicsVideoItem()
        self.overlay_rect = QGraphicsRectItem()
        self.overlay_text = QGraphicsTextItem()

        self.video_view = VideoGraphicsView(self)
        self.video_view.setScene(self.scene)

        self.scene.addItem(self.video_item)
        self.scene.addItem(self.overlay_rect)
        self.scene.addItem(self.overlay_text)

        self.overlay_rect.setZValue(10)
        self.overlay_text.setZValue(11)
        self.overlay_rect.setPen(QPen(Qt.PenStyle.NoPen))
        self.overlay_text.setDefaultTextColor(QColor("white"))

        overlay_font = QFont()
        overlay_font.setPointSize(18)
        overlay_font.setBold(True)
        self.overlay_text.setFont(overlay_font)

        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_item)
        self.audio_output.setVolume(self.last_volume)

        self.build_ui()
        self.bind_player_events()
        self.bind_shortcuts()

        self.load_existing_csv()

        if self.input_folder:
            self.load_videos_from_folder(self.input_folder)

        self.refresh_ui()

    def build_ui(self) -> None:
        root = QWidget(self)
        root_layout = QVBoxLayout(root)

        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(self.content_splitter)

        self.main_splitter = QSplitter(Qt.Orientation.Vertical)
        self.content_splitter.addWidget(self.main_splitter)

        self.top_panel = QWidget(self)
        top_layout = QVBoxLayout(self.top_panel)

        top_layout.addWidget(self.video_view)

        self.position_slider = SeekSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.sliderPressed.connect(self.on_slider_pressed)
        self.position_slider.sliderReleased.connect(self.on_slider_released)
        self.position_slider.sliderMoved.connect(self.on_slider_moved)
        self.position_slider.seekRequested.connect(self.seek_absolute_milliseconds)
        top_layout.addWidget(self.position_slider)
        top_layout.addSpacing(12)

        self.segment_timeline = SegmentTimelineWidget(self)
        self.segment_timeline.segmentClicked.connect(self.select_segment_from_timeline)
        self.segment_timeline.emptyClicked.connect(self.prepare_new_segment_from_timeline)
        self.segment_timeline.dividerDragStarted.connect(self.begin_timeline_divider_drag)
        self.segment_timeline.dividerDragged.connect(self.drag_timeline_divider)
        self.segment_timeline.dividerDragFinished.connect(self.finish_timeline_divider_drag)
        top_layout.addWidget(self.segment_timeline)

        status_layout = QGridLayout()

        self.video_label = QLabel("Video: none")
        self.time_label = QLabel("Time: 00:00.000 / 00:00.000")
        self.phase_label = QLabel("Current phase: inside_plane")
        self.segment_start_label = QLabel("Segment start: 00:00.000")
        self.segment_duration_label = QLabel("Segment duration: 00:00.000")

        status_layout.addWidget(self.video_label, 0, 0, 1, 3)
        status_layout.addWidget(self.time_label, 1, 0)
        status_layout.addWidget(self.phase_label, 1, 1)
        status_layout.addWidget(self.segment_start_label, 2, 0)
        status_layout.addWidget(self.segment_duration_label, 2, 1)

        top_layout.addLayout(status_layout)

        self.bottom_panel = QWidget(self)
        bottom_layout = QVBoxLayout(self.bottom_panel)

        controls_layout = QHBoxLayout()

        self.open_folder_button = QPushButton("Open Folder")
        self.open_folder_button.clicked.connect(self.open_folder_dialog)

        self.previous_video_button = QPushButton("P Previous Video")
        self.previous_video_button.clicked.connect(self.previous_video)

        self.next_video_button = QPushButton("N Next Video")
        self.next_video_button.clicked.connect(self.next_video)

        self.play_button = QPushButton("Space Play/Pause")
        self.play_button.clicked.connect(self.toggle_play)

        self.mute_button = QPushButton("M Mute")
        self.mute_button.clicked.connect(self.toggle_mute)

        self.back_5_button = QPushButton(f"<< {int(SEEK_LARGE_SECONDS)}s")
        self.back_5_button.clicked.connect(lambda: self.seek_relative(-SEEK_LARGE_SECONDS))

        self.back_1_button = QPushButton(f"< {int(SEEK_SMALL_SECONDS)}s")
        self.back_1_button.clicked.connect(lambda: self.seek_relative(-SEEK_SMALL_SECONDS))

        self.forward_1_button = QPushButton(f"{int(SEEK_SMALL_SECONDS)}s >")
        self.forward_1_button.clicked.connect(lambda: self.seek_relative(SEEK_SMALL_SECONDS))

        self.forward_5_button = QPushButton(f"{int(SEEK_LARGE_SECONDS)}s >>")
        self.forward_5_button.clicked.connect(lambda: self.seek_relative(SEEK_LARGE_SECONDS))

        self.last_frame_button = QPushButton("End Last Frame")
        self.last_frame_button.clicked.connect(self.seek_last_frame)

        for button in [
            self.open_folder_button,
            self.previous_video_button,
            self.next_video_button,
            self.play_button,
            self.mute_button,
            self.back_5_button,
            self.back_1_button,
            self.forward_1_button,
            self.forward_5_button,
            self.last_frame_button,
        ]:
            controls_layout.addWidget(button)

        bottom_layout.addLayout(controls_layout)

        phase_layout = QGridLayout()
        self.phase_buttons: dict[str, QPushButton] = {}

        for index, (key, phase, label) in enumerate(PHASE_BUTTONS):
            button = QPushButton(f"{key} {label}")
            button.clicked.connect(lambda checked=False, p=phase: self.set_current_phase(p))
            self.phase_buttons[phase] = button
            phase_layout.addWidget(button, index // 4, index % 4)

        bottom_layout.addLayout(phase_layout)

        edit_layout = QHBoxLayout()

        self.finish_button = QPushButton("Enter Finish Current Phase + Advance")
        self.finish_button.clicked.connect(self.finish_current_phase_and_advance)

        self.skip_button = QPushButton("Tab Skip Current Phase")
        self.skip_button.clicked.connect(self.skip_current_phase)

        self.back_phase_button = QPushButton("B Back One Phase")
        self.back_phase_button.clicked.connect(self.back_one_phase)

        self.delete_selected_button = QPushButton("Delete Selected Segment")
        self.delete_selected_button.clicked.connect(self.delete_selected_segment)

        self.mark_boring_button = QPushButton("Mark Whole Video Empty/Boring")
        self.mark_boring_button.clicked.connect(self.mark_current_video_empty_or_boring)

        self.keep_checkbox = QCheckBox("K Keep")
        self.keep_checkbox.stateChanged.connect(self.on_keep_changed)

        self.phase_combo = QComboBox()
        self.phase_combo.addItems(ALL_PHASES)
        self.phase_combo.currentTextChanged.connect(self.set_current_phase)

        self.notes_input = QLineEdit()
        self.notes_input.setPlaceholderText("Notes for current segment")

        self.save_button = QPushButton("S Save CSV")
        self.save_button.clicked.connect(self.save_csv)

        for widget in [
            self.finish_button,
            self.skip_button,
            self.back_phase_button,
            self.delete_selected_button,
            self.mark_boring_button,
            self.keep_checkbox,
            self.phase_combo,
            self.notes_input,
            self.save_button,
        ]:
            edit_layout.addWidget(widget)

        bottom_layout.addLayout(edit_layout)

        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet(
            "color: #f5b700; font-weight: bold; padding: 3px 0;"
        )
        bottom_layout.addWidget(self.warning_label)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Video", "Start", "End", "Phase", "Keep", "Notes"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self.jump_to_segment_from_table)
        bottom_layout.addWidget(self.table)

        self.main_splitter.addWidget(self.top_panel)
        self.main_splitter.addWidget(self.bottom_panel)
        self.main_splitter.setStretchFactor(0, 3)
        self.main_splitter.setStretchFactor(1, 2)
        self.main_splitter.setSizes([560, 360])

        self.video_list_panel = QWidget(self)
        video_list_layout = QVBoxLayout(self.video_list_panel)
        self.video_list_title = QLabel("Videos")
        self.video_list_title.setStyleSheet("font-weight: bold;")
        self.video_progress_label = QLabel("Videos: 0/0 labeled")
        self.video_list = QListWidget()
        self.video_list.itemClicked.connect(self.open_video_from_list_item)
        self.video_list.itemActivated.connect(self.open_video_from_list_item)

        video_list_layout.addWidget(self.video_list_title)
        video_list_layout.addWidget(self.video_progress_label)
        video_list_layout.addWidget(self.video_list)

        self.content_splitter.addWidget(self.video_list_panel)
        self.content_splitter.setStretchFactor(0, 5)
        self.content_splitter.setStretchFactor(1, 1)
        self.content_splitter.setSizes([1180, 320])

        self.setCentralWidget(root)

        menu = self.menuBar()
        file_menu = menu.addMenu("File")

        open_folder_action = QAction("Open Folder", self)
        open_folder_action.triggered.connect(self.open_folder_dialog)
        file_menu.addAction(open_folder_action)

        save_action = QAction("Save CSV", self)
        save_action.triggered.connect(self.save_csv)
        file_menu.addAction(save_action)

    def bind_player_events(self) -> None:
        self.player.positionChanged.connect(self.on_position_changed)
        self.player.durationChanged.connect(self.on_duration_changed)
        self.player.errorOccurred.connect(self.on_player_error)

        self.ui_timer = QTimer(self)
        self.ui_timer.setInterval(500)
        self.ui_timer.timeout.connect(self.refresh_playhead_ui)
        self.ui_timer.start()

    def bind_shortcuts(self) -> None:
        shortcuts = [
            ("Space", self.toggle_play),
            ("Return", self.finish_current_phase_and_advance),
            ("Enter", self.finish_current_phase_and_advance),
            ("Tab", self.skip_current_phase),
            ("B", self.back_one_phase),
            ("Delete", self.delete_selected_segment),
            ("K", self.toggle_keep),
            ("M", self.toggle_mute),
            ("S", self.save_csv),
            ("N", self.next_video),
            ("P", self.previous_video),
            ("End", self.seek_last_frame),
            ("Left", lambda: self.seek_relative(-SEEK_SMALL_SECONDS)),
            ("Right", lambda: self.seek_relative(SEEK_SMALL_SECONDS)),
            ("Shift+Left", lambda: self.seek_relative(-SEEK_LARGE_SECONDS)),
            ("Shift+Right", lambda: self.seek_relative(SEEK_LARGE_SECONDS)),
        ]

        for key, callback in shortcuts:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(callback)

        for key, phase, _label in PHASE_BUTTONS:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(lambda p=phase: self.set_current_phase(p))

    def resize_video_scene(self) -> None:
        width = max(1, self.video_view.viewport().width())
        height = max(1, self.video_view.viewport().height())

        self.scene.setSceneRect(QRectF(0, 0, width, height))
        self.video_item.setPos(0, 0)
        self.video_item.setSize(QSizeF(width, height))

        self.update_overlay_graphics()

    def update_overlay_graphics(self) -> None:
        current = self.current_time_sec()
        segment_duration = max(0.0, current - self.current_segment_start_sec)

        display_phase = self.current_phase.replace("_", " ").upper()

        self.overlay_text.setPlainText(
            f"{display_phase}\n"
            f"Time: {seconds_to_label(current)}\n"
            f"Start: {seconds_to_label(self.current_segment_start_sec)}\n"
            f"Duration: {seconds_to_label(segment_duration)}"
        )

        self.overlay_text.setPos(22, 18)

        text_rect = self.overlay_text.boundingRect()
        rect = QRectF(
            12,
            12,
            text_rect.width() + 24,
            text_rect.height() + 18,
        )

        self.overlay_rect.setRect(rect)

        self.overlay_rect.setBrush(QBrush(phase_color(self.current_phase, 190)))

        self.overlay_rect.setVisible(True)
        self.overlay_text.setVisible(True)

    def load_videos_from_folder(self, folder: Path) -> None:
        folder = folder.resolve()
        self.input_folder = folder

        self.videos = sorted(
            path
            for path in folder.rglob("*")
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
        )

        if not self.videos:
            QMessageBox.warning(self, "No videos", f"No supported videos found in:\n{folder}")
            return

        self.video_index = 0
        self.refresh_video_list()
        self.load_current_video()

    def open_folder_dialog(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select video folder")

        if not folder:
            return

        self.load_videos_from_folder(Path(folder))

    def load_current_video(self) -> None:
        if not self.videos:
            return

        video = self.videos[self.video_index]
        self.player.setSource(QUrl.fromLocalFile(str(video)))

        self.current_phase_index = 0
        self.current_phase = PHASES[0]
        self.current_segment_start_sec = 0.0
        self.active_start_sec = None
        self.drag_boundary_refs = []
        self.active_segment_index = None
        self.finish_at_video_end = False
        self.notes_input.clear()
        self.keep_checkbox.setChecked(DEFAULT_KEEP[self.current_phase])
        self.phase_combo.setCurrentText(self.current_phase)

        self.refresh_table()
        self.refresh_ui()

    def current_video_path(self) -> Path | None:
        if not self.videos:
            return None

        if self.video_index < 0 or self.video_index >= len(self.videos):
            return None

        return self.videos[self.video_index]

    def current_time_sec(self) -> float:
        return milliseconds_to_seconds(self.player.position())

    def duration_sec(self) -> float:
        return milliseconds_to_seconds(self.player.duration())

    def segment_matches_current_video(self, segment: Segment) -> bool:
        current_video = self.current_video_path()
        if current_video is None:
            return False

        return self.segment_matches_video(segment, current_video)

    def segment_matches_video(self, segment: Segment, video: Path) -> bool:
        return segment_source_key(segment.source_video) == segment_source_key(str(video))

    def video_segment_indexes(self, video: Path) -> list[int]:
        return [
            index
            for index, segment in enumerate(self.segments)
            if self.segment_matches_video(segment, video)
        ]

    def video_segment_count(self, video: Path) -> int:
        return len(self.video_segment_indexes(video))

    def current_video_segment_indexes(self) -> list[int]:
        return [
            index
            for index, segment in enumerate(self.segments)
            if self.segment_matches_current_video(segment)
        ]

    def sorted_current_video_segment_indexes(self) -> list[int]:
        return sorted(
            self.current_video_segment_indexes(),
            key=lambda index: (self.segments[index].start_sec, self.segments[index].end_sec),
        )

    def table_segment_index(self, row: int) -> int | None:
        if row < 0 or row >= len(self.table_segment_indexes):
            return None
        return self.table_segment_indexes[row]

    def duplicate_phase_warning_text(self) -> str:
        issues = self.current_video_issues()
        if not issues:
            return ""

        error_count = sum(1 for issue in issues if issue.level == "error")
        warning_count = len(issues) - error_count
        parts: list[str] = []

        if error_count:
            parts.append(f"ERROR: {error_count} timeline problem(s)")
        if warning_count:
            parts.append(f"WARNING: {warning_count} timeline warning(s)")

        shown = "; ".join(issue.message for issue in issues[:3])
        if len(issues) > 3:
            shown += f"; +{len(issues) - 3} more"

        return f"{' / '.join(parts)}. {shown}. Needs fixing."

    def refresh_duplicate_warning(self) -> None:
        warning = self.duplicate_phase_warning_text()
        self.warning_label.setText(warning)
        self.warning_label.setVisible(bool(warning))

    def video_has_duplicate_phase_sections(self, video: Path) -> bool:
        return any(issue.code == "duplicate_phase" for issue in self.video_issues(video))

    def current_video_issues(self) -> list[TimelineIssue]:
        current_video = self.current_video_path()
        if current_video is None:
            return []
        return self.video_issues(current_video)

    def video_issues(self, video: Path) -> list[TimelineIssue]:
        return validate_segment_indexes(self.segments, self.video_segment_indexes(video))

    def video_issue_level(self, video: Path) -> str:
        issues = self.video_issues(video)
        if any(issue.level == "error" for issue in issues):
            return "error"
        if issues:
            return "warning"
        return "ok"

    def issue_messages_by_segment_index(self) -> dict[int, list[str]]:
        messages: dict[int, list[str]] = {}
        for issue in self.current_video_issues():
            for index in issue.segment_indexes:
                messages.setdefault(index, []).append(f"{issue.level.upper()}: {issue.message}")
        return messages

    def refresh_video_list(self) -> None:
        if not hasattr(self, "video_list"):
            return

        segment_counts: dict[str, int] = {}
        for segment in self.segments:
            source_key = segment_source_key(segment.source_video)
            segment_counts[source_key] = segment_counts.get(source_key, 0) + 1

        issues_by_source = validate_segments_by_source(self.segments)
        total = len(self.videos)
        video_source_keys = [segment_source_key(str(video)) for video in self.videos]
        labeled = sum(1 for source_key in video_source_keys if segment_counts.get(source_key, 0) > 0)
        self.video_progress_label.setText(f"Videos: {labeled}/{total} labeled")

        self.refreshing_video_list = True
        try:
            self.video_list.clear()

            for index, (video, source_key) in enumerate(zip(self.videos, video_source_keys)):
                segment_count = segment_counts.get(source_key, 0)
                issues = issues_by_source.get(source_key, [])
                if any(issue.level == "error" for issue in issues):
                    issue_level = "error"
                elif issues:
                    issue_level = "warning"
                else:
                    issue_level = "ok"
                if issue_level == "error":
                    status = "ERROR"
                elif issue_level == "warning":
                    status = "WARN"
                else:
                    status = "DONE" if segment_count else "TODO"
                marker = ">" if index == self.video_index else " "
                detail = f"{status} - {segment_count} segment(s)"
                item = QListWidgetItem(f"{marker} {index + 1:02d}. {video.name}\n   {detail}")
                item.setData(Qt.ItemDataRole.UserRole, index)

                if index == self.video_index:
                    item.setBackground(QBrush(QColor("#264653")))
                    item.setForeground(QBrush(QColor("white")))
                elif issue_level == "error":
                    item.setForeground(QBrush(QColor("#b00020")))
                elif issue_level == "warning":
                    item.setForeground(QBrush(QColor("#9a6700")))
                elif segment_count:
                    item.setForeground(QBrush(QColor("#1f7a3f")))
                else:
                    item.setForeground(QBrush(QColor("#777777")))

                self.video_list.addItem(item)

            if 0 <= self.video_index < self.video_list.count():
                self.video_list.setCurrentRow(self.video_index)
        finally:
            self.refreshing_video_list = False

    def open_video_from_list_item(self, item: QListWidgetItem) -> None:
        if self.refreshing_video_list:
            return

        video_index = item.data(Qt.ItemDataRole.UserRole)
        if video_index is None:
            return

        video_index = int(video_index)
        if video_index < 0 or video_index >= len(self.videos):
            return

        if video_index == self.video_index:
            return

        self.video_index = video_index
        self.load_current_video()

    def segment_index_at_time(self, time_sec: float) -> int | None:
        for index in self.sorted_current_video_segment_indexes():
            segment = self.segments[index]
            if segment.start_sec <= time_sec < segment.end_sec:
                return index

        indexes = self.sorted_current_video_segment_indexes()
        if indexes:
            last_index = indexes[-1]
            last_segment = self.segments[last_index]
            if abs(time_sec - last_segment.end_sec) <= 0.001:
                return last_index

        return None

    def set_editor_state_from_segment(self, segment_index: int) -> None:
        if segment_index < 0 or segment_index >= len(self.segments):
            return

        segment = self.segments[segment_index]
        self.active_segment_index = segment_index
        self.active_start_sec = None
        self.current_segment_start_sec = segment.start_sec

        self.syncing_from_timeline = True
        try:
            self.set_current_phase(segment.phase)
            self.keep_checkbox.blockSignals(True)
            self.keep_checkbox.setChecked(segment.keep)
            self.keep_checkbox.blockSignals(False)
            self.notes_input.setText(segment.notes)
        finally:
            self.syncing_from_timeline = False

    def sync_editor_state_after_seek(self, time_sec: float) -> None:
        segment_index = self.segment_index_at_time(time_sec)
        if segment_index is not None:
            self.set_editor_state_from_segment(segment_index)
            return

        self.active_segment_index = None

        if time_sec < self.current_segment_start_sec:
            self.current_segment_start_sec = round(max(0.0, time_sec), 3)
            self.active_start_sec = self.current_segment_start_sec
            self.notes_input.clear()

    def infer_next_phase_after(self, time_sec: float) -> str:
        return infer_next_phase_after(
            self.segments,
            self.sorted_current_video_segment_indexes(),
            time_sec,
        )

    def previous_segment_end_at_or_before(self, end_sec: float) -> float:
        return previous_segment_end_at_or_before(
            self.segments,
            self.sorted_current_video_segment_indexes(),
            end_sec,
        )

    def select_segment_from_timeline(self, segment_index: int, position_ms: int) -> None:
        if segment_index < 0 or segment_index >= len(self.segments):
            return

        segment = self.segments[segment_index]
        if not self.segment_matches_current_video(segment):
            return

        self.set_editor_state_from_segment(segment_index)
        self.refresh_ui()

    def prepare_new_segment_from_timeline(self, position_ms: int) -> None:
        current_video = self.current_video_path()
        if current_video is None:
            return

        duration = seconds_to_milliseconds(self.duration_sec())
        if duration > 0:
            position_ms = max(0, min(int(position_ms), duration))
        else:
            position_ms = max(0, int(position_ms))

        time_sec = round(milliseconds_to_seconds(position_ms), 3)
        phase = self.infer_next_phase_after(time_sec)

        self.active_segment_index = None
        self.active_start_sec = time_sec
        self.current_segment_start_sec = time_sec
        self.finish_at_video_end = False
        self.notes_input.clear()
        self.set_current_phase(phase)
        self.refresh_ui()

    def timeline_ranges_for_current_video(self) -> list[tuple[float, float, str, int]]:
        ranges: list[tuple[float, float, str, int]] = []

        for index, segment in enumerate(self.segments):
            if not self.segment_matches_current_video(segment):
                continue
            ranges.append((segment.start_sec, segment.end_sec, segment.phase, index))

        return sorted(ranges, key=lambda item: (item[0], item[1]))

    def refresh_segment_timeline(self) -> None:
        selected_segment_index = None
        if (
            self.active_segment_index is not None
            and 0 <= self.active_segment_index < len(self.segments)
            and self.segment_matches_current_video(self.segments[self.active_segment_index])
        ):
            selected_segment_index = self.active_segment_index

        self.segment_timeline.set_timeline_ranges(
            self.timeline_ranges_for_current_video(),
            seconds_to_milliseconds(self.duration_sec()),
            selected_segment_index,
            self.player.position(),
        )

    def refresh_playhead_ui(self) -> None:
        current = self.current_time_sec()
        duration = self.duration_sec()
        segment_duration = max(0.0, current - self.current_segment_start_sec)

        self.time_label.setText(f"Time: {seconds_to_label(current)} / {seconds_to_label(duration)}")
        self.segment_start_label.setText(f"Segment start: {seconds_to_label(self.current_segment_start_sec)}")
        self.segment_duration_label.setText(f"Segment duration: {seconds_to_label(segment_duration)}")
        self.update_overlay_graphics()

    def refresh_ui(self) -> None:
        video = self.current_video_path()

        if video:
            self.video_label.setText(f"Video {self.video_index + 1}/{len(self.videos)}: {video.name}")
        else:
            self.video_label.setText("Video: none")

        self.refresh_playhead_ui()
        self.phase_label.setText(f"Current phase: {self.current_phase}")
        phase_label_color = PHASE_COLORS.get(self.current_phase, PHASE_COLORS["unknown"])
        self.phase_label.setStyleSheet(f"font-weight: bold; color: {phase_label_color};")
        self.refresh_segment_timeline()

        for phase, button in self.phase_buttons.items():
            color = PHASE_COLORS.get(phase, PHASE_COLORS["unknown"])
            text_color = contrasting_text_color(phase_color(phase))
            if phase == self.current_phase:
                button.setStyleSheet(
                    f"font-weight: bold; border: 2px solid white; background-color: {color}; color: {text_color};"
                )
            else:
                button.setStyleSheet(f"background-color: {color}; color: {text_color};")

        next_phase = self.next_phase_name()
        if self.current_phase == PHASES[-1]:
            self.finish_button.setText(f"Enter Finish {self.current_phase} at video end")
        else:
            self.finish_button.setText(f"Enter Finish {self.current_phase} + Advance to {next_phase}")

    def next_phase_name(self) -> str:
        if self.current_phase in PHASES:
            index = PHASES.index(self.current_phase)
            if index + 1 < len(PHASES):
                return PHASES[index + 1]
        return "end"

    def set_current_phase(self, phase: str) -> None:
        if phase not in ALL_PHASES:
            return

        self.current_phase = phase

        if phase in PHASES:
            self.current_phase_index = PHASES.index(phase)

        self.keep_checkbox.blockSignals(True)
        self.keep_checkbox.setChecked(DEFAULT_KEEP.get(phase, False))
        self.keep_checkbox.blockSignals(False)

        self.phase_combo.blockSignals(True)
        self.phase_combo.setCurrentText(phase)
        self.phase_combo.blockSignals(False)

        if (
            not self.syncing_from_timeline
            and self.active_segment_index is not None
            and 0 <= self.active_segment_index < len(self.segments)
            and self.segment_matches_current_video(self.segments[self.active_segment_index])
        ):
            segment = self.segments[self.active_segment_index]
            segment.phase = phase
            segment.keep = DEFAULT_KEEP.get(phase, segment.keep)
            self.keep_checkbox.blockSignals(True)
            self.keep_checkbox.setChecked(segment.keep)
            self.keep_checkbox.blockSignals(False)
            self.refresh_table()
            self.save_csv_silent()

        self.refresh_ui()

    def on_keep_changed(self) -> None:
        if (
            self.active_segment_index is not None
            and 0 <= self.active_segment_index < len(self.segments)
            and self.segment_matches_current_video(self.segments[self.active_segment_index])
        ):
            segment = self.segments[self.active_segment_index]
            segment.keep = self.keep_checkbox.isChecked()
            self.refresh_table()
            self.save_csv_silent()

        self.refresh_ui()

    def toggle_keep(self) -> None:
        self.keep_checkbox.setChecked(not self.keep_checkbox.isChecked())

    def toggle_mute(self) -> None:
        self.is_muted = not self.is_muted
        self.audio_output.setMuted(self.is_muted)

        if self.is_muted:
            self.mute_button.setText("M Unmute")
        else:
            self.mute_button.setText("M Mute")

    def finish_current_phase_and_advance(self) -> None:
        video = self.current_video_path()

        if video is None:
            return

        end_sec = self.current_time_sec()
        duration = self.duration_sec()
        finish_last_phase = self.current_phase == PHASES[-1]
        if finish_last_phase and duration <= 0:
            self.statusBar().showMessage("Wait for the video duration before finishing the last phase.", 5000)
            return
        if self.active_start_sec is None:
            start_sec = self.previous_segment_end_at_or_before(end_sec)
        else:
            start_sec = self.active_start_sec
        end_sec = effective_finish_end_seconds(
            end_sec, duration, self.finish_at_video_end or finish_last_phase
        )
        if duration > 0:
            end_sec = min(end_sec, duration)
        self.current_segment_start_sec = round(start_sec, 3)

        if end_sec <= start_sec:
            self.statusBar().showMessage(
                "Segment was not saved because the end time is not after the start time.",
                5000,
            )
            self.refresh_ui()
            return

        segment = Segment(
            source_video=str(video),
            start_sec=round(start_sec, 3),
            end_sec=round(end_sec, 3),
            phase=self.current_phase,
            keep=self.keep_checkbox.isChecked(),
            notes=self.notes_input.text().strip(),
        )

        try:
            self.segments = replace_overlapping_segments(self.segments, segment)
        except ValueError:
            self.statusBar().showMessage(
                "Segment was not saved because the end time is not after the start time.",
                5000,
            )
            self.refresh_ui()
            return

        self.current_segment_start_sec = end_sec
        reached_end = duration > 0 and end_sec >= duration
        self.active_start_sec = None if reached_end else end_sec
        self.active_segment_index = None
        self.finish_at_video_end = False
        self.notes_input.clear()

        if not reached_end:
            self.advance_phase()
        self.refresh_table()
        self.refresh_ui()
        self.save_csv_silent()

    def advance_phase(self) -> None:
        if self.current_phase in PHASES:
            index = PHASES.index(self.current_phase)
            if index + 1 < len(PHASES):
                self.set_current_phase(PHASES[index + 1])
                return

        self.set_current_phase(self.current_phase)

    def skip_current_phase(self) -> None:
        self.advance_phase()
        self.refresh_ui()

    def back_one_phase(self) -> None:
        if self.current_phase in PHASES:
            index = PHASES.index(self.current_phase)
            if index > 0:
                self.set_current_phase(PHASES[index - 1])
                return

        if self.current_phase in EXTRA_PHASES:
            self.set_current_phase(PHASES[-1])
            return

        self.refresh_ui()

    def delete_selected_segment(self) -> None:
        selected_rows: list[int] = []
        if hasattr(self, "table"):
            selected_rows = sorted(
                {index.row() for index in self.table.selectionModel().selectedRows()},
                reverse=True,
            )

        selected_segment_indexes = sorted(
            {
                segment_index
                for row in selected_rows
                if (segment_index := self.table_segment_index(row)) is not None
            },
            reverse=True,
        )
        deleting_from_table = bool(selected_segment_indexes)

        if (
            not selected_segment_indexes
            and self.active_segment_index is not None
            and 0 <= self.active_segment_index < len(self.segments)
            and self.segment_matches_current_video(self.segments[self.active_segment_index])
        ):
            selected_segment_indexes = [self.active_segment_index]

        if not selected_segment_indexes:
            QMessageBox.information(
                self,
                "No segment selected",
                "Select a segment in the phase bar or current-video table first.",
            )
            return

        deleted_segments: list[Segment] = []

        for segment_index in selected_segment_indexes:
            if 0 <= segment_index < len(self.segments):
                deleted_segments.append(self.segments.pop(segment_index))

        if deleted_segments:
            last_deleted = sorted(deleted_segments, key=lambda segment: segment.start_sec)[0]
            self.active_segment_index = None
            self.active_start_sec = last_deleted.start_sec
            self.finish_at_video_end = False
            video_path = Path(last_deleted.source_video)

            for index, candidate in enumerate(self.videos):
                if candidate.resolve() == video_path.resolve():
                    if self.video_index != index:
                        self.video_index = index
                        self.load_current_video()
                    break

            self.current_segment_start_sec = last_deleted.start_sec
            self.active_start_sec = last_deleted.start_sec
            self.set_current_phase(last_deleted.phase)
            self.keep_checkbox.setChecked(last_deleted.keep)
            self.notes_input.setText(last_deleted.notes)
            if deleting_from_table:
                self.player.setPosition(seconds_to_milliseconds(last_deleted.start_sec))

        self.refresh_table()
        self.refresh_ui()
        self.save_csv_silent()

    def mark_current_video_empty_or_boring(self) -> None:
        video = self.current_video_path()
        duration = self.duration_sec()

        if video is None:
            return

        if duration <= 0:
            QMessageBox.warning(self, "Duration unavailable", "Wait for the video duration to load first.")
            return

        existing_count = len(self.current_video_segment_indexes())
        if existing_count:
            answer = QMessageBox.question(
                self,
                "Replace current labels?",
                f"This will replace {existing_count} existing segment(s) for this video with one empty/boring segment.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self.segments = [
            segment
            for segment in self.segments
            if not self.segment_matches_current_video(segment)
        ]
        self.segments.append(
            Segment(
                source_video=str(video),
                start_sec=0.0,
                end_sec=round(duration, 3),
                phase="empty_or_boring",
                keep=False,
                notes="whole video not relevant",
            )
        )

        self.current_segment_start_sec = 0.0
        self.active_start_sec = None
        self.active_segment_index = None
        self.finish_at_video_end = False
        self.set_current_phase(PHASES[0])
        self.keep_checkbox.setChecked(DEFAULT_KEEP[self.current_phase])
        self.notes_input.clear()
        self.player.setPosition(0)
        self.refresh_table()
        self.refresh_ui()
        self.save_csv_silent()

    def previous_video(self) -> None:
        if not self.videos:
            return

        if self.video_index <= 0:
            return

        self.video_index -= 1
        self.load_current_video()

    def next_video(self) -> None:
        if not self.videos:
            return

        if self.video_index + 1 >= len(self.videos):
            return

        self.video_index += 1
        self.load_current_video()

    def toggle_play(self) -> None:
        self.finish_at_video_end = False
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def seek_relative(self, seconds: float) -> None:
        current_position = self.player.position()
        offset = int(round(float(seconds) * 1000.0))
        self.seek_absolute_milliseconds(current_position + offset)

    def seek_last_frame(self) -> None:
        duration = seconds_to_milliseconds(self.duration_sec())
        if duration <= 0:
            return

        self.player.pause()
        self.seek_absolute_milliseconds(
            last_frame_preview_milliseconds(duration),
            preview_frame=False,
            preserve_video_end_marker=True,
        )
        self.finish_at_video_end = True
        self.statusBar().showMessage("End marker set to the true end of the video.", 3000)

    def seek_absolute_milliseconds(
        self,
        position: int,
        preview_frame: bool = True,
        preserve_video_end_marker: bool = False,
    ) -> None:
        duration = seconds_to_milliseconds(self.duration_sec())

        if duration <= 0:
            return

        if not preserve_video_end_marker:
            self.finish_at_video_end = False

        new_position = max(0, min(int(position), duration))
        was_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

        self.ignore_slider_updates = True
        self.player.setPosition(new_position)
        self.position_slider.setValue(new_position)
        self.ignore_slider_updates = False
        self.refresh_ui()

        if preview_frame and not was_playing:
            self.preview_paused_frame()

    def preview_paused_frame(self) -> None:
        self.player.play()
        QTimer.singleShot(80, self.player.pause)

    def begin_timeline_divider_drag(self, boundary_ms: int) -> None:
        self.active_segment_index = None
        boundary_sec = milliseconds_to_seconds(boundary_ms)
        tolerance = 0.08
        refs: list[tuple[int, str]] = []

        for index in self.sorted_current_video_segment_indexes():
            segment = self.segments[index]
            if abs(segment.start_sec - boundary_sec) <= tolerance:
                refs.append((index, "start"))
            if abs(segment.end_sec - boundary_sec) <= tolerance:
                refs.append((index, "end"))

        self.drag_boundary_refs = refs
        self.drag_boundary_changed = False

    def drag_timeline_divider(self, position_ms: int) -> None:
        self.apply_timeline_divider_drag(position_ms, save=False)

    def finish_timeline_divider_drag(self, position_ms: int) -> None:
        self.apply_timeline_divider_drag(position_ms, save=True)
        self.drag_boundary_refs = []
        self.drag_boundary_changed = False

    def apply_timeline_divider_drag(self, position_ms: int, save: bool) -> None:
        if not self.drag_boundary_refs:
            return

        duration = self.duration_sec()
        if duration <= 0:
            return

        refs = set(self.drag_boundary_refs)
        ordered_indexes = self.sorted_current_video_segment_indexes()
        ordered_position = {segment_index: index for index, segment_index in enumerate(ordered_indexes)}

        min_sec = 0.0
        max_sec = duration

        for segment_index, edge in refs:
            segment = self.segments[segment_index]
            ordered_index = ordered_position.get(segment_index)

            if edge == "start":
                max_sec = min(max_sec, segment.end_sec - MIN_DRAGGED_SEGMENT_SECONDS)
                if ordered_index is not None and ordered_index > 0:
                    previous_index = ordered_indexes[ordered_index - 1]
                    previous = self.segments[previous_index]
                    if (previous_index, "end") in refs:
                        min_sec = max(min_sec, previous.start_sec + MIN_DRAGGED_SEGMENT_SECONDS)
                    else:
                        min_sec = max(min_sec, previous.end_sec)
            else:
                min_sec = max(min_sec, segment.start_sec + MIN_DRAGGED_SEGMENT_SECONDS)
                if ordered_index is not None and ordered_index + 1 < len(ordered_indexes):
                    next_index = ordered_indexes[ordered_index + 1]
                    next_segment = self.segments[next_index]
                    if (next_index, "start") in refs:
                        max_sec = min(max_sec, next_segment.end_sec - MIN_DRAGGED_SEGMENT_SECONDS)
                    else:
                        max_sec = min(max_sec, next_segment.start_sec)

        snap_candidates = boundary_snap_candidates(
            self.segments,
            ordered_indexes,
            refs,
            self.current_time_sec(),
            duration,
        )
        new_sec = snap_seconds(
            milliseconds_to_seconds(position_ms),
            snap_candidates,
            SNAP_THRESHOLD_SECONDS,
        )
        new_sec = round(max(min_sec, min(new_sec, max_sec)), 3)

        changed = False
        for segment_index, edge in refs:
            segment = self.segments[segment_index]
            current_sec = segment.start_sec if edge == "start" else segment.end_sec
            if abs(current_sec - new_sec) > TIMELINE_EPSILON_SECONDS:
                changed = True
                break

        if not changed:
            if save and self.drag_boundary_changed:
                self.refresh_table()
                self.refresh_ui()
                self.save_csv_silent()
            return

        for segment_index, edge in refs:
            segment = self.segments[segment_index]
            if edge == "start":
                segment.start_sec = new_sec
            else:
                segment.end_sec = new_sec

        self.active_segment_index = None
        self.drag_boundary_changed = True

        if save:
            self.refresh_table()
            self.refresh_ui()
            self.save_csv_silent()
        else:
            self.refresh_segment_timeline()

    def on_position_changed(self, position: int) -> None:
        if not self.ignore_slider_updates:
            self.position_slider.setValue(position)
        self.segment_timeline.set_playhead_milliseconds(position, seconds_to_milliseconds(self.duration_sec()))
        self.refresh_playhead_ui()

    def on_duration_changed(self, duration: int) -> None:
        self.position_slider.setRange(0, seconds_to_milliseconds(self.duration_sec()))
        self.resize_video_scene()
        self.refresh_ui()

    def on_slider_pressed(self) -> None:
        self.ignore_slider_updates = True

    def on_slider_moved(self, position: int) -> None:
        self.time_label.setText(
            f"Time: {seconds_to_label(milliseconds_to_seconds(position))} / {seconds_to_label(self.duration_sec())}"
        )

    def on_slider_released(self) -> None:
        self.ignore_slider_updates = False
        self.seek_absolute_milliseconds(self.position_slider.value())

    def on_player_error(self) -> None:
        error = self.player.errorString()

        if error:
            QMessageBox.warning(self, "Video playback error", error)

    def refresh_table(self) -> None:
        self.table_segment_indexes = self.sorted_current_video_segment_indexes()
        self.table.setRowCount(len(self.table_segment_indexes))
        issue_messages = self.issue_messages_by_segment_index()

        for row_index, segment_index in enumerate(self.table_segment_indexes):
            segment = self.segments[segment_index]
            video_name = Path(segment.source_video).name
            values = [
                video_name,
                seconds_to_label(segment.start_sec),
                seconds_to_label(segment.end_sec),
                segment.phase,
                str(segment.keep).lower(),
                segment.notes,
            ]

            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                segment_issue_messages = issue_messages.get(segment_index, [])
                has_error = any(message.startswith("ERROR:") for message in segment_issue_messages)

                row_color = phase_color(segment.phase, 35)
                item.setBackground(QBrush(row_color))
                if has_error:
                    item.setBackground(QBrush(QColor(176, 0, 32, 70)))
                elif segment_issue_messages:
                    item.setBackground(QBrush(QColor(245, 183, 0, 70)))

                if column_index == 3:
                    solid_color = phase_color(segment.phase)
                    item.setBackground(QBrush(solid_color))
                    item.setForeground(QBrush(QColor(contrasting_text_color(solid_color))))
                    font = QFont()
                    font.setBold(True)
                    item.setFont(font)

                if segment_issue_messages:
                    item.setToolTip("\n".join(segment_issue_messages))

                self.table.setItem(row_index, column_index, item)

        if self.table_segment_indexes:
            self.table.scrollToBottom()

        self.refresh_duplicate_warning()
        self.refresh_video_list()
        self.refresh_segment_timeline()

    def jump_to_segment_from_table(self, row: int, _column: int) -> None:
        segment_index = self.table_segment_index(row)
        if segment_index is None:
            return

        segment = self.segments[segment_index]
        video_path = Path(segment.source_video)

        for index, candidate in enumerate(self.videos):
            if candidate.resolve() == video_path.resolve():
                self.video_index = index
                self.load_current_video()
                break

        self.active_segment_index = segment_index
        self.seek_absolute_milliseconds(seconds_to_milliseconds(segment.start_sec))
        self.set_editor_state_from_segment(segment_index)
        self.refresh_ui()

    def save_csv_silent(self) -> None:
        try:
            self.write_csv()
        except Exception:
            pass

    def save_csv(self) -> None:
        try:
            self.write_csv()
            QMessageBox.information(self, "Saved", f"Saved:\n{self.csv_path}")
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))

    def write_csv(self) -> None:
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)

        with self.csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "source_video",
                    "start_sec",
                    "end_sec",
                    "phase",
                    "keep",
                    "notes",
                ],
            )
            writer.writeheader()

            for segment in self.segments:
                row = asdict(segment)
                row["start_sec"] = f"{segment.start_sec:.3f}"
                row["end_sec"] = f"{segment.end_sec:.3f}"
                row["keep"] = str(segment.keep).lower()
                writer.writerow(row)

    def load_existing_csv(self) -> None:
        if not self.csv_path.exists():
            return

        with self.csv_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                try:
                    phase = row["phase"]
                    if phase == "walking_back":
                        phase = "landed"

                    self.segments.append(
                        Segment(
                            source_video=row["source_video"],
                            start_sec=float(row["start_sec"]),
                            end_sec=float(row["end_sec"]),
                            phase=phase,
                            keep=str(row["keep"]).strip().lower() in {"true", "1", "yes", "y"},
                            notes=row.get("notes", ""),
                        )
                    )
                except Exception:
                    continue

        self.refresh_table()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manual skydiving video phase labeler.")
    parser.add_argument(
        "--input-folder",
        default="",
        help="Folder containing videos.",
    )
    parser.add_argument(
        "--csv",
        required=True,
        help="Path to output/input segment CSV.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    input_folder = Path(args.input_folder) if args.input_folder else None
    csv_path = Path(args.csv)

    app = QApplication(sys.argv)
    window = ManualVideoLabeler(input_folder=input_folder, csv_path=csv_path)
    window.resize(1500, 950)
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
