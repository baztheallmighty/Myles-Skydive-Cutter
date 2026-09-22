import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import csv
from dataclasses import replace
import tempfile
import unittest
from unittest.mock import patch

from app.settings import Settings, KeepProfile
from app.timeline import FIELDS, PERSON_FIELDS, canonical_grid, segment_at, join_timeline, write_atomic_csv
from v3_poc.common import intervals


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.segments = [dict(start_sec=0, end_sec=1.5, phase='exit', mean_model_probability=.123456),
                         dict(start_sec=1.5, end_sec=4, phase='freefall', mean_model_probability=.75)]
        self.people = [dict(time_sec=t, person_count=2, largest_person_area_percent=15.0,
                            total_person_area_percent=30.0) for t in (.5, 1.5, 2.5, 3.5)]

    def test_grid_offset_and_duration(self):
        self.assertEqual(canonical_grid(4), [.5, 1.5, 2.5, 3.5])
        self.assertEqual(canonical_grid(2, 2), [.5, 1, 1.5])
        self.assertEqual(canonical_grid(.5), [])
        self.assertEqual(canonical_grid(1.5), [.5])
        self.assertEqual(canonical_grid(4, 10, False), [.5, 1.5, 2.5, 3.5])

    def test_invalid_grid_parameters(self):
        for duration, rate in [(0, 1), (10, 0), (float('nan'), 1), (1, float('inf'))]:
            with self.assertRaises(ValueError):
                canonical_grid(duration, rate)

    def test_exact_midpoint_chooses_right_segment(self):
        self.assertEqual(segment_at(1.5, self.segments)['phase'], 'freefall')
        self.assertEqual(segment_at(1.4999, self.segments)['phase'], 'exit')

    def test_real_common_intervals_have_unique_half_open_membership(self):
        segments = intervals([2, 3, 6], [1, 2, 3], 4)
        for t in canonical_grid(4):
            matches = [s for s in segments if s['start_sec'] <= t < s['end_sec']]
            self.assertEqual(len(matches), 1)
            self.assertEqual(segment_at(t, segments), matches[0])

    def test_missing_phase_is_error(self):
        with self.assertRaises(ValueError):
            segment_at(5, self.segments)

    def test_header_and_na_all_toggle_combinations(self):
        with tempfile.TemporaryDirectory() as directory:
            for phases in (False, True):
                for people in (False, True):
                    settings = Settings(phases_enabled=phases, people_enabled=people)
                    rows = join_timeline('jump.mp4', 4, self.segments, self.people, settings)
                    path = Path(directory) / 'timeline.csv'
                    write_atomic_csv(path, rows)
                    with path.open(newline='', encoding='utf-8') as stream:
                        reader = csv.DictReader(stream)
                        self.assertEqual(reader.fieldnames, FIELDS)
                        first = next(reader)
                    self.assertEqual(first['phase'] == 'NA', not phases)
                    self.assertEqual(first['phase_model_probability'] == 'NA', not phases)
                    for name in PERSON_FIELDS:
                        self.assertEqual(first[name] == 'NA', not people)
                    self.assertEqual(first['time_sec'], '0.500')
                    if phases:
                        self.assertEqual(first['phase_model_probability'], '0.123')

    def test_profile_names_are_unpadded(self):
        p = KeepProfile(phases=frozenset({'exit'}), margin_before_seconds=100, margin_after_seconds=100)
        rows = join_timeline('jump.mp4', 4, self.segments, self.people, Settings(profiles=(p,)))
        self.assertEqual([r['matched_profiles'] for r in rows], [p.name, '', '', ''])
        self.assertEqual(rows, join_timeline('jump.mp4', 4, self.segments, self.people,
                                            Settings(profiles=(replace(p, margin_before_seconds=0, margin_after_seconds=0),))))

    def test_missing_people_is_error_not_zero(self):
        with self.assertRaises(ValueError):
            join_timeline('jump.mp4', 4, self.segments, self.people[:1], Settings())

    def test_failed_atomic_replace_preserves_previous_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'timeline.csv'
            path.write_text('previous')
            with patch('app.timeline.os.replace', side_effect=OSError('locked')):
                with self.assertRaises(OSError):
                    write_atomic_csv(path, [])
            self.assertEqual(path.read_text(), 'previous')
            self.assertFalse(path.with_suffix('.csv.tmp').exists())


if __name__ == '__main__':
    unittest.main()
