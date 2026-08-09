"""The SQLite trace store, against its shared suites and beyond them (ADR-0119 §6).

The three suites cover what every implementation owes: the append, the detached
snapshot, the silent idempotent refusal, the swallowed store fault and its log
record, the horizon, and the walk's total insertion order with its always-present
position. What they cannot cover is the half this implementation exists for —
that a week of traces is still on file once the process that recorded them has
gone, and that the persistence layer did not quietly turn an *absent* metric into
a zero on the way through.

The conformance subclass runs against ``:memory:``, so it touches no filesystem
and needs no ``integration`` mark. The tests that open a real file say so.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sqlite3
import threading
from typing import TYPE_CHECKING, Any

import pytest
from trace_contracts import TraceRetentionContract, TraceSinkContract, TraceStoreContract

from ai_assistant.core.errors import TraceStoreError
from ai_assistant.core.protocols import TraceRetention, TraceSink, TraceStore
from ai_assistant.core.types import (
    RecordIdSet,
    TraceKind,
    TraceOutcome,
    TraceRecordSet,
)
from ai_assistant.evaluation import SqliteTraceStore
from ai_assistant.testing import DEFAULT_OCCURRED_AT, evaluation_trace
from ai_assistant.testing.cancellation import (
    ResourceLog,
    SuspendedMidWrite,
    ThreadSuspension,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator
    from pathlib import Path

    from ai_assistant.core.types import EvaluationTrace
    from ai_assistant.testing.cancellation import SuspendedCall

#: The private method each Protocol operation does its SQL in. ADR-0060 §3's case
#: parks *that* operation's worker, because each ``async with self._lock`` site is
#: a separate place the connection could be handed over early (#370) — and here
#: the read is as much a subject as the writes, since a released connection under
#: a running ``SELECT`` is the same native crash as one under an ``INSERT``.
_SYNC_METHODS = {
    "emit": "_append_sync",
    "purge_before": "_purge_sync",
    "walk": "_walk_sync",
}


@pytest.fixture
def ephemeral() -> Iterator[SqliteTraceStore]:
    """An in-memory store, closed at the end of the case."""
    store = SqliteTraceStore(path=":memory:")
    try:
        yield store
    finally:
        store.close()


def _broken() -> SqliteTraceStore:
    """A store whose connection is closed, so every statement fails.

    The honest way to model "the backing store failed" for a ``sqlite3`` store:
    no monkeypatching, and the fault the driver raises is a real
    ``sqlite3.ProgrammingError`` rather than one a test invented.

    Returns:
        The store.
    """
    store = SqliteTraceStore(path=":memory:")
    store.close()
    return store


@contextlib.asynccontextmanager
async def _suspended() -> AsyncIterator[SuspendedMidWrite[Any]]:
    """Park a named operation's worker thread inside the connection's turn.

    ``arm(operation)`` wraps the private method that operation does its SQL in —
    inside ``async with self._lock`` and inside the worker the event loop cannot
    interrupt, which is exactly where ADR-0054's bug lived — so the first worker
    to reach it blocks and every later one runs free. Blocking there is what makes
    the case deterministic: left to run, a commit finishes in microseconds and
    whether the second caller arrives while the worker still holds the connection
    would be a race.

    Its own store on its own connection: the suspended worker is parked for the
    length of the case, and sharing would make an unrelated failure hang instead
    of fail.

    Yields:
        The harness.
    """
    store = SqliteTraceStore(path=":memory:")
    log = ResourceLog()
    suspension = ThreadSuspension()

    def arm(operation: str) -> SuspendedCall:
        attribute = _SYNC_METHODS[operation]
        original = getattr(store, attribute)
        armed = threading.Event()

        def blocking(*args: object) -> object:
            with log.inside():  # the span the connection is genuinely in use for
                if not armed.is_set():  # the first worker only; later ones run free
                    armed.set()
                    suspension.hold()
                return original(*args)

        setattr(store, attribute, blocking)
        return suspension

    try:
        yield SuspendedMidWrite(store=store, log=log, arm=arm)
    finally:
        suspension.release()
        # An implementation that released the connection early leaves a worker
        # still using it; closing under that is a native crash rather than a
        # reported failure, so give the worker a turn to unwind and let the
        # assertion in the suite be the thing that speaks.
        await asyncio.sleep(0.05)
        store.close()


class TestSqliteTraceStoreContract(TraceSinkContract, TraceRetentionContract, TraceStoreContract):
    """Runs ``SqliteTraceStore`` through all three suites (ADR-0119 §7).

    One object answering three contracts is the arrangement §7 depends on: the
    composition root hands the same store to every emitter as a ``TraceSink``, to
    the ``Engine``'s maintenance operation as a ``TraceRetention``, and to nothing
    in the pipeline as itself.
    """

    @pytest.fixture
    def store(self, ephemeral: SqliteTraceStore) -> TraceStore:
        return ephemeral

    @pytest.fixture
    def sink(self, ephemeral: SqliteTraceStore) -> TraceSink:
        return ephemeral

    @pytest.fixture
    def retention(self, ephemeral: SqliteTraceStore) -> TraceRetention:
        return ephemeral

    async def recorded(self, sink: TraceSink) -> tuple[EvaluationTrace, ...]:
        assert isinstance(sink, SqliteTraceStore)
        return await _everything(sink)

    async def hold(self, retention: TraceRetention, *traces: EvaluationTrace) -> None:
        assert isinstance(retention, SqliteTraceStore)
        for trace in traces:
            await retention.emit(trace)

    async def remaining(self, retention: TraceRetention) -> tuple[EvaluationTrace, ...]:
        assert isinstance(retention, SqliteTraceStore)
        return await _everything(retention)

    def failing_sink(self) -> TraceSink:
        return _broken()

    def failing_retention(self) -> TraceRetention:
        return _broken()

    def failing_store(self) -> TraceStore:
        return _broken()

    async def plant_row_without_id(self, store: TraceStore) -> None:
        """Write a row whose ``id`` the stored JSON does not carry.

        Written through the connection rather than through ``emit``, because
        ``emit`` cannot produce one — which is the reason ADR-0119 §13d makes this
        an obligation on the *store*: the type mints an id for every trace that
        reaches the seam, so only a row already on disk can be missing one.
        """
        assert isinstance(store, SqliteTraceStore)
        payload = json.loads(evaluation_trace("orphan").model_dump_json())
        del payload["id"]
        store._conn.execute(  # planting a row no public seam can write
            "INSERT INTO traces(id, occurred_at_us, data) VALUES (?, ?, ?)",
            ("orphan", 0, json.dumps(payload)),
        )
        store._conn.commit()

    @contextlib.asynccontextmanager
    async def subject_suspended_mid_operation(self) -> AsyncIterator[SuspendedMidWrite[Any]]:
        """Park the named operation's worker inside the connection's turn.

        Yields:
            The harness.
        """
        async with _suspended() as harness:
            yield harness


async def _everything(store: SqliteTraceStore) -> tuple[EvaluationTrace, ...]:
    """Walk the whole store, in chunks, so no case depends on an unbounded read."""
    seen: list[EvaluationTrace] = []
    position = None
    while True:
        chunk = await store.walk(after=position, limit=64)
        seen.extend(chunk.traces)
        position = chunk.position
        if len(chunk.traces) < 64:
            return tuple(seen)


# --- what only a durable store can be asked ----------------------------------


@pytest.mark.integration
async def test_a_trace_survives_the_process_that_recorded_it(tmp_path: Path) -> None:
    """The whole reason this implementation exists (ADR-0119 §6, §10).

    A measure spans weeks and #829's baseline spans a window, so a store that
    forgot on restart would satisfy every clause of the contract and defeat the
    leg.
    """
    path = tmp_path / "traces.db"
    first = SqliteTraceStore(path=path)
    try:
        await first.emit(evaluation_trace("memory_search", kind=TraceKind.RETRIEVAL))
    finally:
        first.close()

    second = SqliteTraceStore(path=path)
    try:
        chunk = await second.walk(limit=10)
    finally:
        second.close()

    assert [held.seam for held in chunk.traces] == ["memory_search"]


@pytest.mark.integration
async def test_an_absent_metric_is_still_absent_after_a_restart(tmp_path: Path) -> None:
    """§13d's round-trip obligation, across the boundary that could erase it.

    "A schema with ``NOT NULL DEFAULT 0`` columns would erase, silently and at the
    persistence layer, the distinction the fault path depends on." The in-memory
    run of the suite already asserts this; doing it again across a reopen is what
    rules out a default applied on *read* rather than on write.
    """
    path = tmp_path / "traces.db"
    first = SqliteTraceStore(path=path)
    try:
        await first.emit(
            evaluation_trace(
                "memory_search",
                kind=TraceKind.RETRIEVAL,
                outcome=TraceOutcome.FAULT,
                fault_class="EmbeddingDeadlineExpiredError",
                metrics={"limit": 10},
                records={TraceRecordSet.RETURNED: RecordIdSet(ids=(), total=0)},
            )
        )
    finally:
        first.close()

    second = SqliteTraceStore(path=path)
    try:
        held = (await second.walk(limit=10)).traces[0]
    finally:
        second.close()

    assert dict(held.metrics) == {"limit": 10}
    assert held.records[TraceRecordSet.RETURNED] == RecordIdSet(ids=(), total=0)
    assert TraceRecordSet.WRITTEN not in held.records


@pytest.mark.integration
def test_the_database_file_is_owner_only(tmp_path: Path) -> None:
    """ADR-0004 §4, kept identical to the other six stores rather than relaxed.

    The file holds no Tier 1 data, so this is defence in depth here — but a store
    that opted out of the family's posture is the one #506 would have to bring
    back in.
    """
    path = tmp_path / "traces.db"
    store = SqliteTraceStore(path=path)
    try:
        assert path.stat().st_mode & 0o777 == 0o600
    finally:
        store.close()


def test_opening_a_store_under_a_missing_directory_is_this_layers_error(tmp_path: Path) -> None:
    """A raw ``sqlite3.OperationalError`` must not escape this layer's boundary."""
    with pytest.raises(TraceStoreError, match="failed to open"):
        SqliteTraceStore(path=tmp_path / "absent" / "traces.db")


@pytest.mark.integration
def test_a_database_labelled_with_an_unknown_schema_is_refused(tmp_path: Path) -> None:
    """ADR-0049 §1's ordering: refused at open, before a table is created or read."""
    path = tmp_path / "traces.db"
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '99')")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(TraceStoreError, match="schema_version=99"):
        SqliteTraceStore(path=path)


async def test_a_row_the_query_kept_but_the_model_rejects_is_a_store_fault(
    ephemeral: SqliteTraceStore,
) -> None:
    """A downgraded or hand-edited database is reported, never handed on.

    Distinct from the missing-id case the suite covers: there the row *looks*
    valid and would silently acquire a fabricated identity; here it does not
    validate at all, and both are faults rather than records.
    """
    ephemeral._conn.execute(  # a corruption no public seam can write
        "INSERT INTO traces(id, occurred_at_us, data) VALUES (?, ?, ?)",
        ("corrupt", 0, '{"id": "not-a-minted-id", "kind": "operation"}'),
    )
    ephemeral._conn.commit()

    with pytest.raises(TraceStoreError, match="no longer validates"):
        await ephemeral.walk(limit=10)


async def test_a_duplicate_id_leaves_the_stored_row_untouched(
    ephemeral: SqliteTraceStore,
) -> None:
    """The ``UNIQUE`` index is the backstop; the check inside the transaction is the rule.

    Asserted on the durable store because this is where the two could disagree: a
    check that read outside the write transaction would let a second process
    observe the same free id, and the index is what stops the resulting insert.
    """
    first = evaluation_trace("first")
    await ephemeral.emit(first)
    await ephemeral.emit(first.model_copy(update={"seam": "second"}))

    chunk = await ephemeral.walk(limit=10)
    assert [held.seam for held in chunk.traces] == ["first"]


async def test_the_walk_is_ordered_by_the_key_and_not_by_the_instant(
    ephemeral: SqliteTraceStore,
) -> None:
    """Two traces stamped with the *same* instant still have a total order.

    The case an ``ORDER BY occurred_at_us`` would pass by accident on any other
    input: ties are exactly where an instant order stops being total, and a page
    boundary drawn across a tie is where a row goes missing (ADR-0119 §7a).
    """
    for index in range(4):
        await ephemeral.emit(evaluation_trace(f"tied_{index}", occurred_at=DEFAULT_OCCURRED_AT))

    first = await ephemeral.walk(limit=2)
    second = await ephemeral.walk(after=first.position, limit=2)

    seen = [held.seam for held in (*first.traces, *second.traces)]
    assert seen == ["tied_0", "tied_1", "tied_2", "tied_3"]


def test_the_store_satisfies_all_three_protocols_at_runtime(
    ephemeral: SqliteTraceStore,
) -> None:
    """ "One concrete implements all three" (ADR-0119 §7), at runtime as well as statically."""
    assert isinstance(ephemeral, TraceSink)
    assert isinstance(ephemeral, TraceRetention)
    assert isinstance(ephemeral, TraceStore)
