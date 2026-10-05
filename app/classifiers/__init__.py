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
    # True when the classifier reads a proxy the people counter can write from its own read of the source:
    # ``prepare(source, settings)`` then gives the run folder, and ``predict`` takes it back as ``prepared``.
    prepare: Callable | None = None


def _v4(source, settings, runner, prepared=None):
    from app.classifiers.v4 import classify
    return classify(source, settings, runner, prepared)


def _v4_prepare(source, settings):
    from app.classifiers.v4 import run_directory
    return run_directory(source, settings)


def _v4_revision():
    from cutter_v4 import ENGINE_REVISION
    return ENGINE_REVISION


CLASSIFIERS = {
    'standard': Classifier('standard', 'Standard (V4: video + audio + motion)', _v4_revision(), _v4, 2.0,
                           prepare=_v4_prepare),
}


def classify_phases(source, settings, runner, prepared=None):
    """Run the chosen classifier and unpack its result. The monitor needs no other classifier knowledge.

    ``prepared``: the run folder from the classifier's ``prepare``, with its proxy already written.
    """
    classifier = get_classifier(settings.phase_classifier)
    extra = {'prepared': prepared} if prepared is not None else {}
    result = validate_result(classifier.predict(source, settings, runner, **extra))
    return result.segments, result.duration_sec, result.work_directory, result.agreement


def available_classifiers():
    return tuple(CLASSIFIERS.values())


def get_classifier(identifier):
    try:
        return CLASSIFIERS[identifier]
    except (KeyError, TypeError):
        raise ValueError('The selected classifier is not installed. Choose another classifier.') from None
