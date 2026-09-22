# How Skydive Cutter works

[User guide](USER_GUIDE.md) · [Output and CSV reference](OUTPUT_REFERENCE.md)

This page explains what the classifier does with each video, how its rules were chosen, and how well it did in
testing. None of it is needed to use the app.

## The nine phases

A skydive video runs through these phases in order. Any of them can be missing (a video may start after the exit, or
stop before landing):

**inside plane → climbing out → exit → freefall → break-off → opening parachutes → canopy flight → landing → landed**

The classifier never lets the phases go backwards. It finds the most likely sequence that respects this order
(*ordered decoding*), so it cannot, for example, put freefall after canopy flight.

## Three sources

### 1. Video (the main model)

- The video is converted once into a small working copy: 12 frames per second, fitted into 160 × 160 pixels. For
  360° footage the front view is used. The copy is deleted afterwards.
- A 3D convolutional network (R3D-18, started from the public Kinetics-400 action-recognition weights) looks at
  **2-second windows, one per second**, and describes each window.
- A **temporal network** reads the whole sequence of window descriptions and decides the phase of each second in the
  context of the entire jump. This context is what lets it tell, say, freefall from canopy flight when a single
  window is ambiguous.
- Ordered decoding turns that into phases.

The models were trained on about 400 hand-labelled jumps from many camera generations: 2009 to 2026, GoPro HERO2
onwards, GoPro MAX 360, DJI action cameras, and others.

### 2. Sound

A separate model listens to **3-second windows, one per second**. It uses 73 sound features: loudness, spectrum
shape and similar. Sound is informative in its own way: the engine noise in the plane, the roar of freefall wind, and
the sudden quiet under canopy. It can't see anything, so on its own it's less accurate than the video model (about
84% of seconds in testing). But it is independent of the video, which makes it a useful second opinion.

### 3. Camera motion

Many cameras record an accelerometer inside the video file: GoPro HERO5 and later, GoPro MAX, and recent DJI action
cameras. Skydive Cutter reads it from the file's metadata without decoding any video. It gives:

- a **g-force trace**: about 1 g in the plane and under canopy, close to 0 g as you leave the plane, then buffeting in
  freefall, a sharp spike at the parachute opening, and a spike at landing;
- three **events** found in the trace: the exit dip, the opening shock and the landing;
- a **motion-only model**: a gradient-boosted classifier that predicts the phase from the motion data alone (8 seconds
  of context either side). It never sees the video.

Cameras without motion data simply don't have these tracks.

## How the final answer is made

The **Final** track (what the clips are cut from) is the video model's answer, with exactly one adjustment:

> On cameras **without** motion data, if the video model ends freefall but the sound model still hears freefall,
> freefall is extended over those seconds of break-off or opening, by up to 30 seconds.

Everything else from sound and motion is **shown, never applied**. Where the check source (motion if the camera has
it, otherwise sound) disagrees with Final, the moment is flagged: `sources_agree = no` in the CSV, amber on the
Review tab.

Why so conservative? Because that is what the tests supported.

## How the rules were chosen

The rules were tested on **318 labelled jumps the video models had never been trained on** (five-fold
cross-validation: the collection was split five ways, and each fifth was predicted by models trained on the other
four). The tests compared the video model alone with every combination of the rules. A second, stricter check used 45
of those jumps whose labels were made from scratch, with no model suggestion to anchor the labeller.

| Idea | Result | Used? |
| --- | --- | --- |
| Video model alone | 89.0% of seconds correct; 72% of phase changes placed within 2 s | Yes (base) |
| "Snap" boundaries to nearby changes in the window scores | Worse: phase changes within 2 s fell from 72% to 66% | No |
| Let sound override the video wherever it hears freefall, opening or canopy | No gain on this model; on 3 old videos it erased the exit and freefall entirely | No |
| **Let sound extend freefall past the video model's end of freefall** (no-motion cameras) | Best overall: 89.5% of seconds, no loss on the strict set | **Yes** |
| The same on motion cameras | No gain | No |
| Let motion override the video | Loses boundary accuracy (tested earlier) | No |
| Use motion/sound disagreement as a warning | Where they agree, the video model is wrong on only ~4% of seconds; disagreement catches 65–80% of its errors while marking 15–21% of the video | **Yes** (amber strip) |
| Extra footage after the clip: 1 s vs 2 s | Whole exit + freefall inside the clip: 71% → 85% of jumps, for ~0.5 s more footage per clip | **2 s** by default |

### The cut, measured directly

For the default Exit + Freefall profile, over the 318 jumps:

| | Jumps with the whole exit and freefall in the clip | Freefall seconds cut off (all jumps) | Extra footage per clip |
| --- | ---: | ---: | ---: |
| Previous model (V3), 1 s margins | 46% | 1,206 | 3.8 s |
| This version, video model only, 1 s margins | 71% | 423 | 2.9 s |
| **This version as shipped** (sound rule, 1 s before / 2 s after) | **85%** | **135** | 3.6 s |

On the strict set of 45 jumps: 99.9% of exit and freefall seconds inside a clip, and 97% of jumps complete.

## Known limits

- **Break-off is fuzzy.** When exactly a group breaks off is a judgement call, and two people labelling the same video
  often disagree by a second or two. Freefall's end is where the model is least certain. That is why the default
  keeps 2 s after.
- **Old and unusual cameras** are harder: low resolution, odd colour, fisheye, or no sound. Accuracy there is lower
  than on modern GoPro/DJI footage.
- **The start of climbing out** and the **inside-plane** phase are the model's weakest spots. The default profile
  doesn't use them, but custom profiles that keep them may be less precise.
- **One jump per video.** Several jumps in one file, or a video that starts mid-freefall, confuse the phase order.
- The **audio-extension rule and the 2 s margin** were chosen on the same 318 jumps they were measured on. They are
  simple, single-setting choices and the strict set agrees, but they have not yet been confirmed on fresh labels.
- Model scores (`phase_model_probability`) are not calibrated confidence. Use `sources_agree` and the Review tab to find
  doubtful moments.

## Your corrections

When you mark a video reviewed on the Review tab, it is re-cut from your labels straight away. Your labels stay
on your PC in `_state/review/review.csv`. Nothing is uploaded.

## Frozen code

The labelling window (`v3_poc/_labeler.py` and `v3_poc/review.py`, about 3,400 lines) came from the research tools
and is embedded in the Review tab. It works and is shipped, but it is deliberately frozen: behaviour is changed in
`cutter_v4/review_ui.py` or `app/ui/review_tab.py`, which sit on top of it, and the file itself is left alone until
it is replaced outright. Treat it as a vendored dependency rather than part of the app's own code.
