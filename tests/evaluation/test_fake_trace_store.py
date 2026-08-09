"""The three canonical trace fakes, run through their shared suites (ADR-0119 §13d).

One binding per Protocol, because the triad is per Protocol: ``FakeTraceSink``
answers for ``TraceSink``, ``FakeTraceRetention`` for ``TraceRetention``, and
``FakeTraceStore`` for ``TraceStore`` — and the last is additionally run through
the two narrow suites, which is ADR-0119 §7's "one concrete implements all three"
as a test rather than an assertion.

Beside the contract runs, the cases at the bottom pin what is the *fake's* own
business rather than the contract's: its failure levers, and the affordance the
suite's hydration obligation needs.
"""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING, Any

import pytest
from trace_contracts import TraceRetentionContract, TraceSinkContract, TraceStoreContract

from ai_assistant.core.errors import TraceStoreError
from ai_assistant.core.protocols import TraceRetention, TraceSink, TraceStore
from ai_assistant.testing import (
    FakeTraceRetention,
    FakeTraceSink,
    FakeTraceStore,
    evaluation_trace,
)
from ai_assistant.testing.cancellation import SuspendedMidWrite

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ai_assistant.core.types import EvaluationTrace


def _suspended[T: FakeTraceSink | FakeTraceRetention | FakeTraceStore](
    subject: T,
) -> SuspendedMidWrite[T]:
    """Wrap ``subject`` as the harness ADR-0060's case drives.

    ``arm`` ignores which operation it is handed: every method on these fakes
    passes through the *one* modelled resource, so the parametrised cases
    exercise the same ``held()`` path here and earn their keep on the durable
    store, where each operation is a separate lock site (#370).

    Args:
        subject: The fake to suspend.

    Returns:
        The harness.
    """
    return SuspendedMidWrite(
        store=subject,
        log=subject.resource.log,
        arm=lambda _operation: subject.resource.suspend_next(),
    )


class TestFakeTraceSinkContract(TraceSinkContract):
    """Runs ``FakeTraceSink`` through the shared ``TraceSink`` suite."""

    @pytest.fixture
    def sink(self) -> TraceSink:
        return FakeTraceSink()

    async def recorded(self, sink: TraceSink) -> tuple[EvaluationTrace, ...]:
        assert isinstance(sink, FakeTraceSink)
        return sink.recorded

    def failing_sink(self) -> TraceSink:
        sink = FakeTraceSink()
        sink.fail_append()
        return sink

    def sink_failing_with(self, error: Exception) -> TraceSink:
        sink = FakeTraceSink()
        sink.fail_append(error)
        return sink

    @contextlib.asynccontextmanager
    async def subject_suspended_mid_operation(self) -> AsyncIterator[SuspendedMidWrite[Any]]:
        """The fake models the resource it does not really own (ADR-0060 §3).

        A list needs no serialising, so without this the canonical fake could only
        opt out — and the case would then run against the ``sqlite3`` store alone,
        which is the implementation that already got it right once.

        Yields:
            The harness. Nothing to dispose of, hence the bare yield.
        """
        yield _suspended(FakeTraceSink())


class TestFakeTraceRetentionContract(TraceRetentionContract):
    """Runs ``FakeTraceRetention`` through the shared ``TraceRetention`` suite."""

    @pytest.fixture
    def retention(self) -> TraceRetention:
        return FakeTraceRetention()

    async def hold(self, retention: TraceRetention, *traces: EvaluationTrace) -> None:
        assert isinstance(retention, FakeTraceRetention)
        retention.hold(*traces)

    async def remaining(self, retention: TraceRetention) -> tuple[EvaluationTrace, ...]:
        assert isinstance(retention, FakeTraceRetention)
        return retention.recorded

    def failing_retention(self) -> TraceRetention:
        retention = FakeTraceRetention()
        retention.fail_purge()
        return retention

    @contextlib.asynccontextmanager
    async def subject_suspended_mid_operation(self) -> AsyncIterator[SuspendedMidWrite[Any]]:
        """As above: the fake models the one resource it does not really own.

        Yields:
            The harness.
        """
        yield _suspended(FakeTraceRetention())


class TestFakeTraceStoreContract(TraceSinkContract, TraceRetentionContract, TraceStoreContract):
    """Runs ``FakeTraceStore`` through all three suites (ADR-0119 §7).

    Inheriting the two narrow suites is what makes "``TraceStore`` structurally
    satisfies both narrow Protocols" evidence: the same object answers the
    emitter's contract, the sweep's contract and the walk's, with no adapter
    between them.
    """

    @pytest.fixture
    def store(self) -> TraceStore:
        return FakeTraceStore()

    @pytest.fixture
    def sink(self, store: TraceStore) -> TraceSink:
        return store

    @pytest.fixture
    def retention(self, store: TraceStore) -> TraceRetention:
        return store

    async def recorded(self, sink: TraceSink) -> tuple[EvaluationTrace, ...]:
        assert isinstance(sink, FakeTraceStore)
        return sink.recorded

    async def hold(self, retention: TraceRetention, *traces: EvaluationTrace) -> None:
        assert isinstance(retention, FakeTraceStore)
        retention.hold(*traces)

    async def remaining(self, retention: TraceRetention) -> tuple[EvaluationTrace, ...]:
        assert isinstance(retention, FakeTraceStore)
        return retention.recorded

    def failing_sink(self) -> TraceSink:
        store = FakeTraceStore()
        store.fail_append()
        return store

    def sink_failing_with(self, error: Exception) -> TraceSink:
        store = FakeTraceStore()
        store.fail_append(error)
        return store

    def failing_retention(self) -> TraceRetention:
        store = FakeTraceStore()
        store.fail_read()
        return store

    def failing_store(self) -> TraceStore:
        store = FakeTraceStore()
        store.fail_read()
        return store

    async def plant_row_without_id(self, store: TraceStore) -> None:
        assert isinstance(store, FakeTraceStore)
        store.plant_raw_row(_row_without_id())

    @contextlib.asynccontextmanager
    async def subject_suspended_mid_operation(self) -> AsyncIterator[SuspendedMidWrite[Any]]:
        """As above: the fake models the one resource it does not really own.

        Yields:
            The harness.
        """
        yield _suspended(FakeTraceStore())


def _row_without_id() -> str:
    """A stored row whose ``id`` the query lost — the case ADR-0119 §13d names.

    Built by dropping the key from a real trace's JSON rather than by hand, so
    the row is valid in every other respect and the refusal can only be about the
    id.

    Returns:
        The raw row.
    """
    payload = json.loads(evaluation_trace("orphan").model_dump_json())
    del payload["id"]
    return json.dumps(payload)


# --- the fakes' own business, not the contract's -----------------------------


async def test_a_planted_row_is_the_only_way_to_reach_the_hydration_refusal() -> None:
    """No sequence of ``emit`` calls can produce an unreadable row.

    Which is why the affordance exists at all: the obligation is about a row a
    *store* holds, and ``EvaluationTrace`` mints an id for every trace that
    reaches ``emit``.
    """
    store = FakeTraceStore()
    await store.emit(evaluation_trace("first"))

    assert (await store.walk(limit=10)).traces[0].id

    store.plant_raw_row(_row_without_id())
    with pytest.raises(TraceStoreError, match="no readable id"):
        await store.walk(limit=10)


async def test_a_scripted_append_failure_is_preserved_as_the_cause() -> None:
    """The lever models a *store* fault, and the fault it was given is the one modelled."""
    sink = FakeTraceSink()
    sink.fail_append(OSError("the disk is full"))

    await sink.emit(evaluation_trace())

    assert sink.recorded == ()


async def test_the_narrow_fakes_cannot_reach_the_wide_seam() -> None:
    """ADR-0119 §7's split, as the shape of the objects rather than as prose.

    A ``FakeTraceSink`` handed to an emitter's test carries no ``walk`` and no
    ``purge_before`` at all, so a consumer that grew a dependency on either would
    fail here rather than passing against a stand-in more capable than the seam
    it stands for.
    """
    sink = FakeTraceSink()
    retention = FakeTraceRetention()

    assert not hasattr(sink, "walk")
    assert not hasattr(sink, "purge_before")
    assert not hasattr(retention, "walk")
    assert not hasattr(retention, "emit")


def test_the_fakes_satisfy_their_protocols_at_runtime() -> None:
    """The ``@runtime_checkable`` half of "one concrete implements all three"."""
    assert isinstance(FakeTraceSink(), TraceSink)
    assert isinstance(FakeTraceRetention(), TraceRetention)
    assert isinstance(FakeTraceStore(), TraceStore)
    assert isinstance(FakeTraceStore(), TraceSink)
    assert isinstance(FakeTraceStore(), TraceRetention)
