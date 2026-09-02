"""The SQLite routing trail, against its shared conformance suites and beyond.

The suites cover what every implementation owes: idempotence over the whole record,
the ``route_id`` rule and the route state machine, ADR-0197 §9's prune and its
blindness to a route's state, recording order against ``decided_at``, bounds, erasure,
and detachment on both paths. What they cannot cover is the half this implementation
exists for — that a decision a **model** took about the user's own stores is still on
file once the process that recorded it has gone.

**Both bindings are here, and the second is what ADR-0197 §12 asks for by name.**
``TestSqliteRoutingTrailContract`` runs the concrete store through the wide suite;
``TestSqliteRoutingTrailSatisfiesTheNarrowSeam`` runs the same class through the
``RoutingRecorder`` one, so the store's satisfaction of the narrow seam is evidence
rather than assertion. That is what makes the composition root's one-object-two-seams
wiring sound rather than merely plausible.

The conformance subclasses run against ``:memory:``, so they touch no filesystem and
need no ``integration`` mark. The tests that open a real file say so.

**ADR-0197 §9's residency clause is tested here rather than left as prose**, because
it "is the one clause of §9 that a working store can violate while every other test
passes": the file lives under the directory it was told to and is created owner-only.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import stat
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from routing_contract import RoutingRecorderContract, RoutingTrailContract

from ai_assistant.core.errors import RoutingTrailError
from ai_assistant.core.types import RoutableOperation, RouteApproval
from ai_assistant.permissions import SqliteRoutingTrail
from ai_assistant.testing.cancellation import ResourceLog, SuspendedMidWrite, ThreadSuspension
from ai_assistant.testing.routing import routed_operation_record

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator
    from pathlib import Path

    from ai_assistant.core.protocols import RoutingRecorder, RoutingTrail
    from ai_assistant.core.types import RoutedOperationRecord
    from ai_assistant.testing.cancellation import SuspendedCall

#: Big enough that no conformance case trips the prune by accident. The prune's own
#: cases build their own trail through ``bounded``.
_ROOMY = 1_000


@pytest.fixture
def ephemeral() -> Iterator[SqliteRoutingTrail]:
    """An in-memory trail, closed after the test."""
    trail = SqliteRoutingTrail(path=":memory:", max_rows=_ROOMY)
    try:
        yield trail
    finally:
        trail.close()


#: The private method each locked operation does its SQL in, which ADR-0060's hook wraps
#: to park a worker thread inside the connection's turn. Spelled out rather than derived
#: from the operation name, because the two reads have different helpers and neither is
#: named for the contract method that takes the lock around it.
_SYNC_METHODS = {
    "record": "_record_sync",
    "clear": "_clear_sync",
    "recent": "_newest_first_sync",
    "export": "_recording_order_sync",
}


class TestSqliteRoutingTrailContract(RoutingTrailContract):
    """Runs SqliteRoutingTrail through the shared RoutingTrail suite."""

    @pytest.fixture
    def trail(self, ephemeral: SqliteRoutingTrail) -> RoutingTrail:
        return ephemeral

    @contextlib.asynccontextmanager
    async def bounded(self, max_rows: int) -> AsyncIterator[RoutingTrail]:
        """An in-memory trail at ``max_rows``, closed when the case is done.

        The construction refusal ADR-0197 §9 requires happens *before* there is anything
        to close, which is why the ``try`` starts after it.
        """
        subject = SqliteRoutingTrail(path=":memory:", max_rows=max_rows)
        try:
            yield subject
        finally:
            subject.close()

    @contextlib.asynccontextmanager
    async def trail_suspended_mid_write(self) -> AsyncIterator[SuspendedMidWrite[RoutingTrail]]:
        """Park a named operation's worker thread inside the connection's turn.

        ``arm(operation)`` wraps the private method that operation does its SQL in
        (:data:`_SYNC_METHODS`) — inside ``async with self._lock`` and inside the worker
        the event loop cannot interrupt, which is exactly where ADR-0054's bug lived — so
        the first worker to reach it blocks and every later one runs free.

        Its own trail on its own connection, not the ``ephemeral`` fixture's: the
        suspended worker is parked for the length of the case, and sharing would make an
        unrelated failure hang instead of fail.
        """
        trail = SqliteRoutingTrail(path=":memory:", max_rows=_ROOMY)
        log = ResourceLog()
        suspension = ThreadSuspension()

        def arm(operation: str) -> SuspendedCall:
            attribute = _SYNC_METHODS[operation]
            original = getattr(trail, attribute)
            armed = threading.Event()

            def blocking(*args: object) -> object:
                with log.inside():  # the span the connection is genuinely in use for
                    if not armed.is_set():  # the first worker only; later ones run free
                        armed.set()
                        suspension.hold()
                    return original(*args)

            setattr(trail, attribute, blocking)
            return suspension

        try:
            yield SuspendedMidWrite(store=trail, log=log, arm=arm)
        finally:
            suspension.release()
            # An implementation that released the connection early leaves a worker still
            # using it; closing under that is a native crash rather than a reported
            # failure, so give the worker a turn to unwind and let the assertion above be
            # the thing that speaks.
            await asyncio.sleep(0.05)
            trail.close()


class TestSqliteRoutingTrailSatisfiesTheNarrowSeam(RoutingRecorderContract):
    """The concrete store, run through the *narrow* seam's suite (ADR-0197 §12).

    ADR-0197 §9's "one concrete store satisfies them" as a test rather than an assertion.
    Deliberately a separate class from :class:`TestSqliteRoutingTrailContract`: that one
    binds the store to the wider suite through ``trail``, and this one binds it through
    ``recorder`` — which is the fixture the routing stage is handed, and therefore the one
    whose behaviour the composition root actually depends on.
    """

    @pytest.fixture
    def recorder(self, ephemeral: SqliteRoutingTrail) -> RoutingRecorder:
        return ephemeral

    async def written(self, recorder: RoutingRecorder) -> list[RoutedOperationRecord]:
        """Read back through ``export``, since this subject has one."""
        assert isinstance(recorder, SqliteRoutingTrail)
        return list(await recorder.export())


# --- what only a durable store can be asked ---------------------------------


@pytest.mark.integration
async def test_a_routed_decision_survives_the_process_that_recorded_it(tmp_path: Path) -> None:
    """The half this implementation exists for (ADR-0004 §7, ADR-0197 §9).

    "Did the assistant destroy a belief because a model chose to" has to be answerable
    *later*, and a routed ``forget`` is the one act that destroys the only other evidence
    of itself. A trail that forgot on restart would satisfy every clause in the suite and
    none of the decision.
    """
    database = tmp_path / "routing.db"
    first = SqliteRoutingTrail(path=database, max_rows=_ROOMY)
    try:
        await first.record(routed_operation_record(record_id="r-1", route_id="route-1"))
        await first.record(
            routed_operation_record(
                record_id="r-2", route_id="route-1", approval=RouteApproval.GIVEN
            )
        )
    finally:
        first.close()

    second = SqliteRoutingTrail(path=database, max_rows=_ROOMY)
    try:
        reloaded = await second.export()
    finally:
        second.close()

    assert [(row.id, row.approval) for row in reloaded] == [
        ("r-1", RouteApproval.OWED),
        ("r-2", RouteApproval.GIVEN),
    ]


@pytest.mark.integration
async def test_the_route_state_machine_survives_a_reopen(tmp_path: Path) -> None:
    """The state machine is the file's, not the process's (ADR-0197 §9).

    A check held only in memory would let a restart admit a second answer to a question
    already answered, which is the one thing the append-only trail must never hold.
    """
    database = tmp_path / "routing.db"
    first = SqliteRoutingTrail(path=database, max_rows=_ROOMY)
    try:
        await first.record(routed_operation_record(record_id="r-1", route_id="route-1"))
        await first.record(
            routed_operation_record(
                record_id="r-2", route_id="route-1", approval=RouteApproval.GIVEN
            )
        )
    finally:
        first.close()

    second = SqliteRoutingTrail(path=database, max_rows=_ROOMY)
    try:
        with pytest.raises(RoutingTrailError, match="already answered"):
            await second.record(
                routed_operation_record(
                    record_id="r-3", route_id="route-1", approval=RouteApproval.REFUSED
                )
            )
        assert len(await second.export()) == 2
    finally:
        second.close()


@pytest.mark.integration
async def test_the_prune_survives_a_reopen(tmp_path: Path) -> None:
    """The horizon is the file's, not the process's (ADR-0197 §9).

    A cap held only in memory would let a restart start counting again, so a hub restarted
    every hour would hold an unbounded trail — the exact failure the row cap exists to
    prevent.
    """
    database = tmp_path / "routing.db"
    first = SqliteRoutingTrail(path=database, max_rows=2)
    try:
        for index in range(2):
            await first.record(
                routed_operation_record(
                    RoutableOperation.SPEND_TOTALS,
                    record_id=f"r-{index}",
                    route_id=f"route-{index}",
                )
            )
    finally:
        first.close()

    second = SqliteRoutingTrail(path=database, max_rows=2)
    try:
        await second.record(
            routed_operation_record(
                RoutableOperation.SPEND_TOTALS, record_id="r-2", route_id="route-2"
            )
        )
        held = [row.id for row in await second.export()]
    finally:
        second.close()

    assert held == ["r-1", "r-2"]


@pytest.mark.integration
def test_the_database_lives_where_it_was_told_to_and_is_owner_only(tmp_path: Path) -> None:
    """ADR-0197 §9's residency clause, as a test rather than as prose.

    "It is the one clause of §9 that a working store can violate while every other test
    passes." A row names the subject of a model-selected operation against the owner's own
    memory and the conversation it ran under, so the file is Tier 1: it is created under
    the directory it was given — nothing outside it is opened — and the mode is set
    **before** the first statement, because a journal opened while the file still carried
    the process umask would be world-readable and would hold the same pages (#489, #490).
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database = data_dir / "routing.db"

    trail = SqliteRoutingTrail(path=database, max_rows=_ROOMY)
    try:
        assert database.exists()
        assert stat.S_IMODE(database.stat().st_mode) == 0o600
        assert {entry.name for entry in tmp_path.iterdir()} == {"data"}
        assert {entry.parent for entry in data_dir.iterdir()} == {data_dir}
    finally:
        trail.close()


@pytest.mark.integration
def test_a_labelled_schema_this_code_cannot_read_is_refused(tmp_path: Path) -> None:
    """Refused at open rather than read blindly (ADR-0049 §1's ordering).

    Reading a future schema would let a downgrade construct successfully and fail later
    with a raw ``sqlite3`` error, which is a fault to report at open — the posture
    ``SqliteSourceReadTrail`` and ``SqliteSourceGrantStore`` already take.
    """
    database = tmp_path / "routing.db"
    conn = sqlite3.connect(database)
    try:
        conn.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '99')")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(RoutingTrailError, match="schema_version=99"):
        SqliteRoutingTrail(path=database, max_rows=_ROOMY)


@pytest.mark.integration
def test_a_trail_that_cannot_be_opened_reports_this_seams_error(tmp_path: Path) -> None:
    """A missing parent directory is this seam's error, not a raw ``sqlite3`` one."""
    with pytest.raises(RoutingTrailError, match="failed to open"):
        SqliteRoutingTrail(path=tmp_path / "absent" / "routing.db", max_rows=_ROOMY)


def test_a_path_the_driver_refuses_outright_is_still_this_seams_error() -> None:
    """A path with an embedded NUL leaves ``sqlite3.connect`` as a ``ValueError``.

    Neither a ``sqlite3.Error`` nor an ``OSError``, so a clause catching only those
    two lets a bare builtin escape the boundary this constructor documents — the
    hole #1933 records across nine stores, closed here rather than reproduced.

    **The confusion is worse on this trail than it was on the grant store**: the
    constructor already raises ``ValueError`` for a ``max_rows`` it refuses, so a
    caller who wrote ``except ValueError`` around the construction would read "that
    path cannot be opened" as "you passed a bad cap".

    No ``integration`` mark: ``connect`` refuses the path before any file is
    touched, so this reaches no filesystem.
    """
    with pytest.raises(RoutingTrailError, match="failed to open"):
        SqliteRoutingTrail(path="routing\x00.db", max_rows=_ROOMY)


async def test_a_row_that_no_longer_validates_is_reported_rather_than_handed_on(
    ephemeral: SqliteRoutingTrail,
) -> None:
    """A corrupted or downgraded file is a fault to report, never a record to hand on."""
    await ephemeral.record(routed_operation_record(record_id="r-1"))
    ephemeral._conn.execute("UPDATE routes SET data = ?", ('{"id": "r-1"}',))

    with pytest.raises(RoutingTrailError, match="no longer validates"):
        await ephemeral.export()


async def test_the_sequence_is_never_reused_after_a_clear(
    ephemeral: SqliteRoutingTrail,
) -> None:
    """``AUTOINCREMENT``, and the reason it is not decoration (ADR-0197 §9).

    ``clear`` removes every row including the largest, so without it SQLite is free to
    reuse a rowid — and a reused sequence would make a later row sort before an earlier
    one, which is the one thing the ordering column exists to prevent.
    """
    await ephemeral.record(routed_operation_record(record_id="r-1", route_id="route-1"))
    await ephemeral.clear()
    await ephemeral.record(routed_operation_record(record_id="r-2", route_id="route-2"))
    await ephemeral.record(routed_operation_record(record_id="r-3", route_id="route-3"))

    assert [row.id for row in await ephemeral.export()] == ["r-2", "r-3"]
    assert [row.id for row in await ephemeral.recent(limit=2)] == ["r-3", "r-2"]


async def test_the_written_row_carries_no_column_beside_its_blob_and_its_keys(
    ephemeral: SqliteRoutingTrail,
) -> None:
    """The blob is the record; the three columns beside it exist only to order and join.

    A store that unpacked fields into columns would have two representations of one row
    and a migration owed the first time either moved.
    """
    await ephemeral.record(routed_operation_record(record_id="r-1"))

    columns = {row[1] for row in ephemeral._conn.execute("PRAGMA table_info(routes)")}
    assert columns == {"seq", "id", "route_id", "data"}


async def test_a_naive_decided_at_never_reaches_the_file(
    ephemeral: SqliteRoutingTrail,
) -> None:
    """Validation happens before the write, not on the way back out.

    A record corrupted past its frozen model's guard would otherwise be stored and make
    every later read of the trail incoherent — and the store would then be the thing that
    failed, at a moment unrelated to the caller that wrote it.
    """
    corrupted = routed_operation_record(record_id="r-1")
    object.__setattr__(corrupted, "decided_at", datetime(2026, 8, 27, 12, 0))  # noqa: DTZ001 — the naive instant is the subject

    with pytest.raises(RoutingTrailError, match="not a valid record"):
        await ephemeral.record(corrupted)

    assert await ephemeral.export() == ()


async def test_closing_twice_is_not_an_error() -> None:
    """Shutdown paths run more than once; a second close is a no-op, not a fault."""
    trail = SqliteRoutingTrail(path=":memory:", max_rows=_ROOMY)
    trail.close()
    trail.close()


async def test_a_cap_at_the_widest_bindable_value_still_records() -> None:
    """The admissible range's top end is usable rather than merely accepted.

    ``2**63 - 1`` is the widest value SQLite will bind, and the cap is bound as the
    prune's ``OFFSET`` on **every** append — so a store that accepted it at construction
    and then raised ``OverflowError`` on the first record would pass every other case here.
    """
    trail = SqliteRoutingTrail(path=":memory:", max_rows=2**63 - 1)
    try:
        await trail.record(routed_operation_record(record_id="r-1"))

        assert [row.id for row in await trail.export()] == ["r-1"]
    finally:
        trail.close()


@pytest.mark.parametrize("cap", ["1000", 1.0, None])
def test_a_cap_that_is_not_an_integer_at_all_is_refused(cap: object) -> None:
    """``Settings`` refuses it at load; the store restates the rule where it is used.

    A trail built from a future configuration that reads no setting must not be able to
    hold a cap it cannot bind, and a string or a float would reach the prune's ``OFFSET``
    as a value SQLite reads differently from the number the operator wrote.
    """
    with pytest.raises(TypeError, match="exactly an int"):
        SqliteRoutingTrail(path=":memory:", max_rows=cap)  # type: ignore[arg-type]


async def test_an_identical_retry_does_not_disturb_the_horizon() -> None:
    """The idempotent path appends nothing, so it prunes nothing either.

    A store that ran the prune on the retry would evict a row for a write that did not
    happen — the bound applied to a no-op, which is the one way an idempotent call can
    still cost history.
    """
    trail = SqliteRoutingTrail(path=":memory:", max_rows=2)
    try:
        rows = [
            routed_operation_record(
                RoutableOperation.QUESTIONS, record_id=f"r-{index}", route_id=f"route-{index}"
            )
            for index in range(2)
        ]
        for row in rows:
            await trail.record(row)

        await trail.record(rows[1])

        assert [row.id for row in await trail.export()] == ["r-0", "r-1"]
    finally:
        trail.close()


async def test_a_row_recorded_under_a_widened_vocabulary_still_reloads() -> None:
    """Every member of §3's vocabulary survives the file, not only the ones a case names.

    A store that special-cased the shapes its author had in mind would fail the first time
    the vocabulary was widened under §3's rule, at the site furthest from the widening.
    """
    trail = SqliteRoutingTrail(path=":memory:", max_rows=_ROOMY)
    try:
        for index, operation in enumerate(RoutableOperation):
            await trail.record(
                routed_operation_record(
                    operation,
                    record_id=f"r-{index}",
                    route_id=f"route-{index}",
                    decided_at=datetime(2026, 8, 27, 12, 0, tzinfo=UTC),
                )
            )

        held = await trail.export()
    finally:
        trail.close()

    assert [row.operation for row in held] == list(RoutableOperation)
