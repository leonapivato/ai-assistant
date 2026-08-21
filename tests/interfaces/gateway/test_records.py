"""The admission record: two decisions, four classes, and nothing else (ADR-0168 §6)."""

from __future__ import annotations

from datetime import timedelta

import pytest
import structlog
from gateway_timing import Clock, Timers

from ai_assistant.interfaces.gateway.records import (
    AdmissionRecorder,
    RefusalCondition,
    RequestClass,
)

_INTERVAL = timedelta(minutes=1)


@pytest.fixture
def clock() -> Clock:
    """A wall clock this module's tests move by hand."""
    return Clock()


@pytest.fixture
def timers() -> Timers:
    """Every callback the subject deferred, fired by hand."""
    return Timers()


#: Every member ADR-0168 §6 permits a record to carry, and the whole of it: "the
#: instant, which for a refusal record collapsed under the rate bound below is the
#: interval it covers; the request's class; the outcome; and, for a refusal, the
#: condition it was refused on and the number of times that class and that
#: condition occurred together in that interval."
_PERMITTED = frozenset(
    {
        "event",
        "log_level",
        "instant",
        "interval_start",
        "interval_end",
        "request_class",
        "outcome",
        "condition",
        "count",
    }
)


def _recorder(clock: Clock, timers: Timers) -> AdmissionRecorder:
    """A recorder on ADR-0168 §8's own interval."""
    return AdmissionRecorder(interval=_INTERVAL, now=clock, defer=timers)


def test_a_mint_is_recorded_at_once_and_is_not_rate_bounded(clock: Clock, timers: Timers) -> None:
    """ "A mint record is not rate-bounded and needs no bound, because §5 permits one
    mint per process life" (ADR-0168 §6)."""
    recorder = _recorder(clock, timers)

    with structlog.testing.capture_logs() as records:
        recorder.session_minted()

    assert [record["outcome"] for record in records] == ["session-minted"]
    assert records[0]["request_class"] == RequestClass.BOOTSTRAP.value
    assert records[0]["instant"] == clock.reading.isoformat()


def test_nothing_is_recorded_for_a_request_a_live_session_admits(
    clock: Clock, timers: Timers
) -> None:
    """The recorder has no way to say it, which is the point (ADR-0168 §6, ADR-0172 §5).

    "Nothing is recorded for a request a live session admits, which is not an
    admission decision", and ADR-0172 §5 rules that a successful Tier 0 read on
    the admission path is not recorded either. A surface with no such method is
    how that is enforced rather than remembered.
    """
    recorder = _recorder(clock, timers)

    assert not hasattr(recorder, "admitted")
    assert not hasattr(recorder, "session_admitted")


def test_a_refusal_is_not_emitted_on_arrival(clock: Clock, timers: Timers) -> None:
    """The count is not known until the interval closes, and the record carries it."""
    recorder = _recorder(clock, timers)

    with structlog.testing.capture_logs() as records:
        recorder.refused(RequestClass.ASSISTANT, RefusalCondition.NO_LIVE_SESSION)

    assert records == []


def test_one_record_per_pair_per_interval_carries_the_count(clock: Clock, timers: Timers) -> None:
    """§6's rate bound: "each distinct **pair** of class and condition is emitted at
    most once, so that a caller able to drive a refusal cannot drive a record per
    attempt"."""
    recorder = _recorder(clock, timers)
    for _ in range(50):
        recorder.refused(RequestClass.ASSISTANT, RefusalCondition.NO_LIVE_SESSION)

    with structlog.testing.capture_logs() as records:
        clock.advance(_INTERVAL)
        timers.fire_all()

    assert len(records) == 1
    assert records[0]["count"] == 50
    assert records[0]["condition"] == RefusalCondition.NO_LIVE_SESSION.value


def test_the_collapse_key_is_the_pair_and_not_the_condition_alone(
    clock: Clock, timers: Timers
) -> None:
    """ADR-0168 §6, found by adversarial review on the seventh round.

    "§7 decides a `Host` or an `Origin` refusal before the request's class
    matters, so one condition genuinely spans classes… Collapsing on the condition
    alone then obliges one record to name a singular class it cannot truthfully
    name."
    """
    recorder = _recorder(clock, timers)
    recorder.refused(RequestClass.ASSET, RefusalCondition.HOST_NOT_BOUND)
    recorder.refused(RequestClass.BOOTSTRAP, RefusalCondition.HOST_NOT_BOUND)
    recorder.refused(RequestClass.ASSISTANT, RefusalCondition.HOST_NOT_BOUND)

    with structlog.testing.capture_logs() as records:
        timers.fire_all()

    assert {record["request_class"] for record in records} == {
        RequestClass.ASSET.value,
        RequestClass.BOOTSTRAP.value,
        RequestClass.ASSISTANT.value,
    }
    assert all(record["count"] == 1 for record in records)


def test_a_refusal_record_names_the_interval_it_covers(clock: Clock, timers: Timers) -> None:
    """ "The instant, which for a refusal record collapsed under the rate bound below
    is the interval it covers"."""
    recorder = _recorder(clock, timers)
    opened_at = clock.reading
    recorder.refused(RequestClass.OTHER, RefusalCondition.ORIGIN_NOT_OWN)
    clock.advance(_INTERVAL)

    with structlog.testing.capture_logs() as records:
        timers.fire_all()

    assert records[0]["interval_start"] == opened_at.isoformat()
    assert records[0]["interval_end"] == clock.reading.isoformat()
    assert "instant" not in records[0]


def test_the_interval_resets_and_keeps_no_history(clock: Clock, timers: Timers) -> None:
    """ "A fixed set of integers, reset each interval", and "it keeps no history of
    what it emitted" (ADR-0168 §6)."""
    recorder = _recorder(clock, timers)
    recorder.refused(RequestClass.ASSISTANT, RefusalCondition.NO_LIVE_SESSION)
    timers.fire_all()

    with structlog.testing.capture_logs() as records:
        timers.fire_all()
        recorder.flush()

    assert records == []


def test_a_second_interval_starts_only_when_a_refusal_falls_in_it(
    clock: Clock, timers: Timers
) -> None:
    """A gateway nobody is attacking arms no timer and holds no counter."""
    recorder = _recorder(clock, timers)
    recorder.refused(RequestClass.ASSISTANT, RefusalCondition.NO_LIVE_SESSION)
    timers.fire_all()
    assert timers.armed == []

    recorder.refused(RequestClass.ASSISTANT, RefusalCondition.SESSION_CEILING)

    assert len(timers.armed) == 1
    assert timers.armed[0].delay == _INTERVAL.total_seconds()


def test_flushing_on_the_way_down_does_not_swallow_the_interval_in_progress(
    clock: Clock, timers: Timers
) -> None:
    """A gateway that stops mid-interval has counted refusals nobody has read."""
    recorder = _recorder(clock, timers)
    recorder.refused(RequestClass.OTHER, RefusalCondition.BOOTSTRAP_EXCHANGE_FAILED)

    with structlog.testing.capture_logs() as records:
        recorder.flush()

    assert len(records) == 1


def test_every_recorded_member_is_one_adr_0168_section_6_permits(
    clock: Clock, timers: Timers
) -> None:
    """The enumeration is exclusive, and an *exclusion list* was the defect it replaced.

    "An earlier draft had the gateway record 'the request' and forbade only the
    session values — which still admits the utterance out of a refused `ask`, Tier
    1 by ADR-0004 §1, and the bootstrap value out of a failed exchange, Tier 0."
    So the check is that nothing outside the permitted set ever appears.
    """
    recorder = _recorder(clock, timers)

    with structlog.testing.capture_logs() as records:
        recorder.session_minted()
        recorder.refused(RequestClass.ASSISTANT, RefusalCondition.COOKIE_HALF_MISMATCH)
        recorder.flush()

    assert records
    for record in records:
        assert set(record) <= _PERMITTED, record


def test_the_four_request_classes_and_six_conditions_are_the_whole_enumeration() -> None:
    """Both enumerations are "fixed in advance" and total (ADR-0168 §6).

    The classes are §1's four kinds of request; the conditions are the ones §6
    names — §3's, §4's, §5's, §6's and §7's — and §8's are deliberately not among
    them, since "nothing [is recorded] for a refusal on any other ground, §8's
    size bound included".
    """
    assert {member.value for member in RequestClass} == {
        "asset",
        "bootstrap-exchange",
        "assistant-request",
        "other",
    }
    assert {member.value for member in RefusalCondition} == {
        "host-not-bound",
        "origin-not-own",
        "no-live-session",
        "cookie-half-mismatch",
        "session-ceiling",
        "bootstrap-exchange-failed",
    }


def test_a_record_names_a_class_and_an_outcome_always(clock: Clock, timers: Timers) -> None:
    """ "Every record names one class, and every refusal record one condition"."""
    recorder = _recorder(clock, timers)

    with structlog.testing.capture_logs() as records:
        recorder.session_minted()
        recorder.refused(RequestClass.ASSET, RefusalCondition.HOST_NOT_BOUND)
        recorder.flush()

    for record in records:
        assert record["request_class"]
        assert record["outcome"]
    refusals = [one for one in records if one["outcome"] == "refused"]
    assert all(one["condition"] for one in refusals)
