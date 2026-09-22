"""End-to-end test of an installed package, using its own runtime and code (developer tool, not shipped).

    <package>\\.runtime\\cu128\\python.exe -s -B release\\tests\\package_smoke_test.py --work W --labels L V1 V2 ...

Copies the videos into W\\input (originals are only read), then runs what the app runs: process every video, build
the review folder, apply a reviewed correction and a "not skydiving" exclusion, reprocess, and check the clips follow
them. Renders the labeller and the main window to PNG. Prints per-video timing and agreement with human labels.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import shutil
import sys
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--labels', type=Path, help='human_segments.csv + manifest.csv folder, for agreement only')
    parser.add_argument('videos', nargs='+', type=Path)
    args = parser.parse_args()

    from app.monitor import VideoProcessor, file_signature, ledger_entry, load_ledger, needs_processing, save_ledger
    from app.runtime import ProcessRunner
    from app.settings import Settings, settings_fingerprint, state_directory, validate_settings
    from cutter_v4.review import ReviewStore, build_review_run, window_class
    from v3_poc.common import annotation_fingerprint, key, read_csv, write_csv, write_json

    work = args.work.resolve()
    if work.exists():
        shutil.rmtree(work)
    sources = []
    for index, video in enumerate(args.videos):
        target = work / 'input' / f'card{index + 1}' / video.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(video, target)
        sources.append(target)
    settings = Settings(input_folder=str(work / 'input'), output_folder=str(work / 'clips'), csv_folder=str(work / 'csv'),
                        people_enabled=False, output_layout='per_video')
    validate_settings(settings, require_folders=True)
    fingerprint = settings_fingerprint(settings)
    state = state_directory(settings)
    ledger_path = state / 'ledger.json'
    state.mkdir(parents=True, exist_ok=True)
    ledger = load_ledger(ledger_path)
    log = []
    runner = ProcessRunner(log=lambda message: (log.append(message), print('   ', message, flush=True)))
    processor = VideoProcessor(settings, runner)

    def process(source):
        began = time.monotonic()
        entry = ledger['entries'].get(key(source))
        signature = file_signature(source)
        result = processor.process(source, signature, entry)
        ledger['entries'][key(source)] = ledger_entry(signature, fingerprint, 'success', **result)
        save_ledger(ledger_path, ledger)
        return result, time.monotonic() - began

    def clips_of(result):
        with open(result['manifests'][0], encoding='utf-8', newline='') as handle:
            return [(float(r['start_sec']), float(r['end_sec'])) for r in csv.DictReader(handle)]

    human = {}
    if args.labels:
        manifest = {Path(r['source_key']).name.casefold(): r['video_id'] for r in read_csv_plain(args.labels / 'manifest.csv')}
        for row in read_csv_plain(args.labels / 'human_segments.csv'):
            human.setdefault(row['video_id'], []).append((float(row['start_sec']), float(row['end_sec']), row['phase']))
    report = {'videos': []}
    first = {}
    for source in sources:
        print(f'\n== {source.name}', flush=True)
        result, seconds = process(source)
        engine = json.loads((Path(result['run_directory']) / 'result.json').read_text(encoding='utf-8'))
        clips = clips_of(result)
        first[key(source)] = (result, clips)
        entry = {'video': source.name, 'duration_sec': engine['duration_sec'], 'processing_seconds': round(seconds, 1),
                 'engine_seconds': engine['timing_seconds'], 'motion': engine['motion'].get('available'),
                 'audio': engine['audio_status'], 'agreement_basis': engine['agreement_basis'],
                 'disagreement_fraction': engine['disagreement_fraction'], 'flags': engine['review_flags'],
                 'final': [(s['phase'], s['start_sec'], s['end_sec']) for s in engine['tracks']['final']],
                 'clips': clips}
        video_id = manifest.get(source.name.casefold()) if args.labels else None
        if video_id in human:
            truth = human[video_id]
            phase_at = lambda segs, t: next((p for a, b, p in segs if a <= t < b), None)
            final = [(s['start_sec'], s['end_sec'], s['phase']) for s in engine['tracks']['final']]
            seconds_ok = [phase_at(final, k + .5) == phase_at(truth, k + .5) for k in range(int(engine['duration_sec']))
                          if phase_at(truth, k + .5) not in (None, 'unknown', 'empty_or_boring')]
            entry['agreement_with_human_labels'] = round(sum(seconds_ok) / len(seconds_ok), 3) if seconds_ok else None
        report['videos'].append(entry)
        print(json.dumps({k: v for k, v in entry.items() if k != 'final'}, indent=1), flush=True)

    # Review folder: every processed video, labels seeded from Final.
    run = build_review_run(state, settings.input_folder)
    status = json.loads((run / 'status.json').read_text(encoding='utf-8'))
    rows = read_csv(run / 'review.csv')
    assert len(status['records']) == len(sources), status
    assert {key(r['source_video']) for r in rows} == {key(s) for s in sources}
    report['review_folder'] = {'records': len(status['records']), 'label_rows': len(rows)}

    # A reviewed correction: extend freefall by 3 s on the first video that has freefall followed by another phase.
    corrected = None
    for source in sources:
        mine = sorted([r for r in rows if key(r['source_video']) == key(source)], key=lambda r: r['start_sec'])
        index = next((i for i, r in enumerate(mine[:-1]) if r['phase'] == 'freefall'), None)
        if index is not None and mine[index + 1]['end_sec'] - mine[index + 1]['start_sec'] > 4:
            mine[index]['end_sec'] += 3.0
            mine[index + 1]['start_sec'] += 3.0
            corrected = source
            others = [r for r in rows if key(r['source_video']) != key(source)]
            write_csv(run / 'review.csv', others + mine)
            review_state = json.loads((run / 'review_state.json').read_text()) if (run / 'review_state.json').exists() else {}
            review_state[key(source)] = {'fingerprint': annotation_fingerprint(mine),
                                         'source_sha256': ledger['entries'][key(source)]['source_sha256'],
                                         'reviewed_utc': 'test', 'rows': [{k: r[k] for k in
                                             ('source_video', 'start_sec', 'end_sec', 'phase', 'keep', 'notes')} for r in mine]}
            write_json(run / 'review_state.json', review_state)
            break
    assert corrected is not None, 'No video with a freefall to correct.'
    # Exclude a different video.
    excluded = next(s for s in sources if s != corrected)
    write_json(run / 'review_exclusions.json', {key(excluded): {'reason': 'not_skydive', 'note': '', 'rel_path': excluded.name}})

    store = ReviewStore(state)
    for source in (corrected, excluded):
        assert needs_processing(ledger['entries'][key(source)], file_signature(source), fingerprint, store.fingerprint(source))
    untouched = next(s for s in sources if s not in (corrected, excluded))
    assert not needs_processing(ledger['entries'][key(untouched)], file_signature(untouched), fingerprint,
                                store.fingerprint(untouched))

    print(f'\n== reprocess the corrected video ({corrected.name})', flush=True)
    log.clear()
    result, seconds = process(corrected)
    before_clips, after_clips = first[key(corrected)][1], clips_of(result)
    assert any('reviewed labels' in line for line in log), log
    assert not any('Classifying' in line for line in log), 'The model ran again although tracks existed.'
    assert result['run_directory'] == first[key(corrected)][0]['run_directory']
    report['correction'] = {'video': corrected.name, 'clips_before': before_clips, 'clips_after': after_clips,
                            'seconds': round(seconds, 1)}
    print(json.dumps(report['correction']), flush=True)
    assert after_clips and before_clips and abs((after_clips[-1][1] - before_clips[-1][1]) - 3.0) < 1.01, 'Clip end did not move.'

    print(f'\n== reprocess the excluded video ({excluded.name})', flush=True)
    old_paths = [Path(r['clip_path']) for r in csv.DictReader(open(first[key(excluded)][0]['manifests'][0], encoding='utf-8'))]
    result, _ = process(excluded)
    assert clips_of(result) == [], 'An excluded video still has clips.'
    assert not any(p.exists() for p in old_paths), 'Old clips of an excluded video were left behind.'
    report['exclusion'] = {'video': excluded.name, 'clips_removed': len(old_paths)}

    # Render the labeller and the main window.
    from PySide6.QtWidgets import QApplication
    import review as v3_review
    application = QApplication([])
    v3_review.configure_font(application)
    run = build_review_run(state, settings.input_folder)
    window = window_class()(run)
    window.resize(1550, 1000)
    shots = []
    for index in range(len(window.videos)):
        window.video_index = index
        window.load_current_video()
        window.seek_absolute_milliseconds(30_000)
        window.update_comparison_position(30_000)
        for _ in range(20):
            application.processEvents()
            time.sleep(.05)
        path = work / f'labeller_{index + 1}.png'
        window.grab().save(str(path))
        shots.append(str(path))
        assert window.comparison.height() > 150
    window.hide()
    from app.ui.main_window import MainWindow
    main_window = MainWindow()
    for name, edit in main_window.folder_edits.items():
        edit.setText(getattr(settings, name))
    main_window.resize(1040, 960)
    application.processEvents()
    path = work / 'main_window.png'
    main_window.grab().save(str(path))
    shots.append(str(path))
    main_window.hide()
    report['screenshots'] = shots
    (work / 'smoke_report.json').write_text(json.dumps(report, indent=1), encoding='utf-8')
    print('\nPASSED', json.dumps({'videos': [(v['video'], v['processing_seconds'], v.get('agreement_with_human_labels'))
                                             for v in report['videos']]}), flush=True)
    return 0


def read_csv_plain(path):
    with open(path, encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


if __name__ == '__main__':
    sys.exit(main())
