"""A rough time estimate for the queue, from how fast this PC has processed video so far. Qt-free."""
import json
import math
import queue
import subprocess
import threading
from pathlib import Path

ALPHA = 0.3   # weight of the newest measurement in the running average


class SpeedStore:
    """Processing seconds per second of video on this PC, averaged across sessions."""

    def __init__(self, path):
        self.path = Path(path)
        self.rate = None
        self.samples = 0
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            rate = float(data['seconds_per_video_second'])
            if math.isfinite(rate) and rate > 0:
                self.rate, self.samples = rate, int(data.get('samples', 1))
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def update(self, elapsed_seconds, video_seconds):
        if not video_seconds or video_seconds <= 0 or elapsed_seconds <= 0:
            return
        sample = elapsed_seconds / video_seconds
        self.rate = sample if self.rate is None else (1 - ALPHA) * self.rate + ALPHA * sample
        self.samples += 1
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({'seconds_per_video_second': round(self.rate, 4),
                                             'samples': self.samples}), encoding='utf-8')
        except OSError:
            pass

    def remaining_seconds(self, queued_durations, current_duration=None, current_elapsed=0.0):
        """None until at least one video has been timed, or if a queued video's length is unknown."""
        if self.rate is None or any(d is None for d in queued_durations):
            return None
        total = sum(queued_durations) * self.rate
        if current_duration:
            total += max(0.0, current_duration * self.rate - current_elapsed)
        return total


def describe(seconds):
    if seconds is None:
        return ''
    if seconds < 60:
        return 'under a minute left'
    minutes = round(seconds / 60)
    if minutes < 60:
        return f'about {minutes} min left'
    return f'about {minutes // 60} h {minutes % 60:02d} min left'


def video_duration(path, ffprobe):
    """Length of a queued video, for the estimate only. None if it cannot be read quickly."""
    try:
        output = subprocess.run([ffprobe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(path)],
                                capture_output=True, text=True, timeout=15,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
        value = float(json.loads(output)['format']['duration'])
        return value if math.isfinite(value) and value > 0 else None
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return None


class DurationProber:
    """Measures queued videos' lengths on a background thread, so a large batch never freezes the window."""

    def __init__(self, ffprobe):
        self.ffprobe = ffprobe
        self.durations = {}
        self.requests = queue.Queue()
        threading.Thread(target=self.work, daemon=True).start()

    def request(self, source_key, path):
        if source_key not in self.durations:
            self.durations[source_key] = None
            self.requests.put((source_key, path))

    def work(self):
        while True:
            source_key, path = self.requests.get()
            self.durations[source_key] = video_duration(path, self.ffprobe)

    def get(self, source_key):
        return self.durations.get(source_key)
