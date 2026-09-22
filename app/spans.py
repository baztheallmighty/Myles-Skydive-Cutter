"""Turning a per-second timeline into clip spans, and naming what comes out.

These rules came from the original cut-from-CSV tool and decide where clips begin and end, so they are kept
deliberately plain: a span starts at the first interesting sample and ends one sample after the last.
"""
from collections import Counter
import re


def sample_step(rows):
    """The usual gap between samples, so a span can end at the far edge of its last sample."""
    gaps = sorted(gap for gap in (float(b['time_sec']) - float(a['time_sec']) for a, b in zip(rows, rows[1:]))
                  if gap > 0)
    return gaps[len(gaps) // 2] if gaps else 1.0


def fill_small_gaps(rows, max_gap_seconds):
    """Bridge a short dull stretch between two interesting ones, in place."""
    step = sample_step(rows)
    index = 0
    while index < len(rows):
        if rows[index]['interesting']:
            index += 1
            continue
        start = index
        while index < len(rows) and not rows[index]['interesting']:
            index += 1
        gap = float(rows[index - 1]['time_sec']) - float(rows[start]['time_sec']) + step
        joins_two = start > 0 and rows[start - 1]['interesting'] and index < len(rows) and rows[index]['interesting']
        if joins_two and gap <= max_gap_seconds:
            for position in range(start, index):
                rows[position]['interesting'] = True


def build_spans(rows):
    """Runs of interesting samples, as (start, end) in seconds."""
    step = sample_step(rows)
    spans, index = [], 0
    while index < len(rows):
        if not rows[index]['interesting']:
            index += 1
            continue
        start = float(rows[index]['time_sec'])
        while index + 1 < len(rows) and rows[index + 1]['interesting']:
            index += 1
        spans.append((start, float(rows[index]['time_sec']) + step))
        index += 1
    return spans


def merge_close_spans(spans, merge_gap=1.0):
    """Join spans separated by less than ``merge_gap``, so one moment is not cut into two clips."""
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1] + merge_gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def dominant_phase(rows, start_sec, end_sec):
    """The phase a clip is named after: the most common one across the samples it covers."""
    phases = [phase for row in rows if start_sec <= float(row['time_sec']) <= end_sec
              for phase in [str(row.get('phase_label') or row.get('phase') or '').strip()]
              if phase and phase != 'unknown']
    return Counter(phases).most_common(1)[0][0] if phases else 'unknown'


def slugify(value):
    """A file-name-safe form of a profile or phase name."""
    return re.sub(r'[^A-Za-z0-9]+', '_', value).strip('_').lower() or 'unknown'


def clip_filename(index, start_sec, end_sec, phase):
    return f'clip_{index:03d}_{int(round(start_sec)):06d}s-{int(round(end_sec)):06d}s_{slugify(phase)}.mp4'
