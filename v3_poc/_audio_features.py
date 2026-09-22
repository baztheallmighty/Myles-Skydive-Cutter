"""Turn a video file into one feature vector per second of its audio track.

Only the audio is read: `-vn` means ffmpeg demuxes without decoding a single
frame, so this costs a sequential read of the file and nothing more.

The representation is 73 librosa summaries of a 3-second window, taken on a
1-second stride. That combination was chosen by measurement, not taste: a sweep of
window lengths and a comparison of feature sets, both against human labels.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import warnings

import numpy as np

warnings.filterwarnings("ignore")

SAMPLE_RATE = 22050        # nothing above 8 kHz carries phase information
CLIP_SECONDS = 3.0         # window each step sees
STRIDE_SECONDS = 1.0       # one prediction per second
CENTRE_OFFSET = CLIP_SECONDS / 2.0

FEATURE_NAMES = (
    ["rms_mean", "rms_std", "rms_p10", "rms_p90", "rms_delta",
     "zcr_mean", "centroid_mean", "centroid_std", "rolloff_mean",
     "bandwidth_mean", "flatness_mean", "flatness_std", "flatness_p90",
     "onset_mean", "onset_max"]
    + [f"chroma_{i}_mean" for i in range(12)]
    + [f"chroma_{i}_p95" for i in range(12)]
    + [f"mfcc_{i}_mean" for i in range(13)]
    + [f"mfcc_{i}_std" for i in range(13)]
    + [f"mel_band_{i}" for i in range(8)]
)
FEATURE_DIM = len(FEATURE_NAMES)     # 73


class NoAudioError(RuntimeError):
    """The file has no audio track this extractor can use."""


def decode_audio(video_path: Path | str, ffmpeg: str = "ffmpeg") -> np.ndarray:
    """Whole audio track, mono, at SAMPLE_RATE, float32 in [-1, 1].

    `-map 0:a:0` is load-bearing. Left to itself ffmpeg picks the audio stream
    with the most channels, and 360 cameras write a four-channel ambisonic track
    alongside the ordinary stereo one. swresample cannot downmix an ambisonic
    layout to mono, so the default pick fails outright and the file is silently
    skipped. Taking the first audio stream explicitly gets the stereo track that
    every other camera also provides.
    """
    video_path = Path(video_path)
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        result = subprocess.run(
            [str(ffmpeg), "-v", "error", "-y", "-i", str(video_path), "-map", "0:a:0",
             "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", str(wav)],
            capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        if result.returncode != 0 or not wav.exists():
            raise NoAudioError(
                f"{video_path.name}: ffmpeg could not extract audio "
                f"({result.stderr.decode('utf-8', 'replace').strip()[:200]})")
        import soundfile as sf

        signal, _ = sf.read(str(wav), dtype="float32", always_2d=False)
    signal = np.asarray(signal, dtype=np.float32)
    if signal.size < SAMPLE_RATE:
        raise NoAudioError(f"{video_path.name}: audio track shorter than one second")
    return signal


def clip_features(segment: np.ndarray) -> np.ndarray:
    """The 73-dim vector for one window of audio.

    Deliberately includes both level features (loud wind against quiet canopy)
    and shape features (engine hum is tonal, wind is broadband), because the
    phases differ along both axes and camera AGC corrupts level specifically.
    """
    import librosa

    if segment.size < 512:
        return np.zeros(FEATURE_DIM, dtype=np.float32)

    values: list[float] = []
    rms = librosa.feature.rms(y=segment)[0]
    values += [rms.mean(), rms.std(), np.percentile(rms, 10), np.percentile(rms, 90),
               float(rms[-1] - rms[0])]
    values.append(librosa.feature.zero_crossing_rate(segment)[0].mean())

    centroid = librosa.feature.spectral_centroid(y=segment, sr=SAMPLE_RATE)[0]
    values += [centroid.mean(), centroid.std()]
    values.append(librosa.feature.spectral_rolloff(y=segment, sr=SAMPLE_RATE)[0].mean())
    values.append(librosa.feature.spectral_bandwidth(y=segment, sr=SAMPLE_RATE)[0].mean())

    flatness = librosa.feature.spectral_flatness(y=segment)[0]
    values += [flatness.mean(), flatness.std(), float(np.percentile(flatness, 90))]

    onset = librosa.onset.onset_strength(y=segment, sr=SAMPLE_RATE)
    values += [float(onset.mean()), float(onset.max())]

    chroma = librosa.feature.chroma_stft(y=segment, sr=SAMPLE_RATE)
    values += list(chroma.mean(axis=1))
    values += list(np.percentile(chroma, 95, axis=1))

    mfcc = librosa.feature.mfcc(y=segment, sr=SAMPLE_RATE, n_mfcc=13)
    values += list(mfcc.mean(axis=1))
    values += list(mfcc.std(axis=1))

    mel = librosa.feature.melspectrogram(y=segment, sr=SAMPLE_RATE, n_mels=8)
    values += list(np.log1p(mel).mean(axis=1))

    return np.nan_to_num(np.asarray(values, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)


def clip_grid(duration_sec: float) -> np.ndarray:
    """Start time of each window, in seconds."""
    starts = np.arange(0.0, max(0.0, duration_sec - CLIP_SECONDS) + 1e-6,
                       STRIDE_SECONDS, dtype=np.float32)
    return starts if starts.size else np.zeros(1, dtype=np.float32)


def features_from_signal(signal: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """(features [T, 73], window start times [T], duration in seconds)."""
    duration = signal.size / SAMPLE_RATE
    starts = clip_grid(duration)
    rows = np.stack([
        clip_features(signal[int(s * SAMPLE_RATE): int((s + CLIP_SECONDS) * SAMPLE_RATE)])
        for s in starts
    ])
    return rows.astype(np.float32), starts, duration


def features_from_video(video_path: Path | str, ffmpeg: str = "ffmpeg"
                        ) -> tuple[np.ndarray, np.ndarray, float]:
    """Decode a video's audio and reduce it to one vector per second."""
    return features_from_signal(decode_audio(video_path, ffmpeg))
