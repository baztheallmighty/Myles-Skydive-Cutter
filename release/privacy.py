"""Private strings that must never be published, and a check for them.

    python release/privacy.py        # check every file git would publish (run before every push)

Two kinds of pattern. The generic ones below (user folders, machine names, private network addresses, email
addresses) are safe to publish. Your own ones (your names, your drive letters and folder names, host names) would give
away exactly what they protect, so they live in ``release/private-patterns.txt``, which git ignores. Each line there
is ``text: <regex>``, ``binary: <regex>`` or ``both: <regex>``; a line starting with ``#`` is a comment. The package
builder and this check both refuse to run without it, so a new checkout cannot publish anything unchecked by accident.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys

RELEASE = Path(__file__).resolve().parent
ROOT = RELEASE.parent
LOCAL_PATTERNS = RELEASE / 'private-patterns.txt'
TEXT_SUFFIXES = {'.py', '.md', '.ps1', '.cmd', '.json', '.txt', '.sh', '.command', '.yml', '.yaml', '.svg', '.csv', ''}

GENERIC_TEXT = [
    r'[A-Za-z]:[\\/]+Users[\\/]+(?!Public\b|WDAGUtilityAccount\b|<|me\b)[^\\/\s"\'`]+',   # someone's user folder
    r'/Users/(?!me\b|Shared\b|<)[A-Za-z0-9._-]+',                                         # the same on a Mac
    r'DESKTOP-[A-Z0-9]{5,}',                                                              # a Windows machine name
    r'\b192\.168\.\d+\.\d+', r'\b10\.\d+\.\d+\.\d+\b', r'\b172\.(1[6-9]|2\d|3[01])\.\d+\.\d+',
    r'credential\.xml',
    r'\b[A-Za-z0-9._%+-]+@(?!(example|anthropic)\.)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',     # an email address
    r'(ghp_[A-Za-z0-9]{20,}|github' r'_pat_|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY)',  # a credential
]
# Model files are binary: short patterns occur by chance in weights, so only long ones are checked there.
GENERIC_BINARY = [r'C:[\\/]Users[\\/][^\\/]{3,}', r'DESKTOP-[A-Z0-9]{5,}', r'192\.168\.\d+\.\d+', r'credential\.xml']


def local_patterns() -> tuple[list[str], list[str]]:
    if not LOCAL_PATTERNS.is_file():
        raise SystemExit(f'{LOCAL_PATTERNS} is missing, so nothing personal could be checked. Create it (see '
                         f'release/privacy.py) before building or publishing.')
    text, binary = [], []
    for number, line in enumerate(LOCAL_PATTERNS.read_text(encoding='utf-8').splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        kind, _, pattern = line.partition(':')
        pattern = pattern.strip()
        re.compile(pattern)   # a broken pattern should stop here, not match nothing
        if kind in ('text', 'both'):
            text.append(pattern)
        if kind in ('binary', 'both'):
            binary.append(pattern)
        if kind not in ('text', 'binary', 'both'):
            raise SystemExit(f'{LOCAL_PATTERNS.name}:{number}: start the line with text:, binary: or both:')
    return text, binary


def findings(paths, root=ROOT) -> list[str]:
    """Every private match in these files, as 'path:line: context'."""
    own_text, own_binary = local_patterns()
    text_pattern = re.compile('|'.join(GENERIC_TEXT + own_text), re.IGNORECASE)
    binary_pattern = re.compile('|'.join(GENERIC_BINARY + own_binary).encode(), re.IGNORECASE)
    problems = []
    for path in paths:
        path = Path(path)
        name = path.relative_to(root).as_posix() if path.is_absolute() else path.as_posix()
        data = (path if path.is_absolute() else root / path).read_bytes()
        if path.suffix.lower() in TEXT_SUFFIXES:
            text = data.decode('utf-8', 'replace')
            for match in text_pattern.finditer(text):
                line = text.count('\n', 0, match.start()) + 1
                problems.append(f'{name}:{line}: {text[max(0, match.start() - 40):match.end() + 40]!r}')
        else:
            for match in binary_pattern.finditer(data):
                problems.append(f'{name}: {data[max(0, match.start() - 40):match.end() + 40]!r}')
    return problems


def published_files() -> list[Path]:
    """What git would publish: tracked files plus new ones not ignored."""
    listed = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT,
                            capture_output=True, check=True).stdout.decode('utf-8').split('\0')
    return [ROOT / name for name in listed if name and (ROOT / name).is_file()]


if __name__ == '__main__':
    files = published_files()
    found = findings(files)
    for problem in found[:60]:
        print(problem)
    print(f'{len(files)} files checked, {len(found)} private strings found.')
    sys.exit(1 if found else 0)
