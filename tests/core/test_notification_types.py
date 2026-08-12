"""The invariants ADR-0130 puts on its types rather than in a store's care.

The three conformance suites in ``notification_contract.py`` hold
*implementations* to §3 and §5 through §9. These are the rules that hold however
a record is built — the ones a store never gets a chance to break, because the
model refuses first — plus the two predicates §7's whole retention argument rests
on. A validator with no case against it is a validator a refactor deletes.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import pytest

from ai_assistant.core.types import (
    ClassReach,
    DataTier,
    HeldNotification,
    NotificationCandidate,
    NotificationCondition,
    NotificationDisposition,
    NotificationDispositionKind,
    NotificationPreferences,
    NotificationReach,
    QuietWindow,
    minute_of_day,
)

_AT = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


def _candidate(**overrides: object) -> NotificationCandidate:
    """One candidate, with everything a case is not about held constant."""
    fields: dict[str, object] = {
        "candidate_key": "k1",
        "producer": "a-producer",
        "notification_class": "calendar",
        "summary": "something the user did not ask for",
        "noticed_at": _AT,
        "confidence": 0.5,
        "sensitivity": DataTier.PERSONAL,
    }
    return NotificationCandidate(**(fields | overrides))  # type: ignore[arg-type]


def _record(**overrides: object) -> HeldNotification:
    """One held record, likewise."""
    fields: dict[str, object] = {
        "id": "ntf-1",
        "candidate": _candidate(),
        "kind": NotificationDispositionKind.HOLD,
        "reason": NotificationCondition.PERISHABLE,
        "failed": (NotificationCondition.PERISHABLE,),
        "ruled_at": _AT,
        "admitted_at": _AT,
        "retention": timedelta(days=7),
    }
    return HeldNotification(**(fields | overrides))  # type: ignore[arg-type]


# --- §2: what a candidate may not be ----------------------------------------


def test_a_tier_zero_candidate_is_refused_at_validation() -> None:
    """ADR-0004 §3 is unconditional, so this is a refusal and not a gate.

    Refusing at validation rather than at disposition is what keeps it true of
    *every* disposition including the held one: a rule that only stopped Tier 0
    interrupting would still have written it down.
    """
    with pytest.raises(ValueError, match="SECRET"):
        _candidate(sensitivity=DataTier.SECRET)


def test_a_candidate_that_has_already_perished_is_refused() -> None:
    """§2: it is not a proposal, it is a defect."""
    with pytest.raises(ValueError, match="expires_at"):
        _candidate(expires_at=_AT - timedelta(seconds=1))
    with pytest.raises(ValueError, match="expires_at"):
        _candidate(expires_at=_AT)


def test_a_candidate_declares_its_sensitivity_and_is_never_defaulted() -> None:
    """ADR-0093 §4's rule for an attested proposal, kept by omitting a default.

    A producer that wants to notify about a credential therefore learns so at the
    point it proposes, rather than having a tier chosen for it.
    """
    with pytest.raises(ValueError, match="sensitivity"):
        NotificationCandidate(
            candidate_key="k1",
            producer="p",
            notification_class="calendar",
            summary="s",
            noticed_at=_AT,
            confidence=0.5,
        )  # type: ignore[call-arg]


def test_perishability_is_half_open_at_the_expiry_it_names() -> None:
    """§5's boundary, spelled once so a policy and a store cannot disagree."""
    subject = _candidate(expires_at=_AT + timedelta(hours=1))

    assert subject.is_perishable_at(_AT + timedelta(minutes=59, seconds=59)) is True
    assert subject.is_perishable_at(_AT + timedelta(hours=1)) is False
    assert _candidate().is_perishable_at(_AT) is False


# --- §5: what a ruling may not be -------------------------------------------


def _ruling(**overrides: object) -> NotificationDisposition:
    fields: dict[str, object] = {
        "kind": NotificationDispositionKind.HOLD,
        "notification_id": "ntf-1",
        "notification_class": "calendar",
        "ruled_at": _AT,
        "reason": NotificationCondition.QUIET_WINDOW,
        "failed": (NotificationCondition.QUIET_WINDOW,),
    }
    return NotificationDisposition(**(fields | overrides))  # type: ignore[arg-type]


def test_a_hold_must_name_the_conditions_that_failed() -> None:
    """§6 reads the set; an empty one leaves a record no setting change can free."""
    with pytest.raises(ValueError, match="every condition that failed"):
        _ruling(failed=())


def test_a_holds_reason_is_the_first_of_its_failed_set() -> None:
    """§5: the reason names the first for rendering, the set is what §6 reads."""
    with pytest.raises(ValueError, match="first unsatisfied condition"):
        _ruling(
            reason=NotificationCondition.BUDGET,
            failed=(NotificationCondition.QUIET_WINDOW, NotificationCondition.BUDGET),
        )


def test_only_a_hold_carries_a_failed_set() -> None:
    """An INTERRUPT carrying failures would spend a unit of budget it did not earn."""
    with pytest.raises(ValueError, match="only a HOLD carries a failed set"):
        _ruling(
            kind=NotificationDispositionKind.INTERRUPT,
            reason=NotificationCondition.PERISHABLE,
            failed=(NotificationCondition.BUDGET,),
        )


def test_a_failed_set_holds_only_the_four_conjunctive_conditions() -> None:
    """The four DROP conditions are evaluated first and each yields DROP itself."""
    with pytest.raises(ValueError, match="ordered subsequence"):
        _ruling(
            reason=NotificationCondition.DUPLICATE,
            failed=(NotificationCondition.DUPLICATE,),
        )


def test_a_failed_set_is_ordered_and_a_reversed_one_is_refused() -> None:
    """§5 defines the reason as the *first* failure, so the order carries meaning.

    ``(BUDGET, QUIET_WINDOW)`` with ``reason=BUDGET`` is two true facts arranged
    into a false answer: §5's order makes the quiet window the first to fail, so a
    surface rendering that ruling would tell the user their budget stopped a
    notification their quiet hours stopped. It matters most for a value decoded
    off the wire, which no producing implementation vouched for.
    """
    with pytest.raises(ValueError, match="ordered subsequence"):
        _ruling(
            reason=NotificationCondition.BUDGET,
            failed=(NotificationCondition.BUDGET, NotificationCondition.QUIET_WINDOW),
        )

    ordered = _ruling(
        reason=NotificationCondition.QUIET_WINDOW,
        failed=(NotificationCondition.QUIET_WINDOW, NotificationCondition.BUDGET),
    )
    assert ordered.reason is ordered.failed[0]


def test_a_failed_set_names_each_condition_once() -> None:
    """A repeat is refused by the same rule, a subsequence having no duplicates."""
    with pytest.raises(ValueError, match="ordered subsequence"):
        _ruling(
            failed=(NotificationCondition.QUIET_WINDOW, NotificationCondition.QUIET_WINDOW),
        )


def test_a_due_instant_needs_every_failure_to_be_one_time_resolves() -> None:
    """§5: the reach level and an absent expiry are each a condition it does not.

    A ``reconsider_at`` on such a set promises a re-ruling that cannot change
    anything, which is a run spent on every tick for the life of the record.
    """
    with pytest.raises(ValueError, match="time alone resolves"):
        _ruling(
            reason=NotificationCondition.REACH_INTERRUPT,
            failed=(NotificationCondition.REACH_INTERRUPT,),
            reconsider_at=_AT + timedelta(hours=1),
        )


def test_only_a_hold_falls_due_for_reconsideration() -> None:
    """§6: no setting change reaches a record already ruled INTERRUPT."""
    with pytest.raises(ValueError, match="only a HOLD falls due"):
        _ruling(
            kind=NotificationDispositionKind.INTERRUPT,
            reason=NotificationCondition.PERISHABLE,
            failed=(),
            reconsider_at=_AT + timedelta(hours=1),
        )


def test_a_drop_names_a_drop_condition_and_an_interrupt_an_interrupt_one() -> None:
    """Each kind draws its reason from its own group, so a ruling reads honestly."""
    with pytest.raises(ValueError, match="DROP_CONDITIONS"):
        _ruling(
            kind=NotificationDispositionKind.DROP,
            reason=NotificationCondition.BUDGET,
            failed=(),
        )
    with pytest.raises(ValueError, match="INTERRUPT_CONDITIONS"):
        _ruling(
            kind=NotificationDispositionKind.INTERRUPT,
            reason=NotificationCondition.AT_CAP,
            failed=(),
        )


def test_a_kept_ruling_names_the_record_it_produced_and_a_drop_need_not() -> None:
    """§8: a DROP writes no durable record, so it has none to name."""
    with pytest.raises(ValueError, match="names the durable record"):
        _ruling(notification_id=None)

    dropped = _ruling(
        kind=NotificationDispositionKind.DROP,
        notification_id=None,
        reason=NotificationCondition.DUPLICATE,
        failed=(),
    )
    assert dropped.notification_id is None


# --- §7: actionable, retained, purgeable ------------------------------------


def test_a_records_reconsider_at_is_checked_more_loosely_than_a_rulings() -> None:
    """§6's second writer, which stamps one onto a set time never resolves.

    The record below is held only because its class sits at ``hold``. A *ruling*
    may not give it a due instant; the setting write that raises the class must,
    or the user who agreed to be interrupted never is.
    """
    stamped = _record(
        reason=NotificationCondition.REACH_INTERRUPT,
        failed=(NotificationCondition.REACH_INTERRUPT,),
        reconsider_at=_AT,
    )

    assert stamped.is_due_at(_AT) is True

    with pytest.raises(ValueError, match="only a held record falls due"):
        _record(
            kind=NotificationDispositionKind.INTERRUPT,
            reason=NotificationCondition.PERISHABLE,
            failed=(),
            reconsider_at=_AT,
        )


def test_a_dropped_record_is_stamped_and_an_undropped_one_is_not() -> None:
    """A DROP without a stamp has no cessation instant for retention to run from."""
    with pytest.raises(ValueError, match="dropped_at"):
        _record(
            kind=NotificationDispositionKind.DROP,
            reason=NotificationCondition.REACH_OFF,
            failed=(),
        )
    with pytest.raises(ValueError, match="dropped_at"):
        _record(dropped_at=_AT)


def test_cessation_is_the_earliest_of_the_three_ways_it_ends() -> None:
    """§7, and the reason a late DROP moves no retention horizon.

    A record that expired at noon and was dropped by a reconsideration an hour
    later ceased at noon: retention runs from the first of them, so recording the
    later ruling costs the user nothing.
    """
    expired_then_dropped = _record(
        candidate=_candidate(expires_at=_AT + timedelta(hours=1)),
        kind=NotificationDispositionKind.DROP,
        reason=NotificationCondition.EXPIRED,
        failed=(),
        dropped_at=_AT + timedelta(hours=2),
    )

    assert expired_then_dropped.ceased_at() == _AT + timedelta(hours=1)


def test_a_record_with_no_ending_is_actionable_and_never_purgeable() -> None:
    """§7: no record is purged while it is still actionable, whatever its retention.

    Measured from admission instead, such a record is purged while its key is
    still the thing suppressing a cursorless producer's repetition — and the same
    observation then interrupts again on a schedule set by the retention figure.
    """
    forever = _record(retention=timedelta(seconds=1))

    assert forever.ceased_at() is None
    assert forever.is_actionable_at(_AT + timedelta(days=3650)) is True
    assert forever.is_purgeable_at(_AT + timedelta(days=3650)) is False


def test_the_retention_horizon_is_exclusive_and_none_is_never_purged() -> None:
    """§9's boundary: neither before nor **at** the horizon, but immediately after."""
    dismissed = _record(dismissed_at=_AT, retention=timedelta(days=7))
    horizon = _AT + timedelta(days=7)

    assert dismissed.is_actionable_at(_AT) is False
    assert dismissed.is_purgeable_at(horizon) is False
    assert dismissed.is_purgeable_at(horizon + timedelta(microseconds=1)) is True

    kept = _record(dismissed_at=_AT, retention=None)
    assert kept.is_purgeable_at(_AT + timedelta(days=3650)) is False


@pytest.mark.parametrize(
    "retention",
    [timedelta(days=4_000_000), timedelta.max],
    ids=["past-the-calendar", "the-longest-there-is"],
)
def test_a_retention_horizon_past_the_calendar_answers_not_purgeable(
    retention: timedelta,
) -> None:
    """§7 puts no ceiling on a retention, so the horizon can leave the calendar.

    ``ceased + retention`` raises ``OverflowError`` for both of these, and the
    predicate has to answer anyway: it is what ADR-0083 §7's **shared** retention
    job reads, so one such record raising would stop ``MemoryStore`` and
    ``DeferralStore`` being swept too. The answer is the one §7 states — a
    retention that has not elapsed leaves the record retained — and a horizon past
    the end of representable time never elapses.

    The smaller of the two is deliberately inside what a durable store can stamp
    as microseconds in a signed 64-bit column, so the case is not merely
    theoretical: it is an ``OverflowError`` for a retention a backend accepts.
    """
    dismissed = _record(dismissed_at=_AT, retention=retention)
    with pytest.raises(OverflowError):
        _AT + retention  # the spelling this predicate must not use

    assert dismissed.is_actionable_at(_AT) is False
    assert dismissed.is_purgeable_at(_AT) is False
    assert dismissed.is_purgeable_at(datetime.max.replace(tzinfo=UTC)) is False


def test_the_horizon_holds_at_the_far_end_of_the_calendar() -> None:
    """The other end of the same range: a record that ceased near ``datetime.min``.

    Here the sum *is* representable for a large retention, so this is the case
    that would catch a fix which answered ``False`` for every long retention
    rather than only for an unreachable horizon. The boundary stays §9's —
    exclusive at the horizon, purgeable one microsecond past it.
    """
    ceased = datetime.min.replace(tzinfo=UTC) + timedelta(days=1)
    retention = timedelta(days=2_000_000)
    dismissed = _record(
        candidate=_candidate(noticed_at=ceased),
        ruled_at=ceased,
        admitted_at=ceased,
        dismissed_at=ceased,
        retention=retention,
    )
    horizon = ceased + retention

    assert dismissed.is_purgeable_at(horizon) is False
    assert dismissed.is_purgeable_at(horizon + timedelta(microseconds=1)) is True


def test_a_dismissed_record_is_never_due_however_long_it_waits() -> None:
    """§6 stops at *actionable* held records, and a dismissal ends that."""
    dismissed = _record(dismissed_at=_AT, reconsider_at=_AT)

    assert dismissed.is_due_at(_AT + timedelta(days=1)) is False


# --- §6: the standing settings ----------------------------------------------


def test_a_class_no_preference_names_takes_the_shipped_default() -> None:
    """§6: hold for every class, which is why nothing interrupts out of the box."""
    settings = NotificationPreferences(
        reaches=(ClassReach(notification_class="calendar", reach=NotificationReach.INTERRUPT),)
    )

    assert settings.reach_for("calendar") is NotificationReach.INTERRUPT
    assert settings.reach_for("mail") is NotificationReach.HOLD


def test_one_class_may_not_carry_two_reach_levels() -> None:
    """A class whose reach is ambiguous is one whose ``off`` may silently not hold."""
    with pytest.raises(ValueError, match="one reach level"):
        NotificationPreferences(
            reaches=(
                ClassReach(notification_class="calendar", reach=NotificationReach.OFF),
                ClassReach(notification_class="calendar", reach=NotificationReach.INTERRUPT),
            )
        )


def test_a_quiet_window_may_cross_midnight() -> None:
    """The ordinary overnight case, expressed directly rather than as two rows."""
    overnight = QuietWindow.between(time(22, 0), time(7, 0))

    assert overnight.covers(minute_of_day(time(23, 30))) is True
    assert overnight.covers(minute_of_day(time(3, 0))) is True
    assert overnight.covers(minute_of_day(time(7, 0))) is False
    assert overnight.covers(minute_of_day(time(12, 0))) is False


def test_a_quiet_window_is_half_open_at_both_ends() -> None:
    """``[start, end)``: covered at the minute it begins, free at the one it ends."""
    daytime = QuietWindow.between(time(11, 0), time(13, 0))

    assert daytime.covers(minute_of_day(time(11, 0))) is True
    assert daytime.covers(minute_of_day(time(12, 59))) is True
    assert daytime.covers(minute_of_day(time(13, 0))) is False


def test_a_window_naming_one_minute_twice_is_refused() -> None:
    """An empty window and an all-day one are not distinguishable (§6)."""
    with pytest.raises(ValueError, match="must differ"):
        QuietWindow.between(time(9, 0), time(9, 0))


def test_a_window_endpoint_may_not_carry_a_timezone() -> None:
    """§6 introduces no second timezone source, so one cannot be smuggled in.

    ``minute_of_day`` is where that is refused, because the stored endpoint is an
    integer and an integer has nowhere to keep a zone — which is the one thing
    this spelling gets for free.
    """
    with pytest.raises(ValueError, match="naive"):
        minute_of_day(time(22, 0, tzinfo=UTC))


def test_an_endpoint_renders_back_to_the_time_it_was_written_as() -> None:
    """The round trip a surface needs, so a user reads back what they set."""
    window = QuietWindow.between(time(22, 15), time(7, 45))

    assert (window.start, window.end) == (22 * 60 + 15, 7 * 60 + 45)
    assert (window.start_time, window.end_time) == (time(22, 15), time(7, 45))


def test_an_endpoint_outside_the_day_is_refused() -> None:
    """1440 is midnight *tomorrow*, and a window is a statement about one day."""
    with pytest.raises(ValueError, match="less than 1440"):
        QuietWindow(start=1440, end=0)
    with pytest.raises(ValueError, match="greater than or equal to 0"):
        QuietWindow(start=-1, end=0)
