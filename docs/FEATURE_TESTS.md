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
| Repair over the top (`Repair.cmd`) | `install_test.ps1` (damages a library, repairs, re-verifies) | **to do** — rewritten in 2.4.0 and never run on hardware |
| Refusing a too-long path, a OneDrive folder, too little disk | `tests/app/test_installers.py` (text only) | **to do**: cheap, setup stops before downloading |
| "Install now" in the window when a piece is missing | — | **to do**: delete `yolo11n.pt`, start the app, click the button |
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
| Processor instead of the GPU (Advanced settings) | `tests/app/test_settings_health.py` (never reprocesses) | **to do**: process one video with "Processor only" |
| CSV only, no clips | `tests/app/test_process.py` | **to do** by hand: untick "Cut clips", process one video |
| Stop, and cancel the current video | `tests/app/test_window.py`, `soak_test.py` | **to do** by hand |
| Process this video again | — | **done** 23 Sep 2026 (recovered the failed video) |
| A library that moved: new drive letter, renamed folders | `tests/app/test_relocate.py` | **automatic**; **to do** by hand once, because it is new in 2.4.0 |
| Clock changes on FAT32 cards; Mac `._` files; system folders | `tests/app/test_relocate.py` | **automatic** |
| A network drive, a full disk, a path over 260 characters | `tests/app/test_session.py` | **automatic** |

## 3. What comes out

| Feature | Covered by | Status |
| --- | --- | --- |
| Clip folder layouts: per video, per clip, flat, mirror | `tests/app/test_outputs.py`, `test_cutting.py` | **automatic**; spot-check one of each by hand |
| Clip names, output identity, manifests, cleanup of stale clips | `tests/app/test_outputs.py` | **automatic** |
| Thumbnails and the Results list | `release/tests/ui_test.py` | **done** 22 Sep 2026 (seen in the window) |
| "Show clips", "Open timeline CSV", "Open in Review" | `ui_test.py` | **to do** by hand: each opens the right thing |

## 4. Keep profiles

| Feature | Covered by | Status |
| --- | --- | --- |
| Add, Edit, Duplicate, Remove, enable and disable | `ui_test.py`, `tests/app/test_window.py` | **to do** by hand |
| The five presets | `tests/app/test_settings_health.py` | **automatic** |
| Phases, minimum people, minimum area, margins, minimum length, gap | `tests/app/test_profiles.py` | **automatic** |
| Two profiles at once, each cutting its own clips | `tests/app/test_process.py` | **to do** by hand |

## 5. Reviewing

| Feature | Covered by | Status |
| --- | --- | --- |
| Review tab: every track on one axis, zoom, click to jump | `ui_test.py` | **to do** by hand |
| "Check >" walking the disagreements | `ui_test.py` | **to do** by hand |
| Correcting labels, "Mark reviewed and re-cut" | `package_smoke_test.py` | **to do** by hand |
| "Not skydiving" removing the clips | `package_smoke_test.py`, `tests/app/test_process.py` | **automatic** |
| Playing a video and a clip in the window (sound and picture) | — | **to do**: only a person can judge this |
| The labeller window | `ui_test.py` (screenshots) | **to do** |

## 6. Settings and state

| Feature | Covered by | Status |
| --- | --- | --- |
| Settings remembered, window size and columns remembered | `tests/app/test_window.py` | **automatic**; **done** in passing (folders survived a restart) |
| Changing a setting never reprocesses unless it must | `tests/app/test_settings_health.py` | **automatic** |
| Old settings files still load | `tests/app/test_monitor.py` | **automatic** |
| Health banner: red blocks, amber warns | `tests/app/test_window.py` | **done** (amber for the failed video) |

## Suggested order for a release

1. `Run-Tests.cmd` — 233 tests, about a minute.
2. `release/lock_requirements.py --check` — about a minute.
3. `release/tests/ui_test.py` — the real window, 67 checks, about 4 minutes.
4. `release/tests/package_smoke_test.py --labels …` — end to end with human labels, a few minutes.
5. `release/tests/install_test.ps1` on the new ZIP, ideally in Windows Sandbox — about 20 minutes, and the only
   thing that exercises Repair.
6. By hand, in the app: the "to do by hand" rows above. Allow an hour.
7. macOS: the GitHub workflow, then a person on a real Mac for Gatekeeper, the privacy prompts and video playback.
