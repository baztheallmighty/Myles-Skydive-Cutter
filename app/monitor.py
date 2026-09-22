"""Polling decisions, ledger persistence, and a single-video processing service."""
from datetime import datetime, timezone
import json
import os
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
        from cutter_v4.engine import probe, refine_360_kind
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


class VideoProcessor:
    """One instance per monitor session keeps YOLO resident across sequential jobs."""
    def __init__(self, settings, runner):
        self.settings = settings
        self.runner = runner
        self.people = PeopleSampler()

    def process(self, source, expected_signature=None, previous_entry=None, moved_from=()):
        """``moved_from``: ledger entries this file may be, if it moved (see app.relocate)."""
        settings, runner = self.settings, self.runner
        before = file_signature(source)
        if expected_signature is not None and before != expected_signature:
            raise RuntimeError('Source changed after being queued; waiting for it to become stable again.')
        runner.check_cancelled()
        runner.report_progress('identify')
        runner.log(f'Checking {source.name}')
        identity = identify_source(source, runner)
        if file_signature(source) != before:
            raise RuntimeError('Source changed while checking it; wait for the copy to finish.')
        relocated_from = None
        move = matching_move(moved_from, identity.content_sha256) if previous_entry is None else None
        if move:
            identity, previous_entry = relocate(settings, source, identity.content_sha256, *move, log=runner.log)
            relocated_from = move[0]
        runner.log(f'Probing {source.name}')
        duration = probe_duration(source, runner)
        runner.video_duration = duration
        runner.report_progress('identify', 1, 1)
        segments, run_directory, agreement, review = [], None, None, ''
        reviewed = None
        ran_model = False
        if settings.phases_enabled:
            from cutter_v4.review import ReviewStore
            store = ReviewStore(state_directory(settings))
            review = store.fingerprint(source)
            reviewed = store.segments_for(source, identity.content_sha256, duration)
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
        if settings.people_enabled:
            runner.report_progress('people')
        media = view_media(source, run_directory) if settings.people_enabled else None
        people = self.people.sample(source, duration, settings, runner, media=media) if settings.people_enabled else []
        runner.report_progress('timeline')
        rows = join_timeline(source, duration, segments, people, settings, agreement)
        runner.check_cancelled()
        if file_signature(source) != before:
            raise RuntimeError('Source changed while processing; outputs were not published.')
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
        manifests = cut_profiles(source, rows, duration, settings, runner, identity) if settings.cut_enabled else []
        runner.check_cancelled()
        if file_signature(source) != before:
            raise RuntimeError('Source changed while cutting; this video is not marked complete.')
        extra = {'relocated_from': relocated_from} if relocated_from else {}
        return dict(csv_path=str(csv_path), manifests=manifests, duration_sec=duration, source_video=str(source),
                    source_id=identity.identifier, source_sha256=identity.content_sha256,
                    output_name=identity.output_name, review_fingerprint=review,
                    labels=REVIEWED_LABELS if reviewed else EXCLUDED_LABELS if reviewed == [] else MODEL_LABELS,
                    ran_model=ran_model,
                    run_directory=str(run_directory) if run_directory else None, **extra)


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
