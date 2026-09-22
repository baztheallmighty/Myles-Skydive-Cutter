"""The platform layer: what each operating system gets asked to do.

These run on Windows and check the macOS and Linux branches too, by pretending to be on them. That is the point of
having one module for this: the rest of the app never asks what platform it is on.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app import system  # noqa: E402


@pytest.fixture
def pretend(monkeypatch):
    """Pretend to be a platform, and record what would have been launched."""
    launched = []

    def fake_popen(argv, **kwargs):
        launched.append((argv, kwargs))
        return None

    def use(*, windows=False, macos=False):
        monkeypatch.setattr(system, 'WINDOWS', windows)
        monkeypatch.setattr(system, 'MACOS', macos)
        monkeypatch.setattr(system.subprocess, 'Popen', fake_popen)
        monkeypatch.setattr(system.os, 'startfile', lambda path: launched.append((['startfile', path], {})),
                            raising=False)
        return launched
    return use


class TestToolNames:
    def test_windows_tools_end_in_exe(self, pretend):
        pretend(windows=True)
        assert system.tool_name('ffmpeg') == 'ffmpeg.exe'

    def test_elsewhere_they_do_not(self, pretend):
        pretend(macos=True)
        assert system.tool_name('ffmpeg') == 'ffmpeg'


class TestChildProcesses:
    def test_windows_hides_the_console(self, pretend):
        pretend(windows=True)
        assert system.hidden_process()['creationflags'] == subprocess.CREATE_NO_WINDOW

    def test_elsewhere_the_child_gets_its_own_group(self, pretend):
        pretend(macos=True)
        assert system.hidden_process() == {'start_new_session': True}

    def test_the_installer_is_meant_to_be_watched(self, pretend):
        pretend(windows=True)
        assert system.visible_console()['creationflags'] == subprocess.CREATE_NEW_CONSOLE


class TestOpeningThings:
    def test_a_clip_opens_in_the_default_player(self, pretend):
        launched = pretend(windows=True)
        system.open_file(r'C:\clips\jump.mp4')
        assert launched[0][0][0] == 'startfile'

        # The expectations go through Path too: run on Windows, these strings gain backslashes, and on a Mac
        # they do not. What matters is the command, not the separator this machine happens to use.
        launched.clear()
        pretend(macos=True)
        system.open_file('/Users/me/clips/jump.mp4')
        assert launched[0][0] == ['open', str(Path('/Users/me/clips/jump.mp4'))]

        launched.clear()
        pretend()
        system.open_file('/home/me/clips/jump.mp4')
        assert launched[0][0] == ['xdg-open', str(Path('/home/me/clips/jump.mp4'))]

    def test_show_in_folder_selects_the_file_where_it_can(self, pretend):
        launched = pretend(windows=True)
        system.show_in_folder(r'C:\clips\jump.mp4')
        assert launched[0][0][:2] == ['explorer', '/select,']

        launched.clear()
        pretend(macos=True)
        system.show_in_folder('/Users/me/clips/jump.mp4')
        assert launched[0][0][:2] == ['open', '-R']

        launched.clear()
        pretend()
        system.show_in_folder('/home/me/clips/jump.mp4')
        assert launched[0][0] == ['xdg-open', str(Path('/home/me/clips'))]


class TestInstallingMissingPieces:
    """The window's "install what is missing" button: visible, and never a repair over the running app."""

    def test_windows_runs_setup_in_its_own_console_and_waits(self, pretend):
        pretend(windows=True)
        argv, script = system.installer_argv(Path(r'C:\SkydiveCutter'))
        assert argv[0] == 'powershell.exe' and script.name == 'Setup.ps1'
        assert '-Repair' not in argv, 'the app is running from the runtime a repair replaces'
        assert '-PauseAtEnd' in argv, 'the console must stay open long enough to read'

    def test_mac_opens_terminal_and_waits_for_the_result(self, pretend):
        pretend(macos=True)
        root = Path('/Users/me/Skydive-Cutter')
        argv, script = system.installer_argv(root)
        assert script.name == 'Install Missing.command'
        assert argv[:2] == ['/bin/bash', '-c'] and 'open -a Terminal' in argv[2]
        assert argv[-2:] == [str(script), str(root / 'logs' / '.install-status')]
        assert '--repair' not in ' '.join(argv), 'a repair would delete the Python the app is running on'

    def test_the_mac_command_writes_the_status_the_app_waits_for(self):
        command = (ROOT / 'release' / 'mac' / 'Install Missing.command').read_text(encoding='utf-8')
        assert 'logs/.install-status' in command and 'setup.sh' in command and '--repair' not in command


class TestIntelMacs:
    def test_automatic_never_picks_the_untested_intel_gpu(self, monkeypatch):
        import torch
        monkeypatch.setattr(system, 'INTEL_MAC', True)
        monkeypatch.setattr(torch.cuda, 'is_available', lambda: False)
        monkeypatch.setattr(torch.backends.mps, 'is_available', lambda: True)
        assert system.accelerators() == ['cpu']
        monkeypatch.setattr(system, 'MACOS', True)
        assert 'mps' not in [value for value, _ in system.device_choices()]

    def test_apple_silicon_still_gets_its_gpu(self, monkeypatch):
        import torch
        monkeypatch.setattr(system, 'INTEL_MAC', False)
        monkeypatch.setattr(torch.cuda, 'is_available', lambda: False)
        monkeypatch.setattr(torch.backends.mps, 'is_available', lambda: True)
        assert system.accelerators() == ['mps', 'cpu']

    def test_the_engine_agrees(self, monkeypatch):
        import torch
        from cutter_v4 import engine
        monkeypatch.setattr(torch.cuda, 'is_available', lambda: False)
        monkeypatch.setattr(torch.backends.mps, 'is_available', lambda: True)
        monkeypatch.setattr(engine, 'intel_mac', lambda: True)
        assert engine.resolve_device('auto') == 'cpu'
        monkeypatch.setattr(engine, 'intel_mac', lambda: False)
        assert engine.resolve_device('auto') == 'mps'

    def test_no_gpu_warning_on_every_start(self, monkeypatch):
        from app import health
        from app.settings import Settings
        monkeypatch.setattr(system, 'INTEL_MAC', True)
        monkeypatch.setattr(system, 'MACOS', True)
        gpu = next(c for c in health.check_install(Settings(), cuda_available=False) if c.key == 'gpu')
        assert gpu.state == health.OK


class TestDeviceNames:
    @pytest.mark.parametrize('device, name', [('cuda', 'NVIDIA GPU'), ('mps', 'Apple GPU'), ('cpu', 'Processor')])
    def test_each_device_has_a_plain_name(self, device, name):
        assert system.describe_device(device) == name


class TestNothingElseAsks:
    def test_the_app_does_not_reach_for_the_platform_itself(self):
        """Platform choices belong in app/system.py, so a Mac build changes one file, not twenty."""
        offenders = []
        for path in sorted((ROOT / 'app').rglob('*.py')) + sorted((ROOT / 'cutter_v4').rglob('*.py')):
            if path.name in {'system.py', 'runtime.py'}:
                continue   # runtime.py owns process groups and job objects by design
            text = path.read_text(encoding='utf-8')
            for marker in ('os.startfile', "'explorer'", '.exe\'', 'powershell.exe'):
                if marker in text:
                    offenders.append(f'{path.relative_to(ROOT)}: {marker}')
        assert not offenders, 'these reach past app/system.py: ' + ', '.join(offenders)
