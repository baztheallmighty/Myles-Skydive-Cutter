import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dataclasses import replace
import json
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from app import PROJECT_ROOT
from app.monitor import (VideoProcessor, existing_complete, file_signature,
    ledger_entry, load_ledger, needs_processing, save_ledger, scan_folder, stable_candidates)
from app.classifiers import CLASSIFIERS, Classifier, PhaseResult, classify_phases, validate_result
from app.classifiers.v4 import engine_argv
from app.runtime import ProcessRunner, Cancelled
from app.settings import (Settings, KeepProfile, load_settings, save_settings,
                          settings_fingerprint, state_directory, validate_settings)
from v3_poc.common import key


class MonitorTests(unittest.TestCase):
    def test_stability_requires_two_unchanged_polls(self):
        self.assertEqual(stable_candidates({}, {'a': (10, 1)}, {}, 'fp'), [])
        self.assertEqual(stable_candidates({'a': (10, 1)}, {'a': (10, 2)}, {}, 'fp'), [])
        self.assertEqual(stable_candidates({'a': (10, 2)}, {'a': (10, 2)}, {}, 'fp'), ['a'])

    def test_empty_and_pending_files_not_queued(self):
        snap = {'a': (10, 2), 'b': (0, 1)}
        self.assertEqual(stable_candidates(snap, snap, {}, 'fp', {'a'}), [])

    def test_ledger_suppression_and_staleness(self):
        entry = ledger_entry((10, 1), 'fp', 'success')
        self.assertFalse(needs_processing(entry, (10, 1), 'fp'))
        self.assertTrue(needs_processing(entry, (10, 2), 'fp'))
        self.assertTrue(needs_processing(entry, (11, 1), 'fp'))
        self.assertTrue(needs_processing(entry, (10, 1), 'new'))
        self.assertTrue(needs_processing({**entry, 'status': 'failed'}, (10, 1), 'fp'))
        self.assertTrue(needs_processing({**entry, 'status': 'skipped_frozen'}, (10, 1), 'fp'))

    def test_fingerprint_tracks_settings_profiles_and_output_mode(self):
        base = Settings()
        fp = settings_fingerprint(base)
        for changed in (replace(base, cut_enabled=False),
                        replace(base, people_enabled=False), replace(base, sample_fps=2),
                        replace(base, profiles=(replace(base.profiles[0], min_person_count=2),)),
                        replace(base, csv_folder=str(PROJECT_ROOT / 'different'))):
            self.assertNotEqual(settings_fingerprint(changed), fp)
        self.assertEqual(settings_fingerprint(replace(base, poll_seconds=20)), fp)

    def test_settings_defaults_unknown_keys_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            path.write_text(json.dumps({'future': 7, 'profiles': [{'name': 'Example', 'future': True}]}))
            settings = load_settings(path)
            self.assertEqual(settings.sample_fps, 1)
            self.assertEqual(settings.profiles[0].phases, frozenset({'exit', 'freefall'}))
            save_settings(settings, path)
            self.assertEqual(load_settings(path), settings)

    def test_invalid_and_colliding_profiles_rejected(self):
        for profiles in [(KeepProfile(name='../'), KeepProfile(name='unknown')),
                         (KeepProfile(name='A B'), KeepProfile(name='a-b')),
                         (KeepProfile(name='CON'),), (KeepProfile(name='bad;name'),),
                         (KeepProfile(margin_before_seconds=float('nan'), margin_after_seconds=float('nan')), )]:
            with self.assertRaises(ValueError):
                validate_settings(Settings(profiles=profiles))

    def test_scan_excludes_outputs_but_allows_duplicate_camera_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out = root / 'out'
            out.mkdir()
            (out / 'clip.mp4').write_bytes(b'clip')
            (root / 'JUMP.mp4').write_bytes(b'video')
            (root / 'jump.mov').write_bytes(b'video')
            settings = Settings(input_folder=str(root), output_folder=str(out), csv_folder=str(out / 'csv'))
            files = scan_folder(settings)
            self.assertEqual(len(files), 2)
            self.assertEqual({p.name for p, _ in files.values()}, {'JUMP.mp4', 'jump.mov'})

    def test_ledger_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '_state' / 'ledger.json'
            ledger = load_ledger(path)
            ledger['entries']['a'] = ledger_entry((1, 2), 'fp', 'success')
            save_ledger(path, ledger)
            self.assertEqual(load_ledger(path), ledger)

    def test_existing_only_waits_for_unstable_and_retries_changed_attempt(self):
        snap = {'a': (10, 2)}
        self.assertFalse(existing_complete(snap, {}, 'fp', {}))
        self.assertTrue(existing_complete(snap, {}, 'fp', snap))
        self.assertFalse(existing_complete(snap, {}, 'fp', {'a': (10, 1)}))

    def test_old_research_settings_are_discarded_on_save(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            path.write_text(json.dumps({'allow_frozen': False, 'audio_model': 'v3', 'cut_enabled': False}))
            settings = load_settings(path)
            self.assertFalse(settings.cut_enabled)
            self.assertEqual(settings.phase_classifier, 'standard')
            save_settings(settings, path)
            saved = json.loads(path.read_text())
            self.assertNotIn('allow_frozen', saved)
            self.assertNotIn('audio_model', saved)

    def test_csv_only_needs_no_clip_destination_and_never_calls_cutter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'input').mkdir()
            source = root / 'input/jump.mp4'
            source.write_bytes(b'fixture')
            settings = Settings(input_folder=str(source.parent), csv_folder=str(root / 'csv'),
                                output_folder='', cut_enabled=False, phases_enabled=False, people_enabled=False)
            validate_settings(settings, require_folders=True)
            self.assertEqual(state_directory(settings), root / 'csv/_state')
            self.assertIn(key(source), scan_folder(settings))
            with patch('app.monitor.probe_duration', return_value=3), patch('app.monitor.cut_profiles') as cut:
                result = VideoProcessor(settings, ProcessRunner()).process(source)
                cut.assert_not_called()
            self.assertTrue(Path(result['csv_path']).is_file())
            self.assertEqual(result['manifests'], [])

    def test_csv_only_does_not_touch_existing_clip_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'input').mkdir()
            source = root / 'input/jump.mp4'
            source.write_bytes(b'fixture')
            clips = root / 'clips'
            clips.mkdir()
            preserved = clips / 'existing.mp4'
            preserved.write_bytes(b'existing clip')
            settings = Settings(input_folder=str(source.parent), csv_folder=str(root / 'csv'),
                                output_folder=str(clips), cut_enabled=False, phases_enabled=False, people_enabled=False)
            with patch('app.monitor.probe_duration', return_value=3):
                VideoProcessor(settings, ProcessRunner()).process(source)
            self.assertEqual(list(clips.iterdir()), [preserved])
            self.assertEqual(preserved.read_bytes(), b'existing clip')

    def test_classifier_can_be_replaced_without_changing_consumer(self):
        expected = PhaseResult([dict(start_sec=0., end_sec=3., phase='freefall')], 3.)
        calls = []
        def predict(source, settings, runner):
            calls.append(source)
            return expected
        classifier = Classifier('alternative', 'Alternative', '1', predict)
        with patch.dict(CLASSIFIERS, {'alternative': classifier}):
            settings = Settings(phase_classifier='alternative')
            segments, duration, directory, _agreement = classify_phases(Path('jump.mp4'), settings, ProcessRunner())
            self.assertEqual(segments, expected.segments)
            self.assertEqual(duration, 3)
            self.assertIsNone(directory)
            self.assertEqual(calls, [Path('jump.mp4')])
            before = settings_fingerprint(settings)
            CLASSIFIERS['alternative'] = replace(classifier, revision='2')
            self.assertNotEqual(before, settings_fingerprint(settings))

    def test_classifier_rejects_incomplete_timeline(self):
        with self.assertRaises(ValueError):
            validate_result(PhaseResult([dict(start_sec=1., end_sec=3., phase='freefall')], 3.))
        with self.assertRaises(ValueError):
            validate_result(PhaseResult([dict(start_sec=0., end_sec=2., phase='freefall')], 3.))

    def test_adapter_keeps_backend_details_out_of_activity_log(self):
        from app.classifiers.v4 import classify
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(csv_folder=directory, cut_enabled=False)
            runner = Mock()
            runner.run.return_value = 'engine diagnostics'
            segments = [dict(start_sec=0., end_sec=3., phase='freefall')]
            with patch('app.classifiers.v4.read_result',
                       return_value={'tracks': {'final': segments}, 'duration_sec': 3.0}):
                result = classify(Path('jump.mp4'), settings, runner)
            self.assertFalse(runner.run.call_args.kwargs['echo'])
            runner.log.assert_called_once_with('Jump phases classified.')
            self.assertEqual((result.work_directory / 'engine.log').read_text(), 'engine diagnostics')
            runner.run.side_effect = RuntimeError('engine internal error')
            with self.assertRaisesRegex(RuntimeError, 'Could not classify this video') as error:
                classify(Path('jump.mp4'), settings, runner)
            self.assertNotIn('internal', str(error.exception))

    def test_changed_queued_source_does_not_run(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'jump.mp4'
            source.write_bytes(b'changed')
            processor = VideoProcessor(Settings(), ProcessRunner())
            with self.assertRaisesRegex(RuntimeError, 'after being queued'):
                processor.process(source, (0, 0))

    def test_cancel_prevents_subprocess_creation(self):
        runner = ProcessRunner()
        runner.cancelled.set()
        with patch('app.runtime.subprocess.Popen') as popen:
            with self.assertRaises(Cancelled):
                runner.run(['never-run'])
            popen.assert_not_called()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows desktop subprocess ownership')
    def test_live_owned_subprocess_tree_cancels_promptly(self):
        runner = ProcessRunner()
        self.assertEqual(runner.run([sys.executable, '-u', '-c', 'print("ok")'], echo=False).strip(), 'ok')
        runner.log = lambda line: runner.cancelled.set() if line == 'ready' else None
        code = ('import subprocess,sys,time; '
                'subprocess.Popen([sys.executable,"-c","import time;time.sleep(10)"]); '
                'print("ready",flush=True); time.sleep(10)')
        began = time.monotonic()
        with self.assertRaises(Cancelled):
            runner.run([sys.executable, '-u', '-c', code])
        self.assertLess(time.monotonic() - began, 5)

    def test_engine_gets_the_device_batch_and_view(self):
        def value(argv, flag):
            return argv[argv.index(flag) + 1]
        argv = engine_argv(Path('jump.mp4'), 'run', Settings(device='cpu', batch_size=4))
        self.assertEqual(argv[argv.index('-m') + 1], 'cutter_v4.engine')
        self.assertEqual((value(argv, '--device'), value(argv, '--batch-size'), value(argv, '--view')), ('cpu', '4', 'front'))
        # Phases always come from one view; counting people all round does not change it.
        self.assertEqual(value(engine_argv(Path('a.360'), 'run', Settings(view_mode='front_back')), '--view'), 'front')
        self.assertEqual(value(engine_argv(Path('a.360'), 'run', Settings(view_mode='back')), '--view'), 'back')


if __name__ == '__main__':
    unittest.main()
