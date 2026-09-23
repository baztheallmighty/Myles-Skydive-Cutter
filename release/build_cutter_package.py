"""Build a public Skydive Cutter package: an allowlisted folder and ZIP with code, models, installer and docs.

    python release/build_cutter_package.py              # Windows: stage, check, zip
    python release/build_cutter_package.py --stage-only # stage and check (keeps an installed .runtime for testing)
    python release/build_cutter_package.py --mac        # macOS: the same code with the macOS installer

Only allowlisted files are copied. The ZIP never contains a runtime, settings, logs, caches, videos or labels. Before
zipping, every text file and model is scanned for private strings (local folder paths, host names, account names); any
hit stops the build.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / 'release'
VERSION = '2.4.1'
MAC = '--mac' in sys.argv
PLATFORM = 'macos' if MAC else 'windows'
NAME = f'Skydive-Cutter-{VERSION}' + ('-macos' if MAC else '')
DEST = RELEASE / 'dist' / NAME
sys.path.insert(0, str(RELEASE))   # release/privacy.py

FILES = {
    'app': ['__init__.py', 'main.py', 'cutting.py', 'detection.py', 'eta.py', 'ffmpeg_tools.py', 'health.py',
            'monitor.py', 'outputs.py', 'people.py', 'profiles.py', 'progress.py', 'relocate.py', 'runs.py', 'runtime.py',
            'session.py', 'settings.py', 'spans.py', 'system.py', 'timeline.py'],
    'app/classifiers': ['__init__.py', 'contract.py', 'v4.py'],
    'app/ui': ['__init__.py', 'check.svg', 'main_window.py', 'profile_editor.py', 'results.py', 'review_tab.py',
               'theme.py'],
    'cutter_v4': ['__init__.py', 'audio.py', 'engine.py', 'motion.py', 'networks.py', 'review.py', 'review_ui.py'],
    'cutter_v4/models': ['MODELS.json', 'visual.pt', 'temporal.pt', 'audio.pt', 'motion.joblib'],
    # The labeller (_labeler.py, review.py) is inherited research code, frozen: see docs/HOW_IT_WORKS.md.
    'v3_poc': ['common.py', 'networks.py', 'review.py', 'review_exclusions.py', '_labeler.py', '_audio_features.py'],
    'v4_survey': ['telemetry_scan.py', 'accel_events.py'],
}
# Imported by shipped code but left out on purpose, with the reason. Anything else a shipped file imports must ship.
LEFT_OUT: dict[str, str] = {}
PACKAGE_ONLY = RELEASE / 'cutter'   # installer, launchers' scripts and docs, copied to the package root
MAC_ONLY = RELEASE / 'mac'          # the macOS installer and launchers, which replace the Windows ones
WINDOWS_ONLY_FILES = {'Setup.ps1', 'Skydive-Cutter.ps1', 'downloads.json', 'README.md', 'requirements-windows.txt',
                      'torch-cpu.txt', 'torch-cu118.txt', 'torch-cu128.txt'}   # macOS brings its own
# The docs are shared; only the names of the things you double-click differ.
MAC_WORDS = {'Skydive Cutter.cmd': 'Skydive Cutter.command', 'Repair.cmd': 'Repair.command',
             'Skydive-Cutter.ps1': 'skydive-cutter.sh', 'Setup.ps1': 'setup.sh',
             f'Skydive-Cutter-{VERSION}-windows.zip': f'Skydive-Cutter-{VERSION}-macos.zip'}
MAC_EXECUTABLE = {'setup.sh', 'skydive-cutter.sh', 'Skydive Cutter.command', 'Repair.command',
                  'Install Missing.command'}
# What an install adds to a staged folder. Kept between builds so --stage-only can be tested with a real runtime;
# everything else in the staged folder is replaced, so files dropped from the package do not linger there.
INSTALLED_STATE = {'.runtime', '.downloads', 'cache', 'logs', 'bin', 'third_party', 'installation.json', 'yolo11n.pt',
                   '.setup.lock'}
LAUNCHERS = {   # one thing to run; the rest are escape hatches
    'Skydive Cutter.cmd': ('Skydive-Cutter.ps1', '', False),
    'Repair.cmd': ('Skydive-Cutter.ps1', ' -Repair', True),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(8 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def launcher(script: str, extra: str, always_pause: bool) -> str:
    pause = 'echo.\npause\n' if always_pause else 'if not "%SC_EXIT%"=="0" (\n  echo.\n  echo Something went wrong. Read the message above.\n  pause\n)\n'
    return ('@echo off\nsetlocal\ncd /d "%~dp0"\n'
            # %* passes on anything typed after the name, e.g. Repair.cmd -Mode CPU.
            f'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0{script}"{extra} %*\n'
            'set "SC_EXIT=%ERRORLEVEL%"\n' + pause + 'exit /b %SC_EXIT%\n')


def compiled(path: Path) -> bool:
    """Python's own caches, which running a script beside the sources leaves behind. Never shipped."""
    return '__pycache__' in path.parts or path.suffix == '.pyc'


def clear_stage() -> None:
    """Empty the staged folder of everything a build put there, keeping an installed runtime and its settings."""
    if not DEST.is_dir():
        return
    settings = DEST / 'app' / 'settings.json'
    kept_settings = settings.read_bytes() if settings.is_file() else None
    for child in DEST.iterdir():
        if child.name in INSTALLED_STATE:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    if kept_settings is not None:
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_bytes(kept_settings)


def stage() -> list[str]:
    clear_stage()
    DEST.mkdir(parents=True, exist_ok=True)
    names = []
    for folder, files in FILES.items():
        for name in files:
            source, target = ROOT / folder / name, DEST / folder / name
            if not source.is_file():
                if '--bootstrap' in sys.argv and name == 'motion.joblib':
                    continue  # First build only: the motion model is fitted with the package's own runtime.
                raise FileNotFoundError(f'Missing package file: {source}')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            names.append(f'{folder}/{name}')
    for source in sorted(p for p in PACKAGE_ONLY.rglob('*') if p.is_file() and not compiled(p)):
        relative = source.relative_to(PACKAGE_ONLY).as_posix()
        if MAC and source.name in WINDOWS_ONLY_FILES:
            continue
        target = DEST / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if MAC and source.suffix == '.md':
            text = source.read_text(encoding='utf-8')
            for windows_word, mac_word in MAC_WORDS.items():
                text = text.replace(windows_word, mac_word)
            target.write_text(text, encoding='utf-8')
        else:
            shutil.copyfile(source, target)
        names.append(relative)
    if MAC:
        for source in sorted(p for p in MAC_ONLY.rglob('*') if p.is_file() and not compiled(p)):
            name = 'README.md' if source.name == 'README-mac.md' else source.name
            # Shell scripts must keep Unix line endings, so they are copied byte for byte.
            (DEST / name).write_bytes(source.read_bytes())
            names.append(name)
    else:
        for name, (script, extra, always_pause) in LAUNCHERS.items():
            (DEST / name).write_text(launcher(script, extra, always_pause), encoding='ascii', newline='\r\n')
            names.append(name)
    models = json.loads((ROOT / 'cutter_v4' / 'models' / 'MODELS.json').read_text(encoding='utf-8'))
    for entry in models['models'].values():
        if sha256(DEST / 'cutter_v4' / 'models' / entry['file']) != entry['sha256']:
            raise ValueError(f'Model checksum mismatch: {entry["file"]}')
    release = {'name': 'Skydive Cutter', 'version': VERSION, 'license': 'GPL-3.0-only',
               'engine_revision': models['engine_revision'],
               'target': 'macOS 13+ (Apple Silicon or Intel)' if MAC else 'Windows 10/11 x64',
               'platform': PLATFORM,
               'packaged_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
               'contents': 'Application code, trained models, installer and documentation. No videos, labels, '
                           'runtime or personal settings.'}
    (DEST / 'RELEASE.json').write_text(json.dumps(release, indent=2), encoding='utf-8')
    names.append('RELEASE.json')
    window_check(names)
    privacy_check(names)
    hashes = {name: sha256(DEST / name) for name in sorted(names)}
    (DEST / 'PACKAGE_FILES.json').write_text(json.dumps({'schema_version': 1, 'sha256': hashes}, indent=1),
                                             encoding='utf-8')
    print(f'Staged {len(names)} files in {DEST}', flush=True)
    return sorted(names + ['PACKAGE_FILES.json'])


def window_controlled(node) -> bool:
    """True when this call decides what window the child gets, directly or through app/system.py."""
    helpers = {'hidden_process', 'visible_console'}
    for word in node.keywords:
        if word.arg == 'creationflags':
            return True
        if word.arg is None:   # **something
            value = word.value
            if isinstance(value, ast.Call) and getattr(value.func, 'id', getattr(value.func, 'attr', '')) in helpers:
                return True
            if isinstance(value, ast.Name) and value.id in {'creation', 'pipes'}:
                return True
    return False


def window_check(names: list[str]) -> None:
    """Under pythonw a child without CREATE_NO_WINDOW opens its own console window over the app."""
    problems = []
    for name in (n for n in names if n.endswith('.py')):
        tree = ast.parse((DEST / name).read_text(encoding='utf-8'), filename=name)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {'run', 'Popen', 'call', 'check_call', 'check_output'}
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == 'subprocess'
                    and not window_controlled(node)):
                problems.append(f'{name}:{node.lineno}: subprocess.{node.func.attr} without creationflags')
    if problems:
        raise SystemExit('Child processes could open console windows; nothing was zipped:\n  ' + '\n  '.join(problems))
    print('Console-window scan: every child process is hidden', flush=True)


def privacy_check(names: list[str]) -> None:
    """Nothing personal in anything the ZIP would contain (release/privacy.py holds the patterns)."""
    from privacy import findings
    problems = findings([DEST / name for name in names], root=DEST)
    if problems:
        raise SystemExit('Private strings found; nothing was zipped:\n  ' + '\n  '.join(problems[:40]))
    print(f'Privacy scan: {len(names)} files clean', flush=True)


def archive(names: list[str]) -> None:
    path = RELEASE / 'dist' / (f'{NAME}.zip' if MAC else f'{NAME}-windows.zip')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for name in names:
            if MAC and name in MAC_EXECUTABLE:
                # Unix permissions live in the top half of external_attr: 0o755, and the regular-file bit.
                info = zipfile.ZipInfo.from_file(DEST / name, f'{NAME}/{name}')
                info.create_system = 3  # Unix; required for macOS extractors to interpret external_attr as mode bits.
                info.external_attr = (0o100755 << 16)
                info.compress_type = zipfile.ZIP_DEFLATED
                output.writestr(info, (DEST / name).read_bytes())
                continue
            output.write(DEST / name, f'{NAME}/{name}')
    with zipfile.ZipFile(path) as checked:
        assert checked.testzip() is None
        hashes = json.loads(checked.read(f'{NAME}/PACKAGE_FILES.json'))['sha256']
        for name, expected in hashes.items():
            assert hashlib.sha256(checked.read(f'{NAME}/{name}')).hexdigest() == expected, name
        listed = checked.namelist()
        assert len(listed) == len(names)
        if MAC:
            for name in MAC_EXECUTABLE:
                info = checked.getinfo(f'{NAME}/{name}')
                assert info.create_system == 3 and info.external_attr >> 16 == 0o100755, name
        assert not any(part in n for n in listed for part in ('/.runtime/', '/logs/', '/cache/', 'settings.json',
                                                            'installation.json', '/.downloads/', '/bin/'))
    checksum = sha256(path)
    path.with_suffix('.zip.sha256').write_text(f'{checksum}  {path.name}\n', encoding='ascii')
    print(json.dumps({'zip': str(path), 'megabytes': round(path.stat().st_size / 1e6, 1), 'sha256': checksum}, indent=2))


if __name__ == '__main__':
    staged = stage()
    if '--stage-only' not in sys.argv and '--bootstrap' not in sys.argv:
        archive(staged)
