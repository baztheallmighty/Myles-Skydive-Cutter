# Developing Skydive Cutter

For using the app, see the [Windows README](../release/cutter/README.md) or the [Mac README](../release/mac/README-mac.md).
This is for whoever changes it. [TESTING.md](TESTING.md) covers the tests.

## Where things are

| Folder | What it holds |
| --- | --- |
| `app/` | The desktop app. `app/ui/` is the window; everything else has no Qt and is tested without one. |
| `app/session.py` | One processing run: the ledger, the queue, what counts as done. The window only drives it. |
| `app/monitor.py` | Scanning the input folder, the ledger's decisions, and processing one video. |
| `app/relocate.py` | Recognising a video or Clips folder that moved, and pointing its records at the new place. |
| `app/system.py` | Everything that differs between Windows and macOS. Nothing else asks what platform it is on. |
| `cutter_v4/` | The phase engine (`engine.py`, run as a subprocess), its models (`models/`), and the Review tab's data. |
| `v3_poc/`, `v4_survey/` | Inherited modules the engine and the labeller still use. `_labeler.py` and `review.py` are frozen. |
| `release/` | The package builder, the installers (`cutter/` for Windows, `mac/`), the lock files and the release tests. |
| `tests/app/` | The fast tests: about a minute, no GPU. |

## Running it from a checkout

Python 3.12 with the packages in `release/cutter/requirements-windows.txt` and one of `release/cutter/torch-*.txt`
(or `release/mac/requirements-mac-*.txt`), plus FFmpeg on `PATH`:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes --no-deps -r release\cutter\torch-cpu.txt --index-url https://download.pytorch.org/whl/cpu
.venv\Scripts\python.exe -m pip install --require-hashes --no-deps -r release\cutter\requirements-windows.txt
.venv\Scripts\python.exe -m pip install pytest
.\Run-SkydiveCutterApp.ps1        # the app
.\Run-Tests.cmd                   # the fast tests
```

The model weights are stored with Git LFS; run `git lfs pull` if `cutter_v4/models/visual.pt` is a few hundred bytes.

## Making a release

1. Update `VERSION` in `release/build_cutter_package.py` and add the changes to `release/cutter/CHANGELOG.md`.
2. If a package version changed, update `release/locks/tested-windows.txt` from a runtime that passed the install test,
   then `python release/lock_requirements.py` (writes the locks and checks each resolves for its platform).
3. `python release/build_cutter_package.py` and `python release/build_cutter_package.py --mac`. Each stops, and zips
   nothing, if a private string or a console-opening subprocess is found.
4. Run `release/tests/install_test.ps1` on the Windows ZIP, ideally in Windows Sandbox
   (`release/tests/Start-SandboxInstallTest.ps1`).
5. `python release/privacy.py`, then push, and attach both ZIPs and their `.sha256` files to a GitHub Release.
6. Run the **macOS install** workflow (Actions tab) with the Mac ZIP's release address and checksum.

`release/private-patterns.txt` holds your own private strings (names, drive and folder names) for the privacy checks.
Git ignores it, and the builder and `privacy.py` refuse to run without it.

## Rules that are easy to break

- **The fingerprint decides what is processed again.** Every setting in `app/settings.py` either changes the
  fingerprint or is marked `preference(...)`; `tests/app/test_settings_health.py` fails if a new one is neither. Where
  the app, the library or the Clips folder is must never count: moving them must not reprocess a library. Ledgers
  written by older fingerprint formats stay valid through `accepted_fingerprints`.
- **Output names are identities.** A video's clips are named from its path and content at first processing, and keep
  that name if it moves (`app/relocate.py`). Cleanup only ever removes a clip whose manifest row matches exactly.
- **Missing pieces block in red**, rather than quietly producing clips that ignored the people filters.
- **The person detector is downloaded, never shipped.** Ultralytics is AGPL-3.0; keeping it out of the ZIP keeps the
  AGPL out of what is distributed.
- **Front view is the trained view** for 360 footage. An unwrapped rectilinear view looks better and scores worse.
- **The package is an allowlist** (`FILES` in `release/build_cutter_package.py`). A new module must be added there;
  `tests/app/test_installers.py` fails if the app imports one that is not.
- **Every child process is hidden** on Windows (`app/system.hidden_process`), or it opens a console over the app. The
  builder refuses to zip otherwise.

## Adding or replacing a phase classifier

1. Write an adapter with `predict(source, settings, runner) -> PhaseResult` (see `app/classifiers/v4.py`).
2. Register a `Classifier(identifier, display_name, revision, predict, minimum_duration)` in
   `app/classifiers/__init__.py`. Keep heavy imports inside the callable.
3. Return ordered, contiguous intervals from zero to `duration_sec` using the nine phase labels.
4. Change `revision` whenever weights or rules change: it is part of the fingerprint, so videos are reprocessed.
5. Log briefly through `runner.log`, report measurable work through `runner.report_progress`, and keep raw
   diagnostics in the run folder.
