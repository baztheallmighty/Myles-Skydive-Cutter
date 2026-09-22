"""Canonical sampling and half-open phase lookup; CSV values are never padded."""
from bisect import bisect_right
import csv
import math
import os
from pathlib import Path

from app.profiles import matches

PERSON_FIELDS = ['person_count', 'largest_person_area_percent', 'total_person_area_percent']
# Only filled for 360 footage counted on both sides; the plain fields above are what the profiles filter on.
PER_VIEW_FIELDS = ['person_count_front', 'total_person_area_percent_front',
                   'person_count_back', 'total_person_area_percent_back']
FIELDS = ['source_video', 'time_sec', 'phase', 'phase_model_probability', 'sources_agree',
          *PERSON_FIELDS, *PER_VIEW_FIELDS, 'matched_profiles']


def canonical_grid(duration, sample_fps=1.0, people_enabled=True):
    rate = sample_fps if people_enabled else 1.0
    if not math.isfinite(duration) or duration <= 0 or not math.isfinite(rate) or rate <= 0:
        raise ValueError('Duration and sample rate must be finite and positive.')
    return [0.5 + n / rate for n in range(max(0, math.ceil((duration - .5) * rate)))
            if 0.5 + n / rate < duration]


def segment_at(time_sec, segments, starts=None):
    """The segment covering ``time_sec``; a point exactly on a boundary belongs to the segment starting there.

    Raises when the track does not cover the time, because a timeline row with no phase would be wrong to write.
    """
    starts = [s['start_sec'] for s in segments] if starts is None else starts
    index = bisect_right(starts, time_sec) - 1
    if index >= 0 and time_sec < segments[index]['end_sec']:
        return segments[index]
    raise ValueError(f'Phase track does not cover sample {time_sec:.3f}s.')


def agreement_at(time_sec, runs):
    """'yes'/'no' where a check source (motion, or audio without motion) agrees with the phase; 'NA' otherwise."""
    for run in runs or ():
        if run['start_sec'] <= time_sec < run['end_sec']:
            return {'agree': 'yes', 'disagree': 'no'}.get(run['status'], 'NA')
    return 'NA'


def join_timeline(source, duration, segments, people, settings, agreement=None):
    segments = sorted(segments, key=lambda s: s['start_sec'])
    starts = [s['start_sec'] for s in segments]
    people_by_time = {round(p['time_sec'], 9): p for p in people}
    rows = []
    for t in canonical_grid(duration, settings.sample_fps, settings.people_enabled):
        row = dict.fromkeys(FIELDS, 'NA')
        row.update(source_video=str(source), time_sec=t)
        if settings.phases_enabled:
            segment = segment_at(t, segments, starts)
            probability = segment.get('mean_model_probability')
            row.update(phase=segment['phase'], phase_model_probability=probability if probability is not None else 'NA',
                       sources_agree=agreement_at(t, agreement))
        if settings.people_enabled:
            person = people_by_time.get(round(t, 9))
            if person is None:
                raise ValueError(f'Missing person sample at {t:.3f}s; timeline not written.')
            row.update({k: person[k] for k in PERSON_FIELDS})
            row.update({k: person[k] for k in PER_VIEW_FIELDS if k in person})
        row['matched_profiles'] = ';'.join(p.name for p in settings.profiles
                                          if matches(p, row, settings.phases_enabled, settings.people_enabled))
        rows.append(row)
    return rows


def write_atomic_csv(path, rows, fields=FIELDS):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            for row in rows:
                writer.writerow({k: f'{v:.3f}' if isinstance(v, float) else v for k, v in row.items()})
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
