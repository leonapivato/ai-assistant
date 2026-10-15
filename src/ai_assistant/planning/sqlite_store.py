"""A durable :class:`~ai_assistant.core.protocols.PlanStore` on SQLite (ADR-0049).

The persistent counterpart to :class:`~ai_assistant.planning.store.InMemoryPlanStore`.
It follows the house style :mod:`ai_assistant.memory.sqlite_store` and
:mod:`ai_assistant.permissions.audit` set — one owned connection
(``check_same_thread=False``), an :class:`asyncio.Lock` around SQL run in a worker
thread, records stored as their pydantic JSON dump and rebuilt on every read (which is
how the "detached, validated snapshot" obligation is met without a copy step to
forget), and an owner-only database file.

It holds what the phases write and nothing else: the stop records ADR-0297 §1 gives
the store, and the activation effect records ADR-0306 §6 gives it. Each lives in its
own table, and :meth:`SqlitePlanStore.export` and :meth:`SqlitePlanStore.clear` carry
ADR-0004 §6's data rights over both. The goal, plan, execution, attempt, question,
evidence and goal-effect tables retired with the old path (ADR-0309 §5), and so did
their migrations: the cutover deploys on a fresh data directory, and no lane writes a
migration, a reader or a shim for a store written before it (ADR-0309 §6).
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import ActivationEffect, ActivationEffectClaim, PlanExport
from ai_assistant.planning._transactions import transaction
from ai_assistant.planning.activation_effects import (
    checked_effect_id,
    decide_activation_claim,
    finished,
    matched_activations,
    requested_activations,
    requested_parts,
    revalidated_claim,
)
from ai_assistant.planning.stops import revalidated_activation_id

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractContextManager

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import QuestionPart, ToolOutcome

_OWNER_ONLY = 0o600

#: The sidecars SQLite may keep beside a database file. Each holds the same pages
#: the database does, so ADR-0004 §4 reaches them too. SQLite copies the database
#: file's mode onto a sidecar **it creates**, which is what makes restricting the
#: file before the first statement sufficient for those — but that inheritance does
#: not reach one that is *already there*: a ``-journal`` left behind by a crash, or
#: a ``-wal``/``-shm`` from a process that put this file into WAL mode, keeps its
#: own mode across a reopen and then takes Tier 1 pages (#490).
_SIDECARS = ("-journal", "-wal", "-shm")

#: The on-disk schema this code understands, written to ``meta`` at creation
#: (ADR-0049 §1). **It is the only version this code opens.**
#:
#: **Version 11 is ADR-0309 §5's, and it is the first that carries no upgrade path.**
#: The store holds two tables, ``stopped_activations`` (ADR-0297 §1) and
#: ``activation_effects`` (ADR-0306 §6), and nothing else: the goal, plan, execution,
#: attempt, question, evidence and goal-effect tables retired with the members that
#: wrote them. The marker moves so that the two shapes are told apart at the open
#: rather than at a query: this code does not read a version 10 file's other tables,
#: so it could neither export nor clear the records they hold, and an older build
#: opening a version 11 file would find its own tables missing.
#:
#: **An older file is refused, not upgraded**, because ADR-0309 §6 has the cutover
#: deploy on a fresh data directory and says no lane writes a migration, a reader or a
#: shim for a store written before it. ADR-0049 §1's loud refusal of a **newer** label
#: binds entire, and the same refusal now covers every older one.
#:
#: **Version 12 is ADR-0321 §4:9's**: an effect record gains the question part it
#: spends, promoted to ``part_round`` and ``part_number`` so the claim and
#: :meth:`SqlitePlanStore.part_effects` select on it. A version 11 file has no such
#: columns, and ADR-0321 §9:2 has the deploy start from a fresh data directory, so it
#: is refused on the same ground as every older one.
_SCHEMA_VERSION = 12

# The ``meta`` table is created first and on its own, so the schema version can be
# read and any other version refused *before* a record table is created (ADR-0049
# §1: refuse before reading or writing records — creating a table is a write).
_META_SCHEMA = "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"

#: Every row stored under one ``meta`` key — read as a *set* of rows rather than
#: as a single value, because ``_META_SCHEMA``'s primary key is only in force for
#: a table this code created (see :meth:`SqlitePlanStore._read_meta`).
_READ_META = "SELECT value FROM meta WHERE key = ?"

_RECORD_SCHEMA = (
    # ADR-0297 §1's stop records. **The activation id is the whole row**: "a stop record
    # carries the activation id alone: no instant, no reason, no conversation and no
    # content", so there is no blob beside it, and declaring the id the primary key is
    # what makes `record_stop`'s idempotence the schema's — a second record of one
    # activation is `ON CONFLICT DO NOTHING` rather than a row beside the first.
    "CREATE TABLE IF NOT EXISTS stopped_activations(activation_id TEXT PRIMARY KEY)",
    # ADR-0306 §6's effect records. The record is the blob; `activation_id` is a column
    # because the backstop and the read select on it, and `claimed_seq` because they
    # return records in claim order. No foreign key: a record names an activation and a
    # decision, neither of which this store holds. `part_round` and `part_number` are the
    # question part a call under an approval spends (ADR-0321 §4:9), NULL on every other
    # record, because the claim and `part_effects` select on them across activations.
    "CREATE TABLE IF NOT EXISTS activation_effects("
    "id TEXT PRIMARY KEY, activation_id TEXT NOT NULL, claimed_seq INTEGER NOT NULL, "
    "data TEXT NOT NULL, part_round TEXT, part_number INTEGER)",
)

#: Each record column's ``(affinity, required NOT NULL)``. ``CREATE TABLE IF NOT
#: EXISTS`` is a no-op against a pre-existing table of a different shape (#373),
#: exactly as it is for the ``meta`` table (#349), so a hand-built
#: ``activation_effects`` whose ``claimed_seq`` is ``TEXT`` makes ``ORDER BY
#: claimed_seq`` lexical — the claim order silently lost — and a ``data`` that is not
#: text changes what ``model_validate_json`` is handed, all while every other check
#: passes. Each record table is read back with ``PRAGMA table_info`` and required to
#: carry these columns at these affinities (see
#: :meth:`SqlitePlanStore._verify_record_tables`). NOT NULL is only *required* where
#: the schema declares it, never forbidden: ``id`` is a ``TEXT PRIMARY KEY``, which
#: SQLite does not make implicitly ``NOT NULL``, so a file that hardens it is
#: compatible and must not be refused.
#: The columns every read of an effect record selects, in the order
#: :func:`_checked_activation_effect` reconciles them with the record.
_EFFECT_COLUMNS = "id, activation_id, data, part_round, part_number"

#: The rows carrying any of ``{keys}``'s question parts, in claim order: matched by the
#: promoted columns **or** by the record itself, so a row whose columns an outside
#: writer changed or cleared is still found, and then refused by
#: :func:`_checked_activation_effect` rather than read as a part nobody spent
#: (ADR-0321 §4:9). The parameters are the keys twice, once for each side.
_PART_ROWS = (
    "SELECT " + _EFFECT_COLUMNS + " FROM activation_effects "  # noqa: S608 — only constants and placeholders are interpolated
    "WHERE (part_round, part_number) IN (VALUES {keys}) "
    "OR (json_extract(data, '$.part.round'), json_extract(data, '$.part.part')) "
    "IN (VALUES {keys}) ORDER BY claimed_seq ASC"
)

_RECORD_COLUMNS: dict[str, dict[str, tuple[str, bool]]] = {
    "stopped_activations": {
        "activation_id": ("TEXT", False),
    },
    "activation_effects": {
        "id": ("TEXT", False),
        "activation_id": ("TEXT", True),
        "claimed_seq": ("INTEGER", True),
        "data": ("TEXT", True),
        "part_round": ("TEXT", False),
        "part_number": ("INTEGER", False),
    },
}

#: The column each record table's ``PRIMARY KEY`` is, checked against the key's own
#: index. A pre-existing table keyed on something else opens a store whose
#: ``ON CONFLICT`` writes and per-id uniqueness are silently absent, so the key is
#: required, not assumed (#373).
_RECORD_PRIMARY_KEY: dict[str, tuple[str, ...]] = {
    "stopped_activations": ("activation_id",),
    "activation_effects": ("id",),
}


def _affinity(declared_type: str) -> str:
    """Return SQLite's type affinity for a column's declared type.

    ``PRAGMA table_info`` reports the *declared* type, not the affinity SQLite
    derives from it, so the store's ``INTEGER``/``TEXT`` guarantees are compared on
    affinity rather than on the exact spelling — applying SQLite's documented rules
    (§3.1 of "Datatypes In SQLite") in order.
    """
    upper = declared_type.upper()
    if "INT" in upper:
        return "INTEGER"
    if "CHAR" in upper or "CLOB" in upper or "TEXT" in upper:
        return "TEXT"
    if not upper or "BLOB" in upper:
        return "BLOB"
    if "REAL" in upper or "FLOA" in upper or "DOUB" in upper:
        return "REAL"
    return "NUMERIC"


async def _run_to_completion[T](fn: Callable[..., T], /, *args: object) -> T:
    """Run ``fn`` in a worker thread, holding on until it *physically* finishes (ADR-0054).

    The store serialises one ``sqlite3`` connection behind an :class:`asyncio.Lock`
    and runs the SQL in a worker thread. A thread cannot be interrupted, so if the
    awaiting coroutine were simply cancelled the enclosing ``async with self._lock``
    would unwind and release the lock **while the worker was still using the
    connection** — letting a second caller use the same connection concurrently,
    which SQLite refuses.

    The worker records its own outcome and sets a :class:`threading.Event` when it
    physically returns. This coroutine waits on *that* signal — not on the
    cancellable state of any task — so the lock is held for the whole life of the
    worker even if the awaiting task, or a blanket :func:`asyncio.all_tasks`
    cancellation, is cancelled. Nothing here is an :class:`asyncio.Task`: the work
    runs on an executor future and the fallback wait is another, so a task sweep
    finds nothing to cancel out from under the running thread. An absorbed
    cancellation takes precedence over the worker's own result or failure and is
    re-raised once the thread has finished: the caller's task still cancels; what
    is prevented is connection reuse, not the cancellation itself.

    Every failure the worker sees is relayed, ``BaseException`` included. A
    narrower ``except Exception`` catches nothing when ``fn`` raises outside it, so
    both lists stay empty while ``finally: done.set()`` still fires — and the
    caller is then answered out of an empty ``outcome``, an ``IndexError`` standing
    in for the cause rather than chained to it (#680). Which of the two waits below
    runs decides whether the caller sees that or the real failure, which is why it
    presented as an intermittent fault rather than a reproducible one.

    **The completion wait is submitted at most once** (#697). Absorbing a
    cancellation hands the loop a blocking ``done.wait`` job on the default
    executor; a copy that submits a fresh one per cancellation leaves every earlier
    one running, because nothing can interrupt a thread parked in ``Event.wait``
    before the worker sets it. Repeated cancellation of one blocked call then
    occupies the whole pool, which turns one stalled store operation into a process
    that cannot run any thread work at all. Reusing the future costs a local and
    bounds the helper at two executor jobs however many cancellations arrive.
    """
    done = threading.Event()
    outcome: list[T] = []
    failure: list[BaseException] = []

    def worker() -> None:
        try:
            outcome.append(fn(*args))
        except BaseException as exc:  # relayed to the caller once the thread has finished
            failure.append(exc)
        finally:
            done.set()

    loop = asyncio.get_running_loop()
    pending: asyncio.Future[Any] = loop.run_in_executor(None, worker)
    waiting: asyncio.Future[Any] | None = None
    cancellation: asyncio.CancelledError | None = None
    while not done.is_set():
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError as exc:
            # Absorb the cancellation and keep waiting on the worker's physical
            # completion signal, so the lock outlives the still-running thread.
            # The signal is one job, reused: see the docstring.
            cancellation = exc
            if waiting is None:
                waiting = loop.run_in_executor(None, done.wait)
            pending = waiting
    if cancellation is not None:
        raise cancellation
    if failure:
        raise failure[0]
    return outcome[0]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SqlitePlanStore:
    """A persistent ``PlanStore`` backed by SQLite (ADR-0049).

    Structurally implements :class:`~ai_assistant.core.protocols.PlanStore`: the stop
    records and activation effect records the phases write, and the ADR-0004
    data-rights operations over both.
    """

    def __init__(self, *, path: Path | str, now: Clock = _utcnow) -> None:
        """Open (or create) the store at ``path``.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral store.
                **Required, with no default.** Durability is the reason this
                implementation exists (ADR-0049), so a default would let ordinary
                construction produce a store that forgets everything on restart —
                the failure this store exists to avoid. An ephemeral ``:memory:``
                store is available and has to be asked for.
            now: Clock for export timestamps; injectable for deterministic tests.
                Guarded by :func:`~ai_assistant.core.clock.checked_clock`, so a
                non-conforming reading is a ``PlanningError`` (ADR-0026).

        Raises:
            PlanningError: If the database cannot be opened or initialised, or is
                labelled with a schema version other than this code's.
        """
        self._path = path if path == ":memory:" else str(Path(path))
        self._clock = checked_clock(now, owner="SqlitePlanStore")
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    def _setup(self) -> sqlite3.Connection:
        """Connect, verify the version, create the schema, verify its shape."""
        try:
            conn = sqlite3.connect(self._path, check_same_thread=False)
        except (sqlite3.Error, OSError, ValueError) as exc:
            # e.g. the parent directory does not exist — no connection to close.
            # ``ValueError`` is named because a path carrying an embedded NUL
            # raises it out of the driver rather than a ``sqlite3.Error``, and a
            # bad path is this layer's fault to report rather than a raw builtin
            # escaping past the ``PlanningError`` boundary this constructor
            # documents (#1933; the last of the nine stores that carried the hole).
            msg = f"failed to open the plan store at {self._path!r}: {exc}"
            raise PlanningError(msg) from exc
        try:
            # Restricted *before* the first statement, not after the schema is
            # created. SQLite copies the database file's mode onto every rollback
            # journal it creates for it, so a journal opened while the file still
            # carried the process umask is world-readable too — and an interrupted
            # write leaves it on disk holding Tier 1 pages (ADR-0004 §1, §4). The
            # `BEGIN IMMEDIATE` below is exactly such a write. `connect` creates
            # the file, so there is something to restrict by the time this runs
            # (#451; `SqliteConversationStore._setup` has the same ordering).
            self._restrict_permissions()
            # `clear` is ADR-0004 §6's deletion, and an effect record carries the
            # values of a call made on the user's behalf. Without this, a deleted
            # row's bytes stay readable in the pages SQLite frees, so the deletion
            # would hold of the record and not of the file. It covers the pages
            # **this connection** frees, overflow pages included; it does not reach
            # the rollback journal SQLite unlinks at commit, a filesystem snapshot, a
            # copy-on-write clone or a device's wear levelling — ADR-0004 §4's
            # owner-only mode is where that question is answered. **Run outside the
            # transaction**: a pragma issued inside one is silently ignored by SQLite.
            conn.execute("PRAGMA secure_delete = ON")
            with conn:
                # BEGIN IMMEDIATE takes the write lock for the whole of setup, so
                # two processes opening a fresh file are serialised — one creates
                # and initialises, the other finds it done — rather than racing on
                # the meta insert (ADR-0049 §1).
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(_META_SCHEMA)
                # Refuse any other version *before* creating a record table, so a
                # rejected open leaves no schema behind (the transaction rolls the
                # meta table back too on the raise).
                self._verify_or_init_meta(conn)
                for statement in _RECORD_SCHEMA:
                    conn.execute(statement)
                self._verify_record_tables(conn)
        except PlanningError:
            conn.close()  # never leak the connection when opening fails
            raise
        except (sqlite3.Error, OSError) as exc:
            conn.close()
            msg = f"failed to initialise the plan store at {self._path!r}: {exc}"
            raise PlanningError(msg) from exc
        return conn

    def _restrict_permissions(self) -> None:
        """Make the database file and any sidecar beside it owner-only (ADR-0004 §4).

        A missing sidecar is the ordinary case rather than a fault — :data:`_SIDECARS`
        names every file SQLite *may* keep, and a cleanly closed database has none of
        them — so absence is tolerated one name at a time. Nothing else is: a sidecar
        this process cannot restrict is a Tier 1 file it is about to write through, so
        that failure propagates and the open fails.

        A *symlink* under a sidecar's name is skipped rather than followed. ``chmod``
        follows links, and ``os.chmod(follow_symlinks=False)`` is unsupported on
        Linux, so restricting one would silently narrow a file that holds none of
        this store's data and that this store has no business modifying.

        Skipping it strands no page anywhere this method could not reach, because
        SQLite does not follow such a link either (verified against 3.53.1, and
        asserted in the conversation store's tests): a symlinked ``-journal`` is not
        a hot journal, so SQLite unlinks *the link* at the first statement and writes
        a real file in its place — which inherits the ``0600`` set just above — and a
        symlinked ``-wal`` on a WAL-mode database is refused outright rather than
        written through. What is left is a check-then-chmod race, and winning it
        needs write access to the database's own directory, which is already past
        ADR-0004 §4 by routes this method could never close.

        A no-op in memory, where there is no file to restrict.
        """
        if self._path == ":memory:":
            return
        database = Path(self._path)
        database.chmod(_OWNER_ONLY)
        for suffix in _SIDECARS:
            sidecar = database.with_name(database.name + suffix)
            if sidecar.is_symlink():
                continue
            with contextlib.suppress(FileNotFoundError):
                sidecar.chmod(_OWNER_ONLY)

    def _verify_or_init_meta(self, conn: sqlite3.Connection) -> None:
        """Write the version on a fresh database, or refuse any other version.

        Runs inside the setup transaction. A stored ``schema_version`` other than
        :data:`_SCHEMA_VERSION` is refused with ``PlanningError`` *before any record
        table is created, read, or written* (ADR-0049 §1). A **newer** label is a file
        a later build wrote. An **older** one is a store written before the cutover,
        which ADR-0309 §6 leaves without a migration or a reader, or before an effect
        record carried its question part, which ADR-0321 §9:2 leaves the same way, so
        it is refused rather than opened over tables this code would neither export
        nor clear or columns it would not find. An
        unlabelled database is one this code is creating now, and it is stamped.

        The marker is read through :meth:`_read_meta`, so a store holding conflicting
        rows for it is refused rather than resolved by row order (issue #349). The
        file's tables are checked first (:meth:`_refuse_foreign_tables`), so a missing
        or rewritten marker cannot pass an older store off as a fresh or a current one.

        Raises:
            PlanningError: If the file holds a table this code does not create, the
                schema version is not this code's, or the marker is ambiguous or
                unparseable.
        """
        self._refuse_foreign_tables(conn)
        version = self._read_meta(conn, "schema_version")
        if not version:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(_SCHEMA_VERSION),),
            )
            return
        held = self._meta_int("schema_version", version[0])
        if held == _SCHEMA_VERSION:
            return
        msg = (
            f"the plan store at {self._path!r} has schema_version={held}, but this code "
            f"reads version {_SCHEMA_VERSION} only; refusing to open it rather than read it "
            f"blindly (a store written before the cutover, or before the question part, has "
            f"no reader: ADR-0309 §6, ADR-0321 §9:2)"
        )
        raise PlanningError(msg)

    def _refuse_foreign_tables(self, conn: sqlite3.Connection) -> None:
        """Refuse a file holding a table this code does not create, whatever its label.

        The version marker is what tells a store written before the cutover from this
        one, but a marker is one row: deleted, a pre-cutover file reads as a database
        this code is creating and is stamped, and rewritten to 12, it reads as current.
        Either way its ``goals``, ``plans`` or ``executions`` would stay in the file and
        outside :meth:`SqlitePlanStore.export` and :meth:`SqlitePlanStore.clear`,
        which is ADR-0004 §6 failing in silence. So the tables are read first: a file
        this code wrote holds ``meta`` and :data:`_RECORD_COLUMNS`' tables and nothing
        else, and any other table is refused before anything is written. Nothing in it
        is read or migrated (ADR-0309 §6). SQLite's own ``sqlite_`` tables are not the
        file's records and are passed over.

        Raises:
            PlanningError: If the file holds any other table.
        """
        own = {"meta", *_RECORD_COLUMNS}
        foreign = sorted(
            str(name)
            for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            # Lower-cased: SQLite identifiers are case-insensitive, so `META` is `meta`.
            if str(name).lower() not in own and not str(name).lower().startswith("sqlite_")
        )
        if not foreign:
            return
        msg = (
            f"the plan store at {self._path!r} holds tables this code neither creates nor "
            f"reads ({', '.join(foreign)}); a store written before the cutover has no reader "
            f"(ADR-0309 §6), and opening this one would leave their records outside export "
            f"and clear (ADR-0004 §6), so it is refused as it stands"
        )
        raise PlanningError(msg)

    def _verify_record_tables(self, conn: sqlite3.Connection) -> None:
        """Check each record table *is* the shape this store's guarantees rest on.

        ``CREATE TABLE IF NOT EXISTS`` is a no-op against a pre-existing table of a
        different shape, and nothing would validate the columns afterwards, so every
        guarantee built on those columns could be silently absent on a hand-built or
        corrupt file (issue #373). This is the same fail-open #349 closed for
        ``meta``: an object's name is not evidence about the object.

        So each table is read back with ``PRAGMA table_info`` and required to carry
        its :data:`_RECORD_COLUMNS` at the expected **affinity** — affinity, not the
        exact declared type, because that is what SQLite's ordering, comparison and
        storage actually key on (a ``TEXT`` ``claimed_seq`` orders lexically) — and
        ``NOT NULL`` where the schema declares it. Its ``PRIMARY KEY`` is verified
        too, because the ``ON CONFLICT`` writes and per-id uniqueness rest on it.
        Extra columns are tolerated: the store names every column it reads and
        writes, so a superset cannot mislead it, while a *missing*, wrong-affinity,
        wrongly-nullable or unkeyed one can.

        Runs at open, before any record is read or written, on ADR-0049 §1's
        posture: refuse a store whose guarantees cannot hold rather than open it and
        fail — or silently misbehave — at the first query.

        **Scope (deliberate, not exhaustive).** These checks defend against a shape
        mismatch that **silently subverts a store guarantee** — a check passes yet the
        store misbehaves invisibly: a lexical ``claimed_seq``, a case-folded id, a
        mutating trigger. They do **not** attempt exhaustive validation against a
        *hostile* hand-built schema. A construction that makes an operation fail
        **loudly** — a ``CHECK`` constraint, a generated column, an extra ``UNIQUE``
        index, ``WITHOUT ROWID``, a ``DEFAULT`` expression — surfaces a clear
        ``PlanningError`` at the write rather than silent corruption, and is out of
        scope: the plan database lives on the user's local disk (ADR-0004 §2), so
        anyone who can rewrite its schema already owns the data and the schema is not
        a security boundary against them.

        Raises:
            PlanningError: If a record table lacks an expected column, carries one at
                the wrong affinity or nullability, is not keyed as declared, or any
                table the store writes carries a trigger.
        """
        self._verify_no_triggers(conn)
        for table, expected in _RECORD_COLUMNS.items():
            # table_info rows are (cid, name, type, notnull, dflt_value, pk). Column
            # names are lower-cased: SQLite identifiers are case-insensitive, so a
            # `DATA` column is the `data` column and a case-variant but otherwise
            # compatible schema must be accepted, not refused (the names in
            # `_RECORD_COLUMNS` are the lower-case form).
            actual = {
                str(row[1]).lower(): (_affinity(str(row[2])), bool(row[3]))
                for row in conn.execute(f"PRAGMA table_info('{table}')")
            }
            self._verify_columns(table, expected, actual)
            self._verify_primary_key(conn, table)

    def _verify_no_triggers(self, conn: sqlite3.Connection) -> None:
        """Refuse a trigger on any table this store writes — ``meta`` included.

        The column and key checks describe a table's *shape*, but a pre-existing
        table of the exact shape can still carry an ``AFTER INSERT``/``UPDATE``
        trigger that silently subverts a write: one that rewrites ``NEW.id`` or
        corrupts ``data`` leaves a claim reporting a record stored while the row was
        moved underneath it, and one on ``meta`` can relabel the schema version the
        open was decided on. Both are *silent*: every other check passes. This store
        creates no triggers, so any trigger on a table it writes is foreign and there
        is no shape reading that makes a mutating one safe — refuse it at open.

        Raises:
            PlanningError: If any trigger is defined on a record table or ``meta``.
        """
        written_tables = {*_RECORD_COLUMNS, "meta"}
        triggers = sorted(
            str(name)
            for name, table in conn.execute(
                "SELECT name, tbl_name FROM sqlite_master WHERE type = 'trigger'"
            )
            # tbl_name is lower-cased: SQLite identifiers are case-insensitive, so a
            # trigger on `META` binds the same table as one on `meta`.
            if str(table).lower() in written_tables
        )
        if not triggers:
            return
        msg = (
            f"the plan store at {self._path!r} has triggers on the tables it writes "
            f"({', '.join(triggers)}); this store creates none, and a trigger can silently "
            f"rewrite or corrupt a row under a write it reported as stored, so it will not "
            f"open a database that can subvert its writes"
        )
        raise PlanningError(msg)

    def _verify_columns(
        self,
        table: str,
        expected: dict[str, tuple[str, bool]],
        actual: dict[str, tuple[str, bool]],
    ) -> None:
        """Require each column at its affinity and, where declared, its NOT NULL."""
        for column, (affinity, not_null) in expected.items():
            found = actual.get(column)
            if found is None:
                problem = "is absent"
            elif found[0] != affinity:
                problem = f"has {found[0]} affinity, not the {affinity} affinity"
            elif not_null and not found[1]:
                problem = "is nullable, not the NOT NULL"
            else:
                continue
            msg = (
                f"the plan store at {self._path!r} has a {table} table whose {column} "
                f"column {problem} this store's guarantees rest on (ADR-0049 §1); refusing "
                f"to open a table it did not shape rather than read or write records against "
                f"columns that will silently misbehave"
            )
            raise PlanningError(msg)

    def _verify_primary_key(self, conn: sqlite3.Connection, table: str) -> None:
        """Require ``table``'s primary key to be exactly its declared column, BINARY.

        The ``ON CONFLICT`` writes and the per-id uniqueness every record read assumes
        need the declared column to be the primary key; a pre-existing table without
        it, or keyed on something else, opens a store whose guarantee is silently
        absent (#373). The **collation** is load-bearing too: a ``COLLATE NOCASE`` key
        folds ``"A"`` and ``"a"`` into one row, so a claim of a case-variant id is
        refused as held, or a stop of one activation refuses another's claims —
        ``Identifier`` is case-sensitive, and ADR-0049 §1's schema is the default
        ``BINARY``.

        Read from the primary key's own index (``PRAGMA index_list`` origin ``pk``,
        then ``index_xinfo`` for its key columns and their collations), so both the
        column set and the collation are checked against the object rather than the
        column names alone.

        Raises:
            PlanningError: If the primary key is absent, over the wrong columns, or
                not BINARY-collated.
        """
        pk_indexes = [
            str(row[1])
            for row in conn.execute(f"PRAGMA index_list('{table}')")
            if row[3] == "pk"  # index_list rows are (seq, name, unique, origin, partial)
        ]
        # index_xinfo rows are (seqno, cid, name, desc, coll, key); key == 1 marks a
        # key column (vs an appended rowid), so a single-column pk yields one entry.
        # Names are lower-cased and the collation upper-cased: SQLite identifier and
        # collation names are both case-insensitive, so `ID`/`id` and `binary`/
        # `BINARY` are the same and a case-variant schema is not refused for casing.
        key_columns = (
            [
                (str(row[2]).lower(), str(row[4]).upper())
                for row in conn.execute(f"PRAGMA index_xinfo('{pk_indexes[0]}')")
                if row[5]
            ]
            if len(pk_indexes) == 1
            else []
        )
        expected = _RECORD_PRIMARY_KEY[table]
        if key_columns == [(column, "BINARY") for column in expected]:
            return
        if not key_columns:
            detail = "no PRIMARY KEY"
        elif [column for column, _coll in key_columns] != list(expected):
            detail = f"a PRIMARY KEY over {', '.join(column for column, _coll in key_columns)}"
        else:
            collations = ", ".join(sorted({collation for _column, collation in key_columns}))
            detail = f"a {collations}-collated {', '.join(expected)} PRIMARY KEY"
        msg = (
            f"the plan store at {self._path!r} has a {table} table with {detail}, not the "
            f"exact BINARY {', '.join(expected)} PRIMARY KEY (ADR-0049 §1) its upsert and "
            f"per-id uniqueness rest on; refusing to open a table it did not shape"
        )
        raise PlanningError(msg)

    def _read_meta(self, conn: sqlite3.Connection, key: str) -> list[Any]:
        """Return every value stored under ``key``, refusing an ambiguous store.

        ``meta``'s ``key TEXT PRIMARY KEY`` makes a second row for one key
        unreachable in a table *this* code created — but ``CREATE TABLE IF NOT
        EXISTS`` is a no-op against a pre-existing ``meta`` declared without that
        constraint, so a corrupt, hand-built or externally-migrated file can hold
        both ``('schema_version', '11')`` and ``('schema_version', '999')``.
        Collapsing the table into a ``dict`` kept whichever row SQLite returned
        last, which left the refusal in :meth:`_verify_or_init_meta` decided by
        **row order**: the same two rows in the other order opened the store on an
        unsupported schema (issue #349). That is a fail-open in a check whose only
        job is to refuse a database this code cannot read.

        Returns:
            The values found: empty when ``key`` is absent, otherwise exactly one.
            A row holding SQL ``NULL`` is a *present* row rather than an absent
            key — it comes back as ``[None]`` and is refused by :meth:`_meta_int`,
            instead of being silently re-inserted beside.

        Raises:
            PlanningError: If ``key`` has more than one row.
        """
        rows = conn.execute(_READ_META, (key,)).fetchall()
        if len(rows) > 1:
            found = ", ".join(sorted({repr(row[0]) for row in rows}))
            msg = (
                f"the plan store at {self._path!r} holds {len(rows)} {key} rows "
                f"({found}); the store cannot say which one it is and is corrupt"
            )
            raise PlanningError(msg)
        return [row[0] for row in rows]

    def _meta_int(self, key: str, raw: Any) -> int:
        """Parse a stored integer, translating corruption to ``PlanningError``.

        A non-numeric ``schema_version`` is a corrupt or tampered store, not a Python
        exception to leak past this layer's initialisation boundary (ADR-0049 §1).
        """
        msg = (
            f"the plan store at {self._path!r} holds a non-numeric {key} "
            f"({raw!r}); the store is corrupt"
        )
        # The values this code writes are always TEXT, but `CREATE TABLE IF NOT
        # EXISTS` also accepts a pre-existing `meta` whose `value` column has no
        # declared type, and SQLite then returns whatever was stored — a REAL, a
        # BLOB, a NULL. Only a string or an integer is parsed: `int(float("inf"))`
        # raises `OverflowError` and `int(None)` a `TypeError`, neither of which is
        # a `ValueError` nor an `AssistantError`, so both would leave this layer's
        # boundary through a hole. `bool` is an `int` in Python, so it is named
        # rather than left to read as version 0 or 1.
        if isinstance(raw, bool) or not isinstance(raw, str | int):
            raise PlanningError(msg)
        try:
            return int(raw)
        except ValueError as exc:
            raise PlanningError(msg) from exc

    def _now(self) -> datetime:
        """The guarded clock's reading, as `planning`'s own error (ADR-0026 §4).

        Raises:
            PlanningError: If the injected clock's reading is not a conforming
                one — naive, indeterminate, or outside the localizable range.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise PlanningError(str(exc)) from exc

    def _transaction(self, what: str) -> AbstractContextManager[sqlite3.Connection]:
        """Run the block inside one ``BEGIN IMMEDIATE`` transaction, translating failures.

        ``IMMEDIATE`` takes the write lock up front rather than at the first
        write, which is what puts the *reads* every mutation here decides on
        under it: the stop record and the held and matching records a claim is
        decided against, and the held record a finish is applied to. A deferred
        begin would leave each of those outside the lock and let a second process
        act on the state it read (ADR-0049 §1).

        ``what`` reads as the tail of ``failed to {what}``, which is the message
        :func:`_wrap` composes for the reads that run outside a transaction; the
        two spellings are deliberately the same sentence.

        Anything other than a backend failure propagates unchanged, after the
        transaction is rolled back — which is how a refused claim or finish leaves
        nothing behind.

        Raises:
            PlanningError: If the backend fails at any point.
        """
        return transaction(self._conn, what, error=PlanningError)

    # --- stop records and activation effect records ----------------------

    async def record_stop(self, activation_id: str, /) -> None:
        """Write a stop record naming ``activation_id``, idempotently (ADR-0297 §1).

        One ``BEGIN IMMEDIATE`` transaction under the connection lock, so the record and
        any claim are totally ordered: whichever commits first is the one the other
        is decided against.

        Raises:
            PlanningError: If ``activation_id`` is not an identifier, or the backend
                fails.
        """
        named = revalidated_activation_id(activation_id)
        async with self._lock:
            await _run_to_completion(self._record_stop_sync, named)

    def _record_stop_sync(self, activation_id: str) -> None:
        with self._transaction(f"record a stop of activation {activation_id!r}") as conn:
            conn.execute(
                "INSERT INTO stopped_activations(activation_id) VALUES (?) "
                "ON CONFLICT(activation_id) DO NOTHING",
                (activation_id,),
            )

    async def claim_activation_effect(
        self,
        effect: ActivationEffect,
        /,
        *,
        match: tuple[str, ...] | None,
        deliberate_repeat: bool = False,
    ) -> ActivationEffectClaim:
        """Claim one effect of an activation by writing its record (ADR-0306 §6:2).

        The stop, the held ids, the matching records and the write are read and
        decided inside one ``BEGIN IMMEDIATE`` transaction, so a second claim of an
        equal call waits on the write lock and then finds the first's record.

        Raises:
            ClaimStopped: If the store holds a stop record for the activation.
            PlanningError: If the id is already held, the record carries an outcome,
                a reason or a position, or the backend fails.
        """
        # Snapshotted before the first await, so a caller mutating its record while
        # this call is queued cannot change what is written (ADR-0018 §3).
        record = revalidated_claim(effect)
        named = matched_activations(match)
        async with self._lock:
            return await _run_to_completion(
                self._claim_activation_effect_sync, record, named, deliberate_repeat
            )

    def _claim_activation_effect_sync(
        self,
        record: ActivationEffect,
        named: tuple[str, ...] | None,
        deliberate_repeat: bool,
    ) -> ActivationEffectClaim:
        with self._transaction(f"claim activation effect {record.id!r}") as conn:
            held = conn.execute(
                "SELECT 1 FROM activation_effects WHERE id = ?", (record.id,)
            ).fetchone()
            # Every row carrying the part, by its promoted columns or by its record, and
            # each reconciled: a column an outside writer changed or cleared would
            # otherwise hide a spent part and let a second yes run (ADR-0321 §4:9).
            spent = record.part is not None and bool(
                [
                    _checked_activation_effect(str(self._path), row)
                    for row in conn.execute(
                        _PART_ROWS.format(keys="(?, ?)"),
                        (record.part.round, record.part.part) * 2,
                    ).fetchall()
                ]
            )
            matched: list[ActivationEffect] = []
            if named:
                marks = ", ".join("?" for _ in named)
                matched = [
                    _checked_activation_effect(str(self._path), row)
                    for row in conn.execute(
                        "SELECT " + _EFFECT_COLUMNS + " FROM activation_effects "  # noqa: S608 — only placeholders are interpolated
                        f"WHERE activation_id IN ({marks}) ORDER BY claimed_seq ASC",
                        named,
                    ).fetchall()
                ]
            answer = decide_activation_claim(
                record,
                match=named,
                deliberate_repeat=deliberate_repeat,
                stopped=_is_stopped(conn, record.activation_id),
                held_ids=() if held is None else (record.id,),
                matched=matched,
                spent=spent,
            )
            if answer is ActivationEffectClaim.CLAIMED:
                part = record.part
                conn.execute(
                    "INSERT INTO activation_effects(id, activation_id, claimed_seq, data, "
                    "part_round, part_number) "
                    "VALUES (?, ?, (SELECT COALESCE(MAX(claimed_seq), 0) + 1 "
                    "FROM activation_effects), ?, ?, ?)",
                    (
                        record.id,
                        record.activation_id,
                        record.model_dump_json(),
                        None if part is None else part.round,
                        None if part is None else part.part,
                    ),
                )
        return answer

    async def finish_activation_effect(
        self,
        effect_id: str,
        /,
        outcome: ToolOutcome,
        *,
        reason: str | None = None,
        position: int | None = None,
    ) -> None:
        """Write a claimed effect's outcome, once (ADR-0306 §6:4).

        The read of the held record and the write are one ``BEGIN IMMEDIATE``
        transaction, so two finishes of one record cannot both land.

        Raises:
            PlanningError: If the record is not held or already finished, the reason
                or position does not belong to the outcome, or the backend fails.
        """
        named = checked_effect_id(effect_id)
        async with self._lock:
            await _run_to_completion(
                self._finish_activation_effect_sync, named, outcome, reason, position
            )

    def _finish_activation_effect_sync(
        self, effect_id: str, outcome: object, reason: object, position: object
    ) -> None:
        with self._transaction(f"finish activation effect {effect_id!r}") as conn:
            row = conn.execute(
                "SELECT " + _EFFECT_COLUMNS + " FROM activation_effects WHERE id = ?",  # noqa: S608 — only a constant is interpolated
                (effect_id,),
            ).fetchone()
            held = None if row is None else _checked_activation_effect(str(self._path), row)
            record = finished(held, effect_id, outcome, reason=reason, position=position)
            conn.execute(
                "UPDATE activation_effects SET data = ? WHERE id = ?",
                (record.model_dump_json(), effect_id),
            )

    async def activation_effects(
        self, activation_ids: Sequence[str], /
    ) -> tuple[ActivationEffect, ...]:
        """Return the named activations' effect records, in claim order (ADR-0306 §6:5).

        Raises:
            PlanningError: If ``activation_ids`` is a bare string, or the backend fails.
        """
        named = requested_activations(activation_ids)
        if not named:
            return ()
        async with self._lock:
            rows = await _run_to_completion(self._activation_effects_sync, named)
        return tuple(_checked_activation_effect(str(self._path), row) for row in rows)

    def _activation_effects_sync(self, named: tuple[str, ...]) -> list[tuple[Any, ...]]:
        marks = ", ".join("?" for _ in named)
        try:
            return [
                tuple(row)
                for row in self._conn.execute(
                    "SELECT " + _EFFECT_COLUMNS + " FROM activation_effects "  # noqa: S608 — only placeholders are interpolated
                    f"WHERE activation_id IN ({marks}) ORDER BY claimed_seq ASC",
                    named,
                ).fetchall()
            ]
        except sqlite3.Error as exc:
            raise _wrap("read activation effects", "", exc) from exc

    async def part_effects(self, parts: Sequence[QuestionPart], /) -> tuple[ActivationEffect, ...]:
        """Return the records carrying any of ``parts``, in claim order (ADR-0321 §4:9).

        Raises:
            PlanningError: If ``parts`` holds anything but a ``QuestionPart``, or the
                backend fails.
        """
        named = requested_parts(parts)
        if not named:
            return ()
        async with self._lock:
            rows = await _run_to_completion(self._part_effects_sync, named)
        return tuple(_checked_activation_effect(str(self._path), row) for row in rows)

    def _part_effects_sync(self, named: tuple[QuestionPart, ...]) -> list[tuple[Any, ...]]:
        keys = ", ".join("(?, ?)" for _ in named)
        values = [value for one in named for value in (one.round, one.part)]
        try:
            return [
                tuple(row)
                for row in self._conn.execute(_PART_ROWS.format(keys=keys), values * 2).fetchall()
            ]
        except sqlite3.Error as exc:
            raise _wrap("read activation effects by question part", "", exc) from exc

    # --- data rights (ADR-0004) -------------------------------------------

    async def export(self) -> PlanExport:
        """Return a portable, internally consistent snapshot (ADR-0004 §6).

        The document carries the two kinds of record this store holds: every stop
        record, and every activation effect record in claim order. Its goal, plan,
        execution, attempt, question, evidence and goal-effect sections left it with
        the members that wrote them (ADR-0309 §5).
        """
        exported_at = self._now()
        async with self._lock:
            stopped, acted = await _run_to_completion(self._export_sync)
        return PlanExport(
            exported_at=exported_at,
            # ADR-0297 §1: every stop record, in a deterministic order.
            stopped_activations=tuple(stopped),
            # ADR-0306 §6: every effect record, in claim order.
            activation_effects=tuple(acted),
        )

    def _export_sync(self) -> tuple[list[str], list[ActivationEffect]]:
        # Both reads inside one transaction, so the export is a single database
        # snapshot. The write form, not the deferred one a read would otherwise take:
        # the write lock excludes a writer outright rather than leaving the reads to a
        # snapshot another connection is free to write around.
        with self._transaction("export planning state") as conn:
            # Each stop record is revalidated as the identifier it was written as, so
            # a row an outside writer blanked or nulled is refused as `planning`'s own
            # error rather than escaping as a raw validation failure of the document.
            stopped: list[str] = [
                revalidated_activation_id(r[0])
                for r in conn.execute(
                    "SELECT activation_id FROM stopped_activations ORDER BY activation_id ASC"
                ).fetchall()
            ]
            acted = [
                _checked_activation_effect(str(self._path), row)
                for row in conn.execute(
                    "SELECT " + _EFFECT_COLUMNS + " FROM activation_effects "  # noqa: S608 — only a constant is interpolated
                    "ORDER BY claimed_seq ASC"
                ).fetchall()
            ]
        return stopped, acted

    async def clear(self) -> int:
        """Delete every stop record and activation effect record, returning the count.

        The store holds no execution, so no live step can refuse the erase.
        """
        async with self._lock:
            return await _run_to_completion(self._clear_sync)

    def _clear_sync(self) -> int:
        with self._transaction("clear the plan store") as conn:
            # ADR-0297 §1: `clear` erases every stop record with the store's other rows.
            removed: int = conn.execute("DELETE FROM stopped_activations").rowcount
            # ADR-0306 §6: and every effect record. `meta` is untouched.
            removed += conn.execute("DELETE FROM activation_effects").rowcount
        return removed

    def close(self) -> None:
        """Close the underlying database connection."""
        with contextlib.suppress(sqlite3.Error):
            self._conn.close()


def _is_stopped(conn: sqlite3.Connection, activation_id: str) -> bool:
    """Whether the store holds a stop record for ``activation_id`` (ADR-0297 §2).

    Read on the caller's connection, which is the claim transaction's own.
    """
    row = conn.execute(
        "SELECT 1 FROM stopped_activations WHERE activation_id = ?", (activation_id,)
    ).fetchone()
    return row is not None


def _wrap(action: str, subject: str, exc: sqlite3.Error) -> PlanningError:
    """Translate a raw ``sqlite3`` fault into `planning`'s own error at the seam."""
    target = f" {subject!r}" if subject else ""
    return PlanningError(f"failed to {action}{target}: {exc}")


def _checked_activation_effect(path: str, row: Sequence[Any]) -> ActivationEffect:
    """Decode one effect record and refuse a blob that disagrees with its columns.

    The id, the activation and the question part are promoted, and the backstop, the
    spend and the reads select on them, so each is reconciled with the record a
    tampered file could answer with.

    Args:
        path: The store's path, for the message.
        row: ``(id, activation_id, data, part_round, part_number)``.

    Returns:
        The reconciled record.

    Raises:
        PlanningError: If the blob does not validate, or disagrees with its columns.
    """
    try:
        record = ActivationEffect.model_validate_json(str(row[2]))
    except ValidationError as exc:
        msg = f"the plan store holds an activation effect that no longer validates: {exc}"
        raise PlanningError(msg) from exc
    promoted = (str(row[0]), str(row[1]), row[3], row[4])
    part = record.part
    held = (
        record.id,
        record.activation_id,
        None if part is None else part.round,
        None if part is None else part.part,
    )
    if promoted != held:
        msg = (
            f"the plan store at {path!r} holds an activation effect indexed at {promoted} "
            f"whose record names {held}; the store is corrupt"
        )
        raise PlanningError(msg)
    return record


__all__ = ["SqlitePlanStore"]
