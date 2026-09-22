"""Where the app meets the operating system.

Everything that differs between Windows, macOS and Linux lives here: what an executable is called, how a file is
opened in whatever the person uses, how a folder is revealed, and how a subprocess is owned so it cannot outlive us.
The rest of the app stays platform-free.
"""
import os
import platform
import subprocess
import sys
from pathlib import Path

WINDOWS = os.name == 'nt'
MACOS = sys.platform == 'darwin'
# Intel Macs run PyTorch 2.2.2 on the processor. Some (with an AMD graphics card) report Apple's GPU as available,
# but that path was never tested with these models, so it is not offered.
INTEL_MAC = MACOS and platform.machine() == 'x86_64'


def tool_name(name):
    """The file name of a bundled command-line tool on this platform."""
    return f'{name}.exe' if WINDOWS else name


def hidden_process():
    """Keyword arguments that stop a child process opening a console window.

    Under pythonw a console child with no console of its own is given a brand new one, which appears over the app.
    Only Windows has the problem, and only Windows has the flag.
    """
    if WINDOWS:
        return {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)}
    return {'start_new_session': True}   # its own process group, so a signal to us does not kill it mid-write


def visible_console():
    """Keyword arguments for a child the person is meant to watch, such as the installer."""
    if WINDOWS:
        return {'creationflags': getattr(subprocess, 'CREATE_NEW_CONSOLE', 0)}
    return {'start_new_session': True}


def open_file(path):
    """Open a file in whatever the person uses for it."""
    path = str(Path(path))
    if WINDOWS:
        os.startfile(path)  # noqa: S606 - the person's own default program
    elif MACOS:
        subprocess.Popen(['open', path], **hidden_process())
    else:
        subprocess.Popen(['xdg-open', path], **hidden_process())


def show_in_folder(path):
    """Open the folder holding this file, with the file selected where the platform allows it."""
    path = Path(path)
    if WINDOWS:
        subprocess.Popen(['explorer', '/select,', str(path)], **hidden_process())
    elif MACOS:
        subprocess.Popen(['open', '-R', str(path)], **hidden_process())
    else:
        subprocess.Popen(['xdg-open', str(path.parent)], **hidden_process())


# The Mac installer runs in a Terminal window of its own, which `open` starts and returns from at once. This waits for
# the status file that "Install Missing.command" writes when setup ends, so the app knows when to look again.
MAC_WAIT = ('rm -f "$2"; open -a Terminal "$1" || exit 1; '
            'i=0; while [ $i -lt 21600 ]; do [ -f "$2" ] && exit "$(cat "$2")"; sleep 1; i=$((i+1)); done; exit 124')


def installer_argv(root):
    """How to install what is missing, in a window the person can watch. Returns (argv, the file that must exist).

    This fills in what is missing and never reinstalls over the top: the app is running from the runtime a repair
    would replace. Repairing is Repair.cmd / Repair.command, with the app closed.
    """
    root = Path(root)
    if WINDOWS:
        script = root / 'Setup.ps1'
        return ([str(p) for p in ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script,
                                  '-PauseAtEnd']], script)
    script = root / 'Install Missing.command'
    return (['/bin/bash', '-c', MAC_WAIT, 'install-missing', str(script), str(root / 'logs' / '.install-status')],
            script)


def accelerators():
    """Which processing devices this machine offers, fastest first, always ending in the processor."""
    found = []
    try:
        import torch
        if torch.cuda.is_available():
            found.append('cuda')
        if not INTEL_MAC and getattr(torch.backends, 'mps', None) is not None and torch.backends.mps.is_available():
            found.append('mps')
    except Exception:  # noqa: BLE001 - a broken install must read as "processor only", not stop the app
        pass
    return found + ['cpu']


def best_device():
    """What 'automatic' picks here."""
    return accelerators()[0]


def device_choices():
    """(value, label) for the settings, offering only what this machine could actually use."""
    labels = {'auto': 'Automatic (' + describe_device(best_device()) + ')',
              'cuda': 'NVIDIA GPU', 'mps': 'Apple GPU', 'cpu': 'Processor only'}
    offered = ['auto'] + [name for name in ('cuda', 'mps') if name in accelerators() or
                          (name == 'cuda' and WINDOWS) or (name == 'mps' and MACOS and not INTEL_MAC)] + ['cpu']
    return [(name, labels[name]) for name in offered]


def describe_device(device):
    """What the processing device is called in front of a person, per platform."""
    if device == 'cuda':
        return 'NVIDIA GPU'
    if device == 'mps':
        return 'Apple GPU'
    return 'Processor'
