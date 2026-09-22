import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import csv
from dataclasses import replace
import tempfile
import unittest
from unittest.mock import patch

from app.cutting import cut_profiles, plan_clips
from app.monitor import VideoProcessor
from app.outputs import (OUTPUT_LAYOUTS, clip_destination, owned_clip, reserve_identity,
                         safe_stem, source_identity)
from app.progress import QueueProgress, video_progress
from app.runtime import ProcessRunner
from app.settings import Settings, KeepProfile, settings_fingerprint, save_settings, load_settings
from app.classifiers.v4 import decoded_seconds


class OutputTests(unittest.TestCase):
    def test_same_camera_name_distinct_folders_or_contents(self):
        first = source_identity(Path('card1/GOPR0001.MP4'), 'a' * 64)
        second = source_identity(Path('card2/GOPR0001.MP4'), 'a' * 64)
        replacement = source_identity(Path('card1/GOPR0001.MP4'), 'b' * 64)
        self.assertEqual(len({x.output_name for x in (first, second, replacement)}), 3)
        self.assertEqual(first, source_identity(Path('card1/GOPR0001.MP4'), 'a' * 64))
        self.assertTrue(first.output_name.startswith('GOPR0001_'))

    def test_safe_bounded_names(self):
        self.assertEqual(safe_stem('CON'), '_CON')
        self.assertNotIn('/', safe_stem('bad/name'))
        self.assertLessEqual(len(safe_stem('x' * 300)), 60)
        self.assertEqual(safe_stem('jump 1. '), 'jump 1')

    def test_full_identity_guard_prevents_short_id_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            first = source_identity(Path('GOPR0001.MP4'), 'a' * 64)
            reserve_identity(directory, first)
            reserve_identity(directory, first)
            other = replace(source_identity(Path('GOPR0001.MP4'), 'b' * 64), output_name=first.output_name)
            with self.assertRaises(ValueError):
                reserve_identity(directory, other)

    def test_layout_shapes_and_flat_profile_uniqueness(self):
        args = ('Clips', 'flat', 'GOPR0001_1234', 'Exit + Freefall', 1, 2, 8, 'freefall')
        flat = clip_destination(*args)
        self.assertEqual(flat.parent, Path('Clips'))
        self.assertTrue(flat.name.startswith('GOPR0001_1234__exit_freefall__'))
        second = clip_destination('Clips', 'flat', 'GOPR0001_1234', 'Other', 1, 2, 8, 'freefall')
        self.assertNotEqual(flat, second)
        per_video = clip_destination('Clips', 'per_video', *args[2:])
        self.assertEqual(per_video.parent, Path('Clips/exit_freefall/GOPR0001_1234'))
        per_clip = clip_destination('Clips', 'per_clip', *args[2:])
        self.assertEqual(per_clip.parent.parent, per_video.parent)
        self.assertEqual(per_clip.parent.name, per_clip.stem)

    def test_layout_fingerprint_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            settings = Settings(output_layout='flat')
            save_settings(settings, path)
            self.assertEqual(load_settings(path).output_layout, 'flat')
        self.assertNotEqual(settings_fingerprint(Settings()), settings_fingerprint(settings))
        self.assertEqual(settings_fingerprint(replace(Settings(), cut_enabled=False)),
                         settings_fingerprint(replace(settings, cut_enabled=False)))

    def test_same_named_sources_both_get_csv_and_replacement_keeps_old_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = [root / 'input/card1/GOPR0001.MP4', root / 'input/card2/GOPR0001.MP4']
            for source, contents in zip(sources, [b'video one', b'video two']):
                source.parent.mkdir(parents=True)
                source.write_bytes(contents)
            settings = Settings(input_folder=str(root / 'input'), csv_folder=str(root / 'csv'),
                                cut_enabled=False, phases_enabled=False, people_enabled=False)
            processor = VideoProcessor(settings, ProcessRunner())
            with patch('app.monitor.probe_duration', return_value=3):
                outputs = [processor.process(source) for source in sources]
                self.assertNotEqual(outputs[0]['csv_path'], outputs[1]['csv_path'])
                original_csv = Path(outputs[0]['csv_path']).read_bytes()
                self.assertEqual(sources[0].read_bytes(), b'video one')
                sources[0].write_bytes(b'new camera footage')
                replacement = processor.process(sources[0])
            self.assertNotIn(replacement['csv_path'], [r['csv_path'] for r in outputs])
            self.assertEqual(Path(outputs[0]['csv_path']).read_bytes(), original_csv)
            self.assertEqual(len(list((root / 'csv').glob('*.timeline.csv'))), 3)

    def test_multiple_clips_and_sources_all_layouts_with_owned_cleanup(self):
        class Runner(ProcessRunner):
            def run(self, argv, **kwargs):
                Path(argv[-1]).write_bytes(b'generated clip')
                return ''
        rows = [dict(time_sec=t + .5, phase='freefall' if t in (0, 5) else 'landed') for t in range(6)]
        for layout in OUTPUT_LAYOUTS:
            with self.subTest(layout=layout), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                profile = KeepProfile(margin_before_seconds=0, margin_after_seconds=0)
                settings = Settings(output_folder=str(root), output_layout=layout, people_enabled=False,
                                    profiles=(profile, replace(profile, name='Another')))
                source = Path('card1/GOPR0001.mp4')
                other = Path('card2/GOPR0001.mp4')
                identity = source_identity(source, 'a' * 64)
                other_identity = source_identity(other, 'b' * 64)
                with patch('app.cutting.find_executable', return_value='ffmpeg'):
                    first = cut_profiles(source, rows, 6, settings, Runner(), identity)
                    second = cut_profiles(other, rows, 6, settings, Runner(), other_identity)
                    clips = list(root.rglob('*.mp4'))
                    self.assertEqual(len(clips), 8)
                    self.assertEqual(len(set(clips)), 8)
                    keep = root / 'personal.mp4'
                    keep.write_bytes(b'personal footage')
                    # Reruns keep stable paths rather than adding duplicate outputs.
                    self.assertEqual(cut_profiles(source, rows, 6, settings, Runner(), identity), first)
                    self.assertEqual(len(list(root.rglob('*.mp4'))), 9)
                    cut_profiles(source, [], 6, settings, Runner(), identity)
                    self.assertEqual(len(list(root.rglob('*.mp4'))), 5)
                    self.assertEqual(keep.read_bytes(), b'personal footage')
                    for manifest in second:
                        with Path(manifest).open(newline='') as stream:
                            self.assertTrue(all(Path(row['clip_path']).exists() for row in csv.DictReader(stream)))

    def test_cleanup_rejects_unrelated_and_outside_paths(self):
        identity = source_identity(Path('card1/GOPR0001.mp4'), 'a' * 64)
        settings = Settings(output_folder='Clips', output_layout='flat', people_enabled=False)
        _, clips = plan_clips(Path('card1/GOPR0001.mp4'), [dict(time_sec=.5, phase='freefall')],
                              2, settings.profiles[0], settings, identity)
        row = clips[0]
        self.assertTrue(owned_clip(row, 'Clips', 'flat', identity, settings.profiles[0].name))
        for changes in ({'clip_path': '../outside.mp4'}, {'source_id': 'someone else'},
                        {'profile': 'another'}, {'clip_path': 'Clips/personal.mp4'}):
            self.assertFalse(owned_clip({**row, **changes}, 'Clips', 'flat', identity, settings.profiles[0].name))


class ProgressTests(unittest.TestCase):
    def test_queue_growing_failure_cancel_and_deferred(self):
        progress = QueueProgress()
        self.assertEqual(progress.display()[0], 0)
        progress.enqueue(2)
        progress.settle('success')
        self.assertEqual(progress.display()[0], 50)
        progress.enqueue(2)
        self.assertEqual(progress.display()[0], 25)
        progress.settle('failed')
        progress.settle('cancelled')
        progress.deferred = 1
        percent, label = progress.display()
        self.assertEqual(percent, 75)
        self.assertIn('1 failed', label)
        self.assertIn('1 cancelled', label)
        self.assertIn('1 left for next run', label)

    def test_video_unknown_stage_is_busy_and_only_success_is_100(self):
        settings = Settings()
        self.assertIsNone(video_progress('phases', 0, 0, settings)[0])
        self.assertLess(video_progress('people', 5, 10, settings)[0], video_progress('people', 10, 10, settings)[0])
        self.assertEqual(video_progress('cutting', 1, 1, settings)[0], 99)
        self.assertEqual(video_progress('complete', 1, 1, settings)[0], 100)

    def test_classifier_progress_parsing(self):
        self.assertEqual(decoded_seconds('[12:00:00] Video GOPR0001.MP4: 52s decoded, 89 windows'), 52)
        self.assertIsNone(decoded_seconds('Loaded model'))


if __name__ == '__main__':
    unittest.main()
