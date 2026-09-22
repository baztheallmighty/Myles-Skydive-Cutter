"""Videos and folders that moved: find what was already done for them, and point it at the new place.

A library is keyed by where its files are. When a drive comes back as another letter, a folder is renamed, or the
same library is opened on a Mac after a PC, every path changes while every file stays the same. Without this, each
video would be classified again, lose its reviewed labels, and be cut a second time under a new name.

A video counts as moved only when all of these hold: the ledger has a finished entry with the same file name and the
same content checksum, and nothing exists any longer at that entry's old path. Then its phases, its reviews and its
clip names carry over, and the files that record them are rewritten to the new path.
"""
import csv
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil

from app.outputs import SourceIdentity
from v3_poc.common import FIELDS, RunLock, key, read_csv, write_csv, write_json


def pure(path):
    """A path string parsed the way the machine that wrote it would, so a Windows path reads right on a Mac."""
    text = str(path)
    return PureWindowsPath(text) if '\\' in text or (len(text) > 1 and text[1] == ':') else PurePosixPath(text)


def rebased(path, anchor, new_parent):
    """``path`` moved under ``new_parent`` from its last ``anchor`` component on, or None when it has no anchor.

    ``E:/Clips/_state/runs/x`` with anchor ``_state`` and new parent ``G:/Clips`` gives ``G:/Clips/_state/runs/x``.
    """
    parts = pure(path).parts
    for index in range(len(parts) - 1, -1, -1):
        if parts[index].casefold() == anchor.casefold():
            return Path(new_parent).joinpath(*parts[index:])
    return None


def located(path, anchor, new_parent):
    """Where a recorded state file is now: where it was, else the same place under the moved folder."""
    if not path:
        return path
    if Path(path).exists():
        return str(path)
    moved = rebased(path, anchor, new_parent)
    return str(moved) if moved is not None and moved.exists() else str(path)


def rebase_entries(entries, state_directory, csv_folder=''):
    """Ledger entries with their recorded paths repaired after the clip or CSV folder moved. In place; returns it.

    Paths that still exist, and paths with nowhere better to point, are left exactly as they were.
    """
    output_root = Path(state_directory).parent
    for entry in entries.values():
        if not isinstance(entry, dict):
            continue
        if entry.get('run_directory'):
            entry['run_directory'] = located(entry['run_directory'], '_state', output_root)
        if entry.get('manifests'):
            entry['manifests'] = [located(m, '_manifests', output_root) for m in entry['manifests']]
        csv_path = entry.get('csv_path')
        if csv_path and csv_folder and not Path(csv_path).exists():
            candidate = Path(csv_folder) / pure(csv_path).name
            if candidate.exists():
                entry['csv_path'] = str(candidate)
    return entries


def moved_candidates(entries, source):
    """Finished ledger entries that could be this file before it moved. Cheap: no file is read."""
    new_key = key(source)
    name = Path(new_key).name
    found = []
    for old_key, entry in entries.items():
        if (old_key == new_key or not isinstance(entry, dict) or entry.get('status') != 'success'
                or not entry.get('source_sha256') or not entry.get('output_name') or not entry.get('source_id')
                or pure(old_key).name != name):
            continue
        recorded = entry.get('source_video') or old_key
        if not Path(recorded).exists() and not Path(old_key).exists():
            found.append((old_key, dict(entry)))
    return found


def matching_move(candidates, content_sha256):
    """The one candidate with this exact content, or None. Two equal candidates are ambiguous: treat as new."""
    matches = [(old_key, entry) for old_key, entry in candidates if entry.get('source_sha256') == content_sha256]
    return matches[0] if len(matches) == 1 else None


class ReviewBusy(RuntimeError):
    pass


def relocate(settings, source, content_sha256, old_key, entry, log=lambda message: None):
    """Point everything recorded for ``old_key`` at ``source``. Returns (identity, previous_entry) to carry on with.

    Raises ReviewBusy, before changing anything, when this video has reviewed labels and the review is open.
    """
    from app.settings import state_directory
    state = state_directory(settings)
    identity = SourceIdentity(key(source), content_sha256, entry['source_id'], entry['output_name'])

    review = state / 'review'
    lock = None
    if has_review(review, old_key):
        lock = RunLock(review)
        try:
            lock.__enter__()
        except RuntimeError:
            raise ReviewBusy('This video moved, and it has reviewed labels. Close the Review tab (and the labeller), '
                             'then process it again so your labels move with it.') from None
    try:
        folders = {Path(settings.csv_folder)} | ({Path(settings.output_folder)} if settings.cut_enabled else set())
        for folder in folders:
            move_identity_record(folder, identity, entry)
        if settings.cut_enabled:
            for manifest in entry.get('manifests') or []:
                move_manifest(manifest, settings.output_folder, identity, source)
        if lock is not None:
            move_reviews(review, old_key, source)
    finally:
        if lock is not None:
            lock.__exit__(None, None, None)

    previous = dict(entry)
    previous['run_directory'] = located(entry.get('run_directory'), '_state', state.parent)
    log(f'{Path(source).name} was already processed at its old location; its phases, reviews and clip names carry over.')
    return identity, previous


def move_identity_record(folder, identity, entry):
    path = Path(folder) / '_state' / 'sources' / f'{identity.output_name}.json'
    if not path.exists():
        return
    record = json.loads(path.read_text(encoding='utf-8'))
    if record.get('content_sha256') != identity.content_sha256 or record.get('identifier') != identity.identifier:
        raise ValueError('Output identity conflict. Choose a different output folder.')
    write_json(path, {'schema_version': 1, **identity.__dict__})


def move_manifest(recorded, output_folder, identity, source):
    """Rewrite one clip manifest for the new source path, and for the clip folder if that moved too."""
    from app.cutting import MANIFEST_FIELDS
    from app.timeline import write_atomic_csv
    path = Path(located(recorded, '_manifests', output_folder))
    if not path.is_file():
        return
    with path.open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    if any(row.get('source_id') != identity.identifier or row.get('source_sha256') != identity.content_sha256
           for row in rows):
        raise ValueError(f'Clip manifest belongs to a different version of this video: {path}')
    old_root = pure(recorded).parents[3] if len(pure(recorded).parents) > 3 else None
    for row in rows:
        row['source_video'] = str(source)
        clip = row.get('clip_path', '')
        if clip and not Path(clip).exists() and old_root is not None:
            try:
                row['clip_path'] = str(Path(output_folder).joinpath(*pure(clip).relative_to(old_root).parts))
            except ValueError:
                pass
    write_atomic_csv(path, rows, MANIFEST_FIELDS)


def is_key(path, source_key):
    """Whether a recorded path string belongs to ``source_key``, even when another machine wrote it.

    ``key`` resolves against this machine, which turns a Windows path read on a Mac into nonsense, so the recorded
    text is also compared as written.
    """
    return key_text(path) == source_key or key(path) == source_key


def key_text(path):
    import unicodedata
    return unicodedata.normalize('NFC', str(path)).replace('\\', '/').casefold()


def has_review(review, old_key):
    """Whether the review folder holds anything for this video. Unreadable files count as yes, to be safe."""
    if not review.is_dir():
        return False
    try:
        for name in ('review_state.json', 'review_exclusions.json'):
            path = review / name
            if path.exists() and old_key in json.loads(path.read_text(encoding='utf-8')):
                return True
        csv_path = review / 'review.csv'
        return csv_path.exists() and any(is_key(row['source_video'], old_key) for row in read_csv(csv_path))
    except (OSError, ValueError, KeyError):
        return True


def move_reviews(review, old_key, source):
    """Move this video's labels, marks and exclusion to its new key. Backs each file up before changing it.

    A video marked reviewed keeps counting as reviewed only if its labels were untouched since it was marked; edits
    made after marking stay unmarked edits, exactly as they were.
    """
    from v3_poc.common import annotation_fingerprint
    new_key = key(source)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')

    def backup(path):
        shutil.copy2(path, path.with_name(f'{path.name}.before-move-{stamp}'))

    csv_path = review / 'review.csv'
    rows = read_csv(csv_path) if csv_path.exists() else []
    mine = [row for row in rows if is_key(row['source_video'], old_key)]
    old_fingerprint = annotation_fingerprint(mine)
    if mine:
        backup(csv_path)
        for row in mine:
            row['source_video'] = str(source)
        write_csv(csv_path, [{k: row.get(k, '') for k in FIELDS} for row in rows])
    new_fingerprint = annotation_fingerprint(mine)

    for name in ('review_state.json', 'review_exclusions.json'):
        path = review / name
        if not path.exists():
            continue
        mapping = json.loads(path.read_text(encoding='utf-8'))
        if old_key not in mapping:
            continue
        backup(path)
        value = mapping.pop(old_key)
        if isinstance(value, dict):
            for row in value.get('rows') or []:
                if isinstance(row, dict) and 'source_video' in row:
                    row['source_video'] = str(source)
            if name == 'review_state.json' and value.get('fingerprint') == old_fingerprint:
                value['fingerprint'] = new_fingerprint
        mapping[new_key] = value
        write_json(path, mapping)
