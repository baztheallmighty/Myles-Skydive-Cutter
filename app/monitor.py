"""Polling decisions, ledger persistence, and a single-video processing service."""
from datetime import datetime, timezone
import json
import os
import threading
import time
from pathlib import Path

from app.classifiers import classify_phases, get_classifier
from app.cutting import cut_profiles
from app.ffmpeg_tools import probe_duration
from app.people import PeopleSampler
from app.relocate import is_key, matching_move, relocate
from app.outputs import identify_source, reserve_identity
from app.runs import engine_result, has_result
from app.settings import settings_fingerprint, state_directory
from app.timeline import join_timeline, write_atomic_csv
from v3_poc.common import EXTENSIONS, key, write_json


MODEL_LABELS, REVIEWED_LABELS, EXCLUDED_LABELS = 'model', 'reviewed', 'excluded'
# Several videos may be processed side by side. What they share on disk (the name registry, a moved video's records)
# is touched by one of them at a time.
PUBLISH_LOCK = threading.Lock()
STAGE_NAMES = {'identify': 'checking', 'people': 'reading the video and counting people', 'phases': 'phases',
               'timeline': 'timeline', 'cutting': 'cutting'}


def file_signature(path):
    stat = Path(path).stat()
    return (stat.st_size, stat.st_mtime_ns)


def needs_processing(entry, signature, fingerprint, review=''):
    """``review`` changes when you mark a video reviewed, edit a reviewed video, or exclude it.

    ``fingerprint`` is one fingerprint or several accepted ones (see ``settings.accepted_fingerprints``).
    """
    accepted = {fingerprint} if isinstance(fingerprint, str) else set(fingerprint)
    return not (entry and entry.get('status') == 'success'
                and same_signature((entry.get('size'), entry.get('mtime_ns')), signature)
                and entry.get('settings_fingerprint') in accepted
                and entry.get('review_fingerprint', '') == (review or ''))


# FAT32 keeps modification times in local time: a card or drive read after a daylight-saving change, or on a machine in
# another time zone, reports every file a whole number of hours (sometimes half hours) out. Cameras never edit a
# finished recording in place, so a file of the same size whose time moved by exactly that much is the same file.
# Any other difference, however small, is a changed file.
TIME_SLACK_NS = 1_000_000_000   # rounding by the filesystem driver around the shifted time
HALF_HOUR_NS = 1800 * 1_000_000_000
MOST_ZONE_HOURS = 14


def same_signature(recorded, current):
    """(size, mtime_ns) pairs that describe the same, unchanged file."""
    if recorded == tuple(current):
        return True
    try:
        (size, recorded_ns), (current_size, current_ns) = recorded, current
        if size != current_size or recorded_ns is None:
            return False
        shift = abs(int(current_ns) - int(recorded_ns))
    except (TypeError, ValueError):
        return False
    steps = round(shift / HALF_HOUR_NS)
    return 0 < steps <= 2 * MOST_ZONE_HOURS and abs(shift - steps * HALF_HOUR_NS) <= TIME_SLACK_NS


def stable_candidates(previous, current, entries, fingerprint, pending=(), reviews=None):
    """Snapshots map canonical path keys to (size, mtime_ns). No I/O."""
    reviews = reviews or {}
    return sorted(k for k, signature in current.items()
                  if signature[0] > 0 and previous.get(k) == signature and k not in pending
                  and needs_processing(entries.get(k), signature, fingerprint, reviews.get(k, '')))


def existing_complete(snapshot, entries, fingerprint, attempted, reviews=None):
    reviews = reviews or {}
    return all(attempted.get(k) == signature
               or not needs_processing(entries.get(k), signature, fingerprint, reviews.get(k, ''))
               for k, signature in snapshot.items())


def view_media(source, run_directory=None):
    """What kind of picture this file holds, so people are counted through the same view as the phases.

    The engine already worked it out when it classified the video; only a reused or phase-free run has to ask again.
    """
    media = (engine_result(run_directory) or {}).get('media')
    if media and media.get('kind'):
        return media
    try:
        from app.ffmpeg_tools import find_executable
        from cutter_v4.media import probe, refine_360_kind
        return refine_360_kind(Path(source), find_executable('ffmpeg'), probe(Path(source), find_executable('ffprobe')))
    except Exception:  # noqa: BLE001 - people counting falls back to the whole frame, as before
        return None


def review_fingerprints(settings, keys):
    """Per-video review state from the labeller, keyed like scan_folder. Empty when nothing was reviewed."""
    from cutter_v4.review import ReviewStore
    try:
        store = ReviewStore(state_directory(settings))
    except (OSError, ValueError):
        return {}
    return {k: store.fingerprint_key(k) for k in keys}


# Folders that operating systems keep on cards and drives, never footage.
SYSTEM_FOLDERS = {'$recycle.bin', 'system volume information', '.trashes', '.trash', '.spotlight-v100',
                  '.fseventsd', '.temporaryitems', '.documentrevisions-v100', '@eadir', '#recycle'}


def hidden_entry(relative_parts):
    """True for anything a camera did not record: dot files, and system folders.

    macOS writes a ``._NAME.MP4`` beside every file it copies to an exFAT card or a network share. It has the video's
    name and extension but holds only a few kilobytes of Finder metadata, and fails every probe.
    """
    return any(part.startswith('.') or part.casefold() in SYSTEM_FOLDERS for part in relative_parts)


def scan_folder(settings, problems=None):
    """{key: (path, (size, mtime_ns))} for every video under the input folder.

    ``problems``, if given, collects (path, reason) for what could not be read at all: a folder deeper than Windows'
    260-character limit, one the account may not open. Without that, such videos would simply never appear.
    """
    destinations = [settings.csv_folder] + ([settings.output_folder] if settings.cut_enabled else [])
    excluded = [Path(folder).resolve() for folder in destinations if folder]
    paths = {}
    root = Path(settings.input_folder)

    def unreadable(path, error):
        if problems is not None:
            problems.append((str(path), unreadable_reason(path, error)))

    for directory, folders, files in os.walk(root, onerror=lambda error: unreadable(error.filename or root, error)):
        folders[:] = sorted(name for name in folders if not hidden_entry((name,)))
        for name in sorted(files):
            if hidden_entry((name,)) or Path(name).suffix.lower() not in EXTENSIONS:
                continue
            candidate = Path(directory) / name
            try:
                path = candidate.resolve()
                if any(path.is_relative_to(folder) for folder in excluded):
                    continue
                paths[key(path)] = (path, file_signature(path))
            except FileNotFoundError:
                continue  # A copy/rename may race the scan; retry next poll.
            except OSError as error:
                unreadable(candidate, error)
    return paths


def unreadable_reason(path, error):
    if os.name == 'nt' and (getattr(error, 'winerror', None) == 206 or len(str(path)) >= 260):
        return ('its path is longer than the 260 characters Windows allows. Move it to a shallower folder, or switch '
                'on long paths in Windows')
    if isinstance(error, PermissionError):
        return 'this account is not allowed to open it'
    return getattr(error, 'strerror', None) or str(error)


def load_ledger(path):
    path = Path(path)
    if not path.exists():
        return {'schema_version': 1, 'entries': {}}
    value = json.loads(path.read_text(encoding='utf-8'))
    if value.get('schema_version') != 1 or not isinstance(value.get('entries'), dict):
        raise ValueError(f'Unsupported or damaged ledger: {path}')
    return value


def ledger_entry(signature, fingerprint, status, **extra):
    return dict(size=signature[0], mtime_ns=signature[1], settings_fingerprint=fingerprint,
                completed_utc=datetime.now(timezone.utc).isoformat(), status=status, **extra)


class Identifying:
    """A file's checksum, worked out on a thread of its own while the rest of that video's work goes on.

    Reading a whole recording to checksum it takes a second on a fast drive and a quarter of a minute on a hard disk.
    For a video with nothing on record (never processed, never reviewed, not a moved copy of one that was) nothing
    needs the checksum until the results are saved, so it need not be waited for first.
    """

    def __init__(self, source, runner):
        self.runner, self.abandoned, self.outcome = runner, False, {}
        self.thread = threading.Thread(target=self.work, args=(source,), daemon=True)
        self.thread.start()

    def work(self, source):
        try:
            self.outcome['identity'] = identify_source(source, self)
        except BaseException as exc:  # noqa: BLE001 - handed to whoever asks for the result
            self.outcome['error'] = exc

    # What identify_source asks of a runner: a way to stop, and somewhere to say how far it has got (nowhere, here).
    def check_cancelled(self):
        if self.abandoned:
            raise RuntimeError('The video was given up on before its checksum was finished.')
        self.runner.check_cancelled()

    def report_progress(self, *_):
        pass

    def result(self):
        self.thread.join()
        if 'error' in self.outcome:
            raise self.outcome['error']
        return self.outcome['identity']

    def abandon(self):
        self.abandoned = True


class VideoProcessor:
    """One instance per monitor session keeps YOLO resident across sequential jobs."""
    def __init__(self, settings, runner):
        self.settings = settings
        self.runner = runner
        self.people = PeopleSampler()
        self.identifying = None

    def process(self, source, expected_signature=None, previous_entry=None, moved_from=()):
        """``moved_from``: ledger entries this file may be, if it moved (see app.relocate)."""
        self.identifying = None
        try:
            return self.process_one(source, expected_signature, previous_entry, moved_from)
        finally:
            if self.identifying is not None:
                self.identifying.abandon()   # a video that failed part-way stops reading its file

    def process_one(self, source, expected_signature, previous_entry, moved_from):
        settings, runner = self.settings, self.runner
        stages, mark = {}, time.monotonic()

        def lap(name):
            nonlocal mark
            now = time.monotonic()
            stages[name] = round(stages.get(name, 0) + now - mark, 1)
            mark = now
        before = file_signature(source)
        if expected_signature is not None and before != expected_signature:
            raise RuntimeError('Source changed after being queued; waiting for it to become stable again.')
        runner.check_cancelled()
        runner.report_progress('identify')
        runner.log(f'Checking {source.name}')
        store = None
        if settings.phases_enabled:
            from cutter_v4.review import ReviewStore
            store = ReviewStore(state_directory(settings))
        # With nothing on record for this file, its checksum decides nothing until the results are saved.
        nothing_on_record = previous_entry is None and not moved_from and not (store and store.fingerprint(source))
        if nothing_on_record:
            self.identifying, identity = Identifying(source, runner), None
        else:
            identity = identify_source(source, runner)
            if file_signature(source) != before:
                raise RuntimeError('Source changed while checking it; wait for the copy to finish.')
        relocated_from = None
        move = matching_move(moved_from, identity.content_sha256) if previous_entry is None and identity else None
        if move:
            with PUBLISH_LOCK:
                identity, previous_entry = relocate(settings, source, identity.content_sha256, *move, log=runner.log)
            relocated_from = move[0]
            if store is not None:   # the move brought the video's reviews with it: read them from their new place
                store = ReviewStore(state_directory(settings))
        runner.log(f'Probing {source.name}')
        duration = probe_duration(source, runner)
        runner.video_duration = duration
        runner.report_progress('identify', 1, 1)
        lap('identify')
        segments, run_directory, agreement, review = [], None, None, ''
        reviewed = None
        ran_model = False
        people = None
        if settings.phases_enabled:
            review = store.fingerprint(source)
            reviewed = store.segments_for(source, identity.content_sha256, duration) if identity else None
            previous_run = (previous_entry or {}).get('run_directory')
            has_tracks = has_result(previous_run)
            reusable = has_tracks and reusable_result(previous_run, previous_entry, identity, settings)
            if reviewed is None and reusable:
                # Same file, same model: its answer cannot change, so profile or review changes skip the model.
                runner.report_progress('phases')
                runner.log('Reusing this video\'s phases from the last run (same file, same model).')
                segments, duration, agreement = reusable
                run_directory = previous_run
            elif reviewed is None or not has_tracks:
                # The model runs whenever there are no labeller tracks for this video yet.
                classifier = get_classifier(settings.phase_classifier)
                if duration < classifier.minimum_duration:
                    raise ValueError(f'{classifier.display_name} needs videos at least {classifier.minimum_duration:g} seconds long.')
                people = saved_people(previous_entry, identity, settings, duration) if settings.people_enabled else None
                if people is not None:
                    runner.log('Reusing the people already counted for this video (same file, same detector).')
                if settings.people_enabled and classifier.prepare and people is None:
                    # One read of the picture for both: the people counter looks at it and writes the model's proxy.
                    # The classifier is started at the same moment, so its models load and the sound is analysed
                    # while the picture is still being read; it picks the proxy up when the read has written it.
                    prepared = classifier.prepare(source, settings)
                    started = {}

                    def classify_alongside():
                        try:
                            started['result'] = classify_phases(source, settings, runner, prepared=prepared)
                        except BaseException as exc:  # noqa: BLE001 - handed to the thread that asked
                            started['error'] = exc
                    alongside = threading.Thread(target=classify_alongside, daemon=True)
                    runner.log('Reading the video: counting people, and classifying jump phases alongside…')
                    runner.report_progress('people')
                    alongside.start()
                    try:
                        people = self.people.sample(source, duration, settings, runner, proxy=prepared / 'proxy.mp4')
                    except BaseException:
                        (prepared / 'proxy.failed').write_text('', encoding='utf-8')   # tells the classifier to stop
                        alongside.join()
                        (prepared / 'proxy.mp4').unlink(missing_ok=True)
                        raise
                    lap('people')
                    runner.report_progress('phases')
                    alongside.join()
                    if 'error' in started:
                        raise started['error']
                    segments, duration, run_directory, agreement = started['result']
                else:
                    runner.log('Classifying jump phases…')
                    runner.report_progress('phases')
                    segments, duration, run_directory, agreement = classify_phases(source, settings, runner)
                ran_model = True
            else:
                run_directory = previous_run
            if reviewed is not None:
                # Your labels from the labeller replace the model for this exact file.
                if reviewed:
                    runner.log('Using your reviewed labels for this video.')
                    segments, agreement = reviewed, None
                else:
                    runner.log('Marked "not skydiving" in the labeller: no clips.')
                    segments, agreement = [{'start_sec': 0.0, 'end_sec': duration, 'phase': 'unknown',
                                            'mean_model_probability': None}], None
            runner.report_progress('phases', 1, 1)
            lap('phases')
        if settings.people_enabled and people is None:
            runner.report_progress('people')
            people = saved_people(previous_entry, identity, settings, duration)
            if people is not None:
                runner.log('Reusing the people already counted for this video (same file, same detector).')
            else:
                people = self.people.sample(source, duration, settings, runner, media=view_media(source, run_directory))
            lap('people')
        if identity is None:
            identity = self.identifying.result()
            lap('identify')
        runner.report_progress('timeline')
        rows = join_timeline(source, duration, segments, people or [], settings, agreement)
        runner.check_cancelled()
        if file_signature(source) != before:
            raise RuntimeError('Source changed while processing; outputs were not published.')
        with PUBLISH_LOCK:
            reserve_identity(settings.csv_folder, identity)
            csv_path = Path(settings.csv_folder) / f'{identity.output_name}.timeline.csv'
            # A later session may contain a new source with a stem previously used by another video.
            if csv_path.exists():
                import csv
                with csv_path.open(encoding='utf-8', newline='') as stream:
                    first = next(csv.DictReader(stream), None)
                if first and key(first['source_video']) != key(source) and not (
                        relocated_from and is_key(first['source_video'], relocated_from)):
                    raise ValueError(f'CSV name collision with another source: {csv_path}')
            write_atomic_csv(csv_path, rows)
        runner.log(f'Timeline: {csv_path} ({len(rows)} rows)')
        runner.report_progress('timeline', 1, 1)
        lap('timeline')
        manifests = cut_profiles(source, rows, duration, settings, runner, identity) if settings.cut_enabled else []
        runner.check_cancelled()
        if file_signature(source) != before:
            raise RuntimeError('Source changed while cutting; this video is not marked complete.')
        lap('cutting')
        engine = ((engine_result(run_directory) or {}).get('stage_seconds') if ran_model else None) or {}
        inside = (' (inside phases: ' + ', '.join(f'{name.replace("_", " ")} {seconds:g} s'
                                                 for name, seconds in engine.items()) + ')') if engine else ''
        runner.log('Time taken: ' + ', '.join(f'{STAGE_NAMES[name]} {seconds:g} s'
                                              for name, seconds in stages.items() if seconds >= .1) + inside)
        extra = {'relocated_from': relocated_from} if relocated_from else {}
        return dict(csv_path=str(csv_path), manifests=manifests, duration_sec=duration, source_video=str(source),
                    source_id=identity.identifier, source_sha256=identity.content_sha256,
                    output_name=identity.output_name, review_fingerprint=review,
                    labels=REVIEWED_LABELS if reviewed else EXCLUDED_LABELS if reviewed == [] else MODEL_LABELS,
                    ran_model=ran_model, stage_seconds={**stages, 'engine': engine},
                    people_fingerprint=people_fingerprint(settings) if settings.people_enabled else '',
                    run_directory=str(run_directory) if run_directory else None, **extra)


PEOPLE_READER = 2   # goes up when the way frames are picked or sized for the detector changes


def people_fingerprint(settings):
    """Everything that decides the people counted in a given file. The same fingerprint means the same counts."""
    from v3_poc.common import digest
    return digest({'reader': PEOPLE_READER, 'sample_fps': settings.sample_fps,
                   'confidence': settings.detection_confidence, 'view': settings.view_mode,
                   'detector': Path(settings.yolo_model).name.casefold() if settings.yolo_model else ''})


def saved_people(previous_entry, identity, settings, duration):
    """The people already counted for this exact file with these exact settings, read back from its timeline.

    Changing a profile changes what is kept, not who is in the picture, so a re-cut has no need to read the video
    again. Anything that does not line up exactly (another file, another detector, a timeline that was edited or
    is missing rows) gives None, and the people are counted afresh.
    """
    import csv
    from app.timeline import PER_VIEW_FIELDS, PERSON_FIELDS, canonical_grid
    try:
        if (not previous_entry or previous_entry.get('status') != 'success'
                or previous_entry.get('source_sha256') != identity.content_sha256
                or previous_entry.get('people_fingerprint') != people_fingerprint(settings)):
            return None
        with open(previous_entry['csv_path'], encoding='utf-8', newline='') as stream:
            rows = list(csv.DictReader(stream))
        grid = canonical_grid(duration, settings.sample_fps)
        if len(rows) != len(grid):
            return None
        people = []
        for t, row in zip(grid, rows):
            if abs(float(row['time_sec']) - t) > 1e-6:
                return None
            entry = {'time_sec': t, 'person_count': int(float(row['person_count'])),
                     **{name: float(row[name]) for name in PERSON_FIELDS if name != 'person_count'}}
            for name in PER_VIEW_FIELDS:
                if row.get(name) not in (None, '', 'NA'):
                    entry[name] = float(row[name]) if 'area' in name else int(float(row[name]))
            people.append(entry)
        return people
    except (OSError, KeyError, TypeError, ValueError):
        return None


def reusable_result(run_directory, previous_entry, identity, settings):
    """(final segments, duration, agreement) from the last run when it is still valid for this file, else None."""
    try:
        result = engine_result(run_directory) or {}
        classifier = get_classifier(settings.phase_classifier)
        if (previous_entry.get('status') != 'success' or previous_entry.get('source_sha256') != identity.content_sha256
                or result.get('engine_revision') != classifier.revision or not result['tracks'].get('final')):
            return None
        return result['tracks']['final'], float(result['duration_sec']), result.get('agreement')
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_ledger(path, ledger):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    write_json(path, ledger)
