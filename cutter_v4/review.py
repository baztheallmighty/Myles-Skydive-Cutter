"""Review what was cut: the labeller with every prediction and sensor lined up under the video.

Opened from the cutter's "Review cuts in labeller" button (or 3-Review-Labels.cmd). The review folder lives in the
clips folder's ``_state/review`` and is rebuilt from the processed videos each time it opens; your edits in
``review.csv`` and your "reviewed" marks are kept.

Rows under the video (click any row to jump there):
  Final       what the cutter used for this video
  V4 video    the video model on its own
  Audio       the audio model on its own
  Motion      the motion-only model (cameras that record motion data)
  Motion (g)  the accelerometer load, with the exit dip, opening shock and landing marked
  Agreement   green where motion (or audio, without motion) agrees with Final, amber where it does not
  Clips cut   the clips each profile produced

When you mark a video reviewed, your labels replace the model for that video: the next time you process, its clips
are cut from your labels. "Not skydiving" makes the cutter produce no clips for it.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from cutter_v4 import ROOT

sys.path.insert(0, str(ROOT / 'v3_poc'))
from common import (FIELDS, RunLock, annotation_fingerprint, key, read_csv, write_csv,  # noqa: E402
                    write_json)

REVIEW_FOLDER = 'review'
AGREEMENT_COLORS = {'agree': '#2e7d4f', 'disagree': '#e0a21b', 'unknown': '#3a4454'}
CLIP_COLOR = '#3b82c4'


def review_directory(state_directory: Path) -> Path:
    return Path(state_directory) / REVIEW_FOLDER


# ------------------------------------------------------------------------------------ review folder (no Qt needed)
def read_json(path: Path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def clips_from_manifests(manifests: list[str]) -> list[dict]:
    clips = []
    for manifest in manifests or []:
        path = Path(manifest)
        if not path.is_file():
            continue
        with path.open(encoding='utf-8', newline='') as handle:
            for row in csv.DictReader(handle):
                clips.append({'profile': row['profile'], 'start_sec': float(row['start_sec']),
                              'end_sec': float(row['end_sec']), 'clip_path': row['clip_path']})
    return clips


def people_track(csv_path, requirement=None):
    """Per-second people from the timeline CSV: how many were seen, how much frame they filled, what matched.

    This is what decides whether a second survives a profile's people filter, so the review can show it beside the
    phases instead of leaving an empty clip unexplained.
    """
    import csv as csv_module
    try:  # the timeline CSV, not a review CSV, so it is read plainly
        with Path(csv_path).open(encoding='utf-8', newline='') as handle:
            rows = list(csv_module.DictReader(handle))
    except (OSError, ValueError):
        return None
    times, counts, areas, matched = [], [], [], []
    for row in rows:
        if 'person_count' not in row:
            return None
        try:
            times.append(float(row['time_sec']))
            counts.append(int(float(row.get('person_count') or 0)))
            areas.append(float(row.get('total_person_area_percent') or 0))
        except (TypeError, ValueError):
            return None
        matched.append(bool((row.get('matched_profiles') or '').strip()))
    if not times:
        return None
    track = {'t': times, 'count': counts, 'area': areas, 'matched': matched,
             'counted': any(counts), 'max_count': max(counts), 'max_area': max(areas)}
    if requirement:
        track['requirement'] = requirement
    return track


def people_requirement(profiles):
    """The easiest people bar any enabled profile sets, drawn as the line to clear."""
    asking = [p for p in profiles or [] if getattr(p, 'enabled', True)
              and (getattr(p, 'min_person_count', 0) or getattr(p, 'min_total_area_percent', 0))]
    if not asking:
        return None
    easiest = min(asking, key=lambda p: (p.min_person_count, p.min_total_area_percent))
    return {'name': easiest.name, 'min_count': easiest.min_person_count,
            'min_area': float(easiest.min_total_area_percent)}


def build_review_run(state_directory: Path, input_folder: str = '', locked: bool = False, profiles=None) -> Path:
    """Refresh the review folder from the cutter's ledger. Human edits in review.csv are never overwritten.

    ``locked``: the caller (the app's Review tab) already holds the review folder's lock.
    """
    state_directory = Path(state_directory)
    ledger = read_json(state_directory / 'ledger.json', {}).get('entries', {})
    run = review_directory(state_directory)
    store = ReviewStore(state_directory)
    (run / 'videos').mkdir(parents=True, exist_ok=True)
    with (_NoLock() if locked else RunLock(run)):
        csv_path = run / 'review.csv'
        existing = read_csv(csv_path) if csv_path.exists() else []
        have = {key(row['source_video']) for row in existing}
        rows, records = list(existing), []
        for source_key, entry in sorted(ledger.items()):
            if entry.get('status') != 'success' or not entry.get('run_directory'):
                continue
            result_path = Path(entry['run_directory']) / 'result.json'
            result = read_json(result_path)
            if not result or 'tracks' not in result or 'final' not in result['tracks']:
                continue
            # Where the video is now: the ledger records it from 2.4.0 on, and a moved video's run still names
            # the old place.
            source = entry.get('source_video') or result['source_video']
            if not Path(source).exists():
                continue
            name = entry.get('output_name') or Path(source).stem
            result.update(source_sha256=entry.get('source_sha256', ''), known_split='',
                          clips=clips_from_manifests(entry.get('manifests')), output_name=name,
                          labels_used=entry.get('labels', 'model'))
            people = people_track(entry.get('csv_path') or '', people_requirement(profiles))
            if people:
                result['people'] = people
            # "Final (cut)" must show what the clips were actually cut from.
            if entry.get('labels') == 'reviewed':
                reviewed = store.segments_for(source, entry.get('source_sha256', ''), float(result['duration_sec']))
                if reviewed:
                    result['tracks']['final'] = reviewed
                    result['agreement'] = []
                    result['review_flags'] = ['Clips were cut from your reviewed labels.'] + result.get('review_flags', [])
            elif entry.get('labels') == 'excluded':
                result['tracks']['final'] = []
                result['agreement'] = []
                result['review_flags'] = ['Marked not skydiving: no clips.'] + result.get('review_flags', [])
            target = run / 'videos' / name / 'result.json'
            target.parent.mkdir(parents=True, exist_ok=True)
            write_json(target, result)
            try:
                rel = str(Path(source).resolve().relative_to(Path(input_folder).resolve())) if input_folder else Path(source).name
            except ValueError:
                rel = Path(source).name
            records.append({'status': 'success', 'source_video': source, 'result': f'videos/{name}/result.json',
                            'rel_path': rel})
            if key(source) not in have:
                for segment in result['tracks']['final']:
                    rows.append({'source_video': source, 'start_sec': segment['start_sec'],
                                 'end_sec': segment['end_sec'], 'phase': segment['phase'],
                                 'keep': segment['phase'] in ('exit', 'freefall'),
                                 'notes': 'Skydive Cutter V4; unreviewed'})
                have.add(key(source))
        write_csv(csv_path, rows)
        write_json(run / 'status.json', {'schema_version': 1, 'records': records,
                                         'updated_utc': datetime.now(timezone.utc).isoformat()})
    return run


def checks_from(agreement: list[dict] | None, merge_gap: float = 2.0, minimum: float = 2.0) -> list[tuple[float, float]]:
    """Stretches worth a look: disagreement runs, merged across short gaps, ignoring one-second blips."""
    runs = []
    for run in agreement or []:
        if run['status'] != 'disagree':
            continue
        if runs and run['start_sec'] - runs[-1][1] <= merge_gap:
            runs[-1][1] = run['end_sec']
        else:
            runs.append([run['start_sec'], run['end_sec']])
    return [(start, end) for start, end in runs if end - start >= minimum]


class _NoLock:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class ReviewStore:
    """What the cutter needs from the review folder: labels you marked reviewed, and videos you excluded."""

    def __init__(self, state_directory: Path):
        self.run = review_directory(state_directory)
        self.state = read_json(self.run / 'review_state.json', {}) or {}
        self.exclusions = read_json(self.run / 'review_exclusions.json', {}) or {}
        rows = read_csv(self.run / 'review.csv') if (self.run / 'review.csv').exists() else []
        self.rows: dict[str, list[dict]] = {}
        for row in rows:
            self.rows.setdefault(key(row['source_video']), []).append(row)

    def fingerprint(self, source) -> str:
        """Changes whenever what the cutter should use for this video changes."""
        return self.fingerprint_key(key(source))

    def fingerprint_key(self, source_key: str) -> str:
        if source_key in self.exclusions:
            return 'excluded'
        saved = self.state.get(source_key)
        if not saved:
            return ''
        return f"reviewed:{saved.get('fingerprint', '')}:{saved.get('source_sha256', '')}"

    def segments_for(self, source, content_sha256: str, duration: float):
        """Your reviewed labels for this exact file, ``[]`` if you excluded it, else ``None`` (use the model)."""
        source_key = key(source)
        if source_key in self.exclusions:
            return []
        saved = self.state.get(source_key)
        if not saved or saved.get('source_sha256') != content_sha256:
            return None
        # The labels as they were when you marked the video reviewed; later unmarked edits do not count yet.
        rows = saved.get('rows')
        if rows is None:
            rows = self.rows.get(source_key, [])
            if saved.get('fingerprint') != annotation_fingerprint(rows):
                return None
        segments = []
        for row in sorted(rows, key=lambda r: r['start_sec']):
            start, end = max(0.0, float(row['start_sec'])), min(duration, float(row['end_sec']))
            if end > start:
                segments.append({'start_sec': start, 'end_sec': end, 'phase': row['phase'],
                                 'mean_model_probability': None})
        if segments:
            segments[0]['start_sec'], segments[-1]['end_sec'] = 0.0, duration
            for previous, following in zip(segments, segments[1:]):
                following['start_sec'] = previous['end_sec']
        return segments


# ------------------------------------------------------------------------------------------------ the window (Qt)
def window_class():
    """The labeller window class (cutter_v4/review_ui.py). Needs a QApplication."""
    from cutter_v4.review_ui import CutterReviewWindow
    return CutterReviewWindow


def run_window(run_directory: Path) -> int:
    from PySide6.QtWidgets import QApplication, QMessageBox

    import review as base  # v3_poc/review.py

    app = QApplication(sys.argv[:1])
    base.configure_font(app)
    try:
        with RunLock(run_directory):
            window = window_class()(run_directory)
            window.show()
            return app.exec()
    except Exception as exc:  # noqa: BLE001
        QMessageBox.critical(None, 'Cannot open the review', str(exc))
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--state-directory', type=Path, help='the cutter output folder\'s _state folder')
    parser.add_argument('--input-folder', default='')
    parser.add_argument('--run-directory', type=Path, help='open an existing review folder as it is')
    args = parser.parse_args()
    if args.run_directory:
        run = args.run_directory
    elif args.state_directory:
        run = build_review_run(args.state_directory, args.input_folder)
    else:
        parser.error('Give --state-directory or --run-directory.')
    if not read_json(run / 'status.json', {}).get('records'):
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication(sys.argv[:1])  # noqa: F841 - needed for the message box
        QMessageBox.information(None, 'Nothing to review yet',
                                'No processed videos were found for these folders. Process some videos first.')
        return 1
    return run_window(run)


if __name__ == '__main__':
    sys.exit(main())
