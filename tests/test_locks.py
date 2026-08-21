"""Lock Table tests.

`test_contention_arbitrates_on_priority_not_arrival` is the day-6 entry gate.
If it does not pass by end of day 6, the Lock Table gets cut and the system
ships handling one risk at a time — and says so on the slide. Cutting on day
11, after the build time is already spent, recovers nothing.
"""

from latch.locks import LockTable
from tests.conftest import FrozenClock, make_risk

SLOT = "itt_slot:tuapas_1140"


def test_uncontested_claim_is_granted(clock):
    table = LockTable(clock=clock)
    result = table.claim(SLOT, "cr_0001", priority=18.6)
    assert result.granted
    assert result.reason == "uncontested"
    assert table.holder(SLOT).risk_id == "cr_0001"


def test_contention_arbitrates_on_priority_not_arrival(clock):
    """THE ENTRY GATE.

    Two risks want the last slot. The first to ask has the lower priority and
    must lose it. If this were first-come the Lock Table would be decoration.
    """
    table = LockTable(clock=clock)

    early_but_minor = table.claim(SLOT, "cr_0001", priority=18.6)
    assert early_but_minor.granted

    late_but_urgent = table.claim(SLOT, "cr_0002", priority=41.2)

    assert late_but_urgent.granted, "higher-priority risk must take the slot"
    assert late_but_urgent.preempted_risk_id == "cr_0001"
    assert late_but_urgent.reason == "preempted_lower_priority"
    assert table.holder(SLOT).risk_id == "cr_0002"


def test_loser_is_named_so_it_can_re_deliberate(clock):
    """The loser has to be told. Silent preemption produces a plan built on a
    resource somebody else is holding."""
    table = LockTable(clock=clock)
    table.claim(SLOT, "cr_0001", priority=10.0)
    result = table.claim(SLOT, "cr_0002", priority=99.0)
    assert result.preempted_risk_id == "cr_0001"
    assert table.held_by("cr_0001") == []


def test_lower_priority_claim_is_refused_and_told_who_won(clock):
    table = LockTable(clock=clock)
    table.claim(SLOT, "cr_0002", priority=41.2)
    result = table.claim(SLOT, "cr_0001", priority=18.6)

    assert not result.granted
    assert result.status == "lost"
    assert result.winner_priority == 41.2
    assert result.our_priority == 18.6
    assert result.reason == "outranked"


def test_equal_priority_leaves_the_incumbent_in_place(clock):
    """Ties go to whoever asked first. Stability beats a coin flip here."""
    table = LockTable(clock=clock)
    table.claim(SLOT, "cr_0001", priority=20.0)
    result = table.claim(SLOT, "cr_0002", priority=20.0)
    assert not result.granted
    assert table.holder(SLOT).risk_id == "cr_0001"


def test_committed_reservation_cannot_be_preempted(clock):
    """Once the move has begun, a more urgent risk does not get to un-book it."""
    table = LockTable(clock=clock)
    table.claim(SLOT, "cr_0001", priority=5.0)
    assert table.commit(SLOT, "cr_0001")

    result = table.claim(SLOT, "cr_0002", priority=500.0)
    assert not result.granted
    assert result.reason == "incumbent_committed"
    assert table.holder(SLOT).risk_id == "cr_0001"


def test_commit_fails_if_we_lost_the_slot_in_the_meantime(clock):
    """The gap between claiming and committing is exactly where the bug lives."""
    table = LockTable(clock=clock)
    table.claim(SLOT, "cr_0001", priority=10.0)
    table.claim(SLOT, "cr_0002", priority=40.0)  # preempts

    assert table.commit(SLOT, "cr_0001") is False
    assert table.commit(SLOT, "cr_0002") is True


def test_reservation_expires_so_a_dead_plan_does_not_leak_the_slot(clock):
    table = LockTable(ttl_sec=180, clock=clock)
    table.claim(SLOT, "cr_0001", priority=10.0)

    clock.advance(179)
    assert table.holder(SLOT) is not None

    clock.advance(2)
    assert table.holder(SLOT) is None

    result = table.claim(SLOT, "cr_0002", priority=1.0)
    assert result.granted
    assert result.reason == "uncontested"


def test_committed_reservation_survives_the_ttl_sweep(clock):
    """A TTL sweep must not un-book a move that is physically underway."""
    table = LockTable(ttl_sec=180, clock=clock)
    table.claim(SLOT, "cr_0001", priority=10.0)
    table.commit(SLOT, "cr_0001")

    clock.advance(10_000)
    assert table.holder(SLOT) is not None
    assert table.holder(SLOT).committed


def test_re_claiming_our_own_slot_refreshes_rather_than_deadlocks(clock):
    table = LockTable(ttl_sec=180, clock=clock)
    table.claim(SLOT, "cr_0001", priority=10.0)
    clock.advance(170)

    result = table.claim(SLOT, "cr_0001", priority=12.0)
    assert result.granted
    assert result.reason == "already_held"

    clock.advance(20)  # would have expired under the original claim
    assert table.holder(SLOT) is not None


def test_only_the_holder_may_release(clock):
    table = LockTable(clock=clock)
    table.claim(SLOT, "cr_0001", priority=10.0)
    assert table.release(SLOT, "cr_0002") is False
    assert table.release(SLOT, "cr_0001") is True
    assert table.holder(SLOT) is None


def test_release_all_clears_everything_a_risk_holds(clock):
    table = LockTable(clock=clock)
    table.claim("itt_slot:a", "cr_0001", priority=10.0)
    table.claim("itt_slot:b", "cr_0001", priority=10.0)
    table.claim("itt_slot:c", "cr_0002", priority=10.0)

    assert table.release_all("cr_0001") == ["itt_slot:a", "itt_slot:b"]
    assert table.held_by("cr_0001") == []
    assert table.held_by("cr_0002") == ["itt_slot:c"]


def test_priority_comes_from_the_risk_itself(clock):
    """Wiring check: the number the table arbitrates on is the one the domain
    model computes, not something a caller invented."""
    table = LockTable(clock=clock)
    big_and_tight = make_risk("cr_0002", boxes=55, slack_remaining_min=80)
    small_and_slack = make_risk("cr_0001", boxes=12, slack_remaining_min=400)

    table.claim(SLOT, small_and_slack.risk_id, small_and_slack.priority)
    result = table.claim(SLOT, big_and_tight.risk_id, big_and_tight.priority)

    assert result.granted
    assert result.preempted_risk_id == "cr_0001"


def test_closing_a_risk_does_not_hand_back_a_booked_slot(clock):
    """A committed slot is consumed capacity — the booking happened. Releasing
    it on resolution would hand the same slot to the next risk and let the
    system book it twice, which is the exact failure this table prevents."""
    table = LockTable(clock=clock)
    table.claim(SLOT, "cr_0001", priority=10.0)
    table.commit(SLOT, "cr_0001")

    assert table.release_all("cr_0001") == []
    assert table.holder(SLOT) is not None

    later = table.claim(SLOT, "cr_0002", priority=999.0)
    assert not later.granted
    assert later.reason == "incumbent_committed"


def test_uncommitted_reservations_are_released_on_close(clock):
    """A plan that died holding a provisional claim must not leak it."""
    table = LockTable(clock=clock)
    table.claim(SLOT, "cr_0001", priority=10.0)

    assert table.release_all("cr_0001") == [SLOT]
    assert table.holder(SLOT) is None


def test_a_cancelled_booking_can_return_the_capacity(clock):
    table = LockTable(clock=clock)
    table.claim(SLOT, "cr_0001", priority=10.0)
    table.commit(SLOT, "cr_0001")

    assert table.release_all("cr_0001", keep_committed=False) == [SLOT]
    assert table.holder(SLOT) is None
