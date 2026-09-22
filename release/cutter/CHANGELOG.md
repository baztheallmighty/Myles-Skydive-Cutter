# Changelog

## 2.4.0 (September 2026)

Installs you can rely on, on all three kinds of computer, and a library that survives being moved.

**Counting people**
- **The last moment of a video no longer loses the whole jump.** A video is sampled once a second, so a recording of
  257.507 seconds is sampled at 257.5: inside the video, but past its final frame. Reading nothing there counted as a
  damaged file and failed the video, although its phases, sound and motion had all succeeded. The frame just before it
  is used instead, and only if that cannot be read either does the last second count as nobody in frame. A failure
  anywhere earlier still stops the video. Found on a real library: 1 video in 86.

**Your library**
- **Moving things reprocesses nothing.** Unzipping a new version beside the old one used to change every video's
  fingerprint and process the whole library again. So did the library drive coming back as another letter. Now the
  person detector counts by name, the Clips folder is not part of the fingerprint (the record of finished work lives
  inside it), and ledgers written by 2.3 are still accepted.
- **Moved videos are recognised.** A video with the same name and content whose old place is gone keeps its phases,
  your reviewed labels and its clip names, instead of being classified again and cut a second time under a new name.
  A Clips folder that moved as a whole is followed too.
- **Clock changes do not count as edits.** A FAT32 card or drive read after the clocks changed, or in another time
  zone, shows every file whole hours out; those files now count as unchanged.
- **Mac sidecar files are skipped.** The `._GX010001.MP4` files macOS leaves on cards and shares, and system folders
  such as `$RECYCLE.BIN`, are no longer mistaken for footage.
- **Footage that cannot be read is reported.** A folder deeper than Windows' 260-character limit used to be left out
  without a word; the app now says which, and why.

**Installing**
- **Every package is pinned by checksum**, including the person detector's own dependencies, which used to install
  whatever was newest that day. Each platform has its own lock, built from the versions that passed the install test
  and checked against the platform before release. Pre-built packages only: nothing is ever compiled on your machine.
- **Repair repairs.** On Windows, `Repair.cmd` used to re-run setup without replacing anything, so a damaged library
  stayed damaged. It now reinstalls over the top (close the app first, and it says so if you have not).
- **Falls back to the processor.** If the NVIDIA build cannot use the graphics card (usually an old driver), Windows
  setup installs the processor build and says how to switch later, instead of failing on every start.
- **`Repair.cmd -Mode CPU` works**, as the messages always said it would: the launchers now pass on what you type.
- **Checks before downloading.** Windows setup stops early on a folder path too long for Windows or a folder inside
  OneDrive; Mac setup stops early on macOS older than 13 or less than 6 GB free.
- **Nothing is hidden from the setup log.** Everything pip prints is now in `logs\setup-<date>.log` on Windows.
- **Each download can have more than one source**, tried in order and checked against the same checksum. Windows'
  FFmpeg has a second copy on GitHub.
- **Mac FFmpeg follows its publisher.** osxexperts.net replaces its builds in place when FFmpeg updates, which broke
  the pinned checksum each time. Setup now takes the current build and checks that it runs and is FFmpeg 7 or newer.
- **Install now, on a Mac, opens a Terminal window** you can watch and fills in what is missing. It used to run a
  full repair out of sight, which deleted the Python the app was running on.
- **Intel Macs stay on the processor.** Some report an Apple GPU, but that path was never tested with these models.
- **The Mac launchers survive lost permissions** (only the `.command` file needs to be executable), the app keeps
  running when you close its Terminal window, and the README gives the Gatekeeper steps for macOS 15 and later.

**For whoever maintains it**
- The run loop is now `app/session.py`, testable without a window, with tests for a network share, a full disk, a
  drive unplugged mid-run and paths longer than Windows allows.
- `release/lock_requirements.py` writes and checks the locks; `release/privacy.py` checks everything git would publish
  for private strings; `release/tests/Start-SandboxInstallTest.ps1` runs the install test in Windows Sandbox; and
  `.github/workflows/mac-install.yml` installs a built Mac package on GitHub's Apple Silicon and Intel Macs.

## 2.3.2 (September 2026)

Mac installer fix. The first real-Mac test exposed two clean-machine assumptions that the Windows-side checks could
not reproduce.

- **No Xcode developer-tools prompt.** Setup now uses macOS's built-in `plutil` to locate the bundled Python download,
  then uses that bundled Python for all JSON work. It no longer invokes the `/usr/bin/python3` Xcode stub.
- **Works with the Bash shipped by macOS.** Download messages now delimit variable names explicitly and avoid the
  Unicode-adjacent expansion that Bash 3.2 reported as `filename…: unbound variable`.
- **Mac verification now completes.** It accepts Apple Metal (`mps`), checks the Mac names for FFmpeg and FFprobe,
  and reports the Apple GPU correctly. The desktop health check also tests Metal rather than CUDA on a Mac.
- **Intel dependency pins are internally consistent.** Intel uses NumPy 1.26 and OpenCV 4.11 with PyTorch 2.2.2;
  Apple Silicon keeps the newer stack. The minimum macOS version is corrected to 13 because the pinned OpenCV Mac
  wheel targets macOS 13.

## 2.3.1 (September 2026)

Housekeeping. Nothing about the app's behaviour changes, and processed videos are not reprocessed: the settings
fingerprint is identical.

- **1,510 fewer lines in the download.** The research command-line tools are gone from the package; the handful of
  functions the app actually used (person detection, clip spans and naming, audio windows) now live in the app.
- **One way to do each thing.** A single reader for a classifier run's result, one lookup per kind of phase question,
  one fewer layer between the queue and the model.
- **Settings that cannot surprise you.** Preferences such as the remembered window are marked as not affecting
  output, so adding one can never quietly reprocess a library.
- **The labelling window is marked frozen**, with a note saying where to change its behaviour instead.

## 2.3.0 (September 2026)

360 footage, handled properly.

- **`.360` files are processed.** GoPro MAX recordings were skipped entirely before, because the app only looked at
  ordinary video extensions.
- **Front view by default, with a choice.** Advanced settings > Processing > **360 videos** offers the front view,
  the front view with people counted all round, or the back view. The front view is what the models were trained on:
  on 86 labelled MAX jumps it is the most accurate footage the app handles.
- **Stitched 360 is recognised.** A 2:1 frame is now treated as 360 rather than as flat video, which matches the
  training data and measured better on labelled jumps.
- **People are counted through the same window as the phases.** Before, the detector saw the whole stored frame while
  the phase model saw a crop, so on 360 footage "20% of frame" meant 20% of the entire sphere.
- **Clips keep every lens.** A clip cut from a `.360` stays a `.360`, with both lens tracks, instead of losing half
  the sphere to a single-track copy.

## 2.2.0 (September 2026)

One thing to run, a window that fits a 1080p screen, and people counted by default.

- **One launcher.** `Skydive Cutter.cmd` is the only thing you run. It checks what this folder has, installs anything
  missing, then opens the app. A healthy install adds about a second to the start. Setup, the old start script and the
  people add-on are gone; `Repair.cmd` reinstalls, and `-Mode CPU`, `-Open review` and `-SkipCheck` remain as flags.
- **People detection is part of the app.** Installed with everything else, and on by default. New profiles keep a
  moment only when someone is in view: at least one person filling 20% of the frame. Whole skydive and canopy flight
  presets stay unfiltered, and a new Group freefall preset asks for two people at 30%.
- **It tells you what is missing.** A red banner names it, the advanced section that owns it turns red and opens, and
  **Process videos** is switched off until it is fixed, so a run never quietly ignores your people filters.
  **Install now** fixes it from inside the app. Amber is for things that only cost speed, such as no NVIDIA card.
- **Two columns.** Settings on the left, the results list on the right, with the run button, progress and log pinned
  along the bottom. Advanced settings are three folding sections rather than a panel that appears beside everything.
- **Sized for your screen.** The window opens to fit the monitor it is on, down to 1280 x 800 and up to a large
  display, and remembers its size, position, column split and which sections you left open.
- **People in view, on the Review tab.** A row under the motion trace shows how much of the frame people filled each
  second, a dashed line at what your profiles ask for, and shading on the seconds that clear it, so an empty or short
  clip explains itself. The video overlay adds the count at the current second.
- **Fix:** the Results list no longer freezes the window on a big library. Filling it re-measured every row for every
  cell; with 974 videos that took over two minutes, and switching back from Review looked like a crash. It now takes
  about a second.

## 2.1.0 (September 2026)

A faster review loop and a simpler window.

- **Open source:** Skydive Cutter is now licensed under the GNU GPL, version 3 (see LICENSE).

- **One window, two tabs.** The labeller is now the **Review** tab. Processing carries on while you review, and newly
  finished videos appear without interrupting you.
- **Your labels line up with every track.** Your editable timeline sits directly above Final, V4 video, audio and
  motion, on the same time axis. **Zoom** with Ctrl + mouse wheel, **+ / - / Fit** or **= / - / 0**; all rows zoom
  together.
- **Jump between the stretches worth checking** with **Check >** / **< Check** (C / Shift+C). The video list shows how
  many each video has.
- **Re-cut now:** **Mark reviewed and re-cut** (and **Not skydiving**) cut the video again at once, without running the
  model again.
- **Results list** on the Process tab: a thumbnail, status, labels used, clips, what needs a look and warnings for
  every video. Filter it, double-click a video to review it, or process it again.
- **Profile presets:** whole skydive, exit only, canopy flight, landing, and group freefall (people add-on).
- **Time estimate** for the queue, learned from this PC's speed.
- **Simpler Process tab:** two folders, the profiles, one **Process videos** button with **Keep watching for new
  videos**; everything else is under **Advanced settings**, which opens as a column beside the folders (Output,
  Processing, People), including a new choice of GPU or processor. Timeline CSVs go to `timelines` inside the Clips
  folder by default, or **Somewhere else** of your choosing. Drag folders from Explorer onto the folder boxes.
- **Clearer tick boxes and option buttons** in the dark theme.
- **Keep your folder structure:** a new **Clip folders** choice, **Same folders as the input videos**, recreates your
  input subfolders (for example `2024/Boogie/`) for the clips.
- **Review tab tidy-up:** a compact toolbar, phase chips that double as the colour legend, a one-line overlay (O hides
  it), motion trace gridlines, and clips you can click to play or open.
- **Faster reprocessing:** when only profiles or reviews change, a video reuses its phases from the last run instead
  of running the model again.
- **Fix:** no more console windows. FFmpeg no longer opens a black window over whatever you are doing while a
  video is processed.
- **Fix:** people detection keeps working after the app folder is moved or renamed.

## 2.0.0 (September 2026)

First standalone release.

- **New classifier (V4)** combining video, sound and camera motion. On 318 held-out jumps: 89.5% of seconds correct,
  and the default Exit + Freefall clip contains the whole exit and freefall on 85% of jumps (the previous model
  managed 46%).
- **Labeller built in:** **Review cuts in labeller** shows every processed video with Final, V4 video, audio, motion
  model, the g-force trace, an agreement strip and the clips cut, all lined up under the video. Correct a video, mark
  it reviewed, and its clips are re-cut from your labels on the next run.
- **Separate extra footage before and after** each clip. The default is 1 s before and 2 s after, because break-off
  (the end of freefall) is the least certain moment.
- **`sources_agree` column** in the timeline CSV marks moments where motion or sound disagreed with the result.
- **Standalone Windows package** with a one-click setup that installs everything into its own folder (NVIDIA GPU or
  CPU), and an install self-check.
- Person counting is now an **optional add-on** (`Add-People-Detection.cmd`), because its detector is AGPL-licensed.
