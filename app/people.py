"""Resident YOLO model with samples on the shared timeline grid, taken from one read of the source.

The frames come from ffmpeg, already shrunk, at the grid's own times. When the phase model's proxy is wanted too, the
same decode writes it, so a video's picture is read once however many things look at it.
"""
import os
import subprocess
import threading
from pathlib import Path

from app.timeline import canonical_grid

NOBODY = {'person_count': 0, 'largest_person_area_percent': 0.0, 'total_person_area_percent': 0.0}


def views_for(mode, media):
    """Which sides of the camera to count people on. Only 360 footage has a back."""
    from cutter_v4.media import has_back_view
    if not media or not has_back_view(media):
        return ['front']
    return {'front': ['front'], 'back': ['back'], 'front_back': ['front', 'back']}.get(mode, ['front'])


def read_frames(command, width, height):
    """Frames from an ffmpeg command that writes raw BGR to standard output. Raises if ffmpeg reports failure.

    Stopping early (a cancelled run) stops ffmpeg too.
    """
    import numpy as np
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    complaints = []
    listener = threading.Thread(target=lambda: complaints.append(process.stderr.read()), daemon=True)
    listener.start()
    frame_bytes, finished = width * height * 3, False
    try:
        while True:
            buffer = process.stdout.read(frame_bytes)
            if len(buffer) < frame_bytes:
                break
            yield np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 3)
        finished = True
    finally:
        if not finished:
            process.kill()
        process.stdout.close()
        code = process.wait()
        listener.join(timeout=5)
        process.stderr.close()
        if finished and code:
            error = b''.join(complaints).decode('utf-8', 'replace')
            raise ValueError(f'Could not read this video: {error[-300:]}')


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


class ReadAbandoned(Exception):
    """The read was stopped because whoever wanted it no longer does."""


class PeopleSampler:
    def __init__(self):
        self.model = None
        self.give_up = None   # set to a callable that turns true when this read has become pointless

    def sample(self, source, duration, settings, runner, media=None, proxy=None):
        """Count people in each view this run asks for, on the shared grid.

        ``proxy``: also write the phase model's proxy there, from the same read of the source.
        """
        from app.ffmpeg_tools import find_executable
        from cutter_v4.media import hardware_decode, probe, refine_360_kind, resolve_view
        ffmpeg = find_executable('ffmpeg')
        if media is None:
            media = probe(Path(source), find_executable('ffprobe'))
        views = views_for(settings.view_mode, media)
        if 'back' in views:
            media = refine_360_kind(Path(source), ffmpeg, media)
        # The phases are read through the first view counted, so its read can carry the proxy.
        media, first = resolve_view(Path(source), ffmpeg, media, views[0])
        per_view = {}
        for view in views:
            if len(views) > 1:
                runner.log(f'People: counting in the {view} view')
            hardware = hardware_decode(ffmpeg, source, media, view, settings.hardware_decode)
            per_view[view] = self.sample_view(source, duration, settings, runner, media, ffmpeg, view,
                                              proxy=proxy if view == first else None, hardware=hardware)
        return merge_views(per_view) if len(per_view) > 1 else next(iter(per_view.values()))

    def load(self, settings, runner):
        from app.detection import find_person_class_ids, load_yolo_model
        if self.model is not None:
            return
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
        from app.system import people_device
        device = people_device(settings.device)
        if device:
            self.model.to(device)
        if device == 'mps' and settings.device == 'auto':
            # Apple's GPU was chosen for the person, not by them: prove the detector runs there before relying on it.
            try:
                import numpy as np
                self.model.predict(source=np.zeros((64, 64, 3), dtype=np.uint8), verbose=False)
            except Exception as exc:  # noqa: BLE001 - any failure here means "use the processor", whatever it was
                runner.log(f'The person detector does not run on the Apple GPU here ({type(exc).__name__}); '
                           'using the processor.')
                self.model.to('cpu')
        self.person_ids = find_person_class_ids(self.model)
        if not self.person_ids:
            raise ValueError('The selected YOLO model has no person class.')

    def sample_view(self, source, duration, settings, runner, media, ffmpeg, view='front', proxy=None, hardware=()):
        from app.detection import detect_people
        from cutter_v4.media import people_frame_size, read_command
        self.load(settings, runner)
        grid = canonical_grid(duration, settings.sample_fps)
        width, height = people_frame_size(media)
        temporary = Path(proxy).with_suffix('.tmp.mp4') if proxy else None
        # A hardware decode that fails part-way is done again on the processor.
        attempts = [hardware, ()] if hardware else [()]
        for number, attempt in enumerate(attempts, 1):
            rows = []
            command = read_command(ffmpeg, source, media, view, proxy=temporary, people_fps=settings.sample_fps,
                                   hardware=attempt)
            try:
                for index, frame in enumerate(read_frames(command, width, height)):
                    runner.check_cancelled()
                    if self.give_up is not None and self.give_up():
                        raise ReadAbandoned()
                    if index >= len(grid):
                        continue   # ffmpeg may round one frame past the end; the proxy still has to finish
                    boxes = detect_people(self.model, frame, settings.detection_confidence, self.person_ids)
                    rows.append({'time_sec': grid[index], **detection_metrics(boxes)})
                    runner.report_progress('people', index + 1, len(grid))
                    if index % 10 == 0 or index + 1 == len(grid):
                        runner.log(f'People {index + 1}/{len(grid)} ({100 * (index + 1) / len(grid):.0f}%)')
                break
            except BaseException as exc:   # a cancelled run included: never leave half a proxy behind
                if temporary:
                    temporary.unlink(missing_ok=True)
                if not isinstance(exc, ValueError) or number == len(attempts):
                    raise
                runner.log('The graphics card could not decode this video; reading it on the processor instead.')
        if grid and not rows:
            if temporary:
                temporary.unlink(missing_ok=True)
            raise ValueError(f'Could not read any picture from {Path(source).name}.')
        if temporary:
            os.replace(temporary, proxy)
        # The last sample can sit between the final frame and the end of the video: a 257.507 s recording is sampled
        # at 257.5, which is inside it but past every frame. It is counted from the frame before it. Anything more
        # than that missing is a short read, left uncounted rather than failing the video.
        if len(rows) == len(grid) - 1:
            rows.append({**rows[-1], 'time_sec': grid[-1]})
        while len(rows) < len(grid):
            rows.append({'time_sec': grid[len(rows)], **NOBODY})
        return rows
