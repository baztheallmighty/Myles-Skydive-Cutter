import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import csv
from dataclasses import replace
import tempfile
import unittest
from unittest.mock import patch
from app.cutting import MANIFEST_FIELDS, cut_profiles, ffmpeg_argv, plan_clips, validate_manifest_owner
from app.settings import Settings, KeepProfile
from app.outputs import source_identity, clip_destination, clip_manifest
from app.timeline import write_atomic_csv
from app.spans import clip_filename


class CuttingTests(unittest.TestCase):
    def identity(self, source=Path('jump.mp4')):
        return source_identity(source, 'a' * 64)

    def test_same_stem_other_source_cannot_overwrite_clips(self):
        with self.assertRaisesRegex(ValueError, 'another source'):
            validate_manifest_owner([{'source_video': 'other/jump.mp4'}], Path('jump.mp4'))
        validate_manifest_owner([{'source_video': 'jump.mp4'}], Path('jump.mp4'))

    def test_stream_copy_argv_and_audio_optional(self):
        self.assertEqual(ffmpeg_argv('ffmpeg', 'jump.mp4', 42, 67, 'out.mp4'),
            ['ffmpeg', '-hide_banner', '-nostdin', '-y', '-ss', '42.000', '-i', 'jump.mp4',
             '-t', '25.000', '-map', '0:v:0', '-map', '0:a:0?', '-c', 'copy',
             '-avoid_negative_ts', 'make_zero', 'out.mp4'])

    def test_invalid_bounds(self):
        for start, end in [(-1, 2), (2, 2), (3, 2)]:
            with self.assertRaises(ValueError):
                ffmpeg_argv('ffmpeg', 'jump.mp4', start, end, 'out.mp4')

    def test_filename_reuses_existing_contract(self):
        self.assertEqual(clip_filename(1, 42, 67, 'freefall'), 'clip_001_000042s-000067s_freefall.mp4')

    def test_manifest_path_and_dominant_phase(self):
        p = KeepProfile(margin_before_seconds=0, margin_after_seconds=0)
        settings = Settings(output_folder='output', people_enabled=False)
        rows = [dict(time_sec=t, phase='freefall') for t in (.5, 1.5, 2.5)]
        identity = self.identity()
        manifest, clips = plan_clips(Path('jump.mp4'), rows, 3, p, settings, identity)
        self.assertEqual(manifest, clip_manifest('output', 'per_video', identity.output_name, p.name))
        self.assertEqual(list(clips[0]), MANIFEST_FIELDS)
        self.assertEqual(clips[0]['end_sec'], 3)
        self.assertEqual(clips[0]['dominant_phase'], 'freefall')
        self.assertEqual(Path(clips[0]['clip_path']).parent, Path('output/exit_freefall') / identity.output_name)

    def test_all_token_without_phases(self):
        settings = Settings(output_folder='output', phases_enabled=False, people_enabled=False)
        _, clips = plan_clips(Path('jump.mp4'), [dict(time_sec=.5, phase='NA')], 2, KeepProfile(), settings, self.identity())
        self.assertEqual(clips[0]['dominant_phase'], 'all')
        self.assertTrue(clips[0]['clip_path'].endswith('_all.mp4'))

    def test_empty_manifest_has_header(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.csv'
            write_atomic_csv(path, [], MANIFEST_FIELDS)
            with path.open(newline='') as stream:
                self.assertEqual(next(csv.reader(stream)), MANIFEST_FIELDS)

    def test_no_matches_removes_only_previously_owned_clips(self):
        class Runner:
            def check_cancelled(self): pass
            def report_progress(self, *args): pass
            def run(self, argv): raise AssertionError('No ffmpeg should run for empty spans')
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(output_folder=directory, people_enabled=False)
            source = Path('jump.mp4')
            manifest, clips = plan_clips(source, [dict(time_sec=.5, phase='freefall')],
                                          2, settings.profiles[0], settings, self.identity(source))
            previous = Path(clips[0]['clip_path'])
            previous.parent.mkdir(parents=True)
            previous.write_bytes(b'old clip')
            unrelated = previous.parent / 'personal.mp4'
            unrelated.write_bytes(b'keep me')
            write_atomic_csv(manifest, clips, MANIFEST_FIELDS)
            cut_profiles(source, [dict(time_sec=.5, phase='landed')], 2, settings, Runner(), self.identity(source))
            self.assertFalse(previous.exists())
            self.assertEqual(unrelated.read_bytes(), b'keep me')
            with manifest.open(newline='') as stream:
                self.assertEqual(list(csv.DictReader(stream)), [])

    def test_locked_manifest_does_not_delete_old_clips(self):
        class Runner:
            def check_cancelled(self): pass
            def report_progress(self, *args): pass
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(output_folder=directory, people_enabled=False)
            source = Path('jump.mp4')
            manifest, clips = plan_clips(source, [dict(time_sec=.5, phase='freefall')],
                                          2, settings.profiles[0], settings, self.identity(source))
            previous = Path(clips[0]['clip_path'])
            previous.parent.mkdir(parents=True)
            previous.write_bytes(b'old clip')
            write_atomic_csv(manifest, clips, MANIFEST_FIELDS)
            original = manifest.read_bytes()
            with patch('app.cutting.write_atomic_csv', side_effect=OSError('locked')):
                with self.assertRaises(OSError):
                    cut_profiles(source, [dict(time_sec=.5, phase='landed')], 2, settings, Runner(), self.identity(source))
            self.assertEqual(previous.read_bytes(), b'old clip')
            self.assertEqual(manifest.read_bytes(), original)

    def test_failed_cut_keeps_existing_manifest_and_clips(self):
        class Runner:
            def check_cancelled(self): pass
            def report_progress(self, *args): pass
            def log(self, message): pass
            def run(self, argv, **kwargs): raise RuntimeError('encoder failed')
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(output_folder=directory, people_enabled=False)
            rows = [dict(time_sec=.5, phase='freefall')]
            manifest, clips = plan_clips(Path('jump.mp4'), rows, 2, settings.profiles[0], settings, self.identity())
            manifest.parent.mkdir(parents=True)
            write_atomic_csv(manifest, clips, MANIFEST_FIELDS)
            original_manifest = manifest.read_bytes()
            clip = Path(clips[0]['clip_path'])
            clip.parent.mkdir(parents=True)
            clip.write_bytes(b'previous')
            with patch('app.cutting.find_executable', return_value='ffmpeg'):
                with self.assertRaises(RuntimeError):
                    cut_profiles(Path('jump.mp4'), rows, 2, settings, Runner(), self.identity())
            self.assertEqual(manifest.read_bytes(), original_manifest)
            self.assertEqual(clip.read_bytes(), b'previous')


if __name__ == '__main__':
    unittest.main()
