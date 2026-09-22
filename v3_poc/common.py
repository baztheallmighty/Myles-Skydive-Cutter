"""Shared, timing-aware POC data contract. No training data is loaded here."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path

PHASES = ['inside_plane', 'climbing_out', 'exit', 'freefall', 'break_off',
          'opening_parachutes', 'canopy_flight', 'landing', 'landed']
KEEP = {'climbing_out', 'exit', 'freefall', 'break_off', 'landing'}
FIELDS = ['source_video', 'start_sec', 'end_sec', 'phase', 'keep', 'notes']
EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.mts', '.m2ts', '.wmv', '.mpg', '.mpeg', '.360'}


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def key(path):
    # NFC: macOS can hand back accented names decomposed, Windows composed; both must give the same key.
    import unicodedata
    return unicodedata.normalize('NFC', str(Path(path).resolve())).replace('\\', '/').casefold()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')
    os.replace(temporary, path)


def write_csv(path, rows):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, 'start_sec': f"{float(row['start_sec']):.3f}",
                             'end_sec': f"{float(row['end_sec']):.3f}",
                             'keep': str(row['keep']).lower()})
    os.replace(temporary, path)


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if not set(FIELDS).issubset(reader.fieldnames or []):
            raise ValueError(f'Invalid review CSV columns: {path}')
        rows = list(reader)
    for row in rows:
        row['start_sec'], row['end_sec'] = float(row['start_sec']), float(row['end_sec'])
        if not (math.isfinite(row['start_sec']) and math.isfinite(row['end_sec'])):
            raise ValueError('Non-finite annotation time')
        row['keep'] = str(row['keep']).lower() == 'true'
    return rows


def annotation_fingerprint(rows):
    # Match the labeler's three-decimal CSV serialization, including manual notes/keep.
    normalized = [{**{k: r[k] for k in FIELDS}, 'source_video': key(r['source_video']),
                   'start_sec': round(float(r['start_sec']), 3),
                   'end_sec': round(float(r['end_sec']), 3),
                   'keep': str(r['keep']).lower()} for r in rows]
    return digest(sorted(normalized, key=lambda r: (r['source_video'], r['start_sec'], r['end_sec'], r['phase'])))


def validate_review(rows, duration):
    rows = sorted(rows, key=lambda r: r['start_sec'])
    if not rows:
        raise ValueError('Add annotations before marking this video reviewed.')
    previous = 0.0
    for row in rows:
        start, end = float(row['start_sec']), float(row['end_sec'])
        if row['phase'] not in PHASES + ['unknown', 'empty_or_boring']:
            raise ValueError(f"Unrecognized phase: {row['phase']}")
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= duration + .051):
            raise ValueError('Annotation times must be finite and within the video.')
        if abs(start - previous) > .051:
            raise ValueError('Resolve annotation gaps/overlaps before marking reviewed. Use unknown where needed.')
        previous = end
    if abs(previous - duration) > .051:
        raise ValueError('Review must cover the full video, including unknown/empty intervals.')


def intervals(path, centres, duration, probabilities=None, left=0.0, right=None):
    """Midpoint boundaries; no minimum-duration deletion; no invented initial onset."""
    if not len(path):
        return []
    right = duration if right is None else min(duration, right)
    edges = [max(0.0, left)] + [(float(a) + float(b)) / 2 for a, b in zip(centres, centres[1:])] + [right]
    result = []
    for i, phase_index in enumerate(path):
        start, end = max(0., edges[i]), min(duration, edges[i + 1])
        if end <= start:
            continue
        phase = PHASES[int(phase_index)]
        confidence = float(probabilities[i, int(phase_index)]) if probabilities is not None else None
        if result and result[-1]['phase'] == phase and abs(result[-1]['end_sec'] - start) < 1e-6:
            result[-1]['end_sec'] = end
            result[-1]['_scores'].append(confidence)
        else:
            result.append({'start_sec': start, 'end_sec': end, 'phase': phase, 'keep': phase in KEEP,
                           'left_censored': not result, '_scores': [confidence]})
    for segment in result:
        scores = [v for v in segment.pop('_scores') if v is not None]
        segment['mean_model_probability'] = sum(scores) / len(scores) if scores else None
    return result


def events(segments):
    return [{'phase': s['phase'], 'time_sec': s['start_sec'],
             'onset_observed': not s.get('left_censored', i == 0)}
            for i, s in enumerate(segments)]


def cuts(segments):
    result = []
    for segment in segments:
        if segment['keep']:
            if result and abs(result[-1]['end_sec'] - segment['start_sec']) < 1e-6:
                result[-1]['end_sec'] = segment['end_sec']
            else:
                result.append({'start_sec': segment['start_sec'], 'end_sec': segment['end_sec']})
    return result


class RunLock:
    """OS-held lock releases even after a crash; no stale PID guessing."""
    def __init__(self, directory, name='run.lock'):
        self.path = Path(directory) / name

    def __enter__(self):
        self.file = self.path.open('a+b')
        try:
            if os.fstat(self.file.fileno()).st_size == 0:
                self.file.write(b'0')
                self.file.flush()
            self.file.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError(f'Another process has this run open: {self.path.parent}')
        return self

    def __exit__(self, *args):
        self.file.close()
