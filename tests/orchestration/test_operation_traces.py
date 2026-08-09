"""ADR-0119 §8's engine-boundary emitter, against the seam rather than the engine.

The wiring — that every public method reaches this, under the seam label its own
name carries — is pinned in ``test_engine.py``, which is where the engine is.
What is pinned here is the emitter's own contract: what a trace carries, which
outcome an exception decides, and the four ways §5's subordination has to hold
when the instrument itself is what fails.

**Subordination is the half worth over-testing.** Every other property of this
module shows up as a wrong number in a measure nobody is reading yet; a breach of
§5 shows up as a turn the user did not get, and it shows up in production.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import structlog

from ai_assistant.core.clock import ClockReadingError
from ai_assistant.core.correlation import current_correlation
from ai_assistant.core.errors import (
    ConversationStoreError,
    MemoryStoreError,
    PermissionDeniedError,
    SourceNotGrantedError,
    TraceStoreError,
    UnknownConversationError,
)
from ai_assistant.core.types import (
    UNREPRESENTABLE_FAULT_CLASS,
    EvaluationTrace,
    TraceKind,
    TraceOutcome,
    TraceRef,
)
from ai_assistant.orchestration.traces import (
    _SEAM_LABEL,
    TRACE_NOT_RECORDED,
    UNREADABLE_TRACE_FIELD,
    Observation,
    OperationTraces,
)
from ai_assistant.testing import FakeTraceSink

_AT = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


class RaisingSink:
    """A sink that breaks its own contract by letting a fault escape ``emit``.

    ADR-0119 §7 says a conforming sink cannot do this — "no trace-store failure
    reaches the caller, and that is a contract obligation the conformance suite
    pins" — which is exactly why the emitter is tested against one that does. §5's
    clause is about the *operation*, and an operation must survive a collaborator
    that is wrong as well as one that is merely unlucky.
    """

    async def emit(self, trace: EvaluationTrace) -> None:
        """Raise instead of appending.

        Args:
            trace: Ignored.

        Raises:
            TraceStoreError: Always.
        """
        msg = "the sink is broken"
        raise TraceStoreError(msg)


def _emitter(sink: object, *, now: object = None) -> OperationTraces:
    """An emitter over ``sink``, stopped at :data:`_AT` unless a case says otherwise."""
    return OperationTraces(
        sink=sink,  # type: ignore[arg-type]  # a duck-typed fake stands in for the Protocol
        now=now if now is not None else (lambda: _AT),  # type: ignore[arg-type]
    )


async def _returns(value: int = 7) -> int:
    """Work that succeeds."""
    return value


# --- what the envelope carries (ADR-0119 §8) ----------------------------------


async def test_a_completed_operation_emits_one_trace_carrying_the_envelope() -> None:
    """Seam, kind, instant, elapsed, outcome — and exactly one record (§5, §8).

    "One crossing of a seam produces at most one trace, and two components may not
    both emit for one event", so the count is asserted as hard as the content.
    """
    sink = FakeTraceSink()

    assert await _emitter(sink).observing("converse", _returns()) == 7

    (trace,) = sink.recorded
    assert trace.kind is TraceKind.OPERATION
    assert trace.seam == "converse"
    assert trace.occurred_at == _AT
    assert trace.outcome is TraceOutcome.OK
    assert trace.fault_class is None
    assert trace.elapsed is not None
    assert trace.elapsed >= timedelta(0)


async def test_the_trace_carries_the_identifier_the_work_could_read() -> None:
    """§4's join, from both ends at once.

    The value on the envelope is the value a subsystem several awaits down reads
    out of the context — which is the whole of what makes "a measure over a pair of
    events computable from the stream alone" true. Asserting only that *some*
    identifier is present would pass with a carrier nothing below can see.
    """
    sink = FakeTraceSink()
    seen: list[str | None] = []

    async def work() -> None:
        seen.append(current_correlation())

    await _emitter(sink).observing("learn", work())

    (trace,) = sink.recorded
    assert seen == [trace.refs[TraceRef.CORRELATION]]


async def test_the_instant_is_the_operation_s_start() -> None:
    """``occurred_at`` bounds the traces emitted inside it, so it is the start.

    A ticking clock would give a completion stamp if the reading were taken after
    the work; §3 puts the stamp on the emitter precisely so the trace means the
    event, and the interval it names is ``occurred_at`` plus ``elapsed``.
    """
    sink = FakeTraceSink()
    readings = iter([_AT, _AT + timedelta(hours=1)])

    await _emitter(sink, now=lambda: next(readings)).observing("start", _returns())

    (trace,) = sink.recorded
    assert trace.occurred_at == _AT


# --- what an exception decides (ADR-0119 §3) ----------------------------------


async def test_a_faulting_operation_still_emits_and_still_raises() -> None:
    """ADR-0074's deferral, discharged: the failed turn is a Tier 2 record.

    "A turn that raises before producing an outcome is not captured… what failed is
    *operational* information — Tier 2, and the subject of leg 8's
    ``EvaluationTrace``." The exception is unchanged on its way out, because a
    trace is an observation and not an interception.
    """
    sink = FakeTraceSink()

    async def work() -> None:
        msg = "the store is gone"
        raise MemoryStoreError(msg)

    with pytest.raises(MemoryStoreError):
        await _emitter(sink).observing("converse", work())

    (trace,) = sink.recorded
    assert trace.outcome is TraceOutcome.FAULT
    assert trace.fault_class == "MemoryStoreError"


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (SourceNotGrantedError("no grant"), TraceOutcome.REFUSED),
        (PermissionDeniedError("denied"), TraceOutcome.REFUSED),
        (UnknownConversationError("no such conversation"), TraceOutcome.REFUSED),
        (MemoryStoreError("broken"), TraceOutcome.FAULT),
        (RuntimeError("something"), TraceOutcome.FAULT),
    ],
)
async def test_the_outcome_is_drawn_from_the_class(error: Exception, outcome: TraceOutcome) -> None:
    """ADR-0111 §9's discriminator, applied to the trace stream (ADR-0119 §3).

    The list is short and it fails towards ``FAULT``: the last two cases are the
    ones nobody classified, and each is recorded as a fault rather than quietly
    downgraded. ``RuntimeError`` is deliberately among them — the confirmation
    ceiling's backpressure refusal raises one, and §3 forbids reading the message
    that would distinguish it, so it counts as a fault until it has a class.
    """
    sink = FakeTraceSink()

    async def work() -> None:
        raise error

    with pytest.raises(type(error)):
        await _emitter(sink).observing("resume", work())

    assert sink.recorded[0].outcome is outcome


async def test_a_conversation_store_fault_is_not_a_refusal() -> None:
    """The subclass is listed and the parent is not, which is the point.

    ADR-0083 §6 records the cost of the alternative: an entry point that "cannot
    tell 'this deployment cannot serve this store' from 'this disk is broken'
    without matching on a message string". ``UnknownConversationError`` is a
    ``ConversationStoreError``, and only the narrow one reads as a refusal.
    """
    sink = FakeTraceSink()

    async def work() -> None:
        msg = "the index cannot be read"
        raise ConversationStoreError(msg)

    with pytest.raises(ConversationStoreError):
        await _emitter(sink).observing("conversation", work())

    assert sink.recorded[0].outcome is TraceOutcome.FAULT


async def test_an_unrepresentable_fault_class_costs_the_class_and_not_the_trace() -> None:
    """§3's total conversion, reached through the emitter rather than the type.

    "No exception a provider can raise may prevent a trace from being constructed."
    A dynamically built class with an over-long name is the case §2 names, and the
    refused name goes nowhere — not to the trace, not to the log.
    """
    sink = FakeTraceSink()
    exotic = type("X" * 65, (Exception,), {})

    async def work() -> None:
        raise exotic("boom")

    with pytest.raises(exotic):
        await _emitter(sink).observing("ingest", work())

    (trace,) = sink.recorded
    assert trace.outcome is TraceOutcome.FAULT
    assert trace.fault_class == UNREPRESENTABLE_FAULT_CLASS


async def test_a_cancellation_is_delivered_onward_and_never_classified() -> None:
    """ADR-0060 §1 and ADR-0119 §3, which agree: no trace records a cancellation.

    "An emitter re-raises an externally delivered ``CancelledError`` before any
    outcome or fault class is decided." The mechanism is that ``CancelledError`` is
    a ``BaseException``, so the emitter's broad ``except Exception`` cannot see it;
    the test is here because that is a property of a base class somebody could
    change to ``BaseException`` in a tidying pass.
    """
    sink = FakeTraceSink()

    async def work() -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await _emitter(sink).observing("converse", work())

    assert sink.recorded == ()


# --- the result's own detail rides on the one trace (ADR-0119 §5, §8) ---------


async def test_an_observation_rides_as_metrics_on_the_one_trace() -> None:
    """§5's one-crossing rule: detail becomes numbers here, not a second record."""
    sink = FakeTraceSink()

    def observe(value: int) -> Observation:
        return Observation(metrics={"examined": value})

    await _emitter(sink).observing("consolidate", _returns(3), observe)

    (trace,) = sink.recorded
    assert dict(trace.metrics) == {"examined": 3}


async def test_a_halted_run_is_incomplete() -> None:
    """ADR-0111 §9's third clause, given a value (ADR-0119 §3).

    A halt is "a completed run that did not exhaust its work, not as a failure",
    and the trace has to be able to say so without a ``fault_class`` — which the
    model's own validator would refuse if the outcome named a failure.
    """
    sink = FakeTraceSink()

    def observe(_: int) -> Observation:
        return Observation(outcome=TraceOutcome.INCOMPLETE)

    await _emitter(sink).observing("consolidate", _returns(), observe)

    (trace,) = sink.recorded
    assert trace.outcome is TraceOutcome.INCOMPLETE
    assert trace.fault_class is None


@pytest.mark.parametrize("outcome", [TraceOutcome.REFUSED, TraceOutcome.FAULT])
def test_an_observation_cannot_name_a_failure_no_exception_decided(
    outcome: TraceOutcome,
) -> None:
    """The operation returned, so a failing outcome is a mapper bug (§3).

    Refused at construction rather than at the trace, so it fails in the mapper's
    own test instead of arriving as a hole in the stream.
    """
    with pytest.raises(ValueError, match="only an exception decides one"):
        Observation(outcome=outcome)


# --- subordination: the instrument never touches the work (ADR-0119 §5) -------


async def test_a_sink_that_raises_costs_the_trace_and_not_the_result() -> None:
    """ "A failure to record a trace never propagates into the operation" (§5).

    And the loss is loud: "a trace that could not be recorded is logged as a Tier 2
    log record naming the kind, the seam and the failure's class. Emission failure
    is never silent", because a measure over a stream with dropped rows "reports a
    smaller numerator and does not know it".
    """
    with structlog.testing.capture_logs() as captured:
        assert await _emitter(RaisingSink()).observing("converse", _returns()) == 7

    (record,) = captured
    assert record["event"] == TRACE_NOT_RECORDED
    assert record["kind"] == "operation"
    assert record["seam"] == "converse"
    assert record["error_class"] == "TraceStoreError"


async def test_a_clock_that_will_not_read_costs_the_trace_and_not_the_result() -> None:
    """A mis-wired clock is an instrument fault, and §5 subordinates every one.

    ``purge_expired`` translates its own clock failure into a ``TraceStoreError``
    because the *horizon* depends on it (ADR-0026 §4); the trace's instant does
    not, so here the reading is guarded and its absence costs a record.
    """

    def broken() -> datetime:
        msg = "the reading is naive"
        raise ClockReadingError(msg)

    sink = FakeTraceSink()

    with structlog.testing.capture_logs() as captured:
        assert await _emitter(sink, now=broken).observing("start", _returns()) == 7

    assert sink.recorded == ()
    assert [record["event"] for record in captured] == [TRACE_NOT_RECORDED]


async def test_a_mapper_that_raises_costs_the_trace_and_not_the_result() -> None:
    """A first-party bug is still an instrument failure, and §5 has no exception.

    Losing a consolidation run because its counters would not convert is precisely
    the inversion of priority the clause forbids.
    """

    def observe(_: int) -> Observation:
        msg = "the mapper is wrong"
        raise ValueError(msg)

    sink = FakeTraceSink()

    with structlog.testing.capture_logs() as captured:
        assert await _emitter(sink).observing("consolidate", _returns(), observe) == 7

    # The trace survives the mapper: the envelope was never in doubt, and §3's
    # observation rule says an unobserved quantity is *absent* rather than zero.
    (trace,) = sink.recorded
    assert dict(trace.metrics) == {}
    assert [record["error_class"] for record in captured] == ["ValueError"]


async def test_a_seam_that_is_not_a_label_costs_the_trace_and_not_the_result() -> None:
    """An emitter bug caught by the type is still §5's problem, not the caller's.

    And the refused label does **not** reach the log: §2 bounds what a trace may
    carry, ADR-0004 §5 bounds a log identically ("logs are Tier 2 only"), and
    diverting the refused value "for debuggability" is the trap ADR-0119 §2 names
    one field over.
    """
    sink = FakeTraceSink()

    with structlog.testing.capture_logs() as captured:
        assert await _emitter(sink).observing("NOT A LABEL", _returns()) == 7

    assert sink.recorded == ()
    (record,) = captured
    assert record["seam"] == UNREADABLE_TRACE_FIELD
    assert "NOT A LABEL" not in str(record)


async def test_a_sink_whose_store_fails_still_returns_the_result() -> None:
    """The conforming case, for completeness: the sink swallows and the run stands.

    ``FakeTraceSink.fail_append`` models the environmental failure §5 subordinates
    — a locked database, a full disk — which a conforming sink absorbs on its own
    side. Nothing reaches the operation from either side of that seam.
    """
    sink = FakeTraceSink()
    sink.fail_append()

    assert await _emitter(sink).observing("forget", _returns()) == 7

    assert sink.recorded == ()


# --- the one pattern this module duplicates (ADR-0119 §3, §13a) ---------------


@pytest.mark.parametrize(
    "seam",
    [
        "seam",
        "purge_expired",
        "s",
        "a" * 64,
        "",
        "Seam",
        "1seam",
        "with space",
        "seam-dash",
        "a" * 65,
        # ``$`` matches *before* a trailing newline, which is why §13a's patterns
        # are applied with ``fullmatch``. A duplicate written with ``match`` and
        # ``$`` would admit this one and log an unbounded string.
        "seam\n",
    ],
)
def test_the_duplicated_seam_pattern_agrees_with_the_type(seam: str) -> None:
    """The log's bound must be the type's bound, or the log is the looser surface.

    :func:`~ai_assistant.orchestration.traces._dropped` cannot ask the model whether
    a seam was representable — the model is what failed — so it carries its own copy
    of §13a's ``_TRACE_LABEL``. A copy that drifted *looser* would put into a Tier 2
    log exactly the string the trace refused, which ADR-0119 §2 names as "the trap in
    the obvious fix" one field over, and ADR-0004 §5 forbids unconditionally.

    Asserted as agreement over both answers rather than by comparing the two
    patterns, so a rewrite of either in a different but equivalent form still passes
    and a change in what either *accepts* does not.
    """
    try:
        EvaluationTrace(
            kind=TraceKind.OPERATION, seam=seam, occurred_at=_AT, outcome=TraceOutcome.OK
        )
    # Any refusal is a refusal for this comparison; the type's own tests pin which.
    except Exception:
        accepted_by_type = False
    else:
        accepted_by_type = True

    assert bool(_SEAM_LABEL.fullmatch(seam)) is accepted_by_type
