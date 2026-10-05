# Skydive Cutter: user guide

Skydive Cutter scans a folder of footage, identifies the jump phases in each video, and saves matching clips and CSV
timelines. Profiles describe which moments to keep. The **Review** tab shows what was cut and lets you correct it; a
corrected video is re-cut straight away.

The app only reads your original videos; it never renames or edits them.

Also see the [Output and CSV reference](OUTPUT_REFERENCE.md), [How it works](HOW_IT_WORKS.md) and
[Troubleshooting](TROUBLESHOOTING.md).

## Contents

- [First run](#first-run)
- [Basic and Advanced](#basic-and-advanced)
- [The Process tab](#the-process-tab)
- [Keep profiles](#keep-profiles)
- [Processing videos](#processing-videos)
- [The Results list](#the-results-list)
- [The Review tab](#the-review-tab)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Advanced settings](#advanced-settings)
- [360 footage](#360-footage)
- [When something is missing](#when-something-is-missing)
- [Reprocessing and keeping results](#reprocessing-and-keeping-results)

## First run

1. Start **Skydive Cutter** from the Start menu if you used the installer, or double-click
   **`Skydive Cutter.cmd`** in the folder if you extracted the ZIP. The first run installs what the app needs (see
   the [README](../README.md#install)); later runs check in a second and open straight away.
2. Choose **Videos to process** (folders inside it are included) and **Save clips to**. You can also drag a folder
   from Explorer onto either box.
3. Tick what to keep: **Trim my footage**, **A grade**, **B grade**, or any mix (see
   [Basic and Advanced](#basic-and-advanced)).
4. Click **Process videos**.
5. When videos appear in **Results**, double-click one, or open the **Review** tab, to see what was cut.


## Basic and Advanced

Two buttons at the top of the Process tab choose the screen. A new install opens on **Basic**.

**Basic** asks for two folders and offers three choices. Tick any or all; they run together in one pass.

| Choice | What it keeps | Its own settings |
| --- | --- | --- |
| **Trim my footage** | The jump itself: exit, freefall, break-off and the opening. It does not look for people, so it is the fastest. | Seconds before exit (0 to 10). **Also keep the landing**, with 0 to 10 seconds either side, as a second clip. |
| **A grade (day tape)** | At least 1 person in view filling 20% of the picture, from exit to the end of break-off. | **Include canopy flight with others in view**: at least 2 people filling 20%. That count includes you. |
| **B grade** | Everything A grade keeps, plus looser footage: people fill 10%, gaps up to 6 seconds are joined, and gaps up to 10 seconds are joined while at least 3 people are still in view. | None. |

Each choice gets a folder inside your clips folder (`Trimmed`, `A grade`, `B grade`). Clips are named after the video
they came from, for example `GOPR0001 - A grade.mp4`, with a number when one video gives several. If two cards both
hold a `GOPR0001.MP4`, the second one's clips carry a short code so nothing is overwritten. Because B grade includes
A grade, the same freefall is in both folders when both are ticked.

**Advanced** is every profile and every setting. The three choices are ordinary profiles there (with their
companions, `Trimmed landing` and `A grade canopy`), and can be edited like any other. A choice edited in Advanced
shows "Changed in advanced mode" on the Basic screen, with **Put back** to return it to its built-in settings.
Profiles of your own are switched off, not deleted, while the Basic screen is showing, and come back on when you
return to Advanced.

## The Process tab

| Part | What it does |
| --- | --- |
| **Folders** | **Videos to process**: the folder with your footage; folders inside it are scanned too. **Save clips to**: where clips are saved. It must be outside the videos folder. |
| **What to keep** | The keep profiles. See [Keep profiles](#keep-profiles). |
| **The ? buttons** | Every setting has one. Click it for a plain explanation of what the setting does, with a warning where changing it goes through your finished videos again. Hovering shows the same text. |
| **Advanced settings** | Three folding sections under the profiles: Output, Processing and People. See [Advanced settings](#advanced-settings). **Hide advanced settings** folds the lot away. |
| **The red banner** | Something the app needs is missing. See [When something is missing](#when-something-is-missing). |
| **Results** | One row per processed video. See [The Results list](#the-results-list). |
| **Process videos** | Processes the videos in the input folder that are new or have changed. |
| **Keep watching for new videos** | Tick it, and after the existing videos the app keeps watching the folder and processes new videos as they are copied in, until you press **Stop**. |
| **Review cuts in labeller** | Opens the Review tab. |

Timeline CSVs go into a `timelines` folder inside the clips folder, unless you choose **Somewhere else** under
Advanced settings > Output > Save timelines to.

### Repeated camera filenames

You can process `Card A/GOPR0001.MP4` and `Card B/GOPR0001.MP4` together. Output names combine the original file name
with a 16-character ID, for example `GOPR0001_1a2b3c4d5e6f7890`. The ID comes from the file's location and contents,
so different footage with the same name never collides. You don't need to rename anything.

With **A folder per profile** (which the Basic screen always uses) clips carry the plain file name instead, such as
`GOPR0001 - A grade.mp4`. The first `GOPR0001` processed keeps the plain name; the other one's clips are named
`GOPR0001 [1a2b3c] - A grade.mp4`. Which is which is remembered, so the names stay the same on every later run.

## Keep profiles

Each profile selects footage independently. A moment must pass all of a profile's filters. If you select several
phases, **any one** of them matches.

Use **Add**, **Edit**, **Duplicate** or **Remove**, or double-click a row. **Add a ready-made profile** offers presets.
Each opens in the editor so you can adjust it before saving:

| Preset | Phases | Extra before / after | Other |
| --- | --- | --- | --- |
| Whole skydive | Climbing out to opening | 2 s / 2 s | |
| Exit only | Exit | 3 s / 3 s | |
| Canopy flight | Canopy flight | 0 s / 0 s | At least 10 s; gaps up to 2 s bridged |
| Landing | Landing, landed | 3 s / 5 s | |
| Group freefall | Freefall | 2 s / 2 s | At least 2 people covering 30% of the frame (people add-on only) |

The **Use** tick turns a profile on or off without deleting it. Turning off or removing a profile never deletes
clips it made earlier.

| Setting | Effect |
| --- | --- |
| **Profile name** | Identifies the profile in CSVs and folder names. No semicolons. |
| **Folder for this profile's clips** | Used with **Organise clips: A folder per profile**. Empty means a folder named after the profile inside the clips folder. A name gives a different folder there (two profiles can share one); a full path puts this profile's clips anywhere. |
| **Parts of the jump to keep** | A moment is kept only if it falls in a ticked part. Hover over a part to see what it means. |
| **People in view, at least** | How many people must be visible. **This counts anyone the camera sees, including you**: under canopy or on landing your own legs or arms count as one. **0** keeps moments with nobody in view. |
| **People fill at least (% of the picture)** | The boxes round everyone in view, added up. About 20% is one person close up; distant jumpers may be 1 to 3%. **0** means no requirement. |
| **Start each clip earlier by / End each clip later by (seconds)** | Extra footage before and after each kept stretch, never beyond the video. |
| **Ignore matches shorter than (seconds)** | Drops a matching stretch shorter than this, measured before the extra footage is added. |
| **Join matches separated by up to (seconds)** | Fills a short gap between two matches, so you get one clip instead of two. The gap is measured between the matches themselves, before the extra footage is added, so it is longer than the hole you see between two clips. |
| **Join gaps while people are still in view, up to (seconds)** and **People still in view means at least** | A looser join for footage where the camera drifts off the group. A gap between two matches is filled, however little of the picture people fill, while at least that many people are still found. A moment without them inside the gap (the camera looked away) is let through if it is no longer than **Join matches separated by**. It never makes a clip longer at its ends. **0** seconds switches it off. In Review these seconds show as "joined: people still in view". |

Under the settings the editor writes out, in one sentence, what the profile keeps; it changes as you change the
numbers. A note appears beside the people count when the profile keeps canopy or landing footage, where you are
usually in your own picture.

The default Exit + Freefall keeps **1 s before and 2 s after**. The end of freefall (break-off) is the least certain
moment, for the models and for people. In testing, 2 s after instead of 1 s raised the share of jumps with the whole
exit and freefall in the clip from 71% to 85%.

## Processing videos

**Process videos** handles the videos present when you click it, then stops. With **Keep watching for new videos**
ticked it carries on with new arrivals. A video is processed once its file size and date have stopped changing (two
checks, five seconds apart), so a copy in progress is left alone.

Recognised extensions: `.mp4`, `.mov`, `.avi`, `.mkv`, `.mts`, `.m2ts`, `.wmv`, `.mpg`, `.mpeg`, `.360`, in any
letter case.
Videos are processed one at a time unless you raise **Videos at once** (Advanced settings > Processing). The settings
are locked during a run. You can keep reviewing on the Review tab while videos are processed; new ones appear there as
they finish.

- **Queue progress** counts finished videos, with failures listed separately. After the first video it also shows an
  estimate such as *about 6 min left*. The estimate comes from how fast this PC has processed video so far, so it
  improves with use.
- **Current video** shows the file and its step: checking, reading the video and counting people, working out the
  parts of the jump (video, sound, motion), writing the CSV, creating clips. With several videos at once there is
  one bar for each.
- **Stop** finishes the videos in progress and stops. Press it again (**Cancel current video...** or **Cancel videos
  in progress...**) to stop those too. Finished outputs are kept, and a cancelled video is processed again next time.
- When a video finishes, the log says how long each step took.

## The Results list

One row per processed video in the current Clips folder:

| Column | Meaning |
| --- | --- |
| **Video** | A still from the first clip, and the file (with its subfolder). |
| **Status** | Done, Failed or Cancelled. Hover a failure to see why. |
| **Labels** | **Model**, **Your labels** (cut from your review), or **Not skydiving**. *(re-cut pending)* means you changed the review since the last cut. |
| **Clips** | How many clips were cut. |
| **Needs a look** | How many stretches the motion data (or sound) disagreed with the result, and the share of the video that disagreed. |
| **Notes** | Warnings such as *No usable audio*. |
| **Processed** | When the video was last processed. |

**Show** filters the list: all videos, those that need a look, failed ones, those cut from your labels, or those not
reviewed yet. Click a column title to sort by it, and again to reverse; drag the edge of a title to change a column's
width.

Double-click a row, or use **Open in Review**, to review that video. **Show clips** opens the folder with its clips,
**Open timeline CSV** opens its CSV, and **Process again** runs it again from scratch (useful after a failure). To
process several again together, select them first: Ctrl+click, Shift+click, or Ctrl+A for all.

## The Review tab


Every processed video, with all the tracks lined up under it on **one time axis**. The same second is at the same
position in every row, including your own labels, so you can see at a glance which sources agree.

| Row | Shows |
| --- | --- |
| **Your labels** | Your editable timeline. It starts as a copy of Final. Drag a boundary to move it. |
| **Final (cut)** | What the clips were cut from. |
| **V4 video** | The video model alone. |
| **Audio** | The sound model alone, or *No usable audio*. |
| **Motion model** | A model that uses only the camera's motion data, or *No motion data from this camera*. |
| **Motion (g)** | Acceleration in g, with gridlines at 0, 1, 2 and 3 g. About 1 g in the plane and under canopy, close to 0 at exit, then spikes at the opening shock and landing, which are marked. |
| **People found** | How many people the detector found, second by second, with the number printed on each stretch and a dashed line at what the profile asks for. Green clears the line; amber falls short. |
| **Picture filled** | How much of the picture those people fill, as a percentage, with its own dashed line. Someone can be found and still fall short here: one person at 2% of the picture does not pass a profile that asks for 20%. |
| **Why not kept** | One colour for each second, with a key underneath: kept, kept as extra footage, other part of the jump, nobody found, too few people, people too small, match too short. This is the row that says why a moment is missing from the clips. |
| **Agreement** | Green: motion (or sound, without motion) agrees with Final. Amber: it doesn't, so worth a look. Grey: nothing to compare. |
| **Clips cut** | The clips each profile produced, one lane per profile. |

Click any row to jump there. Untick **Show all predictions and sensors** to keep just Final and Clips cut.

**Finding what to check.** **Check >** (or **C**) jumps to the next amber stretch, a second before it starts;
**< Check** (**Shift+C**) goes back. The counter shows *Check 2 of 5*, and the video list shows how many checks each
video has. Where Agreement is green, the model was wrong on only about 4% of seconds in testing, so the amber stretches
are where your time is best spent.

**Zoom.** **Ctrl + mouse wheel** over the tracks zooms around the mouse, and the plain wheel scrolls when zoomed.
**+**, **-** and **Fit** in the toolbar (or **=**, **-**, **0**) do the same. All rows zoom together.

**Clips.** Click a clip in **Clips cut** to play just that clip; it stops at the clip's end. Right-click for **Open in
my video player** or **Show in folder**.

**The overlay** on the video shows Final, V4, audio and motion at the current moment in one line. Press **O** to hide
it.

**Editing labels.** Pick the phase with the coloured chips (or keys **1** to **9**), then **Finish** (Enter) where it
ends. **Skip phase** (Tab), **Back a phase** (B) and **Delete segment** (Del) are below the tracks. You can also drag
boundaries on **Your labels**. Changes save automatically.

**Mark reviewed and re-cut** makes your labels the cut for this video. The video is re-cut straight away, without
running the model again, and the next video opens. The **Clips cut** row and the Results list update when it is done.
**Not skydiving** removes the video's clips; **Restore video** brings the model's clips back. If you edit a video after
marking it reviewed, it keeps its last reviewed cut until you mark it again. You can turn off the immediate re-cut under
Advanced settings; reviews are then used the next time you click Process videos.

## Keyboard shortcuts

On the Review tab:

| Key | Action |
| --- | --- |
| Space | Play or pause |
| Left / Right | Back or forward 1 second |
| Shift+Left / Shift+Right | Back or forward 5 seconds |
| End | Last frame |
| P / N | Previous or next video |
| 1 to 9 | Choose the phase to label |
| Enter | Finish the current phase and move to the next |
| Tab | Skip the current phase |
| B | Back one phase |
| Delete | Delete the selected segment |
| M | Mute or unmute |
| C / Shift+C | Next or previous check |
| O | Show or hide the overlay |
| = / - / 0 | Zoom in, zoom out, whole video |
| Ctrl + wheel | Zoom around the mouse |

The keys only act while the Review tab is showing.

## Advanced settings

Advanced settings sit under the profiles in the left column, in three folding sections. Click a section to open it;
**Hide advanced settings** (at the right of the Folders box) folds the whole box away. The app remembers which sections
you left open.

**Output**

| Setting | Meaning |
| --- | --- |
| **What to produce** | **Clips and timelines**, or **Timelines only - no clips** (timelines and profile matches only). |
| **Organise clips** | **A folder per video**, **A folder per clip, grouped by video**, **All clips in one folder**, **Same folders as the input videos** (keeps your input folder structure, for example `2024/Boogie/`), or **A folder per profile, clips named after the video** (what the Basic screen uses; each profile can also be given a folder of its own). An example path is shown below it; see the [folder examples](OUTPUT_REFERENCE.md#folder-examples). |
| **Save timelines to** | **In the clips folder** (a `timelines` folder inside it, the default), or **Somewhere else**: choose any folder with **Browse...** or drag one onto the box. With timelines only there is no clips folder, so a folder is required. |

**Processing**

| Setting | Meaning |
| --- | --- |
| **Work out the parts of each jump** | Turn it off to cut by people only. |
| **Run on** | **Automatic** (NVIDIA GPU if available), **NVIDIA GPU**, or **Processor only**. |
| **Videos at once** | **1** (the default) up to **10**, or **Automatic**. More is faster when the machine has spare processor cores and graphics memory, up to a point: on the test PCs an RTX 5090 gained nothing beyond four, and a GTX 1060 was best at two. Automatic starts with one and adds another only while the processor, memory and graphics card have room; it never stops a video that is running. Each video in progress gets its own progress bar. The results are the same however many run together. |
| **Read videos with** | **Automatic** unpacks each video on the graphics card when that works for the file, and on the processor otherwise. The picture is identical either way. **Processor only** is there in case of a graphics driver problem. |
| **Graphics memory use (batch size)** | Video windows per GPU batch. Lower it if a small graphics card runs out of memory. |
| **360 camera footage** | Which side of a 360 camera to use: **Front view only** (the default), **Front view, people counted all round**, or **Back view only**. Ordinary cameras ignore it. See [360 footage](#360-footage). |
| **Re-cut a video as soon as you mark it reviewed** | On by default. Off: reviews are used the next time you click Process videos. |

**People**

| Setting | Meaning |
| --- | --- |
| **Look for people in the picture** | On by default. The detector is installed with the app; if it goes missing this section turns red. |
| **Person detector** | Which model finds the people. **Standard** comes with the app and is small and fast. Larger detectors find more skydivers, especially at a distance or in odd positions; they are listed when their file (for example `yolo26x.pt`) is in the app folder. Changing it counts people again on finished videos. |
| **Checks per second** | How often the video is looked at for people, and how finely clips can start and end. Default 1. |
| **How sure it must be that it is a person (0 to 1)** | The lowest detector score accepted. Lower counts more distant or half-hidden people and more mistakes; higher misses more. Default 0.35. |

Person area uses rectangular boxes. Total area adds the boxes, so overlaps can exceed 100%. Click the **?** beside
any setting for more detail.

The mouse wheel scrolls the settings without changing them. To change a drop-down or a number with the wheel, click
it first.

Each video's picture is read once: the same read counts the people and makes the small copy the phase model looks at.
When a video finishes, the log says how long each step took.

## 360 footage

GoPro MAX `.360` files and stitched 360 videos are processed like any other footage, with one difference: the app has
to choose which part of the sphere to look at.

- **Front view only (the default).** Phases and people come from the front of the camera. This is the view the models
  were trained on, and on 86 labelled MAX jumps it is the most accurate footage the app handles.
- **Front view, people counted all round.** Phases still come from the front, but people are counted in both
  directions and added together, so a group behind the camera still counts towards a profile's people filter. The
  timeline CSV keeps the per-side counts in its own columns.
- **Back view only.** Everything comes from behind the camera. Useful when the camera faces the wearer and the jump
  happens behind it. Phases are less reliable this way: on 20 labelled MAX jumps the back view scored 77% of seconds
  correct against 98% for the front, and got two jumps almost entirely wrong, so check what it produces.

Notes:

- The view only decides where the app looks. Clips are copied whole, with every lens, and a clip of a `.360` file is
  still a `.360` file that opens in GoPro Player.
- The Review tab plays the original file, so a `.360` shows the raw lens image rather than a reframed view. The
  tracks, the people row and the clips all still line up with it.
- Changing this setting changes the result, so those videos are processed again the next time you press
  **Process videos**. Ordinary footage is untouched.

## When something is missing

The app checks what this install has each time it starts, and again before each run.


| Colour | Meaning |
| --- | --- |
| Red banner and a red section | Something needed is missing: the person detector, a jump phase model, FFmpeg or a library. **Process videos** is switched off, and the failing section opens so you can see it. |
| **Install now** | Runs the installer in its own window and downloads whatever is missing, then re-checks. It only fills gaps. To reinstall everything over the top, close the app and run `Repair.cmd`. |
| Amber banner | The work can still run, only slower: usually no NVIDIA graphics card, so the processor does it. |
| No banner | Everything needed is present. **Details** always lists the full state. |

A run is never quietly downgraded. If the person detector disappears mid-batch, that video is marked failed with the
reason, rather than cut as though your people filters were not there.

## Reprocessing and keeping results

Settings are saved when processing starts and when you close the app. Finished work is remembered in the Clips folder's
`_state` folder; keep it with your results.

A video is processed again when the file is new or has changed, when you change something that affects its outputs
(profiles, layout, output mode, classifier), or when you review it. Changes that cannot alter the model's answer, such
as profile changes or reviews, **reuse the phases from the last run** instead of running the model again. Processing
again is therefore quick.

Where things are does not count. Installing a new version over the old one, unzipping one beside it, moving the Clips folder, a
drive coming back as another letter, or renaming the folders your videos are in reprocesses nothing: a video with the
same name and content is recognised in its new place and keeps its phases, reviews and clip names. A file whose time
moved by whole hours (a FAT32 card read after the clocks changed, or in another time zone) also counts as unchanged.

Reprocessing keeps a video's output ID. Its timeline CSV is replaced, and within the same profile and layout its clips
are replaced and stale ones removed. Clips from other layouts, removed profiles or earlier versions of a file remain.
To start a separate set, choose a new Clips folder.

Cutting copies the original video data into MP4, with the first audio track, so it is fast and lossless. Clip starts
can snap back to an earlier keyframe, so a clip may begin a moment early. Cuts are not frame-accurate.
