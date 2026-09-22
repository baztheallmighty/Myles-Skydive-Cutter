"""A season's worth of videos must not freeze the window.

A library of 974 videos once took over two minutes to appear when switching back from Review. The budgets below
guard the parts that can be measured from synthetic data: reading the results and filling the table.

The original freeze could not be reproduced synthetically, so the honest guard is against a real library: set
SKYDIVE_BIG_LIBRARY to a clips folder with hundreds of processed videos and the last test times the real thing.
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

VIDEOS = 1000
BUILD_BUDGET_SECONDS = 3.0      # reading a thousand small result files, warm
SHOW_BUDGET_SECONDS = 2.5       # filling the table: the part that regressed
FILTER_BUDGET_SECONDS = 2.0     # two full refills


@pytest.fixture
def big_library(tmp_path):
    """A ledger with a thousand finished videos, and the run results the list reads."""
    state = tmp_path / 'clips' / '_state'
    (state / 'runs').mkdir(parents=True)
    entries = {}
    for index in range(VIDEOS):
        name = f'jump{index:04d}'
        run = state / 'runs' / name
        run.mkdir()
        (run / 'result.json').write_text(json.dumps({
            'source_video': str(tmp_path / 'input' / f'{name}.mp4'), 'duration_sec': 300.0,
            'tracks': {'final': [{'start_sec': 0.0, 'end_sec': 300.0, 'phase': 'freefall'}]},
            'agreement': [{'start_sec': 0.0, 'end_sec': 10.0, 'status': 'disagree'}],
            'disagreement_fraction': 0.03, 'audio_status': 'ok'}), encoding='utf-8')
        manifest = state / 'runs' / name / 'clips.csv'
        manifest.write_text('clip_index,clip_path,source_video,profile,start_sec,end_sec,duration_sec,'
                            'dominant_phase,source_id,source_sha256,output_layout,source_folder\n'
                            f'1,{tmp_path / "clips" / (name + ".mp4")},{tmp_path / "input" / (name + ".mp4")},'
                            'Exit + Freefall,10,40,30,freefall,id,sha,per_video,\n', encoding='utf-8')
        entries[f'k{index}'] = {'status': 'success', 'run_directory': str(run), 'manifests': [str(manifest)],
                                'labels': 'model', 'review_fingerprint': '', 'processed_utc': '2026-09-20T10:00:00Z',
                                'output_name': name, 'csv_path': str(state / f'{name}.csv')}
    return state, entries


def test_building_the_rows_is_quick(big_library):
    """Reading a thousand results. The first pass is measured warm, so this is about the app, not the disk cache."""
    from app.ui.results import result_rows
    state, entries = big_library
    result_rows(state, entries, '')                    # warm the folder; a cold read is the filer's business
    began = time.monotonic()
    rows = result_rows(state, entries, '')
    elapsed = time.monotonic() - began
    assert len(rows) == VIDEOS
    assert elapsed < BUILD_BUDGET_SECONDS, f'reading {VIDEOS} results took {elapsed:.1f}s'


def test_filling_the_table_is_quick(big_library):
    """The regression that mattered: filling the table re-measured every row for every cell, which turned a
    season's library into a two-minute freeze. This has nothing to do with the disk."""
    from PySide6.QtWidgets import QApplication
    from app.ui import theme
    from app.ui.results import ResultsPanel, result_rows
    state, entries = big_library
    application = QApplication.instance() or QApplication([])
    theme.apply(application)
    panel = ResultsPanel()
    panel.resize(1200, 700)
    panel.show()
    panel.rows = result_rows(state, entries, '')

    began = time.monotonic()
    panel.show_rows()
    application.processEvents()
    shown = time.monotonic() - began
    assert panel.table.rowCount() == VIDEOS
    assert shown < SHOW_BUDGET_SECONDS, f'filling the table with {VIDEOS} videos took {shown:.1f}s'

    began = time.monotonic()
    panel.filter.setCurrentIndex(1)          # needs a look
    application.processEvents()
    panel.filter.setCurrentIndex(0)
    application.processEvents()
    filtered = time.monotonic() - began
    assert filtered < FILTER_BUDGET_SECONDS, f'filtering took {filtered:.1f}s'
    panel.close()


@pytest.mark.skipif(not os.environ.get('SKYDIVE_BIG_LIBRARY'),
                    reason='set SKYDIVE_BIG_LIBRARY to a clips folder with a real processed library')
def test_a_real_library_appears_quickly():
    """Switching back to Process with a real library. This is the case that froze for two minutes."""
    from PySide6.QtWidgets import QApplication
    from app.monitor import load_ledger
    from app.ui import theme
    from app.ui.results import ResultsPanel
    clips = Path(os.environ['SKYDIVE_BIG_LIBRARY'])
    state = clips / '_state'
    entries = load_ledger(state / 'ledger.json')['entries']
    assert len(entries) >= 100, f'{clips} holds only {len(entries)} videos; use a bigger library'

    application = QApplication.instance() or QApplication([])
    theme.apply(application)
    panel = ResultsPanel()
    panel.resize(1400, 800)
    panel.show()
    began = time.monotonic()
    panel.load(state, entries, '')
    application.processEvents()
    elapsed = time.monotonic() - began
    panel.close()
    assert elapsed < 10.0, f'{len(entries)} real videos took {elapsed:.1f}s to appear'
