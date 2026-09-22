"""Adapter for the V4 engine (cutter_v4.engine). Engine details stay in cutter_v4; this only runs and reads it."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from uuid import uuid4

from app.classifiers.contract import PhaseResult
from app.ffmpeg_tools import find_executable
from app.runs import require_engine_result
from app.runtime import Cancelled
from app.settings import state_directory
from app.spans import slugify


def decoded_seconds(line):
    """How far the engine has decoded, read from its own progress line."""
    match = re.search(r': (\d+(?:\.\d+)?)s decoded, \d+ windows$', line)
    return float(match.group(1)) if match else None


def engine_argv(source, run_directory, settings):
    return [sys.executable, '-s', '-u', '-B', '-m', 'cutter_v4.engine', '--source', str(Path(source).resolve()),
            '--out-dir', str(run_directory), '--device', settings.device, '--batch-size', str(settings.batch_size),
            '--ffmpeg', find_executable('ffmpeg'), '--ffprobe', find_executable('ffprobe'),
            # Phases always come from one view; 'front_back' only widens the people count.
            '--view', 'back' if settings.view_mode == 'back' else 'front']


def read_result(run_directory):
    return require_engine_result(run_directory)


def classify(source, settings, runner):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    directory = state_directory(settings) / 'classifier-runs' / f'{slugify(Path(source).stem)}_{stamp}_{uuid4().hex[:8]}'
    directory.mkdir(parents=True, exist_ok=False)
    try:
        def on_output(line):
            seconds = decoded_seconds(line)
            if seconds is not None and runner.video_duration > 0:
                runner.report_progress('phases', min(seconds, runner.video_duration), runner.video_duration)
            elif line.startswith(('audio:', 'motion:')):
                runner.log(line[:1].upper() + line[1:].replace(':', ' -', 1))
        output = runner.run(engine_argv(source, directory, settings), echo=False, on_output=on_output)
        (directory / 'engine.log').write_text(output, encoding='utf-8')
        result = read_result(directory)
    except Cancelled:
        raise
    except Exception as exc:  # noqa: BLE001 - whatever the engine hit, the user gets one message and a log
        (directory / 'engine.log').write_text(str(exc), encoding='utf-8')
        raise RuntimeError('Could not classify this video. Check that it plays correctly and try again. '
                           f'Diagnostic log: {directory / "engine.log"}') from None
    for flag in result.get('review_flags', []):
        runner.log(flag)
    runner.log('Jump phases classified.')
    return PhaseResult(result['tracks']['final'], float(result['duration_sec']), directory, result.get('agreement'))
