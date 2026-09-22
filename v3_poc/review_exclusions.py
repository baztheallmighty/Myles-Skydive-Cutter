"""Desktop/web-compatible, reversible exclusions from a review run."""
import json
from datetime import datetime, timezone
from pathlib import Path

from common import write_json


def read_mapping(path):
    path = Path(path)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def exclude_video(run, source_key, rel_path):
    run = Path(run)
    exclusions_path = run / 'review_exclusions.json'
    state_path = run / 'review_state.json'
    exclusions, state = read_mapping(exclusions_path), read_mapping(state_path)
    previous = exclusions.get(source_key, {}).get('previous_review') or state.get(source_key)
    entry = {'reason': 'not_skydive', 'note': '', 'rel_path': rel_path,
             'excluded_utc': datetime.now(timezone.utc).isoformat()}
    if previous:
        entry['previous_review'] = previous
    exclusions[source_key] = entry
    # Record the exclusion first. Evaluators must honour it even if a later write fails.
    write_json(exclusions_path, exclusions)
    if source_key in state:
        del state[source_key]
        write_json(state_path, state)


def restore_video(run, source_key):
    run = Path(run)
    exclusions_path = run / 'review_exclusions.json'
    state_path = run / 'review_state.json'
    exclusions, state = read_mapping(exclusions_path), read_mapping(state_path)
    entry = exclusions.get(source_key)
    if not entry:
        return
    if entry.get('previous_review') and source_key not in state:
        state[source_key] = entry['previous_review']
        write_json(state_path, state)
    del exclusions[source_key]
    write_json(exclusions_path, exclusions)
