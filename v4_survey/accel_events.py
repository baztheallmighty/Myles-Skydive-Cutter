"""Label-free timing check from motion data: find the exit, the parachute-opening shock and the landing in accelerometer
data, then compare with the survey's phases and, where they exist, with human labels.

Reads one or more telemetry_seconds.csv files (telemetry_scan.py, one row per second: mean/max/std of acceleration
magnitude in m/s^2; later files replace earlier rows for the same video), the survey triage CSV and the V3 labels.
Heuristics on one-second summaries, tuned to work at both GoPro's ~200 Hz and DJI's ~10 Hz:
  exit     the first three-second stretch averaging below 7.5 m/s^2 (the weightless moment after leaving the plane),
           after at least 5 steady seconds near 1 g
  opening  the strongest two-second mean above 13 m/s^2 (the canopy's sustained deceleration) that follows at least
           6 buffeting seconds (std above 1.5) in the previous 15, i.e. coming out of freefall
  landing  the last second, at least 10 s after the opening, whose peak exceeds 18 m/s^2 and that is followed by five
           calm seconds (std below 1.0)
Consistency windows: exit between the survey's exit onset - 3 s and freefall onset + 3 s; opening between opening
onset - 3 s and canopy onset + 3 s; landing between landing onset - 3 s and landed onset + 3 s (within 5 s of whichever
onset exists when only one does). Writes one row per video with motion data.
"""
from __future__ import annotations

import argparse
import collections
import csv
import statistics as st
from pathlib import Path


def read(path):
    with open(path, encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def detect(seconds):
    mean = {t: v['accel_mean'] for t, v in seconds.items() if v['accel_mean'] is not None}
    std = {t: v['accel_std'] or 0. for t, v in seconds.items()}
    peak = {t: v['accel_max'] or 0. for t, v in seconds.items()}
    times = sorted(mean)
    exit_time = None
    for t in times:
        steady = sum(8.5 <= mean.get(u, 0.) <= 11.5 for u in range(t - 8, t))
        window = [mean.get(u) for u in (t, t + 1, t + 2)]
        if steady >= 5 and None not in window and sum(window) / 3 < 7.5:
            exit_time = t
            break
    opening, strength = None, 0.
    for t in times:
        if t + 1 not in mean:
            continue
        value = (mean[t] + mean[t + 1]) / 2
        buffeting = sum(std.get(u, 0.) > 1.5 for u in range(t - 15, t))
        if value > 13 and buffeting >= 6 and value > strength:
            opening, strength = t, value
    landing = None
    if opening is not None:
        for t in sorted(peak, reverse=True):
            if t <= opening + 10:
                break
            if peak[t] > 18 and all(std.get(u, 99.) < 1.0 for u in range(t + 1, t + 6)):
                landing = t
                break
    return exit_time, opening, strength, landing


def within(value, low, high, slack):
    if value is None:
        return None
    if low is not None and high is not None:
        return low - slack <= value <= high + slack
    bound = low if low is not None else high
    return None if bound is None else abs(value - bound) <= slack + 2


def rate(values):
    values = [v for v in values if v is not None and v != '']
    return f'{sum(values)}/{len(values)} ({sum(values) / len(values):.0%})' if values else 'n/a'


def main():
    parser = argparse.ArgumentParser(description='Compare accelerometer exit/opening/landing times with the survey.')
    parser.add_argument('--seconds', action='append', required=True, help='telemetry_seconds.csv; repeat, later wins.')
    parser.add_argument('--triage', required=True)
    parser.add_argument('--labels', default='output/v3/data/manual_segments_v3.csv')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()

    series = {}
    for path in args.seconds:
        fresh = collections.defaultdict(dict)
        for row in read(path):
            if row['accel_mean']:
                fresh[row['rel_path']][int(row['t_sec'])] = {k: number(row[k]) for k in ('accel_mean', 'accel_max', 'accel_std')}
        series.update(fresh)
    triage = {r['rel_path']: r for r in read(args.triage) if r['status'] == 'success'}
    labels = collections.defaultdict(list)
    for row in read(args.labels):
        path = Path(row['source_video'])
        if path.is_file():
            labels[(path.name.casefold(), path.stat().st_size)].append(row)

    rows = []
    for rel, seconds in series.items():
        video = triage.get(rel)
        if not video or len(seconds) < 20:
            continue
        exit_time, opening, strength, landing = detect(seconds)
        onset = lambda phase: number(video[f'{phase}_start_sec'])
        human = {}
        for s in labels.get((rel.rsplit('/', 1)[-1].casefold(), int(video['size_bytes'])), []):
            human.setdefault(s['phase'], float(s['start_sec']))
        name = rel.rsplit('/', 1)[-1].upper()
        rows.append({
            'rel_path': rel, 'camera': 'DJI' if name.startswith('DJI_') else 'GoPro MAX' if name.startswith('GS') else 'GoPro HERO6+',
            'era': video['era'], 'kind': video['kind'], 'labelled_split': video['labelled_split'], 'accel_seconds': len(seconds),
            'accel_exit_sec': exit_time, 'survey_exit_sec': onset('exit'), 'survey_freefall_sec': onset('freefall'),
            'exit_consistent': within(exit_time, onset('exit'), onset('freefall'), 3),
            'accel_opening_sec': opening, 'opening_strength': round(strength, 1) if opening is not None else '',
            'survey_opening_sec': onset('opening_parachutes'), 'survey_canopy_sec': onset('canopy_flight'),
            'opening_consistent': within(opening, onset('opening_parachutes'), onset('canopy_flight'), 3),
            'accel_landing_sec': landing, 'survey_landing_sec': onset('landing'), 'survey_landed_sec': onset('landed'),
            'landing_consistent': within(landing, onset('landing'), onset('landed'), 3),
            'human_opening_sec': human.get('opening_parachutes'), 'human_canopy_sec': human.get('canopy_flight'),
            'detector_vs_human_opening': within(opening, human.get('opening_parachutes'), human.get('canopy_flight'), 3) if human else '',
            'detector_vs_human_exit': within(exit_time, human.get('exit'), human.get('freefall'), 3) if human else '',
        })
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, 'w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f'{len(rows)} surveyed videos with at least 20 seconds of accelerometer data')
    for event in ('exit', 'opening', 'landing'):
        found = [r for r in rows if r[f'accel_{event}_sec'] is not None]
        print(f"  {event:8} detected in motion data: {len(found)}; consistent with survey: {rate([r[f'{event}_consistent'] for r in rows])}")
    gaps = [r['accel_opening_sec'] - r['survey_opening_sec'] for r in rows
            if r['accel_opening_sec'] is not None and r['survey_opening_sec'] is not None]
    if gaps:
        print(f'  opening shock minus survey opening onset: median {st.median(gaps):+.1f} s, within 8 s {sum(abs(g) <= 8 for g in gaps)}/{len(gaps)}')
    labelled = [r for r in rows if r['labelled_split']]
    print(f"  detector against human labels ({len(labelled)} labelled videos): opening {rate([r['detector_vs_human_opening'] for r in labelled])}, "
          f"exit {rate([r['detector_vs_human_exit'] for r in labelled])}")
    for group in ('camera', 'era'):
        buckets = collections.defaultdict(list)
        for r in rows:
            buckets[r[group]].append(r['opening_consistent'])
        print(f'  opening consistency by {group}:', {g: rate(v) for g, v in sorted(buckets.items())})
    contradictions = [r for r in rows if False in (r['opening_consistent'], r['landing_consistent'], r['exit_consistent'])]
    print(f'  {len(contradictions)} videos where motion data contradicts at least one survey timing, e.g.:')
    for r in contradictions[:8]:
        print(f"    {r['rel_path']}: exit {r['accel_exit_sec']} vs {r['survey_exit_sec']}; opening {r['accel_opening_sec']} vs "
              f"{r['survey_opening_sec']}-{r['survey_canopy_sec']}; landing {r['accel_landing_sec']} vs {r['survey_landing_sec']}-{r['survey_landed_sec']}")


if __name__ == '__main__':
    main()
