"""Local executable discovery without importing the inference pipeline."""
import math
import json
import shutil
from app import PROJECT_ROOT
from app.system import tool_name


def find_executable(name):
    for directory in (PROJECT_ROOT / 'bin',):   # the installer's own copy first, then whatever is on PATH
        candidate = directory / tool_name(name)
        if candidate.is_file():
            return str(candidate)
    found = shutil.which(name)
    if not found:
        raise FileNotFoundError(f'{name} is missing. Repair the install, or put {tool_name(name)} '
                                'in the bin folder or on PATH.')
    return found


def probe_duration(source, runner):
    output = runner.run([find_executable('ffprobe'), '-v', 'error', '-show_streams',
                         '-show_format', '-of', 'json', str(source)], timeout=120, echo=False)
    data = json.loads(output)
    videos = [s for s in data.get('streams', []) if s.get('codec_type') == 'video'
              and not s.get('disposition', {}).get('attached_pic')]
    if not videos:
        raise ValueError('No video stream found.')
    value = videos[0].get('duration', data.get('format', {}).get('duration'))
    try:
        duration = float(value)
    except (TypeError, ValueError):
        duration = float(data.get('format', {}).get('duration', 0))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Cannot determine a positive video duration.')
    return duration
