"""Audio windows for the sound model: decode to mono 16 kHz, then 3-second feature windows every second.

Lifted from the V3 pipeline unchanged, because the audio model was trained on exactly these windows. Keeping it
here means the engine no longer pulls in the whole V3 command-line tool to reach one function.
"""
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'v3_poc'))

from _audio_features import SAMPLE_RATE, clip_features  # noqa: E402

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
WINDOW_SECONDS = 3.0
FEATURES = 73


def log(message):
    print(message, flush=True)


def audio_features(source, ffmpeg, directory, offset):
    """(features, window centres, duration). Empty features when the sound is shorter than one window."""
    wav = Path(directory) / 'audio_work.wav'
    try:
        result = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-y', '-i', str(source), '-map', '0:a:0',
                                 '-vn', '-af', 'asetpts=PTS-STARTPTS,aresample=async=1',
                                 '-ac', '1', '-ar', str(SAMPLE_RATE), '-c:a', 'pcm_s16le', str(wav)],
                                capture_output=True, text=True, timeout=3600, creationflags=NO_WINDOW)
        if result.returncode:
            raise RuntimeError('Audio decode failed: ' + result.stderr[-1200:])
        import soundfile
        with soundfile.SoundFile(wav) as stream:
            duration = len(stream) / SAMPLE_RATE
            if duration < WINDOW_SECONDS:
                return np.empty((0, FEATURES), dtype=np.float32), np.array([]), duration
            starts = np.arange(0., duration - WINDOW_SECONDS + 1e-6, 1.)
            rows, last_report = [], time.monotonic()
            for start in starts:
                stream.seek(round(start * SAMPLE_RATE))
                rows.append(clip_features(stream.read(int(WINDOW_SECONDS * SAMPLE_RATE), dtype='float32')))
                if time.monotonic() - last_report > 20:
                    log(f'Audio {Path(source).name}: {len(rows)}/{len(starts)} windows')
                    last_report = time.monotonic()
        return np.stack(rows), starts + WINDOW_SECONDS / 2 + offset, duration
    finally:
        if wav.exists():
            wav.unlink()  # Only this run's known temporary WAV, never source media.
