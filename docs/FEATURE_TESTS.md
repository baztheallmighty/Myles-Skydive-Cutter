# Every feature, and how it gets tested

[TESTING.md](TESTING.md) describes the layers of tests. This is the checklist: every feature the app offers, what
already covers it, and what a person still has to do. Work through the "by hand" column before a release.

Status is what has actually been run on hardware, not what is believed to work.

- **automatic** — a test that runs in `Run-Tests.cmd` or one of the release tests.
- **done** — run on a real machine, with the date.
- **to do** — nobody has tried it.

## 1. Installing

| Feature | Covered by | Status |
| --- | --- | --- |
| Fresh Windows install from the ZIP, one double-click | `release/tests/install_test.ps1` | **done** 22 Sep 2026: 8 min 16 s, GTX 1060, cu118 chosen automatically |
| The right build for the graphics card (cpu / cu118 / cu128) | `tests/app/test_installers.py` reads the rules; the install test proves one | cu118 **done**; cpu and cu128 **to do** (run `Setup.ps1 -Mode CPU` into an empty folder; cu128 needs a 50-series card) |
| Falling back to the processor when the GPU build cannot run | — | **to do**: needs a machine whose driver is too old, or a forced failure |
| Repair over the top (`Repair.cmd`) | `install_test.ps1` (damages a library, repairs, re-verifies) | **done** 23 Sep 2026, twice: the install test, and by hand after deleting a library file. 6 min from the download cache |
| Refusing a too-long path, a OneDrive folder, too little disk | `tests/app/test_installers.py` (text only) | path and OneDrive **done** 23 Sep 2026 (both stop before downloading; `-AllowOneDrive` overrides). Disk space **to do** |
| "Install now" in the window when a piece is missing | — | **done** 23 Sep 2026: deleted the detector with the app open, red banner named it, the button opened its own window, re-downloaded and cleared |
| macOS install, Apple Silicon and Intel | `.github/workflows/mac-install.yml` | **to do**: needs the repository pushed, then run the workflow |
| Every package pinned by checksum; locks resolve per platform | `tests/app/test_installers.py`, `release/lock_requirements.py --check` | **automatic** |

## 2. Processing a library

| Feature | Covered by | Status |
| --- | --- | --- |
| Phases from video, sound and camera motion | `release/tests/package_smoke_test.py` | **done** 22 Sep 2026: 86 videos, 85 first time, 86 after the people fix |
| Counting people, and the 20% default | `tests/app/test_people.py`, `test_process.py` | **done** (7 of 86 videos produced no clips: worth a look) |
| Cutting clips, stream copy, `.360` clips keeping both lenses | `tests/app/test_cutting.py` | **done** for ordinary video; `.360` **to do** (no `.360` file on this PC) |
| 360 view modes: front, front and back, back | `tests/app/test_process.py` (stubbed) | **to do**: needs a `.360` file |
| Timeline CSV per video | `tests/app/test_timeline.py` | **done**: 86 CSVs |
| Keep watching, and a video copied in while it runs | `release/tests/soak_test.py` | **done** 23 Sep 2026, including a copy that stalls: nothing corrupted, retried by itself |
| Processor instead of the GPU (Advanced settings) | `tests/app/test_settings_health.py` (never reprocesses) | **done** 23 Sep 2026: the engine log reads "on cpu". Changing it alone reprocesses nothing, as intended |
| CSV only, no clips | `tests/app/test_process.py` | **done** 23 Sep 2026: CSVs written to their own folder, no new clips. It asks for a CSV folder first, as it should |
| Stop, and cancel the current video | `tests/app/test_window.py`, `soak_test.py` | **done** 23 Sep 2026: Stop finishes the current video, a second press offers to cancel, and the video is recorded as cancelled for next time |
| Process this video again | — | **done** 23 Sep 2026 (recovered the failed video) |
| A library that moved: new drive letter, renamed folders | `tests/app/test_relocate.py` | **automatic**; **done** by hand 23 Sep 2026: renamed the input folder, both videos recognised, no model run, same clip names |
| Clock changes on FAT32 cards; Mac `._` files; system folders | `tests/app/test_relocate.py` | **automatic** |
| A network drive, a full disk, a path over 260 characters | `tests/app/test_session.py` | **automatic** |

## 3. What comes out

| Feature | Covered by | Status |
| --- | --- | --- |
| Clip folder layouts: per video, per clip, flat, mirror | `tests/app/test_outputs.py`, `test_cutting.py` | **automatic**; all four **done** by hand 23 Sep 2026 |
| Clip names, output identity, manifests, cleanup of stale clips | `tests/app/test_outputs.py` | **automatic** |
| Thumbnails and the Results list | `release/tests/ui_test.py` | **done** 22 Sep 2026 (seen in the window) |
| "Show clips", "Open timeline CSV", "Open in Review" | `ui_test.py` | **done** 23 Sep 2026: Explorer on the clip folder, the CSV in the spreadsheet, and the Review tab on that video |

## 4. Keep profiles

| Feature | Covered by | Status |
| --- | --- | --- |
| Add, Edit, Duplicate, Remove, enable and disable | `ui_test.py`, `tests/app/test_window.py` | **done** 23 Sep 2026: Add and Duplicate open the editor, every field is there, Remove takes it away |
| The five presets | `tests/app/test_settings_health.py` | **automatic** |
| Phases, minimum people, minimum area, margins, minimum length, gap | `tests/app/test_profiles.py` | **automatic** |
| Two profiles at once, each cutting its own clips | `tests/app/test_process.py` | **done** 23 Sep 2026: two profiles, two clip sets, the longer margin visibly longer |

## 5. Reviewing

| Feature | Covered by | Status |
| --- | --- | --- |
| Review tab: every track on one axis, zoom, click to jump | `ui_test.py` | **automatic** (67 checks passed 23 Sep 2026); seen by hand too |
| "Check >" walking the disagreements | `ui_test.py` | **automatic**. Note: a disagreement starting at 0.0 s cannot be reached with "Check >" (the back button reaches it) |
| Correcting labels, "Mark reviewed and re-cut" | `package_smoke_test.py`, `ui_test.py` | **automatic** 23 Sep 2026: a label lengthened by 3 s moved the clip end by 3 s |
| "Not skydiving" removing the clips | `package_smoke_test.py`, `tests/app/test_process.py` | **automatic** |
| Playing a video and a clip in the window (sound and picture) | — | **to do**: only a person can judge this |
| The labeller window | `ui_test.py` (screenshots) | **automatic** 23 Sep 2026 |

## 6. Settings and state

| Feature | Covered by | Status |
| --- | --- | --- |
| Settings remembered, window size and columns remembered | `tests/app/test_window.py` | **automatic**; **done** in passing (folders survived a restart) |
| Changing a setting never reprocesses unless it must | `tests/app/test_settings_health.py` | **automatic** |
| Old settings files still load | `tests/app/test_monitor.py` | **automatic** |
| Health banner: red blocks, amber warns | `tests/app/test_window.py` | **done** (amber for the failed video) |

## What is left, and why

- **360 footage.** There is no `.360` file on this machine, so the three view modes and `.360` clips have only ever
  been tested with generated files in `tests/app`. A real GoPro MAX recording would settle it.
- **Playing video and sound in the Review tab.** The window builds and a clip stops at its end (checked), but whether
  the picture and sound actually play is something only a person can say.
- **macOS.** Nothing has run on a Mac. The workflow is ready; the repository has to be pushed first.
- **A processor-only install** (`Setup.ps1 -Mode CPU`) and a cu128 machine. Only cu118 has been installed for real.
- **Too little disk space.** The check exists and is cheap, but forcing it needs a nearly full drive.

## Suggested order for a release

1. `Run-Tests.cmd` — the fast tests, about a minute.
2. `release/lock_requirements.py --check` — about a minute.
3. `release/tests/ui_test.py` — the real window, 67 checks, about 4 minutes.
4. `release/tests/package_smoke_test.py --labels …` — end to end with human labels, a few minutes.
5. `release/tests/install_test.ps1` on the new ZIP, ideally in Windows Sandbox — about 20 minutes, and the only
   thing that exercises Repair.
6. By hand, in the app: the "to do by hand" rows above. Allow an hour.
7. macOS: the GitHub workflow, then a person on a real Mac for Gatekeeper, the privacy prompts and video playback.
