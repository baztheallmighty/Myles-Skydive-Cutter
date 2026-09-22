# Skydive Cutter: troubleshooting

[User guide](USER_GUIDE.md) · [Output and CSV reference](OUTPUT_REFERENCE.md) · [How it works](HOW_IT_WORKS.md)

## Setup fails

- **"Please free at least N GB"**: the NVIDIA setup needs about 20 GB free on the drive holding the folder, the
  processor setup about 8 GB. Free space or move the folder, then run setup again.
- **"This folder's path is N characters long"**: Windows limits a file's full path to 260 characters and the libraries
  install some files 150 characters deep. Move the folder somewhere short, such as `C:\SkydiveCutter`.
- **"This folder is inside OneDrive"**: move the folder out of OneDrive (Desktop, Documents and Downloads are often
  inside it). If you really want it there, run `Repair.cmd -AllowOneDrive` from a Command Prompt in the folder.
- **Download or checksum errors**: check the internet connection and run `Repair.cmd` again. Finished downloads are
  kept in `.downloads` and checked, so a retry continues where it stopped. Each download can have more than one
  source, and every file is checked against the checksum it was released with, whichever source it came from.
- **"Your NVIDIA driver is too old" or "The NVIDIA build could not use this GPU"**: setup has installed the processor
  build instead, so the app works, only more slowly. Update the NVIDIA driver from nvidia.com, close the app and run
  `Repair.cmd` to switch to the GPU.
- **"Close Skydive Cutter before repairing"**: `Repair.cmd` replaces the files the app runs from. Close the app window
  and run it again.
- **"Running scripts is disabled on this system"**, on a work or school PC: an administrator has set PowerShell's
  policy for the whole machine, which overrides the launcher. Ask them to allow it, or use a personal PC.
- **"Another setup is already running"**: wait for the other setup window to finish, or close it and try again.
- **Windows SmartScreen or antivirus blocks a `.cmd` file**: the launchers only start PowerShell scripts in the same
  folder. Choose *More info > Run anyway* if you trust the download, or unblock the ZIP (right-click > Properties >
  Unblock) before extracting.

The full setup log, including everything pip printed, is in `logs\setup-<date>.log`, and the install check's result
in `logs\verified-<cpu|cuda>.json`. The log's first lines name your Windows account and PC; remove them before sharing
if you prefer.

## The app will not open

Run `Skydive Cutter.cmd` from the complete, extracted folder. It installs anything missing before it opens the app, so
a first run can take a while; leave the window open.

If nothing appears, look at the newest `logs\app-<date>.stderr.log`. Avoid starting extra copies while diagnosing the
first one.

## The Review tab is empty or shows a message

- It shows the videos processed into the **Clips** folder currently set on the Process tab (the CSV folder in CSV-only
  mode). Set the same folders you processed with.
- "Nothing has been processed into this folder yet": process some videos first.
- "This folder is already open in another labeller window": another copy of Skydive Cutter (or an older labeller) has
  that folder open. Close it and switch tabs again.
- Videos that were moved or deleted since processing are left out.

## A reviewed video was not re-cut

The Results list shows *(re-cut pending)* until it is. The re-cut starts when you click **Mark reviewed and re-cut**
(or **Not skydiving**), unless **Re-cut a video as soon as you mark it reviewed** is off under Advanced settings; then
it happens the next time you click **Process videos**. If processing is already running, the video is re-cut next, after
the current one. Editing a reviewed video's labels does not change its clips until you mark it reviewed again.

## There is no time estimate

The estimate appears after the first video has been processed on this PC. It also needs the length of every queued
video, which can take a few seconds to read for a large batch. Videos re-cut from your labels are too quick to count
towards it.

## "People detection is not installed" in red

The detector or its model file is missing, so the app will not process with people filters in your profiles. Click
**Install now** in the banner, or run `Repair.cmd`. If you would rather cut on phases alone, open Advanced settings >
What to keep and set every profile's people and area to 0.

## It is watching, but nothing happens

- Allow two unchanged file observations. The default interval between checks is five seconds.
- Confirm the files are non-empty and have a [recognized extension](USER_GUIDE.md#running-a-batch-or-monitoring-a-folder).
- Check the input contains original videos. Output directories are excluded from scanning.
- Successful, unchanged videos with the same settings are skipped. **Process Existing Now** is not a force-reprocess button.
- **Process Existing Now** includes only files present at the start. Use another batch or **Start Monitor** for later arrivals.

For a separate regenerated set, choose a fresh Clips destination when cutting, or a fresh CSV destination in CSV-only mode. Choose a fresh CSV destination too when preserving earlier timelines matters.

## There is a CSV, but no clips

Check **Create** first: **CSV only — no clips** intentionally creates none.

When cutting is enabled, enable at least one profile. With phase identification on, it needs a matching selected phase. People thresholds can exclude all samples, and **Minimum span** can reject short matches. Inspect `matched_profiles` and the profile manifest. A header-only manifest means that profile produced no clips.

The CSV is written before cutting. Failure or cancellation during cutting can leave a CSV without a complete clip set. Check the final status and log, correct the cause, and start another session to retry.

## Clips start early, overlap, or include unwanted moments

Profile margins, bridging non-matching dips, and merging padded spans within one second can add context. Stream copying can also start at an earlier keyframe.

Reduce margins or gap bridging if they add too much footage. Even with both zero, cutting is not frame-accurate. Separate profiles can intentionally produce overlapping clips. See [How matching becomes clips](OUTPUT_REFERENCE.md#how-matching-becomes-clips).

## People count or coverage looks wrong

Small, obscured, blurred, or distant people can be missed. Raising **Person detection threshold** accepts fewer detections; lowering it can admit false detections. **Samples per second** changes inspection frequency, not the meaning of the count.

Coverage measures bounding rectangles, including background inside them. Total coverage sums rectangles with overlaps, so values above 100% are possible. Adjust profile thresholds to suit the footage. Model and detector scores are not guarantees of accuracy.

## Phase classification fails

**Standard** requires at least two seconds and is intended for one jump per video. Confirm the source plays and copying has finished. Very unusual formats (for example raw 360 files straight from a dual-lens camera) may classify poorly; export a normal flat video first.

The warning gives a diagnostic log location. Keep it if you need to ask for help. If only people-based selection is needed, stop the session, disable **Identify jump phases**, and start another run; phase filters will be ignored.

"Out of memory" on a small graphics card: close other programs that use the GPU. If it keeps happening, run `Repair.cmd` with `-Mode CPU` to use the processor instead (slower but reliable). Errors about missing model files mean the folder is incomplete: extract the ZIP again and rerun setup.

## A video cannot be read or cut

Open the original in a video player. A recognized extension does not guarantee supported or undamaged encoding. A people-sample error at a particular timestamp can indicate a frame the decoder cannot read.

Cutting copies source encoding into MP4. A video can classify successfully yet fail cutting if its encoding cannot be copied into that container. Keep the error and the source format details if you ask for help. The GUI has no transcoding setting.

## A source changed during processing

Let copying or modification finish, then start another session to retry. The app checks size and modification time during processing. A detected change prevents successful completion being recorded. Outputs can already exist if the change happened late during cutting, so use the final status to judge completion.

## I moved my videos, or the drive has a different letter

Nothing is classified again. A video with the same name and content whose old place no longer exists is recognised as
moved: its phases, your reviewed labels and its clip names carry over, and the app only reads the file once to check
it is the same one. A Clips folder that moved as a whole is followed too. If the Review tab is open when a moved video
with reviewed labels comes up, that video waits with a message: close the Review tab and process again. The review
files are backed up (`*.before-move-*`) before they are changed.

## Access denied, file in use, or insufficient space

Check the destination is available and writable, including removable or network drives. If Windows Security's
**Controlled folder access** is on, it stops the app writing clips into Documents, Pictures, Videos and Desktop: allow
`pythonw.exe` from the app's `.runtime` folder under *Windows Security > Virus & threat protection > Ransomware
protection > Allow an app through Controlled folder access*, or choose a Clips folder elsewhere. Close an output CSV in spreadsheet software or a clip in a player if it holds the destination open. Check free space: replacement needs room for temporary new clips alongside existing ones.

After resolving the cause, start another session. Failed and cancelled videos can be retried; an unchanged failed video is not repeatedly retried within the same session.

## Output conflict or another session using the destination

An ownership or identity conflict means the app cannot safely treat an existing destination file as its own result. Choose a fresh destination, or ask for help with the conflicting records. Do not edit ownership fields to force an overwrite.

A session-lock error can mean another instance is processing into that active destination. Let it finish or use a separate destination. Do not delete lock or state files during processing.

## Progress is busy, decreases, or reaches 100% with failures

A busy video bar means a stage has not reported a measurable total. Classification can take time between updates. Progress represents work, not time estimates.

Queue percentage can decrease when new files join. It reaches 100% when all attempts finish even if some fail or are cancelled; read the counts. Work left queued when stopping is shown as left for the next run.

Click **Stop Monitor** to finish the current video, or click **Cancel current video…** afterward and confirm. Published outputs remain. See [Stopping, cancelling, and closing](USER_GUIDE.md#stopping-cancelling-and-closing).

## The labels look wrong for a video

Double-click it in **Results** to open it on the Review tab. **Check >** (C) jumps to each stretch where motion or audio disagreed with the result. Correct the labels and click **Mark reviewed and re-cut**: the video is re-cut from your labels at once. Break-off is the least certain phase; the default 2 s of extra footage after each clip allows for it.

## Details to keep when asking for help

Record the warning and nearby activity-log messages, mode and layout, enabled classifiers, profile settings, source duration and format, and whether other videos succeed. Include the diagnostic log identified by the warning when available. Startup errors are in the `logs` folder; classifier diagnostics are in the active destination's `_state/classifier-runs`.

Logs and CSVs can contain source paths and filenames. Share only what is needed for the issue. Do not alter saved settings, completion records, or manifests while processing is active.
