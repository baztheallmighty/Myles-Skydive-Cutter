# What this release was tested on

Skydive Cutter 2.6.0, October 2026. The first two sections are what was tested for 2.5 and 2.6. The sections after
them were measured on 2.3.0 and have not been repeated since, except where they say so.

## The installer (2.6.0)

On Windows 10 Pro 22H2 with an NVIDIA RTX 5090, a test build of the installer (the same files under a separate name)
was installed without anyone at the keyboard into a folder with a space in its name, and passed 25 checks:

- all 79 package files installed and matching their checksums;
- the Start menu shortcut present, pointing at the install folder, using the app's icon and opening no console window;
- the app listed under Windows' installed apps with the right version, for the current user only;
- setup downloaded and installed Python, the libraries, FFmpeg and the person detector in under 5 minutes and passed
  every install check;
- the app opened from the Start menu shortcut, stayed open, and could be seen by an installer as running;
- uninstalling removed the app, the shortcut, the entry under installed apps and everything setup downloaded, and
  left only the settings file.

**Not tested yet:** clicking through the installer's pages by hand, installing a newer version over an older one,
installing on a PC without an NVIDIA card, and Windows 11.

## Speed, and the same results (2.5)

24 jump videos, 62 minutes of footage, mostly 4K at 60 frames a second from GoPro and 2.7K from DJI, with all three
Basic choices ticked:

| PC | 2.4.3 | 2.5, one video at a time | 2.5, several at once |
| --- | ---: | ---: | ---: |
| Ryzen 9 5950X, RTX 5090 | 15.3 min | 7.6 min | 3.5 min (four at once; no gain beyond) |
| GTX 1060 | 38.4 min | 25.7 min | 17.2 min (two at once) |

With **Trim my video** alone: 7.6 and 3.6 minutes on the RTX 5090, 23.8 and 16.9 on the GTX 1060. Every timeline
from every run was identical to the one made by 2.4.3 one video at a time.

The automated tests (443, run on Windows 10) cover the settings, profiles and joins, clip naming and name clashes,
the Basic and Advanced screens, several videos at once, reading on the graphics card and falling back, the help
notes, the Results list, and the installer script.

**Not tested yet:** the **Automatic** setting for Videos at once on PCs other than these two; its limits are first
guesses. The larger person detectors were compared on two videos only.

## Machines and installs

| Setup | Result |
| --- | --- |
| Windows 10 Pro 22H2 (19045), AMD Ryzen 9 5950X, NVIDIA RTX 5090: NVIDIA setup (`cu128` profile) | Passed all install checks, the end-to-end test and the interface test |
| Same PC, **fresh folder extracted from the release ZIP**, setup in CPU mode (`cpu` profile) | Passed all install checks |
| A second PC that had never seen the app (Windows 10, GTX 1060, `cu118` profile), from the ZIP | Installed in 10 min 45 s including a 2.8 GB download; every install check passed |
| A 536-video run over one season's footage, cutting into mirrored input folders | 482 videos cut, 54 failed (unreadable or audio-less files), judged reasonable by eye |

**Not tested yet:** older NVIDIA cards (they use the `cu118` profile), laptops, Windows 11, and PCs without a recent
Visual C++ runtime. Please report problems with the details listed in
[Troubleshooting](TROUBLESHOOTING.md#details-to-keep-when-asking-for-help).

## What a new machine gets

Measured on 2.3.0. On a PC that had never run the app, extracting the ZIP and double-clicking the launcher installed everything
(Python, the libraries, FFmpeg and the person detector) in 10 min 45 s, mostly download time. After that, starting
the app checks the install in 0.4 s. Removing the detector's model file afterwards was reported by name and stopped
processing rather than being ignored, and putting it back cleared the problem.

## Install checks (run automatically at the end of setup)

Package and model checksums; video network, temporal head and ordered decoding; audio features and audio model;
motion model; the person detector and its weights; the main window with its Process and Review tabs and its three
advanced sections builds; the app's own health check reports nothing missing; FFmpeg and FFprobe run.

## End-to-end test

Measured on 2.3.0; processing has roughly doubled in speed since (see above). Three videos processed exactly as the
app does, with clips cut:

| Video | Camera | Motion data | Processing time (RTX 5090) | Agreement with hand labels |
| --- | --- | --- | ---: | ---: |
| 72 s, H.264 1080p60 | GoPro HERO10 | yes | 11 s | 94% |
| 227 s, HEVC 10-bit 1080p60 | DJI Osmo Action 4 | yes | 40 s | 97% |
| 76 s, MJPEG 640×480 AVI | 2009 Canon compact | no | 10 s | 100% |

These three videos were among the model's training material, so the agreement figures only show that everything
works; for honest accuracy see [How it works](HOW_IT_WORKS.md). On the processor alone, the 72 s video took 30 s and
gave exactly the same phases.

Also checked: a reviewed correction is re-cut without running the model and the clip follows it; a "not skydiving"
video loses its clips; an old video filmed from the open door (where the sound model heard "freefall" throughout)
produces no false clip; the person detector installs with the app, its model matches the pinned checksum, and a
"Freefall with 2 people" profile cuts its own clip.

With people counting on by default (one person filling 20% of the frame), the three test videos still produced the
same clips as before, except the 2009 standard-definition video, where the detector finds nobody at all and so nothing
is kept. Old, small or distant footage is the case to watch: if a video you expected clips from produces none, check
the person columns in its timeline CSV before changing anything else.

## 360 footage

Measured against human labels on jumps from the same archive, scoring the video model's phases second by second:

| Footage | What the app looks at | Videos | Correct seconds |
| --- | --- | --- | --- |
| Stitched 360 and dual-fisheye (2:1 frames) | treated as ordinary video (2.2.0) | 20 | 92.4% |
| Same footage | 360 front view (2.3.0 default) | 20 | 96.9% |
| Same footage | front lens unwrapped to a flat view | 20 | 89.1% |
| Same footage | back view | 20 | 90.4% |
| GoPro MAX `.360` dual lens | front lens (default) | 20 | 97.5% |
| Same footage | both lenses squeezed into one square | 20 | 95.6% |
| Same footage | back lens | 20 | 76.8% (median 84.5%) |

Two things this settles. Treating a 2:1 frame as 360 rather than as flat video is worth about four points, which is why
2.3.0 changed it. And unwrapping a lens into a tidy rectilinear picture makes it *worse*, not better, because the
models were trained on the plain crop, so the front view keeps that crop.

The back view is offered because a camera often faces its wearer, not because it classifies as well: on MAX footage it
averages 77% against the front view's 98%, and on two of the twenty jumps it was wrong almost throughout (0% and 37%).
Use it when you know the jump happens behind the lens, and check what it produced.

An end-to-end run on a real `.360` jump (GoPro MAX, two 4096x1344 lens tracks, 153 s) was processed in 69 s: phases
from the front view, people counted through the same window, and two clips cut that keep both lens tracks, the
ordinary audio and the telemetry, and stay `.360` files.

## Interface test (67 checks)

Last run in full on 2.3.0, before the Basic screen existed; what it lists is still in the app, on the Advanced
screen. The real window is driven automatically on the three videos:

- **Tabs and layout:** Process and Review tabs; one Process videos button with Keep watching; two columns, with the
  settings column scrolling on its own beside the results; the three advanced sections folding, opening and being
  remembered; the processing-device choice; the CSV folder defaulting to Clips/timelines; folders dropped on the
  folder boxes; the labeller's keys working only on the Review tab.
- **360 footage:** a `.360` video in the demo is scanned, recognised as dual-lens rather than flat, classified from
  the front view, and cut into clips that are still `.360` files.
- **Missing pieces:** with the person detector hidden, the banner names it, the People section turns red and opens
  itself, Process videos is switched off, and **Install now** appears; putting it back clears all of that. With no
  GPU the banner is amber and processing still runs.
- **Review tab:**
  - Your labels land on the same pixel as every track for the same second, whole video and zoomed.
  - No sideways scrolling at 1500 × 1000.
  - Zoom and fit; the one-line overlay and O to hide it.
  - Check > finds and jumps to the amber stretches; the video list shows the check counts.
  - Clicking a clip plays it and stops at its end.
  - Newly processed videos appear without moving you off the current one.
- **Results and feedback:**
  - Every processed video listed, with thumbnails; the "Needs a look" filter.
  - Double-click opens the video on the Review tab.
  - **Mark reviewed and re-cut** re-cuts at once, and the clip grew by exactly the 3 s added.
  - **Not skydiving** removes the clips; restoring brings them back reusing the stored phases, without running the model.
  - **Process this video again** runs it from scratch.
  - The processing speed is learned for the time estimate.
- **Presets:** the menu lists all presets, including Group freefall; a preset opens in the editor.

The release build scans every file for private paths and names, and checks every file's checksum inside the ZIP.
The installer is built from the same list of files and stops on the same checks.
Screenshots in the documentation show blurred footage and made-up folder names.
