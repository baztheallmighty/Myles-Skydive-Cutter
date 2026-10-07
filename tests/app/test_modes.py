"""Basic and advanced: the built-in choices, a folder per profile, and clips named after their video.

Basic mode is three ticks. Behind them are ordinary profiles, each with a folder of its own inside the clips folder,
so everything the ticks do can also be done, and changed, on the advanced screen.
"""
import json
import os
import shutil
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from app.outputs import named_clip, plain_name, profile_root  # noqa: E402
from app.profiles import profile_spans  # noqa: E402
from app.settings import (A_CANOPY, A_GRADE, B_GRADE, LANDING, TRIM, KeepProfile, Settings, built_in_profiles,  # noqa: E402
                          load_settings, save_settings, settings_fingerprint, validate_profile, with_built_ins)
from conftest import clips_of, make_settings, process  # noqa: E402


def jump():
    """A whole jump, one look a second: plane, exit, freefall with the group near then far, opening, canopy, landing."""
    parts = ([('inside_plane', 2, 60)] * 5 + [('exit', 2, 40)] * 3 + [('freefall', 2, 30)] * 6 + [('freefall', 3, 12)] * 4
             + [('break_off', 1, 4)] * 3 + [('opening_parachutes', 0, 0)] * 4 + [('canopy_flight', 1, 8)] * 10
             + [('landing', 1, 15)] * 4 + [('landed', 1, 30)] * 6)
    return [{'time_sec': f'{index + .5:.3f}', 'phase': phase, 'person_count': str(count),
             'total_person_area_percent': str(area)} for index, (phase, count, area) in enumerate(parts)]


class TestTheBuiltInChoices:
    def test_trim_is_the_jump_itself_whoever_is_in_view(self):
        spans = profile_spans(replace(built_in_profiles()[TRIM], enabled=True), jump(), 45.0)
        assert spans == [(3.5, 26.5)], '2 s before the first look in exit (5.5 s) to 1 s after the last of the opening'

    def test_landing_is_the_approach_with_five_seconds_either_side(self):
        spans = profile_spans(replace(built_in_profiles()[LANDING], enabled=True), jump(), 45.0)
        assert spans == [(30.5, 44.5)], 'the landing is seen from 35.5 to 39.5 s'

    def test_b_grade_keeps_everything_a_grade_keeps_and_more(self):
        a = profile_spans(replace(built_in_profiles()[A_GRADE], enabled=True), jump(), 45.0)
        b = profile_spans(replace(built_in_profiles()[B_GRADE], enabled=True), jump(), 45.0)
        assert a == [(3.5, 16.5)] and b == [(3.5, 21.5)], 'B carries on while the group fills 12% of the picture'
        assert all(any(start >= b_start and end <= b_end for b_start, b_end in b) for start, end in a)

    def test_companions_share_their_parents_folder_and_everything_starts_switched_off(self):
        built = built_in_profiles()
        assert built[LANDING].folder == TRIM and built[A_CANOPY].folder == A_GRADE
        assert not any(profile.enabled for profile in built.values())
        for profile in built.values():
            validate_profile(profile)

    def test_they_are_added_to_an_existing_list_without_touching_it(self):
        mine = KeepProfile(name='Mine')
        edited = replace(built_in_profiles()[B_GRADE], min_total_area_percent=5.0, enabled=True)
        profiles = with_built_ins((mine, edited))
        assert profiles[:2] == (mine, edited), 'yours, and your changes to a built-in one, are left alone'
        assert [p.name for p in profiles[2:]] == [TRIM, LANDING, A_GRADE, A_CANOPY]
        assert settings_fingerprint(Settings(profiles=profiles)) == settings_fingerprint(Settings(profiles=(mine, edited))), \
            'switched off, they change nothing about a finished library'


class TestAFolderPerProfile:
    def settings(self, **changes):
        return Settings(output_folder='C:/cut', output_layout='by_profile', **changes)

    def test_each_profile_has_its_folder_inside_the_clips_folder(self):
        settings = self.settings()
        assert profile_root(settings, KeepProfile(name='A grade')) == Path('C:/cut/A grade')
        assert profile_root(settings, built_in_profiles()[LANDING]) == Path('C:/cut/Trimmed')
        assert profile_root(settings, KeepProfile(name='Mine', folder='D:/Day tape')) == Path('D:/Day tape')

    def test_other_layouts_are_as_they_were(self):
        assert profile_root(Settings(output_folder='C:/cut'), KeepProfile(folder='Elsewhere')) == Path('C:/cut')

    def test_a_folder_is_a_plain_name_or_a_full_path(self):
        validate_profile(KeepProfile(folder='Day tape'))
        validate_profile(KeepProfile(folder=str(Path('D:/Skydiving/Day tape').resolve())))
        with pytest.raises(ValueError, match='plain folder name'):
            validate_profile(KeepProfile(folder='nested/inside'))

    def test_an_empty_folder_reprocesses_nobody_and_a_new_one_recuts(self):
        base = Settings(output_folder='C:/out', csv_folder='C:/out/timelines', yolo_model='C:/yolo.pt')
        assert 'folder' not in json.dumps({'profiles': [settings_fingerprint(base)]})
        moved = replace(base, profiles=(KeepProfile(folder='Elsewhere'),))
        assert settings_fingerprint(moved) != settings_fingerprint(base)

    def test_a_profile_folder_may_not_hold_the_videos(self, tmp_path):
        from app.settings import validate_settings
        inputs = tmp_path / 'tape' / 'videos'
        inputs.mkdir(parents=True)
        settings = Settings(input_folder=str(inputs), output_folder=str(tmp_path / 'cut'),
                            csv_folder=str(tmp_path / 'cut' / 'timelines'), output_layout='by_profile',
                            profiles=(KeepProfile(folder=str(tmp_path / 'tape')),))
        with pytest.raises(ValueError, match='cannot contain'):
            validate_settings(settings, require_folders=True)


class TestClipNames:
    def test_named_after_the_video_and_numbered_only_when_there_are_several(self):
        assert named_clip('D:/in/GOPR0001.MP4', 'GOPR0001_a7c91e3f00112233', 'A grade', 1, 1) == 'GOPR0001 - A grade.mp4'
        assert named_clip('D:/in/GOPR0001.MP4', 'GOPR0001_a7c91e3f00112233', 'A grade', 2, 3) == 'GOPR0001 - A grade 2.mp4'
        assert named_clip('D:/in/jump.360', 'jump_a7c91e3f00112233', 'Trimmed', 1, 1) == 'jump - Trimmed.360'

    def test_the_second_video_with_the_same_name_gets_a_code_and_keeps_it(self, tmp_path):
        first, second = 'GOPR0001_aaaaaa1111111111', 'GOPR0001_bbbbbb2222222222'
        assert plain_name(tmp_path, 'D:/cardA/GOPR0001.MP4', first)
        assert not plain_name(tmp_path, 'E:/cardB/gopr0001.mp4', second), 'same name, whatever its capitals'
        assert plain_name(tmp_path, 'D:/cardA/GOPR0001.MP4', first), 'and the same answer on every later run'
        assert named_clip('E:/cardB/GOPR0001.MP4', second, 'A grade', 1, 1, plain=False) == 'GOPR0001 [bbbbbb] - A grade.mp4'


def by_profile(inputs, clips, classifier, *profiles):
    settings = make_settings(inputs, clips, phase_classifier=classifier, output_layout='by_profile')
    return replace(settings, profiles=profiles)


class TestARealCut:
    """Six seconds of colour bars with a stub model: exit at 2 s, freefall from 4 s."""

    def test_clips_land_in_each_profiles_folder_under_the_videos_own_name(self, folders, make_video, stub_classifier,
                                                                          runner):
        inputs, clips = folders
        shutil.move(make_video('GX010042.MP4'), inputs / 'GX010042.MP4')
        whole = KeepProfile(name='Trimmed', phases=frozenset({'exit', 'freefall'}), min_person_count=0,
                            min_total_area_percent=0.0, margin_before_seconds=0.0, margin_after_seconds=0.0)
        only_exit = replace(whole, name='Exit only', phases=frozenset({'exit'}), folder='Trimmed')
        elsewhere = replace(whole, name='Mine', folder=str(clips.parent / 'day tape'))
        result = process(by_profile(inputs, clips, stub_classifier(), whole, only_exit, elsewhere),
                         inputs / 'GX010042.MP4', runner)
        assert sorted(str(path.relative_to(clips.parent)) for path in clips_of(result)) == sorted([
            str(Path('clips') / 'Trimmed' / 'GX010042 - Trimmed.mp4'),
            str(Path('clips') / 'Trimmed' / 'GX010042 - Exit only.mp4'),
            str(Path('day tape') / 'GX010042 - Mine.mp4')])
        assert all(path.is_file() and path.stat().st_size > 0 for path in clips_of(result))

    def test_the_same_name_on_two_cards_never_collides(self, folders, make_video, stub_classifier, runner):
        inputs, clips = folders
        for card in ('cardA', 'cardB'):
            (inputs / card).mkdir()
            shutil.move(make_video(f'{card}.mp4'), inputs / card / 'GOPR0001.MP4')
        profile = KeepProfile(name='Trimmed', min_person_count=0, min_total_area_percent=0.0)
        settings = by_profile(inputs, clips, stub_classifier(), profile)
        first = clips_of(process(settings, inputs / 'cardA' / 'GOPR0001.MP4', runner))
        second = clips_of(process(settings, inputs / 'cardB' / 'GOPR0001.MP4', runner))
        assert first[0].name == 'GOPR0001 - Trimmed.mp4'
        assert second[0].name.startswith('GOPR0001 [') and second[0].name.endswith('] - Trimmed.mp4')
        assert first[0].is_file() and second[0].is_file()

    def test_a_recut_replaces_its_own_clips_and_leaves_a_strangers_file_alone(self, folders, make_video,
                                                                              stub_classifier, runner):
        inputs, clips = folders
        shutil.move(make_video('jump.mp4'), inputs / 'jump.mp4')
        both = KeepProfile(name='Trimmed', min_person_count=0, min_total_area_percent=0.0,
                           margin_before_seconds=0.0, margin_after_seconds=0.0)
        classifier = stub_classifier()
        first = process(by_profile(inputs, clips, classifier, both), inputs / 'jump.mp4', runner)
        assert [path.name for path in clips_of(first)] == ['jump - Trimmed.mp4']
        (clips / 'Trimmed' / 'my holiday.mp4').write_bytes(b'not ours')
        # The same profile narrowed to the exit: the clip is cut again under the same name.
        narrowed = replace(both, phases=frozenset({'exit'}))
        again = process(by_profile(inputs, clips, classifier, narrowed), inputs / 'jump.mp4', runner)
        assert [path.name for path in clips_of(again)] == ['jump - Trimmed.mp4']
        assert sorted(path.name for path in (clips / 'Trimmed').iterdir()) == ['jump - Trimmed.mp4', 'my holiday.mp4']

    def test_a_file_already_there_under_that_name_is_never_overwritten(self, folders, make_video, stub_classifier,
                                                                      runner):
        inputs, clips = folders
        shutil.move(make_video('jump.mp4'), inputs / 'jump.mp4')
        (clips / 'Trimmed').mkdir()
        (clips / 'Trimmed' / 'jump - Trimmed.mp4').write_bytes(b'somebody else put this here')
        profile = KeepProfile(name='Trimmed', min_person_count=0, min_total_area_percent=0.0)
        with pytest.raises(FileExistsError):
            process(by_profile(inputs, clips, stub_classifier(), profile), inputs / 'jump.mp4', runner)
        assert (clips / 'Trimmed' / 'jump - Trimmed.mp4').read_bytes() == b'somebody else put this here'


class TestSavedSettings:
    def test_a_settings_file_from_before_opens_on_the_full_screen(self, tmp_path):
        path = tmp_path / 'settings.json'
        save_settings(Settings(), path)
        data = json.loads(path.read_text(encoding='utf-8'))
        for name in ('mode', 'advanced_enabled'):
            data.pop(name)
        path.write_text(json.dumps(data), encoding='utf-8')
        assert load_settings(path).mode == 'advanced'

    def test_a_new_install_opens_on_the_basic_screen(self, tmp_path):
        assert load_settings(tmp_path / 'nothing.json').mode == 'basic'

    def test_the_screen_and_the_remembered_profiles_round_trip(self, tmp_path):
        path = tmp_path / 'settings.json'
        save_settings(Settings(mode='basic', advanced_enabled=('Mine', 'Other')), path)
        loaded = load_settings(path)
        assert loaded.mode == 'basic' and loaded.advanced_enabled == ('Mine', 'Other')


@pytest.fixture
def basic(tmp_path, monkeypatch):
    """A window on the basic screen, as a new install opens, with settings in a temporary file."""
    from PySide6.QtWidgets import QApplication
    from app import health as health_module
    from app import settings as settings_module
    from app.ui import main_window as window_module, theme

    for module in (health_module, window_module):
        monkeypatch.setattr(module, 'people_installed', lambda s=None: True, raising=False)
    monkeypatch.setattr(health_module, 'missing_models', lambda: [])
    monkeypatch.setattr(health_module, 'missing_tools', lambda: [])
    monkeypatch.setattr(health_module, 'missing_packages', lambda: [])
    monkeypatch.setattr(window_module.MainWindow, 'check_gpu', lambda self: None)
    path = tmp_path / 'settings.json'
    inputs, clips = tmp_path / 'input', tmp_path / 'clips'
    inputs.mkdir()
    clips.mkdir()
    monkeypatch.setattr(window_module, 'load_settings', lambda: settings_module.load_settings(path))
    monkeypatch.setattr(window_module, 'save_settings', lambda s: settings_module.save_settings(s, path))

    def build(saved=None):
        if saved is not None:
            settings_module.save_settings(saved, path)
        application = QApplication.instance() or QApplication([])
        theme.apply(application)
        built = window_module.MainWindow()
        built.people_available = True
        built.folder_edits['input_folder'].setText(str(inputs))
        built.folder_edits['output_folder'].setText(str(clips))
        built.resize(1500, 1000)
        built.show()
        built.refresh_health(cuda=True)
        application.processEvents()
        return built, application
    return build, clips


def in_use(settings):
    return [profile.name for profile in settings.profiles if profile.enabled]


class TestTheBasicScreen:
    def test_a_first_run_shows_three_choices_with_trimming_ticked(self, basic):
        build, clips = basic
        built, _application = build()
        assert built.mode == 'basic' and built.basic_panel.isVisible()
        assert not built.profile_group.isVisible() and not built.advanced.isVisible()
        settings = built.read_settings()
        assert in_use(settings) == [TRIM]
        assert settings.output_layout == 'by_profile' and settings.phases_enabled and settings.cut_enabled
        assert not settings.people_enabled, 'trimming alone never looks for people'
        assert Path(settings.csv_folder) == clips / 'timelines'
        built.close()

    def test_the_ticks_are_the_built_in_profiles(self, basic):
        build, _clips = basic
        built, _application = build()
        built.cards[A_GRADE]['tick'].setChecked(True)
        built.cards[B_GRADE]['tick'].setChecked(True)
        built.trim_landing.setChecked(True)
        built.a_canopy.setChecked(True)
        settings = built.read_settings()
        assert in_use(settings) == [TRIM, LANDING, A_GRADE, A_CANOPY, B_GRADE]
        assert settings.people_enabled, 'the grades need people counted'
        built.cards[TRIM]['tick'].setChecked(False)
        assert LANDING not in in_use(built.read_settings()), 'the landing goes with trimming'
        built.close()

    def test_the_seconds_are_written_into_the_profiles_however_many(self, basic):
        build, _clips = basic
        built, _application = build()
        built.trim_before.setValue(45.0)
        built.trim_landing.setChecked(True)
        built.landing_seconds.setValue(120.0)
        by_name = {profile.name: profile for profile in built.read_settings().profiles}
        assert by_name[TRIM].margin_before_seconds == 45.0
        assert by_name[LANDING].margin_before_seconds == by_name[LANDING].margin_after_seconds == 120.0
        assert not built.customised(TRIM), 'its own seconds are not a change to the built-in choice'
        built.close()

    def test_long_seconds_come_back_as_they_were_saved(self, basic):
        build, _clips = basic
        built, _application = build()
        built.trim_before.setValue(45.0)
        built.trim_landing.setChecked(True)
        built.landing_seconds.setValue(120.0)
        saved = built.read_settings()
        built.close()
        again, _application = build(saved)
        assert again.trim_before.value() == 45.0 and again.landing_seconds.value() == 120.0
        again.close()

    def test_a_grade_keeps_the_exit_until_it_is_unticked(self, basic):
        build, _clips = basic
        built, _application = build()
        built.cards[A_GRADE]['tick'].setChecked(True)
        built.cards[B_GRADE]['tick'].setChecked(True)
        assert built.a_exit.isChecked() and 'exit' in built.profile_named(A_GRADE).phases
        built.a_exit.setChecked(False)
        assert built.profile_named(A_GRADE).phases == frozenset({'freefall', 'break_off'})
        assert 'exit' in built.profile_named(B_GRADE).phases, 'the tick is A grade\'s alone'
        assert not built.customised(A_GRADE), 'its own tick is not a change to the built-in choice'
        saved = built.read_settings()
        built.close()
        again, _application = build(saved)
        assert not again.a_exit.isChecked()
        again.a_exit.setChecked(True)
        assert again.profile_named(A_GRADE) == replace(built_in_profiles()[A_GRADE], enabled=True)
        again.close()

    def test_nothing_ticked_does_not_start(self, basic):
        build, _clips = basic
        built, _application = build()
        built.cards[TRIM]['tick'].setChecked(False)
        built.cuda = True
        built.start_session(True)
        assert not built.active and 'Tick at least one' in built.warning.text()
        built.close()

    def test_your_own_profiles_are_switched_off_here_and_back_on_in_advanced(self, basic):
        build, _clips = basic
        mine = KeepProfile(name='Mine', min_person_count=3)
        built, _application = build(Settings(mode='advanced', profiles=(mine,)))
        assert built.mode == 'advanced' and built.profile_group.isVisible() and not built.basic_panel.isVisible()
        assert in_use(built.read_settings()) == ['Mine']
        built.set_mode('basic')
        built.cards[A_GRADE]['tick'].setChecked(True)
        settings = built.read_settings()
        assert in_use(settings) == [A_GRADE] and settings.advanced_enabled == ('Mine',)
        assert next(p for p in settings.profiles if p.name == 'Mine') == replace(mine, enabled=False), 'kept, not deleted'
        built.set_mode('advanced')
        assert in_use(built.read_settings()) == ['Mine', A_GRADE], 'and the built-in one stays ticked there too'
        built.close()

    def test_a_profile_switched_off_in_advanced_stays_off_after_a_visit_here(self, basic):
        build, _clips = basic
        built, _application = build(Settings(mode='advanced', profiles=(KeepProfile(name='Mine'),)))
        built.set_mode('basic')
        built.set_mode('advanced')
        assert 'Mine' in in_use(built.read_settings()), 'remembered across the first visit'
        built.profiles = [replace(p, enabled=False) if p.name == 'Mine' else p for p in built.profiles]
        built.set_mode('basic')
        built.set_mode('advanced')
        assert 'Mine' not in in_use(built.read_settings()), 'and not switched back on after the second'
        built.close()

    def test_a_built_in_choice_edited_in_advanced_says_so_and_can_be_put_back(self, basic):
        build, _clips = basic
        built, application = build()
        built.set_built_in(B_GRADE, min_total_area_percent=5.0)
        built.load_basic()
        application.processEvents()
        assert built.customised(B_GRADE) and built.cards[B_GRADE]['reset'].isVisible()
        assert not built.cards[A_GRADE]['reset'].isVisible()
        built.cards[B_GRADE]['reset'].click()
        assert not built.customised(B_GRADE)
        assert built.profile_named(B_GRADE).min_total_area_percent == 10.0
        built.close()

    def test_every_choice_explains_itself(self, basic):
        from app.ui.help import HelpButton
        build, _clips = basic
        built, _application = build()
        keys = {button.key for button in built.basic_panel.findChildren(HelpButton)}
        assert keys == {'basic_trim', 'basic_a', 'basic_b'}
        built.close()

    def test_the_choice_of_screen_is_remembered(self, basic):
        build, _clips = basic
        built, _application = build()
        built.set_mode('advanced')
        built.close()
        again, _application = build()
        assert again.mode == 'advanced' and again.profile_group.isVisible()
        again.close()


class TestTheAdvancedScreen:
    def test_the_built_in_profiles_are_listed_with_a_folder_each_can_change(self, basic):
        from app.ui.profile_editor import ProfileEditor
        build, _clips = basic
        built, _application = build(Settings(mode='advanced'))
        names = [built.table.item(row, 1).text() for row in range(built.table.rowCount())]
        assert names == ['Exit + Freefall', TRIM, LANDING, A_GRADE, A_CANOPY, B_GRADE]
        editor = ProfileEditor(built.profile_named(LANDING))
        assert editor.folder.text() == TRIM
        editor.folder.setText('Landings')
        assert editor.read().folder == 'Landings'
        assert built.output_layout.findData('by_profile') >= 0, 'a folder per profile is one of the ways to organise'
        built.close()
