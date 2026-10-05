"""Pure gates and clip spans, reusing the existing cutter's ordering."""
from app.spans import build_spans, fill_small_gaps, merge_close_spans, sample_step


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


def still_in_view(profile, row, phases_enabled):
    """Enough people for the people join, in a part of the jump the profile keeps, whatever share they fill."""
    if phases_enabled and row.get('phase') not in profile.phases:
        return False
    try:
        return float(row['person_count']) >= profile.people_gap_count
    except (KeyError, TypeError, ValueError):
        return False


def join_while_people_in_view(profile, rows, flags, phases_enabled):
    """Fill gaps between two matches while people are still in view. Returns the row numbers it filled.

    A gap is filled when it lasts no longer than the profile's people join and, inside it, people are in view
    throughout - except that a stretch without them (the camera looked away) is let through if it is no longer
    than the ordinary join. So the two joins work together: a long one for "the group is small in the picture",
    a short one for "nobody for a moment".
    """
    step = sample_step(flags)
    filled, index = set(), 0
    while index < len(flags):
        if flags[index]['interesting']:
            index += 1
            continue
        start = index
        while index < len(flags) and not flags[index]['interesting']:
            index += 1
        between_matches = start > 0 and index < len(flags)
        length = float(flags[index - 1]['time_sec']) - float(flags[start]['time_sec']) + step
        if not between_matches or length > profile.people_gap_seconds:
            continue
        away = longest = 0
        for position in range(start, index):
            away = 0 if still_in_view(profile, rows[position], phases_enabled) else away + 1
            longest = max(longest, away)
        if longest * step <= profile.max_gap_seconds:
            filled.update(range(start, index))
    for position in filled:
        flags[position]['interesting'] = True
    return filled


def joined_flags(profile, rows, phases_enabled=True, people_enabled=True):
    """Each row as kept-or-not after both joins, and the row numbers the people join filled."""
    flags = [{'time_sec': r['time_sec'],
              'interesting': matches(profile, r, phases_enabled, people_enabled)} for r in rows]
    fill_small_gaps(flags, profile.max_gap_seconds)
    by_people = set()
    if people_enabled and profile.people_gap_seconds:
        by_people = join_while_people_in_view(profile, rows, flags, phases_enabled)
    return flags, by_people


def profile_spans(profile, rows, duration, phases_enabled=True, people_enabled=True):
    flags, _by_people = joined_flags(profile, rows, phases_enabled, people_enabled)
    spans = [(start, end) for start, end in build_spans(flags) if end - start >= profile.min_span_seconds]
    spans = [(max(0.0, start - profile.margin_before_seconds), end + profile.margin_after_seconds) for start, end in spans]
    return clamp_to_duration(merge_close_spans(spans, merge_gap=1.0), duration)
