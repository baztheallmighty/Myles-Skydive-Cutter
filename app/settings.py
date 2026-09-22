"""Versioned settings and validation, independent of Qt."""
from dataclasses import asdict, dataclass, field, fields
import json
import math
from pathlib import Path

from app import PROJECT_ROOT
from app.spans import slugify
from v3_poc.common import PHASES, digest, key, write_json

SETTINGS_PATH = PROJECT_ROOT / 'app' / 'settings.json'
VIEW_MODES = {'front': 'Front view only', 'front_back': 'Front view, people counted all round',
              'back': 'Back view only'}


@dataclass(frozen=True)
class KeepProfile:
    name: str = 'Exit + Freefall'
    phases: frozenset[str] = frozenset({'exit', 'freefall'})
    # Footage with nobody in it is the boring kind: by default a moment counts only with a person in view.
    min_person_count: int = 1
    min_total_area_percent: float = 20.0
    margin_before_seconds: float = 1.0
    # Freefall's end is where the models are least sure (break-off is fuzzy); 2 s after keeps the whole freefall on
    # 85% of tested jumps against 71% with 1 s, for about half a second more footage per clip.
    margin_after_seconds: float = 2.0
    min_span_seconds: float = 0.0
    max_gap_seconds: float = 0.0
    enabled: bool = True


def profile_presets(people_available=True):
    """Ready-made profiles for the "Add preset" menu. Each opens in the editor before it is added.

    Most presets keep the default person requirement. The two that would lose almost everything to it -- a whole jump
    and canopy flight, where the camera often shows only sky or ground -- ask for no people at all.
    """
    return [
        KeepProfile('Whole skydive', frozenset({'climbing_out', 'exit', 'freefall', 'break_off', 'opening_parachutes'}),
                    min_person_count=0, min_total_area_percent=0.0,
                    margin_before_seconds=2.0, margin_after_seconds=2.0),
        KeepProfile('Exit only', frozenset({'exit'}), margin_before_seconds=3.0, margin_after_seconds=3.0),
        KeepProfile('Canopy flight', frozenset({'canopy_flight'}), min_person_count=0, min_total_area_percent=0.0,
                    margin_before_seconds=0.0, margin_after_seconds=0.0,
                    min_span_seconds=10.0, max_gap_seconds=2.0),
        KeepProfile('Landing', frozenset({'landing', 'landed'}), margin_before_seconds=3.0, margin_after_seconds=5.0),
        KeepProfile('Group freefall', frozenset({'freefall'}), min_person_count=2,
                    min_total_area_percent=30.0, margin_before_seconds=2.0, margin_after_seconds=2.0,
                    min_span_seconds=4.0, max_gap_seconds=1.0),
    ]


def preference(default, **kwargs):
    """A setting that does not change any output: excluded from the processing fingerprint.

    Anything without this marker is assumed to change results, so forgetting it reprocesses nothing by surprise.
    """
    return field(default=default, metadata={'affects_output': False}, **kwargs)


@dataclass(frozen=True)
class Settings:
    input_folder: str = preference('')
    output_folder: str = ''
    csv_folder: str = ''
    phases_enabled: bool = True
    people_enabled: bool = True  # the person detector ships with the app; counting people is the normal way to cut
    cut_enabled: bool = True
    output_layout: str = 'per_video'
    phase_classifier: str = 'standard'
    # Where and how fast the work runs does not change what it produces, so neither reprocesses a library.
    device: str = preference('auto')
    # 360 footage: which side of the camera to look at. Ordinary videos ignore this.
    view_mode: str = 'front'
    batch_size: int = preference(8)
    sample_fps: float = 1.0
    detection_confidence: float = 0.35
    yolo_model: str = str(PROJECT_ROOT / 'yolo11n.pt')
    poll_seconds: float = preference(5.0)
    keep_watching: bool = preference(False)
    recut_on_review: bool = preference(True)
    # Remembered window: Qt's own geometry blob, the column split, and which advanced sections were left open.
    window_geometry: str = preference('')
    column_state: str = preference('')
    open_sections: tuple[str, ...] = preference(())
    profiles: tuple[KeepProfile, ...] = field(default_factory=lambda: (KeepProfile(),))


def profile_dict(profile):
    return {**asdict(profile), 'phases': sorted(profile.phases)}


def settings_dict(settings):
    return {**asdict(settings), 'schema_version': 3,
            'profiles': [profile_dict(p) for p in settings.profiles]}


def settings_fingerprint(settings):
    """What decides whether a finished video is processed again.

    Nothing here depends on where the app or the library sits: moving the app folder, unzipping a new version beside
    the old one, or the library drive coming back as a different letter must not reprocess anything. The clip folder
    is not part of it at all, because the ledger that holds these fingerprints lives inside that folder (a different
    clip folder has a different ledger). The CSV folder counts only relative to it.
    """
    value = settings_dict(settings)
    from app.outputs import NAMING_VERSION
    value['output_naming_version'] = NAMING_VERSION
    value['schema_version'] = 3  # the fingerprint's own format; unchanged when the settings file gains fields
    for name in (f.name for f in fields(Settings) if f.metadata.get('affects_output') is False):
        value.pop(name, None)
    # The person detector is the file, not where it happens to be: its name is pinned by checksum at install.
    value['yolo_model'] = Path(value['yolo_model']).name.casefold() if value['yolo_model'] else ''
    state_root = value.pop('output_folder') if settings.cut_enabled else value['csv_folder']
    value['csv_folder'] = relative_key(value['csv_folder'], state_root)
    value['profiles'] = [profile_dict(p) for p in settings.profiles if p.enabled]
    if settings.phases_enabled:
        from app.classifiers import get_classifier
        value['classifier_revision'] = get_classifier(settings.phase_classifier).revision
    if not settings.cut_enabled:
        value.pop('output_folder', None)
        value.pop('output_layout')
    return digest(value)


def relative_key(path, root):
    """``path`` as seen from ``root`` when both are given and on the same drive, else its full key."""
    if not path:
        return ''
    if root:
        import os
        try:
            return os.path.relpath(Path(path).resolve(), Path(root).resolve()).replace('\\', '/').casefold()
        except ValueError:   # different Windows drives have no relative path
            pass
    return key(path)


def accepted_fingerprints(settings):
    """Every fingerprint that still counts as up to date: the current one first, then the 2.3.1 format.

    Ledgers written before the format changed stay valid, so upgrading reprocesses nothing. Each video moves to the
    current format the next time it is processed for any other reason.
    """
    return (settings_fingerprint(settings), legacy_settings_fingerprint(settings))


def legacy_settings_fingerprint(settings):
    """The 2.3.1 fingerprint, kept only to recognise ledgers written by it. Do not change."""
    value = settings_dict(settings)
    from app.outputs import NAMING_VERSION
    value['output_naming_version'] = NAMING_VERSION
    value['schema_version'] = 2  # the fingerprint's own format; unchanged when the settings file gains fields
    for name in (f.name for f in fields(Settings) if f.metadata.get('affects_output') is False):
        value.pop(name, None)
    # Destinations and cut mode matter too: classify-only must not suppress a later cut.
    for name in ('output_folder', 'csv_folder', 'yolo_model'):
        value[name] = key(value[name]) if value[name] else ''
    value['profiles'] = [profile_dict(p) for p in settings.profiles if p.enabled]
    if settings.phases_enabled:
        from app.classifiers import get_classifier
        value['classifier_revision'] = get_classifier(settings.phase_classifier).revision
    if not settings.cut_enabled:
        value.pop('output_folder')
        value.pop('output_layout')
    return digest(value)


def state_directory(settings):
    """CSV-only work needs no clip destination and never touches existing clip folders."""
    return Path(settings.output_folder if settings.cut_enabled else settings.csv_folder) / '_state'


def validate_profile(profile):
    if not isinstance(profile.name, str) or not profile.name.strip() or ';' in profile.name:
        raise ValueError('Give each profile a name without semicolons.')
    if slugify(profile.name).upper() in {'CON', 'PRN', 'AUX', 'NUL',
                                        *(f'COM{i}' for i in range(1, 10)),
                                        *(f'LPT{i}' for i in range(1, 10))}:
        raise ValueError('This profile name is reserved by Windows.')
    if not profile.phases.issubset(PHASES):
        raise ValueError('Profile contains an unknown phase.')
    if type(profile.min_person_count) is not int or profile.min_person_count < 0:
        raise ValueError('Minimum people must be a non-negative integer.')
    for name in ('min_total_area_percent', 'margin_before_seconds', 'margin_after_seconds', 'min_span_seconds',
                 'max_gap_seconds'):
        value = getattr(profile, name)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f'{name} must be finite and non-negative.')
    if type(profile.enabled) is not bool:
        raise ValueError('Profile enabled must be a boolean.')


def validate_settings(settings, require_folders=False):
    from app.outputs import OUTPUT_LAYOUTS
    if settings.output_layout not in OUTPUT_LAYOUTS:
        raise ValueError('Choose a valid clip folder layout.')
    for name in ('phases_enabled', 'people_enabled', 'cut_enabled', 'keep_watching', 'recut_on_review'):
        if type(getattr(settings, name)) is not bool:
            raise ValueError(f'{name} must be a boolean.')
    for name in ('input_folder', 'output_folder', 'csv_folder', 'yolo_model'):
        if not isinstance(getattr(settings, name), str):
            raise ValueError(f'{name} must be a path string.')
    for name in ('window_geometry', 'column_state'):
        if not isinstance(getattr(settings, name), str):
            raise ValueError(f'{name} must be a string.')
    if not all(isinstance(name, str) for name in settings.open_sections):
        raise ValueError('open_sections must be a list of section names.')
    if settings.device not in ('auto', 'cpu', 'cuda', 'mps'):
        raise ValueError('Invalid processing device.')
    if settings.view_mode not in VIEW_MODES:
        raise ValueError('Choose a valid 360 view.')
    from app.classifiers import get_classifier
    get_classifier(settings.phase_classifier)
    if type(settings.batch_size) is not int or settings.batch_size < 1:
        raise ValueError('Batch size must be a positive integer.')
    for name in ('sample_fps', 'poll_seconds'):
        value = getattr(settings, name)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{name} must be finite and positive.')
    if (type(settings.detection_confidence) not in (int, float)
            or not math.isfinite(settings.detection_confidence)
            or not 0 < settings.detection_confidence <= 1):
        raise ValueError('Detection confidence must be between 0 (exclusive) and 1.')
    slugs = set()
    for profile in settings.profiles:
        validate_profile(profile)
        slug = slugify(profile.name)
        if slug in slugs:
            raise ValueError('Profile names must produce different output folder names.')
        slugs.add(slug)
    if require_folders:
        if not settings.input_folder or not Path(settings.input_folder).is_dir():
            raise ValueError('Choose an existing input folder.')
        if settings.cut_enabled and not settings.output_folder:
            raise ValueError('Choose a Clips folder (where the clips go).')
        if not settings.csv_folder:
            raise ValueError('Choose a folder for the timeline CSVs (Advanced settings > Output).')
        source = Path(settings.input_folder).resolve()
        destinations = [settings.csv_folder] + ([settings.output_folder] if settings.cut_enabled else [])
        for folder in destinations:
            dest = Path(folder).resolve()
            if source == dest or source.is_relative_to(dest):
                raise ValueError('Output and CSV folders cannot contain or equal the input folder.')


def load_settings(path=SETTINGS_PATH):
    path = Path(path)
    if not path.exists():
        return Settings()
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Settings must be a JSON object.')
    known = {f.name for f in fields(Settings)}
    values = {k: v for k, v in data.items() if k in known}
    if 'open_sections' in values:
        values['open_sections'] = tuple(values['open_sections'] or ())
    if 'profiles' in values:
        profile_fields = {f.name for f in fields(KeepProfile)}
        profiles = []
        for entry in values['profiles']:
            p = {k: v for k, v in entry.items() if k in profile_fields}
            if 'margin_seconds' in entry and 'margin_before_seconds' not in entry:
                # Settings from before separate margins: keep the user's single margin on both sides.
                p['margin_before_seconds'] = p['margin_after_seconds'] = entry['margin_seconds']
            if 'phases' in p:
                p['phases'] = frozenset(p['phases'])
            profiles.append(KeepProfile(**p))
        values['profiles'] = tuple(profiles)
    if not Path(values.get('yolo_model', '')).is_file() and (PROJECT_ROOT / 'yolo11n.pt').is_file():
        # The app folder was moved or renamed: use the person detector that sits beside the app.
        values['yolo_model'] = str(PROJECT_ROOT / 'yolo11n.pt')
    settings = Settings(**values)
    validate_settings(settings)
    return settings


def save_settings(settings, path=SETTINGS_PATH):
    validate_settings(settings)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    write_json(path, settings_dict(settings))
