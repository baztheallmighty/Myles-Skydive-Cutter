"""Pure gates and clip spans, reusing the existing cutter's ordering."""
from app.spans import build_spans, fill_small_gaps, merge_close_spans


def matches(profile, row, phases_enabled, people_enabled):
    if not profile.enabled:
        return False
    if phases_enabled and row.get('phase') not in profile.phases:
        return False
    if people_enabled:
        try:
            return (float(row['person_count']) >= profile.min_person_count
                    and float(row['total_person_area_percent']) >= profile.min_total_area_percent)
        except (KeyError, TypeError, ValueError):
            return False
    return True


def clamp_to_duration(spans, duration):
    return [(max(0.0, start), min(duration, end)) for start, end in spans
            if min(duration, end) > max(0.0, start)]


def profile_spans(profile, rows, duration, phases_enabled=True, people_enabled=True):
    flags = [{'time_sec': r['time_sec'],
              'interesting': matches(profile, r, phases_enabled, people_enabled)} for r in rows]
    fill_small_gaps(flags, profile.max_gap_seconds)
    spans = [(start, end) for start, end in build_spans(flags) if end - start >= profile.min_span_seconds]
    spans = [(max(0.0, start - profile.margin_before_seconds), end + profile.margin_after_seconds) for start, end in spans]
    return clamp_to_duration(merge_close_spans(spans, merge_gap=1.0), duration)
