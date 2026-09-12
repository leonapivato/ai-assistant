"""A durable :class:`~ai_assistant.core.protocols.PlanStore` on SQLite (ADR-0049).

The persistent counterpart to :class:`~ai_assistant.planning.store.InMemoryPlanStore`.
It follows the house style :mod:`ai_assistant.memory.sqlite_store` and
:mod:`ai_assistant.permissions.audit` set — one owned connection
(``check_same_thread=False``), an :class:`asyncio.Lock` around SQL run in
:func:`asyncio.to_thread`, records stored as their pydantic JSON dump and rebuilt
on every read (which is how the "detached, validated snapshot" obligation is met
without a copy step to forget), and an owner-only database file.

What is new here is persistence, and only persistence: every step transition is
still delegated to the same :class:`~ai_assistant.planning.execution.PlanExecution`
tracker :class:`InMemoryPlanStore` uses, so the ADR-0014 §4 transition graph is
authoritative in exactly one place and the two stores cannot drift on it. This
store adds durability of that state across a restart (ADR-0049 §2), execution-id
non-reuse by a per-incarnation ``pid``-and-nonce plus a durable ordinal
(ADR-0049 §3), and referential integrity via enforced foreign keys (ADR-0049 §1).

The durable ordinal is only worth what its *monotonicity* is worth, so it carries
a high-water mark beside it in ``meta`` and the store refuses a counter that has
fallen below it — at open and again at every allocation — with the records and a
unique ``created_seq`` beneath that as the durable backstop (ADR-0064).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from uuid import uuid4

from pydantic import ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import ActiveExecutionError, PlanningError, StaleExecutionError
from ai_assistant.core.types import (
    ActionPlan,
    ExecutionState,
    Goal,
    GoalAttempt,
    GoalDeletion,
    GoalInterpretation,
    GoalQuestion,
    GoalQuestionDisposition,
    MemorySource,
    PlanExport,
    StepStatus,
    ground_of,
)
from ai_assistant.planning._transactions import transaction
from ai_assistant.planning.execution import PlanExecution
from ai_assistant.planning.goals import advanced, appended, bounded, capped, engaged, settled
from ai_assistant.planning.goals import with_status as _with_status

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import (
        AttemptTransition,
        GoalCandidates,
        GoalRevision,
        GoalStatus,
        StepTransition,
        UtcInstant,
    )

_OWNER_ONLY = 0o600

#: The sidecars SQLite may keep beside a database file. Each holds the same pages
#: the database does, so ADR-0004 §4 reaches them too. SQLite copies the database
#: file's mode onto a sidecar **it creates**, which is what makes restricting the
#: file before the first statement sufficient for those — but that inheritance does
#: not reach one that is *already there*: a ``-journal`` left behind by a crash, or
#: a ``-wal``/``-shm`` from a process that put this file into WAL mode, keeps its
#: own mode across a reopen and then takes Tier 1 pages (#490).
_SIDECARS = ("-journal", "-wal", "-shm")

#: The on-disk schema this code understands. Written to ``meta`` at creation
#: (ADR-0049 §1) so a *future* version has a marker to migrate from; opening a
#: database labelled **newer** than this is refused loudly rather than read blindly.
#:
#: **2 since ADR-0249 §12**, which lands this store's first migration and partially
#: supersedes ADR-0049 §1's "the migration is table creation only" in that clause
#: alone. ``Goal`` gains an ``interpretation`` and four more fields and loses
#: ``statement`` from its dump, and the ``attempts`` table is new, so a version 1
#: ``goals`` row no longer decodes. §1's marker is relied on as exactly the thing it
#: was written for — "so a **future** schema change has the version marker" — and its
#: loud refusal of a newer label binds entire: a version 1 store is **older**, and is
#: upgraded in place rather than refused.
#: **3 since ADR-0250 §9**, which lands this store's **second** migration: the
#: ``goal_questions`` table, and the two ``goals`` columns ``candidates_for`` reads.
#: A version 2 ``goals`` row still **decodes** — ``Goal.last_engaged_in`` is defaulted,
#: so the blob needs no rewrite — but the columns beside it do not exist, so the
#: candidate-set query would be a raw "no such column" on every conversation. The
#: marker is what makes the upgrade in place possible, exactly as at 2, and §1's loud
#: refusal of a **newer** label binds entire.
_SCHEMA_VERSION = 3

#: The versions a database this code can upgrade carries. Two members since ADR-0250:
#: version 1 is ADR-0049 §1's original shape and version 2 is ADR-0249 §12's, and the
#: two need different work — a version 1 store's ``goals`` blobs are rewritten
#: (:meth:`SqlitePlanStore._upgrade_goal_rows`) where a version 2 store's are not,
#: while **both** gain the new columns and the questions table.
_UPGRADABLE_FROM: Final[frozenset[int]] = frozenset({1, 2})

# The ``meta`` table is created first and on its own, so the schema version can be
# read and a newer store refused *before* any record table is created (ADR-0049
# §1: refuse before reading or writing records — creating a table is a write).
_META_SCHEMA = "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"

#: Every row stored under one ``meta`` key — read as a *set* of rows rather than
#: as a single value, because ``_META_SCHEMA``'s primary key is only in force for
#: a table this code created (see :meth:`SqlitePlanStore._read_meta`).
_READ_META = "SELECT value FROM meta WHERE key = ?"

#: The ``meta`` key holding the highest value ``exec_counter`` has ever reached
#: (ADR-0064). ADR-0049 §3 rests execution-id non-reuse on the ordinal never
#: rewinding, but nothing checked it: the counter is a single mutable row, and an
#: outside writer that lowers it makes the store re-mint ids it has already handed
#: out (issue #356). The mark is the durable witness that makes the rewind
#: *detectable* — it advances in lockstep with the counter, in the same
#: transaction, so the two only disagree when something outside this store moved
#: one of them.
_HIGH_WATER = "exec_high_water"

_WRITE_HIGH_WATER = "INSERT INTO meta(key, value) VALUES ('exec_high_water', ?)"

_UPDATE_HIGH_WATER = "UPDATE meta SET value = ? WHERE key = 'exec_high_water'"

#: The two ``goals`` columns ADR-0250 §9's migration adds, beside the blob. They are
#: the two that decide **candidate-set membership** (§2) — the conversation the goal
#: was opened in, and the conversation that last engaged it — so
#: ``candidates_for`` is a query rather than a scan-and-decode of every goal in the
#: store. Both are nullable: ``conversation_id`` because a row written before ADR-0249
#: carries none, and ``last_engaged_in`` because a row written before ADR-0250 does
#: (§1's one route to a ``None``). The **order** the set is then put in is
#: :func:`~ai_assistant.planning.goals.capped`'s, over the decoded rows, so §1's key
#: is stated once for both stores rather than once here in SQL and once in Python.
_GOAL_COLUMNS: Final[tuple[str, ...]] = ("conversation_id", "last_engaged_in")

_RECORD_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS goals("
    "id TEXT PRIMARY KEY, conversation_id TEXT, last_engaged_in TEXT, data TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS plans("
    "id TEXT PRIMARY KEY, goal_id TEXT NOT NULL REFERENCES goals(id), data TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS executions("
    "id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(id), "
    "version INTEGER NOT NULL, active INTEGER NOT NULL, "
    "created_seq INTEGER NOT NULL, data TEXT NOT NULL)",
    # ADR-0249 §12's attempts table, with the foreign key onto `goals` ADR-0049 §1's
    # schema discipline requires. `opened_at` is a plain column and decides nothing
    # but `attempts_of`'s contractual order; the blob is the record, exactly as it is
    # for the three tables above. On a version 1 database this table is **created
    # empty**, because such a store holds no attempt.
    "CREATE TABLE IF NOT EXISTS attempts("
    "id TEXT PRIMARY KEY, goal_id TEXT NOT NULL REFERENCES goals(id), "
    "opened_at TEXT NOT NULL, data TEXT NOT NULL)",
    # ADR-0250 §9's questions table, with the foreign key onto `goals` ADR-0049 §1's
    # schema discipline requires. `attempt_id` carries no declared key: this store
    # declares one foreign key per table, and `record_question` refuses a dangling
    # attempt at the write exactly as `open_attempt` refuses a dangling plan.
    # `disposition` is a plain column and decides nothing but the one-open gate's
    # query and `outstanding_questions`; `asked_at` decides that member's contractual
    # order; the blob is the record, as it is for the four tables above.
    "CREATE TABLE IF NOT EXISTS goal_questions("
    "id TEXT PRIMARY KEY, goal_id TEXT NOT NULL REFERENCES goals(id), "
    "attempt_id TEXT NOT NULL, asked_at TEXT NOT NULL, disposition TEXT NOT NULL, "
    "data TEXT NOT NULL)",
)

#: ``created_seq`` is unique by construction — every allocation takes it from the
#: counter it increments in the same ``BEGIN IMMEDIATE`` transaction — so declaring
#: it makes ADR-0049 §1's oldest-first ordering a property of the *schema* rather
#: than a convention the counter is trusted to keep (ADR-0064 §4). It is the
#: backstop beneath the high-water mark, in the same way the foreign keys sit
#: beneath ``save_plan``'s app-level orphan check: whatever route a second row at
#: one ordinal arrives by — a rewound counter this code did not see, a concurrent
#: writer that does not maintain the mark — SQLite refuses it rather than letting
#: ``active_executions``/``export`` quietly stop being an order. Created after the
#: table and before the mark is reconciled, so a file that *already* holds
#: duplicates is refused at the open (ADR-0049 §1's posture) rather than carried.
_INDEXES = ("CREATE UNIQUE INDEX IF NOT EXISTS executions_created_seq ON executions(created_seq)",)

#: ``IF NOT EXISTS`` keys on the *name*, so a pre-existing index called this and
#: shaped differently — non-unique, on another column, or partial — leaves the
#: creation above a silent no-op and the backstop absent. The name is checked
#: against the object it actually names (see
#: :meth:`SqlitePlanStore._verify_the_ordinal_index`), the same reasoning issue
#: #349 applied to a ``meta`` table this code did not shape.
_ORDINAL_INDEX = "executions_created_seq"

#: The one ``_UPGRADABLE_FROM`` version whose ``goals`` **blobs** need rewriting: at
#: version 1 a row carries a ``statement`` and no ``interpretation`` (ADR-0249 §12), so
#: it does not decode at all, while a version 2 row decodes unchanged and needs only
#: the two columns beside it (ADR-0250 §9).
_VERSION_BEFORE_INTERPRETATIONS: Final[int] = 1

#: Each record column's ``(affinity, required NOT NULL)``. ``CREATE TABLE IF NOT
#: EXISTS`` is a no-op against a pre-existing table of a different shape (#373),
#: exactly as it is for the ``meta`` table (#349) and the ordinal index (#364), so
#: a hand-built ``executions`` whose ``created_seq`` is ``TEXT`` makes ``ORDER BY
#: created_seq``/``MAX(created_seq)`` lexical — the ADR-0049 §1 oldest-first order
#: silently lost — a ``version`` without integer affinity breaks the CAS compare, a
#: non-integer ``active`` breaks ``WHERE active = 1``, a ``data`` that is not text
#: changes what ``model_validate_json`` is handed, and a nullable ``data`` can store
#: a ``NULL`` no decode accepts, all while every other check passes. Each record
#: table is read back with ``PRAGMA table_info`` and required to carry these columns
#: at these affinities (see :meth:`SqlitePlanStore._verify_record_tables`). NOT NULL
#: is only *required* where the schema declares it, never forbidden: ``id`` is a
#: ``TEXT PRIMARY KEY``, which SQLite does not make implicitly ``NOT NULL``, so a
#: file that hardens it is compatible and must not be refused.
_RECORD_COLUMNS: dict[str, dict[str, tuple[str, bool]]] = {
    "goals": {
        "id": ("TEXT", False),
        "conversation_id": ("TEXT", False),
        "last_engaged_in": ("TEXT", False),
        "data": ("TEXT", True),
    },
    "plans": {
        "id": ("TEXT", False),
        "goal_id": ("TEXT", True),
        "data": ("TEXT", True),
    },
    "executions": {
        "id": ("TEXT", False),
        "plan_id": ("TEXT", True),
        "version": ("INTEGER", True),
        "active": ("INTEGER", True),
        "created_seq": ("INTEGER", True),
        "data": ("TEXT", True),
    },
    "attempts": {
        "id": ("TEXT", False),
        "goal_id": ("TEXT", True),
        "opened_at": ("TEXT", True),
        "data": ("TEXT", True),
    },
    "goal_questions": {
        "id": ("TEXT", False),
        "goal_id": ("TEXT", True),
        "attempt_id": ("TEXT", True),
        "asked_at": ("TEXT", True),
        "disposition": ("TEXT", True),
        "data": ("TEXT", True),
    },
}

#: The single column every record table's ``PRIMARY KEY`` is, checked against
#: ``PRAGMA table_info``'s ``pk`` flag. A pre-existing table without it opens a
#: store whose ``save_goal`` ``ON CONFLICT(id)`` upsert and per-id uniqueness are
#: silently absent, so the key is required, not assumed (#373).
_RECORD_PRIMARY_KEY = "id"

#: The foreign keys ADR-0049 §1's referential-integrity backstop rests on, absent
#: on a pre-existing table this code did not create. ``table -> (child column,
#: parent table, parent column)``; read back with ``PRAGMA foreign_key_list``. The
#: parent column is checked too, so a key that resolves to the wrong column — a
#: ``REFERENCES goals(data)`` in place of ``goals(id)`` — is refused, not accepted
#: on the table name alone (see :meth:`SqlitePlanStore._verify_foreign_key`).
_RECORD_FOREIGN_KEYS: dict[str, tuple[str, str, str]] = {
    "plans": ("goal_id", "goals", "id"),
    "executions": ("plan_id", "plans", "id"),
    "attempts": ("goal_id", "goals", "id"),
    "goal_questions": ("goal_id", "goals", "id"),
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

    Structurally implements :class:`~ai_assistant.core.protocols.PlanStore`,
    including the compare-and-swap write path, the ADR-0044 §1 execution-id
    non-reuse guarantee, and the ADR-0004 data-rights operations.
    """

    def __init__(
        self,
        *,
        path: Path | str,
        now: Clock = _utcnow,
        tracker: PlanExecution | None = None,
        incarnation_factory: Callable[[], str] = lambda: uuid4().hex,
    ) -> None:
        """Open (or create) the store at ``path``.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral store.
                **Required, with no default.** Durability is the reason this
                implementation exists (ADR-0049), so a default would let ordinary
                construction produce a store that forgets everything on restart —
                the failure this store exists to avoid. An ephemeral ``:memory:``
                store is available and has to be asked for; its non-reuse still
                holds via the per-incarnation nonce (ADR-0049 §3), not the durable
                ordinal.
            now: Clock for export timestamps and, by default, the transition
                tracker; injectable for deterministic tests. Guarded by
                :func:`~ai_assistant.core.clock.checked_clock`, so a
                non-conforming reading is a ``PlanningError`` (ADR-0026).
            tracker: The transition tracker to validate writes against. Defaults
                to a :class:`PlanExecution` sharing this store's clock. The
                *unwrapped* clock is handed on, so a bad reading names the seam
                that read it.
            incarnation_factory: Mints the per-incarnation nonce folded into an
                execution id (ADR-0049 §3). Defaults to ``uuid4().hex``; a test
                injects fixed values to make the id-composition assertions
                deterministic (the ``id_factory`` seam #305 asks for). Production
                never passes it.

        Raises:
            PlanningError: If the database cannot be opened or initialised, is
                labelled with a schema version this code does not understand, or
                holds an ``exec_counter`` rewound below the high-water mark of the
                ordinals it has already issued (ADR-0064).
        """
        self._path = path if path == ":memory:" else str(Path(path))
        self._clock = checked_clock(now, owner="SqlitePlanStore")
        self._tracker = tracker or PlanExecution(now=now)
        self._incarnation_factory = incarnation_factory
        # Minted once per store object. Folded together with os.getpid() *at
        # allocation time* (see start_execution), so a fork that copies this
        # value still yields distinct ids by the differing pid (ADR-0049 §3).
        self._nonce = incarnation_factory()
        # ADR-0249 §12: the version this file arrived at where it is one this code
        # upgrades, else ``None``. Set by ``_verify_or_init_meta`` inside the setup
        # transaction and read by ``_upgrade_goal_rows`` and the marker move below it.
        self._upgrade_from: int | None = None
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    def _setup(self) -> sqlite3.Connection:
        """Connect, enforce foreign keys, create the schema, verify the version."""
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
            # Per-connection, not persisted: the referential-integrity guard of
            # ADR-0049 §1 is only in force while this pragma is on.
            conn.execute("PRAGMA foreign_keys = ON")
            # **Why this store takes a pragma the family did not**, and what changed.
            # `permissions/parked_reads.py` reasons that it "is the one in the tree
            # whose ADR states a retention rule over named fields it clears **in
            # place** … nowhere else here does a store's contract promise that a value
            # is gone while the row survives". ADR-0250 §8 makes that no longer true:
            # `settle_question` "clears `text` and `about` **in the same step that
            # moves the disposition**", "no implementation retains a copy, a digest, a
            # snapshot or an archive of either", and "the content lives exactly as long
            # as the question does". Without this, replacing the row's JSON leaves the
            # cleared text readable in freed pages, so the promise would hold of the
            # record and not of the file.
            #
            # **What it does and does not reach**, stated narrowly because this store
            # is older than the pragma. It covers the pages **this connection** frees,
            # overflow pages included, for every byte written from this open onward —
            # which is every question this decision writes, since the record is new and
            # no question content can predate it. It does **not** retroactively scrub a
            # goal, plan or execution page an earlier open already freed, and it does
            # not reach the rollback journal SQLite unlinks at commit, a filesystem
            # snapshot, a copy-on-write clone or a device's wear levelling — ADR-0004
            # §4's owner-only mode is where that question is answered and ADR-0099 §1's
            # single-user model is what scopes it. **Run outside the transaction**: a
            # pragma issued inside one is silently ignored by SQLite.
            conn.execute("PRAGMA secure_delete = ON")
            with conn:
                # BEGIN IMMEDIATE takes the write lock for the whole of setup, so
                # two processes opening a fresh file are serialised — one creates
                # and initialises, the other finds it done — rather than racing on
                # the meta insert (ADR-0049 §1).
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(_META_SCHEMA)
                # Refuse a newer store — or one whose counter has been rewound —
                # *before* creating any record table, so a rejected open leaves no
                # schema behind (the transaction rolls the meta table back too on
                # the raise).
                counter, mark = self._verify_or_init_meta(conn)
                for statement in (*_RECORD_SCHEMA, *_INDEXES):
                    conn.execute(statement)
                # ADR-0250 §9's column half of the migration, *before* the shape
                # checks: `CREATE TABLE IF NOT EXISTS` is a no-op against the
                # pre-existing `goals` of a version 1 or 2 store, so the two new
                # columns have to be added by `ALTER TABLE` or `_verify_record_tables`
                # would refuse the very file this open is here to upgrade.
                self._add_missing_goal_columns(conn)
                self._verify_record_tables(conn)
                self._verify_the_ordinal_index(conn)
                # **ADR-0249 §12's migration, in the same transaction the shape checks
                # ran in** — so a failure leaves the file exactly as it arrived:
                # unupgraded, still labelled 1, and refusing to open rather than
                # half-migrated. It runs *after* the tables are created and verified,
                # because it rewrites rows of one of them, and *before* the marker is
                # moved below.
                self._upgrade_goal_rows(conn)
                # And the column half's backfill, after the blobs are whatever this
                # file's version leaves them: the two columns are projections of the
                # blob, so they are written from it rather than guessed.
                self._backfill_goal_columns(conn)
                # Reconciled *after* the schema above, in the same transaction, so
                # the mark is only written for a file this open has actually brought
                # to the current shape — and a failure rolls it back rather than
                # leaving a database falsely labelled. This is
                # `SqliteAuditTrail._check_schema_version`'s ordering (#346),
                # applied to the second marker this store backfills; it is also what
                # puts `executions` in scope for the corroboration.
                self._reconcile_high_water(conn, counter, mark)
                if self._upgrade_from is not None:
                    # Stamped last and inside the same transaction, so a failure
                    # anywhere above rolls the marker back with the rows rather than
                    # leaving a database falsely labelled current. An UPDATE rather
                    # than an upsert because the row already exists.
                    conn.execute(
                        "UPDATE meta SET value = ? WHERE key = 'schema_version'",
                        (str(_SCHEMA_VERSION),),
                    )
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

    def _verify_or_init_meta(self, conn: sqlite3.Connection) -> tuple[int, int | None]:
        """Write the version and counter on a fresh DB, or refuse any other version.

        Runs inside the setup transaction. A stored ``schema_version`` that is
        neither :data:`_SCHEMA_VERSION` nor a member of :data:`_UPGRADABLE_FROM` is
        refused with ``PlanningError`` *before any record table is created, read, or
        written*: an unreadable label on an incompatible ``goals`` table would
        otherwise construct successfully and only fail on the first query with a raw
        "no such column" — a fault to report at open, not defer, matching how the
        audit trail treats a row that no longer validates. ADR-0049 §1's loud refusal
        of a database "whose ``schema_version`` is **newer** than the code
        understands" binds entire and is what that covers now.

        **A database labelled** :data:`_UPGRADABLE_FROM` **is upgraded rather than
        refused** (ADR-0249 §12), and this method records which version it arrived at
        so :meth:`_upgrade_goal_rows` — which runs after the record tables exist —
        knows whether to run. An unlabelled database is one this code is creating
        now, and it is stamped rather than migrated.

        Every marker is read through :meth:`_read_meta`, so a store holding
        conflicting rows for any key is refused rather than resolved by row order
        (issue #349).

        The counter is also checked against its high-water mark (ADR-0064): a
        stored ``exec_counter`` *below* ``exec_high_water`` is a counter something
        outside this store has rewound, and re-minting from it would hand out
        execution ids this store has already issued (issue #356). That refusal
        joins the schema one *ahead of the record tables*, on ADR-0049 §1's
        reasoning: a store that cannot promise non-reuse should not be opened at
        all, rather than open and fail at the first allocation.

        Returns:
            The validated counter, and the stored mark — or ``None`` where the
            database carries none. :meth:`_reconcile_high_water` takes it from
            there, once the record tables exist.

        Raises:
            PlanningError: If the schema version is unsupported, a marker is
                ambiguous or unparseable, or the counter has been rewound below
                its mark.
        """
        version = self._read_meta(conn, "schema_version")
        held: int | None = None
        if not version:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(_SCHEMA_VERSION),),
            )
        else:
            held = self._meta_int("schema_version", version[0])
            if held != _SCHEMA_VERSION and held not in _UPGRADABLE_FROM:
                known = ", ".join(str(one) for one in sorted({*_UPGRADABLE_FROM, _SCHEMA_VERSION}))
                msg = (
                    f"the plan store at {self._path!r} has schema_version={held}, but this "
                    f"code reads version {known}; refusing to open it rather than read it "
                    f"blindly"
                )
                raise PlanningError(msg)
        self._upgrade_from = held if held in _UPGRADABLE_FROM else None
        if rows := self._read_meta(conn, "exec_counter"):
            counter = self._meta_int("exec_counter", rows[0])  # validate on open
        else:
            counter = 0
            conn.execute("INSERT INTO meta(key, value) VALUES ('exec_counter', '0')")
        if mark := self._read_meta(conn, _HIGH_WATER):
            stored_mark = self._meta_int(_HIGH_WATER, mark[0])
            self._refuse_a_rewound_counter(counter, stored_mark)
            return counter, stored_mark
        return counter, None

    def _upgrade_goal_rows(self, conn: sqlite3.Connection) -> None:
        """Convert a version 1 store's ``goals`` rows in place (ADR-0249 §12).

        **This store's first migration**, and ADR-0049 §1's marker is what makes it
        possible: "A durable ``meta("schema_version")`` row is written at creation so
        a **future** schema change has the version marker." A version 1 store is
        *older* than this code rather than newer, so §1's loud refusal does not reach
        it and it is upgraded in place.

        Each ``goals`` row gains an ``interpretation`` of **exactly one revision**
        whose ``outcome`` is the row's stored ``statement``, whose ``outcome_ground``
        is derived from the row's stored ``provenance.source`` by
        :func:`_migrated_ground`, whose ``constraints``, ``criteria`` and
        ``conditions`` are empty, whose ``recorded_at`` is its ``created_at``, and
        whose ``raised_by`` is **absent**. ``conversation_id`` and ``last_engaged_at``
        are **absent**; ``version`` and ``interpretation_elided`` are 0.

        **The migration writes no value this system did not record, and the absences
        are the whole of how it says so** (§12). It does not invent a turn id for
        ``raised_by``, a conversation for ``conversation_id``, an instant for
        ``last_engaged_at``, or a span of a request it does not hold for
        ``outcome_span`` — a synthesised ``raised_by`` would attribute an
        understanding to a turn that never raised it.

        **Nothing else is rewritten.** Each ``plans`` row is left byte for byte as it
        is and decodes with ``targets_revision`` absent, which ADR-0249 §8 reads as
        targeting no revision, so such a plan is **not driven**; each ``executions``
        row is untouched; and ``attempts`` is created empty by :data:`_RECORD_SCHEMA`,
        because a version 1 store holds no attempt.

        Runs inside the setup transaction, so a failure anywhere leaves the file
        exactly as it arrived — unupgraded, still labelled 1, and refusing to open
        rather than half-migrated.

        Args:
            conn: The connection the setup transaction is running on.

        Raises:
            PlanningError: If a stored goal is not a shape this migration can read.
        """
        if self._upgrade_from != _VERSION_BEFORE_INTERPRETATIONS:
            return
        rows = conn.execute("SELECT id, data FROM goals").fetchall()
        for row_id, data in rows:
            conn.execute(
                "UPDATE goals SET data = ? WHERE id = ?",
                (_migrated_goal(str(row_id), str(data)), row_id),
            )

    def _add_missing_goal_columns(self, conn: sqlite3.Connection) -> None:
        """Add ADR-0250 §9's two ``goals`` columns to an older file, in place.

        **The second half of this store's second migration**, and the half a
        ``CREATE TABLE IF NOT EXISTS`` cannot do: that statement is a no-op against
        the ``goals`` table a version 1 or 2 store already holds, so without this the
        file would reach :meth:`_verify_record_tables` missing two columns and be
        refused — the store refusing to open the very file the upgrade exists for.

        Read back with ``PRAGMA table_info`` rather than assumed from the version
        marker, so a file that already carries one of the two (a partial hand
        migration, a third-party tool) gains only what it lacks rather than failing
        on a duplicate column. Runs inside the setup transaction, before the shape
        checks and before either row pass.

        Args:
            conn: The connection the setup transaction is running on.
        """
        if self._upgrade_from is None:
            return
        held = {str(row[1]) for row in conn.execute("PRAGMA table_info(goals)").fetchall()}
        for column in _GOAL_COLUMNS:
            if column not in held:
                # `column` is a fixed literal of `_GOAL_COLUMNS`, never caller input.
                conn.execute(f"ALTER TABLE goals ADD COLUMN {column} TEXT")

    def _backfill_goal_columns(self, conn: sqlite3.Connection) -> None:
        """Write the two ``goals`` columns from the rows themselves (ADR-0250 §9).

        The columns are **projections of the blob** — ``Goal.conversation_id`` and
        ``Goal.last_engaged_in`` — so a migrated row's values are read out of the
        record rather than invented, which is ADR-0249 §12's "the migration writes no
        value this system did not record" binding on this half too. A version 1 store's
        rows are read **after** :meth:`_upgrade_goal_rows` has rewritten them, so both
        passes see one shape; a version 2 store's blobs are not rewritten at all, and
        every one of them yields ``last_engaged_in`` absent, which is §1's one route to
        a ``None``.

        Args:
            conn: The connection the setup transaction is running on.

        Raises:
            PlanningError: If a stored goal no longer decodes.
        """
        if self._upgrade_from is None:
            return
        rows = conn.execute("SELECT id, data FROM goals").fetchall()
        for row_id, data in rows:
            goal = _decode_goal(str(data))
            conn.execute(
                "UPDATE goals SET conversation_id = ?, last_engaged_in = ? WHERE id = ?",
                (goal.conversation_id, goal.last_engaged_in, row_id),
            )

    def _verify_the_ordinal_index(self, conn: sqlite3.Connection) -> None:
        """Check that the ordinal index *is* the one this store means to rely on.

        ``CREATE UNIQUE INDEX IF NOT EXISTS`` keys on the **name**, so a
        pre-existing index called :data:`_ORDINAL_INDEX` and shaped differently —
        non-unique, over another column, or partial — makes the creation a silent
        no-op and leaves the ADR-0064 §4 backstop absent while every message in
        this module claims it is there. That is the same fail-open issue #349 found
        in a ``meta`` table this code did not shape: an object's name is not
        evidence about the object.

        So the index is read back from ``PRAGMA index_list``/``index_info`` and
        required to be unique, total, and over exactly ``created_seq``. Nothing
        here inspects the *rows*: if an index with those properties exists — this
        open's or an earlier one's — duplicate ordinals cannot be present, and if
        it had to be created just now, creating it over a table that already held
        duplicates would have raised. Verifying the index is therefore the whole
        check, not half of one.

        Raises:
            PlanningError: If no index of that name exists, or it is not a unique,
                non-partial index over ``created_seq`` alone.
        """
        # Names are lower-cased before comparison: SQLite identifiers are
        # case-insensitive, so an `EXECUTIONS_CREATED_SEQ` over `CREATED_SEQ` is the
        # same index over the same column, and a case-variant but compatible schema
        # must not be refused for casing (matches `_verify_record_tables`).
        listed = [
            row
            for row in conn.execute("PRAGMA index_list('executions')")
            if str(row[1]).lower() == _ORDINAL_INDEX
        ]
        columns = [
            str(row[2]).lower()
            for row in conn.execute("PRAGMA index_info('executions_created_seq')")
        ]
        # index_list rows are (seq, name, unique, origin, partial).
        if len(listed) == 1 and listed[0][2] and not listed[0][4] and columns == ["created_seq"]:
            return
        found = (
            "no such index"
            if not listed
            else f"unique={listed[0][2]}, partial={listed[0][4]}, over {columns}"
        )
        msg = (
            f"the plan store at {self._path!r} has an {_ORDINAL_INDEX} that is not a unique "
            f"index over executions(created_seq) ({found}); the ordinal uniqueness ADR-0049 §1's "
            f"oldest-first ordering rests on is not enforced, and this store will not open "
            f"claiming a backstop the database does not have"
        )
        raise PlanningError(msg)

    def _verify_record_tables(self, conn: sqlite3.Connection) -> None:
        """Check each record table *is* the shape this store's guarantees rest on.

        ``CREATE TABLE IF NOT EXISTS`` is a no-op against a pre-existing
        ``goals``/``plans``/``executions`` of a different shape, and nothing
        validated the columns afterwards, so every guarantee built on those columns
        could be silently absent on a hand-built, third-party-migrated or corrupt
        file (issue #373). This is the same fail-open #349 closed for ``meta`` and
        #364 for the ordinal index, extended from the index to the record columns
        themselves: an object's name is not evidence about the object.

        So each table is read back with ``PRAGMA table_info`` and required to carry
        its :data:`_RECORD_COLUMNS` at the expected **affinity** — affinity, not the
        exact declared type, because that is what SQLite's ordering, comparison and
        storage actually key on (a ``TEXT`` ``created_seq`` orders lexically; a
        non-integer ``version`` breaks the compare-and-swap) — and ``NOT NULL``
        where the schema declares it. Its ``PRIMARY KEY`` is verified too, because
        ``save_goal``'s ``ON CONFLICT(id)`` upsert and per-id uniqueness rest on it,
        and so is each ``REFERENCES`` clause ADR-0049 §1's referential integrity
        rests on, down to the parent column. Extra columns are tolerated: the store
        names every column it reads and writes, so a superset cannot mislead it,
        while a *missing*, wrong-affinity, wrongly-nullable, unkeyed or mis-targeted
        one can.

        Runs at open, before any record is read or written, on ADR-0049 §1's
        posture: refuse a store whose guarantees cannot hold rather than open it and
        fail — or silently misbehave — at the first query.

        **Scope of this cluster (deliberate, not exhaustive).** ``_verify_columns``,
        ``_verify_primary_key``, ``_verify_foreign_key``, ``_verify_no_triggers`` and
        ``_verify_the_ordinal_index`` defend against a shape mismatch that **silently
        subverts a store guarantee** — a check passes yet the store misbehaves
        invisibly: a lexical ``created_seq``, a case-folded id, a mutating trigger, a
        broken foreign key. They do **not** attempt exhaustive validation against a
        *hostile* hand-built schema. A construction that makes an operation fail
        **loudly** — a ``CHECK`` constraint, a generated column, an extra ``UNIQUE``
        index, ``WITHOUT ROWID``, an extra or composite foreign key, a ``DEFAULT``
        expression — surfaces a clear ``PlanningError`` at the write rather than
        silent corruption, and is out of scope: the plan database lives on the user's
        local disk (ADR-0004 §2), so anyone who can rewrite its schema already owns
        the data and the schema is not a security boundary against them. See the
        parked follow-up issue for the enumerated fail-loud cases; do not reopen this
        loop to chase them.

        Raises:
            PlanningError: If a record table lacks an expected column, carries one at
                the wrong affinity or nullability, is not keyed on ``id``, is missing
                (or mis-targets) a declared foreign key, or any table the store writes
                carries a trigger.
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
            self._verify_foreign_key(conn, table)

    def _verify_no_triggers(self, conn: sqlite3.Connection) -> None:
        """Refuse a trigger on any table this store writes — ``meta`` included.

        The column/PK/FK checks describe a table's *shape*, but a pre-existing table
        of the exact shape can still carry an ``AFTER INSERT``/``UPDATE`` trigger that
        silently subverts a write. On a record table it rewrites ``NEW.id`` or
        corrupts ``data``, so ``save_goal`` returns a caller's id while the row was
        moved underneath it (ADR-0049 §1/§2). On ``meta`` it is worse: a trigger that
        resets ``exec_counter``/``exec_high_water`` on update defeats the
        ordinal-monotonicity ADR-0064 rests on, so a later ``start_execution``
        re-issues an execution id already handed out — and a reused id lets a stale
        parked confirmation resolve a freshly-created execution (ADR-0049 §3). Both
        are *silent*: every other check passes. This store creates no triggers, so
        any trigger on a table it writes is foreign and there is no shape reading that
        makes a mutating one safe — refuse it at open.

        Raises:
            PlanningError: If any trigger is defined on ``goals``, ``plans``,
                ``executions`` or ``meta``.
        """
        # Every table the store writes, `meta` included (the ordinal lives there).
        written_tables = {*_RECORD_COLUMNS, "meta"}
        triggers = sorted(
            str(name)
            for name, table in conn.execute(
                "SELECT name, tbl_name FROM sqlite_master WHERE type = 'trigger'"
            )
            # tbl_name is lower-cased: SQLite identifiers are case-insensitive, so a
            # trigger on `GOALS` binds the same table as one on `goals`.
            if str(table).lower() in written_tables
        )
        if not triggers:
            return
        msg = (
            f"the plan store at {self._path!r} has triggers on the tables it writes "
            f"({', '.join(triggers)}); this store creates none, and a trigger can silently "
            f"rewrite or corrupt a row — or reset the durable ordinal (ADR-0064) — under a write "
            f"it reported as stored, so it will not open a database that can subvert its writes"
        )
        raise PlanningError(msg)

    def _verify_columns(
        self,
        table: str,
        expected: dict[str, tuple[str, bool]],
        actual: dict[str, tuple[str, bool]],
    ) -> None:
        """Require each expected column at its affinity and, where declared, NOT NULL."""
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
        """Require ``table``'s primary key to be exactly ``id``, BINARY-collated.

        ``save_goal``'s ``ON CONFLICT(id) DO UPDATE`` upsert and the per-id
        uniqueness every record read assumes need ``id`` to be the primary key; a
        pre-existing table without it, or keyed on something else, opens a store
        whose guarantee is silently absent (#373). The **collation** is load-bearing
        too: a ``COLLATE NOCASE`` key folds ``"A"`` and ``"a"`` into one row, so an
        upsert of a case-variant id overwrites a different record's blob and
        ``get_goal`` hands back an id the caller never stored — ``Identifier`` is
        case-sensitive, and ADR-0049 §1's schema is the default ``BINARY``.

        Read from the primary key's own index (``PRAGMA index_list`` origin ``pk``,
        then ``index_xinfo`` for its key columns and their collations), so both the
        column set and the collation are checked against the object rather than the
        column names alone — the same posture :meth:`_verify_the_ordinal_index`
        takes for the ordinal index.

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
        if key_columns == [(_RECORD_PRIMARY_KEY, "BINARY")]:
            return
        if not key_columns:
            detail = "no PRIMARY KEY"
        elif [column for column, _coll in key_columns] != [_RECORD_PRIMARY_KEY]:
            detail = f"a PRIMARY KEY over {', '.join(column for column, _coll in key_columns)}"
        else:
            detail = f"a {key_columns[0][1]}-collated {_RECORD_PRIMARY_KEY} PRIMARY KEY"
        msg = (
            f"the plan store at {self._path!r} has a {table} table with {detail}, not the "
            f"exact BINARY {_RECORD_PRIMARY_KEY} PRIMARY KEY (ADR-0049 §1) its upsert and "
            f"per-id uniqueness rest on; refusing to open a table it did not shape"
        )
        raise PlanningError(msg)

    def _verify_foreign_key(self, conn: sqlite3.Connection, table: str) -> None:
        """Require ``table``'s foreign keys to be *exactly* the declared one (or none).

        A pre-existing table declared without its ``REFERENCES`` clause carries no
        foreign key, so the ADR-0049 §1 backstop beneath ``save_plan``'s app-level
        orphan check is gone — an orphaned plan or execution can be committed. The
        keys are read back from ``PRAGMA foreign_key_list`` and required to be
        precisely the expected **single-column** key binding the expected child
        column to the expected parent *column* — no more, no fewer:

        - a key to another column of the right table (``goals(data)`` for
          ``goals(id)``) does not enforce the binding this store relies on;
        - a *composite* key (``FOREIGN KEY(goal_id, data) REFERENCES goals(id,
          data)``) whose first pair reads ``goal_id → goals(id)`` is not it either —
          its parent key is not ``goals(id)``, so SQLite raises ``foreign key
          mismatch`` at the first write;
        - an *extra* key the store never declares (``FOREIGN KEY(data) REFERENCES
          goals(id)`` beside the real one) makes ``goals``-id-shaped ``data`` a write
          precondition SQLite enforces, so every otherwise-valid plan write fails.

        Each of these opens a table this store cannot correctly write, so — on
        ADR-0049 §1's refuse-before-writing posture — the foreign keys present must
        equal the declared set exactly, not merely contain it. A key that omits the
        parent column (``REFERENCES goals``) resolves to the parent's primary key,
        which this same pass requires to be ``id``, so it is accepted.

        Raises:
            PlanningError: If the expected foreign key is absent or mis-targeted, or
                any other foreign key (composite or extra) is present.
        """
        expected = _RECORD_FOREIGN_KEYS.get(table)
        # foreign_key_list rows are (id, seq, table, from, to, ...); one constraint
        # spans multiple rows (one per column pair), sharing an id, so group by it.
        constraints: dict[int, list[Any]] = {}
        for row in conn.execute(f"PRAGMA foreign_key_list('{table}')"):
            constraints.setdefault(int(row[0]), []).append(row)

        expected_seen = False
        unexpected = False
        for rows in constraints.values():
            row = rows[0]
            # Names are lower-cased: SQLite identifiers are case-insensitive, so a
            # `REFERENCES GOALS(ID)` key binds the same columns as `goals(id)`. `to`
            # is NULL when the clause omits the parent column, meaning its PK.
            is_the_expected_key = (
                expected is not None
                and len(rows) == 1  # single-column; a composite one is not the binding
                and str(row[3]).lower() == expected[0]
                and str(row[2]).lower() == expected[1]
                and (row[4] is None or str(row[4]).lower() == expected[2])
            )
            if is_the_expected_key and not expected_seen:
                expected_seen = True
            else:
                unexpected = True

        # A missing/mistargeted key (also the composite-only case: the expected
        # single-column key is not present) is reported first and specifically.
        if expected is not None and not expected_seen:
            column, parent, target = expected
            msg = (
                f"the plan store at {self._path!r} has a {table} table with no single-column "
                f"foreign key from {column} to {parent}({target}); the referential integrity "
                f"ADR-0049 §1 requires is not enforced, and this store will not open claiming a "
                f"backstop the database does not have"
            )
            raise PlanningError(msg)
        # The expected key is present, but so is another the store never declares.
        if unexpected:
            msg = (
                f"the plan store at {self._path!r} has a {table} table with an unexpected foreign "
                f"key this store does not declare; an extra or composite key SQLite enforces on a "
                f"write is a constraint this code did not shape, so it will not open a database "
                f"that can reject its own valid writes (ADR-0049 §1)"
            )
            raise PlanningError(msg)

    def _reconcile_high_water(
        self, conn: sqlite3.Connection, counter: int, mark: int | None
    ) -> None:
        """Corroborate the counter against the records, then bring the mark level.

        Runs inside the setup transaction, once the record tables exist — which is
        what puts ``executions`` in scope. Two things happen here, and each closes
        a hole the ``counter >= mark`` test in :meth:`_verify_or_init_meta` cannot
        see on its own.

        **The records corroborate the counter.** Every execution stores in
        ``created_seq`` the ordinal it was allocated with, written by the same
        transaction that advanced the counter, and ``clear``/``delete_goal`` only
        ever *remove* rows — so ``MAX(created_seq) <= exec_counter`` holds for every
        file this store wrote, and a violation is corruption whatever the mark says.
        The mark alone cannot catch two cases: a *deleted* mark is indistinguishable
        from one that was never written, so the backfill below would otherwise
        launder a two-row tamper into a fresh, agreeing pair; and a mark left
        *lagging* (§3) agrees with a counter rewound down to meet it. Both were
        reproduced before this check existed, and both end the same way — a second
        execution allocated a ``created_seq`` an existing one already holds, so
        ``active_executions``/``export`` silently stop being the oldest-first order
        the contract promises. The records are not a substitute for the mark and
        never *raise* the counter: they are exactly what ``clear``/``delete_goal``
        erase, which is why ADR-0049 §3 keeps the ordinal in ``meta`` at all. They
        can only refuse — and where no execution survives there is nothing to
        corroborate *and* nothing to corrupt (ADR-0064 §5).

        This runs at the open, never per allocation. The unique index in
        :data:`_INDEXES` is what holds the same line on the allocation path, where
        scanning ``executions`` would be a cost on every ``start_execution``.

        **The mark is then brought level with the counter**, written where it is
        absent and *promoted* where it lags. Promoting is not a repair: the counter
        is the highest ordinal issued, so that is what the high water is. Doing it
        eagerly at open rather than lazily at the next allocation is what makes the
        allocation-time test in :meth:`_next_ordinal` sound for the rest of the
        session — with the two level, any mid-session rewind falls below the mark
        and is refused, without the allocation having to re-scan the records.

        Raises:
            PlanningError: If an execution survives that was allocated an ordinal
                above the counter, or ``created_seq`` does not read as an integer.
        """
        row = conn.execute("SELECT MAX(created_seq) FROM executions").fetchone()
        highest = 0 if row is None or row[0] is None else self._meta_int("created_seq", row[0])
        if counter < highest:
            msg = (
                f"the plan store at {self._path!r} has exec_counter={counter} but still "
                f"holds an execution allocated at created_seq={highest}: the counter has "
                f"been rewound past ordinals the store has already issued, and its "
                f"exec_high_water no longer witnesses that (ADR-0049 §3). Refusing rather "
                f"than allocating an ordinal a stored execution already carries"
            )
            raise PlanningError(msg)
        if mark is None:
            conn.execute(_WRITE_HIGH_WATER, (str(counter),))
        elif mark < counter:
            conn.execute(_UPDATE_HIGH_WATER, (str(counter),))

    def _refuse_a_rewound_counter(self, counter: int, mark: int) -> None:
        """Refuse a counter that has fallen below the highest ordinal already issued.

        The invariant ADR-0049 §3 assumes and ADR-0064 enforces: ``exec_counter``
        only ever moves forward, so the ordinal half of an execution id is never
        re-issued within one incarnation. The mark advances with the counter in the
        same transaction, so ``counter < mark`` cannot arise from anything this
        store did — it means the counter was moved by something else.

        The test is deliberately one-sided. A mark *below* the counter is not a
        rewind — no ordinal has been re-issued — so it is levelled up rather than
        refused (:meth:`_reconcile_high_water`). Only the counter falling behind
        means ids already handed out are about to be minted a second time.

        Raises:
            PlanningError: If ``counter`` is below ``mark``.
        """
        if counter >= mark:
            return
        msg = (
            f"the plan store at {self._path!r} has exec_counter={counter}, below the "
            f"exec_high_water={mark} it has already issued: the counter has been rewound "
            f"outside this store and would re-mint execution ids it has already handed "
            f"out (ADR-0049 §3). Refusing rather than reissuing an id"
        )
        raise PlanningError(msg)

    def _read_meta(self, conn: sqlite3.Connection, key: str) -> list[Any]:
        """Return every value stored under ``key``, refusing an ambiguous store.

        ``meta``'s ``key TEXT PRIMARY KEY`` makes a second row for one key
        unreachable in a table *this* code created — but ``CREATE TABLE IF NOT
        EXISTS`` is a no-op against a pre-existing ``meta`` declared without that
        constraint, so a corrupt, hand-built or externally-migrated file can hold
        both ``('schema_version', '1')`` and ``('schema_version', '999')``.
        Collapsing the table into a ``dict`` kept whichever row SQLite returned
        last, which left the refusal in :meth:`_verify_or_init_meta` decided by
        **row order**: the same two rows in the other order opened the store on an
        unsupported schema (issue #349). That is a fail-open in a check whose only
        job is to refuse a database this code cannot read.

        ``exec_counter`` is read the same way, and ADR-0049 §3 is why it must be:
        the ordinal is the durable half of execution-id non-reuse, so a losing row
        does not merely mislabel the file — it **rewinds the counter**, re-minting
        ordinals the store has already handed out and breaking the ADR-0044 §1
        guarantee a parked confirmation's recovery rests on. Taking the largest of
        the conflicting rows would preserve non-reuse, but it is a *repair* of a
        table this code did not write, and ADR-0049 §1's posture for this store is
        to refuse rather than read on regardless.

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

        A non-numeric ``schema_version``, ``exec_counter`` or ``exec_high_water``
        is a corrupt or tampered store, not a Python exception to leak past this
        layer's initialisation boundary (ADR-0049 §1). ``created_seq`` is read the
        same way by :meth:`_reconcile_high_water`: it is declared ``INTEGER NOT
        NULL``, but only in a table *this* code created.
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

    def _transaction(
        self, what: str, *, immediate: bool = True
    ) -> AbstractContextManager[sqlite3.Connection]:
        """Run the block inside one transaction, translating backend failures.

        ``IMMEDIATE`` takes the write lock up front rather than at the first
        write, which is what puts the *reads* every mutation here decides on
        under it: the identity comparison in :meth:`save_goal`, the goal's
        existence in :meth:`save_plan`, the durable ordinal in
        :meth:`start_execution`, the stored version a transition is applied to,
        and the liveness scan a deletion is refused by. A deferred begin would
        leave each of those outside the lock and let a second process act on the
        state it read (ADR-0049 §1, §3). ``immediate=False`` is the read form, a
        deferred transaction for several ``SELECT``s that must see one snapshot.

        ``what`` reads as the tail of ``failed to {what}``, which is the message
        :func:`_wrap` composes for the reads that run outside a transaction; the
        two spellings are deliberately the same sentence.

        Anything other than a backend failure propagates unchanged, after the
        transaction is rolled back — which is how :meth:`save_plan` refuses an
        orphan and :meth:`clear` refuses a live execution without leaving
        anything behind.

        Raises:
            PlanningError: If the backend fails at any point.
        """
        return transaction(self._conn, what, error=PlanningError, immediate=immediate)

    # --- goals and plans --------------------------------------------------

    async def save_goal(self, goal: Goal) -> str:
        """Persist a **new** goal (ADR-0249 §12), refusing an id already held.

        **The opening write alone, and no longer an upsert.** An upsert that replaced
        a whole goal would defeat ADR-0249 §1's append-only interpretation and §12's
        compare-and-swap in one call: every later change goes through
        :meth:`record_interpretation`.

        The input is **revalidated before it is persisted**, not merely copied
        (like ``SqliteAuditTrail`` does with a decision): ``Goal`` is mutable and
        does not validate on assignment, so a caller can build a valid goal, reach
        past its validators, and hand it here. Storing that unchecked would
        write a record every later ``get_goal``/``export`` fails to decode — the
        store would poison its own reads. Revalidating turns it into a
        ``PlanningError`` at the write, before anything is persisted.

        That revalidation is also this method's ADR-0065 snapshot: it runs on the
        coroutine's first executed line, before the first ``await``, and the id
        returned is read from **it** rather than from the caller's instance. A
        caller that mutates ``goal.id`` while the write is in flight would
        otherwise be handed an id that names no row.

        Raises:
            PlanningError: If the store already holds a goal under this ``id``, or
                the goal does not revalidate.
        """
        snapshot = _revalidated_goal(goal)
        async with self._lock:
            await _run_to_completion(self._save_goal_sync, snapshot)
        return snapshot.id

    def _save_goal_sync(self, goal: Goal) -> None:
        with self._transaction(f"save goal {goal.id!r}") as conn:
            if conn.execute("SELECT 1 FROM goals WHERE id = ?", (goal.id,)).fetchone() is not None:
                msg = (
                    f"goal {goal.id} already exists: save_goal is the opening write "
                    "alone, and a later change to a goal is a record_interpretation "
                    "(ADR-0249 §12)"
                )
                raise PlanningError(msg)
            # ADR-0249 §2's bound is stated over **the write**, so the opening write
            # takes it too: a goal handed in with more revisions than the ceiling
            # admits is stored trimmed, with the count saying how many went.
            stored = bounded(goal)
            conn.execute(
                "INSERT INTO goals(id, conversation_id, last_engaged_in, data) VALUES (?, ?, ?, ?)",
                (
                    stored.id,
                    stored.conversation_id,
                    stored.last_engaged_in,
                    stored.model_dump_json(),
                ),
            )

    async def get_goal(self, goal_id: str) -> Goal | None:
        """Return the goal with ``goal_id``, or ``None``."""
        async with self._lock:
            row = await _run_to_completion(self._read_one, "goals", goal_id)
        return None if row is None else _decode_goal(row)

    async def record_interpretation(self, revision: GoalRevision) -> Goal:
        """Append one interpretation revision, compare-and-swap (ADR-0249 §12).

        The read, the comparison and the write all run inside one ``BEGIN
        IMMEDIATE`` transaction, so a second writer that read the same version
        cannot also commit — it reads the advanced version and is refused. That is
        ADR-0014 §5's discipline, on the construction ADR-0049 §1 already uses for
        ``commit_transition``.

        Raises:
            StaleExecutionError: If the stored version has moved on.
            PlanningError: If ``goal_id`` names no stored goal, or the revision does
                not follow the goal's current one.
        """
        async with self._lock:
            return await _run_to_completion(self._record_interpretation_sync, revision)

    def _record_interpretation_sync(self, revision: GoalRevision) -> Goal:
        what = f"record an interpretation on goal {revision.goal_id!r}"
        with self._transaction(what) as conn:
            row = conn.execute(
                "SELECT data FROM goals WHERE id = ?", (revision.goal_id,)
            ).fetchone()
            if row is None:
                msg = f"cannot record an interpretation for unknown goal {revision.goal_id}"
                raise PlanningError(msg)
            stored = _decode_goal(row[0])
            if stored.version != revision.expected_version:
                msg = (
                    f"goal {revision.goal_id} is at version {stored.version}, not "
                    f"{revision.expected_version}: re-read it and recompute the revision"
                )
                raise StaleExecutionError(msg)
            updated = appended(stored, revision.interpretation)
            # The two columns are unmoved by a revision — `record_interpretation`
            # leaves both engagement fields exactly as it found them (ADR-0250 §1) and
            # `conversation_id` is never rewritten — so only the blob is written here.
            conn.execute(
                "UPDATE goals SET data = ? WHERE id = ?",
                (updated.model_dump_json(), updated.id),
            )
        return updated

    # --- engagement, status and the candidate set (ADR-0250 §§1, 2, 9) -----

    def _goal_for_write(
        self, conn: sqlite3.Connection, goal_id: str, expected: int, what: str
    ) -> Goal:
        """Read a goal for a compare-and-swap write inside an open transaction.

        The read, the comparison and the caller's write all run inside one ``BEGIN
        IMMEDIATE``, so a second writer that read the same version cannot also commit
        — it reads the advanced version and is refused. ADR-0014 §5's discipline,
        stated once for both of ADR-0250's goal writes.

        Args:
            conn: The connection the write transaction is running on.
            goal_id: The goal to read.
            expected: The ``Goal.version`` the caller computed against.
            what: What the caller is about to do, for the refusal message.

        Returns:
            The stored goal.

        Raises:
            StaleExecutionError: If the stored version has moved on.
            PlanningError: If ``goal_id`` names no stored goal.
        """
        row = conn.execute("SELECT data FROM goals WHERE id = ?", (goal_id,)).fetchone()
        if row is None:
            msg = f"cannot {what} unknown goal {goal_id}"
            raise PlanningError(msg)
        stored = _decode_goal(row[0])
        if stored.version != expected:
            msg = (
                f"goal {goal_id} is at version {stored.version}, not {expected}: re-read "
                f"it and recompute the write"
            )
            raise StaleExecutionError(msg)
        return stored

    async def engage_goal(
        self, goal_id: str, /, *, at: UtcInstant, conversation_id: str, expected_version: int
    ) -> Goal:
        """Stamp the goal's engagement, compare-and-swap (ADR-0250 §1, §9).

        The **one** writer of ``last_engaged_at`` and ``last_engaged_in``, which is
        why the ``last_engaged_in`` column is written here and nowhere else.

        Raises:
            StaleExecutionError: If the stored version has moved on.
            PlanningError: If ``goal_id`` names no stored goal.
        """
        async with self._lock:
            return await _run_to_completion(
                self._engage_goal_sync, goal_id, at, conversation_id, expected_version
            )

    def _engage_goal_sync(
        self, goal_id: str, at: UtcInstant, conversation_id: str, expected_version: int
    ) -> Goal:
        with self._transaction(f"engage goal {goal_id!r}") as conn:
            stored = self._goal_for_write(conn, goal_id, expected_version, "engage")
            updated = engaged(stored, at=at, conversation_id=conversation_id)
            conn.execute(
                "UPDATE goals SET last_engaged_in = ?, data = ? WHERE id = ?",
                (updated.last_engaged_in, updated.model_dump_json(), updated.id),
            )
        return updated

    async def set_goal_status(
        self,
        goal_id: str,
        /,
        *,
        status: GoalStatus,
        at: UtcInstant,  # noqa: ARG002 — the contract's instant; no field of `Goal` records it, and this store mints no second record to hold it (ADR-0250 §9)
        expected_version: int,
    ) -> Goal:
        """Move the goal's status, compare-and-swap (ADR-0250 §9).

        The goal's **only** status-mutation route, and it refuses no member of the
        vocabulary: A10 and A3 write ``ACHIEVED`` and ``BLOCKED`` through it, and a
        store that refused one would be a second place the vocabulary is decided.

        Raises:
            StaleExecutionError: If the stored version has moved on.
            PlanningError: If ``goal_id`` names no stored goal.
        """
        async with self._lock:
            return await _run_to_completion(
                self._set_goal_status_sync, goal_id, status, expected_version
            )

    def _set_goal_status_sync(self, goal_id: str, status: GoalStatus, expected: int) -> Goal:
        with self._transaction(f"set the status of goal {goal_id!r}") as conn:
            stored = self._goal_for_write(conn, goal_id, expected, "set the status of")
            updated = _with_status(stored, status=status)
            conn.execute(
                "UPDATE goals SET data = ? WHERE id = ?",
                (updated.model_dump_json(), updated.id),
            )
        return updated

    async def candidates_for(self, conversation_id: str, /, *, limit: int) -> GoalCandidates:
        """Return this conversation's candidate goals, capped (ADR-0250 §2, §9).

        The membership test is the query — the goal was **opened in** this
        conversation or was **last engaged in** it — and the order is
        :func:`~ai_assistant.planning.goals.capped`'s over the decoded rows, so §1's
        key is stated once for both conforming stores rather than once here in SQL and
        once in Python.

        Raises:
            PlanningError: If ``limit`` is not positive, or a stored goal no longer
                decodes.
        """
        async with self._lock:
            rows = await _run_to_completion(self._candidates_for_sync, conversation_id)
        return capped((_decode_goal(data) for data in rows), limit=limit)

    def _candidates_for_sync(self, conversation_id: str) -> list[str]:
        try:
            return [
                str(row[0])
                for row in self._conn.execute(
                    "SELECT data FROM goals WHERE conversation_id = ? OR last_engaged_in = ?",
                    (conversation_id, conversation_id),
                ).fetchall()
            ]
        except sqlite3.Error as exc:
            raise _wrap("read the candidate set of", conversation_id, exc) from exc

    # --- a goal's clarification (ADR-0250 §§8-12) --------------------------

    async def record_question(self, question: GoalQuestion, /) -> bool:
        """Write an ``OPEN`` question, or refuse a second on one goal (§9).

        Revalidated before it is persisted, for :meth:`save_goal`'s own reason, and
        that revalidation is this method's ADR-0065 snapshot. The read of the existing
        question and the write run inside one ``BEGIN IMMEDIATE``, so two turns of one
        conversation — or two engines over one data directory — cannot both be
        admitted against the same goal.

        Raises:
            PlanningError: If ``goal_id`` or ``attempt_id`` names no stored record,
                this store already holds a question under this ``id``, or the question
                does not revalidate.
        """
        snapshot = _revalidated_question(question)
        if snapshot.disposition is not GoalQuestionDisposition.OPEN:
            # Refused before the lock and before any read: a terminal record written
            # here would answer `True` while `open_question` answered `None` for the
            # same goal. Only `settle_question` reaches a terminal disposition
            # (ADR-0250 §9, §12).
            msg = (
                f"question {snapshot.id} arrives {snapshot.disposition.value} and "
                f"record_question writes an OPEN question: a terminal disposition is "
                f"written by settle_question and by nothing else (ADR-0250 §9)"
            )
            raise PlanningError(msg)
        async with self._lock:
            return await _run_to_completion(self._record_question_sync, snapshot)

    def _record_question_sync(self, question: GoalQuestion) -> bool:
        with self._transaction(f"record question {question.id!r}") as conn:
            if (
                conn.execute("SELECT 1 FROM goals WHERE id = ?", (question.goal_id,)).fetchone()
                is None
            ):
                msg = f"question {question.id} refers to unknown goal {question.goal_id}"
                raise PlanningError(msg)
            attempt = conn.execute(
                "SELECT goal_id FROM attempts WHERE id = ?", (question.attempt_id,)
            ).fetchone()
            if attempt is None:
                msg = f"question {question.id} refers to unknown attempt {question.attempt_id}"
                raise PlanningError(msg)
            if str(attempt[0]) != question.goal_id:
                # ADR-0014 §5's closure kept at write time, as `commit_attempt` keeps it
                # for an attempt's own references: `delete_goal` cascades one goal's
                # attempts and questions together, so a question naming *another* goal's
                # attempt outlives that attempt and makes the next export unvalidatable.
                msg = (
                    f"question {question.id} names attempt {question.attempt_id}, which "
                    f"belongs to goal {attempt[0]} and not to {question.goal_id}: a "
                    f"question's attempt is one its own goal holds (ADR-0250 §9)"
                )
                raise PlanningError(msg)
            if (
                conn.execute("SELECT 1 FROM goal_questions WHERE id = ?", (question.id,)).fetchone()
                is not None
            ):
                msg = f"question {question.id} already exists"
                raise PlanningError(msg)
            held = conn.execute(
                "SELECT 1 FROM goal_questions WHERE goal_id = ? AND disposition = ?",
                (question.goal_id, GoalQuestionDisposition.OPEN.value),
            ).fetchone()
            if held is not None:
                return False
            conn.execute(
                "INSERT INTO goal_questions"
                "(id, goal_id, attempt_id, asked_at, disposition, data) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    question.id,
                    question.goal_id,
                    question.attempt_id,
                    question.asked_at.isoformat(),
                    question.disposition.value,
                    question.model_dump_json(),
                ),
            )
        return True

    async def get_question(self, question_id: str, /) -> GoalQuestion | None:
        """Return the question under that id, whatever its disposition (§9)."""
        async with self._lock:
            row = await _run_to_completion(self._read_one, "goal_questions", question_id)
        return None if row is None else _decode_question(row)

    async def open_question(self, goal_id: str, /) -> GoalQuestion | None:
        """Return that goal's open question, or ``None`` (ADR-0250 §9)."""
        async with self._lock:
            row = await _run_to_completion(self._open_question_sync, goal_id)
        return None if row is None else _decode_question(row)

    def _open_question_sync(self, goal_id: str) -> str | None:
        try:
            row = self._conn.execute(
                "SELECT data FROM goal_questions WHERE goal_id = ? AND disposition = ?",
                (goal_id, GoalQuestionDisposition.OPEN.value),
            ).fetchone()
        except sqlite3.Error as exc:
            raise _wrap("read the open question of goal", goal_id, exc) from exc
        return None if row is None else str(row[0])

    async def outstanding_questions(self) -> tuple[GoalQuestion, ...]:
        """Return every ``OPEN`` question, in ``asked_at`` order (ADR-0250 §9).

        It takes no view of the clock: an expired question is still ``OPEN`` until
        something settles it, and settling it is the caller's (§12).
        """
        async with self._lock:
            rows = await _run_to_completion(self._outstanding_questions_sync)
        return tuple(_decode_question(data) for data in rows)

    def _outstanding_questions_sync(self) -> list[str]:
        try:
            return [
                str(row[0])
                for row in self._conn.execute(
                    "SELECT data FROM goal_questions WHERE disposition = ? "
                    "ORDER BY asked_at ASC, id ASC",
                    (GoalQuestionDisposition.OPEN.value,),
                ).fetchall()
            ]
        except sqlite3.Error as exc:
            raise _wrap("read outstanding questions", "", exc) from exc

    async def settle_question(
        self, question_id: str, /, *, disposition: GoalQuestionDisposition, at: UtcInstant
    ) -> bool:
        """Settle an ``OPEN`` question, clearing its content (ADR-0250 §9).

        The resolve-once gate: the read, the comparison and the write run inside one
        ``BEGIN IMMEDIATE``, so one of two racing callers answers ``True`` and the
        other ``False``, and the content is cleared exactly once.

        Raises:
            PlanningError: If ``disposition`` is ``OPEN``, which settles nothing.
        """
        if disposition is GoalQuestionDisposition.OPEN:
            # Refused before the lock and before any read, because it is a malformed
            # command rather than a lost race (ADR-0250 §9, §12).
            msg = (
                "settle_question moves an OPEN question to a terminal member: OPEN "
                "settles nothing and no disposition is inferred from silence "
                "(ADR-0250 §9, §12)"
            )
            raise PlanningError(msg)
        async with self._lock:
            return await _run_to_completion(
                self._settle_question_sync, question_id, disposition, at
            )

    def _settle_question_sync(
        self, question_id: str, disposition: GoalQuestionDisposition, at: UtcInstant
    ) -> bool:
        with self._transaction(f"settle question {question_id!r}") as conn:
            row = conn.execute(
                "SELECT data FROM goal_questions WHERE id = ? AND disposition = ?",
                (question_id, GoalQuestionDisposition.OPEN.value),
            ).fetchone()
            if row is None:
                return False
            updated = settled(_decode_question(str(row[0])), disposition=disposition, at=at)
            conn.execute(
                "UPDATE goal_questions SET disposition = ?, data = ? WHERE id = ?",
                (updated.disposition.value, updated.model_dump_json(), updated.id),
            )
        return True

    # --- attempts ---------------------------------------------------------

    async def open_attempt(self, attempt: GoalAttempt) -> str:
        """Persist a new attempt for a stored goal (ADR-0249 §12).

        Revalidated before it is persisted, for :meth:`save_goal`'s own reason, and
        that revalidation is this method's ADR-0065 snapshot.

        Raises:
            PlanningError: If ``goal_id`` names no stored goal, the store already
                holds an attempt under this ``id``, or the attempt does not
                revalidate.
        """
        snapshot = _revalidated_attempt(attempt)
        async with self._lock:
            await _run_to_completion(self._open_attempt_sync, snapshot)
        return snapshot.id

    def _open_attempt_sync(self, attempt: GoalAttempt) -> None:
        with self._transaction(f"open attempt {attempt.id!r}") as conn:
            held = conn.execute("SELECT 1 FROM goals WHERE id = ?", (attempt.goal_id,)).fetchone()
            if held is None:
                msg = f"attempt {attempt.id} refers to unknown goal {attempt.goal_id}"
                raise PlanningError(msg)
            if (
                conn.execute("SELECT 1 FROM attempts WHERE id = ?", (attempt.id,)).fetchone()
                is not None
            ):
                msg = (
                    f"attempt {attempt.id} already exists; a change to an attempt is a "
                    "commit_attempt, which is its only mutation route (ADR-0249 §12)"
                )
                raise PlanningError(msg)
            for plan_id in attempt.plan_ids:
                self._refuse_a_dangling_plan(conn, attempt, plan_id)
            for execution_id in attempt.execution_ids:
                self._refuse_a_dangling_execution(conn, attempt, execution_id)
            conn.execute(
                "INSERT INTO attempts(id, goal_id, opened_at, data) VALUES (?, ?, ?, ?)",
                (
                    attempt.id,
                    attempt.goal_id,
                    attempt.opened_at.isoformat(),
                    attempt.model_dump_json(),
                ),
            )

    async def get_attempt(self, attempt_id: str) -> GoalAttempt | None:
        """Return the attempt with ``attempt_id``, or ``None``."""
        async with self._lock:
            row = await _run_to_completion(self._read_one, "attempts", attempt_id)
        return None if row is None else _decode_attempt(row)

    async def attempts_of(self, goal_id: str) -> tuple[GoalAttempt, ...]:
        """Return every attempt of ``goal_id``, in ``opened_at`` order.

        Ordered by the stored ``opened_at`` column with ``id`` as the tie-break, so
        two attempts opened at one instant are enumerated in a fixed order rather
        than in whatever order the file holds.
        """
        async with self._lock:
            rows = await _run_to_completion(self._attempts_of_sync, goal_id)
        return tuple(_decode_attempt(data) for data in rows)

    def _attempts_of_sync(self, goal_id: str) -> list[str]:
        try:
            return [
                str(row[0])
                for row in self._conn.execute(
                    "SELECT data FROM attempts WHERE goal_id = ? ORDER BY opened_at ASC, id ASC",
                    (goal_id,),
                ).fetchall()
            ]
        except sqlite3.Error as exc:
            raise _wrap("read attempts of goal", goal_id, exc) from exc

    async def commit_attempt(self, transition: AttemptTransition) -> GoalAttempt:
        """Apply one attempt transition, compare-and-swap (ADR-0249 §12).

        The attempt's **only** mutation route, and — as for
        :meth:`record_interpretation` — the read, the comparison and the write run
        inside one ``BEGIN IMMEDIATE`` transaction.

        Raises:
            StaleExecutionError: If the stored version has moved on.
            IllegalTransitionError: If the move is not legal from where it stands.
            PlanningError: If the attempt does not exist, or the result is not a shape
                ADR-0249 §5 admits.
        """
        async with self._lock:
            return await _run_to_completion(self._commit_attempt_sync, transition)

    def _commit_attempt_sync(self, transition: AttemptTransition) -> GoalAttempt:
        what = f"commit a transition on attempt {transition.attempt_id!r}"
        with self._transaction(what) as conn:
            row = conn.execute(
                "SELECT data FROM attempts WHERE id = ?", (transition.attempt_id,)
            ).fetchone()
            if row is None:
                msg = f"unknown attempt {transition.attempt_id}"
                raise PlanningError(msg)
            stored = _decode_attempt(row[0])
            if stored.version != transition.expected_version:
                msg = (
                    f"attempt {transition.attempt_id} is at version {stored.version}, not "
                    f"{transition.expected_version}: re-read it and recompute the transition"
                )
                raise StaleExecutionError(msg)
            if transition.add_plan_id is not None:
                self._refuse_a_dangling_plan(conn, stored, transition.add_plan_id)
            if transition.add_execution_id is not None:
                self._refuse_a_dangling_execution(conn, stored, transition.add_execution_id)
            updated = advanced(stored, transition)
            conn.execute(
                "UPDATE attempts SET data = ? WHERE id = ?",
                (updated.model_dump_json(), updated.id),
            )
        return updated

    @staticmethod
    def _refuse_a_dangling_plan(
        conn: sqlite3.Connection, attempt: GoalAttempt, plan_id: str
    ) -> None:
        """Refuse a plan reference that does not resolve under this attempt's goal.

        **ADR-0014 §5's export promise kept at write time rather than repaired at read
        time**, which is the division ADR-0228 §5 already records for ``supersedes``:
        an attempt's ``plan_ids`` are ``plan_id`` values referenced by an included
        record (ADR-0249 §11), so a store that accepted one it does not hold would
        produce a ``PlanExport`` that does not validate.

        **Under this attempt's own goal**, read off the ``plans`` table's own
        ``goal_id`` column inside the write transaction, so the check and the write
        see one fact. Confining the reference to one goal is also what keeps the
        closure true across a deletion: ``delete_goal`` cascades a goal's plans,
        executions and attempts together.

        Args:
            conn: The connection the write transaction is running on.
            attempt: The attempt the reference is being written onto.
            plan_id: The plan the write names.

        Raises:
            PlanningError: If the plan is not one this attempt's goal holds.
        """
        held = conn.execute(
            "SELECT 1 FROM plans WHERE id = ? AND goal_id = ?", (plan_id, attempt.goal_id)
        ).fetchone()
        if held is None:
            msg = (
                f"attempt {attempt.id} names plan {plan_id}, which this store does not "
                f"hold under goal {attempt.goal_id}; an export naming a plan it does "
                "not carry does not validate (ADR-0014 §5, ADR-0249 §11)"
            )
            raise PlanningError(msg)

    @staticmethod
    def _refuse_a_dangling_execution(
        conn: sqlite3.Connection, attempt: GoalAttempt, execution_id: str
    ) -> None:
        """Refuse an execution reference that does not resolve under this goal (§11).

        :meth:`_refuse_a_dangling_plan`'s reasoning over the second reference an
        attempt accumulates, reached through the plan the execution runs.

        Args:
            conn: The connection the write transaction is running on.
            attempt: The attempt the reference is being written onto.
            execution_id: The execution the write names.

        Raises:
            PlanningError: If the execution is not one this attempt's goal holds.
        """
        held = conn.execute(
            "SELECT 1 FROM executions e JOIN plans p ON e.plan_id = p.id "
            "WHERE e.id = ? AND p.goal_id = ?",
            (execution_id, attempt.goal_id),
        ).fetchone()
        if held is None:
            msg = (
                f"attempt {attempt.id} names execution {execution_id}, which this store "
                f"does not hold under goal {attempt.goal_id}; an export naming an "
                "execution it does not carry does not validate (ADR-0014 §5)"
            )
            raise PlanningError(msg)

    async def save_plan(self, plan: ActionPlan) -> str:
        """Persist a plan, requiring its goal to exist and its id to be free.

        Rejecting an orphan is what lets ``export`` promise referential integrity
        without repairing anything at read time; the enforced foreign key is the
        durable backstop beneath the app-level check (ADR-0049 §1). Rejecting a
        *reused* id keeps a plan an audit record: re-planning takes a new id
        (ADR-0014 §2). An identical re-save is idempotent, so a retry is harmless.

        **An unstamped ``targets_revision`` is refused too** (ADR-0249 §8), inside
        the same write transaction and for the reason the check below is there: the
        window is closed at the store rather than trusted to close itself. A plan
        **already on disk** carrying ``None`` decodes — ADR-0249 §12's migration
        leaves every version 1 plan row exactly so — and §8's not-driven rule is what
        reads it.

        **A ``supersedes`` that does not resolve is refused** (ADR-0228 §5): one
        naming a plan this store does not hold, one naming the saving plan's own
        ``id``, and one naming a plan under a different ``goal_id``. It is checked
        inside the same write transaction as the orphan check, against the ``plans``
        table's own ``goal_id`` column, so a concurrent writer cannot land a
        predecessor between the check and the insert.

        **And no durable foreign key stands beneath it**, unlike the ``goal_id``
        one — ADR-0228 §5 states the reason and ADR-0049 §1 supplies it. That
        constraint exists to close a *cross-process* window ("one connection deletes
        goal ``g`` between another's check and its insert"), and this reference has
        none: both plans of a turn are written by that turn, oldest first, and this
        store offers no way to delete a single plan — :meth:`delete_goal` removes a
        goal's plans together and both of a turn's plans share its ``goal_id``, and
        :meth:`clear` removes everything. A future member that deletes plans
        individually, or a chain that spanned goals, fires that constraint; ADR-0228
        §1 forbids the second and nothing contracts the first.

        Revalidated before it is persisted, for the same reason as ``save_goal``:
        a mutable ``ActionPlan`` mutated past its validators must fail at the write
        rather than poison every later decode.
        """
        snapshot = _revalidated_plan(plan)
        async with self._lock:
            await _run_to_completion(self._save_plan_sync, snapshot)
        return plan.id

    def _save_plan_sync(self, plan: ActionPlan) -> None:
        with self._transaction(f"save plan {plan.id!r}") as conn:
            if conn.execute("SELECT 1 FROM goals WHERE id = ?", (plan.goal_id,)).fetchone() is None:
                msg = f"plan {plan.id} refers to unknown goal {plan.goal_id}"
                raise PlanningError(msg)
            # ADR-0249 §8: the unstamped state exists only between the planner's
            # return and the loop's stamp, and the window is closed at the store.
            if plan.targets_revision is None:
                msg = (
                    f"plan {plan.id} carries no targets_revision: the unstamped state "
                    "exists only between the planner's return and the loop's stamp, "
                    "and the window is closed at the store (ADR-0249 §8)"
                )
                raise PlanningError(msg)
            # ADR-0228 §5's three arms, read off the `plans` table's own `goal_id`
            # column rather than by decoding the predecessor: the column is what the
            # insert below writes, so the check and the write see one fact.
            if plan.supersedes is not None:
                if plan.supersedes == plan.id:
                    msg = f"plan {plan.id} supersedes itself; a plan cannot replace the plan it is"
                    raise PlanningError(msg)
                predecessor = conn.execute(
                    "SELECT goal_id FROM plans WHERE id = ?", (plan.supersedes,)
                ).fetchone()
                if predecessor is None:
                    msg = f"plan {plan.id} supersedes unknown plan {plan.supersedes}"
                    raise PlanningError(msg)
                if predecessor[0] != plan.goal_id:
                    msg = (
                        f"plan {plan.id} supersedes plan {plan.supersedes}, which is under "
                        f"goal {predecessor[0]} rather than {plan.goal_id}; a revision "
                        "replaces a plan for the same goal"
                    )
                    raise PlanningError(msg)
            row = conn.execute("SELECT data FROM plans WHERE id = ?", (plan.id,)).fetchone()
            if row is not None:
                if _decode_plan(row[0]) != plan:
                    msg = (
                        f"plan {plan.id} already exists and differs; re-planning must use a "
                        "new id so the previous plan stays an intact audit record"
                    )
                    raise PlanningError(msg)
                return  # idempotent re-save
            conn.execute(
                "INSERT INTO plans(id, goal_id, data) VALUES (?, ?, ?)",
                (plan.id, plan.goal_id, plan.model_dump_json()),
            )

    async def get_plan(self, plan_id: str) -> ActionPlan | None:
        """Return the plan with ``plan_id``, or ``None``."""
        async with self._lock:
            row = await _run_to_completion(self._read_one, "plans", plan_id)
        return None if row is None else _decode_plan(row)

    # --- executions -------------------------------------------------------

    async def start_execution(self, plan_id: str) -> ExecutionState:
        """Open and store a fresh execution for ``plan_id``.

        The id is ``{plan_id}-exec-{pid}-{nonce}-{ordinal}`` (ADR-0049 §3): the
        ``pid`` is read here, at allocation, so a fork that copied the store's
        nonce still yields distinct ids; the ``nonce`` distinguishes independent
        constructions (the ``:memory:`` case, where the ordinal rewinds); and the
        ``ordinal`` is a durable, never-reset counter allocated under the write
        lock, giving intra-incarnation monotonicity and same-file concurrency
        safety. Together they meet ADR-0044 §1's non-reuse guarantee.
        """
        async with self._lock:
            return await _run_to_completion(self._start_execution_sync, plan_id)

    def _start_execution_sync(self, plan_id: str) -> ExecutionState:
        with self._transaction(f"start execution for plan {plan_id!r}") as conn:
            row = conn.execute("SELECT data FROM plans WHERE id = ?", (plan_id,)).fetchone()
            if row is None:
                msg = f"cannot start an execution for unknown plan {plan_id}"
                raise PlanningError(msg)
            plan = _decode_plan(row[0])
            ordinal = self._next_ordinal(conn)
            execution_id = f"{plan_id}-exec-{os.getpid()}-{self._nonce}-{ordinal}"
            state = self._tracker.start(plan, execution_id=execution_id)
            conn.execute(
                "INSERT INTO executions(id, plan_id, version, active, created_seq, data) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    state.id,
                    state.plan_id,
                    state.version,
                    int(state.is_active),
                    ordinal,
                    state.model_dump_json(),
                ),
            )
        return state.model_copy(deep=True)

    def _next_ordinal(self, conn: sqlite3.Connection) -> int:
        """Read-increment the durable execution counter, inside the open write txn.

        The write lock is already held (``BEGIN IMMEDIATE``), so this read then
        write is atomic against another process on the same file: neither the
        counter rewinds nor two executions share an ordinal (ADR-0049 §3).

        Read through :meth:`_read_meta` like the open-time check, so the counter
        is refused here on the same terms it is refused there. This is the second
        read of the same value, and the one whose answer becomes an execution id:
        taking the first of two conflicting rows here would rewind the ordinal
        even for a file whose *open* had validated the other row.

        **The high-water check is re-run here, and this is the site that closes
        issue #356.** The open-time check cannot: the rewind that actually reissues
        an id happens *mid-session*, after the open has validated, and its damage
        is intra-incarnation — the pid and nonce folded into the id are constant
        for the life of this object, so a counter rewound between two
        ``start_execution`` calls yields a byte-identical id. (Across a reopen the
        nonce already covers it, which is why the open-time refusal is about
        reporting a corrupt file loudly rather than about non-reuse.) Same shape as
        the ambiguous-counter check above: the open establishes nothing an outside
        writer cannot undo a moment later, so the allocation re-reads.

        Raises:
            PlanningError: If the counter or its mark is missing, ambiguous or
                unparseable, or the counter has been rewound below the mark.
        """
        current = self._read_meta(conn, "exec_counter")
        mark = self._read_meta(conn, _HIGH_WATER)
        if not current or not mark:
            # `_verify_or_init_meta` seeds both rows at open, so reaching this needs
            # an outside writer to have deleted one since. An allocator with no
            # counter cannot promise non-reuse (ADR-0049 §3), and one with no mark
            # cannot tell whether the counter it does have has been rewound, so
            # both refuse rather than restarting from zero or minting unwitnessed —
            # and refuse in this layer's own error, where unpacking an empty
            # `fetchone()` would have raised `TypeError`.
            missing = "exec_counter" if not current else _HIGH_WATER
            msg = f"the plan store at {self._path!r} has lost its {missing}; the store is corrupt"
            raise PlanningError(msg)
        counter = self._meta_int("exec_counter", current[0])
        self._refuse_a_rewound_counter(counter, self._meta_int(_HIGH_WATER, mark[0]))
        nxt = counter + 1
        conn.execute("UPDATE meta SET value = ? WHERE key = 'exec_counter'", (str(nxt),))
        # The check above leaves `counter >= mark`, so `nxt` is strictly above the
        # mark and this is the new high water. Written in the same transaction as
        # the counter — that lockstep is what makes a later disagreement mean
        # tampering, and what lets a whole-file restore roll both back together and
        # open cleanly (ADR-0064).
        conn.execute(_UPDATE_HIGH_WATER, (str(nxt),))
        return nxt

    async def commit_transition(self, transition: StepTransition) -> ExecutionState:
        """Apply one transition against the stored snapshot and persist it.

        The only write path for execution state. Reading the stored state,
        applying the tracker, and writing back all run inside one
        ``BEGIN IMMEDIATE`` transaction, so a second writer that read the same
        version cannot also commit — it reads the advanced version and the tracker
        rejects it (ADR-0049 §1).

        **And a ``→ RUNNING`` claim carries ADR-0249 §8's further condition** — the
        plan the execution runs targets its goal's current revision. The plan and the
        goal are read **inside that same transaction**, so there is no separate read
        on which a decision is taken and nothing can advance the goal between the
        comparison and the claim.

        Raises:
            StaleExecutionError: If the stored version has moved on, or a
                ``→ RUNNING`` claim names a plan that does not target its goal's
                current revision.
            IllegalTransitionError: If the move is not legal from the step's current
                status.
            PlanningError: If the execution or step does not exist.
        """
        async with self._lock:
            return await _run_to_completion(self._commit_transition_sync, transition)

    def _commit_transition_sync(self, transition: StepTransition) -> ExecutionState:
        what = f"commit a transition on execution {transition.execution_id!r}"
        with self._transaction(what) as conn:
            row = conn.execute(
                "SELECT data FROM executions WHERE id = ?", (transition.execution_id,)
            ).fetchone()
            if row is None:
                msg = f"unknown execution {transition.execution_id}"
                raise PlanningError(msg)
            stored = _decode_execution(row[0])
            self._refuse_a_stale_target(conn, stored, transition)
            updated = self._tracker.apply(stored, transition)
            conn.execute(
                "UPDATE executions SET version = ?, active = ?, data = ? WHERE id = ?",
                (
                    updated.version,
                    int(updated.is_active),
                    updated.model_dump_json(),
                    updated.id,
                ),
            )
        return updated.model_copy(deep=True)

    def _refuse_a_stale_target(
        self, conn: sqlite3.Connection, stored: ExecutionState, transition: StepTransition
    ) -> None:
        """Refuse a ``→ RUNNING`` claim on a plan targeting a stale revision (§8).

        **The store's guard and not the driver's**, in ADR-0014 §5's own words:
        "Optimistic concurrency turns that into a detectable, retryable failure, and
        it belongs to the store because the store is the only place with a total
        order over writes." Read on the transaction's own connection, so the plan,
        the goal and the claim are one indivisible step.

        A plan whose ``targets_revision`` is absent — the one route being a row
        ADR-0249 §12 migrated — names no revision and is therefore not driven either.

        Args:
            conn: The connection the commit transaction is running on.
            stored: The execution the transition claims a step of.
            transition: The move being applied.

        Raises:
            StaleExecutionError: If the claim names a plan that does not target its
                goal's current interpretation revision.
        """
        if transition.to_status is not StepStatus.RUNNING:
            return
        row = conn.execute(
            "SELECT p.data, g.data FROM executions e "
            "JOIN plans p ON e.plan_id = p.id JOIN goals g ON p.goal_id = g.id "
            "WHERE e.id = ?",
            (stored.id,),
        ).fetchone()
        if row is None:  # pragma: no cover — the foreign keys make an orphan unreachable
            return
        plan, goal = _decode_plan(row[0]), _decode_goal(row[1])
        if plan.targets_revision != goal.revision:
            msg = (
                f"plan {plan.id} targets revision {plan.targets_revision} and goal "
                f"{goal.id} stands at {goal.revision}: a plan that does not target the "
                f"goal's current understanding is not driven (ADR-0249 §8)"
            )
            raise StaleExecutionError(msg)

    async def get_execution(self, execution_id: str) -> ExecutionState | None:
        """Return the execution with ``execution_id``, or ``None``."""
        async with self._lock:
            row = await _run_to_completion(self._read_one, "executions", execution_id)
        return None if row is None else _decode_execution(row)

    async def active_executions(self) -> list[ExecutionState]:
        """Return every execution with outstanding work, oldest first.

        Ordered by the durable creation ordinal, not by id (ids embed a plan
        prefix, so sorting them would interleave plans), and filtered on the
        stored ``active`` flag so only outstanding executions are decoded.
        """
        async with self._lock:
            rows = await _run_to_completion(self._active_executions_sync)
        return [_decode_execution(data) for data in rows]

    def _active_executions_sync(self) -> list[str]:
        try:
            return [
                str(row[0])
                for row in self._conn.execute(
                    "SELECT data FROM executions WHERE active = 1 ORDER BY created_seq ASC"
                ).fetchall()
            ]
        except sqlite3.Error as exc:
            raise _wrap("read active executions", "", exc) from exc

    def _read_one(self, table: str, row_id: str) -> str | None:
        """Read one record's JSON blob by id. ``table`` is a fixed literal, never input."""
        try:
            row = self._conn.execute(
                f"SELECT data FROM {table} WHERE id = ?",  # noqa: S608 — table is a fixed literal
                (row_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise _wrap(f"read from {table}", row_id, exc) from exc
        return None if row is None else str(row[0])

    # --- data rights (ADR-0004) -------------------------------------------

    async def export(self) -> PlanExport:
        """Return a portable, internally consistent snapshot (ADR-0004 §6)."""
        exported_at = self._now()
        async with self._lock:
            snapshot = await _run_to_completion(self._export_sync)
        goals, plans, executions, attempts, questions = snapshot
        return PlanExport(
            exported_at=exported_at,
            goals=tuple(_decode_goal(data) for data in goals),
            plans=tuple(_decode_plan(data) for data in plans),
            executions=tuple(_decode_execution(data) for data in executions),
            attempts=tuple(_decode_attempt(data) for data in attempts),
            questions=tuple(_decode_question(data) for data in questions),
        )

    def _export_sync(self) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
        # All three reads inside one transaction, so the export is a single
        # database snapshot: a concurrent connection cannot commit a goal+plan
        # between the goals read and the plans read and leave the export with a
        # plan whose goal is missing — the dangling, PlanExport-rejected state
        # ADR-0004 §6's "internally consistent" forbids. The write form, not the
        # deferred one a read would otherwise take: the write lock excludes a
        # writer outright rather than leaving the reads to a snapshot another
        # connection is free to write around.
        with self._transaction("export planning state") as conn:
            goals = [str(r[0]) for r in conn.execute("SELECT data FROM goals").fetchall()]
            plans = [str(r[0]) for r in conn.execute("SELECT data FROM plans").fetchall()]
            executions = [
                str(r[0])
                for r in conn.execute(
                    "SELECT data FROM executions ORDER BY created_seq ASC"
                ).fetchall()
            ]
            attempts = [
                str(r[0])
                for r in conn.execute(
                    "SELECT data FROM attempts ORDER BY opened_at ASC, id ASC"
                ).fetchall()
            ]
            questions = [
                str(r[0])
                for r in conn.execute(
                    "SELECT data FROM goal_questions ORDER BY asked_at ASC, id ASC"
                ).fetchall()
            ]
        return goals, plans, executions, attempts, questions

    async def delete_goal(self, goal_id: str) -> GoalDeletion:
        """Delete a goal, its plan history, its attempts and its questions.

        Refused while any of the goal's executions has a ``RUNNING`` step. The
        cascade deletes children before parents — executions, then plans, then
        attempts, then questions, then the goal — so the enforced foreign keys are satisfied at each
        step, and
        the live-execution refusal runs first, before anything is removed
        (ADR-0049 §1).
        """
        async with self._lock:
            return await _run_to_completion(self._delete_goal_sync, goal_id)

    def _delete_goal_sync(self, goal_id: str) -> GoalDeletion:
        with self._transaction(f"delete goal {goal_id!r}") as conn:
            if conn.execute("SELECT 1 FROM goals WHERE id = ?", (goal_id,)).fetchone() is None:
                return GoalDeletion(deleted=False, blocked_by=("<no such goal>",))

            plan_ids = [
                str(r[0])
                for r in conn.execute(
                    "SELECT id FROM plans WHERE goal_id = ?", (goal_id,)
                ).fetchall()
            ]
            executions = [
                _decode_execution(r[0])
                for r in conn.execute(
                    "SELECT e.data FROM executions e JOIN plans p ON e.plan_id = p.id "
                    "WHERE p.goal_id = ?",
                    (goal_id,),
                ).fetchall()
            ]

            live = sorted(state.id for state in executions if state.has_live_step)
            if live:
                return GoalDeletion(deleted=False, blocked_by=tuple(live))

            indeterminate = tuple(
                sorted(
                    step.step_id
                    for state in executions
                    for step in state.steps
                    if step.status is StepStatus.INDETERMINATE
                )
            )
            # Children first, so the foreign keys hold at each delete.
            conn.execute(
                "DELETE FROM executions WHERE plan_id IN (SELECT id FROM plans WHERE goal_id = ?)",
                (goal_id,),
            )
            conn.execute("DELETE FROM plans WHERE goal_id = ?", (goal_id,))
            # ADR-0249 §12: the cascade reaches attempts, which **extends** ADR-0014
            # §5's "a goal the user deletes must not leave its plan history behind"
            # rather than re-promising it. The live-step refusal above is unchanged
            # and keys on a RUNNING step, so an attempt in a non-terminal state does
            # not block a deletion no execution blocks. Deleted before the goal so
            # the enforced foreign key holds at each step.
            conn.execute("DELETE FROM attempts WHERE goal_id = ?", (goal_id,))
            # ADR-0250 §9: and it reaches that goal's questions, **open and terminal
            # alike**. An open question does not block a deletion, on ADR-0073 §5's
            # "the store deletes what it is told to delete", and `GoalDeletion` reports
            # them exactly as ADR-0249 §12 has it report attempts — which is to say the
            # record carries no count for either. Before the goal, so the foreign key
            # holds at each step.
            conn.execute("DELETE FROM goal_questions WHERE goal_id = ?", (goal_id,))
            conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
        return GoalDeletion(
            deleted=True,
            plans_removed=len(plan_ids),
            executions_removed=len(executions),
            indeterminate_steps=indeterminate,
        )

    async def clear(self) -> int:
        """Delete everything, refusing while any execution has a live step.

        The durable ``exec_counter`` is deliberately **not** reset, so a fresh
        execution after a ``clear`` cannot collide with one a still-retained audit
        trail already names (ADR-0049 §3).
        """
        async with self._lock:
            return await _run_to_completion(self._clear_sync)

    def _clear_sync(self) -> int:
        with self._transaction("clear the plan store") as conn:
            # A live step is RUNNING, which implies active, so the flag
            # pre-filters the rows to decode; has_live_step is the exact test.
            active = (
                _decode_execution(str(r[0]))
                for r in conn.execute("SELECT data FROM executions WHERE active = 1").fetchall()
            )
            live = sorted(state.id for state in active if state.has_live_step)
            if live:
                msg = f"cannot clear while executions are live: {', '.join(live)}"
                raise ActiveExecutionError(msg)
            removed = 0
            # Children first, to satisfy the foreign keys; meta is untouched.
            removed += conn.execute("DELETE FROM executions").rowcount
            removed += conn.execute("DELETE FROM plans").rowcount
            removed += conn.execute("DELETE FROM attempts").rowcount
            removed += conn.execute("DELETE FROM goal_questions").rowcount
            removed += conn.execute("DELETE FROM goals").rowcount
        return removed

    def close(self) -> None:
        """Close the underlying database connection."""
        with contextlib.suppress(sqlite3.Error):
            self._conn.close()


def _wrap(action: str, subject: str, exc: sqlite3.Error) -> PlanningError:
    """Translate a raw ``sqlite3`` fault into `planning`'s own error at the seam."""
    target = f" {subject!r}" if subject else ""
    return PlanningError(f"failed to {action}{target}: {exc}")


def _revalidated_goal(goal: Goal) -> Goal:
    """Rebuild ``goal`` as a validated, detached :class:`Goal`, or refuse it.

    Both the snapshot (so a caller mutating its instance after the call cannot
    reach stored state) and the guard against persisting an invalid record: a
    mutable ``Goal`` mutated past its validators would otherwise be stored and
    break every later decode. Rebuilt as ``Goal`` specifically, so a subclass's
    extra fields are refused by ``extra="forbid"`` rather than silently dropped.

    Raises:
        PlanningError: If the goal does not satisfy its own model.
    """
    try:
        return Goal.model_validate(goal.model_dump())
    except ValidationError as exc:
        # getattr, not goal.id: a model_construct'd instance may have no id at
        # all, and reading it while composing the message would leak an
        # AttributeError past this helper's PlanningError boundary.
        subject = getattr(goal, "id", "<no id>")
        msg = f"goal {subject!r} is not a valid record and will not be stored: {exc}"
        raise PlanningError(msg) from exc


def _revalidated_plan(plan: ActionPlan) -> ActionPlan:
    """Rebuild ``plan`` as a validated, detached :class:`ActionPlan`, or refuse it.

    Same reasoning as :func:`_revalidated_goal`.

    Raises:
        PlanningError: If the plan does not satisfy its own model.
    """
    try:
        return ActionPlan.model_validate(plan.model_dump())
    except ValidationError as exc:
        subject = getattr(plan, "id", "<no id>")  # id-less model_construct: see _revalidated_goal
        msg = f"plan {subject!r} is not a valid record and will not be stored: {exc}"
        raise PlanningError(msg) from exc


def _revalidated_attempt(attempt: GoalAttempt) -> GoalAttempt:
    """Rebuild ``attempt`` as a validated, detached record, or refuse it.

    Same reasoning as :func:`_revalidated_goal`.

    Raises:
        PlanningError: If the attempt does not satisfy its own model.
    """
    try:
        return GoalAttempt.model_validate(attempt.model_dump())
    except ValidationError as exc:
        subject = getattr(attempt, "id", "<no id>")  # see _revalidated_goal
        msg = f"attempt {subject!r} is not a valid record and will not be stored: {exc}"
        raise PlanningError(msg) from exc


def _revalidated_question(question: GoalQuestion) -> GoalQuestion:
    """Rebuild ``question`` as a validated, detached record, or refuse it.

    Same reasoning as :func:`_revalidated_goal`.

    Raises:
        PlanningError: If the question does not satisfy its own model.
    """
    try:
        return GoalQuestion.model_validate(question.model_dump())
    except ValidationError as exc:
        subject = getattr(question, "id", "<no id>")  # see _revalidated_goal
        msg = f"question {subject!r} is not a valid record and will not be stored: {exc}"
        raise PlanningError(msg) from exc


def _migrated_goal(row_id: str, data: str) -> str:
    """Rewrite one version 1 ``goals`` row as ADR-0249 §12's shape.

    The row holds a pre-decision ``Goal``: an ``id``, a ``statement``, a ``status``, a
    ``provenance``, a ``created_at`` and an optional ``deadline``. The conversion
    keeps every one of them, builds the single interpretation revision §12 describes
    from the ``statement``, the ``provenance.source`` and the ``created_at``, and
    writes **no value this system did not record**.

    Read and rewritten as JSON rather than through :class:`Goal`, because the stored
    shape is one the current model no longer validates — a migration that could only
    read rows the new contract accepts would be able to migrate nothing.

    Args:
        row_id: The row's id, for the error message.
        data: The row's stored JSON.

    Returns:
        The row's JSON at the current shape.

    Raises:
        PlanningError: If the row is not a version 1 goal this migration can read.
    """
    try:
        held = json.loads(data)
        statement = held["statement"]
        created_at = held["created_at"]
        source = MemorySource(held["provenance"]["source"])
        # **Constructed inside the boundary, not beside it.** A row whose `statement`
        # is blank once stripped, or whose `created_at` is not a conforming instant,
        # fails here rather than at the key read — and a `ValidationError` escaping
        # this helper would reach `_setup`, whose cleanup catches `PlanningError`,
        # `sqlite3.Error` and `OSError` and would leak the connection past a raw
        # pydantic error. `ValidationError` is a `ValueError`, so the clause below
        # translates it once the construction is *inside* the block; what was wrong
        # was its position, not the clause. That is what keeps ADR-0049 §1's error
        # boundary total over the migration.
        revision = GoalInterpretation(
            revision=1,
            outcome=statement,
            outcome_ground=ground_of(source),
            # **No span in either branch** (§12): the request the stored statement was
            # read from is not in the row, and §1's fourth absence is exactly this
            # route.
            recorded_at=created_at,
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        msg = (
            f"the plan store holds a goal {row_id!r} this migration cannot read: {exc}. "
            f"The file is left exactly as it arrived (ADR-0249 §12)"
        )
        raise PlanningError(msg) from exc
    del held["statement"]
    held["interpretation"] = [revision.model_dump(mode="json")]
    held["interpretation_elided"] = 0
    held["conversation_id"] = None
    held["last_engaged_at"] = None
    held["version"] = 0
    return json.dumps(held)


def _decode_goal(data: str) -> Goal:
    """Rebuild a stored goal from its JSON, surfacing corruption as ``PlanningError``."""
    try:
        return Goal.model_validate_json(data)
    except ValidationError as exc:
        msg = f"the plan store holds a goal that no longer validates: {exc}"
        raise PlanningError(msg) from exc


def _decode_question(data: str) -> GoalQuestion:
    """Rebuild a stored question from its JSON, surfacing corruption as ``PlanningError``."""
    try:
        return GoalQuestion.model_validate_json(data)
    except ValidationError as exc:
        msg = f"the plan store holds a question that no longer validates: {exc}"
        raise PlanningError(msg) from exc


def _decode_plan(data: str) -> ActionPlan:
    """Rebuild a stored plan from its JSON, surfacing corruption as ``PlanningError``."""
    try:
        return ActionPlan.model_validate_json(data)
    except ValidationError as exc:
        msg = f"the plan store holds a plan that no longer validates: {exc}"
        raise PlanningError(msg) from exc


def _decode_attempt(data: str) -> GoalAttempt:
    """Rebuild a stored attempt from its JSON, surfacing corruption as ``PlanningError``."""
    try:
        return GoalAttempt.model_validate_json(data)
    except ValidationError as exc:
        msg = f"the plan store holds an attempt that no longer validates: {exc}"
        raise PlanningError(msg) from exc


def _decode_execution(data: str) -> ExecutionState:
    """Rebuild a stored execution from its JSON, surfacing corruption as ``PlanningError``."""
    try:
        return ExecutionState.model_validate_json(data)
    except ValidationError as exc:
        msg = f"the plan store holds an execution that no longer validates: {exc}"
        raise PlanningError(msg) from exc


__all__ = ["SqlitePlanStore"]
