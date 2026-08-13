"""ADR-0141 §3's ruling seam: what one ruling's trace carries, and what it omits.

The omissions carry as much here as the contents do. ADR-0119 §3's observation
rule makes an absent key mean *not observed* rather than zero, and §5 of ADR-0141
reads the two apart: a trace carrying **none** of §4's keys is a crossing that
raised before its ruling committed and enters no population, where a trace
carrying some of them is a malformed emitter. So the fault cases below assert an
empty metric mapping rather than a mapping of zeros, and the ``DROP`` cases assert
that the four interrupt-condition keys are absent rather than ``0``.

**Nothing here asks a fake or a conformance suite to emit** (§10). Emission is a
property of the wired concrete — the required ``traces_sink`` argument is the
mechanism — and not an obligation of the ``NotificationStore`` contract, so
ADR-0130 §9's shared suite gains no case and no canonical fake changes. What is
pinned is the one store the composition root wires.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import structlog
from notification_contract import NOW, MutableClock, candidate, reaching
from pydantic import TypeAdapter

from ai_assistant.core.correlation import correlated_operation
from ai_assistant.core.errors import NotificationStoreError, TraceStoreError
from ai_assistant.core.types import (
    INTERRUPT_CONDITIONS,
    ClassReach,
    NotificationCondition,
    NotificationDispositionKind,
    NotificationPreferences,
    NotificationReach,
    QuietWindow,
    TraceKind,
    TraceLabel,
    TraceOutcome,
    TraceRef,
)
from ai_assistant.memory import notification_store, notification_traces, traces
from ai_assistant.memory.notification_policy import DefaultNotificationPolicy
from ai_assistant.memory.notification_store import SqliteNotificationStore
from ai_assistant.memory.notification_traces import (
    CONDITION_METRICS,
    DISPOSITION_METRICS,
    HELD_SECONDS,
    SEAM_ADMIT,
    SEAM_RECONSIDER,
)
from ai_assistant.testing import FakeTraceSink

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from ai_assistant.core.types import (
        EvaluationTrace,
        HeldNotification,
        NotificationCandidate,
        NotificationDisposition,
    )

#: The type a seam label and a metric key both are, so the constants below are
#: checked against ``core``'s own validator rather than against a copy of it.
_LABEL: TypeAdapter[str] = TypeAdapter(TraceLabel)

#: A quiet window covering ``NOW`` (midday UTC) and ending at 13:00, so an
#: admission under it is held with a ``reconsider_at`` a case can advance past.
_QUIET = QuietWindow(start=11 * 60, end=13 * 60)

#: The four keys a ``DROP`` carries none of, and a completed ruling of any other
#: kind carries all of (§4).
_INTERRUPT_KEYS = frozenset(CONDITION_METRICS[condition] for condition in INTERRUPT_CONDITIONS)


def _perishable(key: str = "k1") -> NotificationCandidate:
    """A candidate that could interrupt, because it declares a live expiry."""
    return candidate(key=key, expires_at=NOW + timedelta(days=1))


def _interrupting(*, quiet: bool = False) -> NotificationPreferences:
    """Settings under which a perishable candidate is ruled ``INTERRUPT``."""
    return NotificationPreferences(
        reaches=(ClassReach(notification_class="calendar", reach=NotificationReach.INTERRUPT),),
        quiet_windows=(_QUIET,) if quiet else (),
    )


class _BreakingClock(MutableClock):
    """A clock a case can break *after* it has already been read successfully.

    The store fixes its clock at construction, so a case about a reading that
    fails on the **second** ruling — the reconsideration of a record the first
    one admitted — cannot express itself with a clock that was broken all along.
    """

    def __init__(self, at: datetime = NOW) -> None:
        """Start readable.

        Args:
            at: The first reading.
        """
        super().__init__(at)
        #: What the invocation raises once set — ``checked_clock`` lets this past
        #: unwrapped, including a ``BaseException``.
        self.failure: BaseException | None = None
        #: Whether the reading is naive, which the guard refuses as its own error.
        self.naive = False

    def __call__(self) -> datetime:
        """Read the clock, or fail in whichever way the case asked for.

        Returns:
            The current reading, naive where the case asked for one.

        Raises:
            BaseException: Whatever the case set, unwrapped.
        """
        if self.failure is not None:
            raise self.failure
        reading = super().__call__()
        return reading.replace(tzinfo=None) if self.naive else reading


def _only(sink: FakeTraceSink) -> EvaluationTrace:
    """The one notification trace the sink holds — §3's one-crossing rule, as a test."""
    recorded = sink.recorded
    assert len(recorded) == 1, f"expected exactly one trace, got {len(recorded)}"
    return recorded[0]


def _condition(trace: EvaluationTrace, condition: NotificationCondition) -> object:
    """What one condition's key carries, or ``None`` where the key is absent."""
    return trace.metrics.get(CONDITION_METRICS[condition])


@pytest.fixture
def sink() -> FakeTraceSink:
    """The sink an emitter's test is handed: append only, read back by the test."""
    return FakeTraceSink()


@pytest.fixture
def make_store(
    tmp_path: Path, sink: FakeTraceSink
) -> Iterator[Callable[..., SqliteNotificationStore]]:
    """Build stores over one sink, closed on teardown so temp files release cleanly."""
    opened: list[SqliteNotificationStore] = []

    def build(**overrides: Any) -> SqliteNotificationStore:
        arguments: dict[str, Any] = {
            "path": tmp_path / f"notifications-{len(opened)}.db",
            "traces_sink": sink,
            "now": MutableClock(),
        }
        arguments.update(overrides)
        store = SqliteNotificationStore(**arguments)
        opened.append(store)
        return store

    try:
        yield build
    finally:
        for store in opened:
            store.close()


# --- the admission seam -------------------------------------------------------


async def test_an_admission_records_one_trace_at_its_own_seam(
    make_store: Callable[..., SqliteNotificationStore], sink: FakeTraceSink
) -> None:
    """§3: one crossing of ``admit``, one ``NOTIFICATION`` trace, one seam label."""
    store = make_store()

    await store.admit(candidate(), policy=DefaultNotificationPolicy())

    trace = _only(sink)
    assert trace.kind is TraceKind.NOTIFICATION
    assert trace.seam == SEAM_ADMIT
    assert trace.outcome is TraceOutcome.OK


async def test_a_ruling_carries_all_three_disposition_keys(
    make_store: Callable[..., SqliteNotificationStore], sink: FakeTraceSink
) -> None:
    """§4: all three, each ``0`` or ``1``, summing to exactly one.

    Written by one statement so they are observed and lost together, which is what
    lets §6 draw a numerator and a denominator from one trace and satisfy
    ADR-0119 §5's rule without an external count.
    """
    store = make_store()

    await store.admit(candidate(), policy=DefaultNotificationPolicy())

    metrics = _only(sink).metrics
    assert {key: metrics[key] for key in DISPOSITION_METRICS.values()} == {
        "ruled_interrupt": 0,
        "ruled_hold": 1,
        "ruled_drop": 0,
    }


async def test_a_ruling_that_dropped_carries_the_drop_conditions_and_no_interrupt_condition(
    make_store: Callable[..., SqliteNotificationStore], sink: FakeTraceSink
) -> None:
    """§4: all four drop conditions always, and the interrupt four exactly when not ``DROP``.

    The ruling stopped at the first drop condition, so the policy never evaluated
    the other half — and the store may not evaluate it either, because a quiet
    window is read in ``Settings.timezone``, which is a construction-time property
    of the *policy* and never crosses the seam.
    """
    store = make_store()
    await store.set_preferences(reaching("calendar", NotificationReach.OFF))

    ruling = await store.admit(_perishable(), policy=DefaultNotificationPolicy())

    assert ruling.kind is NotificationDispositionKind.DROP
    trace = _only(sink)
    assert _condition(trace, NotificationCondition.REACH_OFF) == 1
    assert _condition(trace, NotificationCondition.EXPIRED) == 0
    assert _condition(trace, NotificationCondition.DUPLICATE) == 0
    assert _condition(trace, NotificationCondition.AT_CAP) == 0
    assert _INTERRUPT_KEYS.isdisjoint(trace.metrics)
    assert HELD_SECONDS not in trace.metrics


async def test_a_hold_carries_a_zero_for_each_condition_that_failed_and_a_one_for_the_rest(
    make_store: Callable[..., SqliteNotificationStore], sink: FakeTraceSink
) -> None:
    """§4: the interrupt half is read off the disposition and never recomputed.

    ``NotificationDisposition`` refuses at construction any ``HOLD`` whose
    ``failed`` is not the whole ordered failing set, so the recovery rests on the
    contract rather than on ``DefaultNotificationPolicy``'s behaviour — a custom
    policy cannot make this reading wrong without being refused first.
    """
    store = make_store()

    # No expiry and the default reach: two conditions fail, two hold.
    ruling = await store.admit(candidate(), policy=DefaultNotificationPolicy())

    assert ruling.failed == (
        NotificationCondition.PERISHABLE,
        NotificationCondition.REACH_INTERRUPT,
    )
    trace = _only(sink)
    assert _condition(trace, NotificationCondition.PERISHABLE) == 0
    assert _condition(trace, NotificationCondition.REACH_INTERRUPT) == 0
    assert _condition(trace, NotificationCondition.QUIET_WINDOW) == 1
    assert _condition(trace, NotificationCondition.BUDGET) == 1


async def test_an_interrupt_carries_a_one_for_every_interrupt_condition(
    make_store: Callable[..., SqliteNotificationStore], sink: FakeTraceSink
) -> None:
    """§4: ADR-0130 §5 rules that kind exactly when all four hold, so all four are ``1``."""
    store = make_store()
    await store.set_preferences(_interrupting())

    ruling = await store.admit(_perishable(), policy=DefaultNotificationPolicy())

    assert ruling.kind is NotificationDispositionKind.INTERRUPT
    trace = _only(sink)
    assert {key: trace.metrics[key] for key in sorted(_INTERRUPT_KEYS)} == dict.fromkeys(
        sorted(_INTERRUPT_KEYS), 1
    )
    assert trace.metrics["ruled_interrupt"] == 1
    assert HELD_SECONDS not in trace.metrics


async def test_a_candidate_declaring_no_expiry_carries_zero_for_both_expiry_conditions(
    make_store: Callable[..., SqliteNotificationStore], sink: FakeTraceSink
) -> None:
    """§4: the propositions are the enumeration's own and the two are not negations.

    ``EXPIRED`` declares an expiry not later than the ruling instant and
    ``PERISHABLE`` declares one later than it, so a candidate declaring **no**
    expiry makes both false — which is the ordinary case, and precisely why
    ADR-0130 §5 holds such a candidate rather than dropping it.
    """
    store = make_store()

    await store.admit(candidate(), policy=DefaultNotificationPolicy())

    trace = _only(sink)
    assert _condition(trace, NotificationCondition.EXPIRED) == 0
    assert _condition(trace, NotificationCondition.PERISHABLE) == 0


async def test_an_expired_candidate_carries_the_expired_condition(
    make_store: Callable[..., SqliteNotificationStore], sink: FakeTraceSink
) -> None:
    """§4: the store reads the candidate's expiry against the ruling instant.

    A candidate cannot be *born* expired — ``NotificationCandidate`` refuses one
    whose expiry does not follow the instant it was noticed at — so the case a
    ruling meets is a proposal that perished on the way, and the ruling instant is
    what decides it.
    """
    store = make_store(now=MutableClock(NOW + timedelta(hours=2)))

    ruling = await store.admit(
        candidate(expires_at=NOW + timedelta(hours=1)), policy=DefaultNotificationPolicy()
    )

    assert ruling.reason is NotificationCondition.EXPIRED
    assert _condition(_only(sink), NotificationCondition.EXPIRED) == 1


async def test_the_duplicate_and_at_cap_conditions_are_the_booleans_the_store_handed_the_policy(
    make_store: Callable[..., SqliteNotificationStore], sink: FakeTraceSink
) -> None:
    """§4: each is read from an argument the store passed to ``rule``.

    ADR-0130 §9's determinism clause makes the ruling a function of those
    arguments, so the store's reading and the policy's are the same reading —
    which is what lets the two halves of §4's roster come from two sources without
    the risk of them disagreeing.
    """
    store = make_store(cap=1)
    policy = DefaultNotificationPolicy()

    await store.admit(candidate(key="k1"), policy=policy)
    await store.admit(candidate(key="k1"), policy=policy)
    await store.admit(candidate(key="k2"), policy=policy)

    held, duplicate, at_cap = sink.recorded
    assert _condition(held, NotificationCondition.DUPLICATE) == 0
    assert _condition(duplicate, NotificationCondition.DUPLICATE) == 1
    assert _condition(at_cap, NotificationCondition.AT_CAP) == 1


# --- the reconsideration seam -------------------------------------------------


async def _held_behind_a_quiet_window(
    store: SqliteNotificationStore, clock: MutableClock
) -> NotificationDisposition:
    """Admit a candidate that would interrupt but for the window covering ``NOW``."""
    await store.set_preferences(_interrupting(quiet=True))
    ruling = await store.admit(_perishable(), policy=DefaultNotificationPolicy())
    assert ruling.kind is NotificationDispositionKind.HOLD
    assert ruling.reason is NotificationCondition.QUIET_WINDOW
    clock.advance(timedelta(hours=1))  # past the window's 13:00 end
    return ruling


async def test_a_reconsideration_that_interrupts_carries_how_long_the_record_was_held(
    make_store: Callable[..., SqliteNotificationStore], sink: FakeTraceSink
) -> None:
    """§4: the ruling instant less ``admitted_at``, in seconds, at this seam alone.

    The store already holds ``admitted_at`` on the record it is re-ruling, so the
    duration travels as a number rather than as the join a ``TraceRef`` member
    would have bought at ADR-0119 §13e's full price.
    """
    clock = MutableClock()
    store = make_store(now=clock)
    ruling = await _held_behind_a_quiet_window(store, clock)
    assert ruling.notification_id is not None

    reconsidered = await store.reconsider(
        ruling.notification_id, policy=DefaultNotificationPolicy()
    )

    assert reconsidered is not None
    assert reconsidered.kind is NotificationDispositionKind.INTERRUPT
    admission, reconsideration = sink.recorded
    assert admission.seam == SEAM_ADMIT
    assert HELD_SECONDS not in admission.metrics
    assert reconsideration.seam == SEAM_RECONSIDER
    assert reconsideration.metrics[HELD_SECONDS] == timedelta(hours=1).total_seconds()


async def test_a_reconsideration_that_did_not_interrupt_carries_no_held_seconds(
    make_store: Callable[..., SqliteNotificationStore], sink: FakeTraceSink
) -> None:
    """§4: ``held_seconds`` rides on an interrupting reconsideration and no other trace.

    A record whose candidate perished while it was held is ADR-0130 §5's other
    route to ``DROP``, and a ``DROP`` carries none of the interrupt conditions
    wherever it was ruled.
    """
    clock = MutableClock()
    store = make_store(now=clock)
    ruling = await _held_behind_a_quiet_window(store, clock)
    assert ruling.notification_id is not None
    clock.advance(timedelta(days=1))  # past the candidate's expiry

    reconsidered = await store.reconsider(
        ruling.notification_id, policy=DefaultNotificationPolicy()
    )

    assert reconsidered is not None
    assert reconsidered.kind is NotificationDispositionKind.DROP
    trace = sink.recorded[-1]
    assert trace.seam == SEAM_RECONSIDER
    assert HELD_SECONDS not in trace.metrics
    assert _INTERRUPT_KEYS.isdisjoint(trace.metrics)
    assert _condition(trace, NotificationCondition.EXPIRED) == 1


async def test_a_reconsideration_that_found_nothing_to_rule_emits_no_trace(
    make_store: Callable[..., SqliteNotificationStore], sink: FakeTraceSink
) -> None:
    """§3: "no ruling was made", so there is no event for a trace to record."""
    store = make_store()

    assert await store.reconsider("nothing-here", policy=DefaultNotificationPolicy()) is None

    assert sink.recorded == ()


async def test_a_reconsideration_records_one_trace_per_call(
    make_store: Callable[..., SqliteNotificationStore], sink: FakeTraceSink
) -> None:
    """§3: one crossing at most one trace, on the seam that re-rules one record."""
    clock = MutableClock()
    store = make_store(now=clock)
    ruling = await _held_behind_a_quiet_window(store, clock)
    assert ruling.notification_id is not None

    await store.reconsider(ruling.notification_id, policy=DefaultNotificationPolicy())

    assert [trace.seam for trace in sink.recorded] == [SEAM_ADMIT, SEAM_RECONSIDER]


# --- the instant, and the fault paths -----------------------------------------


async def test_the_instant_is_the_ruling_and_never_the_emission(
    make_store: Callable[..., SqliteNotificationStore], sink: FakeTraceSink
) -> None:
    """§3: ``occurred_at`` is the single reading taken inside the atomic act.

    The clock here moves on every read, so an emitter that took one of its own
    would stamp an instant an hour later than the ruling. §8's windows are
    half-open on ``occurred_at``, so that gap is not cosmetic: a ruling near a
    boundary would land inside the window under one emitter and outside it under
    the other, and the two would report different interruption shares from one
    stream.
    """
    readings = iter([NOW, NOW + timedelta(hours=1)])

    store = make_store(now=lambda: next(readings))
    ruling = await store.admit(candidate(), policy=DefaultNotificationPolicy())

    assert ruling.ruled_at == NOW
    assert _only(sink).occurred_at == NOW


async def test_a_crossing_that_raised_carries_its_fault_and_none_of_the_metric_keys(
    make_store: Callable[..., SqliteNotificationStore], sink: FakeTraceSink
) -> None:
    """§3: the fault path binds on both sides of the ruling, and carries no key.

    An empty mapping rather than a mapping of zeros: §5 reads a trace carrying
    none of §4's keys as **incomplete** — the ordinary fault path — and a trace
    carrying some of them as a malformed emitter, so the two must not be spelled
    alike.
    """

    class _RaisingPolicy:
        async def rule(self, *args: object, **kwargs: object) -> NotificationDisposition:
            msg = "the policy is broken"
            raise RuntimeError(msg)

    store = make_store()
    with pytest.raises(RuntimeError):
        await store.admit(candidate(), policy=_RaisingPolicy())

    trace = _only(sink)
    assert trace.outcome is TraceOutcome.FAULT
    assert trace.fault_class == "RuntimeError"
    assert trace.metrics == {}
    assert trace.occurred_at == NOW


async def test_a_disposition_the_transaction_rolled_back_carries_no_metric_key(
    make_store: Callable[..., SqliteNotificationStore], sink: FakeTraceSink
) -> None:
    """§3: the fault path is bounded by the **commit** and not by the ruling.

    ADR-0130 §5 spends a unit of budget "exactly when an ``INTERRUPT`` is
    recorded", so a disposition the transaction rolled back cost the user nothing
    and reached nobody. Counting its keys would put an interruption in §6's
    numerator that no record reflects — the measure would be about what the policy
    decided rather than about what happened.
    """
    store = make_store()
    await store.set_preferences(_interrupting())

    def raising(conn: sqlite3.Connection, record: HeldNotification) -> None:
        msg = "disk I/O error"
        raise sqlite3.OperationalError(msg)

    store._write = raising  # type: ignore[method-assign]
    with pytest.raises(NotificationStoreError):
        await store.admit(_perishable(), policy=DefaultNotificationPolicy())

    trace = _only(sink)
    assert trace.outcome is TraceOutcome.FAULT
    assert trace.metrics == {}
    assert await store.export() == []


async def test_a_reconsideration_that_raised_carries_its_fault_at_its_own_seam(
    make_store: Callable[..., SqliteNotificationStore], sink: FakeTraceSink
) -> None:
    """§3's fault clause reaches the second seam, and it is not the first's.

    Both ruling seams owe the same trace on the same terms — the clause is
    written over "a crossing", not over ``admit`` — and the seam label is what
    §5's two sub-populations are drawn by, so a fault trace landing under the
    wrong label would move a diagnostic rather than merely read oddly.
    """

    class _RaisingPolicy:
        async def rule(self, *args: object, **kwargs: object) -> NotificationDisposition:
            msg = "the policy is broken"
            raise RuntimeError(msg)

    clock = MutableClock()
    store = make_store(now=clock)
    ruling = await _held_behind_a_quiet_window(store, clock)
    assert ruling.notification_id is not None

    with pytest.raises(RuntimeError):
        await store.reconsider(ruling.notification_id, policy=_RaisingPolicy())

    trace = sink.recorded[-1]
    assert trace.seam == SEAM_RECONSIDER
    assert trace.outcome is TraceOutcome.FAULT
    assert trace.fault_class == "RuntimeError"
    assert trace.metrics == {}
    assert trace.occurred_at == clock.at
    held = await store.get(ruling.notification_id)
    assert held is not None
    assert held.kind is NotificationDispositionKind.HOLD


async def test_a_reconsideration_the_transaction_rolled_back_carries_no_metric_key(
    make_store: Callable[..., SqliteNotificationStore], sink: FakeTraceSink
) -> None:
    """§3: on this seam too, a re-ruling that never committed is not a ruling.

    A reconsideration ruled ``INTERRUPT`` spends a unit of budget like any other
    ruling (ADR-0130 §5), so the window between the policy returning and the
    commit is where the same three readings of a ruling-bounded clause would
    diverge. The record is left holding its previous disposition, and the trace
    says a crossing happened and nothing about what it decided.
    """
    clock = MutableClock()
    store = make_store(now=clock)
    ruling = await _held_behind_a_quiet_window(store, clock)
    assert ruling.notification_id is not None

    def raising(conn: sqlite3.Connection, record: HeldNotification) -> None:
        msg = "disk I/O error"
        raise sqlite3.OperationalError(msg)

    store._write = raising  # type: ignore[method-assign]
    with pytest.raises(NotificationStoreError):
        await store.reconsider(ruling.notification_id, policy=DefaultNotificationPolicy())

    trace = sink.recorded[-1]
    assert trace.seam == SEAM_RECONSIDER
    assert trace.outcome is TraceOutcome.FAULT
    assert trace.metrics == {}
    held = await store.get(ruling.notification_id)
    assert held is not None
    assert held.kind is NotificationDispositionKind.HOLD
    assert held.ruled_at == NOW


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("refused-reading", NotificationStoreError), ("raising-invocation", RuntimeError)],
    ids=["a-reading-the-guard-refuses", "an-invocation-that-raises"],
)
async def test_a_crossing_that_obtained_no_reading_emits_nothing_and_is_logged(
    make_store: Callable[..., SqliteNotificationStore],
    sink: FakeTraceSink,
    mode: str,
    expected: type[Exception],
) -> None:
    """§3: both of ``checked_clock``'s failure modes, and one consequence.

    The guard refuses a non-conforming *reading* with ``ClockReadingError`` and
    lets an exception from the *invocation* propagate unwrapped, deliberately, so
    that relabelling the clock's own failure does not destroy its type and its
    cause. The clause is written over what the emitter lacks rather than over
    which of the two raised, because the consequence is identical: no instant, and
    ``occurred_at`` is not optional. Dropping the trace silently is what ADR-0119
    §5 refuses outright and stamping a wall clock the guard has just rejected
    would put a fabricated instant in a window, so it is logged as a lost trace.
    """

    def naive() -> datetime:
        """A reading the guard refuses, raising ``ClockReadingError`` of its own."""
        return datetime(2026, 8, 11, 12, 0)  # noqa: DTZ001 — naive on purpose

    def raising() -> datetime:
        """An invocation that fails, which the guard lets past unwrapped."""
        msg = "the clock is unreachable"
        raise RuntimeError(msg)

    store = make_store(now=naive if mode == "refused-reading" else raising)

    with structlog.testing.capture_logs() as captured, pytest.raises(expected):
        await store.admit(candidate(), policy=DefaultNotificationPolicy())

    assert sink.recorded == ()
    assert [record["event"] for record in captured] == [traces.TRACE_NOT_RECORDED]
    (record,) = captured
    assert record["kind"] == TraceKind.NOTIFICATION
    assert record["seam"] == SEAM_ADMIT


async def test_a_reconsideration_that_obtained_no_reading_emits_nothing_and_is_logged(
    make_store: Callable[..., SqliteNotificationStore], sink: FakeTraceSink
) -> None:
    """§3's no-reading clause reaches the second seam, on its own label.

    The store reads its clock first and inside the act on both seams, so a
    reconsideration that cannot obtain an instant is in exactly the position an
    admission is: nothing to stamp, and a lost trace rather than a silent drop or
    a fabricated instant.
    """
    clock = _BreakingClock()
    store = make_store(now=clock)
    ruling = await _held_behind_a_quiet_window(store, clock)
    assert ruling.notification_id is not None
    clock.naive = True

    with structlog.testing.capture_logs() as captured, pytest.raises(NotificationStoreError):
        await store.reconsider(ruling.notification_id, policy=DefaultNotificationPolicy())

    assert [trace.seam for trace in sink.recorded] == [SEAM_ADMIT]
    assert [record["event"] for record in captured] == [traces.TRACE_NOT_RECORDED]
    (record,) = captured
    assert record["seam"] == SEAM_RECONSIDER


async def test_a_cancellation_arriving_as_a_clock_read_writes_nothing_at_all(
    make_store: Callable[..., SqliteNotificationStore], sink: FakeTraceSink
) -> None:
    """§3: cancellation outranks the no-reading clause where the two meet.

    ``checked_clock`` lets a ``BaseException`` from the invocation propagate along
    with everything else, so a shutdown can arrive at this seam as a clock read
    that produced nothing. Read without the precedence clause the two rules
    collide: the no-reading clause says log a lost trace, ADR-0119 §5 says that
    record names the failure's class, and ADR-0119 §3 forbids deriving one from a
    cancellation — so an operator's log would carry a notification-seam failure
    every time the hub stops. Nothing is written for it, and it costs nothing,
    because a cancelled read has no event to be lost.
    """
    clock = _BreakingClock()
    store = make_store(now=clock)
    ruling = await _held_behind_a_quiet_window(store, clock)
    assert ruling.notification_id is not None
    clock.failure = asyncio.CancelledError()

    with structlog.testing.capture_logs() as captured, pytest.raises(asyncio.CancelledError):
        await store.reconsider(ruling.notification_id, policy=DefaultNotificationPolicy())

    assert [trace.seam for trace in sink.recorded] == [SEAM_ADMIT]
    assert captured == []


async def test_a_cancellation_writes_neither_a_trace_nor_a_lost_trace_record(
    make_store: Callable[..., SqliteNotificationStore], sink: FakeTraceSink
) -> None:
    """§3: cancellation outranks both the fault clause and the lost-trace rule.

    ADR-0119 §5's lost-trace record names the failure's class and ADR-0119 §3
    forbids deriving one from a cancellation, so writing it would classify a
    shutdown — and an operator's log would carry a notification-seam failure every
    time the hub stops. Nothing is written for one, and it costs nothing, because
    a cancelled crossing has no event to be lost.
    """
    reached = asyncio.Event()

    class _ParkingPolicy:
        async def rule(self, *args: object, **kwargs: object) -> NotificationDisposition:
            reached.set()
            await asyncio.Event().wait()
            raise AssertionError

    store = make_store()
    with structlog.testing.capture_logs() as captured:
        parked = asyncio.create_task(store.admit(candidate(), policy=_ParkingPolicy()))
        await reached.wait()
        parked.cancel()
        with pytest.raises(asyncio.CancelledError):
            await parked

    assert sink.recorded == ()
    assert captured == []


async def test_a_sink_that_raises_costs_the_trace_and_never_the_ruling(
    tmp_path: Path,
) -> None:
    """§3's subordination, on the seam where propagating instead would be worst.

    A sink call inside the ruling transaction would let a trace-store fault roll
    back a committed disposition — spending nothing and telling nobody, which is
    the exact inversion of "the instrument is subordinate to the work it
    observes".
    """

    class _RaisingSink:
        async def emit(self, trace: EvaluationTrace) -> None:
            msg = "the store is unavailable"
            raise TraceStoreError(msg)

    store = SqliteNotificationStore(
        path=tmp_path / "n.db", traces_sink=_RaisingSink(), now=MutableClock()
    )
    try:
        with structlog.testing.capture_logs() as captured:
            ruling = await store.admit(candidate(), policy=DefaultNotificationPolicy())

        assert ruling.kind is NotificationDispositionKind.HOLD
        assert len(await store.held()) == 1
    finally:
        store.close()

    assert [record["event"] for record in captured] == [traces.TRACE_NOT_RECORDED]


# --- what travels, and what may not ------------------------------------------


async def test_a_reading_that_raises_costs_the_trace_and_never_the_ruling(
    make_store: Callable[..., SqliteNotificationStore],
    sink: FakeTraceSink,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§3's subordination reaches a bug in this package's own reading.

    ADR-0119 §5 admits no exception for first-party code, and the whole trace is
    lost rather than a keyless one recorded: §5 of ADR-0141 reads a trace carrying
    none of §4's keys as a crossing that never reached its ruling, and this one
    did.
    """

    def raising(**kwargs: object) -> dict[str, int | float]:
        msg = "the reading is broken"
        raise ZeroDivisionError(msg)

    # Patched where the store *reads* it: the seam imported the name, so
    # rebinding it in the emitting module would leave the call site untouched.
    monkeypatch.setattr(notification_store, "ruling_metrics", raising)
    store = make_store()

    with structlog.testing.capture_logs() as captured:
        ruling = await store.admit(candidate(), policy=DefaultNotificationPolicy())

    assert ruling.kind is NotificationDispositionKind.HOLD
    assert len(await store.held()) == 1
    assert sink.recorded == ()
    assert [record["event"] for record in captured] == [traces.TRACE_NOT_RECORDED]


async def test_the_correlation_is_carried_where_there_is_one(
    make_store: Callable[..., SqliteNotificationStore], sink: FakeTraceSink
) -> None:
    """§3, on ADR-0119 §4: the ambient value is read, never minted here."""
    store = make_store()

    with correlated_operation() as correlation:
        await store.admit(candidate(), policy=DefaultNotificationPolicy())

    assert _only(sink).refs[TraceRef.CORRELATION] == correlation


async def test_a_ruling_outside_an_operation_omits_the_reference_rather_than_inventing_one(
    make_store: Callable[..., SqliteNotificationStore], sink: FakeTraceSink
) -> None:
    """ADR-0119 §4: "``None`` is the honest answer outside an operation".

    A reconsideration sweep and a producer's tick both reach this seam from a
    scheduler job, so the reference is genuinely absent rather than merely
    unusual.
    """
    store = make_store()

    await store.admit(candidate(), policy=DefaultNotificationPolicy())

    assert _only(sink).refs == {}


async def test_nothing_about_the_notification_travels(
    make_store: Callable[..., SqliteNotificationStore], sink: FakeTraceSink
) -> None:
    """§4's last clause: what was decided and on what conditions, and nothing else.

    Written as a prohibition rather than left to the type, because a summary is
    literally what the user would be shown, and a class or a producer name looks
    enum-shaped from a distance while being a producer-declared string.
    """
    store = make_store()

    ruling = await store.admit(
        candidate(key="a-candidate-key", notification_class="calendar"),
        policy=DefaultNotificationPolicy(),
    )

    trace = _only(sink)
    assert trace.records == {}
    assert set(trace.metrics) <= {
        *DISPOSITION_METRICS.values(),
        *CONDITION_METRICS.values(),
        HELD_SECONDS,
    }
    rendered = trace.model_dump_json()
    for secret in ("a-candidate-key", "a-producer", "calendar", "something the user did not ask"):
        assert secret not in rendered
    assert ruling.notification_id is not None
    assert ruling.notification_id not in rendered


# --- the literals -------------------------------------------------------------


def test_every_seam_and_metric_key_is_a_representable_label() -> None:
    """ADR-0119 §2: a key is a literal constant, and the type bounds its shape."""
    for label in (
        SEAM_ADMIT,
        SEAM_RECONSIDER,
        HELD_SECONDS,
        *DISPOSITION_METRICS.values(),
        *CONDITION_METRICS.values(),
    ):
        assert _LABEL.validate_python(label) == label


def test_the_disposition_keys_are_total_over_the_enumeration() -> None:
    """A kind added later fails here rather than dropping a count silently."""
    assert set(DISPOSITION_METRICS) == set(NotificationDispositionKind)


def test_the_condition_keys_are_total_over_the_enumeration() -> None:
    """A condition added later fails here rather than shrinking a denominator."""
    assert set(CONDITION_METRICS) == set(NotificationCondition)


def test_the_key_roster_is_the_eleven_keys_the_adr_names() -> None:
    """§4's roster, spelled out once so a rename is caught by the text and not by use."""
    assert sorted(DISPOSITION_METRICS.values()) == ["ruled_drop", "ruled_hold", "ruled_interrupt"]
    assert sorted(CONDITION_METRICS.values()) == [
        "condition_at_cap",
        "condition_budget",
        "condition_duplicate",
        "condition_expired",
        "condition_perishable",
        "condition_quiet_window",
        "condition_reach_interrupt",
        "condition_reach_off",
    ]
    assert HELD_SECONDS == "held_seconds"
    assert notification_traces.SEAM_ADMIT == "notification_admit"
    assert notification_traces.SEAM_RECONSIDER == "notification_reconsider"
