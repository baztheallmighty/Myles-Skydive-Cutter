# FROZEN: inherited research code for the review window it sits in. It ships and runs, but is not maintained in place:
# fix behaviour in cutter_v4/review_ui.py or app/ui/review_tab.py, or replace this file wholesale.
"""Existing manual labeler with separate V3 comparison tracks and review accounting."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from functools import lru_cache
import json
import math
from pathlib import Path
import sys

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter
from PySide6.QtWidgets import QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QWidget

import _labeler as labeler
from review_exclusions import exclude_video, read_mapping, restore_video
from common import (PHASES, RunLock, annotation_fingerprint, key as uncached_key, read_csv,
                    validate_review, write_csv, write_json)


@lru_cache(maxsize=8192)
def _source_key(source):
    # Corpus paths stay fixed during a review session. Resolving them repeatedly on
    # Windows turns a queue refresh into hundreds of thousands of filesystem calls.
    return uncached_key(source)


def key(source):
    return _source_key(str(source))

labeler.PHASES = PHASES
labeler.ALL_PHASES = PHASES + labeler.EXTRA_PHASES
labeler.PHASE_BUTTONS = [(str(i + 1), phase, phase.replace('_', ' ').title()) for i, phase in enumerate(PHASES)]


class ComparisonTracks(QWidget):
    seek = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result = None
        self.position = 0.
        self.expanded = False
        self.setFixedHeight(58)
        self.setMouseTracking(True)
        self.setToolTip('Read-only model tracks. Click to seek. Edit your labels in the main timeline/table below.')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#181e28'))
        labels = [('video', 'V3 video'), ('audio', 'Audio')]
        if self.expanded:
            labels += [('baseline', 'V3 baseline'), ('blend', 'Blend (trial)')]
        width = max(1, self.width() - 125)
        for row, (name, title) in enumerate(labels):
            y = row * 26 + 3
            painter.setPen(QColor('#edf1f7'))
            painter.drawText(5, y + 16, title)
            if self.result:
                duration = self.result['duration_sec']
                segments = self.result['tracks'].get(name, [])
                if not segments:
                    painter.drawText(128, y + 16, 'Unavailable - video fallback')
                for segment in segments:
                    x = 122 + segment['start_sec'] / duration * width
                    span = (segment['end_sec'] - segment['start_sec']) / duration * width
                    painter.fillRect(QRectF(x, y, max(1, span), 23), QColor(labeler.PHASE_COLORS[segment['phase']]))
                    if span > 82:
                        painter.setPen(QColor('#ffffff'))
                        painter.drawText(QRectF(x + 3, y, span - 5, 23), Qt.AlignmentFlag.AlignVCenter,
                                         segment['phase'].replace('_', ' '))
                painter.setPen(QColor('#ffffff'))
                x = 122 + min(duration, self.position) / duration * width
                painter.drawLine(int(x), y, int(x), y + 23)
        painter.end()

    def set_expanded(self, enabled):
        self.expanded = enabled
        self.setFixedHeight(110 if enabled else 58)
        self.update()

    def mousePressEvent(self, event):
        if self.result and event.position().x() >= 122:
            fraction = max(0., min(1., (event.position().x() - 122) / max(1, self.width() - 125)))
            self.seek.emit(fraction * self.result['duration_sec'])

    def mouseMoveEvent(self, event):
        if not self.result or event.position().x() < 122:
            return
        names = ['video', 'audio'] + (['baseline', 'blend'] if self.expanded else [])
        row = min(len(names) - 1, max(0, int(event.position().y()) // 26))
        seconds = (event.position().x() - 122) / max(1, self.width() - 125) * self.result['duration_sec']
        segment = next((s for s in self.result['tracks'][names[row]] if s['start_sec'] <= seconds < s['end_sec']), None)
        if segment:
            self.setToolTip(f"{names[row]}: {segment['phase'].replace('_', ' ')} | "
                            f"{segment['start_sec']:.2f}-{segment['end_sec']:.2f}s. Click to seek.")
        else:
            self.setToolTip(f'{names[row]}: unavailable at {seconds:.2f}s. Click to seek.')


class ReviewWindow(labeler.ManualVideoLabeler):
    def __init__(self, run_directory):
        self.run_directory = Path(run_directory).resolve()
        status = json.loads((self.run_directory / 'status.json').read_text())
        self.records = [r for r in status['records'] if r['status'] == 'success']
        if not self.records:
            raise ValueError('This run has no successfully processed videos to review. See SUMMARY.md.')
        self.results = {key(r['source_video']): json.loads((self.run_directory / r['result']).read_text()) for r in self.records}
        self.review_state_path = self.run_directory / 'review_state.json'
        self.review_state = json.loads(self.review_state_path.read_text()) if self.review_state_path.exists() else {}
        self.exclusions_path = self.run_directory / 'review_exclusions.json'
        self.exclusions = read_mapping(self.exclusions_path)
        read_csv(self.run_directory / 'review.csv')  # Validate before the base labeler's forgiving loader.
        super().__init__(None, self.run_directory / 'review.csv')
        self.setWindowTitle('V3 POC - compare predictions and review labels')
        self.resize(1550, 1000)
        self.open_folder_button.setEnabled(False)
        self.open_folder_button.setToolTip('This review is scoped to the videos processed in this run.')
        self.review_banner = QLabel()
        self.review_banner.setWordWrap(True)
        self.top_panel.layout().addWidget(self.review_banner)
        self.comparison = ComparisonTracks(self)
        self.comparison.seek.connect(lambda seconds: self.seek_absolute_milliseconds(round(seconds * 1000)))
        self.top_panel.layout().addWidget(self.comparison)
        self.extra_tracks = QCheckBox('Show baseline video and experimental blend comparisons')
        self.extra_tracks.toggled.connect(self.comparison.set_expanded)
        self.top_panel.layout().addWidget(self.extra_tracks)
        self.review_button = QPushButton('Mark this video reviewed and next')
        self.review_button.clicked.connect(self.mark_reviewed)
        self.exclude_button = QPushButton('Not skydiving')
        self.exclude_button.setToolTip('Exclude this video from review and evaluation, then move to the next video. The file and labels are kept.')
        self.exclude_button.clicked.connect(self.toggle_exclusion)
        review_actions = QWidget()
        review_actions_layout = QHBoxLayout(review_actions)
        review_actions_layout.setContentsMargins(0, 0, 0, 0)
        review_actions_layout.addWidget(self.review_button)
        review_actions_layout.addWidget(self.exclude_button)
        self.bottom_panel.layout().insertWidget(0, review_actions)
        self.evaluate_button = QPushButton('Compare models against reviewed videos')
        self.evaluate_button.clicked.connect(self.evaluate_reviewed)
        self.bottom_panel.layout().insertWidget(1, self.evaluate_button)
        self.player.positionChanged.connect(self.update_comparison_position)
        self.videos = [Path(r['source_video']) for r in self.records]
        self.video_index = next((i for i, source in enumerate(self.videos) if key(source) not in self.exclusions), 0)
        self.load_current_video()
        self.refresh_video_list()
        self.main_splitter.setSizes([550, 430])
        self.make_scrollable()

    def refresh_table(self):
        super().refresh_table()
        self.fit_table_to_rows()

    def fit_table_to_rows(self):
        # Show every segment row; the window's scroll area handles the extra height.
        table = self.table
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rows = max(3, table.rowCount())
        height = (table.horizontalHeader().sizeHint().height()
                  + rows * table.verticalHeader().defaultSectionSize()
                  + 2 * table.frameWidth())
        if table.horizontalScrollBar().isVisible():
            height += table.horizontalScrollBar().sizeHint().height()
        table.setMinimumHeight(height)
        table.setMaximumHeight(height)

    def make_scrollable(self):
        # The controls need about 1550x1000 pixels. On smaller or scaled screens,
        # scroll the whole window instead of pushing buttons off the screen.
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        scroll.setWidget(self.takeCentralWidget())
        self.setCentralWidget(scroll)
        screen = self.screen() or QApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            # Leave room for the title bar and window frame.
            self.resize(min(1550, area.width() - 16), min(1000, area.height() - 48))
            self.move(area.left() + max(0, (area.width() - self.width()) // 2),
                      area.top() + max(0, (area.height() - self.height() - 40) // 2))

    def load_current_video(self):
        super().load_current_video()
        if self.snap_final_section_to_end():
            self.write_csv()
            self.refresh_table()
        if hasattr(self, 'comparison'):
            self.sync_editor_state_after_seek(0.)
            self.comparison.result = self.results.get(key(self.current_video_path()))
            self.comparison.update()
            self.update_review_banner()

    def duration_sec(self):
        # Qt can report the container/audio duration, which may exceed the
        # video duration used by inference and review validation.
        source = self.current_video_path()
        result = self.results.get(key(source)) if source else None
        return float(result['duration_sec']) if result else super().duration_sec()

    def current_time_sec(self):
        return min(super().current_time_sec(), self.duration_sec())

    def snap_final_section_to_end(self):
        indexes = self.sorted_current_video_segment_indexes()
        if not indexes:
            return False
        segment = self.segments[indexes[-1]]
        duration = self.duration_sec()
        if (math.isfinite(segment.start_sec) and math.isfinite(segment.end_sec)
                and 0 <= segment.start_sec < duration < segment.end_sec):
            segment.end_sec = duration
            return True
        return False

    def update_overlay_graphics(self):
        super().update_overlay_graphics()
        source = self.current_video_path()
        result = self.results.get(key(source)) if source else None
        if result:
            position = self.current_time_sec()
            def phase_at(track):
                segment = next((s for s in result['tracks'][track] if s['start_sec'] <= position < s['end_sec']), None)
                return segment['phase'].replace('_', ' ') if segment else 'unavailable'
            self.overlay_text.setPlainText(f"Video: {phase_at('video')}\nAudio: {phase_at('audio')}\n"
                                           f"Time: {labeler.seconds_to_label(position)}\n"
                                           f"Editing: {self.current_phase.replace('_', ' ')}")
            rect = self.overlay_text.boundingRect()
            self.overlay_rect.setRect(QRectF(12, 12, rect.width() + 24, rect.height() + 18))

    def update_comparison_position(self, milliseconds):
        self.comparison.position = milliseconds / 1000.
        self.comparison.update()

    def rows_for(self, source):
        source_key = key(source)
        return [asdict(s) for s in self.segments if key(s.source_video) == source_key]

    def reviewed(self, source, rows=None):
        if key(source) in self.exclusions:
            return False
        saved = self.review_state.get(key(source), {})
        result = self.results.get(key(source), {})
        return (bool(saved.get('fingerprint'))
                and saved.get('fingerprint') == annotation_fingerprint(self.rows_for(source) if rows is None else rows)
                and saved.get('source_sha256') == result.get('source_sha256'))

    def update_review_banner(self):
        source = self.current_video_path()
        if source is None:
            return
        result = self.results[key(source)]
        reviewed = self.reviewed(source)
        flags = ' '.join(result['review_flags']) or 'No automatic review flags.'
        excluded = self.exclusions.get(key(source))
        status = ('NOT SKYDIVING' if excluded.get('reason') == 'not_skydive' else 'NOT RELEVANT') if excluded else ('REVIEWED' if reviewed else 'NEEDS HUMAN REVIEW')
        self.review_button.setEnabled(not bool(excluded))
        self.exclude_button.setText('Restore video' if excluded else 'Not skydiving')
        self.review_banner.setText(f"{status} | {result['known_split']} | "
                                   f"Audio: {result['audio_status']} | {flags}\n"
                                   'Your editable labels start from V3 context. Video and audio predictions stay unchanged.')

    def refresh_video_list(self):
        super().refresh_video_list()
        if not hasattr(self, 'review_state'):
            return
        rows_by_source = {}
        for segment in self.segments:
            rows_by_source.setdefault(key(segment.source_video), []).append(asdict(segment))
        count = 0
        for i, source in enumerate(self.videos):
            done = self.reviewed(source, rows_by_source.get(key(source), []))
            count += int(done)
            item = self.video_list.item(i)
            if item:
                excluded = self.exclusions.get(key(source))
                status = ('Not skydiving' if excluded.get('reason') == 'not_skydive' else 'Not relevant') if excluded else ('Reviewed' if done else 'To review')
                item.setText(f"{status} | {source.name}")
                item.setToolTip(str(source))
        excluded_count = sum(key(source) in self.exclusions for source in self.videos)
        self.video_progress_label.setText(f'{count}/{len(self.videos)} explicitly reviewed; {excluded_count} not relevant')
        if hasattr(self, 'review_banner'):
            self.update_review_banner()

    def write_csv(self):
        write_csv(self.csv_path, [asdict(s) for s in self.segments])
        if hasattr(self, 'review_banner'):
            self.update_review_banner()

    def save_csv_silent(self):
        try:
            self.write_csv()
        except Exception as exc:
            QMessageBox.critical(self, 'Could not save your corrections', str(exc))

    def mark_reviewed(self):
        source = self.current_video_path()
        try:
            if key(source) in self.exclusions:
                raise ValueError('Restore this video before marking it reviewed.')
            self.snap_final_section_to_end()
            rows = self.rows_for(source)
            validate_review(rows, self.results[key(source)]['duration_sec'])
            self.write_csv()
            self.review_state[key(source)] = {'fingerprint': annotation_fingerprint(rows),
                'source_sha256': self.results[key(source)]['source_sha256'],
                'reviewed_utc': datetime.now(timezone.utc).isoformat()}
            write_json(self.review_state_path, self.review_state)
            self.refresh_video_list()
            self.next_video()
        except Exception as exc:
            QMessageBox.warning(self, 'Review needs attention', str(exc))

    def next_video(self):
        for index in range(self.video_index + 1, len(self.videos)):
            if key(self.videos[index]) not in self.exclusions:
                self.video_index = index
                self.load_current_video()
                return

    def toggle_exclusion(self):
        source = self.current_video_path()
        if source is None:
            return
        source_key = key(source)
        was_excluded = source_key in self.exclusions
        try:
            self.player.pause()
            self.write_csv()
            if was_excluded:
                restore_video(self.run_directory, source_key)
            else:
                record = self.records[self.video_index]
                exclude_video(self.run_directory, source_key, record.get('rel_path', str(source)))
            self.exclusions = read_mapping(self.exclusions_path)
            self.review_state = read_mapping(self.review_state_path)
            self.refresh_video_list()
            if not was_excluded:
                self.next_video()
        except Exception as exc:
            self.exclusions = read_mapping(self.exclusions_path)
            self.review_state = read_mapping(self.review_state_path)
            self.refresh_video_list()
            QMessageBox.warning(self, 'Could not update this video', str(exc))

    def evaluate_reviewed(self):
        from evaluate import evaluate
        try:
            self.write_csv()
            report = evaluate(self.run_directory)
            QMessageBox.information(self, 'Comparison saved',
                f"Compared {report['reviewed_videos']} reviewed videos.\n{self.run_directory / 'evaluation.md'}")
        except Exception as exc:
            QMessageBox.warning(self, 'Comparison needs attention', str(exc))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-directory')
    args = parser.parse_args()
    run = Path(args.run_directory) if args.run_directory else Path(json.loads((Path(__file__).parent / 'last_run.json').read_text())['run_directory'])
    app = QApplication(sys.argv[:1])
    configure_font(app)
    try:
        with RunLock(run):
            window = ReviewWindow(run)
            window.show()
            return app.exec()
    except Exception as exc:
        QMessageBox.critical(None, 'Cannot open V3 review', str(exc))
        return 1


def configure_font(app):
    # Explicit fallback also renders correctly in Windows offscreen QA.
    font_path = Path('C:/Windows/Fonts/segoeui.ttf')
    if font_path.is_file():
        QFontDatabase.addApplicationFont(str(font_path))
        app.setFont(QFont('Segoe UI', 9))


if __name__ == '__main__':
    sys.exit(main())
