"""Resident YOLO model with samples on the shared timeline grid."""
import subprocess

from app.timeline import canonical_grid

PEOPLE_SIZE = 640  # what the detector sees; the phase model uses the same view at 160


def views_for(mode, media):
    """Which sides of the camera to count people on. Only 360 footage has a back."""
    from cutter_v4.engine import has_back_view
    if not media or not has_back_view(media):
        return ['front']
    return {'front': ['front'], 'back': ['back'], 'front_back': ['front', 'back']}.get(mode, ['front'])


def view_frames(source, media, view, settings, ffmpeg):
    """Frames on the sample grid, through the same window the phase model looks through."""
    import numpy as np
    from cutter_v4.engine import video_map, view_filter
    view_chain = view_filter(media['kind'], media['width'], media['height'], view, fps=settings.sample_fps,
                             size=PEOPLE_SIZE,
                             dual_fisheye=bool(media.get('dual_fisheye'))).replace('format=rgb24', 'format=bgr24')
    command = [ffmpeg, '-hide_banner', '-nostdin', '-loglevel', 'error', '-i', str(source),
               '-map', video_map(media, view), '-an', '-sn', '-dn', '-vf', view_chain,
               '-f', 'rawvideo', '-pix_fmt', 'bgr24', 'pipe:1']
    frame_bytes = PEOPLE_SIZE * PEOPLE_SIZE * 3
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        while True:
            buffer = process.stdout.read(frame_bytes)
            if len(buffer) < frame_bytes:
                break
            yield np.frombuffer(buffer, dtype=np.uint8).reshape(PEOPLE_SIZE, PEOPLE_SIZE, 3)
    finally:
        process.stdout.close()
        error = process.stderr.read().decode('utf-8', 'replace')
        process.stderr.close()
        if process.wait() not in (0, None) and error:
            raise ValueError(f'Could not read frames for people counting: {error[-300:]}')


def merge_views(per_view):
    """One row per second: people seen in any view count, and their areas add up."""
    merged = []
    length = min(len(rows) for rows in per_view.values())
    for index in range(length):
        row = {'time_sec': next(iter(per_view.values()))[index]['time_sec'],
               'person_count': 0, 'largest_person_area_percent': 0.0, 'total_person_area_percent': 0.0}
        for view, rows in per_view.items():
            row['person_count'] += rows[index]['person_count']
            row['total_person_area_percent'] += rows[index]['total_person_area_percent']
            row['largest_person_area_percent'] = max(row['largest_person_area_percent'],
                                                     rows[index]['largest_person_area_percent'])
            row[f'person_count_{view}'] = rows[index]['person_count']
            row[f'total_person_area_percent_{view}'] = rows[index]['total_person_area_percent']
        merged.append(row)
    return merged


def detection_metrics(boxes):
    areas = [box.box_area_percent for box in boxes]
    return {'person_count': len(boxes), 'largest_person_area_percent': max(areas, default=0.0),
            'total_person_area_percent': sum(areas)}


class PeopleSampler:
    def __init__(self):
        self.model = None

    def sample(self, source, duration, settings, runner, media=None):
        """Count people in each view this run asks for, on the shared one-second grid."""
        views = views_for(settings.view_mode, media)
        if views == ['front'] and (not media or media['kind'] == 'flat'):
            return self.sample_view(source, duration, settings, runner)   # an ordinary video is read directly
        from app.ffmpeg_tools import find_executable
        ffmpeg = find_executable('ffmpeg')
        per_view = {}
        for view in views:
            runner.log(f'People: counting in the {view} view')
            per_view[view] = self.sample_view(source, duration, settings, runner, media=media,
                                              ffmpeg=ffmpeg, view=view)
        return merge_views(per_view) if len(per_view) > 1 else next(iter(per_view.values()))

    def sample_view(self, source, duration, settings, runner, media=None, ffmpeg=None, view='front'):
        import cv2
        from app.detection import detect_people, find_person_class_ids, load_yolo_model
        if self.model is None:
            from pathlib import Path
            try:
                # Ultralytics sends anonymous usage statistics by default; this app promises to stay offline.
                from ultralytics import settings as ultralytics_settings
                ultralytics_settings.update({'sync': False})
            except Exception:  # noqa: BLE001 - an older or missing Ultralytics simply has nothing to switch off
                pass
            if not Path(settings.yolo_model).is_file():
                raise FileNotFoundError(f'Local YOLO model is missing: {settings.yolo_model}')
            runner.log('Loading person detector…')
            self.model = load_yolo_model(settings.yolo_model)
            if settings.device != 'auto':
                self.model.to(settings.device)
            self.person_ids = find_person_class_ids(self.model)
            if not self.person_ids:
                raise ValueError('The selected YOLO model has no person class.')
        rows = []
        grid = canonical_grid(duration, settings.sample_fps)
        if ffmpeg:   # 360 footage: the detector looks through the same window as the phase model
            frames = view_frames(source, media, view, settings, ffmpeg)
            for index, t in enumerate(grid):
                runner.check_cancelled()
                frame = next(frames, None)
                if frame is None:
                    break
                boxes = detect_people(self.model, frame, settings.detection_confidence, self.person_ids)
                rows.append({'time_sec': t, **detection_metrics(boxes)})
                runner.report_progress('people', index + 1, len(grid))
                if index % 10 == 0 or index + 1 == len(grid):
                    runner.log(f'People {index + 1}/{len(grid)} ({100 * (index + 1) / len(grid):.0f}%)')
            while len(rows) < len(grid):   # a short read leaves the tail uncounted rather than failing the video
                rows.append({'time_sec': grid[len(rows)], 'person_count': 0, 'largest_person_area_percent': 0.0,
                             'total_person_area_percent': 0.0})
            return rows
        capture = cv2.VideoCapture(str(source))
        try:
            if not capture.isOpened():
                raise ValueError(f'Cannot open video: {source}')
            for index, t in enumerate(grid):
                runner.check_cancelled()
                capture.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
                ok, frame = capture.read()
                if not ok:
                    raise ValueError(f'Cannot decode person sample at {t:.3f}s in {source.name}.')
                boxes = detect_people(self.model, frame, settings.detection_confidence, self.person_ids)
                rows.append({'time_sec': t, **detection_metrics(boxes)})
                runner.report_progress('people', index + 1, len(grid))
                if index % 10 == 0 or index + 1 == len(grid):
                    runner.log(f'People {index + 1}/{len(grid)} ({100 * (index + 1) / len(grid):.0f}%)')
        finally:
            capture.release()
        return rows
