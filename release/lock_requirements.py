"""Write the hash-pinned lock files every installer uses, and prove each one resolves for its platform.

    python release/lock_requirements.py            # write the locks, then check them
    python release/lock_requirements.py --check    # only check the locks already written

The versions are the ones in ``release/locks/tested-windows.txt``: the ``pip freeze`` of a runtime that passed the
install test. Apple Silicon uses the same versions; Intel Macs replace the few in ``INTEL_MAC`` because PyTorch
stopped building for them at 2.2. Every package, including the person detector's own dependencies, is listed, so an
install can never pick up whatever happened to be newest that day.

Each lock lists the SHA-256 of every wheel of that version that could suit its platform (pip keeps only those), and
installers use them with ``--require-hashes --no-deps --only-binary=:all:``. The check runs pip's resolver against
each target platform without installing anything: a missing dependency, a clash, or a wheel that does not exist for
macOS 13 fails here instead of on someone's machine.
"""
from __future__ import annotations

import html
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.request

RELEASE = Path(__file__).resolve().parent
TESTED = RELEASE / 'locks' / 'tested-windows.txt'
PYTORCH = 'https://download.pytorch.org/whl'
TORCH = {'torch', 'torchvision'}
INTEL_MAC = {'numpy': '1.26.4', 'opencv-python': '4.11.0.86', 'torch': '2.2.2', 'torchvision': '0.17.2',
             'contourpy': '1.3.2'}   # contourpy 1.4 (for matplotlib) needs NumPy 2
WINDOWS_PROFILES = ('cpu', 'cu118', 'cu128')

# name: (lock file, wheel platform test, pip --platform values for the check)
PLATFORMS = {
    'windows': (RELEASE / 'cutter' / 'requirements-windows.txt', lambda tag: tag == 'win_amd64', ['win_amd64']),
    'mac-arm64': (RELEASE / 'mac' / 'requirements-mac-arm64.txt',
                  lambda tag: tag.startswith('macosx') and tag.endswith(('arm64', 'universal2')), ['macosx_13_0_arm64']),
    'mac-intel': (RELEASE / 'mac' / 'requirements-mac-intel.txt',
                  lambda tag: tag.startswith('macosx') and tag.endswith(('x86_64', 'universal2', 'intel')),
                  ['macosx_13_0_x86_64']),
}


def tested_versions() -> dict[str, str]:
    versions = {}
    for line in TESTED.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            name, version = line.split('==')
            versions[name] = version.split('+')[0]   # torch==2.7.1+cu118 -> 2.7.1; the profile is chosen per lock
    return versions


def python_fits(python_tag: str, abi_tag: str) -> bool:
    """Wheels a CPython 3.12 can install."""
    tags = python_tag.split('.')
    if abi_tag == 'cp312':
        return 'cp312' in tags
    if abi_tag == 'abi3':
        return any(re.fullmatch(r'cp3(\d+)', t) and int(t[3:]) <= 12 for t in tags)
    return abi_tag == 'none' and any(t in ('py3', 'py312', 'cp312') or t.startswith('py3') for t in tags)


def wheel_fits(filename: str, platform_fits) -> bool:
    if not filename.endswith('.whl'):
        return False
    python_tag, abi_tag, platform_tag = filename[:-4].split('-')[-3:]
    platforms = platform_tag.split('.')
    return python_fits(python_tag, abi_tag) and (platforms == ['any'] or any(platform_fits(p) for p in platforms))


def pypi_hashes(name: str, version: str, platform_fits) -> list[str]:
    with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/{version}/json', timeout=60) as response:
        files = json.load(response)['urls']
    return sorted(f['digests']['sha256'] for f in files if wheel_fits(f['filename'], platform_fits))


def pytorch_hashes(name: str, version: str, profile: str) -> list[str]:
    """Hashes from the PyTorch index page, which names each file's SHA-256 in its link."""
    with urllib.request.urlopen(f'{PYTORCH}/{profile}/{name}/', timeout=120) as response:
        page = html.unescape(response.read().decode('utf-8'))
    wanted = f'{name}-{version}-'   # version carries its local tag, e.g. 2.7.1+cu118
    found = []
    for filename, digest in re.findall(r'href="(?:[^"]*/)?([^/"#]+\.whl)#sha256=([0-9a-f]{64})"', page):
        filename = urllib.request.unquote(filename)
        if filename.startswith(wanted) and wheel_fits(filename, lambda tag: tag == 'win_amd64'):
            found.append(digest)
    return sorted(set(found))


def lock_text(title: str, pins: list[tuple[str, str, list[str]]]) -> str:
    lines = [f'# {title}',
             '# Written by release/lock_requirements.py from release/locks/tested-windows.txt. Do not edit by hand.',
             '# Installed with --require-hashes --no-deps --only-binary=:all:, then checked with pip check.']
    for name, version, hashes in pins:
        if not hashes:
            raise SystemExit(f'No suitable wheel for {name}=={version} ({title}).')
        lines.append(f'{name}=={version} \\')
        lines += [f'    --hash=sha256:{digest}' + (' \\' if i < len(hashes) - 1 else '') for i, digest in enumerate(hashes)]
    return '\n'.join(lines) + '\n'


def write_locks() -> None:
    versions = tested_versions()
    for platform, (path, fits, _check) in PLATFORMS.items():
        chosen = dict(versions, **(INTEL_MAC if platform == 'mac-intel' else {}))
        names = sorted((n for n in chosen if platform != 'windows' or n not in TORCH), key=str.casefold)
        pins = [(name, chosen[name], pypi_hashes(name, chosen[name], fits)) for name in names]
        title = {'windows': 'Windows x64, Python 3.12: everything except PyTorch (see torch-<profile>.txt)',
                 'mac-arm64': 'Apple Silicon macOS 13+, Python 3.12',
                 'mac-intel': 'Intel macOS 13+, Python 3.12: PyTorch 2.2.2 with NumPy 1.26 and OpenCV 4.11'}[platform]
        path.write_text(lock_text(title, pins), encoding='utf-8', newline='\n')
        print(f'{path.relative_to(RELEASE.parent)}: {len(pins)} packages', flush=True)
    for profile in WINDOWS_PROFILES:
        pins = [(name, f'{versions[name]}+{profile}', pytorch_hashes(name, f'{versions[name]}+{profile}', profile))
                for name in ('torch', 'torchvision')]
        path = RELEASE / 'cutter' / f'torch-{profile}.txt'
        path.write_text(lock_text(f'PyTorch for Windows x64, {profile} build, from {PYTORCH}/{profile}', pins),
                        encoding='utf-8', newline='\n')
        print(f'{path.relative_to(RELEASE.parent)}: torch and torchvision', flush=True)


def check_locks() -> None:
    """pip's resolver, per platform, with every dependency required to be in the locks."""
    failures = []
    for platform, (path, _fits, check_platforms) in PLATFORMS.items():
        runs = [(f'{platform}/{p}', [path, RELEASE / 'cutter' / f'torch-{p}.txt'], f'{PYTORCH}/{p}')
                for p in WINDOWS_PROFILES] if platform == 'windows' else [(platform, [path], None)]
        for label, files, extra_index in runs:
            with tempfile.TemporaryDirectory() as target:
                argv = [sys.executable, '-m', 'pip', 'install', '--dry-run', '--ignore-installed', '--quiet',
                        '--disable-pip-version-check', '--only-binary=:all:', '--require-hashes',
                        '--python-version', '3.12', '--implementation', 'cp', '--abi', 'cp312', '--target', target]
                for tag in check_platforms:
                    argv += ['--platform', tag]
                if extra_index:
                    argv += ['--extra-index-url', extra_index]
                for file in files:
                    argv += ['-r', str(file)]
                result = subprocess.run(argv, capture_output=True, text=True)
            state = 'resolves' if result.returncode == 0 else 'FAILED'
            print(f'check {label}: {state}', flush=True)
            if result.returncode:
                failures.append(f'{label}:\n{(result.stderr or result.stdout)[-2500:]}')
    if failures:
        raise SystemExit('\n\n'.join(failures))


if __name__ == '__main__':
    if '--check' not in sys.argv:
        write_locks()
    check_locks()
