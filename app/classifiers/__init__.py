"""Internal classifier registry. The UI knows only identifiers and display names."""
from dataclasses import dataclass
from typing import Callable

from app.classifiers.contract import PhaseResult, validate_result


@dataclass(frozen=True)
class Classifier:
    identifier: str
    display_name: str
    revision: str
    predict: Callable
    minimum_duration: float = 0.0


def _v4(source, settings, runner):
    from app.classifiers.v4 import classify
    return classify(source, settings, runner)


def _v4_revision():
    from cutter_v4 import ENGINE_REVISION
    return ENGINE_REVISION


CLASSIFIERS = {
    'standard': Classifier('standard', 'Standard (V4: video + audio + motion)', _v4_revision(), _v4, 2.0),
}


def classify_phases(source, settings, runner):
    """Run the chosen classifier and unpack its result. The monitor needs no other classifier knowledge."""
    result = validate_result(get_classifier(settings.phase_classifier).predict(source, settings, runner))
    return result.segments, result.duration_sec, result.work_directory, result.agreement


def available_classifiers():
    return tuple(CLASSIFIERS.values())


def get_classifier(identifier):
    try:
        return CLASSIFIERS[identifier]
    except (KeyError, TypeError):
        raise ValueError('The selected classifier is not installed. Choose another classifier.') from None
