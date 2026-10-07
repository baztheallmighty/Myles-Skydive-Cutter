"""Whether a newer Skydive Cutter has been published. No Qt, so it can be tested without a window.

This is the one thing the app asks the internet after setup: a single request for the latest release's number.
Nothing about this PC or its videos is sent beyond what any web request carries. Offline, blocked, or answered with
something unexpected, it says nothing at all: the app works the same without it.
"""
import json
import re
import urllib.request

from app import PROJECT_ROOT

REPOSITORY = 'https://github.com/baztheallmighty/Myles-Skydive-Cutter'
LATEST = 'https://api.github.com/repos/baztheallmighty/Myles-Skydive-Cutter/releases/latest'
DOWNLOAD_PAGE = REPOSITORY + '/releases/latest'


def installed_version(root=PROJECT_ROOT):
    """The version this package was built as, or '' when running from a development folder."""
    try:
        return str(json.loads((root / 'RELEASE.json').read_text(encoding='utf-8')).get('version') or '')
    except (OSError, ValueError, AttributeError):
        return ''


def numbers(version):
    """'v2.7.0' as (2, 7, 0), for comparing. Anything that is not plain numbers and dots is None."""
    match = re.fullmatch(r'v?(\d+(?:\.\d+)*)', str(version).strip())
    return tuple(int(part) for part in match.group(1).split('.')) if match else None


def is_newer(candidate, current):
    """True only when both are version numbers and the candidate is the later one."""
    theirs, ours = numbers(candidate), numbers(current)
    if theirs is None or ours is None:
        return False
    width = max(len(theirs), len(ours))
    return theirs + (0,) * (width - len(theirs)) > ours + (0,) * (width - len(ours))


def release_page(address):
    """The page to open for a release: only ever one inside the project's own repository."""
    return address if isinstance(address, str) and address.startswith(REPOSITORY + '/releases/') else DOWNLOAD_PAGE


def latest_release(timeout=6, opener=urllib.request.urlopen):
    """(version, page) of the latest published release, or None when it cannot be found out."""
    request = urllib.request.Request(LATEST, headers={'Accept': 'application/vnd.github+json',
                                                      'User-Agent': 'Skydive-Cutter'})
    try:
        with opener(request, timeout=timeout) as response:
            found = json.loads(response.read(1 << 20).decode('utf-8'))
        if found.get('draft') or found.get('prerelease') or numbers(found.get('tag_name')) is None:
            return None
        return str(found['tag_name']).strip().lstrip('v'), release_page(found.get('html_url'))
    except Exception:  # noqa: BLE001 - offline, blocked, rate-limited or changed: none of them is the person's problem
        return None


NEWER, LATEST_INSTALLED, UNKNOWN = 'newer', 'latest', 'unknown'


def check(current=None, **how):
    """(answer, version, page) for someone who asked: a newer release, already the latest, or could not find out."""
    current = installed_version() if current is None else current
    found = latest_release(**how) if current else None
    if not found:
        return UNKNOWN, '', ''
    return (NEWER, *found) if is_newer(found[0], current) else (LATEST_INSTALLED, found[0], '')


def available_update(current=None, **how):
    """(version, page) when a release newer than this install is published, else None. Never raises."""
    current = installed_version() if current is None else current
    if not current:
        return None
    found = latest_release(**how)
    return found if found and is_newer(found[0], current) else None
