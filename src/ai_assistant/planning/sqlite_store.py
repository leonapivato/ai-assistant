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
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import ActiveExecutionError, PlanningError
from ai_assistant.core.types import (
    ActionPlan,
    ExecutionState,
    Goal,
    GoalDeletion,
    PlanExport,
    StepStatus,
)
from ai_assistant.planning.execution import PlanExecution

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import StepTransition

_OWNER_ONLY = 0o600

#: The only on-disk schema this code understands. Written to ``meta`` at creation
#: (ADR-0049 §1) so a *future* version has a marker to migrate from; opening a
#: database labelled newer than this is refused loudly rather than read blindly.
_SCHEMA_VERSION = 1

# The ``meta`` table is created first and on its own, so the schema version can be
# read and a newer store refused *before* any record table is created (ADR-0049
# §1: refuse before reading or writing records — creating a table is a write).
_META_SCHEMA = "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"

_RECORD_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS goals(id TEXT PRIMARY KEY, data TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS plans("
    "id TEXT PRIMARY KEY, goal_id TEXT NOT NULL REFERENCES goals(id), data TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS executions("
    "id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(id), "
    "version INTEGER NOT NULL, active INTEGER NOT NULL, "
    "created_seq INTEGER NOT NULL, data TEXT NOT NULL)",
)


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
            PlanningError: If the database cannot be opened or initialised, or is
                labelled with a schema version newer than this code understands.
        """
        self._path = path if path == ":memory:" else str(Path(path))
        self._clock = checked_clock(now, owner="SqlitePlanStore")
        self._tracker = tracker or PlanExecution(now=now)
        self._incarnation_factory = incarnation_factory
        # Minted once per store object. Folded together with os.getpid() *at
        # allocation time* (see start_execution), so a fork that copies this
        # value still yields distinct ids by the differing pid (ADR-0049 §3).
        self._nonce = incarnation_factory()
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    def _setup(self) -> sqlite3.Connection:
        """Connect, enforce foreign keys, create the schema, verify the version."""
        try:
            conn = sqlite3.connect(self._path, check_same_thread=False)
        except (sqlite3.Error, OSError) as exc:
            # e.g. the parent directory does not exist — no connection to close.
            msg = f"failed to open the plan store at {self._path!r}: {exc}"
            raise PlanningError(msg) from exc
        try:
            # Per-connection, not persisted: the referential-integrity guard of
            # ADR-0049 §1 is only in force while this pragma is on.
            conn.execute("PRAGMA foreign_keys = ON")
            with conn:
                # BEGIN IMMEDIATE takes the write lock for the whole of setup, so
                # two processes opening a fresh file are serialised — one creates
                # and initialises, the other finds it done — rather than racing on
                # the meta insert (ADR-0049 §1).
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(_META_SCHEMA)
                # Refuse a newer store *before* creating any record table, so a
                # rejected open leaves no schema behind (the transaction rolls the
                # meta table back too on the raise).
                self._verify_or_init_meta(conn)
                for statement in _RECORD_SCHEMA:
                    conn.execute(statement)
            if self._path != ":memory:":
                Path(self._path).chmod(_OWNER_ONLY)
        except PlanningError:
            conn.close()  # never leak the connection when opening fails
            raise
        except (sqlite3.Error, OSError) as exc:
            conn.close()
            msg = f"failed to initialise the plan store at {self._path!r}: {exc}"
            raise PlanningError(msg) from exc
        return conn

    def _verify_or_init_meta(self, conn: sqlite3.Connection) -> None:
        """Write the version and counter on a fresh DB, or refuse any other version.

        Runs inside the setup transaction. ADR-0049 §1 makes v1 the first and only
        on-disk schema — a fresh database is the sole prior state — so a stored
        ``schema_version`` that is anything *other than* the supported one, newer
        **or** older, is refused with ``PlanningError`` *before any record table is
        created, read, or written*. There is no migration yet, and an older label
        on an incompatible ``goals`` table would otherwise construct successfully
        and only fail on the first query with a raw "no such column" — a fault to
        report at open, not defer, matching how the audit trail treats a row that
        no longer validates.
        """
        existing = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        stored = existing.get("schema_version")
        if stored is None:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(_SCHEMA_VERSION),),
            )
        elif self._meta_int("schema_version", stored) != _SCHEMA_VERSION:
            msg = (
                f"the plan store at {self._path!r} has schema_version={stored}, but this "
                f"code supports only version {_SCHEMA_VERSION} and has no migration; "
                f"refusing to open it rather than read it blindly"
            )
            raise PlanningError(msg)
        if "exec_counter" in existing:
            self._meta_int("exec_counter", existing["exec_counter"])  # validate on open
        else:
            conn.execute("INSERT INTO meta(key, value) VALUES ('exec_counter', '0')")

    def _meta_int(self, key: str, raw: str) -> int:
        """Parse a stored ``meta`` integer, translating corruption to ``PlanningError``.

        A non-numeric ``schema_version`` or ``exec_counter`` is a corrupt or
        tampered store, not a Python ``ValueError`` to leak past this layer's
        initialisation boundary (ADR-0049 §1).
        """
        try:
            return int(raw)
        except ValueError as exc:
            msg = (
                f"the plan store at {self._path!r} holds a non-numeric {key} "
                f"({raw!r}); the store is corrupt"
            )
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

    # --- goals and plans --------------------------------------------------

    async def save_goal(self, goal: Goal) -> str:
        """Persist a goal, or update the parts of one that may change.

        ``status`` and ``deadline`` move over a goal's life. ``statement``,
        ``provenance`` and ``created_at`` are its identity: rewriting them would
        make every plan and execution already recorded against this id describe
        an objective the user never set, so a changed objective needs a new goal.
        """
        snapshot = goal.model_copy(deep=True)
        async with self._lock:
            await asyncio.to_thread(self._save_goal_sync, snapshot)
        return goal.id

    def _save_goal_sync(self, goal: Goal) -> None:
        conn = self._conn
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT data FROM goals WHERE id = ?", (goal.id,)).fetchone()
                if row is not None:
                    existing = _decode_goal(row[0])
                    identity = ("statement", "provenance", "created_at")
                    changed = [
                        field
                        for field in identity
                        if getattr(existing, field) != getattr(goal, field)
                    ]
                    if changed:
                        msg = (
                            f"goal {goal.id} already exists and its {', '.join(changed)} cannot "
                            "change: plans and executions already recorded against it would "
                            "silently come to describe a different objective. Use a new id."
                        )
                        raise PlanningError(msg)
                conn.execute(
                    "INSERT INTO goals(id, data) VALUES (?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                    (goal.id, goal.model_dump_json()),
                )
        except sqlite3.Error as exc:
            raise _wrap("save goal", goal.id, exc) from exc

    async def get_goal(self, goal_id: str) -> Goal | None:
        """Return the goal with ``goal_id``, or ``None``."""
        async with self._lock:
            row = await asyncio.to_thread(self._read_one, "goals", goal_id)
        return None if row is None else _decode_goal(row)

    async def save_plan(self, plan: ActionPlan) -> str:
        """Persist a plan, requiring its goal to exist and its id to be free.

        Rejecting an orphan is what lets ``export`` promise referential integrity
        without repairing anything at read time; the enforced foreign key is the
        durable backstop beneath the app-level check (ADR-0049 §1). Rejecting a
        *reused* id keeps a plan an audit record: re-planning takes a new id
        (ADR-0014 §2). An identical re-save is idempotent, so a retry is harmless.
        """
        snapshot = plan.model_copy(deep=True)
        async with self._lock:
            await asyncio.to_thread(self._save_plan_sync, snapshot)
        return plan.id

    def _save_plan_sync(self, plan: ActionPlan) -> None:
        conn = self._conn
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                if (
                    conn.execute("SELECT 1 FROM goals WHERE id = ?", (plan.goal_id,)).fetchone()
                    is None
                ):
                    msg = f"plan {plan.id} refers to unknown goal {plan.goal_id}"
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
        except sqlite3.Error as exc:
            raise _wrap("save plan", plan.id, exc) from exc

    async def get_plan(self, plan_id: str) -> ActionPlan | None:
        """Return the plan with ``plan_id``, or ``None``."""
        async with self._lock:
            row = await asyncio.to_thread(self._read_one, "plans", plan_id)
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
            return await asyncio.to_thread(self._start_execution_sync, plan_id)

    def _start_execution_sync(self, plan_id: str) -> ExecutionState:
        conn = self._conn
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
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
        except sqlite3.Error as exc:
            raise _wrap("start execution for plan", plan_id, exc) from exc
        return state.model_copy(deep=True)

    def _next_ordinal(self, conn: sqlite3.Connection) -> int:
        """Read-increment the durable execution counter, inside the open write txn.

        The write lock is already held (``BEGIN IMMEDIATE``), so this read then
        write is atomic against another process on the same file: neither the
        counter rewinds nor two executions share an ordinal (ADR-0049 §3).
        """
        (current,) = conn.execute("SELECT value FROM meta WHERE key = 'exec_counter'").fetchone()
        nxt = self._meta_int("exec_counter", current) + 1
        conn.execute("UPDATE meta SET value = ? WHERE key = 'exec_counter'", (str(nxt),))
        return nxt

    async def commit_transition(self, transition: StepTransition) -> ExecutionState:
        """Apply one transition against the stored snapshot and persist it.

        The only write path for execution state. Reading the stored state,
        applying the tracker, and writing back all run inside one
        ``BEGIN IMMEDIATE`` transaction, so a second writer that read the same
        version cannot also commit — it reads the advanced version and the tracker
        rejects it (ADR-0049 §1).
        """
        async with self._lock:
            return await asyncio.to_thread(self._commit_transition_sync, transition)

    def _commit_transition_sync(self, transition: StepTransition) -> ExecutionState:
        conn = self._conn
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT data FROM executions WHERE id = ?", (transition.execution_id,)
                ).fetchone()
                if row is None:
                    msg = f"unknown execution {transition.execution_id}"
                    raise PlanningError(msg)
                stored = _decode_execution(row[0])
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
        except sqlite3.Error as exc:
            raise _wrap("commit a transition on execution", transition.execution_id, exc) from exc
        return updated.model_copy(deep=True)

    async def get_execution(self, execution_id: str) -> ExecutionState | None:
        """Return the execution with ``execution_id``, or ``None``."""
        async with self._lock:
            row = await asyncio.to_thread(self._read_one, "executions", execution_id)
        return None if row is None else _decode_execution(row)

    async def active_executions(self) -> list[ExecutionState]:
        """Return every execution with outstanding work, oldest first.

        Ordered by the durable creation ordinal, not by id (ids embed a plan
        prefix, so sorting them would interleave plans), and filtered on the
        stored ``active`` flag so only outstanding executions are decoded.
        """
        async with self._lock:
            rows = await asyncio.to_thread(self._active_executions_sync)
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
            goals, plans, executions = await asyncio.to_thread(self._export_sync)
        return PlanExport(
            exported_at=exported_at,
            goals=tuple(_decode_goal(data) for data in goals),
            plans=tuple(_decode_plan(data) for data in plans),
            executions=tuple(_decode_execution(data) for data in executions),
        )

    def _export_sync(self) -> tuple[list[str], list[str], list[str]]:
        conn = self._conn
        try:
            # All three reads inside one transaction, so the export is a single
            # database snapshot: a concurrent connection cannot commit a goal+plan
            # between the goals read and the plans read and leave the export with a
            # plan whose goal is missing — the dangling, PlanExport-rejected state
            # ADR-0004 §6's "internally consistent" forbids. BEGIN IMMEDIATE takes
            # the write lock, so no writer interleaves the reads.
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                goals = [str(r[0]) for r in conn.execute("SELECT data FROM goals").fetchall()]
                plans = [str(r[0]) for r in conn.execute("SELECT data FROM plans").fetchall()]
                executions = [
                    str(r[0])
                    for r in conn.execute(
                        "SELECT data FROM executions ORDER BY created_seq ASC"
                    ).fetchall()
                ]
        except sqlite3.Error as exc:
            raise _wrap("export planning state", "", exc) from exc
        return goals, plans, executions

    async def delete_goal(self, goal_id: str) -> GoalDeletion:
        """Delete a goal and its plan history, unless work is live.

        Refused while any of the goal's executions has a ``RUNNING`` step. The
        cascade deletes children before parents — executions, then plans, then
        the goal — so the enforced foreign keys are satisfied at each step, and
        the live-execution refusal runs first, before anything is removed
        (ADR-0049 §1).
        """
        async with self._lock:
            return await asyncio.to_thread(self._delete_goal_sync, goal_id)

    def _delete_goal_sync(self, goal_id: str) -> GoalDeletion:
        conn = self._conn
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
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
                    "DELETE FROM executions WHERE plan_id IN "
                    "(SELECT id FROM plans WHERE goal_id = ?)",
                    (goal_id,),
                )
                conn.execute("DELETE FROM plans WHERE goal_id = ?", (goal_id,))
                conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
        except sqlite3.Error as exc:
            raise _wrap("delete goal", goal_id, exc) from exc
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
            return await asyncio.to_thread(self._clear_sync)

    def _clear_sync(self) -> int:
        conn = self._conn
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
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
                removed += conn.execute("DELETE FROM goals").rowcount
        except sqlite3.Error as exc:
            raise _wrap("clear the plan store", "", exc) from exc
        return removed

    def close(self) -> None:
        """Close the underlying database connection."""
        with contextlib.suppress(sqlite3.Error):
            self._conn.close()


def _wrap(action: str, subject: str, exc: sqlite3.Error) -> PlanningError:
    """Translate a raw ``sqlite3`` fault into `planning`'s own error at the seam."""
    target = f" {subject!r}" if subject else ""
    return PlanningError(f"failed to {action}{target}: {exc}")


def _decode_goal(data: str) -> Goal:
    """Rebuild a stored goal from its JSON, surfacing corruption as ``PlanningError``."""
    try:
        return Goal.model_validate_json(data)
    except ValidationError as exc:
        msg = f"the plan store holds a goal that no longer validates: {exc}"
        raise PlanningError(msg) from exc


def _decode_plan(data: str) -> ActionPlan:
    """Rebuild a stored plan from its JSON, surfacing corruption as ``PlanningError``."""
    try:
        return ActionPlan.model_validate_json(data)
    except ValidationError as exc:
        msg = f"the plan store holds a plan that no longer validates: {exc}"
        raise PlanningError(msg) from exc


def _decode_execution(data: str) -> ExecutionState:
    """Rebuild a stored execution from its JSON, surfacing corruption as ``PlanningError``."""
    try:
        return ExecutionState.model_validate_json(data)
    except ValidationError as exc:
        msg = f"the plan store holds an execution that no longer validates: {exc}"
        raise PlanningError(msg) from exc


__all__ = ["SqlitePlanStore"]
