# Skydive Cutter: output and CSV reference

[User guide](USER_GUIDE.md) · [How it works](HOW_IT_WORKS.md) · [Troubleshooting](TROUBLESHOOTING.md)

## Folder examples

These examples show two clips from one source under **Exit + Freefall**. The video ID is illustrative. `Clips` is your selected Clips destination.

**A folder per video**

```text
Clips/
  exit_freefall/
    GOPR0001_1a2b3c4d5e6f7890/
      clip_001_000042s-000067s_freefall.mp4
      clip_002_000080s-000095s_freefall.mp4
```

**A folder per clip, grouped by video**

```text
Clips/
  exit_freefall/
    GOPR0001_1a2b3c4d5e6f7890/
      clip_001_000042s-000067s_freefall/
        clip_001_000042s-000067s_freefall.mp4
      clip_002_000080s-000095s_freefall/
        clip_002_000080s-000095s_freefall.mp4
```

**All clips in one folder**

```text
Clips/
  GOPR0001_1a2b3c4d5e6f7890__exit_freefall__clip_001_000042s-000067s_freefall.mp4
  GOPR0001_1a2b3c4d5e6f7890__exit_freefall__clip_002_000080s-000095s_freefall.mp4
```

**Same folders as the input videos**

Your input subfolders are recreated under the profile folder. For a video at `Input videos/2024/Boogie/GOPR0001.MP4`:

```text
Clips/
  exit_freefall/
    2024/
      Boogie/
        GOPR0001_1a2b3c4d5e6f7890__clip_001_000042s-000067s_freefall.mp4
        GOPR0001_1a2b3c4d5e6f7890__clip_002_000080s-000095s_freefall.mp4
```

Videos at the top of the input folder go straight into `exit_freefall/`. The subfolders are taken relative to the
**Videos to process** folder at the time the video is processed.

**A folder per profile, clips named after the video**

The Basic screen always uses this one. Each profile has a folder named after it, and clips carry the video's own
file name, the profile and, when one video gives several clips, a number:

```text
Clips/
  Exit + Freefall/
    GOPR0001 - Exit + Freefall 1.mp4
    GOPR0001 - Exit + Freefall 2.mp4
  A grade/
    GOPR0001 - A grade.mp4
    GOPR0001 - A grade canopy.mp4
```

- A profile's **Folder for this profile's clips** changes where its clips go: a name gives another folder inside
  Clips, and a full path puts them anywhere. Two profiles can share a folder; that is how `A grade canopy` lands in
  `A grade` and `Trimmed landing` in `Trimmed`.
- If two different videos have the same file name (two cards each with a `GOPR0001.MP4`), the first one processed
  keeps the plain name and the other's clips carry the first six characters of its ID:
  `GOPR0001 [1a2b3c] - A grade.mp4`. The choice is recorded in `_state/clip_names.json`, so names never change
  between runs.
- These names carry no times or phase. The manifest has them.

Another video uses its own name and ID. Another profile gets its own folder or, in the flat layout, its own filename component. Every layout also has `_manifests` and `_state` supporting folders in the Clips folder, omitted above for clarity.

A clip of a 360 video keeps that video's own extension (`clip_001_000042s-000067s_freefall.360`) and every lens
track, so it still opens in the camera maker's player.

## Filenames

Timelines, manifests and every layout except **A folder per profile** use the video's output name. A video's output name is its sanitized original filename without the extension, followed by an underscore and a 16-character ID. Very long stems are shortened and Windows-invalid characters are replaced. The ID incorporates the source path and a checksum of the entire file. Full identity records are checked before a shortened ID is reused.

| Clip filename part | Meaning |
| --- | --- |
| `clip_001` | Number, starting at 1 independently for each video and profile. |
| `000042s-000067s` | Requested source start and end times, rounded to whole elapsed seconds. These are not clock times or recording dates. |
| `freefall` | Most common sampled phase in the requested interval. A clip may contain other phases too. |
| `.mp4` | Output container. The original video encoding is copied. |

With phase identification off, the filename phase is `all`. Flat filenames add the video output name and profile, separated by double underscores.

Use the manifest for more precise requested times. Neither the filename nor manifest reports measured keyframe-adjusted playback boundaries.

## Timeline CSV

Each processed video produces `<video name>_<ID>.timeline.csv` in the CSV folder (by default `timelines` inside the Clips folder). Both output modes use the same format: UTF-8, comma-separated, with a header. Decimal values are written to three decimal places.

| Column | Meaning |
| --- | --- |
| `source_video` | Original source path. |
| `time_sec` | Sample timestamp in seconds from the source's start. |
| `phase` | Phase at that sample, or `NA` with phase identification off. |
| `phase_model_probability` | Mean model probability for the interval containing the sample, on a 0–1 scale. `NA` with phase identification off, for labels you reviewed, or when no probability is supplied. |
| `sources_agree` | `yes` where the check source agrees with `phase`, `no` where it disagrees, `NA` where there is nothing to compare. The check source is the motion-only model when the camera recorded motion data, otherwise the audio model. `no` marks moments worth checking. |
| `person_count` | Accepted detections in the sampled frame. `0` means none; `NA` means detection is off. |
| `largest_person_area_percent` | Largest individual box area as a percentage of the frame. `0` when none are detected; `NA` when detection is off. |
| `total_person_area_percent` | Sum of accepted box areas as a percentage of the frame. Overlaps count in each box, so the sum can exceed 100%. `0` when none are detected; `NA` when detection is off. |
| `matched_profiles` | Matching enabled profile names, separated by semicolons. Empty when none match. |

Probabilities are model scores, not guarantees of accuracy. Person measurements are per-sample detections, not identity tracking or exact body outlines.

| CSV phase | Display label |
| --- | --- |
| `inside_plane` | Inside plane |
| `climbing_out` | Climbing out |
| `exit` | Exit |
| `freefall` | Freefall |
| `break_off` | Break off |
| `opening_parachutes` | Opening parachutes |
| `canopy_flight` | Canopy flight |
| `landing` | Landing |
| `landed` | Landed |

### Sample timing and matches

Sampling starts at **0.5 seconds**. With people detection on, spacing is `1 / Checks per second`; the default produces 0.5, 1.5, 2.5 seconds, and so on. With people detection off, spacing is one second. Only timestamps strictly before the end are included. A very short video can produce a header-only CSV when phase identification is disabled.

A sample exactly on a phase boundary belongs to the interval starting there. This is sampled data, not a per-frame export. Increasing people sampling frequency does not itself increase the phase classifier's resolution.

`matched_profiles` records direct tests at each sample. Extra footage and joined gaps do not add matches, and **Ignore matches shorter than** does not remove matches from the CSV. Therefore matches can exist even when no clips survive that rule. The Review tab's **Why not kept** row shows the outcome of every rule for each second.

The app writes CSV results; it does not watch CSV edits or offer a GUI action to cut from an edited CSV. A later run can overwrite the timeline for the same source identity. Save a separate copy for manual analysis or annotations.

## How matching becomes clips

For each enabled profile, the app:

1. Tests samples against the active phase and people filters.
2. Fills gaps between two matches that are no longer than **Join matches separated by up to**.
3. If **Join gaps while people are still in view** is above 0, also fills longer gaps between two matches, up to that length, while at least **People still in view means at least** people are found in every sample of the gap, however little of the picture they fill. A stretch inside the gap without them is allowed if it is no longer than the ordinary join in step 2. This never extends a clip at its ends.
4. Groups matches into spans, starting at the first matching timestamp and ending one sample interval after the last matching timestamp.
5. Drops spans shorter than **Ignore matches shorter than**, before the extra footage is added.
6. Adds **Start each clip earlier by** and **End each clip later by**.
7. Merges padded spans that overlap or are separated by no more than **one second**.
8. Limits intervals to the source duration and cuts them.

At one check per second, matches at 10.5, 11.5, and 12.5 seconds form a requested 10.5–13.5-second span. A four-second minimum rejects it before the extra footage. With a three-second minimum, 1 s before and 2 s after request 9.5–15.5 seconds, provided that lies within the source.

The cutter stream-copies the first video stream and the first audio stream, if present. It does not export every stream, transcode codecs, or concatenate sources. Keyframe alignment can add footage before the requested start and change playable duration. Some source codecs cannot be copied successfully into MP4.

## Clip manifests

Each enabled profile has one manifest per processed source, even when no clips match. No-match manifests contain only the header. Manifests are created only in clip-creation mode.

```text
Clips/_manifests/<layout>/<profile>/<video name>_<ID>.clips.csv
```

The layout folder is `per_video`, `per_clip`, `flat`, `mirror` or `by_profile`. Manifests are always in the Clips folder, including for a profile whose clips go to a folder of its own elsewhere.

| Column | Meaning |
| --- | --- |
| `clip_index` | Number within this video's profile output. |
| `clip_path` | Generated destination. |
| `source_video` | Original source path. |
| `profile` | Profile display name. |
| `start_sec` | Requested source start after span rules and margins. |
| `end_sec` | Requested source end. |
| `duration_sec` | Requested duration: end minus start. |
| `dominant_phase` | Most common sampled phase within the requested interval; `all` with phase identification off. |
| `source_id` | Full identity used for output ownership. |
| `source_sha256` | Source content SHA-256 checksum. |
| `output_layout` | `per_video`, `per_clip`, `flat`, `mirror` or `by_profile`. |

Manifests let the app recognize its previous clips during replacement. Preserve them with the outputs; editing them does not provide a supported way to change cut decisions.

## Supporting records and retention

| Location | Purpose |
| --- | --- |
| `<active destination>/_state/ledger.json` | Completion history. Active destination means Clips when cutting, or CSV files in CSV-only mode. |
| `<active destination>/_state/classifier-runs/<video>_<time>/result.json` | Every track for one video: Final, V4 video, audio, motion model, the motion trace and events, the agreement strip, and warnings. `engine.log` beside it holds diagnostics. |
| `<active destination>/_state/review/` | The Review tab's folder: `review.csv` (your labels), `review_state.json` (what you marked reviewed, with a copy of those labels), `review_exclusions.json` (videos marked not skydiving). |
| `<active destination>/_state/thumbnails/<video>_<ID>/` | One still per clip (`<profile>_<clip number>.jpg`), shown in the Results list. |
| `<Clips>/_state/clip_names.json` | Which video owns each plain clip name in the folder-per-profile layout. |
| `<CSV files>/_state/sources/` | Full identity records protecting CSV names. |
| `<Clips>/_state/sources/` | Full identity records for clip outputs when cutting. |
| `<application folder>/app/settings.json` | Saved GUI choices and internal settings. |
| `<application folder>/app/speed.json` | How fast this PC processes video, for the time estimate. Safe to delete. |
| `<application folder>/logs/` | Setup logs, the install check, and the app's startup logs. |

The application folder is where the app is installed: `%LOCALAPPDATA%\Programs\Skydive Cutter` with the installer
unless you chose another, or the folder you extracted the ZIP into. The ledger also records how long each step took
for each video and the people already counted, which is why changing a profile does not read the video again.

Old classifier-run directories are not automatically removed, and layouts are not automatically consolidated. Earlier source identities and removed profiles retain their outputs. Within an active profile and layout, a successful replacement can remove stale clips owned by its previous manifest. Archive files after processing stops, retaining supporting records with results you want the app to recognize.
