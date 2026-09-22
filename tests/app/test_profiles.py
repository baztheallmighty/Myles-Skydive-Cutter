import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dataclasses import replace
import unittest
from app.settings import KeepProfile
from app.profiles import matches, profile_spans, clamp_to_duration


class ProfilesTests(unittest.TestCase):
    def setUp(self):
        self.profile = KeepProfile(min_person_count=2, min_total_area_percent=30)
        self.row = dict(time_sec=5.5, phase='freefall', person_count=2,
                        total_person_area_percent=30, largest_person_area_percent=15)

    def test_inclusive_total_area_and_count(self):
        self.assertTrue(matches(self.profile, self.row, True, True))
        self.assertFalse(matches(self.profile, {**self.row, 'total_person_area_percent': 29.99}, True, True))
        self.assertFalse(matches(self.profile, {**self.row, 'person_count': 1}, True, True))

    def test_disabled_phase_gate_passes(self):
        self.assertTrue(matches(self.profile, {**self.row, 'phase': 'NA'}, False, True))
        self.assertFalse(matches(self.profile, {**self.row, 'phase': 'NA'}, True, True))

    def test_disabled_people_gates_pass(self):
        self.assertTrue(matches(self.profile, {'phase': 'freefall'}, True, False))
        self.assertFalse(matches(self.profile, {'phase': 'freefall'}, True, True))

    def test_disabled_profile_never_matches(self):
        self.assertFalse(matches(replace(self.profile, enabled=False), self.row, False, False))

    def test_both_classifiers_off(self):
        self.assertTrue(matches(self.profile, {}, False, False))

    def test_margin_both_ends_and_rows_unchanged(self):
        rows = [self.row]
        # The default profile keeps 1 s before and 2 s after, so a single 5.5-6.5 s sample becomes 4.5-8.5.
        self.assertEqual(profile_spans(self.profile, rows, 20), [(4.5, 8.5)])
        self.assertEqual(rows, [self.row])

    def test_clamp_and_empty_spans(self):
        self.assertEqual(clamp_to_duration([(-3, 4), (8, 20), (11, 12), (5, 5)], 10), [(0, 4), (8, 10)])
        self.assertEqual(clamp_to_duration([], 10), [])

    def test_independent_overlapping_profiles(self):
        second = replace(self.profile, name='Another', margin_before_seconds=0, margin_after_seconds=0)
        self.assertEqual(profile_spans(self.profile, [self.row], 20), [(4.5, 8.5)])
        self.assertEqual(profile_spans(second, [self.row], 20), [(5.5, 6.5)])

    def test_minimum_before_padding(self):
        self.assertEqual(profile_spans(replace(self.profile, min_span_seconds=2, margin_before_seconds=10, margin_after_seconds=10),
                                       [self.row], 20), [])

    def test_bridge_gap_and_clamp_padding(self):
        rows = [{**self.row, 'time_sec': t, 'phase': phase} for t, phase in
                [(0.5, 'exit'), (1.5, 'canopy_flight'), (2.5, 'freefall')]]
        p = replace(self.profile, max_gap_seconds=1, min_span_seconds=3)
        self.assertEqual(profile_spans(p, rows, 3.1), [(0, 3.1)])

    def test_long_dip_is_not_bridged(self):
        rows = [{**self.row, 'time_sec': t + .5, 'phase': 'exit' if t in (0, 5) else 'landed'}
                for t in range(6)]
        p = replace(self.profile, max_gap_seconds=1, margin_before_seconds=0, margin_after_seconds=0)
        self.assertEqual(profile_spans(p, rows, 6), [(.5, 1.5), (5.5, 6)])


if __name__ == '__main__':
    unittest.main()
