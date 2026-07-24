"""SqlitePlanStore: the shared PlanStore conformance suite, and its durability.

The conformance subclass runs against ``:memory:`` (no filesystem, so no
``integration`` mark). The tests that open a real file — the half this store
exists for (ADR-0049 §2): a parked confirmation, an execution, and the non-reused
id space surviving the process that made them — say so via ``tmp_path``.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from plan_store_contract import PlanStoreContract, _goal, _plan

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import StepStatus, StepTransition
from ai_assistant.planning import SqlitePlanStore

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ai_assistant.core.protocols import PlanStore


def _fixed_now() -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC)


async def _seed_and_start(store: SqlitePlanStore, plan_id: str = "p1") -> str:
    """Save a goal+plan and start one execution, returning its id."""
    await store.save_goal(_goal())
    await store.save_plan(_plan(plan_id=plan_id))
    return (await store.start_execution(plan_id)).id


async def _park(store: SqlitePlanStore) -> str:
    """Seed, start, and drive the one step to AWAITING_APPROVAL; return the id."""
    state = await store.start_execution("p1")
    await store.commit_transition(
        StepTransition(
            execution_id=state.id,
            step_id="s1",
            to_status=StepStatus.AWAITING_APPROVAL,
            expected_version=state.version,
            bound_tool="smtp",
        )
    )
    return state.id


class TestSqlitePlanStoreContract(PlanStoreContract):
    """Runs SqlitePlanStore through the shared PlanStore conformance suite."""

    @pytest.fixture
    def store(self) -> Iterator[PlanStore]:
        realised = SqlitePlanStore(path=":memory:", now=_fixed_now)
        try:
            yield realised
        finally:
            realised.close()


# --- durability: state survives the process (ADR-0049 §2) ------------------


async def test_a_parked_confirmation_survives_a_restart(tmp_path: Path) -> None:
    """The property the whole store exists for: an AWAITING_APPROVAL step reloads.

    A restarted StepRunner recovers it by asking the trail for
    ``pending_confirmation(execution_id, step_id)`` (ADR-0044 §3), so the
    ``bound_tool`` and the durable execution id must survive, and the step must
    still be resumable — a RUNNING transition commits after the reopen.
    """
    path = tmp_path / "plans.db"
    first = SqlitePlanStore(path=path, now=_fixed_now)
    await first.save_goal(_goal())
    await first.save_plan(_plan())
    execution_id = await _park(first)
    first.close()

    reopened = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        state = await reopened.get_execution(execution_id)
        assert state is not None
        step = state.step("s1")
        assert step is not None
        assert step.status is StepStatus.AWAITING_APPROVAL
        assert step.bound_tool == "smtp"

        # Resumable across the restart: the parked step still claims.
        ran = await reopened.commit_transition(
            StepTransition(
                execution_id=execution_id,
                step_id="s1",
                to_status=StepStatus.RUNNING,
                expected_version=state.version,
                approval_ref="perm-1",
            )
        )
        resumed = ran.step("s1")
        assert resumed is not None
        assert resumed.status is StepStatus.RUNNING
    finally:
        reopened.close()


async def test_an_execution_id_is_not_reused_after_delete_then_reopen(tmp_path: Path) -> None:
    """The durable exec_counter does not rewind across delete_goal + a reopen."""
    path = tmp_path / "plans.db"
    first = SqlitePlanStore(path=path, now=_fixed_now)
    first_id = await _seed_and_start(first)
    await first.delete_goal("g1")
    first.close()

    reopened = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        second_id = await _seed_and_start(reopened)
        assert second_id != first_id
    finally:
        reopened.close()


async def test_an_execution_id_is_not_reused_after_clear_then_reopen(tmp_path: Path) -> None:
    """Same non-reuse through clear + a reopen: the counter is not reset."""
    path = tmp_path / "plans.db"
    first = SqlitePlanStore(path=path, now=_fixed_now)
    first_id = await _seed_and_start(first)
    await first.clear()
    first.close()

    reopened = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        second_id = await _seed_and_start(reopened)
        assert second_id != first_id
    finally:
        reopened.close()


# --- execution-id non-reuse across fresh instances (ADR-0049 §3) -----------


async def test_two_fresh_memory_instances_do_not_reuse_an_id() -> None:
    """The mode where the durable counter is worthless (a fresh :memory: DB).

    Non-reuse there rests entirely on the per-incarnation nonce. Injecting two
    *distinct* fixed nonces makes the assertion deterministic (not two real
    uuid4()s differing) and lets it check the id actually embeds its nonce.
    """
    first = SqlitePlanStore(path=":memory:", now=_fixed_now, incarnation_factory=lambda: "NONCE-A")
    second = SqlitePlanStore(path=":memory:", now=_fixed_now, incarnation_factory=lambda: "NONCE-B")
    try:
        first_id = await _seed_and_start(first)
        second_id = await _seed_and_start(second)
        assert first_id != second_id
        assert "NONCE-A" in first_id
        assert "NONCE-B" in second_id
    finally:
        first.close()
        second.close()


@pytest.mark.skipif(not hasattr(os, "fork"), reason="platform has no fork")
async def test_execution_ids_do_not_collide_across_a_fork() -> None:
    """#305's copied-store case, closed by reading the pid *at allocation*.

    The store — nonce and all — is constructed and seeded in the **parent**, then
    ``fork``ed. A fork copies the incarnation nonce (and the whole store object)
    into both children, so the only thing that can differentiate their ids is the
    pid — and only if it is read at allocation, not captured in ``__init__``. Each
    child drives ``_start_execution_sync`` directly on its own copied ``:memory:``
    database (a forked child is the sole user of its copy, and this avoids reusing
    the parent's event loop), then writes its id through a pipe. A buggy impl that
    stored ``os.getpid()`` at construction would give both children the *parent's*
    pid and identical ids — this test fails on that; the real impl reads the pid in
    ``_start_execution_sync`` and the ids differ.
    """
    parent = SqlitePlanStore(path=":memory:", now=_fixed_now, incarnation_factory=lambda: "SHARED")
    await parent.save_goal(_goal())
    await parent.save_plan(_plan())

    def _run_child(write_fd: int) -> None:
        # Drive the sync allocation path directly: no event loop (the parent's is
        # copied into the child and must not be reused), the sole user of this
        # child's copied in-memory database.
        exec_id = parent._start_execution_sync("p1").id
        with os.fdopen(write_fd, "w") as pipe:
            pipe.write(exec_id)
        os._exit(0)

    ids: list[str] = []
    try:
        for _ in range(2):
            read_fd, write_fd = os.pipe()
            pid = os.fork()
            if pid == 0:  # child
                os.close(read_fd)
                _run_child(write_fd)
            os.close(write_fd)  # parent
            with os.fdopen(read_fd) as pipe:
                ids.append(pipe.read())
            os.waitpid(pid, 0)  # noqa: ASYNC222 — reaping a forked child in a test
    finally:
        parent.close()

    assert "SHARED" in ids[0]
    assert ids[0] != ids[1], "forked children sharing a nonce must differ by pid"


# --- transactional integrity (ADR-0049 §1) ---------------------------------


async def test_a_refused_transition_leaves_the_execution_untouched(tmp_path: Path) -> None:
    """A rejected commit rolls back: no half-applied version reaches disk.

    An illegal transition (PENDING → SUCCEEDED, skipping the claim) must raise
    and change nothing — asserted by reopening the file, so a return-value-only
    rollback would not pass.
    """
    path = tmp_path / "plans.db"
    store = SqlitePlanStore(path=path, now=_fixed_now)
    execution_id = await _seed_and_start(store)
    before = await store.get_execution(execution_id)
    assert before is not None

    with pytest.raises(PlanningError):
        await store.commit_transition(
            StepTransition(
                execution_id=execution_id,
                step_id="s1",
                to_status=StepStatus.SUCCEEDED,
                expected_version=before.version,
            )
        )
    store.close()

    reopened = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        after = await reopened.get_execution(execution_id)
        assert after is not None
        assert after.version == before.version
        step = after.step("s1")
        assert step is not None
        assert step.status is StepStatus.PENDING
    finally:
        reopened.close()


async def test_two_connections_serialise_a_compare_and_swap(tmp_path: Path) -> None:
    """Two stores on one file: only one writer of a version wins (ADR-0049 §1)."""
    path = tmp_path / "plans.db"
    a = SqlitePlanStore(path=path, now=_fixed_now)
    execution_id = await _seed_and_start(a)
    b = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        state_a = await a.get_execution(execution_id)
        state_b = await b.get_execution(execution_id)
        assert state_a is not None
        assert state_b is not None

        claim_a = StepTransition(
            execution_id=execution_id,
            step_id="s1",
            to_status=StepStatus.RUNNING,
            expected_version=state_a.version,
            bound_tool="smtp",
            approval_ref="perm-1",
        )
        claim_b = claim_a.model_copy(update={"approval_ref": "perm-2"})

        await a.commit_transition(claim_a)
        with pytest.raises(PlanningError):  # StaleExecutionError, a PlanningError
            await b.commit_transition(claim_b)
    finally:
        a.close()
        b.close()


async def test_two_connections_do_not_reuse_an_execution_id(tmp_path: Path) -> None:
    """The durable counter, allocated under the write lock, is unique across a file."""
    path = tmp_path / "plans.db"
    a = SqlitePlanStore(path=path, now=_fixed_now)
    await a.save_goal(_goal())
    await a.save_plan(_plan())
    b = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        id_a = (await a.start_execution("p1")).id
        id_b = (await b.start_execution("p1")).id
        assert id_a != id_b
    finally:
        a.close()
        b.close()


async def test_two_stores_can_open_one_fresh_file(tmp_path: Path) -> None:
    """Concurrent first-time opens do not race on the meta initialisation (§1).

    Setup runs under ``BEGIN IMMEDIATE``, so a second store opening the same
    freshly-created file finds the schema and meta already there rather than
    losing a primary-key race on the ``schema_version`` insert. Both stores are
    then usable, and their durable counter is shared (distinct ids).
    """
    path = tmp_path / "plans.db"
    a = SqlitePlanStore(path=path, now=_fixed_now)
    b = SqlitePlanStore(path=path, now=_fixed_now)  # second open of the fresh file
    try:
        await a.save_goal(_goal())
        await a.save_plan(_plan())
        id_a = (await a.start_execution("p1")).id
        id_b = (await b.start_execution("p1")).id
        assert id_a != id_b
    finally:
        a.close()
        b.close()


async def test_a_newer_schema_is_refused_before_any_record_table_exists(tmp_path: Path) -> None:
    """A rejected newer-schema open leaves no schema behind (§1).

    A database holding only a ``meta`` table marked ``schema_version = 999`` must
    be refused *before* ``goals``/``plans``/``executions`` are created — creating a
    table is a write, and the refusal must precede any write. The rollback of the
    setup transaction also removes the ``meta`` table this attempt would create.
    """
    path = tmp_path / "plans.db"
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    raw.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '999')")
    raw.commit()
    raw.close()

    with pytest.raises(PlanningError, match="newer version"):
        SqlitePlanStore(path=path, now=_fixed_now)

    check = sqlite3.connect(path)
    try:
        tables = {
            row[0] for row in check.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "goals" not in tables
        assert "plans" not in tables
        assert "executions" not in tables
    finally:
        check.close()


def test_foreign_keys_are_enforced(tmp_path: Path) -> None:
    """The pragma is on, so the referential-integrity backstop is live (§1)."""
    path = tmp_path / "plans.db"
    store = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        (flag,) = store._conn.execute("PRAGMA foreign_keys").fetchone()
        assert flag == 1
        # A raw orphan insert — bypassing the app-level check — is refused.
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute("INSERT INTO plans(id, goal_id, data) VALUES ('p9', 'ghost', '{}')")
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

    with pytest.raises(PlanningError, match="newer version"):
        SqlitePlanStore(path=path, now=_fixed_now)


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


async def test_export_is_a_single_consistent_snapshot(tmp_path: Path) -> None:
    """A committed goal+plan pair is exported whole, never as a dangling plan.

    ``export`` reads all three tables inside one ``BEGIN IMMEDIATE`` transaction
    (ADR-0004 §6), so a second connection cannot interleave a write between the
    reads and leave a plan whose goal is missing — the referential inconsistency
    ``PlanExport`` rejects. Two connections on one file: writer ``b`` commits a
    goal and its plan; reader ``a``'s export then sees *both*, and (before ``b``
    writes) sees *neither* — all-or-nothing visibility, which is exactly the
    anti-dangling guarantee. A torn half would raise ``ValidationError`` here.
    """
    path = tmp_path / "plans.db"
    a = SqlitePlanStore(path=path, now=_fixed_now)
    b = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        empty = await a.export()
        assert empty.goals == ()
        assert empty.plans == ()

        await b.save_goal(_goal())
        await b.save_plan(_plan())

        whole = await a.export()
        assert [g.id for g in whole.goals] == ["g1"]
        assert [p.id for p in whole.plans] == ["p1"]
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
