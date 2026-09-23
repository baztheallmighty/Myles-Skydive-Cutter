# Skydive Cutter

Point it at a folder of skydiving videos and it finds the jump in each one and cuts out the part you want. By default
that's the exit and the freefall. It runs entirely on your own Windows PC: after the one-time setup it needs no
internet, and your videos never leave your computer.

It also shows you exactly what it cut and why. Correct anything that's wrong, and the video is re-cut straight away.


## What it does

For every video in the folder you choose (subfolders included), Skydive Cutter:

1. **Finds the jump phases:** inside the plane, climbing out, exit, freefall, break-off, opening, canopy flight,
   landing and landed. It uses three independent sources:
   - **Video:** a neural network that watches 2-second windows and reads them in the context of the whole jump.
   - **Sound:** a second model that listens. Wind noise tells it a lot about freefall.
   - **Camera motion:** the accelerometer data that GoPro (HERO5 and later, MAX) and recent DJI cameras record
     inside the file. It shows the exit's weightless moment, the opening shock and the landing.
2. **Cuts clips** for each *keep profile*. The default, **Exit + Freefall**, keeps the exit and the whole freefall, with
   1 s of extra footage before and 2 s after. Cutting copies the original video data, so it is fast and loses no
   quality.
3. **Writes a CSV timeline** for each video: the phase at every second, whether the other sources agreed, and which
   profiles matched.

The **Results** list shows every processed video: how many clips were cut, and which videos have stretches worth a
look. The **Review** tab shows each video with all the tracks lined up under it, on one time axis you can zoom:

| Row | What it shows |
|---|---|
| Final (cut) | The phases the clips were cut from |
| V4 video | The video model on its own |
| Audio | The sound model on its own |
| Motion model | A model that uses nothing but the camera's motion data |
| Motion (g) | The acceleration trace, with the exit, opening shock and landing marked |
| Agreement | Green where motion (or sound, without motion) agrees with Final; amber where it doesn't |
| Clips cut | The clips each profile produced |

**Check >** (or the **C** key) jumps to the next amber stretch. Fix your labels (they sit directly above the tracks,
same time axis), click **Mark reviewed and re-cut**, and the clip is cut again from your labels at once, without
running the model again. Click a clip in the Clips cut row to play just that clip.

## How accurate is it?

The tests used several hundred jumps the models never trained on, labelled by hand.

- **Phase at each second:** about 89–91% correct across all camera types. It is better on modern GoPro/DJI footage and
  weaker on very old cameras.
- **The cut itself (Exit + Freefall):** the clip contained the whole exit and freefall on **85%** of jumps. The rest
  typically miss a second or two at an edge. Clips carry about 3.6 seconds of extra footage on average.
- Where the motion data (or sound) agrees with the video model, the video model was wrong on only about **4%** of
  seconds. The amber stretches in the Review tab are where to look.

Break-off is the hardest moment to place, for people as well as for the model. See
[docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) for the details and the test results.

## Requirements

- Windows 10 or 11, 64-bit, on an Intel or AMD processor (not ARM).
- 8 GB RAM minimum, 16 GB recommended.
- About **20 GB free** for the NVIDIA setup, or 8 GB for the processor-only setup.
- An **NVIDIA graphics card** is recommended: GTX 900 series or newer, with a current driver. Without one it still
  works on the processor, just more slowly.
- Internet for the one-time setup only.

## Install

1. Download `Skydive-Cutter-2.4.2-windows.zip`. Right-click it and choose **Extract All** into a short, normal folder,
   for example `C:\SkydiveCutter`. Not inside the ZIP, not in Program Files, and not in a OneDrive folder (Desktop,
   Documents and Downloads often are): OneDrive would upload the 10 GB the app installs. Setup checks both, and also
   stops if the folder's path is too long for Windows (over 100 characters).
2. Double-click **`Skydive Cutter.cmd`**. That is the only thing you ever run.

The first run installs what the app needs into that folder: Python, the AI libraries, the person detector and FFmpeg.
It needs no administrator rights and changes nothing else on your PC. With an NVIDIA card this is several GB, so leave
the window open until the app appears. Every later run checks the same list in about a second and starts straight away.

If something is removed or a download was interrupted, the app says so in red and offers **Install now**, which fills
in what is missing in a window you can watch. To reinstall everything over the top, close the app and double-click
**`Repair.cmd`**.

If the NVIDIA build cannot use your graphics card (usually an old driver), setup installs the processor build instead
and says so; update the driver and run `Repair.cmd` to try the GPU again. To choose the processor build yourself,
open a Command Prompt in the folder and run:

```bat
Repair.cmd -Mode CPU
```

To uninstall, delete the folder.

## Quick start


1. **Input videos:** the folder with your jump videos. Its subfolders are included. **Clips:** where the clips go,
   outside the input folder. You can drag folders from Explorer onto these boxes.
2. Leave **Exit + Freefall** ticked, or add profiles. **Add preset** has ready-made ones: whole skydive, exit only,
   canopy flight, landing, group freefall. By default a moment is kept only when someone is in view: at least one
   person filling 20% of the frame. Sky-only and ground-only footage is dropped.
3. Click **Process videos**. Tick **Keep watching for new videos** to carry on with videos you copy in later.
   As a guide, a 72-second GoPro clip took 11 s on an RTX 5090 and 30 s on a fast 16-core desktop processor. Older
   graphics cards and laptop processors are slower. After the first video the app shows an estimate of the time left.
4. Double-click a video in **Results**, or open the **Review** tab, to see what was cut and correct anything that's
   wrong.

GoPro MAX `.360` files work too: the app uses the front view by default, and can count people all round or work
from the back view instead (Advanced settings > Processing > 360 videos).

Use one jump per video for best results. Camera chapter files (GoPro splits long recordings) are processed separately.

## Documentation

- [User guide](docs/USER_GUIDE.md): every setting, profiles, the Results list, the Review tab, keyboard shortcuts.
- [Output and CSV reference](docs/OUTPUT_REFERENCE.md): folder layouts, file names, CSV columns.
- [How it works](docs/HOW_IT_WORKS.md): the models, the rules and the test results.
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md) · [Changelog](CHANGELOG.md)

## Counting people

Every profile can require people in frame, for example *freefall with at least two people filling 30% of the frame*.
The default profiles ask for one person filling 20%, because footage with nobody in it is the boring kind.

This uses the Ultralytics YOLO person detector. It is licensed under AGPL-3.0, so it is **not inside this download**:
setup fetches it from PyPI and Ultralytics' own release page onto your PC, the same way it fetches Python and FFmpeg.
If it is missing, the app shows a red panel and refuses to process rather than quietly ignoring your people filters.

## Privacy

Nothing is uploaded. After setup the app works offline and makes no network connections of its own. (Setup switches
off Ultralytics' anonymous usage statistics.) Your original videos
are only read, never changed, moved or renamed. Results, settings and logs stay in the folders you choose and in the app's own folder. Logs
and CSVs contain your file paths, so check them before sharing.

## Licence

Copyright (C) 2026 the Skydive Cutter authors.

Skydive Cutter, including its trained model files, is free software: you can redistribute it and/or modify it under
the terms of the **GNU General Public License, version 3**, as published by the Free Software Foundation. It is
distributed in the hope that it will be useful, but **without any warranty**, without even the implied warranty of
merchantability or fitness for a particular purpose. See [LICENSE](LICENSE) for the full terms.

The components that setup downloads keep their own licences; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
