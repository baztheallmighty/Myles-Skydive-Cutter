"""Model-independent entry point for phase classification."""
from app.classifiers import get_classifier, validate_result


def classify(source, settings, runner):
    classifier = get_classifier(settings.phase_classifier)
    result = validate_result(classifier.predict(source, settings, runner))
    return result.segments, result.duration_sec, result.work_directory, result.agreement
