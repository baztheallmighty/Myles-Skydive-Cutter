# Changelog

## 2.5.0 (October 2026)

Faster processing, several videos at once, and an explanation beside every setting.

- **A Basic screen.** Two folders and three choices: Trim my footage (with an optional landing), A grade for day
  tape (with optional canopy), and B grade. Any or all run together, each into its own folder, with clips named
  after the video they came from. A new install opens here; an existing one opens on Advanced as before.
- **Safer and clearer to use.** The mouse wheel no longer changes a drop-down or number it happens to pass over
  while you scroll the settings; click one first to change it with the wheel. Profiles in use are highlighted, with
  a sentence under the list saying what a run will keep. Long help notes no longer lose their last lines, and a
  help button returns to normal after its note closes.
- **Results list:** select several videos (Ctrl, Shift, or Ctrl+A) and process them again together; click a column
  title to sort; columns fit the list and can be dragged to resize.
- **Videos at once goes up to 10**, then Automatic.
- **The three choices are built-in profiles** on the Advanced screen, editable like any other.
- **A folder per profile.** New way to organise clips, and a "Folder" field on each profile: a name inside the clips
  folder, or a full path to put that profile's clips anywhere.
- **About twice as fast again, with the same results.** Measured on 24 jump videos (62 minutes, mostly 4K60): a fast
  PC went from 15.3 to 7.6 minutes one at a time and 3.5 minutes four at once; a GTX 1060 laptop went from 38.4 to
  25.7 minutes, and 17.2 two at once. Every timeline is identical to before. Frames the models do not need are
  dropped on the graphics card before being copied back; the classifier loads and analyses sound while the picture is
  being read; and a new video's checksum is worked out alongside, which matters on a hard disk.
- **Fixed: several videos at once on a fresh install broke sound analysis for good.** The first run filled a compile
  cache from several classifiers at once and left it damaged, after which every video failed. One classifier now
  fills it while the others wait, and a cache nobody vouches for is rebuilt.
- **Changing a profile no longer reads the video again.** The people already counted are reused when the file, the
  detector and its settings are the same.
- **Older FFmpeg is handled** (before 5.1 an option had another name).
- **Each video's picture is read once, not twice.** Counting people and working out the parts of the jump used to
  unpack the video separately. One read now feeds both. On a 3-minute 1080p60 video on the test PC, reading went from
  48 s to 22 s. The copy the phase model looks at is identical, frame for frame, so the phases do not change.
- **The graphics card unpacks the video when it can.** New setting, Advanced settings > Processing > **Read videos
  with**. Automatic tries the graphics card on each video and uses the processor if that fails, including part-way
  through. The picture is identical either way.
- **Several videos at once.** New setting, **Videos at once**: 1 (the default), 2, 3, 4 or Automatic. Automatic adds
  a video only while the processor, memory and graphics card have room. Each video in progress has its own progress
  bar, and Stop finishes or cancels all of them. Results are the same however many run together.
- **A "?" beside every setting**, with a plain explanation and a warning where a change goes through finished videos
  again. Several settings are renamed to say what they do: for example "Detection threshold" is now "How sure it must
  be that it is a person", and "Bridge non-matching dips" is "Join matches separated by up to".
- **"People in view" says it includes you.** Under canopy and on landing your own legs or arms count as a person.
  The profile editor now says so beside the number when it applies, and writes out in one sentence what the profile
  keeps.
- **People are counted on the exact frame for each second.** The old reader occasionally returned a different frame
  on 10-bit DJI video, and 360 footage was looked at half a second early. On the DJI test video this changes whether
  the default profile matches on 7 of 192 seconds; on the GoPro test video nothing changes. Finished videos are not
  reprocessed for this; it applies to videos processed from now on.
- **Review shows people as two things, and says why a moment was left out.** "People found" (the count) and
  "Picture filled" (the percentage) are separate rows, each with its own bar to clear, and a new "Why not kept" row
  gives the reason for every second: nobody found, too few people, people too small, and so on. Each row prints its
  value at the playback position, and the readout beside the mouse now updates as you move (it used to appear once).
  With several profiles in use, a drop-down chooses which one the rows are judged against.
- **A join that asks who is still there.** Two new profile settings: "Join gaps while people are still in view, up
  to (seconds)" and "People still in view means at least". A gap between two matches is filled while enough people
  are still found, however small they are in the picture; a short look-away inside it is allowed up to the ordinary
  join. Off by default, and upgrading reprocesses nothing. Review marks these seconds "joined: people still in view".
- **A choice of person detector.** Advanced settings > People > **Person detector** lists the detectors whose files
  are in the app folder. On two test jumps the largest (`yolo26x.pt`) found two or more people on 93% of exit and
  freefall seconds against 70% for the standard one. The installer still fetches only the standard detector.
- **Insta360 X5 motion data is read** (`.insv`), for the motion check. The app does not yet take `.insv` as input.
- **The log says where the time went** for every video: checking, reading and counting people, phases, cutting.

## 2.4.3 (September 2026)

Installs on Intel Macs. No change to the app or its results on any computer.

- **Intel Mac setup no longer stops at "Motion model missing".** The motion model carried a leftover from its
  training, a random-number generator in a form only NumPy 2 can read, and Intel Macs have to use NumPy 1.26 (the
  last PyTorch for Intel Macs needs it). Every Intel Mac install since 2.4.0 failed at the final check with "motion
  model unavailable (ValueError)". The model is saved again without it. It gives identical answers: every prediction
  on 5,000 test inputs matches 2.4.2 exactly, under both NumPy 1.26 and NumPy 2.
- A new check stops any release whose models NumPy 1.26 could not load.

## 2.4.2 (September 2026)

A dropped connection during setup no longer leaves a PC with a good NVIDIA GPU on the processor. Every download now
comes from the project's own site, or from a site that project links to.

- **A failed download no longer counts as a GPU problem.** Windows setup used to install the processor build
  whenever anything went wrong while installing the NVIDIA build, including a dropped connection, and then said the
  GPU could not be used. Now only a GPU that fails its check falls back; a failed download stops setup, and running
  it again continues from what was already downloaded. Each download also gets three tries before its next source.
- **Choosing a GPU the install cannot use stops processing at once.** The check used to run only when the app
  opened, so choosing NVIDIA GPU afterwards, or a re-cut from the Review tab, sent every video to a GPU that was not
  there and each failed with "Check that it plays correctly". The app now checks again whenever the setting changes
  and before any run starts, and if the processor build is installed it says how to get the GPU build.
- **Mac FFmpeg comes from evermeet.cx**, the macOS build site ffmpeg.org links to, instead of osxexperts.net, which
  ffmpeg.org does not link to. The files are versioned (FFmpeg 9.0.2), so they are no longer replaced under the same
  name. They are Intel programs, so on Apple Silicon setup first checks for Apple's Rosetta 2 and, if it is missing,
  says how to install it.
- **Mac setup installs from PyPI only**, as Windows setup already did, whatever the Mac's own pip settings say.
- The third-party notices now list where each platform's Python and FFmpeg come from.

## 2.4.1 (September 2026)

Installs you can rely on, on all three kinds of computer, and a library that survives being moved.

This release was installed from its own ZIP on a clean folder, processed a library of 86 jumps, and had every part of
the window clicked through. What that found is fixed here; see the test record in the repository.

**Privacy**
- **The person detector's usage statistics are switched off by setup again.** The command that does it was quoted in a
  way PowerShell mangled, so it failed silently on Windows and left a traceback in the setup log. Nothing was sent
  meanwhile (the app switches them off itself before it loads the detector), but the first run no longer depends on
  that.

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
