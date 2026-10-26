"""A durable :class:`~ai_assistant.core.protocols.PlanStore` on SQLite (ADR-0049).

The persistent counterpart to :class:`~ai_assistant.planning.store.InMemoryPlanStore`.
It follows the house style :mod:`ai_assistant.memory.sqlite_store` and
:mod:`ai_assistant.permissions.audit` set — one owned connection
(``check_same_thread=False``), an :class:`asyncio.Lock` around SQL run in a worker
thread, records stored as their pydantic JSON dump and rebuilt on every read (which is
how the "detached, validated snapshot" obligation is met without a copy step to
forget), and an owner-only database file.

It holds what the phases and the observer write and nothing else: the stop records
ADR-0297 §1 gives the store, the activation effect records ADR-0306 §6 gives it, and the
observation records ADR-0329 §16 gives it. Each lives in its own table, and
:meth:`SqlitePlanStore.export` and :meth:`SqlitePlanStore.clear` carry ADR-0004 §6's
data rights over all three. The goal, plan, execution, attempt, question, evidence and
goal-effect tables retired with the old path (ADR-0309 §5), and so did their
migrations: a file written before ADR-0309 §6:1's deploy is refused. A file the store
has written since is upgraded in place when it opens (ADR-0326 §4, §5:1).
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    ActivationEffect,
    ActivationEffectClaim,
    ObservationRecord,
    PlanExport,
    ScheduledTask,
    ScheduledTaskWrite,
    TaskWriteAnswer,
)
from ai_assistant.planning._transactions import transaction
from ai_assistant.planning.activation_effects import (
    checked_effect_id,
    confirmed,
    decide_activation_claim,
    finished,
    matched_activations,
    requested_activations,
    requested_parts,
    revalidated_claim,
)
from ai_assistant.planning.observations import (
    checked_expected_revision,
    checked_observation,
    checked_since,
    decide_observation_write,
    requested_episodes,
    stamped,
)
from ai_assistant.planning.scheduled_tasks import (
    Schedule,
    by_person,
    checked_id,
    checked_instant,
    checked_limit,
    checked_number,
    checked_optional_id,
    checked_person,
    checked_rule_push,
    checked_spawn,
    checked_spawn_effect,
    checked_state,
    decide_cancel,
    decide_cascade_retirement,
    decide_push,
    decide_removal,
    decide_settle,
    decide_task_write,
    due,
    is_pushed,
    lineage,
    live_below,
    requested_ids,
    requested_states,
    spawned_by,
)
from ai_assistant.planning.stops import revalidated_activation_id

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractContextManager

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import (
        OccurrencePush,
        OccurrenceState,
        QuestionPart,
        RulePush,
        ScheduledDue,
        ScheduledTaskCancel,
        TaskSpawn,
        ToolOutcome,
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
#:
#: **Version 13 is ADR-0329 §16's**: the store gains ``observations``, the observer's
#: record of each episode it processed or attempted, and ``meta`` the issuer of its
#: revisions. **A version 12 file is upgraded in place, not refused** (ADR-0326 §4:1,
#: §5:1): 12 is the label ADR-0309 §6:1's deploy wrote, so a person's hub holds such a
#: file, and the upgrade adds the empty table and moves the label inside the open's one
#: transaction, carrying every stop and effect record as it stands (§4:3, §4:4). The
#: refusal of 0 to 11 stands under ADR-0326 §5:1, as a refusal of files written before
#: that deploy.
#:
#: **Version 14 is ADR-0329 §16:1's carry across a restart** (#3205): an observation
#: record's findings gain ``supply`` and ``written``, the placement meet of what the runs
#: over a finding were supplied (§12:6) and what a commit of it wrote before it failed
#: (§16:4). No column changes, since the record is the blob, but the label moves all
#: the same: a build reading 13 refuses the fields as extra, so it must refuse a file
#: that may hold them at the open (ADR-0326 §5:3) rather than at the first read. **A
#: version 13 file is upgraded in place** (ADR-0326 §4:1), and every finding it holds
#: reads back with both fields empty, which is what they are on a finding recorded
#: before them.
#:
#: **Version 15 is ADR-0346's** (§4:5, §4:6, §6:5, §6:8): a finding gains the scout's
#: ``annotations``, its ``further_candidates`` and, while pending, what framing kept of it
#: (``framed``), a record the candidates the scout
#: ``declines``, and an outcome the
#: ``unclear`` its placement calls named and the wordings the floor ``asked`` about. No
#: column changes, since the record is the blob, and the label moves for 14's reason: a
#: build reading 14 refuses the fields as extra (ADR-0326 §5:3). **A version 14 file is
#: upgraded in place** (§4:1), and every record it holds reads back with the new fields
#: empty, which is what they are on a record written before them.
#:
#: **Version 16 is ADR-0350 §12:3's**: the store gains ``scheduled_tasks``, the Task
#: Scheduler's tasks, each its record as a blob with its person, parent and write order
#: promoted, and ``cascade_records``, a stop command's cascade records, each the
#: activation id alone. **A version 15 file is upgraded in place** (ADR-0326 §4:1, §12:4
#: of ADR-0350): the open's ``CREATE TABLE IF NOT EXISTS`` adds both tables, empty, in its
#: one transaction, every stop, effect and observation record is carried as it stands
#: (§4:4), and the step is the label alone. A build reading 15 refuses a file at 16, whose
#: tables it would leave outside export and clear (ADR-0326 §5:3).
#:
#: **Version 17 is ADR-0340 §9's**: a scheduled task may hold a rule as its when, and a
#: task with a rule holds more than one occurrence. No column changes, since the task is
#: its blob, but a build reading 16 refuses a rule's kind and a task with more than one
#: occurrence, so it must refuse a file that may hold them at the open (ADR-0326 §5:3)
#: rather than at the first read. **A version 16 file is upgraded in place** (ADR-0326
#: §4:1, ADR-0340 §9:4): every task it holds is one-off, which reads back as it was, and
#: the step is the label alone.
#:
#: **Version 18 is ADR-0352 §6:4's**: the store loses ``cascade_records``, since no stop
#: writes a cascade record and no push is refused below one (§2:2-§2:3). **A version 17
#: file is upgraded in place** (ADR-0326 §4:1), and its cascade records keep the reach
#: they had when their stops were made (ADR-0352 §2:6): in the open's one transaction,
#: every pending occurrence of a task whose lineage carries one ends *cancelled*, as the
#: push step refused it before; the activation of every occurrence below one marked
#: pushed, its outcome unwritten, gets a stop record, so ADR-0350 §8:1 ends it *stopped*
#: at start; and then the table is dropped (:meth:`SqlitePlanStore._retire_cascades`).
#: A build reading 17 would recreate the table and find it empty, so it must refuse a
#: file at 18 (ADR-0326 §5:3).
_SCHEMA_VERSION = 18

#: The labels :meth:`SqlitePlanStore._verify_or_init_meta` upgrades from, each to the
#: next, in order (ADR-0326 §4:5). Every label from ADR-0309 §6:1's deploy to the one
#: before :data:`_SCHEMA_VERSION` is here, and none is removed without the owner's
#: ruling (§4:6).
_UPGRADABLE: tuple[int, ...] = (12, 13, 14, 15, 16, 17)

#: The table ADR-0350 §12:3 gave the store for a stop command's cascade records, and the
#: last label that holds it. A file at that label or below may hold it, and the open
#: retires it (ADR-0352 §2:6, §6:4); at any later label it is a table this code does not
#: create, refused as any other (:meth:`SqlitePlanStore._refuse_foreign_tables`).
_RETIRED_CASCADES = "cascade_records"
_LAST_CASCADE_LABEL = 17

#: The ``meta`` key holding the last observation revision issued (ADR-0329 §16:9). It
#: lives beside the records rather than being derived from them, because a revision is
#: never issued twice for the life of the data: ``clear`` erases the records and keeps
#: this row, and a store that rebuilt the issuer from the rows present would reissue the
#: stamp of a record a clear erased.
_OBSERVATION_ISSUER = "observation_revision"

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
    # ADR-0329 §16's observation records, one per episode. The record is the blob;
    # `revision` is promoted because the conditional write compares it, and
    # `last_call_us` — the latest model call the record holds, in microseconds since the
    # epoch, NULL where it made none — because the budget's count selects on it rather
    # than decoding every record. Both are reconciled with the blob on every read.
    "CREATE TABLE IF NOT EXISTS observations("
    "episode_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, last_call_us INTEGER, "
    "data TEXT NOT NULL)",
    # ADR-0350 §12:3's scheduled tasks. The record is the blob; `person` and `parent` are
    # promoted because they name whom the task is for and what spawned it, and
    # `written_seq` because every read answers in the order the tasks were written. Each
    # is reconciled with the blob on every read. No foreign key: a task names
    # activations, which this store does not hold.
    "CREATE TABLE IF NOT EXISTS scheduled_tasks("
    "id TEXT PRIMARY KEY, person TEXT NOT NULL, parent TEXT NOT NULL, "
    "written_seq INTEGER NOT NULL, data TEXT NOT NULL)",
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
#: (ADR-0321 §4:9). The parameters are the keys twice, once for each side. ``{seq}`` is
#: ``"claimed_seq, "`` where the rows of several statements are merged in claim order,
#: and empty where one statement is the whole read.
_PART_ROWS = (
    "SELECT {seq}" + _EFFECT_COLUMNS + " FROM activation_effects "  # noqa: S608 — only constants and placeholders are interpolated
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
    "observations": {
        "episode_id": ("TEXT", False),
        "revision": ("INTEGER", True),
        "last_call_us": ("INTEGER", False),
        "data": ("TEXT", True),
    },
    "scheduled_tasks": {
        "id": ("TEXT", False),
        "person": ("TEXT", True),
        "parent": ("TEXT", True),
        "written_seq": ("INTEGER", True),
        "data": ("TEXT", True),
    },
}

#: The columns every read of a scheduled task selects, in the order
#: :func:`_checked_task` reconciles them with the record.
_TASK_COLUMNS = "id, person, parent, data"

#: The columns every read of an observation record selects, in the order
#: :func:`_checked_observation` reconciles them with the record.
_OBSERVATION_COLUMNS = "episode_id, revision, last_call_us, data"

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

#: How many ids one statement binds where a read names any number of them —
#: :meth:`SqlitePlanStore.observations`' episodes, and the activations
#: :meth:`SqlitePlanStore.activation_effects` and a claim's ``match`` name (issue #3296)
#: — well under the smallest limit SQLite has shipped (999).
_IN_SLICE = 500

#: How many question parts one statement of :meth:`SqlitePlanStore.part_effects` names.
#: :data:`_PART_ROWS` binds four parameters per part, a part's two values once for each
#: side of its match, so a statement binds :data:`_IN_SLICE` parameters as the other
#: sliced reads do (issue #3301).
_PART_SLICE = _IN_SLICE // 4

#: The column each record table's ``PRIMARY KEY`` is, checked against the key's own
#: index. A pre-existing table keyed on something else opens a store whose
#: ``ON CONFLICT`` writes and per-id uniqueness are silently absent, so the key is
#: required, not assumed (#373).
_RECORD_PRIMARY_KEY: dict[str, tuple[str, ...]] = {
    "stopped_activations": ("activation_id",),
    "activation_effects": ("id",),
    "observations": ("episode_id",),
    "scheduled_tasks": ("id",),
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
                held = self._verify_or_init_meta(conn)
                for statement in _RECORD_SCHEMA:
                    conn.execute(statement)
                self._verify_record_tables(conn)
                # ADR-0352 §2:6: the upgrade past 17 applies the cascade records' reach
                # and drops them, on the tables just verified, in this transaction.
                if held is not None and held <= _LAST_CASCADE_LABEL:
                    self._retire_cascades(conn)
        except PlanningError:
            conn.close()  # never leak the connection when opening fails
            raise
        except (sqlite3.Error, OSError) as exc:
            conn.close()
            msg = f"failed to initialise the plan store at {self._path!r}: {exc}"
            raise PlanningError(msg) from exc
        except BaseException:
            # The upgrade past 17 reads the injected clock (ADR-0352 §2:6), whose own
            # failure propagates unwrapped (`checked_clock`); the open is rolled back
            # all the same, and its connection is closed as on every other failure.
            conn.close()
            raise
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

    def _verify_or_init_meta(self, conn: sqlite3.Connection) -> int | None:
        """Write the version on a fresh database, upgrade an older one, or refuse it.

        Runs inside the setup transaction, before any record table is created, read or
        written (ADR-0049 §1). A stored ``schema_version`` equal to
        :data:`_SCHEMA_VERSION` opens as it is. One in :data:`_UPGRADABLE` is brought
        forward by :meth:`_upgrade`, one version at a time (ADR-0326 §4:5), inside the
        same transaction, so a failure anywhere in the open — the shape checks that
        follow included — leaves the file as it found it (§4:3). Any other is refused:
        a **newer** label is a file a later build wrote (ADR-0326 §5:3), and an
        **older** one a store written before ADR-0309 §6:1's deploy — before the
        cutover, or before an effect record carried its question part — which has no
        reader (ADR-0309 §6, ADR-0321 §9:2, ADR-0326 §5:1). An unlabelled database is
        one this code is creating now, and it is stamped.

        The marker is read through :meth:`_read_meta`, so a store holding conflicting
        rows for it is refused rather than resolved by row order (issue #349). The
        file's tables are checked before anything is written or upgraded
        (:meth:`_refuse_foreign_tables`), so a missing or rewritten marker cannot pass an
        older store off as a fresh or a current one.

        Returns:
            The label the file held, where it was upgraded from it; ``None`` where it was
            created now or opened at :data:`_SCHEMA_VERSION`.

        Raises:
            PlanningError: If the file holds a table this code does not create, the
                schema version is neither this code's nor one it upgrades, or the
                marker is ambiguous or unparseable.
        """
        version = self._read_meta(conn, "schema_version")
        held = self._meta_int("schema_version", version[0]) if version else None
        self._refuse_foreign_tables(conn, held)
        if held is None:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(_SCHEMA_VERSION),),
            )
            return None
        if held == _SCHEMA_VERSION:
            return None
        if held in _UPGRADABLE:
            self._upgrade(conn, held)
            return held
        if held > _SCHEMA_VERSION:
            msg = (
                f"the plan store at {self._path!r} has schema_version={held}, newer than "
                f"this code reads (version {_SCHEMA_VERSION}); a later build wrote it, and "
                f"no build opens a file whose label is newer than its own (ADR-0326 §5:3)"
            )
            raise PlanningError(msg)
        msg = (
            f"the plan store at {self._path!r} has schema_version={held}, but this code "
            f"reads version {_SCHEMA_VERSION} and upgrades "
            f"{', '.join(str(one) for one in _UPGRADABLE)}; refusing to open it rather than "
            f"read it blindly (a store written before the cutover, or before the question "
            f"part, has no reader: ADR-0309 §6, ADR-0321 §9:2, ADR-0326 §5:1)"
        )
        raise PlanningError(msg)

    def _upgrade(self, conn: sqlite3.Connection, held: int) -> None:
        """Bring a file at ``held`` forward to :data:`_SCHEMA_VERSION`, in place.

        Each step converts one version to the next (ADR-0326 §4:5) and carries every
        record the file holds (§4:4). It runs on the open's own transaction, before a
        record is read or written, and a raise anywhere in the open rolls back the
        steps already taken (§4:3).

        **12 → 13** (ADR-0329 §16:10): the store gains the ``observations`` table, which
        the open's ``CREATE TABLE IF NOT EXISTS`` creates, empty, in this same
        transaction; no stop or effect record changes, and the observation issuer is
        absent, which reads as nothing issued. So the step is the label alone.

        **13 → 14** (ADR-0329 §16:1, #3205): a finding gains ``supply`` and ``written``,
        each with an empty default, and the record is its blob, so every record the file
        holds reads back as it was with both empty. No row is rewritten, and the step is
        the label alone again.

        **14 → 15** (ADR-0346 §4:5, §4:6, §6:5, §6:8): a finding gains ``annotations``,
        a record ``declines`` and an outcome ``unclear`` and ``asked``, each with an
        empty default, so every record reads back as it was with them empty, and the
        step is the label alone once more.

        **15 → 16** (ADR-0350 §12:3): the store gains ``scheduled_tasks``, which the
        open's ``CREATE TABLE IF NOT EXISTS`` creates, empty, in this same transaction.
        No record changes, so the step is the label alone. (``cascade_records``, which
        16 also added, is never created for a file a step brings past 17.)

        **16 → 17** (ADR-0340 §9:3-§9:4): a task's when may be a rule, and a task with a
        rule holds more than one occurrence. Every task a file at 16 holds is one-off and
        reads back as it was, so no row is rewritten and the step is the label alone.

        **17 → 18** (ADR-0352 §2:6, §6:4): the store loses ``cascade_records``. The step
        moves the label here, and :meth:`_retire_cascades` applies the records' reach and
        drops the table once the record tables are verified, in this same transaction.
        """
        for step in range(held, _SCHEMA_VERSION):
            conn.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(step + 1),))

    def _refuse_foreign_tables(self, conn: sqlite3.Connection, held: int | None) -> None:
        """Refuse a file holding a table this code does not create, at the label it holds.

        The version marker is what tells a store written before the cutover from this
        one, but a marker is one row: deleted, a pre-cutover file reads as a database
        this code is creating and is stamped, and rewritten to a label this code opens,
        it reads as current.
        Either way its ``goals``, ``plans`` or ``executions`` would stay in the file and
        outside :meth:`SqlitePlanStore.export` and :meth:`SqlitePlanStore.clear`,
        which is ADR-0004 §6 failing in silence. So the tables are read first: a file
        this code wrote holds ``meta`` and :data:`_RECORD_COLUMNS`' tables and nothing
        else, and any other table is refused before anything is written. Nothing in it
        is read or migrated (ADR-0309 §6). SQLite's own ``sqlite_`` tables are not the
        file's records and are passed over. A file labelled
        :data:`_LAST_CASCADE_LABEL` or below may also hold :data:`_RETIRED_CASCADES`,
        which its upgrade retires (ADR-0352 §6:4); an unlabelled file or a later one may
        not.

        Args:
            conn: The open's connection.
            held: The label the file holds, or ``None`` where it holds none.

        Raises:
            PlanningError: If the file holds any other table.
        """
        retired = {_RETIRED_CASCADES} if held is not None and held <= _LAST_CASCADE_LABEL else set()
        own = {"meta", *_RECORD_COLUMNS, *retired}
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

    def _retire_cascades(self, conn: sqlite3.Connection) -> None:
        """Apply the reach of a file's cascade records once, then drop them (ADR-0352 §2:6).

        Run in the open's transaction, after the record tables are verified, for a file
        the open upgraded from :data:`_LAST_CASCADE_LABEL` or below. Every pending
        occurrence of a task whose lineage carries a cascade record ends *cancelled*, as
        ADR-0350 §7:5's push step refused it before; the activation of every occurrence
        below one marked pushed, its outcome unwritten, gets a stop record, so ADR-0350
        §8:1 ends it *stopped* at start and never pushes it again; and the table is
        dropped. :func:`~ai_assistant.planning.scheduled_tasks.decide_cascade_retirement`
        decides which. A file that never held the table, one upgraded from 15 or below,
        has nothing to retire.

        Each record is revalidated as the activation id it was written as, so a row an
        outside writer blanked is refused as damage (ADR-0326 §5:1), and the open, with
        every step it took, is rolled back (§4:3).

        Raises:
            PlanningError: If a cascade record or a scheduled task does not validate, or
                the clock's reading is not a conforming one.
        """
        present = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND lower(name) = ?",
            (_RETIRED_CASCADES,),
        ).fetchone()
        if present is None:
            return
        cascades = {
            revalidated_activation_id(row[0])
            for row in conn.execute(
                f"SELECT activation_id FROM {_RETIRED_CASCADES}"  # noqa: S608 — only a constant is interpolated
            ).fetchall()
        }
        schedule = self._schedule(conn, self._now())
        stops = decide_cascade_retirement(schedule, cascades)
        self._persist(conn, schedule)
        for activation_id in stops:
            conn.execute(
                "INSERT INTO stopped_activations(activation_id) VALUES (?) "
                "ON CONFLICT(activation_id) DO NOTHING",
                (activation_id,),
            )
        conn.execute(f"DROP TABLE {_RETIRED_CASCADES}")

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
                a reason or a position, ``match`` names an id with no UTF-8 encoding
                (which SQLite could not bind), or the backend fails.
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
            answer = self._decided_claim(conn, record, named, deliberate_repeat)
            if answer is ActivationEffectClaim.CLAIMED:
                _insert_effect(conn, record)
        return answer

    def _decided_claim(
        self,
        conn: sqlite3.Connection,
        record: ActivationEffect,
        named: tuple[str, ...] | None,
        deliberate_repeat: bool,
    ) -> ActivationEffectClaim:
        """Decide one claim on ``conn``, inside the caller's write transaction.

        The stop, the held id, the spend and the backstop, read on the transaction's own
        connection: the claim's step, and the first half of a spawn's (ADR-0350 §3:3).

        Raises:
            ClaimStopped: If the store holds a stop record for the activation.
            PlanningError: If the store already holds a record under the id.
        """
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
                    _PART_ROWS.format(keys="(?, ?)", seq=""),
                    (record.part.round, record.part.part) * 2,
                ).fetchall()
            ]
        )
        # Read in slices on this transaction's own connection, so a match past
        # SQLite's bound is still read whole under the write lock (issue #3296).
        matched = [
            _checked_activation_effect(str(self._path), row)
            for row in _effect_rows(conn, named or ())
        ]
        return decide_activation_claim(
            record,
            match=named,
            deliberate_repeat=deliberate_repeat,
            stopped=_is_stopped(conn, record.activation_id),
            held_ids=() if held is None else (record.id,),
            matched=matched,
            spent=spent,
        )

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
            PlanningError: If ``effect_id`` is not an identifier, the record is not
                held or already finished, the reason is blank or has no UTF-8
                encoding, the reason or position does not belong to the outcome, or
                the backend fails.
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
            PlanningError: If ``activation_ids`` is a bare string, or not a sequence
                of strings, names an id with no UTF-8 encoding (which SQLite could not
                bind), or the backend fails.
        """
        named = requested_activations(activation_ids)
        if not named:
            return ()
        async with self._lock:
            rows = await _run_to_completion(self._activation_effects_sync, named)
        return tuple(_checked_activation_effect(str(self._path), row) for row in rows)

    def _activation_effects_sync(self, named: tuple[str, ...]) -> list[tuple[Any, ...]]:
        # Several statements under one read transaction, so the slices see one snapshot
        # (issue #3296).
        with transaction(
            self._conn, "read activation effects", error=PlanningError, immediate=False
        ) as conn:
            return _effect_rows(conn, named)

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
        # Several statements under one read transaction, so the slices see one snapshot
        # (issue #3301).
        with transaction(
            self._conn,
            "read activation effects by question part",
            error=PlanningError,
            immediate=False,
        ) as conn:
            return _part_rows(conn, named)

    # --- observation records (ADR-0329 §16) ------------------------------

    async def write_observation(
        self, record: ObservationRecord, /, *, expected_revision: int
    ) -> ObservationRecord:
        """Write an episode's observation record whole, conditionally (ADR-0329 §16:9).

        The held revision, the issuer and the write are read and decided inside one
        ``BEGIN IMMEDIATE`` transaction, so a second writer holding the same
        expectation waits on the write lock and then finds the first's revision.

        Raises:
            PlanningError: If the record is not valid, the expectation is not a
                revision, the held record does not match it, or the backend fails.
        """
        # Snapshotted before the first await (ADR-0018 §3).
        written = checked_observation(record)
        expected = checked_expected_revision(expected_revision)
        async with self._lock:
            return await _run_to_completion(self._write_observation_sync, written, expected)

    def _write_observation_sync(
        self, record: ObservationRecord, expected: int
    ) -> ObservationRecord:
        with self._transaction(f"write the observation record of {record.episode!r}") as conn:
            row = conn.execute(
                "SELECT " + _OBSERVATION_COLUMNS + " FROM observations WHERE episode_id = ?",  # noqa: S608 — only a constant is interpolated
                (record.episode,),
            ).fetchone()
            held = None if row is None else _checked_observation(str(self._path), row)
            decide_observation_write(
                record.episode, held=None if held is None else held.revision, expected=expected
            )
            stored = stamped(record, self._last_issued(conn) + 1)
            conn.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (_OBSERVATION_ISSUER, str(stored.revision)),
            )
            conn.execute(
                "INSERT INTO observations(episode_id, revision, last_call_us, data) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(episode_id) DO UPDATE SET "
                "revision = excluded.revision, last_call_us = excluded.last_call_us, "
                "data = excluded.data",
                (stored.episode, stored.revision, _last_call_us(stored), stored.model_dump_json()),
            )
        return stored

    def _last_issued(self, conn: sqlite3.Connection) -> int:
        """The last observation revision issued, read on the write's own transaction.

        Absent on a file no observation was written to, which reads as nothing issued.
        A value no issuer could have written is corruption, refused rather than counted
        on: a negative one would stamp a revision a writer that read no record expects,
        and one below a revision a record carries would issue that revision again — each
        defeating the conditional write it exists for (ADR-0329 §16:6).

        Raises:
            PlanningError: If the issuer is not an integer, is negative, or is below the
                revision a held record carries.
        """
        issued = self._read_meta(conn, _OBSERVATION_ISSUER)
        last = self._meta_int(_OBSERVATION_ISSUER, issued[0]) if issued else 0
        (highest,) = conn.execute("SELECT COALESCE(MAX(revision), 0) FROM observations").fetchone()
        if last < 0 or last < highest:
            msg = (
                f"the plan store at {self._path!r} records {last} as the last observation "
                f"revision issued, below a revision it has issued; the store is corrupt"
            )
            raise PlanningError(msg)
        return last

    async def observations(self, episode_ids: Sequence[str], /) -> tuple[ObservationRecord, ...]:
        """Return the named episodes' observation records, in the order named.

        Raises:
            PlanningError: If ``episode_ids`` is not a sequence of strings, names an id
                with no UTF-8 encoding (which SQLite could not bind), or the backend
                fails.
        """
        named = requested_episodes(episode_ids)
        if not named:
            return ()
        async with self._lock:
            rows = await _run_to_completion(self._observations_sync, named)
        found = {
            record.episode: record
            for record in (_checked_observation(str(self._path), row) for row in rows)
        }
        return tuple(found[one] for one in named if one in found)

    def _observations_sync(self, named: tuple[str, ...]) -> list[tuple[Any, ...]]:
        # In slices, because the observer may ask after every due episode at once and
        # SQLite bounds the parameters one statement binds. Several statements under one
        # read transaction, so the slices see one snapshot.
        rows: list[tuple[Any, ...]] = []
        with transaction(
            self._conn, "read observation records", error=PlanningError, immediate=False
        ) as conn:
            for start in range(0, len(named), _IN_SLICE):
                part = named[start : start + _IN_SLICE]
                marks = ", ".join("?" for _ in part)
                rows.extend(
                    tuple(row)
                    for row in conn.execute(
                        "SELECT " + _OBSERVATION_COLUMNS + " FROM observations "  # noqa: S608 — only placeholders are interpolated
                        f"WHERE episode_id IN ({marks})",
                        part,
                    ).fetchall()
                )
        return rows

    async def observer_calls_since(self, since: datetime, /) -> int:
        """Count the model calls the observation records hold at or after ``since``.

        Only a record whose latest call is at or after ``since`` can hold one, so only
        those are decoded, each reconciled with its promoted columns.

        Raises:
            PlanningError: If ``since`` is not a timezone-aware instant, or the
                backend fails.
        """
        start = checked_since(since)
        async with self._lock:
            rows = await _run_to_completion(self._calls_since_sync, _micros(start))
        return sum(_checked_observation(str(self._path), row).call_count(start) for row in rows)

    def _calls_since_sync(self, since_us: int) -> list[tuple[Any, ...]]:
        try:
            return [
                tuple(row)
                for row in self._conn.execute(
                    "SELECT " + _OBSERVATION_COLUMNS + " FROM observations "  # noqa: S608 — only a constant is interpolated
                    "WHERE last_call_us >= ?",
                    (since_us,),
                ).fetchall()
            ]
        except sqlite3.Error as exc:
            raise _wrap("count the observer's model calls", "", exc) from exc

    # --- the Task Scheduler's scheduled tasks (ADR-0350 §12:3) -------------
    #
    # Every member reads the whole schedule on its own transaction's connection, runs
    # one decision of `planning.scheduled_tasks` over it, and writes back what the
    # decision changed, so each is one indivisible step (§3:3, §7:5, §9:9). The writes
    # take `BEGIN IMMEDIATE`, and the reads a deferred transaction, which sees one
    # snapshot of both tables.

    def _schedule(self, conn: sqlite3.Connection, now: datetime) -> Schedule:
        """Read the whole schedule on ``conn``, inside the caller's transaction."""
        tasks = {
            task.id: task
            for task in (
                _checked_task(str(self._path), row)
                for row in conn.execute(
                    "SELECT " + _TASK_COLUMNS + " FROM scheduled_tasks "  # noqa: S608 — only a constant is interpolated
                    "ORDER BY written_seq ASC"
                ).fetchall()
            )
        }
        return Schedule(tasks=tasks, now=now)

    def _persist(self, conn: sqlite3.Connection, schedule: Schedule) -> None:
        """Write back the tasks a decision changed and delete those it removed."""
        for task_id in schedule.changed:
            task = schedule.tasks[task_id]
            updated = conn.execute(
                "UPDATE scheduled_tasks SET data = ? WHERE id = ?",
                (task.model_dump_json(), task.id),
            ).rowcount
            if not updated:
                conn.execute(
                    "INSERT INTO scheduled_tasks(id, person, parent, written_seq, data) "
                    "VALUES (?, ?, ?, (SELECT COALESCE(MAX(written_seq), 0) + 1 "
                    "FROM scheduled_tasks), ?)",
                    (task.id, task.person, task.parent, task.model_dump_json()),
                )
        for task_id in schedule.removed:
            conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))

    async def write_scheduled_task(  # noqa: PLR0913 — the Protocol's signature
        self,
        spawn: TaskSpawn,
        effect: ActivationEffect,
        /,
        *,
        match: tuple[str, ...] | None,
        deliberate_repeat: bool = False,
        replace_any: bool = False,
        chain_limit: int,
        pending_limit: int,
    ) -> ScheduledTaskWrite:
        """Write a scheduled task with its spawn's effect claim, in one step (§3:3).

        The claim, the replace, the wait, the limits and both writes are read and
        decided inside one ``BEGIN IMMEDIATE`` transaction, so two spawns of one round
        cannot pass the limits together (§9:9). A refusal writes neither row.

        Raises:
            ClaimStopped: If the store holds a stop record for the spawning activation.
            PlanningError: If the spawn, the effect or a limit is not valid, an id is
                already held, or the backend fails.
        """
        asked = checked_spawn(spawn)
        record = checked_spawn_effect(revalidated_claim(effect))
        named = matched_activations(match)
        limits = (
            checked_limit(chain_limit, "chain limit"),
            checked_limit(pending_limit, "pending limit"),
        )
        now = self._now()
        async with self._lock:
            return await _run_to_completion(
                self._write_scheduled_task_sync,
                asked,
                record,
                named,
                (deliberate_repeat, replace_any),
                limits,
                now,
            )

    def _write_scheduled_task_sync(  # noqa: PLR0913 — the spawn, its claim and its step's facts
        self,
        spawn: TaskSpawn,
        record: ActivationEffect,
        named: tuple[str, ...] | None,
        flags: tuple[bool, bool],
        limits: tuple[int, int],
        now: datetime,
    ) -> ScheduledTaskWrite:
        deliberate_repeat, replace_any = flags
        chain_limit, pending_limit = limits
        with self._transaction(f"write scheduled task {spawn.id!r}") as conn:
            answer = self._decided_claim(conn, record, named, deliberate_repeat)
            if answer is not ActivationEffectClaim.CLAIMED:
                return ScheduledTaskWrite(answer=TaskWriteAnswer(answer.value))
            schedule = self._schedule(conn, now)
            written = decide_task_write(
                schedule,
                spawn,
                record.activation_id,
                replace_any=replace_any,
                chain_limit=chain_limit,
                pending_limit=pending_limit,
            )
            if written.answer is TaskWriteAnswer.WRITTEN:
                self._persist(conn, schedule)
                _insert_effect(conn, record)
        return written

    async def cancel_scheduled_task(
        self, task_id: str, /, *, person: str | None = None, spawned_by: str | None = None
    ) -> ScheduledTaskCancel:
        """End every pending occurrence of a task as cancelled, in one step (§9:5).

        Raises:
            PlanningError: If an id is not an identifier, or the backend fails.
        """
        named = checked_id(task_id, "scheduled task")
        whose = None if person is None else checked_person(person)
        by = checked_optional_id(spawned_by, "spawning activation")
        now = self._now()
        async with self._lock:
            return await _run_to_completion(self._cancel_scheduled_task_sync, named, whose, by, now)

    def _cancel_scheduled_task_sync(
        self, task_id: str, person: str | None, spawned_by: str | None, now: datetime
    ) -> ScheduledTaskCancel:
        with self._transaction(f"cancel scheduled task {task_id!r}") as conn:
            schedule = self._schedule(conn, now)
            answer = decide_cancel(schedule, task_id, person=person, spawned_by=spawned_by)
            self._persist(conn, schedule)
        return answer

    async def scheduled_tasks(self, task_ids: Sequence[str], /) -> tuple[ScheduledTask, ...]:
        """Return the named tasks the store holds, in the order named (§12:3).

        Raises:
            PlanningError: If ``task_ids`` is not a sequence of encodable strings, or
                the backend fails.
        """
        named = requested_ids(task_ids, "scheduled tasks")
        async with self._lock:
            held = await _run_to_completion(self._scheduled_tasks_sync)
        return tuple(held[one] for one in named if one in held)

    def _read_schedule(self, what: str) -> Schedule:
        """The whole schedule, read under one deferred transaction."""
        with transaction(self._conn, what, error=PlanningError, immediate=False) as conn:
            return self._schedule(conn, _EPOCH)

    def _scheduled_tasks_sync(self) -> dict[str, ScheduledTask]:
        return self._read_schedule("read scheduled tasks").tasks

    async def person_scheduled_tasks(
        self, person: str, states: Sequence[OccurrenceState], /
    ) -> tuple[ScheduledTask, ...]:
        """Return a person's tasks with an occurrence in any of ``states`` (§4:6).

        Raises:
            PlanningError: If ``person`` or ``states`` is not valid, or the backend
                fails.
        """
        whose = checked_person(person)
        wanted = requested_states(states)
        async with self._lock:
            held = await _run_to_completion(self._person_scheduled_tasks_sync)
        return by_person(held, whose, wanted)

    def _person_scheduled_tasks_sync(self) -> dict[str, ScheduledTask]:
        return self._read_schedule("read a person's scheduled tasks").tasks

    async def spawned_tasks(self, activation_ids: Sequence[str], /) -> tuple[ScheduledTask, ...]:
        """Return the tasks whose parent is any of the named activations (§12:3).

        Raises:
            PlanningError: If ``activation_ids`` is not a sequence of encodable
                strings, or the backend fails.
        """
        named = requested_ids(activation_ids, "spawned tasks")
        async with self._lock:
            held = await _run_to_completion(self._spawned_tasks_sync)
        return spawned_by(held, named)

    def _spawned_tasks_sync(self) -> dict[str, ScheduledTask]:
        return self._read_schedule("read spawned tasks").tasks

    async def scheduled_lineage(self, activation_id: str, /) -> tuple[ScheduledTask, ...]:
        """Return the lineage of the task pushed to ``activation_id`` (§6:5).

        Raises:
            PlanningError: If ``activation_id`` is not an identifier, or the backend
                fails.
        """
        named = checked_id(activation_id, "activation")
        async with self._lock:
            held = await _run_to_completion(self._scheduled_lineage_sync)
        return lineage(held, named)

    def _scheduled_lineage_sync(self) -> dict[str, ScheduledTask]:
        return self._read_schedule("read a scheduled task's lineage").tasks

    async def live_below(self, task_id: str, /) -> bool:
        """Whether anything below a task is pending, pushed or running (§7:8).

        Raises:
            PlanningError: If ``task_id`` is not an identifier, or the backend fails.
        """
        named = checked_id(task_id, "scheduled task")
        async with self._lock:
            held = await _run_to_completion(self._live_below_sync)
        return live_below(held, named)

    def _live_below_sync(self) -> dict[str, ScheduledTask]:
        return self._read_schedule("read what is live below a scheduled task").tasks

    async def due_occurrences(self, at: datetime, /) -> ScheduledDue:
        """Return the occurrences due at or before ``at``, and the next due after (§7:3).

        Raises:
            PlanningError: If ``at`` is not a timezone-aware instant, or the backend
                fails.
        """
        instant = checked_instant(at)
        async with self._lock:
            held = await _run_to_completion(self._due_occurrences_sync)
        return due(held, instant)

    def _due_occurrences_sync(self) -> dict[str, ScheduledTask]:
        return self._read_schedule("read the scheduled occurrences due").tasks

    async def mark_occurrence_pushed(
        self, task_id: str, number: int, activation_id: str, /, *, rule: RulePush | None = None
    ) -> OccurrencePush:
        """Mark a pending occurrence pushed, in one step (§7:5, ADR-0352 §2:3).

        A rule's occurrence first pushed writes its successor, and any it skips, inside
        the same ``BEGIN IMMEDIATE`` transaction (ADR-0340 §4:6, §4:8, §9:3).

        Raises:
            PlanningError: If an argument is not valid, the task holds no such
                occurrence, the activation was already pushed to, ``rule`` does not fit
                the push, or the backend fails.
        """
        named = checked_id(task_id, "scheduled task")
        which = checked_number(number)
        pushed = checked_id(activation_id, "activation")
        instants = checked_rule_push(rule)
        now = self._now()
        async with self._lock:
            return await _run_to_completion(
                self._mark_occurrence_pushed_sync, named, which, pushed, instants, now
            )

    def _mark_occurrence_pushed_sync(
        self,
        task_id: str,
        number: int,
        activation_id: str,
        rule: RulePush | None,
        now: datetime,
    ) -> OccurrencePush:
        with self._transaction(f"push occurrence {number} of {task_id!r}") as conn:
            schedule = self._schedule(conn, now)
            answer = decide_push(schedule, task_id, number, activation_id, rule=rule)
            self._persist(conn, schedule)
        return answer

    async def settle_occurrence(
        self, activation_id: str, state: OccurrenceState, /, *, second_try: bool = False
    ) -> ScheduledTask:
        """Write the outcome of the occurrence pushed to an activation (§7:6, §8).

        The stop record it reads and the write are one ``BEGIN IMMEDIATE`` step.

        Raises:
            PlanningError: If no occurrence is pushed to it, the outcome is refused, or
                the backend fails.
        """
        named = checked_id(activation_id, "activation")
        outcome = checked_state(state)
        now = self._now()
        async with self._lock:
            return await _run_to_completion(
                self._settle_occurrence_sync, named, outcome, second_try is True, now
            )

    def _settle_occurrence_sync(
        self, activation_id: str, state: OccurrenceState, second_try: bool, now: datetime
    ) -> ScheduledTask:
        with self._transaction(f"settle the occurrence of {activation_id!r}") as conn:
            schedule = self._schedule(conn, now)
            task = decide_settle(
                schedule,
                activation_id,
                state,
                second_try=second_try,
                stopped=_is_stopped(conn, activation_id),
            )
            self._persist(conn, schedule)
        return task

    async def stop_pushed_activation(self, activation_id: str, /) -> bool:
        """Write a stop record for an activation pushed and not yet admitted (§9:10).

        Raises:
            PlanningError: If ``activation_id`` is not an identifier, or the backend
                fails.
        """
        named = revalidated_activation_id(activation_id)
        async with self._lock:
            return await _run_to_completion(self._stop_pushed_activation_sync, named)

    def _stop_pushed_activation_sync(self, activation_id: str) -> bool:
        with self._transaction(f"stop pushed activation {activation_id!r}") as conn:
            if not is_pushed(self._schedule(conn, _EPOCH).tasks, activation_id):
                return False
            conn.execute(
                "INSERT INTO stopped_activations(activation_id) VALUES (?) "
                "ON CONFLICT(activation_id) DO NOTHING",
                (activation_id,),
            )
        return True

    async def stopped_activations(self, activation_ids: Sequence[str], /) -> tuple[str, ...]:
        """Return which of the named activations the store holds a stop record for.

        Raises:
            PlanningError: If ``activation_ids`` is not a sequence of encodable
                strings, or the backend fails.
        """
        named = requested_ids(activation_ids, "stop records")
        if not named:
            return ()
        async with self._lock:
            held = await _run_to_completion(self._stopped_activations_sync, named)
        return tuple(one for one in named if one in held)

    def _stopped_activations_sync(self, named: tuple[str, ...]) -> set[str]:
        held: set[str] = set()
        with transaction(
            self._conn, "read stop records", error=PlanningError, immediate=False
        ) as conn:
            for start in range(0, len(named), _IN_SLICE):
                part = named[start : start + _IN_SLICE]
                marks = ", ".join("?" for _ in part)
                held.update(
                    revalidated_activation_id(row[0])
                    for row in conn.execute(
                        "SELECT activation_id FROM stopped_activations "  # noqa: S608 — only placeholders are interpolated
                        f"WHERE activation_id IN ({marks})",
                        part,
                    ).fetchall()
                )
        return held

    async def confirm_message_effect(
        self, effect_id: str, /, *, delivered: bool, position: int | None = None
    ) -> None:
        """Settle a message's effect record from its place's confirmation, once (§8:11).

        The read of the held record and the write are one ``BEGIN IMMEDIATE`` step.

        Raises:
            PlanningError: If the record is not held, is a call, is already settled,
                the position does not match ``delivered``, or the backend fails.
        """
        named = checked_effect_id(effect_id)
        async with self._lock:
            await _run_to_completion(self._confirm_message_effect_sync, named, delivered, position)

    def _confirm_message_effect_sync(
        self, effect_id: str, delivered: object, position: object
    ) -> None:
        with self._transaction(f"confirm activation effect {effect_id!r}") as conn:
            row = conn.execute(
                "SELECT " + _EFFECT_COLUMNS + " FROM activation_effects WHERE id = ?",  # noqa: S608 — only a constant is interpolated
                (effect_id,),
            ).fetchone()
            held = None if row is None else _checked_activation_effect(str(self._path), row)
            record = confirmed(held, effect_id, delivered=delivered, position=position)
            conn.execute(
                "UPDATE activation_effects SET data = ? WHERE id = ?",
                (record.model_dump_json(), effect_id),
            )

    async def remove_scheduled_task(self, task_id: str, /) -> bool:
        """Remove a task once nothing of it or below it is live, in one step (§7:8).

        Raises:
            PlanningError: If ``task_id`` is not an identifier, or the backend fails.
        """
        named = checked_id(task_id, "scheduled task")
        async with self._lock:
            return await _run_to_completion(self._remove_scheduled_task_sync, named)

    def _remove_scheduled_task_sync(self, task_id: str) -> bool:
        with self._transaction(f"remove scheduled task {task_id!r}") as conn:
            schedule = self._schedule(conn, _EPOCH)
            removed = decide_removal(schedule, task_id)
            self._persist(conn, schedule)
        return removed

    # --- data rights (ADR-0004) -------------------------------------------

    async def export(self) -> PlanExport:
        """Return a portable, internally consistent snapshot (ADR-0004 §6).

        The document carries the three kinds of record this store holds: every stop
        record, every activation effect record in claim order, and every observation
        record by episode id. Its goal, plan, execution, attempt, question, evidence
        and goal-effect sections left it with the members that wrote them (ADR-0309
        §5).
        """
        exported_at = self._now()
        async with self._lock:
            stopped, acted, observed, schedule = await _run_to_completion(self._export_sync)
        return PlanExport(
            exported_at=exported_at,
            # ADR-0297 §1: every stop record, in a deterministic order.
            stopped_activations=tuple(stopped),
            # ADR-0306 §6: every effect record, in claim order.
            activation_effects=tuple(acted),
            # ADR-0329 §16:9: every observation record, by episode id.
            observations=tuple(observed),
            # ADR-0350 §12:3: every scheduled task, in the order written.
            scheduled_tasks=tuple(schedule.tasks.values()),
        )

    def _export_sync(
        self,
    ) -> tuple[list[str], list[ActivationEffect], list[ObservationRecord], Schedule]:
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
            observed = [
                _checked_observation(str(self._path), row)
                for row in conn.execute(
                    "SELECT " + _OBSERVATION_COLUMNS + " FROM observations "  # noqa: S608 — only a constant is interpolated
                    "ORDER BY episode_id ASC"
                ).fetchall()
            ]
            schedule = self._schedule(conn, _EPOCH)
        return stopped, acted, observed, schedule

    async def clear(self) -> int:
        """Delete every record, the Task Scheduler's included, returning the count.

        The store holds no execution, so no live step can refuse the erase. The
        observation issuer in ``meta`` is kept, so no revision is issued twice
        (ADR-0329 §16:9).
        """
        async with self._lock:
            return await _run_to_completion(self._clear_sync)

    def _clear_sync(self) -> int:
        with self._transaction("clear the plan store") as conn:
            # ADR-0297 §1: `clear` erases every stop record with the store's other rows.
            removed: int = conn.execute("DELETE FROM stopped_activations").rowcount
            # ADR-0306 §6: and every effect record.
            removed += conn.execute("DELETE FROM activation_effects").rowcount
            # ADR-0329 §16:9: and every observation record. `meta`, which holds the
            # observation issuer, is untouched.
            removed += conn.execute("DELETE FROM observations").rowcount
            # ADR-0350 §12:3: and every scheduled task.
            removed += conn.execute("DELETE FROM scheduled_tasks").rowcount
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


def _insert_effect(conn: sqlite3.Connection, record: ActivationEffect) -> None:
    """Write a claimed effect record on ``conn``, inside the caller's transaction."""
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


def _checked_task(path: str, row: Sequence[Any]) -> ScheduledTask:
    """Decode one scheduled task and refuse a blob that disagrees with its columns.

    The id, the person and the parent are promoted, so each is reconciled with the
    record a tampered file could answer with (ADR-0350 §12:3).

    Args:
        path: The store's path, for the message.
        row: ``(id, person, parent, data)``.

    Returns:
        The reconciled task.

    Raises:
        PlanningError: If the blob does not validate, or disagrees with its columns.
    """
    try:
        task = ScheduledTask.model_validate_json(str(row[3]))
    except ValidationError as exc:
        msg = f"the plan store holds a scheduled task that no longer validates: {exc}"
        raise PlanningError(msg) from exc
    promoted = (row[0], row[1], row[2])
    held = (task.id, task.person, task.parent)
    if promoted != held:
        msg = (
            f"the plan store at {path!r} holds a scheduled task indexed at {promoted} "
            f"whose record names {held}; the store is corrupt"
        )
        raise PlanningError(msg)
    return task


def _micros(instant: datetime) -> int:
    """``instant`` as whole microseconds since the epoch, the budget's column unit."""
    return (instant - _EPOCH) // timedelta(microseconds=1)


def _last_call_us(record: ObservationRecord) -> int | None:
    """The record's latest model call, as :data:`_RECORD_SCHEMA`'s ``last_call_us``."""
    last = record.last_call_at
    return None if last is None else _micros(last)


def _checked_observation(path: str, row: Sequence[Any]) -> ObservationRecord:
    """Decode one observation record and refuse a blob that disagrees with its columns.

    The episode, the revision and the latest call are promoted, and the conditional
    write, the reads and the budget's count select on them, so each is reconciled with
    the record a tampered file could answer with.

    Args:
        path: The store's path, for the message.
        row: ``(episode_id, revision, last_call_us, data)``.

    Returns:
        The reconciled record.

    Raises:
        PlanningError: If the blob does not validate, or disagrees with its columns.
    """
    try:
        record = ObservationRecord.model_validate_json(str(row[3]))
    except ValidationError as exc:
        msg = f"the plan store holds an observation record that no longer validates: {exc}"
        raise PlanningError(msg) from exc
    promoted = (row[0], row[1], row[2])
    held = (record.episode, record.revision, _last_call_us(record))
    if promoted != held:
        msg = (
            f"the plan store at {path!r} holds an observation record indexed at {promoted} "
            f"whose record names {held}; the store is corrupt"
        )
        raise PlanningError(msg)
    return record


def _effect_rows(conn: sqlite3.Connection, activations: Sequence[str]) -> list[tuple[Any, ...]]:
    """The effect rows of ``activations``, in claim order, read in slices of the ids.

    In slices, because SQLite bounds the parameters one statement binds, and a read or a
    match names any number of activations (issue #3296). The caller holds the
    transaction the slices run in, so they see one state of the table. Each id is read
    once, so no row is answered twice, and the rows are put in claim order across the
    slices by :func:`_claim_order`, which orders as ``ORDER BY claimed_seq`` would.

    Args:
        conn: The connection, inside the caller's transaction.
        activations: The activations whose rows to read.

    Returns:
        ``(id, activation_id, data, part_round, part_number)`` per row, in claim order.
    """
    named = tuple(dict.fromkeys(activations))
    keyed: list[tuple[Any, ...]] = []
    for start in range(0, len(named), _IN_SLICE):
        part = named[start : start + _IN_SLICE]
        marks = ", ".join("?" for _ in part)
        keyed.extend(
            tuple(row)
            for row in conn.execute(
                "SELECT claimed_seq, " + _EFFECT_COLUMNS + " FROM activation_effects "  # noqa: S608 — only placeholders are interpolated
                f"WHERE activation_id IN ({marks})",
                part,
            ).fetchall()
        )
    keyed.sort(key=lambda row: _claim_order(row[0]))
    return [row[1:] for row in keyed]


def _part_rows(conn: sqlite3.Connection, parts: Sequence[QuestionPart]) -> list[tuple[Any, ...]]:
    """The rows carrying any of ``parts``, in claim order, read in slices of the parts.

    In slices, because SQLite bounds the parameters one statement binds, and a read
    names any number of parts (issue #3301). The caller holds the transaction the
    slices run in, so they see one state of the table, and the rows are put in claim
    order across the slices by :func:`_claim_order`, as :func:`_effect_rows` puts them.

    A row is answered as often as the single statement these slices replace answered
    it, which is once. A later slice can find a row an earlier one found: its columns
    and its record may name two parts the read names apart, or a hand-built file may
    collate ``part_round`` other than ``BINARY``, so that two parts the read tells apart
    both match it. A row a later slice finds again is dropped. Rows equal in every
    column match the same parts, so they first appear in one slice together, and each
    is kept there, as the single statement keeps each.

    Args:
        conn: The connection, inside the caller's transaction.
        parts: The question parts whose rows to read, each once.

    Returns:
        ``(id, activation_id, data, part_round, part_number)`` per row, in claim order.
    """
    seen: set[tuple[Any, ...]] = set()
    keyed: list[tuple[Any, ...]] = []
    for start in range(0, len(parts), _PART_SLICE):
        part = parts[start : start + _PART_SLICE]
        keys = ", ".join("(?, ?)" for _ in part)
        values = [value for one in part for value in (one.round, one.part)]
        fresh = [
            row
            for row in (
                tuple(found)
                for found in conn.execute(
                    _PART_ROWS.format(keys=keys, seq="claimed_seq, "), values * 2
                ).fetchall()
            )
            if row not in seen
        ]
        seen.update(fresh)
        keyed.extend(fresh)
    keyed.sort(key=lambda row: _claim_order(row[0]))
    return [row[1:] for row in keyed]


def _claim_order(seq: object) -> tuple[int, Any]:
    """Sort key putting ``claimed_seq`` values in the order SQLite's ``ORDER BY`` does.

    The column is ``INTEGER`` and the store writes integers alone, but an outside writer
    can store text or a blob in it, which Python will not compare with an integer. SQLite
    orders ``NULL``, then numbers, then text, then blobs, each by value (text in UTF-8
    byte order, which is code point order), so the merged slices answer exactly as the
    single statement they replace did.
    """
    if seq is None:
        return (0, 0)
    if isinstance(seq, (int, float)):
        return (1, seq)
    if isinstance(seq, str):
        return (2, seq)
    return (3, seq)


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
