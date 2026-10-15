"""SqlitePlanStore: the shared PlanStore conformance suite, and its durability.

The conformance subclass runs against ``:memory:`` (no filesystem, so no
``integration`` mark). The tests that open a real file — the half this store
exists for (ADR-0049 §2): a stop record and an activation's effect records
surviving the process that wrote them — say so via ``tmp_path``.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import pytest
from plan_store_contract import PlanStoreContract
from pydantic import ValidationError

from ai_assistant.core.errors import ClaimStopped, PlanningError
from ai_assistant.core.types import (
    ActivationEffect,
    ActivationEffectClaim,
    QuestionPart,
    ToolOutcome,
)
from ai_assistant.planning import SqlitePlanStore, sqlite_store
from ai_assistant.planning.sqlite_store import _run_to_completion
from ai_assistant.testing.cancellation import (
    ResourceLog,
    SuspendedMidWrite,
    ThreadSuspension,
    worker_finished_before_the_first_check,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence
    from pathlib import Path

    from ai_assistant.core.protocols import PlanStore
    from ai_assistant.testing.cancellation import SuspendedCall


def _fixed_now() -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC)


#: The instant every effect record this suite claims was claimed at.
_AT = datetime(2026, 1, 1, tzinfo=UTC)
#: The record tables this store creates. A refused open creates neither.
_RECORD_TABLES: Final = frozenset({"stopped_activations", "activation_effects"})


def _journal_mode(database: Path) -> int | None:
    """The permission bits of the rollback journal beside ``database``, or ``None``."""
    journal = database.with_name(f"{database.name}-journal")
    return journal.stat().st_mode & 0o777 if journal.exists() else None


#: The private method each locked operation does its SQL in, which ADR-0060's hook
#: wraps to park a worker thread inside the connection's turn.
_SYNC_METHODS = {
    "clear": "_clear_sync",
    "export": "_export_sync",
    # ADR-0297 §1's member: the write every later claim is decided against.
    "record_stop": "_record_stop_sync",
    # ADR-0306 §6's three members: the claim is one `BEGIN IMMEDIATE` deciding the
    # stop, the backstop and the write; the finish reads and writes in one; the read
    # holds the connection lock like every other.
    "claim_activation_effect": "_claim_activation_effect_sync",
    "finish_activation_effect": "_finish_activation_effect_sync",
    "activation_effects": "_activation_effects_sync",
    # ADR-0321 §4:9's read by question part, its own lock site.
    "part_effects": "_part_effects_sync",
}


class TestSqlitePlanStoreContract(PlanStoreContract):
    """Runs SqlitePlanStore through the shared PlanStore conformance suite."""

    @pytest.fixture
    def store(self) -> Iterator[PlanStore]:
        realised = SqlitePlanStore(path=":memory:", now=_fixed_now)
        try:
            yield realised
        finally:
            realised.close()

    @contextlib.asynccontextmanager
    async def store_suspended_mid_write(
        self,
    ) -> AsyncIterator[SuspendedMidWrite[PlanStore]]:
        """Park a named operation's worker thread inside the connection's turn.

        ``arm(operation)`` wraps the private method that operation does its SQL in
        (:data:`_SYNC_METHODS`) — inside ``async with self._lock`` and inside the
        ``to_thread`` the event loop cannot interrupt, which is exactly where
        ADR-0054's bug lived — so the first worker to reach it blocks and every
        later one runs free. Each distinct lock site is a separate place the bug can
        reappear, the locked *reads* included (#370, #397). Blocking there is what
        makes the case deterministic: left to
        run, a commit finishes in microseconds and whether the second caller
        arrives while the worker still holds the connection would be a race, so
        the invariant would be exercised only sometimes.

        Its own store on its own connection, not the ``store`` fixture's: the
        suspended worker is parked for the length of the case, and sharing would
        make an unrelated failure hang instead of fail.
        """
        realised = SqlitePlanStore(path=":memory:", now=_fixed_now)
        log = ResourceLog()
        suspension = ThreadSuspension()

        def arm(operation: str) -> SuspendedCall:
            attribute = _SYNC_METHODS[operation]
            original = getattr(realised, attribute)
            armed = threading.Event()

            def blocking(*args: object) -> object:
                with log.inside():  # the span the connection is genuinely in use for
                    if not armed.is_set():  # the first worker only; later ones run free
                        armed.set()
                        suspension.hold()
                    return original(*args)

            setattr(realised, attribute, blocking)
            return suspension

        try:
            yield SuspendedMidWrite(store=realised, log=log, arm=arm)
        finally:
            suspension.release()
            # An implementation that released the connection early leaves a
            # worker still using it; closing under that is a native crash rather
            # than a reported failure, so give the worker a turn to unwind and
            # let the assertion above be the thing that speaks.
            await asyncio.sleep(0.05)
            realised.close()


# --- transactional integrity (ADR-0049 §1) ---------------------------------


async def test_a_stop_cannot_land_between_the_claims_lookup_and_its_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0297 §2: the stop record and the claim are decided in one indivisible step.

    Raced across **separate connections**, which share no in-process lock, so what
    orders them is the claim's own ``BEGIN IMMEDIATE``. The claiming worker is parked
    **after** it has read the stop records and **before** it writes the record, and a
    second connection then tries to take the write lock a stop's write begins with,
    **while it is parked** and with no busy wait, so the attempt is made at that
    instant rather than whenever a scheduler gets to it. It must be refused. An
    implementation that read the records outside the claim's transaction would hold no
    lock there, so the stop would commit inside the window and the claim then land
    after it — the "third case" §2 says the store's total order admits none of.

    Released, the claim lands (it was first), and the stop then lands through the store
    and refuses the activation's next claim.
    """
    path = tmp_path / "plans.db"
    claimer = SqlitePlanStore(path=path, now=_fixed_now)
    stopper = SqlitePlanStore(path=path, now=_fixed_now)
    looked_up = threading.Event()
    release = threading.Event()
    original = sqlite_store._is_stopped

    def parked(conn: sqlite3.Connection, activation_id: str) -> bool:
        answer = original(conn, activation_id)
        looked_up.set()
        release.wait(timeout=10)
        return answer

    in_flight: list[asyncio.Future[Any]] = []
    try:
        monkeypatch.setattr(sqlite_store, "_is_stopped", parked)

        claiming = asyncio.ensure_future(claimer.claim_activation_effect(_acted("e1"), match=None))
        in_flight.append(claiming)
        assert await asyncio.to_thread(looked_up.wait, 10), "the claim reached its lookup"

        competing = sqlite3.connect(path, timeout=0, isolation_level=None)
        try:
            # Taking the write lock is the first thing a stop's write does, and the
            # claim's transaction already holds it.
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                competing.execute("BEGIN IMMEDIATE")
        finally:
            competing.close()
        release.set()

        claimed = await claiming
        monkeypatch.setattr(sqlite_store, "_is_stopped", original)
        await stopper.record_stop("act-1")

        assert claimed is ActivationEffectClaim.CLAIMED, "the claim was first, so it stands"
        assert await stopper.activation_effects(["act-1"]) == (_acted("e1"),)
        with pytest.raises(ClaimStopped):
            await claimer.claim_activation_effect(_acted("e2"), match=None)
    finally:
        # Released and drained before either connection closes: closing under a worker
        # still inside its statement is a native crash rather than a reported failure.
        release.set()
        await asyncio.gather(*in_flight, return_exceptions=True)
        claimer.close()
        stopper.close()


def test_concurrent_first_opens_of_one_fresh_file_both_succeed(tmp_path: Path) -> None:
    """Two threads opening the same *absent* file at once both construct (§1).

    Released together by a barrier so both hit ``connect`` + setup on a fresh file
    concurrently — the race a sequential open cannot provoke. Setup runs under
    ``BEGIN IMMEDIATE``, so one thread creates and initialises while the other
    waits and finds it done, instead of both observing empty ``meta`` and losing a
    primary-key race on the ``schema_version`` insert. Both constructors succeed.
    """
    import threading  # noqa: PLC0415 — test-local

    path = tmp_path / "plans.db"
    barrier = threading.Barrier(2)
    opened: list[SqlitePlanStore] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def _open() -> None:
        barrier.wait()  # both threads proceed into setup together
        try:
            store = SqlitePlanStore(path=path, now=_fixed_now)
        except BaseException as exc:
            with lock:
                errors.append(exc)
        else:
            with lock:
                opened.append(store)

    threads = [threading.Thread(target=_open) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        assert not errors, f"a concurrent first open failed: {errors}"
        assert len(opened) == 2
    finally:
        for store in opened:
            store.close()


async def test_a_newer_schema_is_refused_before_any_record_table_exists(tmp_path: Path) -> None:
    """A rejected newer-schema open leaves no schema behind (§1).

    A database holding only a ``meta`` table marked ``schema_version = 999`` must
    be refused *before* a record table is created — creating a table is a write,
    and the refusal must precede any write.
    """
    path = tmp_path / "plans.db"
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    raw.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '999')")
    raw.commit()
    raw.close()

    with pytest.raises(PlanningError, match="this code reads version 12 only"):
        SqlitePlanStore(path=path, now=_fixed_now)

    assert _tables(path).isdisjoint(_RECORD_TABLES)


@contextlib.contextmanager
def _traced(store: SqlitePlanStore) -> Iterator[list[str]]:
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

    * the **first** statement is ``BEGIN IMMEDIATE``, so every read the write
      depends on sits inside the write lock rather than in front of it — the
      window #526 is about, which a staged race cannot see because a race can
      only prove the lock excludes, never *when* it was taken;
    * exactly **one** ``BEGIN``, since a second on the shared connection raises;
    * the **last** statement closes it — ``COMMIT``, or ``ROLLBACK`` where the
      block was left by a refusal — so no arm, an early ``return`` included,
      abandons an open transaction that would poison the next caller's ``BEGIN``.

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


async def test_every_transaction_path_opens_and_closes_exactly_one(tmp_path: Path) -> None:
    """The same assertion over every path that opens a transaction.

    Each write reads before it writes — the held id, the matching records and the
    stop a claim is decided against, the held record a finish is applied to — and
    each read is one #526 says must not be interleavable. The refusals leave the
    block by raising, and are driven too, since a refusal is where an open
    transaction would be abandoned.
    """
    store = SqlitePlanStore(path=tmp_path / "plans.db", now=_fixed_now)

    async def recorded(
        what: str, run: Callable[[], Awaitable[object]], *, closes: str = "COMMIT"
    ) -> None:
        with _traced(store) as statements:
            if closes == "COMMIT":
                await run()
            else:
                with pytest.raises(PlanningError):
                    await run()
        _assert_one_immediate_transaction(statements, what=what, closes=closes)

    try:
        await recorded(
            "claim_activation_effect",
            lambda: store.claim_activation_effect(_acted("e1"), match=None),
        )
        await recorded(
            "claim_activation_effect (refused: the id is already held)",
            lambda: store.claim_activation_effect(_acted("e1"), match=None),
            closes="ROLLBACK",
        )
        await recorded(
            "claim_activation_effect (matched: already done)",
            lambda: store.claim_activation_effect(_acted("e2"), match=("act-1",)),
        )
        await recorded(
            "finish_activation_effect",
            lambda: store.finish_activation_effect("e1", ToolOutcome.SUCCEEDED),
        )
        await recorded(
            "finish_activation_effect (refused: already finished)",
            lambda: store.finish_activation_effect("e1", ToolOutcome.SUCCEEDED),
            closes="ROLLBACK",
        )
        await recorded("record_stop", lambda: store.record_stop("act-1"))
        await recorded("record_stop (idempotent repeat)", lambda: store.record_stop("act-1"))
        await recorded(
            "claim_activation_effect (refused: the activation was stopped)",
            lambda: store.claim_activation_effect(_acted("e3"), match=None),
            closes="ROLLBACK",
        )
        await recorded("export", store.export)
        await recorded("clear", store.clear)
    finally:
        store.close()


async def test_a_refusal_inside_a_transaction_leaves_the_store_usable(tmp_path: Path) -> None:
    """A domain refusal ends the transaction rather than abandoning it open.

    Finishing a record the store does not hold raises ``PlanningError`` — not a
    ``sqlite3.Error`` — from inside the block, which is the arm that has to reach a
    ``ROLLBACK`` on the way out. The statement stream is asserted above; what this
    adds is the consequence: the connection is out of its transaction and the next
    write still lands, since a lingering transaction poisons the following ``BEGIN``.
    """
    store = SqlitePlanStore(path=tmp_path / "plans.db", now=_fixed_now)
    try:
        with pytest.raises(PlanningError):
            await store.finish_activation_effect("e1", ToolOutcome.SUCCEEDED)

        assert store._conn.in_transaction is False
        assert await store.claim_activation_effect(_acted("e1"), match=None) is (
            ActivationEffectClaim.CLAIMED
        ), "the store is not poisoned"
    finally:
        store.close()


# --- schema versioning (ADR-0049 §1) ---------------------------------------


async def test_a_newer_on_disk_schema_is_refused(tmp_path: Path) -> None:
    """Opening a database written by a newer version raises before any read.

    Seeded by bumping ``meta.schema_version`` on a real file, then reopening.
    """
    path = tmp_path / "plans.db"
    store = SqlitePlanStore(path=path, now=_fixed_now)
    store.close()

    raw = sqlite3.connect(path)
    raw.execute("UPDATE meta SET value = '999' WHERE key = 'schema_version'")
    raw.commit()
    raw.close()

    with pytest.raises(PlanningError, match="this code reads version"):
        SqlitePlanStore(path=path, now=_fixed_now)


async def test_a_fresh_file_is_labelled_version_12_and_holds_only_the_two_tables(
    tmp_path: Path,
) -> None:
    """The absolute figure's home, and the shape it labels (ADR-0309 §5, ADR-0321 §4:9).

    Version 12 is the store ADR-0309 §5 leaves, its effect records carrying the question
    part ADR-0321 §4:9 promotes: the stop records and the activation effect records,
    beside ``meta``, and no table of the old path.
    """
    path = tmp_path / "plans.db"
    SqlitePlanStore(path=path, now=_fixed_now).close()

    assert sqlite_store._SCHEMA_VERSION == 12
    assert _meta(path, "schema_version") == "12"
    assert _tables(path) == {"meta", *_RECORD_TABLES}


@pytest.mark.parametrize(
    "version", ["0", "1", "10", "11"], ids=["zero", "the-first", "the-cutover-old", "the-last-old"]
)
async def test_an_older_on_disk_schema_is_refused(tmp_path: Path, version: str) -> None:
    """Every older version is refused, the ones this store once upgraded included.

    ADR-0309 §6: the cutover deploys on a fresh data directory, and no lane writes a
    migration, a reader or a shim for a store written before it. Opening such a file
    over ``CREATE TABLE IF NOT EXISTS`` would leave its old tables beside the new ones,
    holding records this code would neither export nor clear, so it is refused at the
    open (ADR-0049 §1) and named as a store written before the cutover.
    """
    path = tmp_path / "plans.db"
    SqlitePlanStore(path=path, now=_fixed_now).close()

    raw = sqlite3.connect(path)
    raw.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (version,))
    raw.commit()
    raw.close()

    with pytest.raises(
        PlanningError,
        match="written before the cutover, or before the question part, has no reader",
    ):
        SqlitePlanStore(path=path, now=_fixed_now)


@pytest.mark.parametrize(
    "label",
    ["10", None, "12"],
    ids=["as-written", "its-marker-deleted", "its-marker-rewritten-to-current"],
)
async def test_a_pre_cutover_file_is_refused_and_left_exactly_as_it_was(
    tmp_path: Path, label: str | None
) -> None:
    """A file holding the old path's records keeps them and its label, and gains nothing.

    The refusal precedes every write, so the file a user's old hub wrote is not
    half-adopted: no record table is created beside its own, and its marker is not
    moved. **It rests on the tables, not on the marker alone**: a marker deleted or
    rewritten to the current version would otherwise pass the file off as a fresh or a
    current one, and its goals would stay in it and outside ``export`` and ``clear``
    (ADR-0004 §6).
    """
    path = tmp_path / "plans.db"
    raw = sqlite3.connect(path)
    try:
        raw.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        if label is not None:
            raw.execute("INSERT INTO meta(key, value) VALUES ('schema_version', ?)", (label,))
        raw.execute("CREATE TABLE goals(id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        raw.execute("INSERT INTO goals(id, data) VALUES ('g1', '{}')")
        raw.commit()
    finally:
        raw.close()

    with pytest.raises(PlanningError, match=r"neither creates nor reads \(goals\)"):
        SqlitePlanStore(path=path, now=_fixed_now)

    assert _tables(path) == {"meta", "goals"}
    assert _meta(path, "schema_version") == label
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT id FROM goals").fetchall() == [("g1",)]


async def test_a_non_numeric_schema_version_is_a_planning_error(tmp_path: Path) -> None:
    """A corrupt/tampered meta value is refused as PlanningError, not a raw ValueError.

    ``int('not-a-number')`` must not leak past the initialisation boundary
    (ADR-0049 §1); opening a store with a garbled ``schema_version`` is a fault to
    report in this layer's own error type.
    """
    path = tmp_path / "plans.db"
    SqlitePlanStore(path=path, now=_fixed_now).close()

    raw = sqlite3.connect(path)
    raw.execute("UPDATE meta SET value = 'not-a-number' WHERE key = 'schema_version'")
    raw.commit()
    raw.close()

    with pytest.raises(PlanningError, match="non-numeric schema_version"):
        SqlitePlanStore(path=path, now=_fixed_now)


# --- a `meta` table this store did not shape (issue #349) -------------------
#: A ``meta`` **without** ``key TEXT PRIMARY KEY``, so it can hold two rows for
#: one key. ``CREATE TABLE IF NOT EXISTS`` is a no-op against it, so this is the
#: table the store actually opens.
_META_WITHOUT_PK = "CREATE TABLE meta(key TEXT, value TEXT NOT NULL)"
#: The same, with no declared type on ``value``: SQLite then hands back whatever
#: was stored — a REAL, a NULL — rather than coercing it to TEXT.
_META_UNTYPED = "CREATE TABLE meta(key TEXT, value)"


def _hand_built_meta(path: Path, rows: Sequence[tuple[str, object]], *, typed: bool = True) -> None:
    """Seed a database whose ``meta`` this store did not create."""
    raw = sqlite3.connect(path)
    try:
        raw.execute(_META_WITHOUT_PK if typed else _META_UNTYPED)
        raw.executemany("INSERT INTO meta(key, value) VALUES (?, ?)", rows)
        raw.commit()
    finally:
        raw.close()


def _refusal(path: Path, pattern: str) -> str:
    """Open ``path``, require a ``PlanningError`` matching ``pattern``, return it."""
    with pytest.raises(PlanningError, match=pattern) as caught:
        SqlitePlanStore(path=path, now=_fixed_now)
    return str(caught.value).replace(str(path), "<db>")


async def test_conflicting_schema_version_rows_are_refused_whatever_their_order(
    tmp_path: Path,
) -> None:
    """Two rows for one key are refused, and by the *rows*, not by their order.

    ``meta``'s primary key makes this unreachable for a table the store created,
    but ``CREATE TABLE IF NOT EXISTS`` accepts a pre-existing one declared without
    it. Collapsing the table into a ``dict`` kept whichever row SQLite returned
    last, so these two databases — identical row *sets*, differing only in
    insertion order — behaved oppositely: one refused a supported schema, and the
    other **opened** on an unsupported one. Asserting the two messages are equal is
    what pins the order out of the answer.
    """
    ascending, descending = tmp_path / "asc.db", tmp_path / "desc.db"
    _hand_built_meta(ascending, (("schema_version", "11"), ("schema_version", "999")))
    _hand_built_meta(descending, (("schema_version", "999"), ("schema_version", "11")))

    assert _refusal(ascending, "2 schema_version rows") == _refusal(
        descending, "2 schema_version rows"
    )

    # And refused before any record table exists: ADR-0049 §1 puts the refusal
    # ahead of every write, and creating a table is a write.
    assert _tables(ascending).isdisjoint(_RECORD_TABLES)


@pytest.mark.parametrize("value", [float("inf"), None, b"1", 1.5])
def test_an_untyped_meta_value_never_leaks_a_non_domain_error(
    tmp_path: Path, value: object
) -> None:
    """A ``value`` column with no declared type returns whatever was stored.

    ``int(float("inf"))`` raises ``OverflowError`` and ``int(None)`` a
    ``TypeError`` — neither a ``ValueError`` nor an ``AssistantError``, so both
    escaped the ``PlanningError`` boundary ``_setup`` exists to hold (ADR-0049
    §1). A stored ``NULL`` also has to read as a *present* row rather than an
    absent key, or the store would insert a second row beside it.
    """
    path = tmp_path / "plans.db"
    _hand_built_meta(path, [("schema_version", value)], typed=False)

    with pytest.raises(PlanningError, match="non-numeric schema_version"):
        SqlitePlanStore(path=path, now=_fixed_now)


def _meta(path: Path, key: str) -> str | None:
    """The single value stored under ``key``, or ``None`` if there is no row."""
    raw = sqlite3.connect(path)
    try:
        row = raw.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    finally:
        raw.close()
    return None if row is None else str(row[0])


def _tables(path: Path) -> set[str]:
    raw = sqlite3.connect(path)
    try:
        return {
            row[0] for row in raw.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        raw.close()


async def test_a_failed_open_rolls_the_schema_and_the_label_back(tmp_path: Path) -> None:
    """The label and the tables are written in one transaction, or neither is.

    The create fails part-way: SQLite shares one namespace across tables and indexes,
    so an index already named ``activation_effects`` makes ``CREATE TABLE IF NOT
    EXISTS activation_effects`` an error rather than a no-op — after
    ``stopped_activations`` has been created and the label written. Both roll back.
    """
    path = tmp_path / "plans.db"
    raw = sqlite3.connect(path)
    try:
        raw.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        raw.execute("CREATE INDEX activation_effects ON meta(key)")
        raw.commit()
    finally:
        raw.close()

    with pytest.raises(PlanningError, match="failed to initialise the plan store"):
        SqlitePlanStore(path=path, now=_fixed_now)

    assert _meta(path, "schema_version") is None
    assert "stopped_activations" not in _tables(path)


async def test_a_path_the_driver_refuses_outright_is_still_a_planning_error() -> None:
    """A path with an embedded NUL leaves ``sqlite3.connect`` as a ``ValueError``.

    Neither a ``sqlite3.Error`` nor an ``OSError``, so a clause catching only those
    two lets a bare builtin escape the ``PlanningError`` boundary this constructor
    documents — the hole #1933 records across nine stores, of which this is the
    last to be closed.

    No ``integration`` mark and no ``tmp_path``: the driver refuses the argument
    before it opens anything, so this reaches no filesystem.
    """
    with pytest.raises(PlanningError, match="failed to open"):
        SqlitePlanStore(path="plans\x00.db", now=_fixed_now)


# --- a record table this store did not shape (issue #373) -------------------


def _hand_built_table(path: Path, table: str, body: str) -> None:
    """Seed a database whose ``table`` this store did not create.

    ``CREATE TABLE IF NOT EXISTS`` is a no-op against it, so this is the table the
    store actually opens; every other record table it creates fresh and correctly.
    """
    raw = sqlite3.connect(path)
    try:
        raw.execute(f"CREATE TABLE {table}({body})")
        raw.commit()
    finally:
        raw.close()


@pytest.mark.parametrize(
    ("table", "body", "match"),
    [
        pytest.param(
            "activation_effects",
            "id TEXT PRIMARY KEY, activation_id TEXT NOT NULL, claimed_seq TEXT NOT NULL, "
            "data TEXT NOT NULL",
            "claimed_seq column has TEXT affinity",
            id="claimed-seq-not-integer-orders-the-claims-lexically",
        ),
        pytest.param(
            "activation_effects",
            "id TEXT PRIMARY KEY, activation_id TEXT NOT NULL, claimed_seq INTEGER NOT NULL, "
            "data BLOB NOT NULL",
            "data column has BLOB affinity",
            id="data-not-text-changes-what-model_validate_json-is-handed",
        ),
        pytest.param(
            "activation_effects",
            "id TEXT PRIMARY KEY, activation_id TEXT NOT NULL, claimed_seq INTEGER NOT NULL, "
            "data TEXT",
            "data column is nullable",
            id="nullable-data-can-store-a-null-no-decode-accepts",
        ),
        pytest.param(
            "activation_effects",
            "id TEXT PRIMARY KEY, activation_id TEXT, claimed_seq INTEGER NOT NULL, "
            "data TEXT NOT NULL",
            "activation_id column is nullable",
            id="nullable-activation-hides-a-record-from-every-match",
        ),
        pytest.param(
            "activation_effects",
            "id TEXT PRIMARY KEY, activation_id TEXT NOT NULL, data TEXT NOT NULL",
            "claimed_seq column is absent",
            id="missing-a-column",
        ),
        pytest.param(
            "activation_effects",
            "id TEXT PRIMARY KEY, activation_id TEXT NOT NULL, claimed_seq INTEGER NOT NULL, "
            "data TEXT NOT NULL, part_round TEXT, part_number TEXT",
            "part_number column has TEXT affinity",
            id="part-number-not-integer-misses-every-spent-part",
        ),
        pytest.param(
            "activation_effects",
            "id TEXT, activation_id TEXT NOT NULL, claimed_seq INTEGER NOT NULL, "
            "data TEXT NOT NULL, part_round TEXT, part_number INTEGER",
            "no PRIMARY KEY",
            id="effects-without-a-primary-key-admit-a-second-record-of-one-id",
        ),
        pytest.param(
            "activation_effects",
            "id TEXT PRIMARY KEY COLLATE NOCASE, activation_id TEXT NOT NULL, "
            "claimed_seq INTEGER NOT NULL, data TEXT NOT NULL, part_round TEXT, "
            "part_number INTEGER",
            "NOCASE-collated id PRIMARY KEY",
            id="case-insensitive-primary-key-folds-distinct-ids",
        ),
        pytest.param(
            "stopped_activations",
            "activation_id TEXT PRIMARY KEY COLLATE NOCASE",
            "NOCASE-collated activation_id PRIMARY KEY",
            id="a-case-folded-stop-refuses-another-activations-claims",
        ),
    ],
)
async def test_a_record_table_of_the_wrong_shape_is_refused(
    tmp_path: Path, table: str, body: str, match: str
) -> None:
    """Every load-bearing shape property, refused at open (#373).

    A hand-built table breaks each the same way ``CREATE TABLE IF NOT EXISTS`` lets
    it through: the ``claimed_seq`` the claim order is read by, the ``data`` blob
    ``model_validate_json`` reads, a nullable column that can store a ``NULL`` no
    read accepts, and the primary key the ``ON CONFLICT`` writes and per-id
    uniqueness need (absent, or folded case-insensitively by a ``COLLATE NOCASE``
    that collides distinct ids).
    """
    path = tmp_path / "plans.db"
    _hand_built_table(path, table, body)

    with pytest.raises(PlanningError, match=match):
        SqlitePlanStore(path=path, now=_fixed_now)


async def test_a_case_variant_but_compatible_schema_is_accepted(tmp_path: Path) -> None:
    """SQLite identifiers are case-insensitive, so a case-variant schema is *the* shape.

    A hand-built all-uppercase schema differs only in identifier casing, which every
    query this store issues resolves case-insensitively, so it is the shape this store
    understands and refusing it for casing alone would be a false refusal. Every shape
    check lower-cases identifier names before comparing, so the store opens and a
    claim, a stop and the read — including the ``ORDER BY claimed_seq`` — work against
    ``CLAIMED_SEQ``.
    """
    path = tmp_path / "plans.db"
    raw = sqlite3.connect(path)
    try:
        raw.execute("CREATE TABLE STOPPED_ACTIVATIONS(ACTIVATION_ID TEXT PRIMARY KEY)")
        raw.execute(
            "CREATE TABLE ACTIVATION_EFFECTS(ID TEXT PRIMARY KEY, ACTIVATION_ID TEXT NOT NULL, "
            "CLAIMED_SEQ INTEGER NOT NULL, DATA TEXT NOT NULL, PART_ROUND TEXT, "
            "PART_NUMBER INTEGER)"
        )
        raw.commit()
    finally:
        raw.close()

    store = SqlitePlanStore(path=path, now=_fixed_now)  # opens rather than refusing
    try:
        await store.claim_activation_effect(_acted("e1"), match=None)
        await store.claim_activation_effect(_acted("e2"), match=None)
        await store.record_stop("act-1")
        assert await store.activation_effects(["act-1"]) == (_acted("e1"), _acted("e2"))
        assert (await store.export()).stopped_activations == ("act-1",)
    finally:
        store.close()


async def test_a_trigger_on_a_record_table_is_refused(tmp_path: Path) -> None:
    """A mutating trigger subverts a *successful* write, so a table carrying one is refused.

    The columns and key can be exactly right while an ``AFTER INSERT`` trigger rewrites
    ``NEW.id`` underneath the write: a claim would report its record stored while the
    row was moved, and the read would then find it under an id nothing claimed. The
    store creates no triggers, so any trigger on a record table is foreign and there is
    no shape that makes a mutating one safe; it is refused at open (ADR-0049 §1's
    fail-closed posture), the same reasoning as a wrong column or a missing key.
    """
    path = tmp_path / "plans.db"
    raw = sqlite3.connect(path)
    try:
        raw.execute(
            "CREATE TABLE activation_effects(id TEXT PRIMARY KEY, activation_id TEXT NOT NULL, "
            "claimed_seq INTEGER NOT NULL, data TEXT NOT NULL)"
        )
        raw.execute(
            "CREATE TRIGGER effects_tamper AFTER INSERT ON activation_effects "
            "BEGIN UPDATE activation_effects SET id = id || '-moved' WHERE id = NEW.id; END"
        )
        raw.commit()
    finally:
        raw.close()

    with pytest.raises(PlanningError, match="triggers on the tables it writes"):
        SqlitePlanStore(path=path, now=_fixed_now)


async def test_a_trigger_on_meta_is_refused(tmp_path: Path) -> None:
    """A ``meta`` trigger can relabel the schema, so it too is refused (#373, #405).

    The open is decided on ``schema_version``, so a trigger that rewrites it would
    move the label under the store's own write. This is a *silent* break — every
    other check passes — so the trigger class is closed over every table the store
    writes, ``meta`` included.
    """
    path = tmp_path / "plans.db"
    raw = sqlite3.connect(path)
    try:
        raw.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        raw.execute(
            "CREATE TRIGGER meta_relabel AFTER INSERT ON meta "
            "BEGIN UPDATE meta SET value = '10' WHERE key = 'schema_version'; END"
        )
        raw.commit()
    finally:
        raw.close()

    with pytest.raises(PlanningError, match="triggers on the tables it writes"):
        SqlitePlanStore(path=path, now=_fixed_now)


async def test_export_is_a_single_consistent_snapshot(tmp_path: Path) -> None:
    """The export reads both tables in one transaction, against a second writer.

    ``export`` reads both tables inside one ``BEGIN IMMEDIATE`` transaction (ADR-0004
    §6), so a second connection cannot interleave a write between the reads. Two
    connections on one file: reader ``a``'s export sees neither record before writer
    ``b`` commits them, and both after.
    """
    path = tmp_path / "plans.db"
    a = SqlitePlanStore(path=path, now=_fixed_now)
    b = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        empty = await a.export()
        assert empty.stopped_activations == ()
        assert empty.activation_effects == ()

        await b.claim_activation_effect(_acted("e1"), match=None)
        await b.record_stop("act-1")

        whole = await a.export()
        assert whole.stopped_activations == ("act-1",)
        assert whole.activation_effects == (_acted("e1"),)
    finally:
        a.close()
        b.close()


async def test_the_database_file_is_owner_only(tmp_path: Path) -> None:
    """A Tier 1 store's file is created owner-only (ADR-0004), like the others."""
    path = tmp_path / "plans.db"
    store = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        assert (path.stat().st_mode & 0o777) == 0o600
    finally:
        store.close()


async def test_a_journal_opened_during_setup_is_owner_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0004 §4 reaches the sidecars, and reaches them from the first write (#451).

    SQLite copies the *database file's* mode onto every rollback journal it creates
    for it, so restricting the file after the schema is created leaves every journal
    opened in between carrying the process umask — and an interrupted write leaves
    that journal on disk holding Tier 1 pages beside a ``0600`` base file. Setup's
    ``BEGIN IMMEDIATE`` is exactly such a write.

    Observed **inside** ``_setup`` rather than after it, because that is the only
    place the difference is visible: by the time the constructor returns the
    transaction has committed, and a journal provoked afterwards inherits ``0600``
    under either ordering. The hook is ``_verify_or_init_meta``, which runs inside
    that transaction; on the unfixed ordering the journal is ``0644`` there.

    The file is pre-created ``0644`` so the case does not depend on the runner's
    umask — and because reopening an existing store is the common path anyway.
    """
    path = tmp_path / "plans.db"
    path.touch()
    path.chmod(0o644)
    observed: list[int | None] = []
    original = SqlitePlanStore._verify_or_init_meta

    def observing(store: SqlitePlanStore, conn: sqlite3.Connection) -> None:
        original(store, conn)
        observed.append(_journal_mode(path))

    monkeypatch.setattr(SqlitePlanStore, "_verify_or_init_meta", observing)

    opened = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        assert observed[0] is not None, "setup should have opened a journal"
        assert observed == [0o600]
    finally:
        opened.close()


def test_a_sidecar_that_was_already_there_is_restricted_at_open(tmp_path: Path) -> None:
    """ADR-0004 §4 reaches a sidecar this process did not create (#490).

    SQLite copies the database file's mode onto a sidecar **it creates**, which is
    what makes restricting the file before the first statement enough for those. It
    does nothing for one already on disk: a ``-wal``/``-shm`` left by a process that
    put this file into WAL mode keeps its own mode across a reopen and then takes
    Tier 1 pages.

    Planted at ``0644`` and asserted after a *reopen*, because that is the only shape
    that can fail: a sidecar SQLite makes for an already-``0600`` file is ``0600``
    however this store is written. Nothing in this codebase sets ``journal_mode``, so
    SQLite neither reads nor writes these two — the mode asserted is this store's own
    chmod and nothing else.
    """
    path = tmp_path / "plans.db"
    SqlitePlanStore(path=path, now=_fixed_now).close()
    sidecars = [path.with_name(f"{path.name}{suffix}") for suffix in ("-wal", "-shm")]
    for sidecar in sidecars:
        sidecar.touch()
        sidecar.chmod(0o644)

    SqlitePlanStore(path=path, now=_fixed_now).close()

    assert [each.stat().st_mode & 0o777 for each in sidecars] == [0o600, 0o600]


async def _spin(iterations: int = 50) -> None:
    """Yield to the event loop repeatedly so a pending cancellation can unwind."""
    for _ in range(iterations):
        await asyncio.sleep(0)


@pytest.mark.integration
async def test_cancelling_a_write_does_not_release_the_connection(tmp_path: Path) -> None:
    """A cancelled write must not free the lock while its worker thread runs (ADR-0054).

    A worker thread cannot be interrupted, so a cancellation that unwound the awaiting
    coroutine here would release the connection lock while the worker was still
    inside its ``BEGIN IMMEDIATE`` transaction on the shared connection. This blocks a
    worker inside ``record_stop``, cancels the awaiting task, and asserts the lock
    stays held until the worker finishes, then that a second write lands on an intact
    connection.
    """
    store = SqlitePlanStore(path=tmp_path / "cancel.db", now=_fixed_now)
    entered = threading.Event()
    release = threading.Event()
    original_record = store._record_stop_sync

    def blocking_record(activation_id: str) -> None:
        if not entered.is_set():
            entered.set()
            if not release.wait(timeout=5):  # pragma: no cover - only on a hang
                msg = "the blocked worker was never released"
                raise AssertionError(msg)
        original_record(activation_id)

    store._record_stop_sync = blocking_record  # type: ignore[method-assign]
    try:
        first = asyncio.ensure_future(store.record_stop("act-1"))
        assert await asyncio.to_thread(entered.wait, 5), "worker never entered"
        assert store._lock.locked()

        first.cancel()
        await _spin()
        # The invariant: cancellation did NOT release the lock — the worker is
        # still running, so the connection is still exclusively held.
        assert store._lock.locked()

        second = asyncio.ensure_future(store.record_stop("act-2"))
        await _spin()
        assert not second.done()
        assert store._lock.locked()

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        await second  # must not raise on a concurrently-used connection

        # The connection is intact: the deferred-to-completion first write
        # committed, and the second landed cleanly on top of it.
        assert (await store.export()).stopped_activations == ("act-1", "act-2")
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
    evidence about it. ``KeyboardInterrupt`` stands in for the class; ``SystemExit``
    and a ``CancelledError`` raised by the work itself are the other members.

    Its own copy of the helper, deliberately: ADR-0060 refuses this shape a shared
    home, so each copy is a separate place the relay could be narrow (#680).
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

    Pinned in this module rather than once for the family, because ADR-0060
    refuses this helper a shared home: each copy is a separate place the reuse can
    be lost, and a single pin on one copy is exactly how six later copies came to
    be written with the defect rather than without it (#697).

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


#: A string that occurs nowhere else in the file: no table or column name holds it, no
#: SQL keyword and no other fixture contains it, so its presence is the row's doing —
#: and long enough that repeating it pushes the row's JSON off the leaf page and into
#: overflow, which is a second place freed content can be left behind.
_NEEDLE: Final = b"heliotrope-belfry-quintessence"
#: One record small enough to sit in a leaf page, and one whose blob needs overflow
#: pages. The parametrisation is not decoration: `secure_delete` has to reach both.
_NEEDLE_SIZES: Final = {"one leaf page": 1, "several overflow pages": 800}


@pytest.mark.parametrize("repeats", list(_NEEDLE_SIZES.values()), ids=list(_NEEDLE_SIZES))
async def test_a_clear_leaves_no_trace_of_a_record_in_the_file(
    tmp_path: Path, repeats: int
) -> None:
    """``clear`` is ADR-0004 §6's deletion, and it reaches the file's freed pages.

    A ``DELETE`` that merely unlinked the row would satisfy every assertion the shared
    suite can make — it reads decoded rows — while the reason an effect was not done
    stayed recoverable by reading the file. The needle rides in that reason.

    The first assertion is the anti-vacuity half: the bytes are genuinely there while
    the record stands, so their absence afterwards is the clear's doing and not the
    needle's.
    """
    path = tmp_path / "plans.db"
    store = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        await store.claim_activation_effect(_acted("e1"), match=None)
        await store.finish_activation_effect(
            "e1", ToolOutcome.FAILED, reason=_NEEDLE.decode() * repeats
        )
    finally:
        store.close()
    assert _NEEDLE in path.read_bytes(), "the record is on disk while it stands"

    reopened = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        assert await reopened.clear() == 1
    finally:
        reopened.close()

    assert _NEEDLE not in path.read_bytes()


async def test_the_store_asks_sqlite_to_overwrite_what_it_frees(tmp_path: Path) -> None:
    """The pragma itself, asserted where a lane could quietly drop it.

    The case above would keep passing on a build whose ``SQLITE_SECURE_DELETE`` is
    compiled **on** by default, so it is not on its own evidence that this store asks
    for it. This is: the connection says so, whatever the build's default.
    """
    store = SqlitePlanStore(path=tmp_path / "plans.db", now=_fixed_now)
    try:
        assert store._conn.execute("PRAGMA secure_delete").fetchone() == (1,)
    finally:
        store.close()


# --- durability: state survives the process (ADR-0049 §2) ------------------


async def test_a_stop_record_survives_a_restart(tmp_path: Path) -> None:
    """ADR-0297 §1 on the durable store: a record outlives the process that wrote it.

    "No stop record is removed while the store holds its rows" — so a claim a stopped
    activation's work makes after the hub reopened its store is refused exactly as it
    would have been before.
    """
    path = tmp_path / "plans.db"
    store = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        await store.record_stop("act-1")
    finally:
        store.close()

    reopened = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        with pytest.raises(ClaimStopped):
            await reopened.claim_activation_effect(_acted("e1"), match=None)
        assert (await reopened.export()).stopped_activations == ("act-1",)
    finally:
        reopened.close()


async def test_a_blanked_stop_record_is_refused_as_planning_s_own_error(
    tmp_path: Path,
) -> None:
    """A record an outside writer blanked or nulled is refused at the export.

    It is read back as the identifier it was written as, so the refusal is
    ``planning``'s own error rather than a raw validation failure of the document.
    """
    path = tmp_path / "plans.db"
    store = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        await store.record_stop("act-1")
    finally:
        store.close()
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE stopped_activations SET activation_id = NULL")

    reopened = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        with pytest.raises(PlanningError) as refusal:
            await reopened.export()
        assert not isinstance(refusal.value, ValidationError)
    finally:
        reopened.close()


async def test_a_stop_table_without_its_key_is_refused_at_open(tmp_path: Path) -> None:
    """``record_stop``'s idempotence rests on the activation id being the primary key.

    ``CREATE TABLE IF NOT EXISTS`` is a no-op against a pre-existing table of another
    shape (#373), so a hand-built ``stopped_activations`` with no key would let one
    activation hold two rows and the export carry a duplicate the document refuses.
    """
    path = tmp_path / "plans.db"
    SqlitePlanStore(path=path, now=_fixed_now).close()
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE stopped_activations")
        conn.execute("CREATE TABLE stopped_activations(activation_id TEXT)")

    with pytest.raises(PlanningError, match="stopped_activations"):
        SqlitePlanStore(path=path, now=_fixed_now)


# --- ADR-0306 §6: acting's effect records on the durable store -----------------


def _acted(effect_id: str, *, activation: str = "act-1") -> ActivationEffect:
    """A call's effect record as acting claims it, with no outcome."""
    return ActivationEffect(
        id=effect_id,
        activation_id=activation,
        round="r1",
        capability="book_stay",
        values_digest="a" * 64,
        decision_id=f"d-{effect_id}",
        claimed_at=_AT,
    )


async def test_an_activation_effect_survives_a_restart(tmp_path: Path) -> None:
    """A claimed record outlives the process, and still refuses an equal call.

    ADR-0306 §5:6: a record given no outcome, as after a crash, is never resolved by
    guessing; the reopened store holds it unfinished, and it counts as done for the
    backstop (§5:11).
    """
    path = tmp_path / "plans.db"
    store = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        await store.claim_activation_effect(_acted("e1"), match=None)
    finally:
        store.close()

    reopened = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        assert await reopened.activation_effects(["act-1"]) == (_acted("e1"),)
        assert await reopened.claim_activation_effect(_acted("e2"), match=("act-1",)) is (
            ActivationEffectClaim.ALREADY_DONE
        )
    finally:
        reopened.close()


async def test_an_activation_effect_whose_columns_disagree_with_its_record_is_refused(
    tmp_path: Path,
) -> None:
    """A promoted column an outside writer changed is corruption, not a different record.

    The backstop selects on ``activation_id``, so a column that disagreed with the
    record would hide it from the match; the read refuses it as ``PlanningError``.
    """
    path = tmp_path / "plans.db"
    store = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        await store.claim_activation_effect(_acted("e1"), match=None)
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE activation_effects SET activation_id = 'act-2'")
        with pytest.raises(PlanningError):
            await store.activation_effects(["act-2"])
        with pytest.raises(PlanningError):
            await store.export()
    finally:
        store.close()


@pytest.mark.parametrize(
    "tamper",
    [
        "UPDATE activation_effects SET part_round = 'q-other'",
        "UPDATE activation_effects SET part_number = 2",
        "UPDATE activation_effects SET part_round = NULL, part_number = NULL",
    ],
    ids=["another-round", "another-part", "the-part-erased"],
)
async def test_a_spent_part_whose_columns_disagree_with_its_record_is_refused(
    tmp_path: Path, tamper: str
) -> None:
    """ADR-0321 §4:9: the promoted part key is reconciled with the record on every read.

    The spend and ``part_effects`` select on ``part_round`` and ``part_number``, so a
    column an outside writer changed would hide a spent part from the claim and let a
    second yes run; every read refuses the row as ``PlanningError`` instead.
    """
    path = tmp_path / "plans.db"
    store = SqlitePlanStore(path=path, now=_fixed_now)
    spent = _acted("e1").model_copy(update={"part": QuestionPart(round="q-round", part=1)})
    try:
        await store.claim_activation_effect(spent, match=None)
        with sqlite3.connect(path) as conn:
            conn.execute(tamper)
        with pytest.raises(PlanningError, match="the store is corrupt"):
            await store.activation_effects(["act-1"])
        with pytest.raises(PlanningError, match="the store is corrupt"):
            await store.export()
    finally:
        store.close()


async def test_a_spent_part_survives_a_restart(tmp_path: Path) -> None:
    """ADR-0321 §4:9: a part spent before a restart stays spent after it."""
    path = tmp_path / "plans.db"
    part = QuestionPart(round="q-round", part=1)
    store = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        await store.claim_activation_effect(
            _acted("e1").model_copy(update={"part": part}), match=None
        )
    finally:
        store.close()

    reopened = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        assert [one.id for one in await reopened.part_effects([part])] == ["e1"]
        again = _acted("e2", activation="act-2").model_copy(update={"part": part})
        assert await reopened.claim_activation_effect(again, match=None) is (
            ActivationEffectClaim.ALREADY_USED
        )
    finally:
        reopened.close()
