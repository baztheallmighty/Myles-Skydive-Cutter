# Skydive Cutter: troubleshooting

[User guide](USER_GUIDE.md) · [Output and CSV reference](OUTPUT_REFERENCE.md) · [How it works](HOW_IT_WORKS.md)

## The installer

- **"Windows protected your PC" (SmartScreen)**: the installer is not code-signed, because this free project does not
  buy a certificate. Choose **More info**, then **Run anyway**. The download's SHA-256 checksum is published beside
  it if you want to check the file first.
- **"Setup has detected that Skydive Cutter is currently running"**: close the app window, then choose Retry. The
  same message appears when uninstalling.
- **The download window closed early, or the PC was switched off during it**: start Skydive Cutter from the Start
  menu. It lists what is missing in red and **Install now** continues from the files already downloaded.
- **The download window stopped with a red message**: it stays open so you can read it. The causes are the ones
  under [Setup fails](#setup-fails) below. After fixing the cause, start the app and click **Install now**, or run
  `Repair.cmd` in the install folder.
- **Where it is installed**: `%LOCALAPPDATA%\Programs\Skydive Cutter` unless you chose another folder. Paste that
  into Explorer's address bar to open it; `Repair.cmd` and the `logs` folder are there.
- **Uninstalling**: Windows **Settings > Apps**, find Skydive Cutter, **Uninstall**. It removes the app and what it
  downloaded, and asks about your settings. Clips, timelines and your videos are never removed. Then delete the
  folder if you no longer want the settings file left in it.
- **Upgrading**: run the newer installer. It replaces the app and keeps your settings and everything already
  downloaded; nothing is processed again because of the upgrade.

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

With the installer, start it from the Start menu. Nothing appears for a few seconds while the install is checked,
then the window opens; if something is missing, a setup window you can watch opens instead. From the ZIP, run
`Skydive Cutter.cmd` from the complete, extracted folder. Either way it installs anything missing before it opens
the app, so a first run can take a while; leave the window open.

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
the ones in progress. Editing a reviewed video's labels does not change its clips until you mark it reviewed again.

## There is no time estimate

The estimate appears after the first video has been processed on this PC. It also needs the length of every queued
video, which can take a few seconds to read for a large batch. Videos re-cut from your labels are too quick to count
towards it.

## "People detection is not installed" in red

The detector or its model file is missing, so the app will not process with people filters in your profiles. Click
**Install now** in the banner, or run `Repair.cmd`. If you would rather cut on phases alone, use **Trim my footage**
on the Basic screen, which does not look for people, or on the Advanced screen set every profile's **People in view**
and **People fill** to 0.

## It is watching, but nothing happens

- A video is processed once its size and date have stopped changing: two checks, five seconds apart.
- Confirm the files are not empty and have a [recognised extension](USER_GUIDE.md#processing-videos).
- Check the videos folder holds the original videos. Output folders are left out of the scan.
- Finished, unchanged videos with the same settings are skipped. **Process videos** is not a force-reprocess button;
  to run a video again from scratch, select it in Results and click **Process again**.
- Without **Keep watching for new videos** ticked, only the videos present when you clicked are processed.

For a separate regenerated set, choose a new **Save clips to** folder (or a new timelines folder with timelines only).

## There is a CSV, but no clips

Check **What to produce** first: **Timelines only - no clips** intentionally creates none.

Otherwise open the video on the Review tab and look at the **Why not kept** row. It gives the reason for every second:
another part of the jump, nobody found, too few people, people too small, or a match too short. The usual causes:

- **Nobody was found.** Distant jumpers and people seen from behind are the detector's weak spot. Try a larger
  **Person detector**, or lower **People fill at least**.
- **People were found but are small in the picture.** One person at 3% does not pass a profile that asks for 20%.
  B grade asks for 10%; Trim my footage asks for nobody.
- **The matches are short and scattered.** Raise **Join matches separated by up to**, or use **Join gaps while people
  are still in view**, or lower **Ignore matches shorter than**.
- **No jump was found** in the video (a ground video, or one that starts under canopy).

The CSV is written before cutting. Failure or cancellation during cutting can leave a CSV without a complete clip set.
Check the Status column, correct the cause, and process again.

## Clips start early, overlap, or include unwanted moments

**Start each clip earlier by**, **End each clip later by**, the two joins, and merging clips that end up within one
second of each other can all add footage. Copying the video data without re-encoding can also start a clip at an
earlier keyframe.

Reduce the extra footage or the joins if they add too much. Even with all of them at zero, cutting is not
frame-accurate. Separate profiles can produce overlapping clips on purpose: B grade contains everything A grade does.
See [How matching becomes clips](OUTPUT_REFERENCE.md#how-matching-becomes-clips).

## People count or coverage looks wrong

The Review tab shows what was found: **People found** is the count each second and **Picture filled** the percentage,
each with a dashed line at what the profile asks for.

- **Skydivers are missed**, especially far away, from behind, or head-down. The detector that comes with the app is
  small and fast. Put a larger one (for example `yolo26x.pt`, from Ultralytics' release page) in the app folder and
  choose it under Advanced settings > People > **Person detector**. On two test videos the largest found two or more
  people in 93% of the seconds where the standard one managed 70%. It is slower, and finished videos have their
  people counted again.
- **The count is one too high** under canopy or on landing: your own legs or arms count as a person.
- Raising **How sure it must be that it is a person** accepts fewer detections; lowering it finds more people and
  more mistakes. **Checks per second** changes how often the video is looked at, not what the count means.

Coverage measures rectangles round each person, background included, and adds them up, so overlapping people can
exceed 100%. A larger detector barely changes the percentage; it mostly changes the count.

## Phase classification fails

The video must be at least two seconds long, and the model expects one jump per video. Confirm the original plays and
that copying it has finished.

The warning gives the location of a diagnostic log. Keep it if you need to ask for help. If you only need to select on
people, turn off **Work out the parts of each jump** under Advanced settings > Processing and run again; the parts of
the jump ticked in each profile are then ignored.

"Out of memory" on a small graphics card: set **Videos at once** to 1, close other programs that use the graphics
card, and lower **Graphics memory use (batch size)**. If it keeps happening, run `Repair.cmd -Mode CPU` to use the
processor instead (slower but reliable). Errors about missing model files mean the install is incomplete: run
`Repair.cmd`, or install again.

## Processing is slow, or the PC is unusable while it runs

- **Videos at once** set too high slows everything down. Past the point where the graphics card is full, more videos
  only wait on each other: on the test PCs an RTX 5090 was fastest at four and a GTX 1060 at two. **Automatic** adds
  a video only while there is room.
- Most of the time goes on reading the video, and 4K at 60 frames a second is eight times the work of 1080p at 30.
  **Read videos with: Automatic** uses the graphics card for this when it can; check it has not been left on
  Processor only.
- **Trim my footage** on its own is the quickest choice, because it does not look for people.
- A larger **Person detector** is slower.
- The log shows how long each step took for every video, which says where the time goes on your PC.

## A video cannot be read or cut

Open the original in a video player. A recognised extension does not guarantee supported or undamaged encoding. A
people-counting error at a particular time can point to a frame that cannot be read. If videos fail to read only with
**Read videos with** on Automatic, set it to **Processor only** and update the graphics driver; normally the app
falls back to the processor by itself, even part-way through a video.

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

A moving bar with no percentage means that step has not reported how much work there is. Working out the parts of the
jump can take a while between updates.

The queue percentage can go down when new files join. It reaches 100% when every video has been attempted, even if
some failed or were cancelled; read the counts. Videos still queued when you stop are left for the next run.

Click **Stop** to finish the videos in progress, or click it again (**Cancel current video...**) and confirm to stop
those too. Clips already saved remain. See [Processing videos](USER_GUIDE.md#processing-videos).

## The labels look wrong for a video

Double-click it in **Results** to open it on the Review tab. **Check >** (C) jumps to each stretch where motion or audio disagreed with the result. Correct the labels and click **Mark reviewed and re-cut**: the video is re-cut from your labels at once. Break-off is the least certain phase; the default 2 s of extra footage after each clip allows for it.

## Details to keep when asking for help

Record the app's version, the warning and nearby log messages, whether you were on Basic or Advanced, the profiles in use and their settings, how the clips are organised, **Videos at once**, the video's length and format, and whether other videos succeed. Include the diagnostic log identified by the warning when available. Startup errors are in the `logs` folder; classifier diagnostics are in the active destination's `_state/classifier-runs`.

Logs and CSVs can contain source paths and filenames. Share only what is needed for the issue. Do not alter saved settings, completion records, or manifests while processing is active.
