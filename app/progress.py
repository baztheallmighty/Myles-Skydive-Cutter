"""Pure progress calculations. Percentages describe work steps, not an ETA."""
from dataclasses import dataclass

STAGE_LABELS = {'identify': 'Checking video', 'phases': 'Identifying jump phases',
                'people': 'Counting people', 'timeline': 'Writing CSV',
                'cutting': 'Creating clips', 'complete': 'Complete'}


def video_stages(settings):
    return (['identify'] + (['phases'] if settings.phases_enabled else [])
            + (['people'] if settings.people_enabled else []) + ['timeline']
            + (['cutting'] if settings.cut_enabled else []))


def video_progress(stage, completed, total, settings):
    if stage == 'complete':
        return 100, 'Complete'
    stages = video_stages(settings)
    if stage not in stages:
        return None, STAGE_LABELS.get(stage, 'Processing')
    label = f'{STAGE_LABELS[stage]} — step {stages.index(stage) + 1}/{len(stages)}'
    if total <= 0:
        return None, label
    fraction = max(0., min(1., completed / total))
    value = min(99, int(100 * (stages.index(stage) + fraction) / len(stages)))
    return value, f'{label} ({round(100 * fraction)}%)'


@dataclass
class QueueProgress:
    total: int = 0
    finished: int = 0
    failed: int = 0
    cancelled: int = 0
    deferred: int = 0

    def enqueue(self, count):
        self.total += count

    def settle(self, status):
        self.finished += 1
        self.failed += status == 'failed'
        self.cancelled += status == 'cancelled'

    def display(self):
        value = round(100 * self.finished / self.total) if self.total else 0
        label = f'{self.finished}/{self.total} videos finished' if self.total else 'Waiting for videos'
        for count, word in [(self.failed, 'failed'), (self.cancelled, 'cancelled'), (self.deferred, 'left for next run')]:
            if count:
                label += f' · {count} {word}'
        return value, label
