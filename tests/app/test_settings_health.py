"""Settings, the processing fingerprint, and the health check that decides whether a run may start."""
import json
import sys
from dataclasses import fields, replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app import health  # noqa: E402
from app.settings import (KeepProfile, Settings, load_settings, profile_presets, save_settings,  # noqa: E402
                          settings_fingerprint, state_directory, validate_settings)


def saved(tmp_path, **changes):
    path = tmp_path / 'settings.json'
    save_settings(Settings(**changes), path)
    return path


class TestValidation:
    def test_defaults_are_valid(self):
        validate_settings(Settings())

    @pytest.mark.parametrize('changes, message', [
        ({'device': 'tpu'}, 'processing device'),
        ({'view_mode': 'sideways'}, '360 view'),
        ({'output_layout': 'spiral'}, 'clip folder layout'),
        ({'batch_size': 0}, 'Batch size'),
        ({'detection_confidence': 0}, 'Detection confidence'),
        ({'sample_fps': 0}, 'sample_fps'),
        ({'profiles': (KeepProfile(name='has; semicolon'),)}, 'semicolons'),
        ({'profiles': (KeepProfile(min_person_count=-1),)}, 'Minimum people'),
        ({'profiles': (KeepProfile(name='One'), KeepProfile(name='one'))}, 'different output folder names'),
    ])
    def test_bad_settings_are_refused_with_a_readable_reason(self, changes, message):
        with pytest.raises(ValueError, match=message):
            validate_settings(Settings(**changes))

    def test_folders_are_only_checked_when_asked(self, tmp_path):
        settings = Settings(input_folder=str(tmp_path / 'missing'))
        validate_settings(settings)
        with pytest.raises(ValueError, match='input folder'):
            validate_settings(settings, require_folders=True)

    def test_output_cannot_contain_the_input(self, tmp_path):
        inputs = tmp_path / 'clips' / 'input'
        inputs.mkdir(parents=True)
        settings = Settings(input_folder=str(inputs), output_folder=str(tmp_path / 'clips'),
                            csv_folder=str(tmp_path / 'clips' / 'timelines'))
        with pytest.raises(ValueError, match='cannot contain'):
            validate_settings(settings, require_folders=True)


class TestSavedFile:
    def test_round_trip(self, tmp_path):
        original = Settings(input_folder='C:/in', output_folder='C:/out', csv_folder='C:/csv',
                            view_mode='front_back', open_sections=('output', 'people'))
        path = tmp_path / 'settings.json'
        save_settings(original, path)
        assert load_settings(path) == original

    def test_a_missing_file_gives_defaults(self, tmp_path):
        assert load_settings(tmp_path / 'nothing.json') == Settings()

    def test_unknown_fields_are_ignored(self, tmp_path):
        path = saved(tmp_path)
        data = json.loads(path.read_text(encoding='utf-8'))
        data['something_from_the_future'] = 42
        path.write_text(json.dumps(data), encoding='utf-8')
        assert load_settings(path).batch_size == Settings().batch_size

    def test_the_old_single_margin_is_kept_on_both_sides(self, tmp_path):
        path = saved(tmp_path)
        data = json.loads(path.read_text(encoding='utf-8'))
        data['profiles'][0].pop('margin_before_seconds')
        data['profiles'][0].pop('margin_after_seconds')
        data['profiles'][0]['margin_seconds'] = 4.0
        path.write_text(json.dumps(data), encoding='utf-8')
        profile = load_settings(path).profiles[0]
        assert (profile.margin_before_seconds, profile.margin_after_seconds) == (4.0, 4.0)


class TestFingerprint:
    """The fingerprint decides whether a library is processed again, so it has to be exactly as fussy as it should."""

    base = Settings(input_folder='C:/in', output_folder='C:/out', csv_folder='C:/csv', yolo_model='C:/yolo.pt')

    @pytest.mark.parametrize('field_name', [f.name for f in fields(Settings)
                                            if f.metadata.get('affects_output') is False])
    def test_preferences_never_reprocess(self, field_name):
        values = {'input_folder': 'C:/elsewhere', 'poll_seconds': 30.0, 'keep_watching': True,
                  'recut_on_review': False, 'window_geometry': 'AAA', 'column_state': 'BBB',
                  'open_sections': ('output',), 'device': 'cpu', 'batch_size': 2}
        changed = replace(self.base, **{field_name: values[field_name]})
        assert settings_fingerprint(changed) == settings_fingerprint(self.base)

    @pytest.mark.parametrize('changes', [
        {'view_mode': 'back'}, {'people_enabled': False}, {'phases_enabled': False}, {'cut_enabled': False},
        {'output_layout': 'flat'}, {'sample_fps': 2.0}, {'detection_confidence': .5},
        {'csv_folder': 'C:/other'},
        {'profiles': (KeepProfile(min_person_count=3),)},
    ])
    def test_anything_that_changes_output_does_reprocess(self, changes):
        assert settings_fingerprint(replace(self.base, **changes)) != settings_fingerprint(self.base)

    def test_every_field_is_decided_one_way_or_the_other(self):
        """A new setting must either change the fingerprint or be marked a preference.

        Forgetting reprocesses everyone's library on upgrade, which is the kind of mistake nobody notices until the
        machine has been busy for an hour.
        """
        nudge = {str: lambda v: (v or 'x') + 'x', bool: lambda v: not v, int: lambda v: v + 1,
                 float: lambda v: v + 1.0, tuple: lambda v: v + ('output',)}
        undecided = []
        for spec in fields(Settings):
            if spec.name in {'profiles', 'phase_classifier'} or spec.metadata.get('affects_output') is False:
                continue   # profiles and the classifier reach the fingerprint through their own entries
            if spec.name == 'output_folder':
                continue   # decided by where the ledger lives: see test_another_clip_folder_is_another_ledger
            value = getattr(self.base, spec.name)
            change = nudge.get(type(value))
            assert change, f'{spec.name}: this test needs a way to change a {type(value).__name__}'
            if settings_fingerprint(replace(self.base, **{spec.name: change(value)})) == settings_fingerprint(self.base):
                undecided.append(spec.name)
        assert not undecided, f'these settings change nothing and are not marked preferences: {undecided}'

    def test_another_clip_folder_is_another_ledger(self):
        """The clip folder is not in the fingerprint because the ledger lives inside it: a new one starts empty."""
        other = replace(self.base, output_folder='D:/elsewhere')
        assert state_directory(other) != state_directory(self.base)
        assert state_directory(replace(self.base, cut_enabled=False)) == Path('C:/csv') / '_state'

    def test_moving_the_app_or_the_drive_does_not_reprocess(self):
        """A new version unzipped beside the old one, or the library drive back as another letter."""
        moved = replace(self.base, yolo_model='D:/Skydive-Cutter-2.3.2/yolo11n.pt', output_folder='G:/out',
                        csv_folder='G:/csv', input_folder='G:/in')
        base = replace(self.base, yolo_model='C:/Skydive-Cutter-2.3.1/yolo11n.pt')
        assert settings_fingerprint(moved) == settings_fingerprint(base)
        assert settings_fingerprint(replace(base, yolo_model='C:/yolo11s.pt')) != settings_fingerprint(base)

    def test_ledgers_from_before_the_format_changed_still_count(self):
        from app.settings import accepted_fingerprints, legacy_settings_fingerprint
        current, legacy = accepted_fingerprints(self.base)
        assert current == settings_fingerprint(self.base) and legacy == legacy_settings_fingerprint(self.base)
        assert current != legacy

    def test_where_it_runs_does_not_reprocess(self):
        """Switching to the processor, or a smaller batch, is a speed choice, not a different answer."""
        for changes in ({'device': 'cpu'}, {'device': 'cuda'}, {'batch_size': 2}):
            assert settings_fingerprint(replace(self.base, **changes)) == settings_fingerprint(self.base)

    def test_a_disabled_profile_is_ignored(self):
        with_disabled = replace(self.base, profiles=(KeepProfile(), KeepProfile(name='Off', enabled=False)))
        assert settings_fingerprint(with_disabled) == settings_fingerprint(replace(self.base, profiles=(KeepProfile(),)))


class TestPresets:
    def test_the_shipped_presets_are_all_valid(self):
        for preset in profile_presets():
            validate_settings(Settings(profiles=(preset,)))

    def test_sky_only_presets_ask_for_nobody(self):
        by_name = {p.name: p for p in profile_presets()}
        assert by_name['Whole skydive'].min_person_count == 0
        assert by_name['Canopy flight'].min_person_count == 0
        assert by_name['Group freefall'].min_person_count == 2


class TestHealth:
    def check(self, monkeypatch, *, people=True, cuda=True, settings=None, models=(), tools=()):
        monkeypatch.setattr(health, 'people_installed', lambda s=None: people)
        monkeypatch.setattr(health, 'missing_models', lambda: list(models))
        monkeypatch.setattr(health, 'missing_tools', lambda: list(tools))
        monkeypatch.setattr(health, 'missing_packages', lambda: [])
        return health.check_install(settings or Settings(), cuda_available=cuda)

    def test_a_healthy_install_says_nothing(self, monkeypatch):
        checks = self.check(monkeypatch)
        assert health.blocking(checks) == [] and health.summary(checks) == ''

    def test_a_missing_detector_blocks_the_run(self, monkeypatch):
        checks = self.check(monkeypatch, people=False)
        blocked = health.blocking(checks)
        assert [c.key for c in blocked] == ['people']
        assert blocked[0].repairable and blocked[0].section == 'people'
        assert 'not installed' in health.summary(checks)

    def test_a_missing_detector_only_warns_when_no_profile_wants_people(self, monkeypatch):
        settings = Settings(people_enabled=False,
                            profiles=(KeepProfile(min_person_count=0, min_total_area_percent=0),))
        checks = self.check(monkeypatch, people=False, settings=settings)
        assert health.blocking(checks) == []
        assert [c.state for c in checks if c.key == 'people'] == [health.WARNING]

    def test_a_profile_that_wants_people_is_enough_to_block(self, monkeypatch):
        settings = Settings(people_enabled=False, profiles=(KeepProfile(min_person_count=1),))
        assert [c.key for c in health.blocking(self.check(monkeypatch, people=False, settings=settings))] == ['people']

    def test_no_gpu_is_amber_not_red(self, monkeypatch):
        checks = self.check(monkeypatch, cuda=False)
        assert health.blocking(checks) == []
        assert 'NVIDIA' in health.summary(checks)

    def test_asking_for_a_gpu_that_is_not_there_is_red(self, monkeypatch):
        checks = self.check(monkeypatch, cuda=False, settings=Settings(device='cuda'))
        assert [c.key for c in health.blocking(checks)] == ['gpu']

    def test_missing_models_and_tools_block(self, monkeypatch):
        checks = self.check(monkeypatch, models=['visual.pt'], tools=['ffmpeg'])
        assert {c.key for c in health.blocking(checks)} == {'models', 'ffmpeg'}

    def test_worst_first(self, monkeypatch):
        checks = self.check(monkeypatch, people=False, cuda=False)
        assert checks[0].state == health.ERROR and checks[1].state == health.WARNING
