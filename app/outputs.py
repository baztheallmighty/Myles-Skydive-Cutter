"""Stable video identities and pure output-layout decisions."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from app.spans import clip_filename, slugify
from v3_poc.common import digest, key, write_json

OUTPUT_LAYOUTS = {
    'per_video': 'A folder per video',
    'per_clip': 'A folder per clip, grouped by video',
    'flat': 'All clips in one folder',
    'mirror': 'Same folders as the input videos',
}
NAMING_VERSION = 2


def source_label(source, input_folder):
    try:
        return str(Path(source).resolve().relative_to(Path(input_folder).resolve()))
    except ValueError:
        return str(source)


def source_folder(source, input_folder):
    """The video's subfolder inside the input folder ('' at its top level or outside it), for the mirror layout."""
    try:
        relative = Path(source).resolve().parent.relative_to(Path(input_folder).resolve())
    except (TypeError, ValueError):
        return ''
    return '/'.join(safe_stem(part) for part in relative.parts)


def safe_stem(value):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip(' .')[:60].rstrip(' .') or 'video'
    if name.upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
                       *(f'LPT{i}' for i in range(1, 10))}:
        name = '_' + name
    return name


@dataclass(frozen=True)
class SourceIdentity:
    source_key: str
    content_sha256: str
    identifier: str
    output_name: str


def source_identity(source, content_sha256):
    if not re.fullmatch(r'[0-9a-f]{64}', content_sha256):
        raise ValueError('A complete source checksum is required for output naming.')
    identifier = digest({'path': key(source), 'content_sha256': content_sha256})
    return SourceIdentity(key(source), content_sha256, identifier,
                          f'{safe_stem(Path(source).stem)}_{identifier[:16]}')


def identify_source(source, runner):
    size = Path(source).stat().st_size
    hashed = 0
    checksum = hashlib.sha256()
    with Path(source).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            runner.check_cancelled()
            checksum.update(block)
            hashed += len(block)
            runner.report_progress('identify', hashed, max(1, size))
    return source_identity(source, checksum.hexdigest())


def reserve_identity(folder, identity):
    """Validate the full identity before using a shortened ID, even for an empty CSV."""
    directory = Path(folder) / '_state' / 'sources'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'{identity.output_name}.json'
    record = {'schema_version': 1, **identity.__dict__}
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != record:
            raise ValueError('Output identity conflict. Choose a different output folder.')
    else:
        write_json(path, record)


MULTI_LENS_SUFFIXES = {'.360', '.insv'}   # one video track per lens, and their own players


def clip_suffix(source):
    """A clip of a 360 file keeps that file's own extension, so its player still recognises it."""
    suffix = Path(source).suffix
    return suffix if suffix.casefold() in MULTI_LENS_SUFFIXES else ''


def clip_destination(root, layout, output_name, profile_name, index, start, end, phase, folder='', source=''):
    root = Path(root)
    profile = slugify(profile_name)
    filename = clip_filename(index, start, end, phase)
    suffix = clip_suffix(source) if source else ''
    if suffix:
        filename = Path(filename).with_suffix(suffix).name
    if layout == 'per_video':
        return root / profile / output_name / filename
    if layout == 'per_clip':
        return root / profile / output_name / Path(filename).stem / filename
    if layout == 'flat':
        return root / f'{output_name}__{profile}__{filename}'
    if layout == 'mirror':
        return root / profile / Path(*folder.split('/')) / f'{output_name}__{filename}' if folder             else root / profile / f'{output_name}__{filename}'
    raise ValueError('Choose a valid clip folder layout.')


def clip_manifest(root, layout, output_name, profile_name):
    return Path(root) / '_manifests' / layout / slugify(profile_name) / f'{output_name}.clips.csv'


def layout_example(layout):
    path = clip_destination(Path('Clips'), layout, 'GOPR0001_a7c91e3f',
                            'Exit + Freefall', 1, 42, 67, 'freefall', folder='2024/Boogie')
    return str(path)


def owned_clip(row, root, layout, identity, profile_name):
    """A manifest entry grants cleanup ownership only of its exact generated path."""
    try:
        if (row['source_id'] != identity.identifier or row['source_sha256'] != identity.content_sha256
                or row['output_layout'] != layout or row['profile'] != profile_name
                or key(row['source_video']) != identity.source_key):
            return False
        expected = clip_destination(root, layout, identity.output_name, profile_name,
                                    int(row['clip_index']), float(row['start_sec']),
                                    float(row['end_sec']), row['dominant_phase'],
                                    folder=row.get('source_folder') or '', source=row['source_video'])
        candidate = Path(row['clip_path']).resolve()
        return candidate == expected.resolve() and candidate.is_relative_to(Path(root).resolve())
    except (KeyError, TypeError, ValueError):
        return False


def thumbnail_path(state_directory, output_name, profile_name, index):
    """One still per clip, taken from the middle of the clip, for the results list and the labeller."""
    return Path(state_directory) / 'thumbnails' / output_name / f'{slugify(profile_name)}_{int(index):03d}.jpg'
