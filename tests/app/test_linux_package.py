"""The Linux package: its pinned libraries, where its downloads come from, and its scripts.

Nothing here runs on Linux. These are the checks that can be made from Windows: the scripts parse and keep Unix line
endings, the two places that name the Python build agree, every library PyTorch's Linux wheel asks for is pinned,
and the choice of FFmpeg behaves as described when run under Git Bash with stand-ins.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LINUX = ROOT / 'release' / 'linux'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

from test_installers import BASH, OFFICIAL_HOSTS, download_urls, lock, versions_that_passed  # noqa: E402

SCRIPTS = ('setup.sh', 'skydive-cutter.sh', 'repair.sh', 'install-missing.sh')


class TestTheLock:
    def pins(self):
        return lock(LINUX / 'requirements-linux-x86_64.txt')

    def test_every_pin_has_a_hash(self):
        pins = self.pins()
        assert pins and all(hashes and all(re.fullmatch(r'[0-9a-f]{64}', h) for h in hashes)
                            for _version, hashes in pins.values())

    def test_it_is_the_tested_versions_plus_what_pytorch_for_linux_brings(self):
        from release.lock_requirements import LINUX_EXTRA
        pins = {name: version for name, (version, _hashes) in self.pins().items()}
        assert pins == {**versions_that_passed(), **LINUX_EXTRA}

    def test_pytorch_comes_from_pypi_with_its_nvidia_libraries(self):
        pins = self.pins()
        assert pins['torch'][0] == versions_that_passed()['torch']
        assert sum(name.startswith('nvidia-') and name.endswith('-cu12') for name in pins) == 14 and 'triton' in pins


class TestWhereItDownloadsFrom:
    def manifest(self):
        return json.loads((LINUX / 'downloads.json').read_text(encoding='utf-8'))

    def test_every_address_is_an_official_source(self):
        urls = list(download_urls(self.manifest()))
        assert urls
        for url in urls:
            where = url[len('https://'):]
            assert url.startswith('https://') and any(
                where.startswith(host + ('' if host.endswith('/') else '/')) for host in OFFICIAL_HOSTS), url

    def test_setup_and_the_manifest_name_the_same_python(self):
        """setup.sh needs these before any Python exists to read the manifest, so it carries its own copy."""
        setup = (LINUX / 'setup.sh').read_text(encoding='utf-8')
        python = self.manifest()['python']['x86_64']
        for name, value in (('python_filename', python['filename']), ('python_sha256', python['sha256']),
                            ('python_url', python['urls'][0])):
            assert f'{name}="{value}"' in setup, name

    def test_the_person_detector_is_the_one_the_other_packages_pin(self):
        windows = json.loads((ROOT / 'release' / 'cutter' / 'downloads.json').read_text(encoding='utf-8'))
        assert self.manifest()['people']['sha256'] in json.dumps(windows)


class TestTheScripts:
    def test_unix_line_endings(self):
        for name in SCRIPTS:
            assert b'\r' not in (LINUX / name).read_bytes(), f'{name}: "bad interpreter" on Linux'

    def test_wheels_only_and_every_hash_checked(self):
        setup = (LINUX / 'setup.sh').read_text(encoding='utf-8')
        for flag in ('--only-binary=:all:', '--require-hashes', '--no-deps', '--index-url https://pypi.org/simple',
                     'requirements-linux-x86_64.txt'):
            assert flag in setup, flag

    def test_nothing_asks_for_root(self):
        for name in SCRIPTS:
            lines = [line for line in (LINUX / name).read_text(encoding='utf-8').splitlines()
                     if 'sudo' in line and not line.lstrip().startswith(('#', 'echo'))]
            assert not lines, f'{name} runs sudo: {lines}'

    def test_the_install_button_never_repairs_over_the_running_app(self):
        command = (LINUX / 'install-missing.sh').read_text(encoding='utf-8')
        assert 'logs/.install-status' in command and 'setup.sh' in command and '--repair' not in command

    @pytest.mark.skipif(not BASH, reason='needs Git Bash')
    def test_they_parse(self):
        for name in SCRIPTS:
            result = subprocess.run([BASH, '-n', str(LINUX / name)], capture_output=True, text=True,
                                    creationflags=NO_WINDOW)
            assert result.returncode == 0, f'{name}: {result.stderr}'


class TestTheAppOnLinux:
    def test_the_install_button_opens_a_terminal_and_waits(self, monkeypatch):
        from app import system
        monkeypatch.setattr(system, 'WINDOWS', False)
        monkeypatch.setattr(system, 'MACOS', False)
        root = Path('/home/me/Skydive-Cutter')
        argv, script = system.installer_argv(root)
        assert script.name == 'install-missing.sh'
        assert argv[:2] == ['/bin/bash', '-c'] and 'x-terminal-emulator' in argv[2] and 'open -a Terminal' not in argv[2]
        assert argv[-2:] == [str(script), str(root / 'logs' / '.install-status')]

    def test_the_package_is_built_from_the_same_files_with_its_own_launchers(self):
        from release import build_cutter_package as package
        assert set(SCRIPTS) == package.LINUX_EXECUTABLE
        assert all((package.LINUX_ONLY / name).is_file() for name in (*SCRIPTS, 'README-linux.md', 'downloads.json'))
        assert set(package.LINUX_WORDS) == set(package.MAC_WORDS), 'every Windows name has its Linux one'


FAKE_TOOL = ('#!/bin/bash\ncase "$1 $2" in\n'
             '  "-version "*) echo "{name} version {version} Copyright" ;;\n'
             '  "-hide_banner -encoders") echo " V....D {encoder}  H.264" ;;\n'
             'esac\n')


@pytest.mark.skipif(not BASH, reason='needs Git Bash to run the Linux scripts')
class TestWhichFFmpegLinuxGets:
    """setup.sh's own FFmpeg section, with a pretend system FFmpeg and a pretend download."""

    def tools(self, folder, version='9.0.2', encoder='libx264'):
        folder.mkdir(parents=True, exist_ok=True)
        for name in ('ffmpeg', 'ffprobe'):
            (folder / name).write_text(FAKE_TOOL.format(name=name, version=version, encoder=encoder), newline='\n')
        return folder

    def choose(self, tmp_path, *, system=None, download=None):
        import tarfile
        text = (LINUX / 'setup.sh').read_text(encoding='utf-8')
        section = text[text.index('ffmpeg_minimum=7'):text.index('# --- the person detector')]
        folder = tmp_path / 'package'
        (folder / '.downloads').mkdir(parents=True)
        (folder / 'bin').mkdir()
        shims = tmp_path / 'shims'
        shims.mkdir()
        served = tmp_path / 'served.tar.xz'
        if download is not None:
            with tarfile.open(served, 'w:xz') as archive:
                for name in ('ffmpeg', 'ffprobe'):
                    archive.add(download / name, f'ffmpeg-n9.0-latest/bin/{name}')
        (shims / 'curl').write_text('#!/bin/bash\nout=""\nwhile [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift ;; esac; '
                                    'shift; done\n[ -f "$SERVED" ] || exit 22\ncp "$SERVED" "$out"\n', newline='\n')
        stubs = ('set -euo pipefail\nrepair=0\nroot="$PWD"\npython="$PYTHON"\n'
                 'python_field() { case "$1" in *.filename) echo ffmpeg.tar.xz ;; *.urls) echo https://example.invalid/f ;; '
                 'esac; }\n')
        (folder / 'try.sh').write_text(stubs + section, newline='\n')
        path = '$(cygpath -u "$SHIMS")' + (':$(cygpath -u "$SYSTEM")' if system is not None else '')
        env = dict(os.environ, SHIMS=str(shims), SERVED=str(served), SYSTEM=str(system or ''),
                   PYTHON=sys.executable.replace('\\', '/'))
        # The pretend system FFmpeg goes on the PATH only when asked for; any real one on this PC is taken off it.
        wrapper = f'export PATH="{path}:/usr/bin:/bin"; exec bash "$0" "$@"'
        result = subprocess.run([BASH, '-c', wrapper, 'try.sh'], cwd=folder, env=env, capture_output=True, text=True,
                                creationflags=NO_WINDOW, timeout=120)
        return result, folder

    def test_a_good_ffmpeg_already_on_the_system_is_used(self, tmp_path):
        result, folder = self.choose(tmp_path, system=self.tools(tmp_path / 'system'))
        assert result.returncode == 0, result.stdout + result.stderr
        assert "FFmpeg is this system's own" in result.stdout and 'Downloading' not in result.stdout
        assert (folder / 'bin' / 'ffmpeg').exists() and (folder / 'bin' / 'ffprobe').exists()

    def test_an_old_system_ffmpeg_is_passed_over_for_the_download(self, tmp_path):
        result, folder = self.choose(tmp_path, system=self.tools(tmp_path / 'system', version='6.1.1'),
                                     download=self.tools(tmp_path / 'download'))
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'FFmpeg is the static build from BtbN/FFmpeg-Builds' in result.stdout
        assert 'version 9.0.2' in (folder / 'bin' / 'ffmpeg').read_text()

    def test_a_system_ffmpeg_without_the_encoder_is_passed_over(self, tmp_path):
        result, _folder = self.choose(tmp_path, system=self.tools(tmp_path / 'system', encoder='libopenh264'),
                                      download=self.tools(tmp_path / 'download'))
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'FFmpeg is the static build' in result.stdout

    def test_with_no_system_ffmpeg_the_download_is_used(self, tmp_path):
        result, _folder = self.choose(tmp_path, download=self.tools(tmp_path / 'download'))
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'FFmpeg is the static build' in result.stdout

    def test_with_nothing_to_be_had_setup_stops_and_says_so(self, tmp_path):
        result, _folder = self.choose(tmp_path)
        assert result.returncode == 1
        assert 'Could not get a working FFmpeg' in result.stdout


def test_git_bash_is_what_these_ran_under():
    if BASH:
        assert shutil.which('bash') or Path(BASH).is_file()
