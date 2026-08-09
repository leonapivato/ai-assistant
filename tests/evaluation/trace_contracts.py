"""Shared conformance suites for ADR-0119's three trace Protocols (§13d).

Every ``TraceSink`` implementation must pass :class:`TraceSinkContract`, every
``TraceRetention`` implementation :class:`TraceRetentionContract`, and every
``TraceStore`` implementation all three — the last because ``TraceStore`` extends
both narrow Protocols (§7), so a concrete that satisfies it satisfies them. A
concrete test subclasses what it implements and supplies its subject fixture.

**Three suites rather than one, and the cost is named rather than discovered.**
One Protocol would have cost one suite and one fake; the split costs three of
each, and it buys the property ADR-0119 §7 is built on — an emitter *cannot name*
:meth:`walk`, which is ``mypy --strict`` holding a clause instead of review. Part
of the cost comes back as evidence: the store binding runs the narrow suites too,
so "one concrete implements all three" is a test rather than an assertion.

**Here rather than under ``tests/core/``.** The corpus puts a suite beside the
package that implements it, and ADR-0119 §6 puts the implementation in
``evaluation/``. The Protocols stay in ``core``, which is what lets an emitter
hold ``TraceSink`` by injection without importing this package.

**What is deliberately not in here**, restated so its absence does not read as
absence from the contract. The test is whether a clause is decidable from a
store's own surface:

* **§2's tier clauses.** Properties of :class:`EvaluationTrace`, held by the type
  and proved by ``tests/core/test_trace_string_closure.py``'s graph walk. No
  store exhibits them; a store handed a conforming trace cannot make it
  non-conforming, and one handed a non-conforming trace never sees it — the model
  refused it at construction.
* **§7's rule that no pipeline component holds the walk.** A statement about what
  a *different* package may name, held by ``lint-imports`` and by the seam split.
* **§8's "which seams emit and what each must carry".** The emitters' own lane's
  (§13d puts them after this one); nothing in a store's return value exhibits it.
* **§4's correlation carrier.** Also a later lane's, and ambient to a request
  rather than visible here.
* **§10's "no count cap".** An absence, and the suites below assert the positive
  half — only age deletes a trace — by purging on a horizon and finding an old
  trace gone and a new one present however many are held.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract bases directly.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
import structlog

from ai_assistant.core.errors import TraceStoreError
from ai_assistant.core.types import (
    EvaluationTrace,
    RecordIdSet,
    TraceKind,
    TraceOutcome,
    TracePosition,
    TraceRecordSet,
)
from ai_assistant.testing import DEFAULT_OCCURRED_AT, TRACE_NOT_RECORDED, evaluation_trace
from ai_assistant.testing.cancellation import settle

if TYPE_CHECKING:
    from collections.abc import Coroutine, Mapping, Sequence
    from contextlib import AbstractAsyncContextManager

    from ai_assistant.core.protocols import TraceRetention, TraceSink, TraceStore
    from ai_assistant.testing.cancellation import SuspendedMidWrite

#: What a failure of a cancellation case means, in one place: every assertion in
#: it is the same invariant seen from a different side.
_RELEASED_EARLY = (
    "the cancelled call released its resource while its own work was still using it (ADR-0060 §3)"
)

#: An hour before and an hour after :data:`DEFAULT_OCCURRED_AT`, so a retention
#: case can say "older" and "newer" without inventing a calendar.
_EARLIER = DEFAULT_OCCURRED_AT - timedelta(hours=1)
_LATER = DEFAULT_OCCURRED_AT + timedelta(hours=1)

#: A position token no conforming store's own encoding can have issued — the
#: order key of an append is a number in every implementation the corpus has or
#: plausibly will have. A suite cannot ask a store for an *invalid* position, so
#: it has to supply one, and this is deliberately far outside any encoding rather
#: than one character off a real token.
_FOREIGN_POSITION = TracePosition(token="not-a-position")  # noqa: S106 — an order key, not a secret


def _emission_failures(
    captured: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """The emission-failure records among ``captured`` structlog events.

    Args:
        captured: What ``structlog.testing.capture_logs`` collected.

    Returns:
        Only the emission failures, so an unrelated log line in the same block
        cannot make a case pass or fail for the wrong reason.
    """
    return [record for record in captured if record.get("event") == TRACE_NOT_RECORDED]


async def _assert_holds_its_resource(
    harness: SuspendedMidWrite[Any],
    operation: str,
    first: Coroutine[Any, Any, object],
    second: Coroutine[Any, Any, object],
) -> None:
    """ADR-0060 §3's choreography: cancel inside the resource, then race a second caller.

    The second call is what makes this a test of the invariant rather than of
    propagation: a single cancelled call in isolation looks identical either way,
    and pre-ADR-0054 code raised ``CancelledError`` correctly *and* released the
    connection anyway.

    Args:
        harness: The store, its resource log, and the lever that arms it.
        operation: Which operation to hold open, passed to ``harness.arm``.
        first: The coroutine to cancel inside the resource.
        second: The coroutine that must not reach the resource until the first
            call's work has physically finished.

    Raises:
        AssertionError: If the resource was handed over early.
    """
    suspended = harness.arm(operation)
    started = asyncio.ensure_future(first)
    follower: asyncio.Task[object] | None = None
    try:
        await suspended.reached()
        started.cancel()
        await settle()

        follower = asyncio.ensure_future(second)
        await settle()
        assert not follower.done(), _RELEASED_EARLY

        # Again, because deferring one cancellation is not the contract: a second
        # delivered while the deferred wait runs must not escape either.
        started.cancel()
        await settle()
        assert not follower.done(), _RELEASED_EARLY

        suspended.release()
        with contextlib.suppress(asyncio.CancelledError):
            await started
        await follower
        assert not harness.log.overlapped, _RELEASED_EARLY
    finally:
        suspended.release()
        started.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await started
        if follower is not None:
            follower.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await follower


class _TraceCancellation:
    """The hook every trace suite's ADR-0060 case shares.

    One hook rather than three, because the store binding inherits all three
    suites and would otherwise implement the same lever three times under three
    names. Each suite passes its own operation name, which is what lets a
    ``sqlite3`` store park the *right* worker: each ``async with self._lock`` site
    is a separate place the resource could be handed over early (#370).
    """

    #: Set on a binding whose subject holds nothing whose safety outlives the
    #: coroutine, which makes ADR-0060's clause vacuous for it.
    acquires_no_shared_resource: bool = False

    def subject_suspended_mid_operation(
        self,
    ) -> AbstractAsyncContextManager[SuspendedMidWrite[Any]]:
        """Supply a subject whose named operation can be stopped *inside* its resource.

        Override unless :attr:`acquires_no_shared_resource` is set. The suite
        cancels the call while it is suspended and then watches what a second
        caller can reach, which is the only way to tell the fixed code from the
        broken code: pre-ADR-0054 a store raised ``CancelledError`` correctly and
        released the connection anyway, so a case that asserts only propagation
        certifies the bug.

        The suite calls ``arm(operation)`` with its own operation's name, which is
        what lets a ``sqlite3`` store park the right worker.

        Returns:
            A context manager over the harness.

        Raises:
            NotImplementedError: Until a binding overrides it.
        """
        raise NotImplementedError


class TraceSinkContract(_TraceCancellation):
    """What every ``TraceSink`` owes (ADR-0119 §5, §7, §13b).

    The narrow write seam. Its obligations are the ones an emitter's correctness
    rests on and cannot check for itself: the append happens, the recorded copy is
    detached from the caller's object, an id already held is refused silently with
    the *first* trace kept, a backing-store fault does not reach the caller, and a
    dropped trace is never dropped silently.
    """

    @pytest.fixture
    def sink(self) -> TraceSink:
        """The subject: an empty sink."""
        raise NotImplementedError

    async def recorded(self, sink: TraceSink) -> tuple[EvaluationTrace, ...]:
        """Every trace ``sink`` holds, in insertion order.

        The suite's window on the sink, not a seam the code under test could
        reach: ``TraceSink`` carries an append and nothing else, which is the
        whole of ADR-0119 §7's narrowing, so a conformance suite for it has to be
        given a way to look.

        Args:
            sink: The subject.

        Returns:
            What it holds.
        """
        raise NotImplementedError

    def failing_sink(self) -> TraceSink:
        """A sink whose backing store fails every append (ADR-0119 §5).

        Returns:
            The sink.
        """
        raise NotImplementedError

    async def test_an_emitted_trace_is_recorded(self, sink: TraceSink) -> None:
        """The base case, so nothing below passes vacuously."""
        trace = evaluation_trace("memory_search", kind=TraceKind.RETRIEVAL)

        await sink.emit(trace)

        assert [held.id for held in await self.recorded(sink)] == [trace.id]

    async def test_emit_returns_nothing(self, sink: TraceSink) -> None:
        """``emit`` answers no question: a caller learns nothing about the store.

        Pinned because the temptation is to return a bool or an id, and either
        would invite an emitter to branch on whether its trace landed — which is
        the pipeline reading the instrument (ADR-0119 §7) through the one seam it
        does hold.
        """
        assert await sink.emit(evaluation_trace()) is None  # type: ignore[func-returns-value]

    async def test_the_recorded_trace_is_detached_from_the_callers_object(
        self, sink: TraceSink
    ) -> None:
        """``frozen=True`` refuses ``x.seam = …`` and not ``x.__dict__["seam"] = …``.

        A sink that kept the caller's object would let a later write past the
        frozen model rewrite the record of an event that already happened.
        """
        trace = evaluation_trace("memory_search")
        await sink.emit(trace)

        trace.__dict__["seam"] = "rewritten"

        assert [held.seam for held in await self.recorded(sink)] == ["memory_search"]

    async def test_the_recorded_trace_is_detached_from_what_a_reader_is_handed(
        self, sink: TraceSink
    ) -> None:
        """Every read is a snapshot: mutating one cannot reach the store."""
        await sink.emit(evaluation_trace("memory_search"))

        handed = (await self.recorded(sink))[0]
        handed.__dict__["seam"] = "rewritten"

        assert [held.seam for held in await self.recorded(sink)] == ["memory_search"]

    async def test_an_absent_metric_key_survives_storage_as_absent(self, sink: TraceSink) -> None:
        """§3's observation rule, through the persistence layer (§13d).

        An operation can raise before a quantity exists — a ``search`` whose
        embedding fails has no candidate count — and the two available shortcuts
        both lie. Recording zero asserts an observation nobody made; omitting the
        trace loses the fault. So the key is simply absent, and a schema with
        ``NOT NULL DEFAULT 0`` columns would erase that distinction silently, at
        the layer furthest from the emitter that depends on it.
        """
        trace = evaluation_trace(
            "memory_search",
            kind=TraceKind.RETRIEVAL,
            outcome=TraceOutcome.FAULT,
            fault_class="EmbeddingDeadlineExpiredError",
            metrics={"limit": 10},
        )

        await sink.emit(trace)

        held = (await self.recorded(sink))[0]
        assert dict(held.metrics) == {"limit": 10}
        assert "candidates" not in held.metrics

    async def test_an_absent_record_set_is_not_an_empty_one(self, sink: TraceSink) -> None:
        """An unobserved id set and an observed-and-empty one stay distinct (§3, §13d).

        "The read returned nothing" and "the read never ran" are different facts,
        and a measure that could not tell them apart would count the second as the
        first — which for a retrieval trace is #824's trigger condition,
        fabricated.
        """
        trace = evaluation_trace(
            "memory_search",
            kind=TraceKind.RETRIEVAL,
            records={TraceRecordSet.RETURNED: RecordIdSet(ids=(), total=0)},
        )

        await sink.emit(trace)

        held = (await self.recorded(sink))[0]
        assert held.records[TraceRecordSet.RETURNED] == RecordIdSet(ids=(), total=0)
        assert TraceRecordSet.WRITTEN not in held.records

    async def test_a_repeated_id_is_refused_silently_and_keeps_the_first(
        self, sink: TraceSink
    ) -> None:
        """§13b's idempotency clause, in all three of its parts.

        Raising is not available (§5 subordinates the instrument) and overwriting
        would let a later write rewrite the record of an earlier event, so the
        stored trace is kept — and the refusal is still logged, because a
        swallowed refusal that said nothing would be the silence §5 refuses.
        """
        first = evaluation_trace("first")
        second = first.model_copy(update={"seam": "second"})
        assert second.id == first.id  # the case's premise, not its subject

        await sink.emit(first)
        with structlog.testing.capture_logs() as captured:
            await sink.emit(second)

        assert [held.seam for held in await self.recorded(sink)] == ["first"]
        assert len(_emission_failures(captured)) == 1

    async def test_emit_returns_normally_when_the_backing_store_fails(self) -> None:
        """§5's subordination clause: the instrument never fails the work.

        ADR-0074 already settled the neighbouring case in the other direction — a
        memory-store failure leaves a turn recorded with no episode rather than
        failing the turn — and a trace is one tier further from the user's answer
        than an episode is.
        """
        sink = self.failing_sink()

        assert await sink.emit(evaluation_trace()) is None  # type: ignore[func-returns-value]

    async def test_a_dropped_trace_is_logged_and_never_silent(self) -> None:
        """§5's second clause, and the reason it is not optional.

        A missing trace is otherwise indistinguishable from a non-event: a measure
        over a stream with dropped rows reports a smaller numerator and does not
        know it. The record names the kind, the seam and the failure's *class* —
        never its message, which may quote a row (ADR-0004 §5).
        """
        sink = self.failing_sink()
        trace = evaluation_trace("memory_search", kind=TraceKind.RETRIEVAL)

        with structlog.testing.capture_logs() as captured:
            await sink.emit(trace)

        failures = _emission_failures(captured)
        assert len(failures) == 1
        assert failures[0]["kind"] == TraceKind.RETRIEVAL.value
        assert failures[0]["seam"] == "memory_search"
        assert failures[0]["error_class"]

    async def test_a_trace_mutated_past_its_model_is_dropped_and_leaks_nothing(
        self, sink: TraceSink
    ) -> None:
        """The one path on which a trace's own fields are not known to be Tier 2.

        ``frozen=True`` refuses ``trace.seam = …`` and **not**
        ``trace.__dict__["seam"] = …``, so a caller that wrote past the model
        hands the sink an object carrying an arbitrary string. Revalidation is
        what catches it — and the trap is one level on, in the failure record:
        logging the refused field would take the value the store just declined to
        store *for carrying content* and write it to the log instead, where
        ADR-0004 §5 is unconditional ("Logs are Tier 2 only") and ADR-0119 §2
        names the same trap for a fault class ("the refused name is not diverted
        to the log, which is the trap in the obvious fix").

        So the trace is dropped, the failure is still recorded, and nothing
        derived from the mutated value appears anywhere.
        """
        tier_one = "the user asked about their diagnosis on 3 March"
        trace = evaluation_trace("memory_search")
        trace.__dict__["seam"] = tier_one

        with structlog.testing.capture_logs() as captured:
            await sink.emit(trace)

        assert await self.recorded(sink) == ()
        assert len(_emission_failures(captured)) == 1
        assert tier_one not in repr(captured)

    @pytest.mark.optional_obligation
    async def test_a_cancelled_emit_holds_its_resource_until_the_work_finishes(self) -> None:
        """``core.protocols``' cancellation clause, on ``emit`` (ADR-0060 §3).

        A cancelled call must not hand the resource to the next caller while the
        work it started is still using it. The cancelled append's *effect* is
        deliberately not asserted — the clause's third paragraph makes it
        indeterminate to the caller — so what is pinned is that the second call is
        whole and the sink still serves it.
        """
        if self.acquires_no_shared_resource:
            pytest.skip("implementation acquires nothing whose safety outlives the coroutine")

        async with self.subject_suspended_mid_operation() as harness:
            sink: TraceSink = harness.store
            await _assert_holds_its_resource(
                harness,
                "emit",
                sink.emit(evaluation_trace("first")),
                sink.emit(evaluation_trace("second")),
            )


class TraceRetentionContract(_TraceCancellation):
    """What every ``TraceRetention`` owes (ADR-0119 §10, §13b).

    The sweep seam. Age is the only reason a trace is deleted; the horizon is
    exclusive at its own instant; the count is what was actually removed; and —
    unlike :meth:`TraceSink.emit` — a store fault here **raises**, because a sweep
    is not the work being observed.
    """

    @pytest.fixture
    def retention(self) -> TraceRetention:
        """The subject: an empty store, seen through the retention seam."""
        raise NotImplementedError

    async def hold(self, retention: TraceRetention, *traces: EvaluationTrace) -> None:
        """Arrange a history on ``retention``.

        ``TraceRetention`` carries a purge and nothing else, so a suite for it has
        to be given a way to put something there to purge.

        Args:
            retention: The subject.
            *traces: What it should hold, in order.
        """
        raise NotImplementedError

    async def remaining(self, retention: TraceRetention) -> tuple[EvaluationTrace, ...]:
        """What ``retention`` still holds, in insertion order.

        Args:
            retention: The subject.

        Returns:
            The survivors.
        """
        raise NotImplementedError

    def failing_retention(self) -> TraceRetention:
        """A retention seam whose backing store fails every purge.

        Returns:
            The subject.
        """
        raise NotImplementedError

    async def test_a_trace_older_than_the_horizon_is_deleted(
        self, retention: TraceRetention
    ) -> None:
        """The base case: age, and only age, deletes a trace (§10)."""
        old = evaluation_trace("old", occurred_at=_EARLIER)
        new = evaluation_trace("new", occurred_at=_LATER)
        await self.hold(retention, old, new)

        removed = await retention.purge_before(DEFAULT_OCCURRED_AT)

        assert removed == 1
        assert [held.seam for held in await self.remaining(retention)] == ["new"]

    async def test_a_trace_at_the_horizon_is_kept(self, retention: TraceRetention) -> None:
        """ "Older than" is strict, so a horizon computed as ``now - retention``
        does not delete the trace that lands exactly on it.
        """
        await self.hold(retention, evaluation_trace("boundary", occurred_at=DEFAULT_OCCURRED_AT))

        removed = await retention.purge_before(DEFAULT_OCCURRED_AT)

        assert removed == 0
        assert [held.seam for held in await self.remaining(retention)] == ["boundary"]

    async def test_a_purge_that_removes_nothing_reports_nothing(
        self, retention: TraceRetention
    ) -> None:
        """An empty store is not an error, and zero is the honest answer."""
        assert await retention.purge_before(DEFAULT_OCCURRED_AT) == 0

    async def test_the_count_is_what_was_removed(self, retention: TraceRetention) -> None:
        """The number is exact, not an estimate and not the count of what was held.

        A sweep that reported the wrong figure would put a wrong number in the
        operational record the sweep is observed through, which is the one place
        an operator would look to tell "nothing to do" from "the purge is broken".
        """
        await self.hold(
            retention,
            *(evaluation_trace(f"old_{index}", occurred_at=_EARLIER) for index in range(3)),
            evaluation_trace("new", occurred_at=_LATER),
        )

        assert await retention.purge_before(DEFAULT_OCCURRED_AT) == 3

    async def test_purge_raises_when_the_store_cannot_be_written(self) -> None:
        """Unlike ``emit``, this one raises (§13b).

        A sweep is not the work being observed, so §5's subordination has nothing
        to say about it, and a purge that silently did nothing would let a store
        grow without bound behind a horizon an operator believes is enforced.
        """
        retention = self.failing_retention()

        with pytest.raises(TraceStoreError):
            await retention.purge_before(DEFAULT_OCCURRED_AT)

    @pytest.mark.optional_obligation
    async def test_a_cancelled_purge_holds_its_resource_until_the_work_finishes(self) -> None:
        """``core.protocols``' cancellation clause, on ``purge_before`` (ADR-0060 §3)."""
        if self.acquires_no_shared_resource:
            pytest.skip("implementation acquires nothing whose safety outlives the coroutine")

        async with self.subject_suspended_mid_operation() as harness:
            retention: TraceRetention = harness.store
            await _assert_holds_its_resource(
                harness,
                "purge_before",
                retention.purge_before(DEFAULT_OCCURRED_AT),
                retention.purge_before(DEFAULT_OCCURRED_AT),
            )


class TraceStoreContract(_TraceCancellation):
    """What every ``TraceStore`` owes beyond the two narrow seams (ADR-0119 §7a).

    The walk. Its clauses are unusually easy to satisfy *almost*: an
    ``occurred_at`` order looks total until two emitters stamp the same instant, a
    ``position: None`` at exhaustion looks natural until a reader throws away the
    only thing that would let it resume, and a short chunk looks like an ending
    until an append arrives a second later.
    """

    @pytest.fixture
    def store(self) -> TraceStore:
        """The subject: an empty store."""
        raise NotImplementedError

    def failing_store(self) -> TraceStore:
        """A store whose backing store fails every read.

        Returns:
            The subject.
        """
        raise NotImplementedError

    async def plant_row_without_id(self, store: TraceStore) -> None:
        """Make ``store`` hold one row whose ``id`` cannot be read.

        The one arrangement no sequence of ``emit`` calls can produce, and the one
        ADR-0119 §13d makes an obligation because "only the store can see the
        difference" between a new trace with no id supplied and a stored row whose
        id was lost.

        Args:
            store: The subject.
        """
        raise NotImplementedError

    async def test_the_walk_returns_what_was_appended(self, store: TraceStore) -> None:
        """The base case, so nothing below passes vacuously."""
        first, second = evaluation_trace("first"), evaluation_trace("second")
        await store.emit(first)
        await store.emit(second)

        chunk = await store.walk(limit=10)

        assert [held.seam for held in chunk.traces] == ["first", "second"]

    async def test_the_order_is_insertion_order_and_not_instant_order(
        self, store: TraceStore
    ) -> None:
        """§7a's first clause, in the case that separates the two orders.

        The *emitter* stamps the instant (§3), so a buffered or slow sink can land
        an earlier instant after a later one — and two traces can carry the same
        instant, which makes an order over ``occurred_at`` not even total. A page
        boundary drawn on it can skip a row that arrives behind the cursor.
        """
        await store.emit(evaluation_trace("late_instant", occurred_at=_LATER))
        await store.emit(evaluation_trace("early_instant", occurred_at=_EARLIER))

        chunk = await store.walk(limit=10)

        assert [held.seam for held in chunk.traces] == ["late_instant", "early_instant"]

    async def test_a_chunk_is_bounded_and_the_sequence_is_complete(self, store: TraceStore) -> None:
        """One call is a prefix; completeness is a property of the *sequence* (§7a).

        Read as one call's obligation the guarantee is unsatisfiable the moment
        more than ``limit`` traces are outstanding, which is the normal case for a
        measure over a week.
        """
        for index in range(5):
            await store.emit(evaluation_trace(f"trace_{index}"))

        seen: list[str] = []
        position: TracePosition | None = None
        for _ in range(3):
            chunk = await store.walk(after=position, limit=2)
            assert len(chunk.traces) <= 2
            seen.extend(held.seam for held in chunk.traces)
            position = chunk.position

        assert seen == [f"trace_{index}" for index in range(5)]

    async def test_the_walk_returns_no_trace_at_or_before_the_given_position(
        self, store: TraceStore
    ) -> None:
        """Resuming does not re-read what the position already covers (§7a)."""
        await store.emit(evaluation_trace("first"))
        await store.emit(evaluation_trace("second"))

        first_chunk = await store.walk(limit=1)
        resumed = await store.walk(after=first_chunk.position, limit=10)

        assert [held.seam for held in resumed.traces] == ["second"]

    async def test_an_empty_chunk_still_carries_a_position(self, store: TraceStore) -> None:
        """There is no exhausted state in which a caller is handed no position (§7a).

        An earlier draft had the walk report exhaustion with ``position: None`` —
        the natural shape, and wrong: a reader handed that has stopped *and thrown
        away the only thing that would let it resume*, so a trace appended between
        the query and the return is unreachable forever.
        """
        floor = await store.walk(limit=10)
        assert floor.traces == ()

        await store.emit(evaluation_trace("first"))
        caught_up = await store.walk(after=floor.position, limit=10)
        exhausted = await store.walk(after=caught_up.position, limit=10)

        assert exhausted.traces == ()
        assert exhausted.position == caught_up.position

    async def test_a_short_chunk_means_nothing_further_yet_and_not_the_end(
        self, store: TraceStore
    ) -> None:
        """The walk is a high-water mark, not an iterator (§7a).

        This is what a measure actually wants — resume tomorrow from where you
        stopped today — and what an iterator that ended could not do at all.
        """
        await store.emit(evaluation_trace("first"))
        chunk = await store.walk(limit=10)
        assert len(chunk.traces) < 10  # the case's premise

        await store.emit(evaluation_trace("later"))
        resumed = await store.walk(after=chunk.position, limit=10)

        assert [held.seam for held in resumed.traces] == ["later"]

    async def test_an_append_racing_a_walk_is_returned_exactly_once(
        self, store: TraceStore
    ) -> None:
        """§7a's resumption guarantee against an append landing mid-walk (§13d).

        "An append that lands during a call takes a position after every position
        already issued, so no page boundary skips or duplicates a trace." Whether
        the racing append lands inside the chunk or after it is not the contract —
        that it is returned once, in order, is.
        """
        for index in range(3):
            await store.emit(evaluation_trace(f"before_{index}"))

        walking = asyncio.ensure_future(store.walk(limit=3))
        appending = asyncio.ensure_future(store.emit(evaluation_trace("during")))
        chunk, _ = await asyncio.gather(walking, appending)

        rest = await store.walk(after=chunk.position, limit=10)
        seen = [held.seam for held in (*chunk.traces, *rest.traces)]
        assert seen == ["before_0", "before_1", "before_2", "during"]

    async def test_a_purge_below_a_held_position_does_not_disturb_it(
        self, store: TraceStore
    ) -> None:
        """A position is a **bound, not a reference** (§7a).

        It holds because a store never reissues a key; without that the sentence
        would be false in the one case that matters — a purge deleting from the
        old end and the next append landing on the freed key, so a held position
        would silently start pointing at a different trace.
        """
        await store.emit(evaluation_trace("old", occurred_at=_EARLIER))
        chunk = await store.walk(limit=10)
        held_position = chunk.position

        assert await store.purge_before(DEFAULT_OCCURRED_AT) == 1
        await store.emit(evaluation_trace("new", occurred_at=_LATER))

        resumed = await store.walk(after=held_position, limit=10)
        assert [held.seam for held in resumed.traces] == ["new"]

    @pytest.mark.parametrize("limit", [0, -1])
    async def test_a_non_positive_bound_is_refused(self, store: TraceStore, limit: int) -> None:
        """§7a's zero refusal, as ADR-0114 §6 refuses one and for the same reason.

        SQLite reads ``LIMIT -1`` as *no limit at all*, so the one bounded read of
        this store would silently become the unbounded one it exists to avoid.
        """
        with pytest.raises(ValueError, match="limit"):
            await store.walk(limit=limit)

    async def test_a_position_the_store_did_not_issue_is_refused(self, store: TraceStore) -> None:
        """A caller-held position this store cannot read is a caller bug (§7a).

        Not the recoverable state ADR-0111 §7 discards for a *durable* cursor:
        there is no cursor here to reset, and a store that quietly restarted the
        walk from its floor would re-return every retained trace to a measure that
        asked for the next page.
        """
        with pytest.raises(ValueError, match="position"):
            await store.walk(after=_FOREIGN_POSITION, limit=10)

    async def test_the_walk_returns_detached_snapshots(self, store: TraceStore) -> None:
        """``frozen=True`` refuses ``x.outcome = …`` and not ``x.__dict__[…] = …``."""
        await store.emit(evaluation_trace("first"))

        handed = (await store.walk(limit=10)).traces[0]
        handed.__dict__["seam"] = "rewritten"

        assert [held.seam for held in (await store.walk(limit=10)).traces] == ["first"]

    async def test_a_row_with_no_readable_id_raises_rather_than_minting_one(
        self, store: TraceStore
    ) -> None:
        """§3's hydration rule, made an obligation by §13d.

        The ``id`` default exists to mint an id for a **new** trace. A defaulted
        field is silent about the difference between "no id was supplied because
        this is a new trace" and "no id was read because the row or the query lost
        the column" — and in the second case a fresh UUID hands back a trace that
        no longer identifies the event it came from, with deduplication and every
        cross-trace join then operating on a fabricated id. The type cannot tell
        the two apart, so the store must.
        """
        await self.plant_row_without_id(store)

        with pytest.raises(TraceStoreError):
            await store.walk(limit=10)

    async def test_the_walk_raises_when_the_store_cannot_be_read(self) -> None:
        """A measure's read is not the work being observed, so this one raises."""
        store = self.failing_store()

        with pytest.raises(TraceStoreError):
            await store.walk(limit=10)

    @pytest.mark.optional_obligation
    async def test_a_cancelled_walk_holds_its_resource_until_the_work_finishes(self) -> None:
        """``core.protocols``' cancellation clause, on ``walk`` (ADR-0060 §3).

        The locked *reads* need it as much as the writes: ADR-0060 §3 binds any
        method that acquires the resource, and a read that released the connection
        early is the same native crash as a write that did.
        """
        if self.acquires_no_shared_resource:
            pytest.skip("implementation acquires nothing whose safety outlives the coroutine")

        async with self.subject_suspended_mid_operation() as harness:
            store: TraceStore = harness.store
            await _assert_holds_its_resource(
                harness,
                "walk",
                store.walk(limit=1),
                store.walk(limit=1),
            )
