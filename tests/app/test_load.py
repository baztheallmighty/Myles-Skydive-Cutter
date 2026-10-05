"""Whether the machine has room for another video: the decisions behind "Videos at once: Automatic"."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.load import Machine, Pacer, Reading, SETTLE_SECONDS, may_start, most_at_once  # noqa: E402

ROOMY = Reading(processor=30.0, memory_free_gb=20.0, graphics=20.0, graphics_memory_free_gb=10.0)


class TestTheDecision:
    def test_the_first_video_always_starts(self):
        assert may_start(0, Reading())[0], 'even with nothing measured'

    def test_room_everywhere_starts_another(self):
        assert may_start(1, ROOMY, limit=4)[0]

    def test_each_thing_that_is_full_says_no_and_why(self):
        for change, word in (({'processor': 95.0}, 'processor'), ({'memory_free_gb': 1.0}, 'memory'),
                             ({'graphics': 99.0}, 'graphics card'), ({'graphics_memory_free_gb': 1.0}, 'graphics memory')):
            reading = Reading(**{**ROOMY.__dict__, **change})
            answer, why = may_start(1, reading, limit=4)
            assert not answer and word in why, change

    def test_never_more_than_the_machine_is_given(self):
        assert not may_start(2, ROOMY, limit=2)[0]
        assert most_at_once(cores=2) == 1 and most_at_once(cores=8) == 2 and most_at_once(cores=16) == 4 and most_at_once(cores=64) == 10

    def test_no_processor_reading_yet_waits(self):
        assert not may_start(1, Reading(memory_free_gb=20.0), limit=4)[0]

    def test_a_graphics_card_that_cannot_be_measured_allows_two_at_most(self):
        blind = Reading(processor=30.0, memory_free_gb=20.0)
        assert may_start(1, blind, limit=4)[0]
        assert not may_start(2, blind, limit=4)[0]

    def test_on_the_processor_the_graphics_card_does_not_matter(self):
        busy_card = Reading(processor=30.0, memory_free_gb=20.0, graphics=99.0, graphics_memory_free_gb=0.5)
        assert may_start(1, busy_card, limit=4, graphics_wanted=False)[0]


class FakeMachine:
    def __init__(self, reading):
        self.reading = reading

    def read(self):
        return self.reading


class TestThePacer:
    def test_a_new_video_is_given_time_to_show_its_load(self):
        now = [100.0]
        pacer = Pacer(FakeMachine(ROOMY), limit=4, clock=lambda: now[0])
        assert pacer.may_start(1)
        pacer.started()
        assert not pacer.may_start(2) and 'still getting going' in pacer.reason
        now[0] += SETTLE_SECONDS + 1
        assert pacer.may_start(2)

    def test_it_follows_the_machine(self):
        machine = FakeMachine(ROOMY)
        pacer = Pacer(machine, limit=4, clock=lambda: 0.0)
        assert pacer.may_start(1)
        machine.reading = Reading(**{**ROOMY.__dict__, 'processor': 97.0})
        assert not pacer.may_start(1) and '97%' in pacer.reason


class TestThisMachine:
    def test_the_real_readings_are_sane(self):
        """Whatever this machine can report is a plausible number; what it cannot is None, never a crash."""
        machine = Machine()
        machine.read()
        reading = machine.read()
        for value, top in ((reading.processor, 100), (reading.graphics, 100)):
            assert value is None or 0 <= value <= top
        for value in (reading.memory_free_gb, reading.graphics_memory_free_gb):
            assert value is None or 0 <= value < 4096
