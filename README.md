# Skydive Cutter

Point it at a folder of skydiving videos and it finds the jump in each one: climbing out, exit, freefall, break-off,
opening, canopy flight and landing. Then it cuts out the parts you want. It works from the video, the sound and the
camera's own motion data, counts the people in frame, and shows you every source lined up on one time axis so you can
correct anything it got wrong. Corrected videos are re-cut straight away.

It runs entirely on your own computer, on Windows or macOS. After a one-time setup it needs no internet, and your
videos never leave your machine.

## Download

Get the latest release from the [Releases page](../../releases):

- **Windows 10 or 11** (64-bit, Intel or AMD): `Skydive-Cutter-<version>-windows.zip`. An NVIDIA graphics card makes
  it several times faster, but is not required. See the [Windows README](release/cutter/README.md).
- **macOS 13 or newer** (Apple Silicon or Intel): `Skydive-Cutter-<version>-macos.zip`. See the
  [Mac README](release/mac/README-mac.md).

Unzip it into a normal folder and double-click `Skydive Cutter.cmd` (Windows) or `Skydive Cutter.command` (Mac). The
first run downloads Python, the model libraries, the person detector and FFmpeg into that folder, each one checked
against a pinned checksum. Nothing is installed anywhere else, and deleting the folder removes all of it.

## Documentation

- [User guide](release/cutter/docs/USER_GUIDE.md): every setting, keep profiles, the Results list, the Review tab.
- [How it works](release/cutter/docs/HOW_IT_WORKS.md): the models, the rules, and how accurate it is.
- [Output and CSV reference](release/cutter/docs/OUTPUT_REFERENCE.md) · [Troubleshooting](release/cutter/docs/TROUBLESHOOTING.md)
- [What each release was tested on](release/cutter/docs/TESTED.md) · [Changelog](release/cutter/CHANGELOG.md)
- For developers: [DEVELOPMENT.md](docs/DEVELOPMENT.md) and [TESTING.md](docs/TESTING.md).

## Licence

Skydive Cutter, including its trained model files, is free software under the
[GNU General Public License, version 3](LICENSE), and comes with no warranty.

The pieces setup downloads keep their own licences; see [THIRD_PARTY_NOTICES.md](release/cutter/THIRD_PARTY_NOTICES.md).
The person detector, [Ultralytics YOLO](https://github.com/ultralytics/ultralytics), is AGPL-3.0 and is downloaded
from its publishers during setup rather than distributed here.
