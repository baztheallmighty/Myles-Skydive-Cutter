"""Keep watching, for hours: videos dripped into a folder, one window, nothing leaking or repeating.

    <package>\\.runtime\\cu128\\python.exe -s -B release\\tests\\soak_test.py --minutes 30 --every 20 VIDEO [VIDEO...]

Copies the given videos into the watched folder at intervals, exactly as a card reader would, and watches the app
process them. It checks the things that only go wrong over time: memory creeping up, a video processed twice, the
window falling behind, or the queue stalling. It does not judge the model's answers.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def memory_megabytes():
    """Working set of this process, without needing psutil.

    The argument types matter: without them ctypes truncates the process handle on 64-bit Python and the call
    quietly returns zero, which makes a leak check that can never fail.
    """
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                    ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                    ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                    ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise OSError(ctypes.get_last_error(), 'could not read this process memory')
    return counters.WorkingSetSize / 1e6


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('videos', nargs='+', type=Path)
    parser.add_argument('--work', type=Path, required=True, help='a folder to watch and cut into')
    parser.add_argument('--minutes', type=float, default=30)
    parser.add_argument('--every', type=float, default=20, help='seconds between arrivals')
    arguments = parser.parse_args()

    from PySide6.QtWidgets import QApplication
    from app.settings import Settings, save_settings
    from app.ui import theme
    from app.ui.main_window import MainWindow

    work = arguments.work.resolve()
    inputs, clips = work / 'input', work / 'clips'
    if work.exists():
        shutil.rmtree(work)
    inputs.mkdir(parents=True)
    clips.mkdir(parents=True)
    save_settings(Settings(input_folder=str(inputs), output_folder=str(clips),
                           csv_folder=str(clips / 'timelines'), keep_watching=True, people_enabled=False))

    application = QApplication([])
    theme.apply(application)
    window = MainWindow()
    window.resize(1500, 1000)
    window.show()
    window.keep_watching.setChecked(True)
    window.start_session(False)

    began = time.monotonic()
    deadline = began + arguments.minutes * 60
    next_arrival = began
    start_memory = memory_megabytes()
    warm_memory = None            # measured once the model is loaded, so loading is not mistaken for a leak
    samples, copied, seen_twice = [], 0, []
    processed_before: dict[str, str] = {}

    while time.monotonic() < deadline:
        application.processEvents()
        time.sleep(.05)
        if time.monotonic() >= next_arrival:
            video = arguments.videos[copied % len(arguments.videos)]
            target = inputs / f'jump{copied:03d}{video.suffix.lower()}'
            shutil.copy2(video, target)
            copied += 1
            next_arrival = time.monotonic() + arguments.every
            print(f'[{time.monotonic() - began:6.0f}s] copied {target.name}', flush=True)
        if len(samples) < (time.monotonic() - began) / 30:
            samples.append(round(memory_megabytes(), 1))
            entries = (window.ledger or {}).get('entries', {}) if getattr(window, 'ledger', None) else {}
            for source_key, entry in entries.items():
                if entry.get('status') != 'success':
                    continue
                stamp = entry.get('processed_utc')
                seen = processed_before.get(source_key)
                # A finished video whose stamp moves on was processed again, which nothing here asked for.
                if seen and stamp and stamp != seen and source_key not in seen_twice:
                    seen_twice.append(source_key)
                processed_before[source_key] = stamp
            if warm_memory is None and len(processed_before) >= 1:
                warm_memory = samples[-1]
            print(f'[{time.monotonic() - began:6.0f}s] memory {samples[-1]:7.1f} MB, '
                  f'{len(entries)} in the ledger, queue {len(window.queue)}', flush=True)

    window.stop_session()
    for _ in range(200):
        application.processEvents()
        time.sleep(.05)

    entries = (window.ledger or {}).get('entries', {})
    finished = sum(1 for entry in entries.values() if entry.get('status') == 'success')
    report = {'copied': copied, 'finished': finished,
              'memory_start_mb': round(start_memory, 1),
              'memory_warm_mb': warm_memory, 'memory_end_mb': round(memory_megabytes(), 1),
              'memory_samples_mb': samples, 'processed_twice': seen_twice,
              'minutes': round((time.monotonic() - began) / 60, 1)}
    # Growth is measured from the first video onwards: loading the model costs a few hundred MB once, which is not
    # a leak. After that, a long run should stay roughly level.
    baseline = warm_memory if warm_memory is not None else start_memory
    report['memory_growth_mb'] = round(report['memory_end_mb'] - baseline, 1)
    report['passed'] = bool(finished >= copied - 2 and not seen_twice and report['memory_growth_mb'] < 300)
    (work / 'soak_report.json').write_text(json.dumps(report, indent=1), encoding='utf-8')
    print(json.dumps(report, indent=1), flush=True)
    print('PASSED' if report['passed'] else 'FAILED', flush=True)
    window.close()
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
