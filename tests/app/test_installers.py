"""The installers, checked on Windows: what they are written to do, and where possible what they actually do.

Nobody has a Mac on the build machine, so the macOS scripts are checked two ways. Static checks hold the rules that
past failures taught (no Xcode Python stub, Bash 3.2 variable parsing, wheels only). Where Git Bash is installed, the
scripts also run for real against stand-in ``uname``, ``sw_vers`` and ``curl`` commands, which proves the macOS
version gate and the download fallback behave, not just that the words are there.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
MAC = ROOT / 'release' / 'mac'
WINDOWS = ROOT / 'release' / 'cutter'
sys.path.insert(0, str(ROOT))
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def lock(path):
    """{name: (version, [hashes])} from a hash-pinned requirements file."""
    pins, name = {}, None
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip().rstrip('\\').strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('--hash=sha256:'):
            pins[name][1].append(line.split(':', 1)[1])
        else:
            name, version = line.split('==')
            pins[name] = (version, [])
    return pins


def versions_that_passed():
    return {line.split('==')[0]: line.split('==')[1].split('+')[0]
            for line in (ROOT / 'release' / 'locks' / 'tested-windows.txt').read_text(encoding='utf-8').splitlines()
            if line and not line.startswith('#')}


class TestLocks:
    """Every install gets exactly the tested versions, each checked against its hash."""

    def test_every_pin_has_a_hash(self):
        for path in [*WINDOWS.glob('requirements-*.txt'), *WINDOWS.glob('torch-*.txt'), *MAC.glob('requirements-*.txt')]:
            pins = lock(path)
            assert pins, path.name
            assert all(hashes and all(re.fullmatch(r'[0-9a-f]{64}', h) for h in hashes)
                       for _version, hashes in pins.values()), path.name

    def test_windows_is_exactly_what_passed_the_install_test(self):
        windows = {name: version for name, (version, _) in lock(WINDOWS / 'requirements-windows.txt').items()}
        want = {name: version for name, version in versions_that_passed().items() if name not in {'torch', 'torchvision'}}
        assert windows == want
        for profile in ('cpu', 'cu118', 'cu128'):
            torch = lock(WINDOWS / f'torch-{profile}.txt')
            assert torch['torch'][0] == f"{versions_that_passed()['torch']}+{profile}"

    def test_apple_silicon_matches_windows_and_intel_differs_only_where_it_must(self):
        arm = {name: version for name, (version, _) in lock(MAC / 'requirements-mac-arm64.txt').items()}
        intel = {name: version for name, (version, _) in lock(MAC / 'requirements-mac-intel.txt').items()}
        assert arm == versions_that_passed()
        assert arm.keys() == intel.keys()
        assert {name for name in arm if arm[name] != intel[name]} == {
            'numpy', 'opencv-python', 'torch', 'torchvision', 'contourpy'}
        assert intel['numpy'] == '1.26.4' and intel['torch'] == '2.2.2'

    def test_the_person_detector_and_its_dependencies_are_locked(self):
        for path in (WINDOWS / 'requirements-windows.txt', MAC / 'requirements-mac-arm64.txt'):
            assert {'ultralytics', 'polars', 'matplotlib', 'psutil', 'ultralytics-thop'} <= set(lock(path)), path.name


class TestThePackage:
    def test_the_licence_travels_with_it(self):
        """GPL-3.0 software has to ship its licence. 2.3.2's Mac ZIP went out without one after the file went missing."""
        licence = (WINDOWS / 'LICENSE').read_text(encoding='utf-8')
        assert 'GNU GENERAL PUBLIC LICENSE' in licence and 'Version 3' in licence

    def test_every_module_the_app_imports_is_shipped(self):
        """The package is an allowlist. A new module left off it builds fine and then fails on every start."""
        import ast
        from release.build_cutter_package import FILES, LEFT_OUT
        shipped = {f'{folder}/{name}' for folder, names in FILES.items() for name in names}
        missing = set()
        for relative in (name for name in shipped if name.endswith('.py')):
            tree = ast.parse((ROOT / relative).read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                modules = ([alias.name for alias in node.names] if isinstance(node, ast.Import) else
                           [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else [])
                for module in modules:
                    if module.split('.')[0] not in {'app', 'cutter_v4', 'v4_survey'}:
                        continue
                    path = module.replace('.', '/')
                    if (ROOT / f'{path}.py').is_file() and f'{path}.py' not in shipped | set(LEFT_OUT):
                        missing.add(f'{path}.py (imported by {relative})')
        assert not missing, 'not in release/build_cutter_package.py FILES: ' + ', '.join(sorted(missing))


class TestMacScripts:
    def text(self, name):
        return (MAC / name).read_text(encoding='utf-8')

    def test_clean_mac_install_does_not_invoke_xcode_python_stub(self):
        for name in ('setup.sh', 'skydive-cutter.sh'):
            lines = self.text(name).splitlines()
            assert all('/usr/bin/python3' not in line for line in lines if not line.lstrip().startswith('#'))
        assert '/usr/bin/plutil -extract' in self.text('setup.sh')

    def test_bash_32_never_has_an_unbraced_variable_next_to_unicode(self):
        # macOS ships Bash 3.2. It interpreted `$filename…` as a variable named `filename…` under `set -u`.
        for path in list(MAC.glob('*.sh')) + list(MAC.glob('*.command')):
            assert re.search(r'\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7f]', path.read_text(encoding='utf-8')) is None, path.name

    def test_unix_line_endings(self):
        for path in list(MAC.glob('*.sh')) + list(MAC.glob('*.command')):
            assert b'\r' not in path.read_bytes(), f'{path.name}: "bad interpreter" on a Mac'

    def test_wheels_only_and_every_hash_checked(self):
        setup = self.text('setup.sh')
        for flag in ('--only-binary=:all:', '--require-hashes', '--no-deps'):
            assert flag in setup
        assert 'requirements=requirements-mac-arm64.txt' in setup
        assert 'if [ "$arch" = x86_64 ]; then requirements=requirements-mac-intel.txt; fi' in setup
        assert '"$python" -m pip check' in setup

    def test_only_the_command_files_need_to_be_executable(self):
        for name in ('Skydive Cutter.command', 'Repair.command'):
            assert '/bin/bash ./skydive-cutter.sh' in self.text(name)
        assert '/bin/bash ./setup.sh' in self.text('skydive-cutter.sh')
        assert 'chmod +x' in self.text('skydive-cutter.sh')

    def test_the_app_outlives_its_terminal_window(self):
        assert re.search(r'nohup "\$python" .*</dev/null', self.text('skydive-cutter.sh'))

    def test_the_verifier_accepts_mps_and_uses_platform_ffmpeg_names(self):
        verifier = (WINDOWS / 'verify_install.py').read_text(encoding='utf-8')
        assert "choices=['cpu', 'cuda', 'mps']" in verifier
        assert "tool_name('ffmpeg')" in verifier and "tool_name('ffprobe')" in verifier
        assert "'ffmpeg.exe'" not in verifier and "'ffprobe.exe'" not in verifier

    def test_health_checks_metal_not_cuda(self):
        assert 'torch.backends.mps.is_available()' in (ROOT / 'app' / 'health.py').read_text(encoding='utf-8')

    def test_the_readme_gives_the_gatekeeper_steps_for_current_macos(self):
        readme = self.text('README-mac.md')
        assert 'Open Anyway' in readme and 'Privacy & Security' in readme


class TestWindowsScripts:
    def test_hash_checked_wheels_from_the_locks(self):
        setup = (WINDOWS / 'Setup.ps1').read_text(encoding='utf-8')
        for flag in ("'--only-binary=:all:'", "'--require-hashes'", "'--no-deps'", 'requirements-windows.txt',
                     'torch-$Build.txt'):
            assert flag in setup

    def test_repair_reaches_setup(self):
        assert "-Repair:$Repair" in (WINDOWS / 'Skydive-Cutter.ps1').read_text(encoding='utf-8')

    def test_launchers_pass_their_arguments_on(self):
        from release.build_cutter_package import launcher
        assert '%*' in launcher('Skydive-Cutter.ps1', ' -Repair', True)

    def test_pip_output_reaches_the_log(self):
        assert 'Write-Host "$_"' in (WINDOWS / 'Setup.ps1').read_text(encoding='utf-8')

    @pytest.mark.skipif(not shutil.which('powershell.exe'), reason='needs Windows PowerShell')
    def test_python_one_liners_survive_powershell(self):
        """PowerShell strips double quotes out of an argument, so a -c one-liner must quote with single ones.

        `settings.update({"sync": False})` reached Python as `{sync: False}`, so switching off the detector's usage
        statistics failed silently for the whole of 2.4.0's first build.
        """
        setup = (WINDOWS / 'Setup.ps1').read_text(encoding='utf-8')
        for line in setup.splitlines():
            if '-c' in line and 'python' in line.lower() or "$setupPython -s -B -c" in line:
                assert '{"' not in line, f'double quotes inside a Python one-liner: {line.strip()}'
        result = subprocess.run(['powershell.exe', '-NoProfile', '-Command',
                                 '& { $args } "from ultralytics import settings; settings.update({\'sync\': False})"'],
                                capture_output=True, text=True, creationflags=NO_WINDOW)
        assert "{'sync': False}" in result.stdout, f'PowerShell mangled the argument: {result.stdout!r}'

    @pytest.mark.skipif(not shutil.which('powershell.exe'), reason='needs Windows PowerShell')
    def test_the_scripts_parse(self):
        for name in ('Setup.ps1', 'Skydive-Cutter.ps1'):
            script = ("$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile("
                      f"'{WINDOWS / name}', [ref]$null, [ref]$e); $e.Count")
            result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', script], capture_output=True,
                                    text=True, creationflags=NO_WINDOW)
            assert result.stdout.strip() == '0', f'{name}: {result.stdout}{result.stderr}'


def git_bash():
    for candidate in (r'C:\Program Files\Git\bin\bash.exe', shutil.which('bash')):
        if candidate and Path(candidate).is_file() and 'system32' not in candidate.lower():
            return candidate
    return None


BASH = git_bash()


@pytest.mark.skipif(not BASH, reason='needs Git Bash to run the macOS scripts')
class TestMacScriptsRun:
    """The real scripts, with stand-ins for the macOS commands they call."""

    def stand_ins(self, tmp_path, macos='14.6', arch='arm64'):
        shims = tmp_path / 'shims'
        shims.mkdir()
        (shims / 'uname').write_text(f'#!/bin/bash\necho {arch}\n', newline='\n')
        (shims / 'sw_vers').write_text(f'#!/bin/bash\necho {macos}\n', newline='\n')
        return shims

    def run(self, script, shims, *arguments, cwd):
        # Git Bash puts its own tools before the Windows PATH, so the stand-ins are put first from inside Bash.
        env = dict(os.environ, SHIMS=str(shims))
        wrapper = 'export PATH="$(cygpath -u "$SHIMS"):$PATH"; exec bash "$0" "$@"'
        return subprocess.run([BASH, '-c', wrapper, script, *arguments], cwd=cwd, env=env, capture_output=True,
                              text=True, creationflags=NO_WINDOW, timeout=60)

    def test_an_old_macos_is_turned_away_before_anything_downloads(self, tmp_path):
        folder = tmp_path / 'package'
        folder.mkdir()
        shutil.copy2(MAC / 'setup.sh', folder / 'setup.sh')
        result = self.run('setup.sh', self.stand_ins(tmp_path, macos='12.7.4'), cwd=folder)
        assert result.returncode == 1
        assert 'needs macOS 13' in result.stdout and '12.7.4' in result.stdout
        assert not (folder / '.downloads').exists(), 'nothing is created or downloaded'

    def test_a_download_moves_on_when_one_source_gives_the_wrong_file(self, tmp_path):
        """need(), lifted out of setup.sh as it is, with a curl that serves a wrong file from the first address."""
        body = re.search(r'^need\(\) \{.*?^\}', (MAC / 'setup.sh').read_text(encoding='utf-8'), re.S | re.M).group(0)
        folder = tmp_path / 'package'
        (folder / '.downloads').mkdir(parents=True)
        shims = self.stand_ins(tmp_path)
        (shims / 'curl').write_text('#!/bin/bash\nout=""; url=""\nwhile [ $# -gt 0 ]; do\n'
                                    '  case "$1" in -o) out="$2"; shift ;; http*) url="$1" ;; esac; shift\ndone\n'
                                    'case "$url" in *bad*) echo wrong > "$out" ;; *) echo right > "$out" ;; esac\n',
                                    newline='\n')
        if not shutil.which('shasum'):
            (shims / 'shasum').write_text('#!/bin/bash\nshift 2\nsha256sum "$@"\n', newline='\n')
        import hashlib
        want = hashlib.sha256(b'right\n').hexdigest()
        (folder / 'try.sh').write_text('set -euo pipefail\n' + body + '\n'
                                       f'need thing.zip {want} https://bad.example/thing.zip https://good.example/thing.zip\n',
                                       newline='\n')
        result = self.run('try.sh', shims, cwd=folder)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == '.downloads/thing.zip'
        assert (folder / '.downloads' / 'thing.zip').read_bytes() == b'right\n'
        assert 'did not match' in result.stderr

    @pytest.mark.parametrize('first_line, usable', [
        ('ffmpeg version 8.0 Copyright (c) 2000-2025 the FFmpeg developers', True),
        ('ffmpeg version 9.1-tessus  https://evermeet.cx/ffmpeg/', True),
        ('ffmpeg version n7.1 Copyright (c) 2000-2024', True),
        ('ffmpeg version N-120161-g1a2b3c4d5e Copyright', True),       # a development build: newer still
        ('ffmpeg version 6.1.1 Copyright (c) 2000-2023', False),       # older than the minimum
        ('ffprobe version 8.0 Copyright', False),                      # the wrong program
        (None, False),                                                 # does not run on this Mac
    ])
    def test_ffmpeg_is_accepted_when_it_runs_and_is_new_enough(self, tmp_path, first_line, usable):
        """Mac FFmpeg is not pinned: its publisher replaces it in place. The check is what keeps a broken one out."""
        body = re.search(r'^usable_tool\(\) \{.*?^\}', (MAC / 'setup.sh').read_text(encoding='utf-8'),
                         re.S | re.M).group(0)
        folder = tmp_path / 'package'
        folder.mkdir()
        program = folder / 'ffmpeg'
        program.write_text('#!/bin/bash\n' + (f'echo "{first_line}"\necho "built with clang"\n' if first_line
                                              else 'exit 126\n'), newline='\n')
        (folder / 'try.sh').write_text(body + '\nusable_tool ./ffmpeg ffmpeg 7 && echo usable || echo refused\n',
                                       newline='\n')
        result = self.run('try.sh', self.stand_ins(tmp_path), cwd=folder)
        assert result.stdout.strip() == ('usable' if usable else 'refused'), result.stderr

    def test_the_mac_ffmpeg_download_is_not_pinned_to_one_build(self):
        import json
        manifest = json.loads((MAC / 'downloads.json').read_text(encoding='utf-8'))
        tools = [entry for arch in ('arm64', 'x86_64') for entry in manifest['ffmpeg'][arch].values()]
        assert tools and not any('binary_sha256' in entry for entry in tools)
        assert 'usable_tool "$binary" "$tool" "$ffmpeg_minimum"' in (MAC / 'setup.sh').read_text(encoding='utf-8')

    def test_the_status_file_the_app_waits_for_is_written(self, tmp_path):
        folder = tmp_path / 'package'
        folder.mkdir()
        shutil.copy2(MAC / 'Install Missing.command', folder / 'Install Missing.command')
        (folder / 'setup.sh').write_text('#!/bin/bash\nexit 3\n', newline='\n')
        result = self.run('Install Missing.command', self.stand_ins(tmp_path), cwd=folder)
        assert (folder / 'logs' / '.install-status').read_text().strip() == '3', result.stdout + result.stderr
