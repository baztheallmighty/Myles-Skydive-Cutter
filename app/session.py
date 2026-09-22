"""One processing run over a folder: the ledger, the queue, and what counts as done. No Qt.

The window drives a session: it calls ``scan`` on its timer, runs ``next_job`` on a worker thread, and hands the
outcome back to ``record``. Everything that decides what gets processed, and what is remembered afterwards, lives
here, so the run loop can be tested with no window, no timer and no thread.
"""
from collections import deque

from app.monitor import (VideoProcessor, existing_complete, file_signature, ledger_entry, load_ledger,
                         review_fingerprints, save_ledger, scan_folder, stable_candidates)
from app.relocate import moved_candidates, rebase_entries
from app.runtime import ProcessRunner
from app.settings import accepted_fingerprints, state_directory, validate_settings
from v3_poc.common import RunLock, key


class ProcessingSession:
    """Holds the destination's lock from start to ``close``, so two sessions never write one ledger."""

    def __init__(self, settings, existing_only=False, only=None, processor_factory=VideoProcessor, runner=None):
        """``only``: process just these files now (re-cut after a review), then stop."""
        validate_settings(settings, require_folders=True)
        self.settings = settings
        self.ledger_path = state_directory(settings) / 'ledger.json'
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = RunLock(self.ledger_path.parent, 'monitor.lock')
        self.lock.__enter__()
        try:
            self.ledger = load_ledger(self.ledger_path)
            # A Clips folder that moved as a whole still points its records at the old place.
            rebase_entries(self.ledger['entries'], self.ledger_path.parent, settings.csv_folder)
        except BaseException:
            self.close()
            raise
        # The current fingerprint first; older formats still count as done, so upgrades reprocess nothing.
        self.fingerprint = accepted_fingerprints(settings)
        self.processor = processor_factory(settings, runner or ProcessRunner())
        self.previous = {}
        self.attempted = {}
        self.queue = deque()
        self.snapshot = {}
        self.reviews = {}
        self.unreadable = []   # (path, reason) the last look could not read
        self.existing_only = existing_only or bool(only)
        self.initial_keys = None
        if only:
            # Seen once already, so they count as stable and are queued on the first check.
            self.initial_keys = {key(path) for path in only}
            self.previous = {key(path): file_signature(path) for path in only}

    # --- finding work -------------------------------------------------------------------------------------------
    def scan(self, busy=None):
        """Look at the folder once. Returns the (path, signature) pairs newly queued.

        A file is queued once it has kept the same size and time across two looks and still needs processing.
        ``busy`` is the video being processed now, which is never queued twice.
        """
        problems = []
        files = scan_folder(self.settings, problems)
        self.unreadable = problems
        if self.initial_keys is None:
            self.initial_keys = set(files)
        if self.existing_only:
            files = {k: v for k, v in files.items() if k in self.initial_keys}
        snapshot = {k: signature for k, (_, signature) in files.items()}
        pending = {key(path) for path, _ in self.queue}
        if busy is not None:
            pending.add(key(busy))
        pending.update(k for k, signature in self.attempted.items() if snapshot.get(k) == signature)
        self.reviews = review_fingerprints(self.settings, snapshot) if self.settings.phases_enabled else {}
        ready = stable_candidates(self.previous, snapshot, self.ledger['entries'], self.fingerprint, pending,
                                  self.reviews)
        queued = [files[k] for k in ready]
        self.queue.extend(queued)
        self.previous = self.snapshot = snapshot
        return queued

    def finished(self):
        """True when only existing files were asked for and every one of them has been dealt with."""
        return self.existing_only and not self.queue and existing_complete(
            self.snapshot, self.ledger['entries'], self.fingerprint, self.attempted, self.reviews)

    # --- doing it -----------------------------------------------------------------------------------------------
    def next_job(self):
        """(source, signature, previous ledger entry, moved-from candidates) for the next video, or None."""
        if not self.queue:
            return None
        source, signature = self.queue.popleft()
        previous = self.ledger['entries'].get(key(source))
        # A video never seen at this path may be one that moved; the processor decides once it knows the checksum.
        moved = () if previous else moved_candidates(self.ledger['entries'], source)
        return source, signature, previous, moved

    def process(self, job):
        """Run one job here and now (the window runs it on a thread instead). Returns (status, result)."""
        from app.runtime import Cancelled
        source, signature, previous, moved = job
        try:
            return 'success', self.processor.process(source, signature, previous, moved_from=moved)
        except Cancelled as exc:
            return 'cancelled', {'error': str(exc)}
        except Exception as exc:  # noqa: BLE001 - one video's failure is recorded, and the run carries on
            return 'failed', {'error': f'{type(exc).__name__}: {exc}'}

    def record(self, source, signature, status, result):
        """Remember how a video went. Returns the status as recorded; raises if the ledger cannot be saved."""
        self.attempted[key(source)] = signature
        if status == 'success' and file_signature(source) != signature:
            status = 'failed'   # it changed while being processed: its outputs describe an older file
        self.ledger['entries'][key(source)] = ledger_entry(signature, self.fingerprint[0], status, **result)
        if status == 'success' and result.get('relocated_from'):
            self.ledger['entries'].pop(result['relocated_from'], None)
        save_ledger(self.ledger_path, self.ledger)
        return status

    def forget(self, source_key):
        """Process this video again, after the ones already waiting."""
        self.ledger['entries'].pop(source_key, None)
        save_ledger(self.ledger_path, self.ledger)
        self.attempted.pop(source_key, None)
        self.previous.pop(source_key, None)

    def requeue_first(self, source):
        """Process this video next, whatever happened to it already (a review asked for a re-cut)."""
        source_key = key(source)
        waiting = [item for item in self.queue if key(item[0]) != source_key]
        self.queue.clear()
        self.queue.extend(waiting)
        self.attempted.pop(source_key, None)
        self.queue.appendleft((source, file_signature(source)))

    def drain(self):
        """Stop taking work. Returns how many queued videos were left for next time."""
        left = len(self.queue)
        self.queue.clear()
        return left

    def close(self):
        if self.lock is not None:
            self.lock.__exit__(None, None, None)
            self.lock = None

    def run(self, cancelled=lambda: False):
        """Everything that is ready, one after another, until nothing is left. For tests and scripts."""
        outcomes = []
        while not cancelled():
            if not self.queue:
                before = dict(self.previous)
                self.scan()
                # A file is ready only after two identical looks, so stop only when a look changed nothing.
                if not self.queue and self.previous == before:
                    break
                if not self.queue:
                    continue
            job = self.next_job()
            status, result = self.process(job)
            outcomes.append((job[0], self.record(job[0], job[1], status, result), result))
        return outcomes
