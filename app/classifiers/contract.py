"""Stable adapter output consumed by the timeline, independent of model versions."""
from dataclasses import dataclass
import math
from pathlib import Path

from v3_poc.common import PHASES


@dataclass(frozen=True)
class PhaseResult:
    segments: list[dict]
    duration_sec: float
    work_directory: Path | None = None
    agreement: list[dict] | None = None  # per-second agree/disagree runs from the check sources, when available


def validate_result(result):
    if not math.isfinite(result.duration_sec) or result.duration_sec <= 0 or not result.segments:
        raise ValueError('The classifier returned an empty or invalid timeline.')
    previous = 0.0
    for segment in result.segments:
        start, end = segment['start_sec'], segment['end_sec']
        if (not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end
                or end > result.duration_sec + 1e-6 or abs(start - previous) > 1e-6
                or segment['phase'] not in PHASES):
            raise ValueError('The classifier returned an invalid phase interval.')
        probability = segment.get('mean_model_probability')
        if probability is not None and (not math.isfinite(probability) or not 0 <= probability <= 1):
            raise ValueError('The classifier returned an invalid model probability.')
        previous = end
    if abs(previous - result.duration_sec) > 1e-6:
        raise ValueError('The classifier did not cover the complete video.')
    return result
