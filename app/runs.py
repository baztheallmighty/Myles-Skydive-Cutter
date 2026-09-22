"""Reading what a classifier run left behind.

Every run writes one ``result.json`` into its own folder. Four places used to open it by hand, each with its own
idea of what a missing or damaged file means, so they read it through here instead.
"""
import json
from pathlib import Path


def result_path(run_directory):
    return Path(run_directory) / 'result.json'


def engine_result(run_directory):
    """The run's result, or None when there is nothing readable there. For callers that can carry on without it."""
    if not run_directory:
        return None
    try:
        return json.loads(result_path(run_directory).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def require_engine_result(run_directory):
    """The run's result, raising if it is missing or damaged. For the classifier, where it is the whole point."""
    return json.loads(result_path(run_directory).read_text(encoding='utf-8'))


def has_result(run_directory):
    return bool(run_directory) and result_path(run_directory).is_file()
