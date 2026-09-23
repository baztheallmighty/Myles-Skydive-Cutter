"""What this install has and what it is missing.

No Qt and no heavy imports, so the window can ask at startup and the launcher can ask before it starts anything.
A missing piece is an error when it stops the work you asked for, and a warning when the work only gets slower.
"""
from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path

from app import PROJECT_ROOT

OK, WARNING, ERROR = 'ok', 'warning', 'error'
MODELS = PROJECT_ROOT / 'cutter_v4' / 'models'


@dataclass(frozen=True)
class Check:
    key: str
    label: str
    state: str
    detail: str
    section: str = ''      # the advanced section to open on a problem
    repairable: bool = False   # the installer can download this


def people_installed(settings=None):
    """Both halves must be here: the detector library, and the weights it reads."""
    if importlib.util.find_spec('ultralytics') is None:
        return False
    weights = Path(settings.yolo_model) if settings and settings.yolo_model else PROJECT_ROOT / 'yolo11n.pt'
    return weights.is_file() or (PROJECT_ROOT / 'yolo11n.pt').is_file()


def people_wanted(settings):
    """People are needed when the tick box is on, or when any enabled profile asks for a person."""
    if settings.people_enabled:
        return True
    return any(p.enabled and (p.min_person_count > 0 or p.min_total_area_percent > 0) for p in settings.profiles)


def missing_models():
    try:
        manifest = json.loads((MODELS / 'MODELS.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return ['MODELS.json']
    # Name and size only: reading 130 MB of weights on every start would cost more than it catches.
    absent = []
    for name, model in manifest.get('models', {}).items():
        path = MODELS / model.get('file', '')
        if not path.is_file() or (model.get('bytes') and path.stat().st_size != model['bytes']):
            absent.append(model.get('file', name))
    return absent


def missing_tools():
    from app.ffmpeg_tools import find_executable
    absent = []
    for name in ('ffmpeg', 'ffprobe'):
        try:
            find_executable(name)
        except FileNotFoundError:
            absent.append(name)
    return absent


def missing_packages():
    return [name for name, module in (('librosa', 'librosa'), ('soundfile', 'soundfile'),
                                      ('scikit-learn', 'sklearn'), ('torch', 'torch'), ('torchvision', 'torchvision'))
            if importlib.util.find_spec(module) is None]


def check_install(settings, cuda_available=None):
    """Every check, worst first. cuda_available is passed in because importing torch takes a second or two."""
    checks = []

    packages = missing_packages()
    checks.append(Check('packages', 'Model libraries', ERROR if packages else OK,
                        'missing: ' + ', '.join(packages) if packages else 'installed',
                        repairable=True))

    tools = missing_tools()
    checks.append(Check('ffmpeg', 'FFmpeg', ERROR if tools else OK,
                        'missing: ' + ', '.join(tools) if tools else 'installed', repairable=True))

    models = missing_models()
    checks.append(Check('models', 'Jump phase models', ERROR if models else OK,
                        'missing or damaged: ' + ', '.join(models) if models
                        else 'visual, temporal, audio and motion models', repairable=False))

    installed = people_installed(settings)
    wanted = people_wanted(settings)
    checks.append(Check('people', 'People detection',
                        OK if installed else (ERROR if wanted else WARNING),
                        'installed' if installed else 'the person detector and its model file are missing',
                        section='people', repairable=True))

    if cuda_available is not None:
        from app.system import INTEL_MAC, MACOS, describe_device
        label = describe_device('mps' if MACOS else 'cuda')
        if INTEL_MAC and settings.device == 'auto':
            # Expected, not a problem: nothing to warn about on every start.
            checks.append(Check('gpu', 'Processor', OK, 'Intel Macs use the processor', section='processing'))
        elif settings.device in ('cuda', 'mps') and not cuda_available:
            detail = ('chosen in the settings, but this install has the processor build. Choose Automatic, or '
                      'close the app and run Repair.cmd -Mode NVIDIA to install the GPU build'
                      if settings.device == 'cuda' and not torch_has_cuda() else
                      'chosen in the settings, but no usable graphics card was found')
            checks.append(Check('gpu', describe_device(settings.device), ERROR, detail, section='processing'))
        elif settings.device != 'cpu' and not cuda_available:
            checks.append(Check('gpu', label, WARNING,
                                'none found; the processor does the work, which is several times slower',
                                section='processing'))
        else:  # the section is named even when it is fine, so an earlier warning is cleared from it
            checks.append(Check('gpu', 'Graphics card', OK, 'in use' if cuda_available else 'not used',
                                section='processing'))

    order = {ERROR: 0, WARNING: 1, OK: 2}
    return sorted(checks, key=lambda check: order[check.state])


def blocking(checks):
    return [check for check in checks if check.state == ERROR]


def summary(checks):
    """One line for the window's banner."""
    stoppers = blocking(checks)
    if stoppers:
        first = stoppers[0]
        if first.key == 'people':
            return 'People detection is not installed, so your profiles cannot check for people'
        return f'{first.label}: {first.detail}'
    warnings = [check for check in checks if check.state == WARNING]
    return f'{warnings[0].label}: {warnings[0].detail}' if warnings else ''


def torch_has_cuda():
    """Whether the installed PyTorch was built with CUDA at all (the processor build never can be)."""
    try:
        import torch
        return torch.version.cuda is not None
    except Exception:  # noqa: BLE001 - a missing or broken torch is reported by the packages check
        return False


def cuda_available():
    """Whether this platform has a usable accelerator (CUDA on Windows, Metal on macOS)."""
    try:
        import torch
        from app.system import MACOS
        if MACOS:
            return bool(getattr(torch.backends, 'mps', None) and torch.backends.mps.is_available())
        return bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001 - a broken CUDA install must read as "no GPU", not stop the app starting
        return False
