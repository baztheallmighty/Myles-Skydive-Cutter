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
**Input videos** folder at the time the video is processed.

Another video uses its own name and ID. Another profile gets its own folder or, in the flat layout, its own filename component. The flat layout still contains `_manifests` and `_state` supporting folders, omitted above for clarity.

A clip of a 360 video keeps that video's own extension (`clip_001_000042s-000067s_freefall.360`) and every lens
track, so it still opens in the camera maker's player.

## Filenames

A video's output name is its sanitized original filename without the extension, followed by an underscore and a 16-character ID. Very long stems are shortened and Windows-invalid characters are replaced. The ID incorporates the source path and a checksum of the entire file. Full identity records are checked before a shortened ID is reused.

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

Sampling starts at **0.5 seconds**. With people detection on, spacing is `1 / Samples per second`; the default produces 0.5, 1.5, 2.5 seconds, and so on. With people detection off, spacing is one second. Only timestamps strictly before the end are included. A very short video can produce a header-only CSV when phase identification is disabled.

A sample exactly on a phase boundary belongs to the interval starting there. This is sampled data, not a per-frame export. Increasing people sampling frequency does not itself increase the phase classifier's resolution.

`matched_profiles` records direct tests at each sample. Margins and gap filling do not add matches, and minimum span does not remove matches from the CSV. Therefore matches can exist even when no clips survive the minimum-span rule.

The app writes CSV results; it does not watch CSV edits or offer a GUI action to cut from an edited CSV. A later run can overwrite the timeline for the same source identity. Save a separate copy for manual analysis or annotations.

## How matching becomes clips

For each enabled profile, the app:

1. Tests samples against the active phase and people filters.
2. Bridges non-matching gaps surrounded by matches when their sampled duration is within **Bridge non-matching dips up to**.
3. Groups matches into spans, starting at the first matching timestamp and ending one sample interval after the last matching timestamp.
4. Drops spans shorter than **Minimum span**, before margins.
5. Adds **Extra footage before** and **Extra footage after**.
6. Merges padded spans that overlap or are separated by no more than **one second**.
7. Limits intervals to the source duration and cuts them.

At one sample per second, matches at 10.5, 11.5, and 12.5 seconds form a requested 10.5–13.5-second span. A four-second minimum rejects it before margins. With a three-second minimum, 1 s before and 2 s after request 9.5–15.5 seconds, provided that lies within the source.

The cutter stream-copies the first video stream and the first audio stream, if present. It does not export every stream, transcode codecs, or concatenate sources. Keyframe alignment can add footage before the requested start and change playable duration. Some source codecs cannot be copied successfully into MP4.

## Clip manifests

Each enabled profile has one manifest per processed source, even when no clips match. No-match manifests contain only the header. Manifests are created only in clip-creation mode.

```text
Clips/_manifests/<layout>/<profile>/<video name>_<ID>.clips.csv
```

The layout folder is `per_video`, `per_clip`, or `flat`.

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
| `output_layout` | `per_video`, `per_clip`, or `flat`. |

Manifests let the app recognize its previous clips during replacement. Preserve them with the outputs; editing them does not provide a supported way to change cut decisions.

## Supporting records and retention

| Location | Purpose |
| --- | --- |
| `<active destination>/_state/ledger.json` | Completion history. Active destination means Clips when cutting, or CSV files in CSV-only mode. |
| `<active destination>/_state/classifier-runs/<video>_<time>/result.json` | Every track for one video: Final, V4 video, audio, motion model, the motion trace and events, the agreement strip, and warnings. `engine.log` beside it holds diagnostics. |
| `<active destination>/_state/review/` | The Review tab's folder: `review.csv` (your labels), `review_state.json` (what you marked reviewed, with a copy of those labels), `review_exclusions.json` (videos marked not skydiving). |
| `<active destination>/_state/thumbnails/<video>_<ID>/` | One still per clip (`<profile>_<clip number>.jpg`), shown in the Results list. |
| `<CSV files>/_state/sources/` | Full identity records protecting CSV names. |
| `<Clips>/_state/sources/` | Full identity records for clip outputs when cutting. |
| `<application folder>/app/settings.json` | Saved GUI choices and internal settings. |
| `<application folder>/app/speed.json` | How fast this PC processes video, for the time estimate. Safe to delete. |
| `<application folder>/logs/` | Setup logs, the install check, and the app's startup logs. |

Old classifier-run directories are not automatically removed, and layouts are not automatically consolidated. Earlier source identities and removed profiles retain their outputs. Within an active profile and layout, a successful replacement can remove stale clips owned by its previous manifest. Archive files after processing stops, retaining supporting records with results you want the app to recognize.
