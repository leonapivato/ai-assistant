"""The SQLite source-read trail, against its shared conformance suites and beyond.

The suites cover what every implementation owes: write-once, the six outcomes, the
two construction invariants, ADR-0185 §6's prune and its direction, recording order
against ``checked_at``, bounds, erasure, and detachment on both paths. What they
cannot cover is the half this implementation exists for — that a read the system
took, and a read it was refused, are still on file once the process that recorded
them has gone (ADR-0004 §7, ADR-0139 §6).

**Both bindings are here, and the second is what ADR-0185 §12 asks for by name.**
``TestSqliteSourceReadTrailContract`` runs the concrete store through the wide
suite; ``TestSqliteSourceReadTrailSatisfiesTheNarrowSeam`` runs the same class
through the ``SourceReadRecorder`` one — "so the store's satisfaction of the narrow
seam is evidence rather than assertion". That is what makes a composition root's
one-object-three-drivers wiring sound rather than merely plausible.

The conformance subclasses run against ``:memory:``, so they touch no filesystem
and need no ``integration`` mark. The tests that open a real file say so.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import stat
import threading
from datetime import datetime
from typing import TYPE_CHECKING

import pytest
from source_read_contract import (
    SOURCE,
    SourceReadRecorderContract,
    SourceReadTrailContract,
)

from ai_assistant.core.errors import ReadTrailError
from ai_assistant.core.types import GrantScope, ReadOutcome
from ai_assistant.permissions import SqliteSourceReadTrail
from ai_assistant.testing.cancellation import ResourceLog, SuspendedMidWrite, ThreadSuspension
from ai_assistant.testing.reads import source_read_record

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator
    from pathlib import Path

    from ai_assistant.core.protocols import SourceReadRecorder, SourceReadTrail
    from ai_assistant.core.types import SourceReadRecord
    from ai_assistant.testing.cancellation import SuspendedCall

#: Big enough that no conformance case trips the prune by accident. The prune's own
#: cases build their own trail through ``bounded``.
_ROOMY = 1_000


@pytest.fixture
def ephemeral() -> Iterator[SqliteSourceReadTrail]:
    """An in-memory trail, closed after the test."""
    trail = SqliteSourceReadTrail(path=":memory:", max_rows=_ROOMY)
    try:
        yield trail
    finally:
        trail.close()


#: The private method each locked operation does its SQL in, which ADR-0060's hook
#: wraps to park a worker thread inside the connection's turn. Spelled out rather
#: than derived from the operation name, because the two reads have different
#: helpers and neither is named for the contract method that takes the lock around
#: it.
_SYNC_METHODS = {
    "record": "_record_sync",
    "clear": "_clear_sync",
    "recent": "_newest_first_sync",
    "export": "_recording_order_sync",
}


class TestSqliteSourceReadTrailContract(SourceReadTrailContract):
    """Runs SqliteSourceReadTrail through the shared SourceReadTrail suite."""

    @pytest.fixture
    def trail(self, ephemeral: SqliteSourceReadTrail) -> SourceReadTrail:
        return ephemeral

    @contextlib.asynccontextmanager
    async def bounded(self, max_rows: int) -> AsyncIterator[SourceReadTrail]:
        """An in-memory trail at ``max_rows``, closed when the case is done.

        The construction refusal ADR-0185 §6 requires happens *before* there is
        anything to close, which is why the ``try`` starts after it.
        """
        subject = SqliteSourceReadTrail(path=":memory:", max_rows=max_rows)
        try:
            yield subject
        finally:
            subject.close()

    @contextlib.asynccontextmanager
    async def trail_suspended_mid_write(
        self,
    ) -> AsyncIterator[SuspendedMidWrite[SourceReadTrail]]:
        """Park a named operation's worker thread inside the connection's turn.

        ``arm(operation)`` wraps the private method that operation does its SQL in
        (:data:`_SYNC_METHODS`) — inside ``async with self._lock`` and inside the
        worker the event loop cannot interrupt, which is exactly where ADR-0054's
        bug lived — so the first worker to reach it blocks and every later one runs
        free. Blocking there is what makes the case deterministic: left to run, a
        commit finishes in microseconds and whether the second caller arrives while
        the worker still holds the connection would be a race.

        Its own trail on its own connection, not the ``ephemeral`` fixture's: the
        suspended worker is parked for the length of the case, and sharing would
        make an unrelated failure hang instead of fail.
        """
        trail = SqliteSourceReadTrail(path=":memory:", max_rows=_ROOMY)
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
            # An implementation that released the connection early leaves a worker
            # still using it; closing under that is a native crash rather than a
            # reported failure, so give the worker a turn to unwind and let the
            # assertion above be the thing that speaks.
            await asyncio.sleep(0.05)
            trail.close()


class TestSqliteSourceReadTrailSatisfiesTheNarrowSeam(SourceReadRecorderContract):
    """The concrete store, run through the *narrow* seam's suite (ADR-0185 §12).

    ADR-0185 §4's "one ``permissions/`` class implementing all four members
    satisfies both seams" as a test rather than an assertion. Deliberately a
    separate class from :class:`TestSqliteSourceReadTrailContract`: that one binds
    the store to the wider suite through ``trail``, and this one binds it through
    ``recorder`` — which is the fixture every *driver* is handed, and therefore the
    one whose behaviour the composition root actually depends on.
    """

    @pytest.fixture
    def recorder(self, ephemeral: SqliteSourceReadTrail) -> SourceReadRecorder:
        return ephemeral

    async def written(self, recorder: SourceReadRecorder) -> list[SourceReadRecord]:
        """Read back through ``export``, since this subject has one."""
        assert isinstance(recorder, SqliteSourceReadTrail)
        return await recorder.export()


# --- what only a durable store can be asked ---------------------------------


@pytest.mark.integration
async def test_a_recorded_attempt_survives_the_process_that_recorded_it(
    tmp_path: Path,
) -> None:
    """The half this implementation exists for (ADR-0004 §7, ADR-0139 §6).

    "Was this source read after I revoked it" has to be answerable *later*, which is
    the whole difference between this and ADR-0097 §8's operator log line — the one
    ADR-0139 §6 dismisses because it "is not durable state and is not exportable".
    A trail that forgot on restart would satisfy every clause in the suite and none
    of the decision.
    """
    database = tmp_path / "reads.db"
    first = SqliteSourceReadTrail(path=database, max_rows=_ROOMY)
    try:
        await first.record(
            source_read_record(
                SOURCE,
                record_id="r-1",
                use=GrantScope.FACET,
                outcome=ReadOutcome.REFUSED,
            )
        )
    finally:
        first.close()

    second = SqliteSourceReadTrail(path=database, max_rows=_ROOMY)
    try:
        (reloaded,) = await second.export()
    finally:
        second.close()

    assert reloaded.id == "r-1"
    assert reloaded.outcome is ReadOutcome.REFUSED
    assert reloaded.grant is None


@pytest.mark.integration
async def test_the_prune_survives_a_reopen(tmp_path: Path) -> None:
    """The horizon is the file's, not the process's (ADR-0185 §6, §10).

    A cap held only in memory would let a restart start counting again, so a hub
    restarted every hour would hold an unbounded trail — the exact failure the row
    cap exists to prevent, arriving through the one thing this store does that the
    fake cannot model.
    """
    database = tmp_path / "reads.db"
    first = SqliteSourceReadTrail(path=database, max_rows=2)
    try:
        for index in range(2):
            await first.record(source_read_record(record_id=f"r-{index}"))
    finally:
        first.close()

    second = SqliteSourceReadTrail(path=database, max_rows=2)
    try:
        await second.record(source_read_record(record_id="r-2"))
        held = [row.id for row in await second.export()]
    finally:
        second.close()

    assert held == ["r-1", "r-2"]


@pytest.mark.integration
def test_the_database_and_its_sidecars_are_owner_only(tmp_path: Path) -> None:
    """ADR-0004 §4 reaches this file exactly as it reaches its neighbours.

    A row names a source the user connected and the grant it was read under, so the
    file is Tier 1 and the mode is set **before** the first statement — a journal
    opened while the file still carried the process umask would be world-readable
    and would hold the same pages (#489, #490).
    """
    database = tmp_path / "reads.db"
    trail = SqliteSourceReadTrail(path=database, max_rows=_ROOMY)
    try:
        assert stat.S_IMODE(database.stat().st_mode) == 0o600
    finally:
        trail.close()


@pytest.mark.integration
def test_a_labelled_schema_this_code_cannot_read_is_refused(tmp_path: Path) -> None:
    """Refused at open rather than read blindly (ADR-0049 §1's ordering).

    Reading a future schema would let a downgrade construct successfully and fail
    later with a raw ``sqlite3`` error, which is a fault to report at open — the
    posture ``SqlitePlanStore`` and ``SqliteSourceGrantStore`` already take.
    """
    database = tmp_path / "reads.db"
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '99')")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(ReadTrailError, match="schema_version=99"):
        SqliteSourceReadTrail(path=database, max_rows=_ROOMY)


@pytest.mark.integration
def test_a_trail_that_cannot_be_opened_reports_this_seams_error(tmp_path: Path) -> None:
    """No ``sqlite3.Error`` or ``OSError`` leaves this layer's boundary."""
    with pytest.raises(ReadTrailError, match="failed to open"):
        SqliteSourceReadTrail(path=tmp_path / "no-such-directory" / "reads.db", max_rows=_ROOMY)


async def test_a_row_that_no_longer_validates_is_reported_rather_than_handed_on(
    ephemeral: SqliteSourceReadTrail,
) -> None:
    """A corrupted or downgraded database is a fault to report, not a record to serve.

    ``AuditTrail``'s posture applied here: a store that handed back whatever a
    tampered blob decoded to would let a row *say* the read completed under a grant
    that never authorised it, which is the one thing an audit record may not do.
    """
    await ephemeral.record(source_read_record(record_id="r-1"))
    # Reaching past the store's own writer is the whole point of this case: no
    # conforming caller can produce a row that fails its own model.
    ephemeral._conn.execute("UPDATE reads SET data = ? WHERE id = ?", ('{"id": "r-1"}', "r-1"))
    ephemeral._conn.commit()

    with pytest.raises(ReadTrailError, match="no longer validates"):
        await ephemeral.export()


async def test_the_sequence_is_never_reused_after_a_clear(
    ephemeral: SqliteSourceReadTrail,
) -> None:
    """Recording order is a monotonic sequence, and ``clear`` must not rewind it.

    Without ``AUTOINCREMENT`` SQLite is free to reuse a rowid once the largest row
    is gone, and ``clear`` removes every row including the largest — so a row
    written after a clear could sort *before* one written before it if the trail
    were ever repopulated from two sources. The prune and both reads are decided by
    that column, which is why it is pinned rather than trusted to the schema.
    """
    await ephemeral.record(source_read_record(record_id="r-1"))
    await ephemeral.clear()
    await ephemeral.record(source_read_record(record_id="r-2"))

    rows = ephemeral._conn.execute("SELECT seq FROM reads").fetchall()
    assert [row[0] for row in rows] == [2]


async def test_the_written_row_carries_no_column_beside_its_blob_and_its_keys(
    ephemeral: SqliteSourceReadTrail,
) -> None:
    """The blob is the record; the columns exist only so SQLite can order and constrain.

    A projection column is a second spelling of a value the blob already carries, and
    a store that grew one would have two places for the same fact to disagree —
    ``SqliteAuditTrail`` pays that cost knowingly for the queries ADR-0044 needs, and
    this store has no query that needs one (ADR-0185 §12: "no query by source and no
    count").
    """
    columns = {row[1] for row in ephemeral._conn.execute("PRAGMA table_info(reads)")}

    assert columns == {"seq", "id", "data"}


async def test_a_naive_checked_at_never_reaches_the_file(
    ephemeral: SqliteSourceReadTrail,
) -> None:
    """The refusal is judged on the snapshot, and the file is what is asserted.

    The suite asserts the refusal through ``export``; this asserts it against the
    table, because a store that inserted and *then* raised would leave the row on
    disk while every in-memory read looked correct.
    """
    corrupted = source_read_record(record_id="r-1")
    object.__setattr__(corrupted, "checked_at", datetime(2026, 7, 20, 12, 0))  # noqa: DTZ001

    with pytest.raises(ReadTrailError):
        await ephemeral.record(corrupted)

    assert ephemeral._conn.execute("SELECT COUNT(*) FROM reads").fetchone()[0] == 0


async def test_closing_twice_is_not_an_error() -> None:
    """Shutdown is ordered and idempotent (ADR-0083 ruling 4)."""
    trail = SqliteSourceReadTrail(path=":memory:", max_rows=_ROOMY)

    trail.close()
    trail.close()


async def test_a_cap_at_the_widest_bindable_value_still_records() -> None:
    """The refusal's boundary is in the right place, which a refusal alone cannot show.

    ADR-0185 §6's admissible range is "every strictly positive integer **below**
    ``2**63``", so ``2**63 - 1`` is admissible and must actually work: the cap is
    bound as the prune's ``OFFSET`` on every append, so a store that refused one step
    too early would be rejecting a configuration the ADR permits, and one that
    refused one step too late would raise ``OverflowError`` out of its own error
    boundary. Only driving a record at the edge distinguishes the three.
    """
    trail = SqliteSourceReadTrail(path=":memory:", max_rows=2**63 - 1)
    try:
        assert await trail.record(source_read_record(record_id="r-1")) == "r-1"
        assert [row.id for row in await trail.export()] == ["r-1"]
    finally:
        trail.close()


@pytest.mark.parametrize("cap", [1.0, "5"], ids=["a float", "a string"])
def test_a_cap_that_is_not_an_integer_at_all_is_refused(cap: object) -> None:
    """The exact-type guard, beyond the ``bool`` case the shared suite drives.

    ``Settings`` refuses these at load through ``_exactly_an_integer``; this store
    holds the figure and restates the rule where it is used, so a trail built from a
    configuration that reads no setting — a test, a future composition — cannot hold
    a cap the comparisons below would answer nonsense for.
    """
    with pytest.raises(TypeError, match="exactly an int"):
        SqliteSourceReadTrail(path=":memory:", max_rows=cap)  # type: ignore[arg-type]  # the subject
