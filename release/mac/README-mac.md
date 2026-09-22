# Skydive Cutter for macOS

Finds the jump phases in your skydiving footage, keeps the parts you want, and lets you correct anything it got
wrong. Same app as the Windows version, same models, same results.

The installer has been tested on Windows and checked against every package it downloads, but it has not yet been
run all the way through on a Mac. Please tell me what happens: the setup log is in the `logs` folder.

## What you need

- macOS 13 (Ventura) or newer. Setup checks this first and stops with a message on anything older, because the
  libraries it installs publish nothing for older macOS.
- An Apple Silicon Mac (M1 or later), or an Intel Mac that runs macOS 13: in practice a 2017 or later model.
- About 6 GB free while installing. Setup checks this first too.
- Internet for the first run only.

## Install

1. Unzip the download into a normal folder, for example your Home folder. Not inside the Applications folder, and
   not on a read-only volume.
2. Open that folder and double-click **`Skydive Cutter.command`**.
3. macOS says it cannot check the file for malicious software, because this package is not signed by Apple. You only
   get past this once:
   - **macOS 15 (Sequoia) and later:** click **Done**. Open **System Settings > Privacy & Security**, scroll down to
     the message about `Skydive Cutter.command`, click **Open Anyway** and confirm with your password. Then
     double-click the file again and choose **Open**.
   - **macOS 13 and 14:** right-click (or Control-click) the file, choose **Open**, then **Open** again.

   Or skip the dialogs: open Terminal, type `bash ` (with a space), drag `Skydive Cutter.command` into the Terminal
   window, and press Return.

The first run installs everything into that same folder: Python, the model libraries, the person detector and
FFmpeg. It needs no administrator password and touches nothing else on the Mac. Expect several GB and 10 to 20
minutes. Every later start checks the same list in about a second and opens straight away. Once the app has opened
you can close the Terminal window.

The first time the app reads videos in Desktop, Documents, Downloads, or on an external or network drive, macOS asks
whether **Terminal** may access them. That is the app asking (it runs from Terminal): click **Allow**. If you clicked
Don't Allow, turn Terminal back on under **System Settings > Privacy & Security > Files and Folders**.

If macOS refuses to run the scripts at all, open Terminal in that folder and run:

```bash
xattr -dr com.apple.quarantine .
bash ./skydive-cutter.sh
```

If a piece goes missing later, the app offers **Install now**, which opens a Terminal window to fetch it. To reinstall
everything over the top, quit the app and double-click **`Repair.command`**.

To uninstall, drag the folder to the Bin. Nothing is left behind.

## Which processor it uses

| Mac | What it uses | Notes |
| --- | --- | --- |
| Apple Silicon | the GPU, through Apple's Metal backend | Chosen automatically. Speed has not been measured yet. |
| Intel | the processor | Intel Macs use PyTorch 2.2.2 with NumPy 1.26 and OpenCV 4.11. The models give identical answers on the two PyTorch versions in earlier checks. Expect it to be slow: minutes per jump. Some Intel Macs report an Apple GPU, but that path is untested with these models, so it is not offered. |

Advanced settings shows what this Mac offers, and lets you force the processor.

## Differences from the Windows version

- The launchers are `Skydive Cutter.command` and `Repair.command` rather than `.cmd` files.
- "Show in folder" opens Finder with the clip selected; "Open in my video player" uses whatever you have set.
- Everything else, including the Review tab and the clips, behaves the same.

## The rest of the documentation

- [User guide](docs/USER_GUIDE.md) · [Output and CSV reference](docs/OUTPUT_REFERENCE.md)
- [How it works](docs/HOW_IT_WORKS.md) · [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md) · [Changelog](CHANGELOG.md)

Where those mention `Skydive Cutter.cmd` or `Repair.cmd`, read `Skydive Cutter.command` and `Repair.command`.

## What is downloaded, and from where

Nothing is bundled that could not be checked. Everything except FFmpeg is checked against the checksum it was
released with:

| Piece | Source | Checked against |
| --- | --- | --- |
| Python 3.12.14 | astral-sh/python-build-standalone | its pinned SHA-256 |
| PyTorch, the person detector (Ultralytics YOLO, AGPL-3.0) and every other library | PyPI, pre-built only | the SHA-256 of each file, listed in `requirements-mac-arm64.txt` or `requirements-mac-intel.txt` |
| FFmpeg and FFprobe | osxexperts.net static builds, the current version | not pinned (the publisher updates them in place); setup checks each runs and is FFmpeg 7 or newer |
| The person detector's model | Ultralytics' release page | its pinned SHA-256 |

## Licence

GPL-3.0-only, the same as the Windows package. See LICENSE and THIRD_PARTY_NOTICES.md.
