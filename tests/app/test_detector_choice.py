"""Choosing the person detector: which files are offered, by what name, and that the choice is saved."""
import os
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from app.settings import Settings, available_detectors, settings_fingerprint  # noqa: E402
from test_window import window  # noqa: E402,F401 - the window fixture


def weights(folder, *names):
    for name in names:
        (folder / name).write_bytes(b'weights')
    return folder


class TestWhatIsOffered:
    def test_detectors_in_the_app_folder_smallest_first_by_plain_names(self, tmp_path):
        weights(tmp_path, 'yolo26x.pt', 'yolo11n.pt', 'yolo11m.pt')
        assert [(label, Path(path).name) for label, path in available_detectors(folder=tmp_path)] == [
            ('Standard (small and fast)', 'yolo11n.pt'), ('Medium', 'yolo11m.pt'),
            ('Largest (finds the most people)', 'yolo26x.pt')]

    def test_models_that_cannot_count_people_are_left_out(self, tmp_path):
        weights(tmp_path, 'yolo11n.pt', 'yolo11n-cls.pt', 'yolo26x-cls.pt', 'yolo11n-seg.pt', 'yolo11n-pose.pt')
        assert [Path(path).name for _label, path in available_detectors(folder=tmp_path)] == ['yolo11n.pt']

    def test_an_unknown_detector_is_offered_by_its_file_name(self, tmp_path):
        weights(tmp_path, 'yolo11n.pt', 'yolo-skydivers.pt')
        assert [label for label, _path in available_detectors(folder=tmp_path)] == [
            'Standard (small and fast)', 'yolo-skydivers.pt']

    def test_the_one_in_use_is_kept_even_if_it_lives_somewhere_else(self, tmp_path):
        app, elsewhere = tmp_path / 'app', tmp_path / 'elsewhere'
        app.mkdir()
        elsewhere.mkdir()
        weights(app, 'yolo11n.pt')
        mine = weights(elsewhere, 'my-detector.pt') / 'my-detector.pt'
        assert [label for label, _path in available_detectors(str(mine), folder=app)] == [
            'Standard (small and fast)', 'my-detector.pt']


class TestTheSetting:
    def test_another_detector_counts_people_again(self):
        base = Settings(output_folder='C:/out', csv_folder='C:/out/timelines', yolo_model='C:/app/yolo11n.pt')
        assert settings_fingerprint(replace(base, yolo_model='C:/app/yolo26x.pt')) != settings_fingerprint(base)

    def test_the_window_offers_it_and_reads_the_choice_back(self, window):  # noqa: F811
        built, _application, _path = window
        assert built.detector.count() >= 1, 'at least the standard detector that comes with the app'
        assert Path(built.read_settings().yolo_model).name == Path(built.detector.currentData()).name
        for index in range(built.detector.count()):
            built.detector.setCurrentIndex(index)
            assert built.read_settings().yolo_model == built.detector.itemData(index)

    def test_it_is_greyed_out_when_people_are_not_looked_for(self, window):  # noqa: F811
        built, _application, _path = window
        built.people_toggle.setChecked(False)
        assert not built.detector.isEnabled()
        built.people_toggle.setChecked(True)
        assert built.detector.isEnabled()
