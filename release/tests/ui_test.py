"""UI test for an installed package, run with its own runtime (developer tool, not shipped).

    <package>\\.runtime\\cu128\\python.exe -s -B release\\tests\\ui_test.py --demo DIR [--keep-demo] [--docs-screens DIR] VIDEO...

Each run (unless --keep-demo): copies the videos into DIR\\input as jump1, jump2, ... and processes them exactly as the app
does, so screenshots show neutral names. Then builds the real main window offscreen, checks each interface behaviour,
and saves screenshots into DIR\\screens. Exits non-zero on the first failed check.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
CHECKS: list[str] = []


def check(condition, message):
    if not condition:
        raise SystemExit(f'FAILED: {message}')
    CHECKS.append(message)
    print(f'  ok  {message}', flush=True)


def snapshot_path(demo: Path) -> Path:
    return demo.with_name(demo.name + '-pristine')


def restore_demo(demo: Path) -> bool:
    """Put back the freshly processed demo from the snapshot. The checks edit labels and clips, so a second run on
    the same folder would start from a reviewed video and fail for reasons that have nothing to do with the app."""
    snapshot = snapshot_path(demo)
    if not (snapshot / 'input').is_dir():
        return False
    if demo.exists():
        shutil.rmtree(demo)
    shutil.copytree(snapshot, demo)
    print(f'  restored the demo from {snapshot.name}', flush=True)
    return True


def build_demo(demo: Path, videos: list[Path]) -> None:
    from app.monitor import VideoProcessor, file_signature, ledger_entry, load_ledger, save_ledger
    from app.runtime import ProcessRunner
    from app.settings import Settings, settings_fingerprint, state_directory, validate_settings
    from v3_poc.common import key

    if demo.exists():
        shutil.rmtree(demo)
    sources = []
    for index, video in enumerate(videos, 1):
        target = demo / 'input' / f'day{1 + (index - 1) // 2}' / f'jump{index}{video.suffix.lower()}'
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(video, target)
        sources.append(target)
    settings = Settings(input_folder=str(demo / 'input'), output_folder=str(demo / 'clips'),
                        csv_folder=str(demo / 'clips' / 'timelines'))
    validate_settings(settings, require_folders=True)
    state = state_directory(settings)
    state.mkdir(parents=True, exist_ok=True)
    ledger = load_ledger(state / 'ledger.json')
    processor = VideoProcessor(settings, ProcessRunner(log=lambda message: None))
    for source in sources:
        began = time.monotonic()
        signature = file_signature(source)
        result = processor.process(source, signature, None)
        ledger['entries'][key(source)] = ledger_entry(signature, settings_fingerprint(settings), 'success', **result)
        save_ledger(state / 'ledger.json', ledger)
        print(f'  processed {source.name} in {time.monotonic() - began:.1f}s', flush=True)
    snapshot = snapshot_path(demo)
    if snapshot.exists():
        shutil.rmtree(snapshot)
    shutil.copytree(demo, snapshot)
    print(f'  snapshot for reruns: {snapshot}', flush=True)


def blur(image, rect):
    """Heavily blur one region of a screenshot (footage of people must not appear in public docs)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPainter
    region = image.copy(rect)
    small = region.scaled(max(1, rect.width() // 28), max(1, rect.height() // 28), Qt.AspectRatioMode.IgnoreAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
    smooth = small.scaled(rect.width(), rect.height(), Qt.AspectRatioMode.IgnoreAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
    painter = QPainter(image)
    painter.drawImage(rect.topLeft(), smooth)
    painter.end()


def docs_screenshots(application, window, labeller, folder):
    """Screenshots for the public docs: neutral folder names, an empty log, blurred video and thumbnails."""
    from PySide6.QtCore import QRect
    folder.mkdir(parents=True, exist_ok=True)
    shown = {'input_folder': r'D:\Skydiving\Boogie 2026', 'output_folder': r'D:\Skydiving\Clips'}
    real = {name: edit.text() for name, edit in window.folder_edits.items()}
    window.tabs.setCurrentIndex(0)
    settle(application)
    for name, text in shown.items():
        window.folder_edits[name].setText(text)
    window.log.clear()
    window.status.setText('Ready. Process videos handles the videos in the input folder; tick "Keep watching" to carry on '
                          'with new ones as they arrive.')
    settle(application)
    image = window.grab().toImage()
    table = window.results.table
    for row in range(table.rowCount()):
        if table.item(row, 0).icon().isNull():
            continue  # no thumbnail, nothing to hide (and the file name must stay readable)
        cell = table.visualItemRect(table.item(row, 0))
        top_left = table.viewport().mapTo(window, cell.topLeft())
        blur(image, QRect(top_left.x(), top_left.y(), 104, cell.height()))
    image.save(str(folder / 'process-tab.png'))
    from app.ui import main_window as window_module
    from app import health as health_module
    real_people = window_module.people_installed
    window_module.people_installed = health_module.people_installed = lambda settings=None: False
    window.people_available = False
    window.refresh_health(cuda=True)
    settle(application)
    window.grab().save(str(folder / 'missing-people.png'))
    window_module.people_installed = health_module.people_installed = real_people
    window.people_available = True
    window.people_toggle.setChecked(True)
    window.refresh_health(cuda=True)
    for section in window.sections.values():
        section.set_open(False)
    settle(application)
    for name, text in real.items():
        window.folder_edits[name].setText(text)
    window.tabs.setCurrentIndex(1)
    labeller.show_video(next(v for v in labeller.videos if v.name == 'jump2.mp4'))
    settle(application, 1.5)
    labeller.seek_absolute_milliseconds(60_000)
    labeller.update_comparison_position(60_000)
    settle(application, 1.5)
    image = window.grab().toImage()
    view = labeller.video_view
    top_left = view.mapTo(window, view.rect().topLeft())
    blur(image, QRect(top_left.x(), top_left.y(), view.width(), view.height()))
    image.save(str(folder / 'review-tab.png'))
    print(f'  docs screenshots in {folder}', flush=True)


def gallery(application, window, labeller, folder, demo):
    """Every menu, dropdown, dialog and state of the interface, captured in context for a visual check."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPainter
    from app.ui.profile_editor import ProfileEditor
    folder.mkdir(parents=True, exist_ok=True)
    shots = []

    def save(name, caption, image=None):
        (image or window.grab()).save(str(folder / f'{len(shots) + 1:02d}_{name}.png'))
        shots.append((f'{len(shots) + 1:02d}_{name}.png', caption))

    def with_popup(popup):
        """The window with a popup (menu or dropdown list) drawn where it opened."""
        settle(application, .5)
        image = window.grab()
        painter = QPainter(image)
        painter.drawPixmap(window.mapFromGlobal(popup.mapToGlobal(QPoint(0, 0))), popup.grab())
        painter.end()
        return image

    def dropdown(combo, name, caption):
        """The window with the combo's list drawn just below the combo, where Qt opens it on screen."""
        combo.showPopup()
        settle(application, .5)
        popup = combo.view().window()
        image = window.grab()
        painter = QPainter(image)
        painter.drawPixmap(combo.mapTo(window, QPoint(0, combo.height())), popup.grab())
        painter.end()
        save(name, caption, image)
        combo.hidePopup()

    window.tabs.setCurrentIndex(0)
    window.advanced_toggle.setChecked(True)
    for section in window.sections.values():
        section.set_open(False)
    settle(application)
    save('process', 'Process tab as it opens: settings on the left, results on the right, folded advanced sections.')
    for section in window.sections.values():
        section.set_open(True)
    settle(application)
    save('process_advanced', 'Every advanced section open: Output, Processing, People.')
    dropdown(window.output_mode, 'dropdown_create', 'Advanced > Output > Create.')
    dropdown(window.output_layout, 'dropdown_clip_folders', 'Advanced > Output > Clip folders.')
    dropdown(window.device, 'dropdown_process_on', 'Advanced > Processing > Process on.')
    window.csv_elsewhere.setChecked(True)
    window.folder_edits['csv_folder'].setText(str(demo / 'csv elsewhere'))
    settle(application)
    save('advanced_csv_elsewhere', 'Timeline CSVs saved somewhere else: the folder box becomes active.')
    window.output_mode.setCurrentIndex(1)
    settle(application)
    save('advanced_csv_only', 'CSV only: the Clips folder and "in the Clips folder" are disabled; a CSV folder is required.')
    window.output_mode.setCurrentIndex(0)
    window.csv_in_clips.setChecked(True)
    window.folder_edits['csv_folder'].clear()
    from app.ui import main_window as window_module
    from app import health as health_module
    real_people = window_module.people_installed
    window_module.people_installed = health_module.people_installed = lambda settings=None: False
    window.people_available = False
    window.refresh_health(cuda=True)
    settle(application)
    save('missing_people', 'People detection missing: red banner, red section, Process videos held.')
    window_module.people_installed = health_module.people_installed = real_people
    window.people_available = True
    window.people_toggle.setChecked(True)
    window.refresh_health(cuda=True)
    for section in window.sections.values():
        section.set_open(False)
    settle(application)
    window.fill_presets()
    window.preset_menu.popup(window.preset_button.mapToGlobal(QPoint(0, window.preset_button.height())))
    save('menu_presets', 'Keep profiles > Add preset.', with_popup(window.preset_menu))
    window.preset_menu.hide()
    editor = ProfileEditor(window.profiles[0], True, window.people_available, window)
    editor.show()
    settle(application)
    save('dialog_profile_editor', 'Keep profiles > Edit: the profile editor.', editor.grab())
    editor.reject()
    dropdown(window.results.filter, 'dropdown_results_filter', 'Results > Show.')
    window.results.table.selectRow(0)
    settle(application)
    save('results_selected', 'Results with a video selected: Open in Review, Show clips, Open timeline CSV, Process again.')

    window.tabs.setCurrentIndex(1)
    labeller.show_video(next(v for v in labeller.videos if v.name == 'jump2.mp4'))
    settle(application, 1.5)
    labeller.seek_absolute_milliseconds(45_000)
    labeller.update_comparison_position(45_000)
    settle(application, 1.0)
    save('review', 'Review tab: your labels above every track, on one time axis.')
    labeller.extra_tracks.setChecked(False)
    settle(application)
    save('review_collapsed', 'Review tab with "Show all predictions and sensors" off: Final and Clips cut only.')
    labeller.extra_tracks.setChecked(True)
    labeller.view.zoom(.3, 45)
    settle(application)
    save('review_zoomed', 'Review tab zoomed in (Ctrl + wheel, +, or =): every row zooms together.')
    labeller.view_fit()
    clip = (labeller.comparison.result.get('clips') or [None])[0]
    if clip:
        menu = labeller.comparison.build_clip_menu(clip)
        x = labeller.comparison.x_of((clip['start_sec'] + clip['end_sec']) / 2)
        top = next(t for t in range(labeller.comparison.height()) if labeller.comparison.row_at(t)[0] == 'clips')
        menu.popup(labeller.comparison.mapToGlobal(QPoint(round(x), top + 10)))
        save('menu_clip', 'Right-click a clip in Clips cut.', with_popup(menu))
        menu.hide()
    window.recut.setChecked(False)       # screenshots only: no re-cut runs while capturing
    labeller.toggle_exclusion()          # not skydiving ...
    settle(application, 1.0)
    labeller.show_video(next(v for v in labeller.videos if v.name == 'jump2.mp4'))
    settle(application, 1.0)
    save('review_not_skydiving', 'A video marked Not skydiving (the button becomes Restore video).')
    labeller.toggle_exclusion()          # ... and restored
    settle(application, 1.0)
    window.recut.setChecked(True)
    empty = demo / 'empty clips'
    empty.mkdir(exist_ok=True)
    real = window.folder_edits['output_folder'].text()
    window.tabs.setCurrentIndex(0)
    window.folder_edits['output_folder'].setText(str(empty))
    window.refresh_results()
    window.tabs.setCurrentIndex(1)
    settle(application)
    save('review_nothing_yet', 'Review tab for a Clips folder with nothing processed yet.')
    window.tabs.setCurrentIndex(0)
    settle(application)
    save('process_nothing_yet', 'Process tab for a new Clips folder: the Results list says so.')
    window.folder_edits['output_folder'].setText(real)
    window.refresh_results()
    (folder / 'captions.json').write_text(json.dumps(shots, indent=1), encoding='utf-8')
    print(f'  gallery: {len(shots)} screenshots in {folder}', flush=True)


def settle(application, seconds=.6):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        application.processEvents()
        time.sleep(.03)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo', type=Path, required=True)
    parser.add_argument('--keep-demo', action='store_true', help='reuse the demo data (checks assume a fresh one)')
    parser.add_argument('--docs-screens', type=Path, help='also write the public docs screenshots here')
    parser.add_argument('--gallery', type=Path, help='also capture every menu, dropdown and dialog here')
    parser.add_argument('videos', nargs='*', type=Path)
    args = parser.parse_args()
    demo = args.demo.resolve()
    if not args.keep_demo or not (demo / 'clips' / '_state' / 'ledger.json').is_file():
        print('building demo data', flush=True)
        build_demo(demo, args.videos)
    elif restore_demo(demo):
        pass   # reused the snapshot, so --keep-demo starts from the same state a fresh build would
    screens = demo / 'screens'
    screens.mkdir(exist_ok=True)

    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent
    from PySide6.QtWidgets import QApplication

    from app.settings import Settings, save_settings
    from app.ui import theme
    from app.ui.main_window import MainWindow

    # Start from known settings: an earlier run (or the app itself) must not decide what this run checks.
    save_settings(Settings(input_folder=str(demo / 'input'), output_folder=str(demo / 'clips'),
                           csv_folder=str(demo / 'clips' / 'timelines')))
    application = QApplication([])
    theme.apply(application)
    window = MainWindow()
    for name, value in (('input_folder', demo / 'input'), ('output_folder', demo / 'clips'), ('csv_folder', '')):
        window.folder_edits[name].setText(str(value))
    window.resize(1500, 1000)
    window.show()
    settle(application)

    print('round 1: one window, one look', flush=True)
    check([window.tabs.tabText(i) for i in range(window.tabs.count())] == ['Process', 'Review'], 'two tabs: Process and Review')
    check(window.process_button.text() == 'Process videos' and window.process_button.objectName() == 'primary',
          'one primary Process videos button')
    check(window.keep_watching.text() == 'Keep watching for new videos', 'keep-watching tick box')
    check(all(not section.body.isVisible() for section in window.sections.values()),
          'advanced sections start folded')
    check(window.splitter.orientation() == Qt.Orientation.Horizontal and window.splitter.widget(1) is window.results,
          'two columns: settings on the left, results on the right')
    check(window.splitter.widget(0) is window.scroll and window.controls.isAncestorOf(window.advanced),
          'advanced settings live in the settings column, which scrolls on its own')
    settings = window.read_settings()
    check(Path(settings.csv_folder) == demo / 'clips' / 'timelines', 'CSV folder defaults to Clips/timelines')
    window.grab().save(str(screens / 'process_tab.png'))
    for key in ('output', 'processing', 'people'):
        window.sections[key].set_open(True)
    settle(application)
    check(all(section.body.isVisible() for section in window.sections.values()), 'each advanced section opens')
    check(window.device.count() == 3 and window.device.currentData() == 'auto', 'processing device choice, automatic by default')
    check(window.view_mode.count() == 3 and window.view_mode.currentData() == 'front',
          '360 videos are processed front view first')
    check(window.read_settings().open_sections == ('output', 'processing', 'people'), 'open sections are remembered')
    window.advanced_toggle.setChecked(False)
    check(window.advanced.isHidden(), 'the whole advanced box folds away')
    window.advanced_toggle.setChecked(True)
    window.csv_elsewhere.setChecked(True)
    window.folder_edits['csv_folder'].setText(str(demo / 'elsewhere'))
    check(Path(window.read_settings().csv_folder) == demo / 'elsewhere', 'timeline CSVs can go somewhere else')
    window.csv_in_clips.setChecked(True)
    check(not window.folder_edits['csv_folder'].isEnabled()
          and Path(window.read_settings().csv_folder) == demo / 'clips' / 'timelines', 'or back into the Clips folder')
    window.output_mode.setCurrentIndex(1)
    check(window.csv_elsewhere.isChecked() and not window.csv_in_clips.isEnabled(), 'CSV-only mode needs its own CSV folder')
    window.output_mode.setCurrentIndex(0)
    window.csv_in_clips.setChecked(True)
    window.folder_edits['csv_folder'].clear()

    print('round 1b: missing pieces are obvious', flush=True)
    from app.ui import main_window as window_module
    from app import health as health_module
    real_people = window_module.people_installed
    window_module.people_installed = health_module.people_installed = lambda settings=None: False
    window.people_available = False
    window.refresh_health(cuda=True)
    settle(application)
    check(window.health_banner.isVisible() and 'not installed' in window.health_banner.text(),
          'a missing person detector is called out in the banner')
    check(window.sections['people'].objectName() == 'sectionDanger' and window.sections['people'].body.isVisible(),
          'the People section turns red and opens itself')
    check(not window.process_button.isEnabled(), 'processing is held while something needed is missing')
    check(window.fix_button.isVisible(), 'the banner offers to install it')
    window.grab().save(str(screens / 'process_tab_missing.png'))
    window_module.people_installed = health_module.people_installed = real_people
    window.people_available = True
    window.people_toggle.setChecked(True)
    window.refresh_health(cuda=False)
    settle(application)
    check(window.process_button.isEnabled() and window.sections['people'].objectName() == 'section',
          'installing it clears the red state')
    check(window.health_banner.isVisible() and 'NVIDIA' in window.health_banner.text()
          and window.health_banner.objectName() == 'bannerWarning', 'no GPU is amber, and only warns')
    window.refresh_health(cuda=True)
    settle(application)
    check(not window.health_banner.isVisible(), 'nothing is said when nothing is wrong')
    window.grab().save(str(screens / 'process_tab_advanced.png'))
    window.advanced_toggle.setChecked(False)

    dropped = demo / 'dropped'
    dropped.mkdir(exist_ok=True)

    def drop_on(widget):
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(str(dropped))])
        centre = widget.mapTo(window, widget.rect().center())
        event = QDropEvent(QPointF(centre), Qt.DropAction.CopyAction, data, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        window.dropEvent(event)

    window.scroll.verticalScrollBar().setValue(0)  # drops land on what you can see
    settle(application)
    before = {n: e.text() for n, e in window.folder_edits.items()}
    drop_on(window.folder_edits['output_folder'])
    check(Path(window.folder_edits['output_folder'].text()) == dropped, 'folder dropped on Clips sets Clips')
    drop_on(window.status)
    check(Path(window.folder_edits['input_folder'].text()) == dropped, 'folder dropped elsewhere sets the input folder')
    for name, value in before.items():
        window.folder_edits[name].setText(value)

    window.tabs.setCurrentIndex(1)
    settle(application, 1.5)
    labeller = window.review_tab.window
    check(labeller is not None, 'Review tab opens the labeller for the Clips folder')
    check(len(labeller.videos) == len(list((demo / 'input').rglob('jump*'))), 'Review tab lists every processed video')
    check(all(s.isEnabled() for s in labeller.labeller_shortcuts), 'labeller keys active on the Review tab')
    check(labeller.menuBar().isHidden(), 'no separate window menu inside the tab')
    window.grab().save(str(screens / 'review_tab.png'))
    window.tabs.setCurrentIndex(0)
    settle(application)
    check(not any(s.isEnabled() for s in labeller.labeller_shortcuts), 'labeller keys off on the Process tab')
    window.tabs.setCurrentIndex(1)
    settle(application)
    last = labeller.videos[-1]
    check(window.review_tab.show_video(last) and labeller.current_video_path() == last, 'jump to a video by path')
    spherical = [v for v in labeller.videos if v.suffix.casefold() == '.360']
    if spherical:
        from v3_poc.common import key as video_key
        result = labeller.results[video_key(spherical[0])]
        media = result.get('media') or {}
        check(media.get('kind') in ('max_dual', 'equirect'), '360 video recognised as 360, not flat')
        check(media.get('view') == 'front', 'phases come from the front view by default')
        clips = result.get('clips') or []
        check(all(Path(c['clip_path']).suffix.casefold() == '.360' for c in clips),
              'a clip of a 360 video stays a 360 file')
    tracks = labeller.comparison
    check(any(name == 'people' for name, _title in tracks.ROWS), 'the review has a people row')
    counted = [r for r in labeller.results.values() if (r.get('people') or {}).get('counted')]
    check(counted and all(len(r['people']['t']) == len(r['people']['matched']) for r in counted),
          'people counts and matches line up per second')
    check(any((r['people'].get('requirement') or {}).get('min_area') for r in counted),
          'the people row knows the filter your profiles ask for')
    window.review_tab.mark_stale()
    window.review_tab.refresh(window.read_settings())
    check(labeller.current_video_path() == last, 'refresh keeps the video being reviewed')

    print('round 2: the review loop', flush=True)
    from PySide6.QtCore import QPoint
    from cutter_v4.review_ui import checks_from
    labeller.show_video(labeller.videos[0])
    settle(application, 1.0)
    tracks, timeline = labeller.comparison, labeller.segment_timeline

    def aligned(seconds):
        a = tracks.mapTo(window, QPoint(round(tracks.x_of(seconds)), 5)).x()
        b = timeline.mapTo(window, QPoint(round(timeline.x_for_ms(seconds * 1000)), 5)).x()
        return abs(a - b) <= 1, a, b

    check(all(aligned(t)[0] for t in (0, 10, 30, 60)), 'your labels line up with every track (same pixel for the same second)')
    scroll = labeller.centralWidget()
    check(not scroll.horizontalScrollBar().isVisible(), 'labeller fits the window without sideways scrolling')
    check(labeller.phase_buttons['freefall'].height() <= 28, 'phase buttons are compact chips')
    check(tracks.row_height('trace') == 48, 'taller motion row with g gridlines')
    labeller.view.zoom(.4, 30)
    settle(application)
    check(labeller.view.zoomed() and 'Showing' in labeller.zoom_label.text(), 'zoom in shows a time range')
    check(all(aligned(t)[0] for t in (22, 30, 38)), 'rows stay aligned when zoomed')
    window.grab().save(str(screens / 'review_zoomed.png'))
    labeller.view_fit()
    check(not labeller.view.zoomed(), 'fit shows the whole video again')
    check(labeller.overlay_text.font().pointSize() == 10 and labeller.overlay_rect.rect().height() < 40,
          'overlay is one small line')
    labeller.toggle_overlay()
    check(not labeller.overlay_text.isVisible(), 'O hides the overlay')
    labeller.toggle_overlay()
    result = labeller.results[next(iter(k for k in labeller.results if k.endswith('jump1.mp4')))]
    expected = checks_from(result['agreement'])
    check(labeller.checks == expected and len(expected) > 0, f'checks found from the agreement strip ({len(expected)})')
    labeller.next_check()
    settle(application)
    check(labeller.check_label.text().startswith('Check 1 of'), 'Check > jumps to the first check')
    item_texts = [labeller.video_list.item(i).text() for i in range(labeller.video_list.count())]
    check(any('to check' in text for text in item_texts), 'video list shows how many checks each video has')
    clip = (result.get('clips') or [None])[0]
    if clip:
        x = tracks.x_of((clip['start_sec'] + clip['end_sec']) / 2)
        name_top = next(top for top in range(0, tracks.height()) if tracks.row_at(top)[0] == 'clips')
        found = tracks.clip_at(x, name_top + 8)
        check(found is not None and found['clip_path'] == clip['clip_path'], 'clips row finds the clip under the mouse')
        labeller.play_clip(clip)
        check(labeller.clip_stop_ms == round(clip['end_sec'] * 1000), 'playing a clip stops at its end')
        labeller.player.pause()
        labeller.clip_stop_ms = None
    labeller.show_video(labeller.videos[0])
    settle(application, 1.0)
    window.grab().save(str(screens / 'review_tab.png'))

    print('round 3: results and feedback', flush=True)
    import csv as csv_module
    from app.monitor import load_ledger
    from v3_poc.common import key as path_key

    def wait_until(condition, timeout=240):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            application.processEvents()
            if condition():
                return True
            time.sleep(.05)
        return False

    def entry_for(name):
        ledger = load_ledger(demo / 'clips' / '_state' / 'ledger.json')['entries']
        return next(v for k, v in ledger.items() if k.endswith(name))

    def clip_spans(name):
        spans = []
        for manifest in entry_for(name).get('manifests') or []:
            with open(manifest, encoding='utf-8', newline='') as handle:
                spans += [(float(r['start_sec']), float(r['end_sec'])) for r in csv_module.DictReader(handle)]
        return spans

    window.tabs.setCurrentIndex(0)
    settle(application)
    panel = window.results
    demo_videos = len(list((demo / 'input').rglob('jump*')))
    check(len(panel.rows) == demo_videos and all(r['status'] == 'Done' for r in panel.rows),
          'results list shows every processed video')
    with_clips = [r for r in panel.rows if r['clips']]
    check(with_clips and all(r['thumbnail'] and Path(r['thumbnail']).is_file() for r in with_clips),
          'each video with clips has a thumbnail')
    panel.filter.setCurrentIndex(1)
    check(all(r['checks'] or r['status'] != 'Done' for r in panel.visible_rows()), '"Needs a look" filter keeps only videos to check')
    panel.filter.setCurrentIndex(0)
    window.grab().save(str(screens / 'process_results.png'))
    jump1_row = next(i for i, r in enumerate(panel.visible_rows()) if r['name'].endswith('jump1.mp4'))
    panel.emit_review(jump1_row)
    settle(application, 1.0)
    check(window.tabs.currentIndex() == 1 and labeller.current_video_path().name == 'jump1.mp4',
          'double-clicking a result opens that video in Review')

    # Re-cut now: lengthen freefall by 3 s in your labels, mark reviewed, and the clip follows straight away.
    before = clip_spans('jump1.mp4')
    mine = sorted(labeller.sorted_current_video_segment_indexes(), key=lambda i: labeller.segments[i].start_sec)
    freefall = next(i for i in mine if labeller.segments[i].phase == 'freefall')
    following = mine[mine.index(freefall) + 1]
    labeller.segments[freefall].end_sec += 3.0
    labeller.segments[following].start_sec += 3.0
    labeller.write_csv()
    labeller.mark_reviewed()
    check(wait_until(lambda: not window.active and entry_for('jump1.mp4').get('labels') == 'reviewed'),
          'marking reviewed re-cuts the video at once')
    after = clip_spans('jump1.mp4')
    check(abs((after[-1][1] - before[-1][1]) - 3.0) < 1.01, f'the clip follows the correction ({before[-1]} -> {after[-1]})')
    check(any('Your labels' in r['labels'] and r['name'].endswith('jump1.mp4') for r in window.results.rows),
          'results list shows the video is cut from your labels')

    # Not skydiving, then restore: clips go, then come back without running the model again.
    labeller.show_video(next(v for v in labeller.videos if v.name == 'jump2.mp4'))
    settle(application)
    labeller.toggle_exclusion()
    check(wait_until(lambda: not window.active and entry_for('jump2.mp4').get('labels') == 'excluded')
          and clip_spans('jump2.mp4') == [], '"Not skydiving" removes the clips at once')
    labeller.show_video(next(v for v in labeller.videos if v.name == 'jump2.mp4'))
    settle(application)
    window.log.clear()
    labeller.toggle_exclusion()
    check(wait_until(lambda: not window.active and entry_for('jump2.mp4').get('labels') == 'model')
          and clip_spans('jump2.mp4'), 'restoring brings the clips back')
    check('Reusing this video' in window.log.toPlainText(), 'restoring reuses the stored phases (no model run)')

    # Process again: forget jump3, run a batch; the model runs, and the time estimate learns this PC's speed.
    window.tabs.setCurrentIndex(0)
    settle(application)
    jump3 = next(r['key'] for r in window.results.rows if r['name'].endswith('jump3.avi'))
    window.process_again(jump3)
    check(len(window.results.rows) == demo_videos - 1, '"Process this video again" forgets it')
    (PROJECT := Path(__import__('app').PROJECT_ROOT))
    (PROJECT / 'app' / 'speed.json').unlink(missing_ok=True)
    window.speed.rate = None
    window.start_session(True)
    check(wait_until(lambda: not window.active and len(window.results.rows) == demo_videos),
          'processing again restores the result')
    check(window.speed.rate is not None and (PROJECT / 'app' / 'speed.json').is_file(), 'processing speed is learned for estimates')
    from app.eta import describe
    check(describe(window.speed.remaining_seconds([120.0])) .startswith(('about', 'under')), 'estimate text for queued videos')

    print('round 4: profile presets', flush=True)
    window.fill_presets()
    names = [a.text().split('  (')[0] for a in window.preset_menu.actions()]
    check({'Whole skydive', 'Exit only', 'Canopy flight', 'Landing'} <= set(names), f'preset menu: {", ".join(names)}')
    opened = []
    window.show_editor = lambda profile, index=None: opened.append(profile)
    window.add_preset(next(p for p in __import__('app.settings', fromlist=['x']).profile_presets() if p.name == 'Landing'))
    check(opened and opened[0].phases == frozenset({'landing', 'landed'}) and opened[0].margin_after_seconds == 5.0,
          'a preset opens in the editor, ready to adjust')
    window.grab().save(str(screens / 'process_final.png'))

    if args.docs_screens:
        docs_screenshots(application, window, labeller, args.docs_screens)
    if args.gallery:
        gallery(application, window, labeller, args.gallery, demo)

    window.hide()  # not close(): closing would save these test folders into the app's settings
    report = {'checks': CHECKS, 'screens': sorted(str(p) for p in screens.glob('*.png'))}
    (demo / 'ui_report.json').write_text(json.dumps(report, indent=1), encoding='utf-8')
    print(f'\nPASSED {len(CHECKS)} checks; screenshots in {screens}', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
