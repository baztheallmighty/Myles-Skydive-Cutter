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
# What each column sorts by, and the width it starts at. Video and Notes share whatever room is left.
SORT_KEYS = [lambda r: r['name'].casefold(), lambda r: r['status'], lambda r: r['labels'], lambda r: r['clips'],
             lambda r: (r['checks'], r['disagreement'] or 0), lambda r: r['notes'].casefold(), lambda r: r['completed']]
WIDTHS = [180, 78, 112, 52, 168, 90, 104]
ROOMY = (0, 5)   # Video and Notes take whatever is left over


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
        stamp = completed = entry.get('completed_utc', '')
        try:
            stamp = datetime.fromisoformat(stamp).astimezone().strftime('%d %b %H:%M')
        except ValueError:
            pass
        rows.append({
            'key': source_key, 'source': source, 'name': source_label(source, input_folder) if input_folder else Path(source).name,
            'status': {'success': 'Done', 'failed': 'Failed', 'cancelled': 'Cancelled'}.get(entry.get('status'), entry.get('status', '')),
            'error': entry.get('error', ''), 'labels': labels, 'clips': len(clips),
            'checks': len(checks), 'disagreement': fraction if used == 'model' else None,
            'notes': ' '.join(flags), 'processed': stamp, 'completed': completed, 'thumbnail': thumb,
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
    process_again = Signal(object)   # the keys of every selected video

    def __init__(self, parent=None):
        super().__init__('Results', parent)
        self.rows = []
        self.shown = []           # the rows in the table, in the order they are listed
        self.sort_column = None   # None: the usual order, problems first
        self.sort_descending = False
        self.sized_by_hand = False
        self.fitting = False
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
        # Several at once: Ctrl or Shift and click, or Ctrl+A for all, so a whole list can be processed again.
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setIconSize(QSize(96, 54))
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(60)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)   # every column can be dragged wider or narrower
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(28)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(False)
        header.sectionClicked.connect(self.sort_by)
        header.sectionResized.connect(self.resized_by_hand)
        header.setToolTip('Click a title to sort by it; click again to turn the order round. Drag an edge to resize.')
        self.fit_columns()
        self.table.cellDoubleClicked.connect(lambda row, _column: self.emit_review(row))
        self.table.itemSelectionChanged.connect(self.update_buttons)
        layout.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        self.review_button = QPushButton('Open in Review')
        self.review_button.setToolTip('Open this video on the Review tab (or double-click the row).')
        self.review_button.clicked.connect(lambda: self.emit_review(None))
        self.clips_button = QPushButton('Show clips')
        self.clips_button.clicked.connect(self.show_clips)
        self.csv_button = QPushButton('Open timeline CSV')
        self.csv_button.clicked.connect(self.open_csv)
        self.again_button = QPushButton('Process again')
        self.again_button.setToolTip('Classify and cut the selected videos again, for example after a failure or a '
                                     'change of mind. Select several with Ctrl or Shift, or all with Ctrl+A.')
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
        """The rows the filter lets through, in the order chosen by clicking a column title."""
        rows = [r for r in self.rows if keep(r, self.filter.currentIndex())]
        if self.sort_column is not None:
            rows.sort(key=SORT_KEYS[self.sort_column], reverse=self.sort_descending)
        return rows

    def sort_by(self, column):
        """Sort by this column; the same column again turns the order round."""
        self.sort_descending = self.sort_column == column and not self.sort_descending
        self.sort_column = column
        header = self.table.horizontalHeader()
        header.setSortIndicatorShown(True)
        header.setSortIndicator(column, Qt.SortOrder.DescendingOrder if self.sort_descending
                                else Qt.SortOrder.AscendingOrder)
        self.show_rows()

    def resized_by_hand(self, *_):
        if not self.fitting:
            self.sized_by_hand = True   # the widths are yours from here on

    def fit_columns(self):
        """Every column inside the list: the short ones at their own width, Video and Notes sharing the rest."""
        if self.sized_by_hand:
            return
        self.fitting = True
        try:
            room, usual = self.table.viewport().width() - 2, sum(WIDTHS)
            widths = [int(width * room / usual) for width in WIDTHS] if room < usual else list(WIDTHS)
            spare = room - sum(widths)
            if spare > 0:   # a wide list gives the extra to the two columns that hold long text
                widths[ROOMY[0]] += int(spare * .6)
                widths[ROOMY[1]] += spare - int(spare * .6)
            for column, width in enumerate(widths):
                self.table.setColumnWidth(column, width)
        finally:
            self.fitting = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_columns()

    def showEvent(self, event):
        super().showEvent(event)
        self.fit_columns()

    def show_rows(self):
        chosen = {row['key'] for row in self.selected_rows()}
        self.shown = self.visible_rows()
        self.table.setUpdatesEnabled(False)
        try:
            self.fill_rows(self.shown)
            self.table.clearSelection()
            model, selection = self.table.model(), self.table.selectionModel()
            for index, row in enumerate(self.shown):   # the same videos stay selected through a sort or a refresh
                if row['key'] in chosen:
                    selection.select(model.index(index, 0),
                                     selection.SelectionFlag.Select | selection.SelectionFlag.Rows)
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
                item.setToolTip(value)   # whatever a narrow column cuts short can still be read
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
        if index is None:
            rows = self.selected_rows()
            return rows[0] if rows else None
        return self.shown[index] if 0 <= index < len(self.shown) else None

    def selected_rows(self):
        """Every selected video, in the order listed."""
        indexes = sorted({item.row() for item in self.table.selectedIndexes()})
        return [self.shown[index] for index in indexes if index < len(self.shown)]

    def update_buttons(self):
        rows = self.selected_rows()
        row = rows[0] if len(rows) == 1 else None   # these three act on one video
        self.review_button.setEnabled(bool(row and row['status'] == 'Done'))
        self.clips_button.setEnabled(bool(row and row['clip_paths']))
        self.csv_button.setEnabled(bool(row and row['csv_path'] and Path(row['csv_path']).is_file()))
        self.again_button.setEnabled(bool(rows))
        self.again_button.setText(f'Process these {len(rows)} again' if len(rows) > 1 else 'Process again')

    def emit_review(self, index):
        row = self.selected(index)
        if row and row['status'] == 'Done':
            self.open_in_review.emit(row['source'])

    def emit_again(self):
        keys = [row['key'] for row in self.selected_rows()]
        if keys:
            self.process_again.emit(keys)

    def show_clips(self):
        row = self.selected()
        if row and row['clip_paths']:
            from cutter_v4.review_ui import show_in_folder
            show_in_folder(row['clip_paths'][0])

    def open_csv(self):
        row = self.selected()
        if row and row['csv_path'] and Path(row['csv_path']).is_file():
            open_file(row['csv_path'])
