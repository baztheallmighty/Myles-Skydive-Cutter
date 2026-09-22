"""Cancellable owned subprocesses; all GUI updates are delivered by signals."""
import os
import queue
import subprocess
import threading
import time

from app import PROJECT_ROOT


class Cancelled(RuntimeError):
    pass


class WindowsJob:
    """Kill-on-close ownership, including children of the venv's launcher process.

    Attach while the subprocess is suspended so it cannot create unowned children.
    No process enumeration, taskkill, administrator rights, or external library.
    """
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.SetInformationJobObject.restype = wintypes.BOOL
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL

        class BasicLimits(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                        ('flags', wintypes.DWORD), ('min_working_set', ctypes.c_size_t),
                        ('max_working_set', ctypes.c_size_t), ('active_processes', wintypes.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [('basic', BasicLimits), ('io_counters', ctypes.c_uint64 * 6),
                        ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                        ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t)]

        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def attach_and_resume(self, process):
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        # Popen closes the initial thread handle; resume via the process handle.
        resume = self.ctypes.WinDLL('ntdll').NtResumeProcess
        resume.argtypes = [self.ctypes.c_void_p]
        resume.restype = self.ctypes.c_long
        status = resume(int(process._handle))
        if status < 0:
            raise OSError(f'Could not resume owned subprocess (NTSTATUS {status:#x}).')

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class ProcessRunner:
    def __init__(self, log=lambda message: None, progress=lambda stage, done, total: None):
        self.log = log
        self.progress = progress
        self.video_duration = 0.0
        self.cancelled = threading.Event()

    def check_cancelled(self):
        if self.cancelled.is_set():
            raise Cancelled('Processing cancelled; this video will be retried next session.')

    def report_progress(self, stage, done=0, total=0):
        self.progress(stage, done, total)

    def stop_group(self, process):
        """Stop the child and anything it started. Windows uses a job object; elsewhere, the process group."""
        try:
            if os.name == 'nt':
                process.terminate()
            else:
                import signal
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            process.terminate()

    def run(self, argv, timeout=None, echo=True, on_output=None):
        self.check_cancelled()
        job = WindowsJob() if os.name == 'nt' else None
        # Windows: start suspended with no console, attach to a kill-on-close job, then resume.
        # Elsewhere: its own process group, so stopping this run cannot leave orphans behind.
        creation = {'creationflags': subprocess.CREATE_NO_WINDOW | 0x4} if job else {'start_new_session': True}
        process = None
        try:
            process = subprocess.Popen(argv, cwd=PROJECT_ROOT, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                       errors='replace', **creation,
                                       env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
            if job:
                job.attach_and_resume(process)
        except BaseException:   # including KeyboardInterrupt: an unowned child must never be left running
            if job:
                job.close()
            if process is not None:
                process.kill()
                process.wait()
                process.stdout.close()
            raise
        lines = queue.Queue()

        def read_output():
            try:
                for line in process.stdout:
                    lines.put(line)
            finally:
                lines.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        output = []
        began = time.monotonic()
        try:
            while True:
                self.check_cancelled()
                if timeout and time.monotonic() - began > timeout:
                    raise TimeoutError(f'Command timed out after {timeout}s: {argv[0]}')
                try:
                    line = lines.get(timeout=.1)
                except queue.Empty:
                    continue
                if line is None:
                    break
                output.append(line)
                if on_output:
                    on_output(line.rstrip())
                if echo:
                    self.log(line.rstrip())
            process.wait(timeout=5)
            self.check_cancelled()
            if process.returncode:
                raise RuntimeError(f'Command failed ({process.returncode}): {"".join(output)[-3000:]}')
            return ''.join(output)
        finally:
            if job:
                job.close()  # The kernel terminates this owned process tree only.
            if process.poll() is None:
                if not job:
                    self.stop_group(process)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            reader.join(timeout=2)
            process.stdout.close()
