# How this app is tested

This is about the app and the process it follows, not about how accurate the models are. Model accuracy is measured
separately against human labels (see `release/cutter/docs/TESTED.md`).

## The short version

```bat
Run-Tests.cmd            :: the fast checks: about half a minute, no GPU
Run-Tests.cmd ui         :: adds the real window on the demo videos
Run-Tests.cmd full       :: adds the install check
```

To test with a Python outside this folder, set `SC_PYTHON` to it first. See [DEVELOPMENT.md](DEVELOPMENT.md) for
setting one up.

[FEATURE_TESTS.md](FEATURE_TESTS.md) is the other half of this: every feature, what covers it, and what a person
still has to try before a release.

## The layers

| Layer | Where | Needs | Time | What it proves |
| --- | --- | --- | --- | --- |
| Logic | `tests/app/test_{settings_health,outputs,profiles,timeline,cutting,monitor}.py` | nothing | seconds | Settings, the fingerprint, health, spans, naming, timeline rows, ledger decisions |
| Process | `tests/app/test_process.py`, `test_process_edges.py` | ffmpeg | ~10 s | A real video through the whole process with a stub model: timeline, clips, layouts, reviewing, excluding, cancelling, damaged state, 360 files |
| Session | `tests/app/test_session.py`, `test_relocate.py` | ffmpeg | ~15 s | The run loop with no window: what is queued and remembered, a network share, a full disk, a drive unplugged mid-run, a path over 260 characters, and a library that moved |
| Installers | `tests/app/test_installers.py` | Git Bash, PowerShell (else skipped) | ~2 s | The locks are complete and hashed; the Mac scripts obey Bash 3.2 and run for real against stand-in macOS commands; the Windows scripts parse |
| Window | `tests/app/test_window.py` | Qt offscreen | ~6 s | What the window remembers, what it blocks, where a dropped folder lands |
| Scale | `tests/app/test_scale.py` | Qt offscreen | ~20 s | A thousand videos still appear quickly; with `SKYDIVE_BIG_LIBRARY` set, a real library is timed |
| Interface | `release/tests/ui_test.py` | GPU, real videos | ~4 min | The real window end to end, including the Review tab, the labeller and screenshots |
| End to end | `release/tests/package_smoke_test.py` | GPU, real videos | ~3 min | The packaged app on real jumps, against human labels |
| Locks | `release/lock_requirements.py --check` | internet | ~1 min | pip's resolver accepts every lock for its platform (Windows cpu/cu118/cu128, Apple Silicon, Intel Mac on macOS 13), without installing anything |
| Install | `release/tests/install_test.ps1`, or `Start-SandboxInstallTest.ps1` to run it in Windows Sandbox | a clean machine | ~20 min | What a stranger gets: extract, install, a damaged library repaired, and a missing piece reported |
| Mac install | `.github/workflows/mac-install.yml` | a built Mac ZIP at a URL | ~40 min | A clean install, check and repair on GitHub's Apple Silicon and Intel Macs, with the system Bash 3.2 |
| Soak | `release/tests/soak_test.py` | GPU, hours | as long as you like | Keep-watching over time: no leak, no video processed twice, no stall |

## The stub model

`tests/app/conftest.py` registers a classifier that returns whatever phases a test asks for and writes the same
`result.json` a real run leaves behind. That is what makes the process testable in seconds: the model is not the
subject, the process is.

## Rules that keep this honest

- **The fast layers run before every commit.** If a layer is not run automatically, assume it is broken: the app's
  unit tests sat broken for nine days because nothing ran them.
- **A test that has never failed has proved nothing.** When fixing a bug, check the new test fails against the old
  behaviour first. The scale test is annotated where it could not reproduce the original freeze, rather than
  pretending it does.
- **Tests own their fixtures.** The interface test snapshots the processed demo and restores it, so reruns cannot
  inherit the last run's edits.
- **Budgets are generous on purpose.** A performance test that fails on a busy machine gets ignored, which is worse
  than not having it.

## Things worth adding next

- The Review tab's own behaviour is only covered by the interface test; the labeller is frozen, so this is deliberate.
- A real Mac. The Mac workflow and the Bash stand-ins cover the scripts, but only a person on a Mac sees Gatekeeper,
  the privacy prompts and whether Qt plays the videos.
- A development PC is not a clean machine. Run the install test in Windows Sandbox before a release
  (`release/tests/Start-SandboxInstallTest.ps1`; the Sandbox feature must be switched on first).
