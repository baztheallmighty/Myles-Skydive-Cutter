"""The Results list on the Process tab: one row per processed video, what happened, and what needs a look."""
from datetime import datetime
import os
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QComboBox, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from app.outputs import source_label, thumbnail_path
from app.system import open_file

FILTERS = ['All videos', 'Needs a look', 'Failed', 'Cut from your labels', 'Not reviewed']
COLUMNS = ['Video', 'Status', 'Labels', 'Clips', 'Needs a look', 'Notes', 'Processed']
QUIET_FLAGS = ('No camera motion data.', 'Clips were cut from your reviewed labels.', 'Marked not skydiving: no clips.')


def result_rows(state_directory, entries, input_folder=''):
    """What the list shows, from the ledger and each video's result file. Pure; no Qt."""
    import csv
    import json

    from app.monitor import EXCLUDED_LABELS, MODEL_LABELS, REVIEWED_LABELS
    from app.runs import engine_result
    from cutter_v4.review import ReviewStore, checks_from
    try:
        store = ReviewStore(state_directory)
    except (OSError, ValueError):
        store = None
    rows = []
    for source_key, entry in entries.items():
        result = engine_result(entry.get('run_directory')) or {}
        source = result.get('source_video') or source_key
        clips = []
        for manifest in entry.get('manifests') or []:
            try:
                with open(manifest, encoding='utf-8', newline='') as handle:
                    clips += list(csv.DictReader(handle))
            except OSError:
                pass
        used = entry.get('labels', MODEL_LABELS)
        pending = store is not None and store.fingerprint_key(source_key) != entry.get('review_fingerprint', '')
        labels = {REVIEWED_LABELS: 'Your labels', EXCLUDED_LABELS: 'Not skydiving'}.get(used, 'Model')
        if pending and entry.get('status') == 'success':
            labels += ' (re-cut pending)'
        checks = checks_from(result.get('agreement')) if used == 'model' else []
        fraction = result.get('disagreement_fraction')
        flags = [f for f in result.get('review_flags', []) if f not in QUIET_FLAGS and not f.startswith('Sources disagree')]
        thumb = None
        if clips and entry.get('output_name'):
            candidate = thumbnail_path(state_directory, entry['output_name'], clips[0]['profile'], clips[0]['clip_index'])
            thumb = str(candidate) if candidate.is_file() else None
        stamp = entry.get('completed_utc', '')
        try:
            stamp = datetime.fromisoformat(stamp).astimezone().strftime('%d %b %H:%M')
        except ValueError:
            pass
        rows.append({
            'key': source_key, 'source': source, 'name': source_label(source, input_folder) if input_folder else Path(source).name,
            'status': {'success': 'Done', 'failed': 'Failed', 'cancelled': 'Cancelled'}.get(entry.get('status'), entry.get('status', '')),
            'error': entry.get('error', ''), 'labels': labels, 'clips': len(clips),
            'checks': len(checks), 'disagreement': fraction if used == 'model' else None,
            'notes': ' '.join(flags), 'processed': stamp, 'thumbnail': thumb,
            'csv_path': entry.get('csv_path'), 'clip_paths': [c['clip_path'] for c in clips],
        })
    rows.sort(key=lambda r: (r['status'] == 'Done', -r['checks'], r['name'].casefold()))
    return rows


def keep(row, index):
    return (index == 0 or (index == 1 and (row['checks'] > 0 or row['status'] != 'Done'))
            or (index == 2 and row['status'] != 'Done') or (index == 3 and row['labels'].startswith('Your labels'))
            or (index == 4 and row['labels'].startswith('Model')))


class ResultsPanel(QGroupBox):
    open_in_review = Signal(str)
    process_again = Signal(str)

    def __init__(self, parent=None):
        super().__init__('Results', parent)
        self.rows = []
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.addItems(FILTERS)
        self.filter.currentIndexChanged.connect(self.show_rows)
        top.addWidget(QLabel('Show'))
        top.addWidget(self.filter)
        self.summary = QLabel('Nothing processed into this folder yet.')
        self.summary.setObjectName('hint')
        top.addWidget(self.summary, 1)
        layout.addLayout(top)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setIconSize(QSize(96, 54))
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(60)
        header = self.table.horizontalHeader()
        header.setResizeContentsPrecision(40)  # measure a sample of rows, not a whole season of them
        self.fit_columns()
        self.table.cellDoubleClicked.connect(lambda row, _column: self.emit_review(row))
        self.table.itemSelectionChanged.connect(self.update_buttons)
        layout.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        self.review_button = QPushButton('Open in Review')
        self.review_button.setToolTip('Open this video on the Review tab (or double-click the row).')
        self.review_button.clicked.connect(lambda: self.emit_review(self.table.currentRow()))
        self.clips_button = QPushButton('Show clips')
        self.clips_button.clicked.connect(self.show_clips)
        self.csv_button = QPushButton('Open timeline CSV')
        self.csv_button.clicked.connect(self.open_csv)
        self.again_button = QPushButton('Process this video again')
        self.again_button.setToolTip('Classify and cut this video again, for example after a failure.')
        self.again_button.clicked.connect(self.emit_again)
        for button in (self.review_button, self.clips_button, self.csv_button, self.again_button):
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.update_buttons()

    def load(self, state_directory, entries, input_folder=''):
        self.rows = result_rows(state_directory, entries, input_folder) if entries else []
        done = sum(r['status'] == 'Done' for r in self.rows)
        failed = sum(r['status'] == 'Failed' for r in self.rows)
        look = sum(r['checks'] > 0 for r in self.rows)
        clips = sum(r['clips'] for r in self.rows)
        self.summary.setText(f'{done} processed, {clips} clips' + (f', {failed} failed' if failed else '')
                             + (f', {look} with stretches to check' if look else '') if self.rows
                             else 'Nothing processed into this folder yet.')
        self.show_rows()

    def visible_rows(self):
        return [r for r in self.rows if keep(r, self.filter.currentIndex())]

    def fit_columns(self):
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.Stretch)

    def show_rows(self):
        rows = self.visible_rows()
        # Filling with the columns set to resize to their contents re-measures every row on every cell, which turns a
        # season's worth of videos into minutes of frozen window. Size the columns once, after the rows are in.
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setUpdatesEnabled(False)
        try:
            self.fill_rows(rows)
        finally:
            self.table.setUpdatesEnabled(True)
            self.fit_columns()
        self.update_buttons()

    def fill_rows(self, rows):
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            needs = '-' if row['disagreement'] is None else (
                f"{row['checks']} to check ({100 * row['disagreement']:.0f}% disagree)" if row['checks']
                else f"none ({100 * row['disagreement']:.0f}% disagree)")
            values = [row['name'], row['status'], row['labels'], str(row['clips']), needs, row['notes'], row['processed']]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setToolTip(row['source'])
                    if row['thumbnail']:
                        item.setIcon(QIcon(QPixmap(row['thumbnail'])))
                if column == 1 and row['status'] != 'Done':
                    item.setForeground(QColor('#ff9b85'))
                    item.setToolTip(row['error'] or row['status'])
                if column == 4 and row['checks']:
                    item.setForeground(QColor('#f0b43c'))
                self.table.setItem(index, column, item)

    def selected(self, index=None):
        index = self.table.currentRow() if index is None else index
        rows = self.visible_rows()
        return rows[index] if 0 <= index < len(rows) else None

    def update_buttons(self):
        row = self.selected()
        self.review_button.setEnabled(bool(row and row['status'] == 'Done'))
        self.clips_button.setEnabled(bool(row and row['clip_paths']))
        self.csv_button.setEnabled(bool(row and row['csv_path'] and Path(row['csv_path']).is_file()))
        self.again_button.setEnabled(row is not None)

    def emit_review(self, index):
        row = self.selected(index)
        if row and row['status'] == 'Done':
            self.open_in_review.emit(row['source'])

    def emit_again(self):
        row = self.selected()
        if row:
            self.process_again.emit(row['key'])

    def show_clips(self):
        row = self.selected()
        if row and row['clip_paths']:
            from cutter_v4.review_ui import show_in_folder
            show_in_folder(row['clip_paths'][0])

    def open_csv(self):
        row = self.selected()
        if row and row['csv_path'] and Path(row['csv_path']).is_file():
            open_file(row['csv_path'])
