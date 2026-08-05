"""The SQLite source-grant store, against its shared conformance suite and beyond it.

The suite covers what every ``SourceGrantStore`` owes: write-once, one live grant
per source, the five revocation invariants, the timestamp that is deliberately not
one, ordering, bounds, and detachment on both paths. What it cannot cover is the
half this implementation exists for — that a grant the user made, and a revocation
they made after it, are still on file once the process that recorded them has gone
(ADR-0097 §4).

The conformance subclass runs against ``:memory:``, so it touches no filesystem
and needs no ``integration`` mark. The tests that open a real file say so.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from source_grant_contract import SourceGrantStoreContract

from ai_assistant.core.errors import GrantError, InvalidGrantError
from ai_assistant.core.types import GrantScope
from ai_assistant.permissions import SqliteSourceGrantStore
from ai_assistant.permissions.grants import _run_to_completion
from ai_assistant.testing.cancellation import (
    ResourceLog,
    SuspendedMidWrite,
    ThreadSuspension,
    worker_finished_before_the_first_check,
)
from ai_assistant.testing.grants import DEFAULT_DECIDED_AT, revocation_of, source_grant

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator
    from pathlib import Path

    from ai_assistant.core.protocols import SourceGrantStore
    from ai_assistant.core.types import SourceGrant
    from ai_assistant.testing.cancellation import SuspendedCall

SOURCE = "calendar"


def _journal_mode(database: Path) -> int | None:
    """The permission bits of the rollback journal beside ``database``, or ``None``."""
    journal = database.with_name(f"{database.name}-journal")
    return journal.stat().st_mode & 0o777 if journal.exists() else None


async def _spin() -> None:
    """Let the loop run every ready callback, so a pending task can settle."""
    for _ in range(10):
        await asyncio.sleep(0)


@pytest.fixture
def ephemeral() -> Iterator[SqliteSourceGrantStore]:
    """An in-memory store, closed after the test."""
    store = SqliteSourceGrantStore(path=":memory:")
    try:
        yield store
    finally:
        store.close()


#: The private method each locked operation does its SQL in, which ADR-0060's hook
#: wraps to park a worker thread inside the connection's turn. Spelled out rather
#: than derived from the operation name, because ``recent`` and ``export`` share
#: one ordered reader: ``_ordered_sync`` is named for what it does, not for the two
#: contract methods that each take the lock around it. Wrapping the shared helper
#: still exercises both sites separately, because the case arms immediately before
#: the site under test calls it.
_SYNC_METHODS = {
    "record": "_record_sync",
    "clear": "_clear_sync",
    "live": "_live_sync",
    "recent": "_ordered_sync",
    "export": "_ordered_sync",
}


class TestSqliteSourceGrantStoreContract(SourceGrantStoreContract):
    """Runs SqliteSourceGrantStore through the shared SourceGrantStore suite.

    Inherited from :class:`~source_grant_contract.SourceGrantsContract` too, so the
    narrow seam's three clauses bind this same object — ADR-0097 §3's "one
    implementation satisfies both" tested against the concrete store rather than
    only against the canonical fake.
    """

    @pytest.fixture
    def store(self, ephemeral: SqliteSourceGrantStore) -> SourceGrantStore:
        return ephemeral

    @contextlib.asynccontextmanager
    async def store_suspended_mid_write(
        self,
    ) -> AsyncIterator[SuspendedMidWrite[SourceGrantStore]]:
        """Park a named operation's worker thread inside the connection's turn.

        ``arm(operation)`` wraps the private method that operation does its SQL in
        (:data:`_SYNC_METHODS`) — inside ``async with self._lock`` and inside the
        worker the event loop cannot interrupt, which is exactly where ADR-0054's
        bug lived — so the first worker to reach it blocks and every later one runs
        free. Each distinct lock site is a separate place the bug can reappear, the
        locked *reads* included. Blocking there is what makes the case
        deterministic: left to run, a commit finishes in microseconds and whether
        the second caller arrives while the worker still holds the connection would
        be a race.

        Its own store on its own connection, not the ``ephemeral`` fixture's: the
        suspended worker is parked for the length of the case, and sharing would
        make an unrelated failure hang instead of fail.
        """
        store = SqliteSourceGrantStore(path=":memory:")
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
            # assertion above be the thing that speaks.
            await asyncio.sleep(0.05)
            store.close()


# --- refusals and their shape ----------------------------------------------


async def test_a_refused_write_leaves_the_store_untouched(
    ephemeral: SqliteSourceGrantStore,
) -> None:
    """A rejected append must not half-happen.

    The contract exercises atomicity against a race; this is the same property from
    the other side — a refusal is not a partial write with an exception on top.
    """
    granted = source_grant(SOURCE, grant_id="g-1")
    await ephemeral.record(granted)

    with pytest.raises(InvalidGrantError):
        await ephemeral.record(source_grant(SOURCE, grant_id="g-2"))

    assert [held.id for held in await ephemeral.export()] == ["g-1"]
    live = await ephemeral.live(source=SOURCE, use=GrantScope.FACET)
    assert live is not None
    assert live.id == "g-1"


@contextlib.contextmanager
def _traced(store: SqliteSourceGrantStore) -> Iterator[list[str]]:
    """Collect every statement the store's connection runs inside the block."""
    statements: list[str] = []
    store._conn.set_trace_callback(statements.append)
    try:
        yield statements
    finally:
        store._conn.set_trace_callback(None)


def _assert_one_immediate_transaction(
    statements: list[str], *, what: str, closes: str = "COMMIT"
) -> None:
    """Assert ``what`` ran inside exactly one ``BEGIN IMMEDIATE`` that it closed.

    Three properties, each of which a change to how the transaction is *spelled*
    can break without breaking any behavioural test:

    * the **first** statement is ``BEGIN IMMEDIATE``, so the duplicate-id,
      live-grant and revocation checks sit inside the write lock rather than in
      front of it — the window #526 is about, which a staged race cannot see,
      because a race can only prove the lock excludes, never *when* it was taken;
    * exactly **one** ``BEGIN``, since a second on the shared connection raises;
    * the **last** statement closes it — ``COMMIT``, or ``ROLLBACK`` where the
      block was left by a refusal — so no arm abandons an open transaction that
      would poison the next caller's ``BEGIN``.

    ``SqliteMemoryStore`` has carried the same assertion since #526
    (``_assert_opens_with_the_write_lock``); this is that pin for this store.
    """
    assert statements, f"{what} ran no SQL at all"
    opened = statements[0].strip()
    assert opened.upper() == "BEGIN IMMEDIATE", (
        f"{what} began with {opened!r}. The write lock has to be the *first* "
        f"statement: a `BEGIN IMMEDIATE` issued any later leaves every read before "
        f"it outside the transaction, which is the exposure #526 names."
    )
    begins = [one for one in statements if one.strip().upper().startswith("BEGIN")]
    assert len(begins) == 1, f"{what} opened {len(begins)} transactions: {begins}"
    assert statements[-1].strip().upper() == closes, (
        f"{what} ended with {statements[-1]!r} rather than {closes}, so it left a "
        f"transaction open on the shared connection"
    )


async def test_recording_opens_and_closes_exactly_one_immediate_transaction(
    ephemeral: SqliteSourceGrantStore,
) -> None:
    """Every arm of ``record``: the append, and the three refusals that leave early.

    The refusals are the ones that matter structurally — ``InvalidGrantError`` is
    not a ``sqlite3.Error``, so it leaves the block by an exception the
    transaction still has to be closed on the way out of.
    """
    granted = source_grant(SOURCE, grant_id="g-1")

    with _traced(ephemeral) as statements:
        await ephemeral.record(granted)
    _assert_one_immediate_transaction(statements, what="record (grant)")

    with _traced(ephemeral) as statements, pytest.raises(InvalidGrantError):
        await ephemeral.record(source_grant(SOURCE, grant_id="g-1"))
    _assert_one_immediate_transaction(
        statements, what="record (refused: duplicate id)", closes="ROLLBACK"
    )

    with _traced(ephemeral) as statements, pytest.raises(InvalidGrantError):
        await ephemeral.record(source_grant(SOURCE, grant_id="g-2"))
    _assert_one_immediate_transaction(
        statements, what="record (refused: source already granted)", closes="ROLLBACK"
    )

    with _traced(ephemeral) as statements, pytest.raises(InvalidGrantError):
        await ephemeral.record(revocation_of(source_grant("other", grant_id="g-ghost")))
    _assert_one_immediate_transaction(
        statements, what="record (refused: revokes nothing on file)", closes="ROLLBACK"
    )

    with _traced(ephemeral) as statements:
        await ephemeral.record(revocation_of(granted, grant_id="g-revoke"))
    _assert_one_immediate_transaction(statements, what="record (revocation)")

    assert ephemeral._conn.in_transaction is False


async def test_a_refusal_is_catchable_as_the_store_fault_too(
    ephemeral: SqliteSourceGrantStore,
) -> None:
    """``InvalidGrantError`` is a ``GrantError``, which is what makes §5a work.

    A driver fails closed on "the store could not answer" and refuses on "your
    record was refused", so the two must be distinguishable — and a caller that
    only wants "something went wrong with grants" must still get one handler
    (ADR-0097 §10).
    """
    with pytest.raises(GrantError):
        await ephemeral.record(revocation_of(source_grant(SOURCE, grant_id="g-1")))


@pytest.mark.parametrize("field", ["id", "source", "scope", "decided_at"])
async def test_a_record_missing_a_field_is_refused_not_a_raw_attribute_error(
    ephemeral: SqliteSourceGrantStore, field: str
) -> None:
    """A ``__dict__`` a field was *deleted* from is the case the suite does not reach.

    The shared suite corrupts a record by *substituting* a value, which leaves
    every attribute present. Deleting one is the other half of the same access —
    ``frozen=True`` refuses neither — and it is where a refusal message composed
    through ``grant.id`` stops being a refusal: the attribute is gone, so building
    the message raises a bare ``AttributeError`` out of the handler and this
    layer's error boundary leaks a builtin instead of saying the record was
    refused.

    ``id`` is the sharp one because it is what the message names; the other three
    are here so the answer is about the shape rather than about one field.
    """
    corrupted = source_grant(SOURCE, grant_id="g-1")
    object.__getattribute__(corrupted, "__dict__").pop(field)

    with pytest.raises(InvalidGrantError, match="not a valid record"):
        await ephemeral.record(corrupted)

    assert await ephemeral.export() == []


async def test_the_one_revocation_per_grant_rule_is_also_a_database_constraint(
    ephemeral: SqliteSourceGrantStore,
) -> None:
    """The checked read gives the friendly error; the unique index is the net.

    ``_check_revocation`` is a read followed by a write, and the whole of ``record``
    runs inside one ``BEGIN IMMEDIATE`` so nothing can interleave — but the
    invariant is worth a durable constraint as well, for the same reason
    ``decisions_resolves`` exists on the trail: a bug in the check would otherwise
    write a history the contract says cannot exist. Asserted by going behind the
    store to the connection, which is the only way to reach the index.
    """
    granted = source_grant(SOURCE, grant_id="g-1")
    await ephemeral.record(granted)
    first = revocation_of(granted, grant_id="r-1")
    await ephemeral.record(first)

    with pytest.raises(sqlite3.IntegrityError):
        ephemeral._conn.execute(
            "INSERT INTO grants(id, source, decided_at_us, revokes, data) "
            "VALUES ('r-2', ?, 0, 'g-1', ?)",
            (SOURCE, first.model_dump_json()),
        )


async def test_two_grants_a_microsecond_apart_order_correctly(
    ephemeral: SqliteSourceGrantStore,
) -> None:
    """The sort key is exact, so ``recent`` cannot invert two adjacent records.

    An epoch *float* carrying microsecond precision needs sixteen significant
    digits at present-day values, which is right at the edge of a double — so two
    records a microsecond apart could compare equal or invert. The integer key
    below is why they do not.
    """
    await ephemeral.record(source_grant("a", grant_id="g-1", decided_at=DEFAULT_DECIDED_AT))
    await ephemeral.record(
        source_grant("b", grant_id="g-2", decided_at=DEFAULT_DECIDED_AT + timedelta(microseconds=1))
    )

    assert [held.id for held in await ephemeral.recent()] == ["g-2", "g-1"]


# --- the store as a reader of its own file ----------------------------------


async def test_a_row_the_model_no_longer_accepts_is_reported_not_returned(
    ephemeral: SqliteSourceGrantStore,
) -> None:
    """A corrupt row is a fault to report, never a record to hand on.

    Reported as the ``GrantError`` **base** rather than ``InvalidGrantError``:
    nothing the caller handed in was refused, the store itself is unreadable, and a
    driver's fail-closed branch is exactly the right response (ADR-0097 §5a).
    """
    await ephemeral.record(source_grant(SOURCE, grant_id="g-1"))
    ephemeral._conn.execute("UPDATE grants SET data = '{\"id\": \"g-1\"}' WHERE id = 'g-1'")

    with pytest.raises(GrantError) as export_error:
        await ephemeral.export()
    with pytest.raises(GrantError):
        await ephemeral.live(source=SOURCE, use=GrantScope.FACET)

    assert not isinstance(export_error.value, InvalidGrantError)


async def test_two_live_grants_for_one_source_are_refused_rather_than_picked_from(
    ephemeral: SqliteSourceGrantStore,
) -> None:
    """A store that cannot say what the user granted must not answer the gate.

    ADR-0097 §4 guarantees at most one live grant per source and ``record`` is what
    keeps it true, so reaching this state needs a hand-edited file. Picking one of
    the two would answer §5's gate from a store whose history contradicts itself;
    reporting fails the read **closed**, which is the same outcome as no grant and
    the one an operator can see.
    """
    first = source_grant(SOURCE, grant_id="g-1", scope=(GrantScope.FACET,))
    await ephemeral.record(first)
    second = source_grant(SOURCE, grant_id="g-2", scope=(GrantScope.INGEST,))
    ephemeral._conn.execute(
        "INSERT INTO grants(id, source, decided_at_us, revokes, data) VALUES (?, ?, 0, NULL, ?)",
        (second.id, second.source, second.model_dump_json()),
    )

    with pytest.raises(GrantError, match="corrupt"):
        await ephemeral.live(source=SOURCE, use=GrantScope.FACET)


async def test_a_fresh_store_records_the_schema_version(
    ephemeral: SqliteSourceGrantStore,
) -> None:
    """A database created here is labelled, so a future migration has a marker to read.

    Exactly one row, so the label is unambiguous. This store ships *with* its
    marker, which is why it needs no ``_migrate``: there is no population of
    unlabelled files in the wild for one to bring forward.
    """
    rows = ephemeral._conn.execute(
        "SELECT key, value FROM meta WHERE key = 'schema_version'"
    ).fetchall()

    assert rows == [("schema_version", "1")]


@pytest.mark.integration
async def test_a_newer_schema_is_refused_before_the_grants_table_exists(tmp_path: Path) -> None:
    """The refusal precedes any write, so a downgrade cannot create or read a table.

    Creating a table is a write, and ADR-0049 §1's ordering puts the version check
    ahead of it. Asserted by the table's *absence* afterwards, which is the only
    observation that distinguishes "refused before" from "refused after".
    """
    path = tmp_path / "grants.db"
    with contextlib.closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '2')")

    with pytest.raises(GrantError, match="schema_version=2"):
        SqliteSourceGrantStore(path=path)

    with contextlib.closing(sqlite3.connect(path)) as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "grants" not in tables


@pytest.mark.integration
@pytest.mark.parametrize(
    "value",
    [pytest.param("not-a-number", id="text"), pytest.param(None, id="null")],
)
async def test_an_unreadable_marker_is_reported_as_a_grant_error(
    tmp_path: Path, value: str | None
) -> None:
    """A corrupt or tampered marker is this layer's error, not a bare builtin.

    ``meta`` may predate this code's ``TEXT`` column or be hand-built with no
    declared type, in which case SQLite hands back whatever was stored. A
    ``ValueError`` or a ``TypeError`` escaping ``__init__`` would leave this layer's
    error boundary through a hole.
    """
    path = tmp_path / "grants.db"
    with contextlib.closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("CREATE TABLE meta(key PRIMARY KEY, value)")
        conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', ?)", (value,))

    with pytest.raises(GrantError, match="schema_version"):
        SqliteSourceGrantStore(path=path)


@pytest.mark.integration
async def test_conflicting_markers_are_refused_rather_than_resolved_by_row_order(
    tmp_path: Path,
) -> None:
    """A store that cannot say which version it is, is one this code cannot read.

    ``CREATE TABLE IF NOT EXISTS`` accepts a pre-existing ``meta`` declared without
    a primary key, so a hand-built file can hold conflicting markers — and reading
    the first row would let an unsupported version through on the strength of a
    sibling that agrees.
    """
    path = tmp_path / "grants.db"
    with contextlib.closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("CREATE TABLE meta(key TEXT, value TEXT)")
        conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '1')")
        conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '2')")

    with pytest.raises(GrantError, match="corrupt"):
        SqliteSourceGrantStore(path=path)


# --- the file on disk -------------------------------------------------------


@pytest.mark.integration
async def test_the_database_file_is_owner_only(tmp_path: Path) -> None:
    """A Tier 1 store on disk (ADR-0004 §4, ADR-0097 §4)."""
    path = tmp_path / "grants.db"
    store = SqliteSourceGrantStore(path=path)
    store.close()

    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.integration
def test_a_journal_opened_during_setup_is_owner_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0004 §1, §4 reach the sidecars, and reach them from the first write (#489).

    SQLite copies the *database file's* mode onto every rollback journal it creates
    for it, so restricting the file after the schema is built leaves every journal
    opened in between carrying the process umask — and an interrupted write leaves
    that journal on disk holding Tier 1 pages beside a ``0600`` base file. Setup's
    ``BEGIN IMMEDIATE`` is exactly such a write.

    Observed **inside** ``_setup`` rather than after it, because that is the only
    place the difference is visible: by the time the constructor returns the
    transaction has committed, and a journal provoked afterwards inherits ``0600``
    under either ordering.

    The file is pre-created ``0644`` so the case does not depend on the runner's
    umask — and because reopening an existing store is the common path anyway.
    """
    path = tmp_path / "grants.db"
    path.touch()
    path.chmod(0o644)
    observed: list[int | None] = []
    original = SqliteSourceGrantStore._check_schema_version

    def observing(store: SqliteSourceGrantStore, conn: sqlite3.Connection) -> bool:
        labelled = original(store, conn)
        observed.append(_journal_mode(path))
        return labelled

    monkeypatch.setattr(SqliteSourceGrantStore, "_check_schema_version", observing)

    SqliteSourceGrantStore(path=path).close()

    assert observed[0] is not None, "setup should have opened a journal"
    assert observed == [0o600]


@pytest.mark.integration
def test_a_sidecar_that_was_already_there_is_restricted_at_open(tmp_path: Path) -> None:
    """ADR-0004 §4 reaches a sidecar this process did not create either (#490).

    SQLite copies the database file's mode onto a sidecar **it creates**, which is
    what makes restricting the file before the first statement enough for those. It
    does nothing for one already on disk: a ``-wal``/``-shm`` left by a process that
    put this file into WAL mode, or a ``-journal`` left by a crash, keeps its own
    mode across a reopen and then takes Tier 1 pages.
    """
    path = tmp_path / "grants.db"
    SqliteSourceGrantStore(path=path).close()
    sidecars = [path.with_name(f"{path.name}{suffix}") for suffix in ("-wal", "-shm")]
    for sidecar in sidecars:
        sidecar.touch()
        sidecar.chmod(0o644)

    SqliteSourceGrantStore(path=path).close()

    assert [each.stat().st_mode & 0o777 for each in sidecars] == [0o600, 0o600]


@pytest.mark.integration
async def test_opening_an_unusable_path_is_reported_as_a_grant_error(tmp_path: Path) -> None:
    """A missing parent directory is this layer's error, not a raw ``sqlite3.Error``."""
    with pytest.raises(GrantError, match="failed to open"):
        SqliteSourceGrantStore(path=tmp_path / "absent" / "grants.db")


async def test_a_path_the_driver_refuses_outright_is_still_a_grant_error() -> None:
    """A path with an embedded NUL leaves ``sqlite3.connect`` as a ``ValueError``.

    Neither a ``sqlite3.Error`` nor an ``OSError``, so a constructor catching only
    those lets a bare builtin escape this layer's error boundary — the hole #238
    records on ``SqliteAuditTrail``, closed here rather than reproduced.
    """
    with pytest.raises(GrantError, match="failed to open"):
        SqliteSourceGrantStore(path="grants\x00.db")


# --- durability, which is the whole reason this implementation exists --------


@pytest.mark.integration
async def test_a_grant_survives_the_process_that_made_it(tmp_path: Path) -> None:
    """ADR-0097 §4's record is durable, or the grant is a session-local promise."""
    path = tmp_path / "grants.db"
    first = SqliteSourceGrantStore(path=path)
    try:
        await first.record(source_grant(SOURCE, grant_id="g-1", scope=(GrantScope.FACET,)))
    finally:
        first.close()

    second = SqliteSourceGrantStore(path=path)
    try:
        live = await second.live(source=SOURCE, use=GrantScope.FACET)
        assert live is not None
        assert live.id == "g-1"
        assert live.scope == (GrantScope.FACET,)
        assert await second.live(source=SOURCE, use=GrantScope.INGEST) is None
    finally:
        second.close()


@pytest.mark.integration
async def test_a_revocation_still_stops_the_read_after_a_restart(tmp_path: Path) -> None:
    """Revocation is prospective *and* durable (ADR-0097 §4, §6).

    A revocation that did not survive the process would let a restart resurrect an
    authorisation the user withdrew — the failure the append-only record exists to
    make impossible. The revoked grant is still on file afterwards, because a
    source with no authorisation record at all would read as never authorised.
    """
    path = tmp_path / "grants.db"
    granted = source_grant(SOURCE, grant_id="g-1")
    first = SqliteSourceGrantStore(path=path)
    try:
        await first.record(granted)
        await first.record(revocation_of(granted, grant_id="r-1"))
    finally:
        first.close()

    second = SqliteSourceGrantStore(path=path)
    try:
        for use in GrantScope:
            assert await second.live(source=SOURCE, use=use) is None, use
        assert {held.id for held in await second.export()} == {"g-1", "r-1"}
    finally:
        second.close()


@pytest.mark.integration
async def test_the_write_once_rule_survives_a_restart(tmp_path: Path) -> None:
    """History cannot be rewritten by replaying a write into a new process."""
    path = tmp_path / "grants.db"
    granted: SourceGrant = source_grant(SOURCE, grant_id="g-1")
    first = SqliteSourceGrantStore(path=path)
    try:
        await first.record(granted)
    finally:
        first.close()

    second = SqliteSourceGrantStore(path=path)
    try:
        with pytest.raises(InvalidGrantError, match="already recorded"):
            await second.record(granted)
    finally:
        second.close()


@pytest.mark.integration
async def test_clearing_the_store_leaves_it_openable(tmp_path: Path) -> None:
    """Burning the book leaves a database this code can still open.

    ``clear`` empties ``grants`` and leaves ``meta``: the marker describes the
    file's shape rather than the user's history.
    """
    path = tmp_path / "grants.db"
    first = SqliteSourceGrantStore(path=path)
    try:
        await first.record(source_grant(SOURCE, grant_id="g-1"))
        assert await first.clear() == 1
    finally:
        first.close()

    second = SqliteSourceGrantStore(path=path)
    try:
        assert await second.export() == []
        assert await second.record(source_grant(SOURCE, grant_id="g-2")) == "g-2"
    finally:
        second.close()


@pytest.mark.integration
async def test_clear_counts_what_it_actually_deleted(tmp_path: Path) -> None:
    """Two stores on one file: the count must cover rows this instance never wrote.

    Each instance has its own ``asyncio.Lock``, which arbitrates nothing across
    them, so a count read before the write transaction opened could miss an append
    that lands between the two. Counting from the ``DELETE`` makes it exact by
    construction.
    """
    path = tmp_path / "grants.db"
    first = SqliteSourceGrantStore(path=path)
    second = SqliteSourceGrantStore(path=path)
    try:
        await first.record(source_grant("a", grant_id="g-1"))
        await second.record(source_grant("b", grant_id="g-2"))

        assert await first.clear() == 2
        assert await second.export() == []
    finally:
        first.close()
        second.close()


# --- ADR-0054's relay, which every copy of the helper owes -------------------


@pytest.mark.integration
async def test_cancelling_a_record_does_not_release_the_connection(tmp_path: Path) -> None:
    """A cancelled append must not free the lock while its worker thread runs (ADR-0054).

    The conformance suite drives this invariant through the shared harness at every
    lock site; this is the same property asserted directly against the lock, which
    is the observation the suite deliberately does not make. Kept because the store
    is the object whose lock it is.
    """
    store = SqliteSourceGrantStore(path=tmp_path / "cancel.db")
    entered = threading.Event()
    release = threading.Event()
    original_record = store._record_sync

    def blocking_record(snapshot: SourceGrant) -> None:
        if not entered.is_set():
            entered.set()
            if not release.wait(timeout=5):  # pragma: no cover - only on a hang
                msg = "the blocked worker was never released"
                raise AssertionError(msg)
        original_record(snapshot)

    store._record_sync = blocking_record  # type: ignore[method-assign]
    try:
        first = asyncio.ensure_future(store.record(source_grant("a", grant_id="g-1")))
        assert await asyncio.to_thread(entered.wait, 5), "worker never entered"
        assert store._lock.locked()

        first.cancel()
        await _spin()
        # The invariant: cancellation did NOT release the lock — the worker is
        # still running, so the connection is still exclusively held.
        assert store._lock.locked()

        second = asyncio.ensure_future(store.record(source_grant("b", grant_id="g-2")))
        await _spin()
        assert not second.done()
        assert store._lock.locked()

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        await second  # must not raise on a concurrently-used connection

        assert {held.id for held in await store.export()} == {"g-1", "g-2"}
        assert not store._lock.locked()
    finally:
        release.set()
        store.close()


async def test_a_base_exception_from_the_worker_reaches_the_caller() -> None:
    """ADR-0054's relay carries every failure, not only the ``Exception`` half (#680).

    ``_run_to_completion`` answers out of its relay lists alone whenever the worker
    finished before the wait loop's first check. A failure the relay never captured
    leaves both lists empty, so the caller is answered from an empty ``outcome`` —
    an ``IndexError`` standing in for the cause and not chained to it.

    The lever forces that path every time. Without it, which of the two paths a
    caller gets is a race, and a case that only sometimes reaches the defect is not
    evidence about it.

    Its own copy of the helper, deliberately: each copy is a separate place the
    relay could be narrow (#680), and this module carries the sixth (#506, #563).
    """

    def aborts() -> None:
        raise KeyboardInterrupt

    with worker_finished_before_the_first_check(), pytest.raises(KeyboardInterrupt):
        await _run_to_completion(aborts)


async def test_repeated_cancellation_does_not_consume_the_executor() -> None:
    """Absorbing a cancellation costs one executor job, however many arrive (#697).

    Each absorbed cancellation hands the loop something to wait on. A copy that
    submits a fresh blocking ``done.wait`` per cancellation leaves every earlier
    one running, because nothing can interrupt a thread parked in ``Event.wait``
    before the worker sets it — so repeated cancellation of *one* blocked call
    occupies the whole default pool and starves unrelated thread work, which turns
    a single stalled store operation into a process that can run none.

    The pool is deliberately small and the probe is the assertion: counting
    threads would measure the executor's growth policy, while the probe measures
    the property — that something else can still run. The cancellation is still
    re-raised at the end, because a "fix" that stopped absorbing it would bound
    the pool by abandoning ADR-0054's invariant instead.

    The bounded executor is installed as this loop's default because the helper
    submits to ``None``; pytest-asyncio gives each test its own loop, so the
    substitution dies with the test and only the pool needs shutting down.
    """
    workers = 4
    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=workers)
    loop.set_default_executor(executor)
    release = threading.Event()
    entered = threading.Event()

    def blocked() -> str:
        entered.set()
        if not release.wait(timeout=5):  # pragma: no cover - only on a hang
            msg = "the blocked worker was never released"
            raise AssertionError(msg)
        return "done"

    call = asyncio.ensure_future(_run_to_completion(blocked))
    try:
        assert await asyncio.to_thread(entered.wait, 5), "worker never entered"
        for _ in range(workers * 3):
            call.cancel()
            await _spin()

        probe = loop.run_in_executor(executor, lambda: "probe")
        finished, _ = await asyncio.wait([probe], timeout=1)
        assert finished, "the absorbed cancellations consumed the whole executor"

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await call
    finally:
        # Released and settled *before* the pool is shut down, so a failing run
        # reports the assertion above rather than a "cannot schedule new futures
        # after shutdown" from the helper still submitting into a closing pool.
        release.set()
        await asyncio.gather(call, return_exceptions=True)
        executor.shutdown(wait=True)
