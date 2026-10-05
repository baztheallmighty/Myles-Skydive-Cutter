"""The Windows installer: the script written for Inno Setup, where its compiler is found, and what the launchers
were given so a Start-menu shortcut works without a console window.

These check the text and the lookups only. Installing for real is release/tests/installer_test.ps1.
"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from release import build_installer as installer  # noqa: E402

STAGE = Path('C:/stage/Skydive-Cutter-9.9.9')
NAMES = ['app/main.py', 'app/ui/help.py', 'cutter_v4/models/MODELS.json', 'Setup.ps1', 'Skydive-Cutter.ps1',
         'Skydive Cutter.cmd', 'skydive-cutter.ico', 'PACKAGE_FILES.json']


def script(test_build=False):
    return installer.installer_script(NAMES, STAGE, '9.9.9', Path('C:/out'), test_build)


def section(text, name):
    return text.split(f'[{name}]\n', 1)[1].split('\n[', 1)[0]


class TestTheInstallerScript:
    def test_every_staged_file_is_installed_into_its_own_folder_and_nothing_else_is(self):
        files = [line for line in section(script(), 'Files').splitlines() if line]
        assert len(files) == len(NAMES)
        assert f'Source: "{STAGE / "app" / "ui" / "help.py"}"; DestDir: "{{app}}\\app\\ui"; Flags: ignoreversion' in files
        assert f'Source: "{STAGE / "Setup.ps1"}"; DestDir: "{{app}}"; Flags: ignoreversion' in files
        assert '*' not in ''.join(files)   # no wildcards: a runtime left in the staging folder can never be swept in

    def test_it_installs_for_one_person_without_administrator_rights(self):
        setup = section(script(), 'Setup')
        assert 'PrivilegesRequired=lowest' in setup
        assert 'DefaultDirName={localappdata}\\Programs\\Skydive Cutter\n' in setup
        assert 'AppVersion=9.9.9' in setup and 'OutputBaseFilename=Skydive-Cutter-9.9.9-Setup\n' in setup

    def test_the_identifier_windows_knows_the_app_by_never_changes(self):
        assert 'AppId={{7E0B3C1A-52D4-4A6F-9E18-3F2C6D8A41B7}\n' in script()

    def test_a_test_build_cannot_be_mistaken_for_the_real_one(self):
        real, test = script(), script(test_build=True)
        for key in ('AppId', 'AppName', 'DefaultDirName', 'OutputBaseFilename', 'AppMutex'):
            find = re.compile(rf'^{key}=(.*)$', re.MULTILINE)
            assert find.search(real).group(1) != find.search(test).group(1), key

    def test_it_waits_for_an_open_app_to_be_closed_using_the_name_the_app_holds(self):
        from app import main
        assert main.RUNNING_MARK == installer.RUNNING_MARK
        assert f'AppMutex={main.RUNNING_MARK}\n' in script()

    def test_the_shortcut_starts_the_launcher_with_no_window(self):
        icons = section(script(), 'Icons')
        assert 'Name: "{autoprograms}\\Skydive Cutter"' in icons
        assert '-WindowStyle Hidden -File ""{app}\\Skydive-Cutter.ps1"" -Quiet' in icons
        assert 'IconFilename: "{app}\\skydive-cutter.ico"' in icons
        desktop = [line for line in icons.splitlines() if '{autodesktop}' in line]
        assert len(desktop) == 1 and desktop[0].endswith('Tasks: desktopicon')

    def test_setup_runs_after_the_files_are_copied_and_can_be_left_out(self):
        run = section(script(), 'Run').splitlines()
        setup = next(line for line in run if 'Setup.ps1' in line)
        assert '-PauseOnFailure' in setup and 'waituntilterminated' in setup and 'Check: WantsRuntime' in setup
        assert '-WindowStyle Hidden' not in setup   # the download has to be visible
        assert "'{param:NORUNTIME|0}'" in script()

    def test_uninstalling_removes_what_setup_downloaded_but_asks_about_settings(self):
        text = script()
        removed = section(text, 'UninstallDelete')
        for folder in ('.runtime', '.downloads', 'cache', 'logs', 'bin', 'third_party'):
            assert f'Type: filesandordirs; Name: "{{app}}\\{folder}"' in removed
        assert 'settings.json' not in removed
        assert 'Also remove your Skydive Cutter settings?' in text and 'MB_DEFBUTTON2' in text
        assert 'not UninstallSilent' in text   # a silent uninstall keeps them

    def test_the_page_before_installing_says_what_is_downloaded_and_under_which_licence(self):
        text = installer.BEFORE.format(version='9.9.9')
        for words in ('2 to 5 GB', 'AGPL-3.0', 'not code-signed', 'administrator rights', 'never leave this PC'):
            assert words in text


class TestFindingTheCompiler:
    def test_the_pinned_copy_in_the_build_folder_is_used_before_an_installed_one(self, tmp_path, monkeypatch):
        pinned = tmp_path / 'innosetup' / 'ISCC.exe'
        pinned.parent.mkdir()
        pinned.write_bytes(b'')
        monkeypatch.setattr(installer, 'TOOLS', tmp_path)
        monkeypatch.delenv('ISCC', raising=False)
        monkeypatch.setattr(installer.shutil, 'which', lambda name: str(tmp_path / 'elsewhere.exe'))
        assert installer.find_compiler() == pinned

    def test_the_environment_variable_wins(self, tmp_path, monkeypatch):
        chosen = tmp_path / 'my' / 'ISCC.exe'
        chosen.parent.mkdir()
        chosen.write_bytes(b'')
        monkeypatch.setenv('ISCC', str(chosen))
        assert installer.find_compiler() == chosen

    def test_none_when_it_is_nowhere(self, tmp_path, monkeypatch):
        monkeypatch.setattr(installer, 'TOOLS', tmp_path)
        monkeypatch.setattr(installer.shutil, 'which', lambda name: None)
        for variable in ('ISCC', 'ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA'):
            monkeypatch.delenv(variable, raising=False)
        assert installer.find_compiler() is None

    def test_the_compiler_download_is_pinned_by_checksum_and_comes_over_https(self):
        pinned = json.loads((ROOT / 'release' / 'build-tools.json').read_text(encoding='utf-8'))['innosetup']
        assert re.fullmatch(r'[0-9a-f]{64}', pinned['sha256'])
        assert pinned['urls'] and all(url.startswith('https://') and url.endswith(pinned['filename'])
                                      for url in pinned['urls'])
        assert pinned['version'] in pinned['filename']


class TestWhatTheInstallerRelyOn:
    def test_the_icon_is_in_the_package_and_holds_the_sizes_windows_asks_for(self):
        icon = ROOT / 'release' / 'cutter' / installer.ICON
        data = icon.read_bytes()
        count = int.from_bytes(data[4:6], 'little')
        sizes = {data[6 + 16 * index] or 256 for index in range(count)}
        assert data[:4] == b'\x00\x00\x01\x00' and {16, 32, 48, 256} <= sizes

    def test_the_app_finds_its_icon_here_and_in_an_installed_package(self, tmp_path, monkeypatch):
        from app import main
        assert main.app_icon() == ROOT / 'release' / 'cutter' / main.ICON
        (tmp_path / main.ICON).write_bytes(b'')
        monkeypatch.setattr(main, 'PROJECT_ROOT', tmp_path)
        assert main.app_icon() == tmp_path / main.ICON

    @pytest.mark.skipif(sys.platform != 'win32', reason='a Windows mutex')
    def test_the_running_mark_can_be_seen_by_another_program_while_it_is_held(self, monkeypatch):
        import ctypes
        from app import main
        monkeypatch.setattr(main, 'RUNNING_MARK', 'SkydiveCutterRunningUnitTest')
        kernel = ctypes.windll.kernel32
        synchronize = 0x00100000
        assert not kernel.OpenMutexW(synchronize, False, main.RUNNING_MARK)
        handle = main.mark_running()
        try:
            seen = kernel.OpenMutexW(synchronize, False, main.RUNNING_MARK)
            assert seen
            kernel.CloseHandle(seen)
        finally:
            kernel.CloseHandle(handle)

    def test_setup_keeps_its_window_open_only_when_it_stopped(self):
        text = (ROOT / 'release' / 'cutter' / 'Setup.ps1').read_text(encoding='utf-8')
        assert '[switch]$PauseOnFailure' in text
        assert 'if ($PauseAtEnd -or ($PauseOnFailure -and $setupFailed))' in text

    def test_a_quiet_start_hands_over_to_a_visible_window_when_something_is_missing(self):
        text = (ROOT / 'release' / 'cutter' / 'Skydive-Cutter.ps1').read_text(encoding='utf-8')
        quiet = text.index('if ($Quiet -and $missing.Count -gt 0)')
        assert "'Skydive Cutter.cmd'" in text[quiet:quiet + 400]
        assert quiet < text.index('if ($Repair -or $missing.Count -gt 0)')   # before any hidden install could start

    def test_the_uninstall_list_covers_everything_setup_and_the_app_leave_in_the_folder(self):
        from release.build_cutter_package import INSTALLED_STATE
        from fnmatch import fnmatch
        covered = installer.INSTALLED_FOLDERS + installer.INSTALLED_FILES
        assert not [name for name in INSTALLED_STATE if not any(fnmatch(name, pattern) for pattern in covered)]
        assert any(fnmatch('yolo26x.pt', pattern) for pattern in covered)   # a larger detector chosen later
