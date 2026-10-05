"""How busy this machine is, and whether it has room to start another video. No Qt, no extra packages.

"Videos at once: Automatic" asks ``Pacer.may_start`` before each extra video. It only ever answers whether one more
may start: a video that is running is never stopped to make room.
"""
from dataclasses import dataclass
import os
import shutil
import subprocess
import sys
import threading
import time

from app.settings import MAX_PARALLEL_VIDEOS

BUSY_PROCESSOR = 80.0        # percent: above this another video would only take turns with the ones running
BUSY_GRAPHICS = 85.0         # percent
SPARE_MEMORY_GB = 4.0        # left free for the rest of the machine
SPARE_GRAPHICS_MEMORY_GB = 3.0   # one video's models and decoder need about 2 GB
SETTLE_SECONDS = 20.0        # how long a newly started video takes to show its full load
WATCH_SECONDS = 2.0          # how often the load is read while Automatic is deciding
CORES_PER_VIDEO = 4          # decoding and proxy encoding for one video keep about this many cores busy


@dataclass(frozen=True)
class Reading:
    """What could be measured; None for anything this machine cannot report."""
    processor: float | None = None            # percent busy since the last reading
    memory_free_gb: float | None = None
    graphics: float | None = None             # percent busy
    graphics_memory_free_gb: float | None = None


def most_at_once(cores=None):
    """The most videos this machine is ever asked to run side by side."""
    cores = cores or os.cpu_count() or 1
    return max(1, min(MAX_PARALLEL_VIDEOS, cores // CORES_PER_VIDEO))


def may_start(running, reading, limit=None, graphics_wanted=True):
    """(yes or no, why) for starting one more video with ``running`` already going."""
    limit = limit or most_at_once()
    if running == 0:
        return True, 'nothing is running'
    if running >= limit:
        return False, f'{running} is the most this processor is given'
    if reading.processor is None:
        return False, 'waiting for a reading of how busy the processor is'
    if reading.processor > BUSY_PROCESSOR:
        return False, f'the processor is {reading.processor:.0f}% busy'
    if reading.memory_free_gb is not None and reading.memory_free_gb < SPARE_MEMORY_GB:
        return False, f'only {reading.memory_free_gb:.1f} GB of memory is free'
    if graphics_wanted:
        if reading.graphics is None or reading.graphics_memory_free_gb is None:
            # Nothing to steer by (no NVIDIA card, or a Mac): one extra video at most.
            return (running < 2), 'the graphics card cannot be measured, so two is the most'
        if reading.graphics > BUSY_GRAPHICS:
            return False, f'the graphics card is {reading.graphics:.0f}% busy'
        if reading.graphics_memory_free_gb < SPARE_GRAPHICS_MEMORY_GB:
            return False, f'only {reading.graphics_memory_free_gb:.1f} GB of graphics memory is free'
    return True, 'the processor, memory and graphics card all have room'


class Pacer:
    """Decides when Automatic adds a video: room on the machine, and time for the last one to show its load."""

    def __init__(self, machine=None, limit=None, graphics_wanted=True, clock=time.monotonic):
        """With no ``machine`` given, this one is read on a thread of its own every couple of seconds, because
        asking the graphics card how busy it is means running a program, and the window must never wait for one.
        A ``machine`` handed in (the tests do) is read on the spot."""
        self.watching = machine is None
        self.machine = machine or Machine()
        self.limit = limit or most_at_once()
        self.graphics_wanted = graphics_wanted
        self.clock = clock
        self.last_start = None
        self.reason = ''
        self.closed = threading.Event()
        self.latest = Reading()
        if self.watching:
            threading.Thread(target=self.watch, daemon=True).start()
        else:
            self.machine.read()   # the first processor reading needs something to compare with

    def watch(self):
        self.machine.read()
        while not self.closed.wait(WATCH_SECONDS):
            self.latest = self.machine.read()

    def close(self):
        """Stop reading the load; the run that needed it is over."""
        self.closed.set()

    def started(self):
        self.last_start = self.clock()

    def may_start(self, running):
        if running and self.last_start is not None and self.clock() - self.last_start < SETTLE_SECONDS:
            self.reason = 'the last video started is still getting going'
            return False
        reading = self.latest if self.watching else self.machine.read()
        answer, self.reason = may_start(running, reading, self.limit, self.graphics_wanted)
        return answer


class Machine:
    """Reads the load from the operating system and, for an NVIDIA card, from its own tool."""

    def __init__(self):
        self.previous = None
        self.nvidia = shutil.which('nvidia-smi')

    def read(self):
        graphics, graphics_free = self.graphics()
        return Reading(self.processor(), self.memory_free_gb(), graphics, graphics_free)

    def processor(self):
        if sys.platform != 'win32':
            try:   # the one-minute load average, as a share of the cores
                return min(100.0, 100.0 * os.getloadavg()[0] / (os.cpu_count() or 1))
            except (OSError, AttributeError):
                return None
        import ctypes
        from ctypes import wintypes
        idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        now = tuple((t.dwHighDateTime << 32) | t.dwLowDateTime for t in (idle, kernel, user))
        before, self.previous = self.previous, now
        if before is None:
            return None
        idle_time = now[0] - before[0]
        total = (now[1] - before[1]) + (now[2] - before[2])   # kernel time includes idle time
        return max(0.0, min(100.0, 100.0 * (1 - idle_time / total))) if total > 0 else None

    @staticmethod
    def memory_free_gb():
        try:
            if sys.platform == 'win32':
                import ctypes

                class Status(ctypes.Structure):
                    _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                        (name, ctypes.c_ulonglong) for name in ('total', 'available', 'total_page', 'available_page',
                                                                'total_virtual', 'available_virtual', 'extended')]
                status = Status()
                status.length = ctypes.sizeof(Status)
                if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                    return None
                return status.available / 2 ** 30
            if sys.platform == 'darwin':
                output = subprocess.run(['vm_stat'], capture_output=True, text=True, timeout=5).stdout
                page = int(output.split('page size of')[1].split()[0])
                pages = {line.split(':')[0]: int(line.split(':')[1].strip().rstrip('.'))
                         for line in output.splitlines()[1:] if ':' in line}
                return (pages.get('Pages free', 0) + pages.get('Pages inactive', 0)) * page / 2 ** 30
            with open('/proc/meminfo', encoding='ascii') as handle:
                for line in handle:
                    if line.startswith('MemAvailable:'):
                        return int(line.split()[1]) / 2 ** 20
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            pass
        return None

    def graphics(self):
        """(percent busy, GB free) for the first NVIDIA card, or (None, None)."""
        if not self.nvidia:
            return None, None
        try:
            output = subprocess.run([self.nvidia, '--query-gpu=utilization.gpu,memory.used,memory.total',
                                     '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=10,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
            busy, used, total = (float(value) for value in output.splitlines()[0].split(','))
            return busy, (total - used) / 1024
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            return None, None
