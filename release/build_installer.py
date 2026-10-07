"""Build the Windows installer: one Setup.exe that installs Skydive Cutter for the person running it.

    python release/build_installer.py                 # stage the package, write the installer script, compile it
    python release/build_installer.py --fetch-tools   # first, download and unpack the compiler if it is not here
    python release/build_installer.py --test-build    # an installer under another name, for the install test

The installer carries exactly the files the ZIP does (the same allowlist in build_cutter_package.py, the same privacy
and console-window checks), so the two cannot drift apart. It copies them to the user's own programs folder, adds the
shortcuts and the uninstall entry, then runs the package's Setup.ps1, which downloads Python, the libraries for this
PC's graphics card, FFmpeg and the person detector exactly as the ZIP's first run does. Nothing needs administrator
rights. The result is not code-signed, so Windows shows its "unknown publisher" warning when it is run.

The compiler is Inno Setup. It is looked for in the ISCC environment variable, in build/tools (where --fetch-tools
puts a pinned, portable copy; see build-tools.json), on PATH, and in the usual install folders.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

RELEASE = Path(__file__).resolve().parent
ROOT = RELEASE.parent
TOOLS = ROOT / 'build' / 'tools'
WORK = ROOT / 'build' / 'installer'
sys.path.insert(0, str(RELEASE))

APP_NAME = 'Skydive Cutter'
RUNNING_MARK = 'SkydiveCutterRunning'          # app/main.py holds this while the app is open
ICON = 'skydive-cutter.ico'
# Windows knows an installed program by this identifier. It must never change, or an upgrade becomes a second install.
APP_ID = '7E0B3C1A-52D4-4A6F-9E18-3F2C6D8A41B7'
# The install test uses its own name, identifier and folder, so it can never disturb a real install on the same PC.
TEST_ID, TEST_SUFFIX = 'C4A91F60-0D2E-4B7A-8F35-9A1E7B6C2D58', ' (test build)'
# What setup and running the app add to the install folder. Removed on uninstall; settings.json is asked about.
# 'Ultralytics' is where the person detector keeps its own settings (usage statistics switched off).
INSTALLED_FOLDERS = ('.runtime', '.downloads', 'cache', 'logs', 'bin', 'third_party', 'Ultralytics', '.ultralytics')
INSTALLED_FILES = ('installation.json', 'yolo*.pt', '.setup.lock', 'app\\speed.json')
LAUNCH = ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\\Skydive-Cutter.ps1"" -Quiet')
POWERSHELL = '{sys}\\WindowsPowerShell\\v1.0\\powershell.exe'

BEFORE = """Skydive Cutter {version}

This installs Skydive Cutter for you alone. It does not need administrator rights and changes nothing else on this PC.

What happens next
  1. The app is copied to the folder you choose (about 150 MB).
  2. A window opens and downloads what the app runs on: Python, the model libraries for your graphics card, FFmpeg
     and the person detector. This is 2 to 5 GB and can take a while. Leave that window open until it closes.
  3. Skydive Cutter appears in the Start menu.

Needs 64-bit Windows 10 or 11 and 8 GB of free disk space (20 GB with an NVIDIA graphics card).

Your videos never leave this PC. After this one download the app works offline.

The person detector is Ultralytics YOLO, licensed under AGPL-3.0 and downloaded from PyPI during step 2.
Skydive Cutter itself is free software under the GNU General Public License, version 3.

Windows may warn that the publisher is unknown: this installer is not code-signed.
"""


def quoted(value) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def installer_script(names: list[str], stage: Path, version: str, output: Path, test_build: bool = False) -> str:
    """The Inno Setup script for these staged files. Pure text: nothing is read from or written to disk."""
    name = APP_NAME + (TEST_SUFFIX if test_build else '')
    base = f'Skydive-Cutter-{version}-Setup' + ('-test' if test_build else '')
    mark = RUNNING_MARK + ('Test' if test_build else '')
    lines = [
        '; Written by release/build_installer.py. Change that, not this.',
        '[Setup]',
        'AppId={{' + (TEST_ID if test_build else APP_ID) + '}',
        f'AppName={name}',
        f'AppVersion={version}',
        f'AppVerName={name} {version}',
        'AppPublisher=Skydive Cutter (open source)',
        f'VersionInfoVersion={version}',
        f'DefaultDirName={{localappdata}}\\Programs\\{name}',
        'DisableProgramGroupPage=yes',
        'DisableDirPage=no',
        # For the person running it, never the whole PC: the app installs its own libraries and writes its settings here.
        'PrivilegesRequired=lowest',
        'ArchitecturesAllowed=x64compatible',
        'ArchitecturesInstallIn64BitMode=x64compatible',
        'MinVersion=10.0',
        f'OutputDir={output}',
        f'OutputBaseFilename={base}',
        f'SetupIconFile={stage / ICON}',
        f'UninstallDisplayIcon={{app}}\\{ICON}',
        f'UninstallDisplayName={name}',
        f'InfoBeforeFile={WORK / "before.txt"}',
        'Compression=lzma2/max',
        'SolidCompression=yes',
        'WizardStyle=modern',
        # Upgrading or uninstalling with the app open would replace files under it; this asks for it to be closed.
        f'AppMutex={mark}',
        'CloseApplications=no',
        'SetupLogging=yes',
        'ExtraDiskSpaceRequired=8589934592',
        '',
        '[Tasks]',
        'Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: unchecked',
        '',
        '[Files]',
    ]
    for item in names:
        relative = item.replace('/', '\\')
        folder = '{app}' + ('\\' + relative.rsplit('\\', 1)[0] if '\\' in relative else '')
        lines.append(f'Source: {quoted(stage / relative)}; DestDir: {quoted(folder)}; Flags: ignoreversion')
    shortcut = (f'Filename: {quoted(POWERSHELL)}; Parameters: "{LAUNCH}"; WorkingDir: "{{app}}"; '
                f'IconFilename: "{{app}}\\{ICON}"; Comment: "Cut skydiving footage into clips"')
    lines += [
        '',
        '[Icons]',
        f'Name: "{{autoprograms}}\\{name}"; {shortcut}',
        f'Name: "{{autodesktop}}\\{name}"; {shortcut}; Tasks: desktopicon',
        '',
        '[Run]',
        # The package's own setup, in a window of its own so the download can be watched. It stays open only if it
        # stopped. /NORUNTIME=1 leaves this out (the install test, and anyone who wants to run setup later).
        (f'Filename: {quoted(POWERSHELL)}; Parameters: "-NoProfile -ExecutionPolicy Bypass -File '
         '""{app}\\Setup.ps1"" -PauseOnFailure"; WorkingDir: "{app}"; '
         'StatusMsg: "Downloading Python, the model libraries and FFmpeg. A window shows the progress; this can '
         'take a while."; Flags: waituntilterminated; Check: WantsRuntime'),
        (f'Filename: {quoted(POWERSHELL)}; Parameters: "{LAUNCH}"; WorkingDir: "{{app}}"; '
         f'Description: "Start {name}"; Flags: postinstall nowait skipifsilent'),
        '',
        '[UninstallDelete]',
    ]
    lines += [f'Type: filesandordirs; Name: "{{app}}\\{folder}"' for folder in INSTALLED_FOLDERS]
    lines += [f'Type: files; Name: "{{app}}\\{file}"' for file in INSTALLED_FILES]
    lines += [
        '',
        '[Code]',
        'function WantsRuntime: Boolean;',
        'begin',
        "  Result := ExpandConstant('{param:NORUNTIME|0}') <> '1';",
        'end;',
        '',
        '{ Settings are yours: they stay unless you say otherwise. Videos and clips are never in this folder. }',
        'procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);',
        'begin',
        "  if (CurUninstallStep = usPostUninstall) and FileExists(ExpandConstant('{app}\\app\\settings.json')) then",
        '    if (not UninstallSilent) and',
        "       (MsgBox('Also remove your Skydive Cutter settings?' + #13#10 + #13#10 +",
        "               'Your videos and clips are not touched either way.',",
        '               mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES) then',
        "      DelTree(ExpandConstant('{app}'), True, True, True);",
        'end;',
        '',
    ]
    return '\n'.join(lines)


def find_compiler() -> Path | None:
    """ISCC.exe, or None. A pinned copy in build/tools wins over whatever happens to be installed."""
    candidates = [os.environ.get('ISCC'), TOOLS / 'innosetup' / 'ISCC.exe', shutil.which('ISCC'), shutil.which('iscc')]
    for base in (os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles'),
                 str(Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs')):
        if base:
            candidates += [Path(base) / f'Inno Setup {major}' / 'ISCC.exe' for major in (7, 6)]
    return next((Path(c) for c in candidates if c and Path(c).is_file()), None)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(8 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def fetch_tools() -> Path:
    """Download the pinned Inno Setup and unpack it into build/tools without installing it on the PC."""
    pinned = json.loads((RELEASE / 'build-tools.json').read_text(encoding='utf-8'))['innosetup']
    downloads = TOOLS / 'downloads'
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / pinned['filename']
    if not (archive.is_file() and sha256(archive) == pinned['sha256']):
        for url in pinned['urls']:
            print(f'Downloading {pinned["filename"]} from {url.split("/")[2]}...', flush=True)
            try:
                with urllib.request.urlopen(url, timeout=120) as response, archive.open('wb') as handle:
                    shutil.copyfileobj(response, handle)
            except OSError as exc:
                print(f'  {exc}', flush=True)
                continue
            if sha256(archive) == pinned['sha256']:
                break
            print('  That copy did not match its checksum.', flush=True)
        else:
            raise SystemExit(f'Could not download {pinned["filename"]} with the pinned checksum.')
    target = TOOLS / 'innosetup'
    subprocess.run([str(archive), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/CURRENTUSER', '/PORTABLE=1', '/NOICONS',
                    f'/DIR={target}'], check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if not (target / 'ISCC.exe').is_file():
        raise SystemExit(f'Inno Setup did not unpack into {target}.')
    print(f'Inno Setup {pinned["version"]} is in {target}', flush=True)
    return target / 'ISCC.exe'


def build(test_build: bool = False) -> Path:
    import build_cutter_package as package
    if package.UNIX:
        raise SystemExit('The installer is for Windows; the macOS and Linux packages are built by '
                         'build_cutter_package.py --mac and --linux.')
    compiler = find_compiler()
    if compiler is None:
        raise SystemExit('The Inno Setup compiler (ISCC.exe) was not found. Run this once with --fetch-tools, '
                         'or set the ISCC environment variable to where it is.')
    names = [name for name in package.stage() if name != 'app/settings.json']
    stage, output = package.DEST, RELEASE / 'dist'
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / 'before.txt').write_text(BEFORE.format(version=package.VERSION), encoding='utf-8')
    script = WORK / ('skydive-cutter-test.iss' if test_build else 'skydive-cutter.iss')
    # A byte-order mark tells the compiler the script is UTF-8.
    script.write_text(installer_script(names, stage, package.VERSION, output, test_build), encoding='utf-8-sig')
    print(f'Compiling {script.name} with {compiler}', flush=True)
    done = subprocess.run([str(compiler), '/Q', str(script)], capture_output=True, text=True, encoding='utf-8',
                          errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if done.returncode:
        raise SystemExit('The installer did not compile:\n' + (done.stdout + done.stderr)[-3000:])
    result = output / (f'Skydive-Cutter-{package.VERSION}-Setup' + ('-test' if test_build else '') + '.exe')
    checksum = sha256(result)
    result.with_name(result.name + '.sha256').write_text(f'{checksum}  {result.name}\n', encoding='ascii')
    print(json.dumps({'installer': str(result), 'megabytes': round(result.stat().st_size / 1e6, 1),
                      'files': len(names), 'sha256': checksum}, indent=2))
    return result


if __name__ == '__main__':
    if '--fetch-tools' in sys.argv and find_compiler() is None:
        fetch_tools()
    build(test_build='--test-build' in sys.argv)
