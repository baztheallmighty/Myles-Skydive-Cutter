"""Camera motion: the accelerometer trace, its three events, and the motion-only phase classifier.

Motion comes from metadata the camera writes into the file (GoPro GPMF, DJI djmd, CAMM); only the MP4 index and the
small metadata samples are read, never the video frames. Cameras without it (older GoPros, most other brands) simply
have no motion track.

The classifier sees nothing but motion: per-second acceleration mean, spread and peak plus gyro, with 8 s of context.
It is a label-free check on the video model. In testing, where it disagrees with the video model it catches about
two thirds of the video model's mistakes; it is never used to overwrite the video result.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from cutter_v4 import MODELS_DIR, ROOT

sys.path.insert(0, str(ROOT / 'v4_survey'))
from accel_events import detect  # noqa: E402
from telemetry_scan import scan  # noqa: E402

PHASES = ['inside_plane', 'climbing_out', 'exit', 'freefall', 'break_off',
          'opening_parachutes', 'canopy_flight', 'landing', 'landed']
CONTEXT = 8
MIN_SECONDS = 30
STANDARD_GRAVITY = 9.80665


def features(seconds: dict, is_dji: bool) -> dict:
    """Identical to scripts/motion_where_others_fail.py, which the shipped model was fitted and tested with."""
    lookup = lambda t, k, neutral: seconds[t][k] if t in seconds and seconds[t][k] is not None else neutral
    rows = {}
    for t in sorted(seconds):
        vector = []
        for offset in range(-CONTEXT, CONTEXT + 1):
            u = t + offset
            vector += [lookup(u, 'accel_mean', 9.8), lookup(u, 'accel_std', 0.), lookup(u, 'accel_max', 9.8),
                       lookup(u, 'gyro_mean', 0.)]
        window = [lookup(t + o, 'accel_mean', 9.8) for o in range(-CONTEXT, CONTEXT + 1)]
        vector += [float(np.mean(window)), float(np.std(window)), float(is_dji)]
        rows[t] = vector
    return rows


def read_seconds(source: Path) -> tuple[dict, dict]:
    """Per-second acceleration summaries (m/s^2) and a small status record."""
    row, per_second = scan(source.parent, source.name)
    seconds = {}
    for entry in per_second:
        if entry.get('accel_mean') is None:
            continue
        seconds[int(entry['t_sec'])] = {'accel_mean': float(entry['accel_mean']),
                                        'accel_std': float(entry.get('accel_std') or 0.),
                                        'accel_max': float(entry.get('accel_max') or entry['accel_mean']),
                                        'gyro_mean': float(entry['gyro_mean']) if entry.get('gyro_mean') is not None else None}
    status = {'scan_status': row.get('status'), 'metadata_tracks': row.get('metadata_tracks', ''),
              'seconds_with_motion': len(seconds)}
    return seconds, status


def load_classifier():
    """The motion model, or None if missing or unreadable (e.g. a different scikit-learn in a development setup).

    Without it the motion trace and events are still shown; only the motion-model row and motion agreement are lost.
    """
    path = MODELS_DIR / 'motion.joblib'
    if not path.is_file():
        return None
    try:
        import joblib
        return joblib.load(path)
    except Exception as exc:  # noqa: BLE001
        print(f'motion: motion model unavailable ({type(exc).__name__}); showing the trace only', flush=True)
        return None


def analyse(source: Path, monotonic, classifier=None) -> dict:
    """Everything the labeller and the agreement check need from motion, or ``available: False``."""
    seconds, status = read_seconds(source)
    if len(seconds) < MIN_SECONDS:
        return {'available': False, **status}
    exit_sec, opening_sec, opening_strength, landing_sec = detect(seconds)
    times = sorted(seconds)
    result = {
        'available': True, **status,
        'trace': {'t': times, 'load_g': [round(seconds[t]['accel_mean'] / STANDARD_GRAVITY, 3) for t in times]},
        # The opening shock peaks about 2.5 s after a labeller would mark the opening; both are reported as found.
        'events': {'exit_sec': exit_sec, 'opening_shock_sec': opening_sec, 'landing_sec': landing_sec},
        'phase_seconds': {},
    }
    if classifier is not None:
        rows = features(seconds, source.name.upper().startswith('DJI_'))
        order = sorted(rows)
        probabilities = classifier.predict_proba(np.array([rows[t] for t in order]))
        full = np.zeros((len(order), len(PHASES)))
        full[:, classifier.classes_] = probabilities
        path = monotonic(np.clip(full, 1e-6, 1))
        result['phase_seconds'] = {t: PHASES[p] for t, p in zip(order, path)}
    return result


def fit_classifier(inputs: Path, exclude_rel_paths: set[str]):
    """Refit the motion-only classifier exactly as tested (survey pseudo-labels, never human labels)."""
    import csv
    from collections import defaultdict

    from sklearn.ensemble import HistGradientBoostingClassifier

    def read(path):
        with open(path, encoding='utf-8-sig', newline='') as handle:
            return list(csv.DictReader(handle))

    def number(value, default=None):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    runs = ['pilot_rtx5090', 'run_rtx5090_1', 'run_rtx5090_2', 'run_rtx5090', 'pilot_rtx3070', 'run_rtx3070']
    motion = {}
    for name in ('telemetry_seconds.csv', 'telemetry_seconds_dji.csv'):
        fresh = defaultdict(dict)
        for row in read(inputs / name):
            if row['accel_mean']:
                fresh[row['rel_path']][int(row['t_sec'])] = {k: number(row[k]) for k in
                                                             ('accel_mean', 'accel_std', 'accel_max', 'gyro_mean')}
        motion.update(fresh)
    triage = {r['rel_path']: r for r in read(inputs / 'triage.csv') if r['status'] == 'success'}
    survey = {}
    for run in runs:
        found = defaultdict(list)
        for segment in read(inputs / f'{run}_segments.csv'):
            if segment['rel_path'] in motion and segment['rel_path'] not in survey:
                found[segment['rel_path']].append(segment)
        survey.update(found)
    train = [v for v in motion if v in triage and v in survey and len(motion[v]) >= MIN_SECONDS
             and v not in exclude_rel_paths and not triage[v]['labelled_split']]
    X, y = [], []
    for video in train:
        rows = features(motion[video], video.rsplit('/', 1)[-1].upper().startswith('DJI_'))
        for t, vector in rows.items():
            segment = next((s for s in survey[video] if float(s['start_sec']) <= t + .5 < float(s['end_sec'])), None)
            if (not segment or number(segment['mean_model_probability'], 0) < .95
                    or t + .5 - float(segment['start_sec']) < 3 or float(segment['end_sec']) - (t + .5) < 3):
                continue
            X.append(vector)
            y.append(PHASES.index(segment['phase']))
    X, y = np.array(X), np.array(y)
    counts = np.bincount(y, minlength=len(PHASES)).astype(float)
    weight = (counts.sum() / np.maximum(counts, 1)) ** .5
    model = HistGradientBoostingClassifier(max_iter=300, learning_rate=.08, max_leaf_nodes=31, random_state=0)
    model.fit(X, y, sample_weight=weight[y])
    return model, {'training_videos': len(train), 'training_seconds': int(len(y)),
                   'phase_counts': {PHASES[k]: int(c) for k, c in enumerate(counts)}}
