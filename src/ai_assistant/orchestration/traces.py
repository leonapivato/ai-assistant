"""ADR-0119 §8's engine-boundary emitter: one ``OPERATION`` trace per engine call.

§8 puts this at one place and says why: "``Engine._tracked`` already wraps every
public method, so the operation's name, its outcome, its elapsed time and its
fault class are all in hand at one place, for a turn, a scheduled job and a
client command alike". That is three of the dispatch's five seams behind one
wiring point, and it follows from ADR-0083 §8's ruling that "every scheduler job
is a public ``Engine`` call" — a consolidation run, a retention purge and a
user's turn are one kind of event distinguished by the seam label and the
outcome, not three kinds needing three emitters.

**Everything here is subordinate to the work it observes** (§5). No trace failure
propagates: not a clock that will not read, not a label that will not validate,
not a store that will not write. What a lost trace costs is a Tier 2 log record
naming the kind, the seam and the failure's class, because "a missing trace is
indistinguishable from a non-event" and silence is the specific way an instrument
lies.

**A job's detail rides as metrics on this one trace and never as a second
record** (§5's one-crossing rule, §8's engine-boundary paragraph): "a job with
detail the envelope cannot see returns it in the operation's own result type,
where it becomes metrics on that operation's one trace". :class:`Observation` is
that route — the caller supplies a reading of its own result type, and the
reading is taken inside the guarded path, so a mapper that raises costs the trace
and never the run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta
from time import perf_counter
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.correlation import correlated_operation
from ai_assistant.core.errors import (
    OversizedValueError,
    PermissionDeniedError,
    SourceNotGrantedError,
    UngrantableSourceError,
    UnknownConversationError,
)
from ai_assistant.core.types import (
    EvaluationTrace,
    TraceKind,
    TraceOutcome,
    TraceRef,
    fault_class_of,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import TraceSink
    from ai_assistant.core.types import UtcInstant

_log = structlog.get_logger(__name__)

#: The event name an emission failure is logged under (ADR-0119 §5). Duplicated
#: from ``ai_assistant.evaluation``'s durable store rather than imported, for the
#: reason the canonical fakes duplicate it too: golden rule 1 forbids
#: ``orchestration`` naming another subsystem's concrete module, and a shared
#: constant here would be exactly that import. An operator greps one string and
#: finds every lost trace, whichever side lost it.
TRACE_NOT_RECORDED: Final = "trace_not_recorded"

#: What the log record carries in place of a seam that is not a representable
#: label, so an unvalidated string never reaches a Tier 2 log (ADR-0004 §5).
#: Duplicated from the durable store for :data:`TRACE_NOT_RECORDED`'s reason.
UNREADABLE_TRACE_FIELD: Final = "unreadable"

#: The seam pattern, duplicated from ``core/types.py``'s private ``_TRACE_LABEL``
#: for the one use :func:`_dropped` has for it. Importing the original would be
#: reaching into another module's internals for a two-token regex, and the
#: duplication is checked by a test that builds a trace with a seam this accepts.
_SEAM_LABEL: Final = re.compile(r"[a-z][a-z0-9_]{0,63}")

#: The exception classes this surface raises to mean **"no, and that is the right
#: answer"**, as against "something broke".
#:
#: ADR-0111 §9 hands this list to the implementing lane by name — "which classes
#: are refusals is the implementing lane's list, and it is short today:
#: ``SourceNotGrantedError`` is the one ADR-0097 §5 names… Whether the
#: discriminator is a marker base class or an explicit tuple is a code decision
#: this ADR does not take". An explicit tuple, because the corpus has no refusal
#: marker to inherit from and inventing one would touch every class in
#: ``core/errors.py`` for a telemetry distinction.
#:
#: **It fails towards ``FAULT``**, deliberately: an unlisted class is recorded as
#: a fault, so a refusal nobody classified looks noisier than it is, and a fault
#: nobody classified never looks quieter than it is. Under-reporting a fault is
#: the direction that costs an operator something.
#:
#: **The membership test is ``isinstance``, so a subclass inherits its parent's
#: reading.** That runs the right way — a narrower refusal is still a refusal —
#: and it is why the tuple names no class whose subclasses include faults.
#: ``UnknownConversationError`` is a ``ConversationStoreError`` and only the
#: subclass is listed, so a store that genuinely broke is still a fault: the same
#: distinction ADR-0083 §6 draws between "this deployment cannot serve this
#: store" and "this disk is broken".
_REFUSALS: Final[tuple[type[Exception], ...]] = (
    # ADR-0097 §5: an ungranted source "logs a refusal every interval, and that
    # is the correct behaviour rather than a defect to design around". The one
    # class ADR-0111 §9 names.
    SourceNotGrantedError,
    # A source the deployment cannot grant is answered, not broken.
    UngrantableSourceError,
    # The gate declining is the gate working (ADR-0021).
    PermissionDeniedError,
    # A caller naming a conversation that does not exist is told so.
    UnknownConversationError,
    # ADR-0084 §4's payload limit refuses in both directions, and a value that
    # does not fit the contract is an answer rather than a malfunction. Reached
    # inside the traced region because ``Engine._tracked`` applies the check to
    # the result there (``checked=True``), so the trace and the caller agree.
    OversizedValueError,
)


@dataclass(frozen=True, slots=True)
class Observation:
    """A reading of an operation's own result, for the one trace it rides on.

    ADR-0119 §8 routes a job's detail here rather than into a second record: the
    result type carries what the envelope cannot see, and the caller turns it
    into numbers on the operation's own trace.

    Attributes:
        outcome: ``OK``, or ``INCOMPLETE`` for ADR-0111 §9's third clause — "a run
            that halts under §5 without processing its remaining work is recorded
            as a completed run that did not exhaust its work, not as a failure".
            ADR-0119 §3 calls ``INCOMPLETE`` exactly that clause "given a value".
        metrics: Numbers and booleans the run observed, under keys that are
            literal constants in the module supplying them (§2's second clause).
            A quantity the run did not reach is **absent**, never zero (§3's
            observation rule).
    """

    outcome: TraceOutcome = TraceOutcome.OK
    metrics: Mapping[str, int | float | bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Refuse an outcome naming a failure no exception decided.

        ``REFUSED`` and ``FAULT`` are drawn *from* an exception's class (§3), so a
        result-derived reading cannot produce one: the operation returned.
        :class:`~ai_assistant.core.types.EvaluationTrace` would refuse the pair
        anyway — a failing outcome with no ``fault_class`` — but it would refuse
        it by losing the trace, and a mapper's bug should be a mapper's test
        failure rather than a hole in the stream.

        Raises:
            ValueError: If ``outcome`` is ``REFUSED`` or ``FAULT``.
        """
        if self.outcome in (TraceOutcome.REFUSED, TraceOutcome.FAULT):
            msg = f"a returned result cannot be {self.outcome}; only an exception decides one"
            raise ValueError(msg)


#: What an operation with nothing to add says: it completed, and observed no
#: quantity the envelope did not already carry.
_COMPLETED: Final = Observation()


class OperationTraces:
    """Emits the ``OPERATION`` trace for one ``AssistantEngine`` call (ADR-0119 §8).

    Held by the ``Engine`` and driven from ``_tracked``, so every public method is
    covered by one wiring point rather than by twenty-three decorators that can be
    forgotten one at a time.
    """

    def __init__(self, *, sink: TraceSink, now: Clock) -> None:
        """Wire the emitter to its seam and its clock.

        Args:
            sink: The trace store's **append** seam — a
                :class:`~ai_assistant.core.protocols.TraceSink` and never a
                ``TraceStore``, because ADR-0119 §7 gives an emitter the write and
                withholds the walk: "no component of the request pipeline… holds a
                seam carrying the walk, and none reads a trace back". The
                narrowing is this annotation, exactly as ADR-0097 §5 narrows a
                driver to ``SourceGrants``.

                **Required with no default**, which §7 states as a clause of its
                own: "a composition that omits it does not type-check". An
                optional sink defaults to unwired, an unwired emitter produces no
                traces, "and no traces is indistinguishable from no events — the
                same lie §5 refuses, arriving through composition instead of
                through I/O".
            now: The clock the instant is stamped from. §3 puts the stamp on the
                emitter rather than on the store, because a store stamping on
                append "would measure the write rather than the event — wrong for
                any latency figure, and wrong again if a sink ever buffers".
                Guarded by :func:`~ai_assistant.core.clock.checked_clock`
                (ADR-0026 §7) like every other injected clock, so a naive or
                unlocalizable reading is refused here rather than stored.
        """
        self._sink = sink
        self._now = checked_clock(now, owner="OperationTraces")

    async def observing[T](
        self,
        seam: str,
        work: Awaitable[T],
        observe: Callable[[T], Observation] | None = None,
    ) -> T:
        """Run ``work`` under a fresh correlation scope and record one trace for it.

        **The scope opens here and not at the call site**, because this is the
        boundary §4 means by "one ``AssistantEngine`` operation": every trace any
        subsystem emits while this awaits — a ``RETRIEVAL`` inside a turn, a
        ``MEMORY_WRITE`` inside a consolidation chunk — reads the same identifier
        out of the context and joins to this one.

        **A cancellation is never classified** (§3, ADR-0060 §1). ``except
        Exception`` does not catch ``CancelledError``, which is a
        ``BaseException``, so an externally delivered cancellation leaves here
        untouched and no trace records it. That is stated rather than written as a
        re-raising handler, which would be dead code.

        **The trace is written inside the awaited work, after it finishes.** Two
        consequences, both wanted. The engine drains this task before it closes
        the stores (ADR-0042 §2), so the append cannot race the trace store's
        close; and a caller who cancels the shielded await still gets a trace for
        the work that kept running, which is what the shield is for. The accepted
        cost is the mirror of the first: a shutdown reaching phase B's
        cancellation *between* the work finishing and the append delivers the
        cancellation onward, as ADR-0060 §1 requires, and the completed result is
        discarded with it — the same window every other trailing await in a
        tracked task already has, one small local write wide.

        Args:
            seam: The operation's name — a literal constant at the call site, and
                the label a measure filters on (§2's second clause, §3's label
                pattern).
            work: The operation itself.
            observe: How to read the operation's own result into the trace, or
                ``None`` for an operation whose envelope is the whole story.

        Returns:
            Whatever ``work`` returned, untouched.
        """
        with correlated_operation() as correlation:
            # The clock first and the monotonic reading second, so ``elapsed``
            # measures the work rather than the work plus a clock read — §3 cares
            # which instant a record means, and it cares for latency's sake.
            occurred_at = self._stamped(seam)
            started = perf_counter()
            try:
                result = await work
            except Exception as error:
                await self._record(
                    seam,
                    occurred_at=occurred_at,
                    started=started,
                    correlation=correlation,
                    outcome=_outcome_of(error),
                    fault_class=fault_class_of(error),
                )
                raise
            observation = self._observed(seam, result, observe)
            await self._record(
                seam,
                occurred_at=occurred_at,
                started=started,
                correlation=correlation,
                outcome=observation.outcome,
                metrics=observation.metrics,
            )
            return result

    def _stamped(self, seam: str) -> UtcInstant | None:
        """The instant the operation began, or ``None`` if the clock would not read.

        Read **before** the work, so ``occurred_at`` is the operation's start and
        ``occurred_at`` plus ``elapsed`` is its interval — which is what lets this
        trace bound the traces emitted inside it, the join §4 exists for.

        A clock that raises costs the trace and not the run (§5), so the failure
        is logged here and the absence travels to :meth:`_record`, which has no
        trace to write without an instant.

        Args:
            seam: The operation's name, for the log record.

        Returns:
            The reading, or ``None``.
        """
        try:
            return self._now()
        # Broad by design: §5 lets no clock fault reach the work being observed.
        except Exception as error:
            _dropped(seam, error)
            return None

    def _observed[T](
        self, seam: str, result: T, observe: Callable[[T], Observation] | None
    ) -> Observation:
        """Read ``result`` through ``observe``, or fall back to the bare envelope.

        A mapper is first-party code in this package, so a raise here is a bug
        rather than an environmental failure — but §5 admits no exception for
        first-party bugs, and losing a run because its counters would not convert
        is exactly the inversion that clause forbids.

        Args:
            seam: The operation's name, for the log record.
            result: What the operation returned.
            observe: The reading, or ``None``.

        Returns:
            The reading, or a bare completion.
        """
        if observe is None:
            return _COMPLETED
        try:
            return observe(result)
        # Broad by design: §5 lets no mapper bug reach the work being observed.
        except Exception as error:
            _dropped(seam, error)
            return _COMPLETED

    async def _record(  # noqa: PLR0913 — one parameter per field of the one trace
        self,
        seam: str,
        *,
        occurred_at: UtcInstant | None,
        started: float,
        correlation: str,
        outcome: TraceOutcome,
        fault_class: str | None = None,
        metrics: Mapping[str, int | float | bool] | None = None,
    ) -> None:
        """Build the trace and append it, letting nothing out (ADR-0119 §5).

        Construction is guarded as well as emission, because §2's constraints are
        enforced *at construction*: a seam label that does not match the pattern,
        a metric key a mapper derived from data, a non-finite score. Each is an
        emitter bug, and each must cost a trace rather than an operation.

        ``elapsed`` comes from :func:`time.perf_counter` rather than from the
        clock: it is a duration, and a wall clock stepping backwards mid-operation
        would produce a negative one the model refuses (``ge=timedelta(0)``),
        losing the trace to a fact about the machine's clock rather than about the
        run.

        Args:
            seam: The operation's name.
            occurred_at: When it began, or ``None`` if the clock would not read —
                in which case there is nothing to write and the loss is already
                logged.
            started: The monotonic reading taken at the same moment.
            correlation: The operation's identifier, carried under
                :data:`~ai_assistant.core.types.TraceRef.CORRELATION` so §4's join
                has its key.
            outcome: What the operation did.
            fault_class: The class of the exception that decided a failing
                outcome, through §3's total conversion; ``None`` otherwise.
            metrics: What the result observed, or ``None`` for nothing.
        """
        if occurred_at is None:
            return
        try:
            trace = EvaluationTrace(
                kind=TraceKind.OPERATION,
                seam=seam,
                occurred_at=occurred_at,
                elapsed=timedelta(seconds=max(perf_counter() - started, 0.0)),
                outcome=outcome,
                fault_class=fault_class,
                refs={TraceRef.CORRELATION: correlation},
                metrics=metrics if metrics is not None else {},
            )
        # Broad by design: §5 makes a malformed trace a lost trace, not a failed run.
        except Exception as error:
            _dropped(seam, error)
            return
        try:
            await self._sink.emit(trace)
        # Broad by design: §7 says a conforming sink cannot raise here, and §5 says
        # what to do if one does anyway.
        except Exception as error:
            _dropped(seam, error)


def _outcome_of(error: Exception) -> TraceOutcome:
    """``REFUSED`` or ``FAULT``, **by the exception's class** and never its message.

    ADR-0119 §3 binds this to the same discriminator ADR-0111 §9 binds the
    scheduler's log record to, "so the two records about one event cannot
    disagree". ADR-0083 §6 records what the alternative cost: without a class, an
    entry point "cannot tell 'this deployment cannot serve this store' from 'this
    disk is broken' without matching on a message string".

    Args:
        error: What the operation raised.

    Returns:
        The outcome its class decides.
    """
    return TraceOutcome.REFUSED if isinstance(error, _REFUSALS) else TraceOutcome.FAULT


def _dropped(seam: str, error: Exception) -> None:
    """Log a trace that could not be recorded (ADR-0119 §5).

    "Emission failure is never silent", because "a measure over a stream with
    dropped rows reports a smaller numerator and does not know it". The three keys
    are Tier 2 by construction: the kind is fixed, the seam is bounded by the same
    pattern the type enforces, and the error's **class** goes through §3's total
    conversion rather than being read raw — a provider may raise ``type("X" * 65,
    (Exception,), {})``, and ADR-0004 §5 is unconditional that logs are Tier 2
    only, so the bound §2 puts on a trace's ``fault_class`` has to hold on this
    side of the seam too. The message never appears.

    Args:
        seam: The operation's name.
        error: Why the trace was not recorded.
    """
    _log.warning(
        TRACE_NOT_RECORDED,
        kind=str(TraceKind.OPERATION),
        seam=seam if _SEAM_LABEL.fullmatch(seam) else UNREADABLE_TRACE_FIELD,
        error_class=fault_class_of(error),
    )


__all__ = [
    "TRACE_NOT_RECORDED",
    "UNREADABLE_TRACE_FIELD",
    "Observation",
    "OperationTraces",
]
