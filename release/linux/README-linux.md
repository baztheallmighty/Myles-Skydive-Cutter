# Skydive Cutter for Linux

Finds the jump in your skydiving videos, keeps the parts you want, and lets you correct anything it got wrong. Same
app as the Windows version, same models, same results.

**This is the first Linux package, and it is untested on Linux.** The setup script has been checked on Windows:
it parses, its FFmpeg choice has been run with stand-ins, and every package it installs has been checked to exist
for Linux with its checksum. Neither setup nor the app has yet been run all the way through on a Linux PC. Please
tell me what happens: the setup log is in the `logs` folder, and Ctrl+Shift+D in the app saves a diagnostics file to
send.

## What you need

- A 64-bit Intel or AMD PC running a Linux with the GNU C library 2.28 or newer: Ubuntu 20.04, Debian 10, Fedora 29,
  or anything later. Setup checks this first.
- A desktop (X11 or Wayland). The app is a window, not a command-line tool.
- About 16 GB free while installing. Setup checks this first too. PyTorch for Linux brings NVIDIA's libraries with it
  whether or not you have an NVIDIA card, which is most of the size.
- `curl` and `tar`, which nearly every Linux has.
- Internet for the first run only. After that the app only asks, once at start-up, whether a newer version is out.
- For speed, an NVIDIA graphics card with its driver installed. Without one the app uses the processor: expect
  minutes per jump.

## Install and run

1. Unzip `Skydive-Cutter-2.7.0-linux.zip` somewhere in your home folder.
2. Open a terminal in that folder and run:

   ```bash
   bash ./skydive-cutter.sh
   ```

The first run installs everything into that same folder: Python, the model libraries, the person detector and
FFmpeg. It asks for no root password and touches nothing else on the system. Expect several GB and 10 to 20 minutes.
Every later start checks the same list in about a second and opens straight away. Once the app has opened you can
close the terminal.

If the window does not open, setup's last lines say whether a system library the window needs is missing, and give
the one command that installs it. On Ubuntu or Debian that is:

```bash
sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libegl1 libgl1 libfontconfig1 libdbus-1-3
```

If a piece goes missing later, the app offers **Install now**, which opens a terminal window to fetch it. If no
terminal program is found, run `bash ./setup.sh` yourself. To reinstall everything over the top, close the app and
run `bash ./repair.sh`.

To uninstall, delete the folder. Nothing is left behind.

## Differences from the Windows version

- There is no installer and no menu entry: unzip the folder and run `skydive-cutter.sh`.
- **Run on: Automatic** uses an NVIDIA card when PyTorch can see one, and the processor otherwise. AMD and Intel
  graphics are not used.
- **Read videos with: Automatic** tries the NVIDIA card's decoder and uses the processor if that fails. The FFmpeg
  already on your system is used when it is version 7 or newer; whether it can decode on the card depends on how your
  distribution built it.
- **Videos at once: Automatic** reads how busy the processor and memory are, and the NVIDIA card through
  `nvidia-smi`.
- The speed figures in the documentation were measured on Windows PCs and say nothing about this package.
- "Show in folder" opens your file manager at the clip's folder; "Open in my video player" uses whatever you have set.

## The rest of the documentation

- [User guide](docs/USER_GUIDE.md) · [Output and CSV reference](docs/OUTPUT_REFERENCE.md)
- [How it works](docs/HOW_IT_WORKS.md) · [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md) · [Changelog](CHANGELOG.md)

They are shared with the Windows version, so they mention Explorer (read your file manager) and, in the list of what
was tested, the Windows installer.

## What is downloaded, and from where

| Piece | Source | Checked against |
| --- | --- | --- |
| Python 3.12.14 | astral-sh/python-build-standalone | its pinned SHA-256 |
| PyTorch, the person detector (Ultralytics YOLO, AGPL-3.0) and every other library | PyPI, pre-built only | the SHA-256 of each file, listed in `requirements-linux-x86_64.txt` |
| FFmpeg and FFprobe | The copy already on your system if it is version 7 or newer and has the x264 encoder; otherwise the static 9.0 build from BtbN/FFmpeg-Builds, the Linux build linked from ffmpeg.org | that it runs, is FFmpeg 7 or newer and has the x264 encoder. The download is rebuilt in place by its publisher, so it cannot be pinned to a checksum |
| The person detector's model | Ultralytics' release page | its pinned SHA-256 |

Setup says which FFmpeg it used on its last lines, and `installation.json` records it.

## Licence

GPL-3.0-only, the same as the Windows package. See LICENSE and THIRD_PARTY_NOTICES.md.
