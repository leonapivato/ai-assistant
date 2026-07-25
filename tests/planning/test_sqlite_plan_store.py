"""SqlitePlanStore: the shared PlanStore conformance suite, and its durability.

The conformance subclass runs against ``:memory:`` (no filesystem, so no
``integration`` mark). The tests that open a real file — the half this store
exists for (ADR-0049 §2): a parked confirmation, an execution, and the non-reused
id space surviving the process that made them — say so via ``tmp_path``.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import sqlite3
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from plan_store_contract import PlanStoreContract, _goal, _plan

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import StepStatus, StepTransition
from ai_assistant.planning import SqlitePlanStore
from ai_assistant.testing.cancellation import ThreadSuspension

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator, Sequence
    from pathlib import Path

    from ai_assistant.core.protocols import PlanStore
    from ai_assistant.core.types import Goal
    from ai_assistant.testing.cancellation import SuspendedCall


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

    @contextlib.asynccontextmanager
    async def store_suspended_mid_write(self) -> AsyncIterator[tuple[PlanStore, SuspendedCall]]:
        """Park the first ``save_goal``'s worker thread inside the connection's turn.

        The suspension goes in ``_save_goal_sync``, i.e. inside ``async with
        self._lock`` and inside the ``to_thread`` the event loop cannot interrupt
        — which is exactly where ADR-0054's bug lived. Blocking there is what
        makes the case deterministic: left to run, a commit finishes in
        microseconds and whether the second caller arrives while the worker still
        holds the connection would be a race, so the invariant would be exercised
        only sometimes.

        Its own store on its own connection, not the ``store`` fixture's: the
        suspended worker is parked for the length of the case, and sharing would
        make an unrelated failure hang instead of fail.
        """
        realised = SqlitePlanStore(path=":memory:", now=_fixed_now)
        suspension = ThreadSuspension()
        original_save = realised._save_goal_sync
        armed = threading.Event()

        def blocking_save(goal: Goal) -> None:
            if not armed.is_set():  # the first worker only; later ones run free
                armed.set()
                suspension.hold()
            original_save(goal)

        realised._save_goal_sync = blocking_save  # type: ignore[method-assign]
        try:
            yield realised, suspension
        finally:
            suspension.release()
            # An implementation that released the connection early leaves a
            # worker still using it; closing under that is a native crash rather
            # than a reported failure, so give the worker a turn to unwind and
            # let the assertion above be the thing that speaks.
            await asyncio.sleep(0.05)
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


async def test_a_mutated_invalid_goal_is_refused_and_does_not_poison_reads(
    tmp_path: Path,
) -> None:
    """An input mutated past its validators is rejected at the write, not on read.

    ``Goal`` is mutable and does not validate on assignment, so a caller can build
    a valid goal and blank its ``statement`` before saving. The store revalidates
    before persisting, so the write raises ``PlanningError`` and nothing durable
    is written — the store cannot poison its own later reads (round-4 review).
    """
    path = tmp_path / "plans.db"
    store = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        tampered = _goal(goal_id="g-bad")
        tampered.statement = "   "  # blank once stripped — invalid, but assignment sticks

        with pytest.raises(PlanningError):
            await store.save_goal(tampered)

        assert await store.get_goal("g-bad") is None  # nothing was stored
        # And a good goal still writes and reads back — the store is not poisoned.
        await store.save_goal(_goal())
        stored = await store.get_goal("g1")
        assert stored is not None
        assert stored.statement == "relocate to Lisbon"
    finally:
        store.close()


async def test_a_mutated_invalid_plan_is_refused(tmp_path: Path) -> None:
    """The same write-time revalidation guards plans (round-4 review)."""
    path = tmp_path / "plans.db"
    store = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        await store.save_goal(_goal())
        tampered = _plan()
        tampered.__dict__["goal_id"] = "   "  # blank Identifier — invalid

        with pytest.raises(PlanningError):
            await store.save_plan(tampered)
        assert await store.get_plan("p1") is None
    finally:
        store.close()


async def test_an_id_less_constructed_goal_or_plan_is_a_planning_error(tmp_path: Path) -> None:
    """A model_construct'd instance missing its id fails as PlanningError, not AttributeError.

    The revalidation helper reads the id only via ``getattr`` when composing its
    message, so an id-less input stays inside this layer's error boundary rather
    than leaking a raw ``AttributeError`` (round-5 review).
    """
    from ai_assistant.core.types import ActionPlan, Goal  # noqa: PLC0415 — test-local

    path = tmp_path / "plans.db"
    store = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        with pytest.raises(PlanningError):
            await store.save_goal(Goal.model_construct())
        with pytest.raises(PlanningError):
            await store.save_plan(ActionPlan.model_construct())
    finally:
        store.close()


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
    be refused *before* ``goals``/``plans``/``executions`` are created — creating a
    table is a write, and the refusal must precede any write.
    """
    path = tmp_path / "plans.db"
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    raw.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '999')")
    raw.commit()
    raw.close()

    with pytest.raises(PlanningError, match="supports only version"):
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

    with pytest.raises(PlanningError, match="supports only version"):
        SqlitePlanStore(path=path, now=_fixed_now)


async def test_an_older_on_disk_schema_is_refused(tmp_path: Path) -> None:
    """An older, unmigrated schema is refused too — v1 is the only supported one.

    Accepting ``schema_version = '0'`` and letting ``CREATE TABLE IF NOT EXISTS``
    leave an incompatible table would construct successfully and only fail on the
    first query. There is no migration, so any version other than the current one
    is a fault to report at open (ADR-0049 §1).
    """
    path = tmp_path / "plans.db"
    SqlitePlanStore(path=path, now=_fixed_now).close()

    raw = sqlite3.connect(path)
    raw.execute("UPDATE meta SET value = '0' WHERE key = 'schema_version'")
    raw.commit()
    raw.close()

    with pytest.raises(PlanningError, match="supports only version"):
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
    insertion order — behaved oppositely: ``('1', '999')`` refused a supported
    schema, and ``('999', '1')`` **opened** on an unsupported one. Asserting the
    two messages are equal is what pins the order out of the answer.
    """
    ascending, descending = tmp_path / "asc.db", tmp_path / "desc.db"
    _hand_built_meta(ascending, (("schema_version", "1"), ("schema_version", "999")))
    _hand_built_meta(descending, (("schema_version", "999"), ("schema_version", "1")))

    assert _refusal(ascending, "2 schema_version rows") == _refusal(
        descending, "2 schema_version rows"
    )

    # And refused before any record table exists: ADR-0049 §1 puts the refusal
    # ahead of every write, and creating a table is a write.
    check = sqlite3.connect(ascending)
    try:
        tables = {
            row[0] for row in check.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        check.close()
    assert tables.isdisjoint({"goals", "plans", "executions"})


async def test_conflicting_exec_counter_rows_are_refused_whatever_their_order(
    tmp_path: Path,
) -> None:
    """An ambiguous durable ordinal is refused too, for a sharper reason (§3).

    ADR-0049 §3 makes ``exec_counter`` the durable half of execution-id
    non-reuse. A losing row here does not merely mislabel the file: it **rewinds
    the counter**, re-minting ordinals already handed out. Before the fix, a file
    recording ``7`` allocated ordinal 3 — an id ADR-0044 §1 promises is never
    issued twice, and the one a parked confirmation's recovery keys against.
    """
    low_first, high_first = tmp_path / "low.db", tmp_path / "high.db"
    rows = (("schema_version", "1"), ("exec_counter", "2"), ("exec_counter", "7"))
    _hand_built_meta(low_first, rows)
    _hand_built_meta(high_first, (rows[0], rows[2], rows[1]))

    assert _refusal(low_first, "2 exec_counter rows") == _refusal(high_first, "2 exec_counter rows")


async def test_a_duplicated_exec_counter_appearing_after_the_open_is_refused(
    tmp_path: Path,
) -> None:
    """The allocation read refuses on the same terms the open read does.

    The open validates one counter row; nothing stops an outside writer adding a
    second to a ``meta`` that has no primary key. Taking the first row at
    allocation would rewind the ordinal on a file whose open had validated the
    *other* row, so ``_next_ordinal`` re-reads defensively rather than trusting
    what the open established.
    """
    path = tmp_path / "plans.db"
    _hand_built_meta(path, (("schema_version", "1"), ("exec_counter", "7")))
    store = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        await store.save_goal(_goal())
        await store.save_plan(_plan())

        raw = sqlite3.connect(path)
        try:
            raw.execute("INSERT INTO meta(key, value) VALUES ('exec_counter', '2')")
            raw.commit()
        finally:
            raw.close()

        with pytest.raises(PlanningError, match="2 exec_counter rows"):
            await store.start_execution("p1")
    finally:
        store.close()


async def test_a_lost_exec_counter_is_refused_at_allocation(tmp_path: Path) -> None:
    """An allocator with no durable counter refuses rather than restarting at zero.

    Restarting would re-mint every ordinal the store has issued (ADR-0049 §3),
    and unpacking the empty ``fetchone()`` would have raised a raw ``TypeError``
    past this layer's boundary either way.
    """
    path = tmp_path / "plans.db"
    store = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        await store.save_goal(_goal())
        await store.save_plan(_plan())

        raw = sqlite3.connect(path)
        try:
            raw.execute("DELETE FROM meta WHERE key = 'exec_counter'")
            raw.commit()
        finally:
            raw.close()

        with pytest.raises(PlanningError, match="lost its exec_counter"):
            await store.start_execution("p1")
    finally:
        store.close()


@pytest.mark.parametrize("key", ["schema_version", "exec_counter", "exec_high_water"])
@pytest.mark.parametrize("value", [float("inf"), None, b"1", 1.5])
def test_an_untyped_meta_value_never_leaks_a_non_domain_error(
    tmp_path: Path, key: str, value: object
) -> None:
    """A ``value`` column with no declared type returns whatever was stored.

    ``int(float("inf"))`` raises ``OverflowError`` and ``int(None)`` a
    ``TypeError`` — neither a ``ValueError`` nor an ``AssistantError``, so both
    escaped the ``PlanningError`` boundary ``_setup`` exists to hold (ADR-0049
    §1). A stored ``NULL`` also has to read as a *present* row rather than an
    absent key, or the store would insert a second row beside it.
    """
    path = tmp_path / "plans.db"
    rows: list[tuple[str, object]] = [(key, value)]
    if key != "schema_version":
        rows.insert(0, ("schema_version", "1"))
    _hand_built_meta(path, rows, typed=False)

    with pytest.raises(PlanningError, match=f"non-numeric {key}"):
        SqlitePlanStore(path=path, now=_fixed_now)


# --- the ordinal only moves forward (issue #356, ADR-0064) ------------------


def _meta(path: Path, key: str) -> str | None:
    """The single value stored under ``key``, or ``None`` if there is no row."""
    raw = sqlite3.connect(path)
    try:
        row = raw.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    finally:
        raw.close()
    return None if row is None else str(row[0])


def _write_meta(path: Path, key: str, value: str) -> None:
    """Play the outside writer: set one ``meta`` row on a store this test opened."""
    raw = sqlite3.connect(path)
    try:
        raw.execute("UPDATE meta SET value = ? WHERE key = ?", (value, key))
        raw.commit()
    finally:
        raw.close()


def _tables(path: Path) -> set[str]:
    raw = sqlite3.connect(path)
    try:
        return {
            row[0] for row in raw.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        raw.close()


async def test_a_mid_session_counter_rollback_cannot_reissue_an_execution_id(
    tmp_path: Path,
) -> None:
    """Issue #356, reproduced: the rewind that hands out a byte-identical id.

    ``exec_counter`` is one mutable row and nothing checked it only moves forward.
    Rewinding it *mid-session* re-mints an ordinal already issued, and the rest of
    the id is constant for the life of one store object — the pid, and the nonce
    pinned here — so the id comes back **identical**, which ADR-0044 §1 makes
    normative it never is and a parked confirmation's recovery keys against.

    Against the code before ADR-0064 this exact sequence printed::

        first id            : p1-exec-1087458-N-1
        counter after clear : 1        (ADR-0049 §3: never reset)
        counter rolled back : 0
        after rollback      : p1-exec-1087458-N-1
        SAME ID REISSUED    : True

    ``clear()`` is what makes the reissue *silent*: it removes the earlier row, so
    the ``executions.id`` primary key no longer catches the duplicate. The counter
    surviving it is precisely the invariant being protected.
    """
    path = tmp_path / "plans.db"
    store = SqlitePlanStore(path=path, now=_fixed_now, incarnation_factory=lambda: "N")
    try:
        first = await _seed_and_start(store)
        assert first.endswith("-N-1")
        await store.clear()
        assert _meta(path, "exec_counter") == "1"  # never reset (ADR-0049 §3)
        assert _meta(path, "exec_high_water") == "1"  # and neither is its witness

        _write_meta(path, "exec_counter", "0")

        await store.save_goal(_goal())
        await store.save_plan(_plan())
        with pytest.raises(PlanningError, match="has been rewound outside this store"):
            await store.start_execution("p1")

        # And nothing was allocated: the refusal precedes the insert, so the
        # counter is still where the outside writer left it rather than one past.
        assert _meta(path, "exec_counter") == "0"
    finally:
        store.close()


async def test_a_rewound_counter_is_refused_at_open_before_any_record_table(
    tmp_path: Path,
) -> None:
    """The same disagreement refuses the *open*, ahead of every record table.

    ADR-0049 §1's posture: a store this code cannot vouch for is refused before it
    creates, reads or writes a record. A counter below its mark is a file whose
    ordinal is no longer the one this store maintained, so the open is where it is
    loud and diagnosable rather than at whatever allocation happens to hit it.
    """
    path = tmp_path / "plans.db"
    _hand_built_meta(
        path,
        (("schema_version", "1"), ("exec_counter", "3"), ("exec_high_water", "9")),
    )

    with pytest.raises(PlanningError, match="exec_counter=3, below the exec_high_water=9"):
        SqlitePlanStore(path=path, now=_fixed_now)

    assert _tables(path).isdisjoint({"goals", "plans", "executions"})


async def test_a_whole_file_restore_rolls_both_markers_back_and_opens(tmp_path: Path) -> None:
    """The trade that makes the refusal acceptable: an ordinary restore still opens.

    The mark lives in the **same ``meta`` table** as the counter, so restoring the
    database file moves them together and they still agree. That is what keeps
    ADR-0064's refusal aimed at a hand-edit or a partial corruption rather than at
    backup/restore — and the restore also removes the executions that used the
    higher ordinals, so re-issuing those *ordinals* collides with nothing. The ids
    still differ: a reopened store mints a fresh nonce (ADR-0049 §3).
    """
    path, backup = tmp_path / "plans.db", tmp_path / "plans.db.bak"

    first = SqlitePlanStore(path=path, now=_fixed_now)
    await _seed_and_start(first)
    first.close()
    shutil.copy(path, backup)  # the backup: counter and mark both at 1

    second = SqlitePlanStore(path=path, now=_fixed_now)
    later_ids = [(await second.start_execution("p1")).id for _ in range(2)]
    second.close()
    assert _meta(path, "exec_counter") == "3"

    shutil.copy(backup, path)  # the restore
    assert _meta(path, "exec_counter") == "1"
    assert _meta(path, "exec_high_water") == "1"

    restored = SqlitePlanStore(path=path, now=_fixed_now)  # opens: the two agree
    try:
        # The executions that held ordinals 2 and 3 went back with the file, so
        # the ordinal is free again — and the new id differs from theirs anyway.
        for erased in later_ids:
            assert await restored.get_execution(erased) is None
        fresh = (await restored.start_execution("p1")).id
        assert fresh.endswith("-2")
        assert fresh not in later_ids
    finally:
        restored.close()


async def test_a_store_predating_the_mark_is_backfilled_not_refused(tmp_path: Path) -> None:
    """A database with a counter and no mark opens, and is stamped from its counter.

    Every store written before ADR-0064 is in this state. Refusing them would make
    the durable record unopenable by the code that wrote it, and the stamp is
    sound rather than merely lenient: the pre-ADR-0064 counter *was* the highest
    ordinal that file had issued, so recording it asserts nothing new.
    """
    path = tmp_path / "plans.db"
    _hand_built_meta(path, (("schema_version", "1"), ("exec_counter", "7")))

    store = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        assert _meta(path, "exec_high_water") == "7"
        # And the counter is carried forward, not restarted: ordinal 8 is next.
        assert (await _seed_and_start(store)).endswith("-8")
        assert _meta(path, "exec_high_water") == "8"
    finally:
        store.close()


async def test_deleting_the_mark_does_not_launder_a_rewound_counter(tmp_path: Path) -> None:
    """The backfill must not be a way *around* the invariant it exists to preserve.

    A deleted mark is indistinguishable from one that was never written, so a
    two-row tamper — drop ``exec_high_water``, lower ``exec_counter`` — would
    otherwise be stamped at the reopen as a fresh, agreeing pair. The executions
    that survive are the witness: each records the ordinal it was allocated with,
    and ``MAX(created_seq) <= exec_counter`` holds for every file this store wrote
    (``clear``/``delete_goal`` only remove rows).

    Before this check the reopen **succeeded**, and left the table holding two
    executions at ``created_seq = 1`` — so ``active_executions``/``export``'s
    oldest-first ordering silently stopped being an order::

        created_seq: [("…-A-1", 1), ("…-B-1", 1), ("…-A-2", 2), ("…-A-3", 3)]

    No execution *id* was reused there: the reopened store mints a fresh nonce,
    which is exactly the job ADR-0049 §3 assigns it. The durable ordering is the
    casualty, and it is enough.
    """
    path = tmp_path / "plans.db"
    first = SqlitePlanStore(path=path, now=_fixed_now, incarnation_factory=lambda: "A")
    await first.save_goal(_goal())
    await first.save_plan(_plan())
    for _ in range(3):
        await first.start_execution("p1")
    first.close()

    raw = sqlite3.connect(path)
    try:
        raw.execute("DELETE FROM meta WHERE key = 'exec_high_water'")
        raw.execute("UPDATE meta SET value = '0' WHERE key = 'exec_counter'")
        raw.commit()
    finally:
        raw.close()

    with pytest.raises(PlanningError, match="still holds an execution allocated at created_seq=3"):
        SqlitePlanStore(path=path, now=_fixed_now, incarnation_factory=lambda: "B")

    assert _meta(path, "exec_high_water") is None  # the refusal wrote nothing


async def test_a_deleted_mark_is_rebuilt_when_the_records_agree(tmp_path: Path) -> None:
    """The corroboration refuses a rewind, not a missing mark on its own.

    The same file with only the mark removed — the counter untouched — is a store
    whose records are consistent with what it says, so it is re-stamped and the
    ordinal carries on. This is what keeps the check above from being a second,
    stricter refusal than the one ADR-0064 §4 argues for.
    """
    path = tmp_path / "plans.db"
    first = SqlitePlanStore(path=path, now=_fixed_now)
    await first.save_goal(_goal())
    await first.save_plan(_plan())
    for _ in range(3):
        await first.start_execution("p1")
    first.close()

    raw = sqlite3.connect(path)
    try:
        raw.execute("DELETE FROM meta WHERE key = 'exec_high_water'")
        raw.commit()
    finally:
        raw.close()

    reopened = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        assert _meta(path, "exec_high_water") == "3"
        assert (await reopened.start_execution("p1")).id.endswith("-4")
    finally:
        reopened.close()


async def test_the_mark_is_not_stamped_when_the_open_fails(tmp_path: Path) -> None:
    """The backfill lands after the record schema, inside the one transaction.

    Stamping before the create would leave a database labelled with a mark an open
    that then failed never established — the failure mode ``SqliteAuditTrail``
    avoids the same way (#346). Here the create fails part-way: SQLite shares one
    namespace across tables and indexes, so an index already named ``plans`` makes
    ``CREATE TABLE IF NOT EXISTS plans`` an error rather than a no-op — after
    ``goals`` has been created.
    """
    path = tmp_path / "plans.db"
    _hand_built_meta(path, (("schema_version", "1"), ("exec_counter", "7")))
    raw = sqlite3.connect(path)
    try:
        raw.execute("CREATE INDEX plans ON meta(key)")
        raw.commit()
    finally:
        raw.close()

    with pytest.raises(PlanningError, match="failed to initialise the plan store"):
        SqlitePlanStore(path=path, now=_fixed_now)

    assert _meta(path, "exec_high_water") is None
    assert _meta(path, "exec_counter") == "7"
    assert "goals" not in _tables(path)  # the half-built schema rolled back with it


async def test_a_mark_below_the_counter_is_promoted_at_open_not_refused(tmp_path: Path) -> None:
    """A lagging mark is levelled up, not refused — and levelled *at the open*.

    A mark below the counter — what an older build advancing the counter without
    the witness would leave — means no ordinal has been handed out twice, so there
    is nothing to refuse. Promoting it is not a repair either: the counter is the
    highest ordinal issued, so that is what the high water is.

    Doing it eagerly is what makes the allocation-time test sound for the rest of
    the session. Left lagging, the two would agree again as soon as an outside
    writer rewound the counter down to meet the stale mark, and the allocation
    would pass a rewind straight through — so the second half of this test rewinds
    mid-session and requires the refusal.
    """
    path = tmp_path / "plans.db"
    seeded = SqlitePlanStore(path=path, now=_fixed_now)
    await _seed_and_start(seeded)
    seeded.close()

    _write_meta(path, "exec_counter", "9")  # advanced without its witness

    store = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        assert _meta(path, "exec_high_water") == "9"  # levelled by the open itself
        assert (await store.start_execution("p1")).id.endswith("-10")
        assert _meta(path, "exec_high_water") == "10"

        _write_meta(path, "exec_counter", "5")
        with pytest.raises(PlanningError, match="has been rewound outside this store"):
            await store.start_execution("p1")
    finally:
        store.close()


async def test_a_rewind_down_to_a_lagging_mark_is_refused_by_the_records(
    tmp_path: Path,
) -> None:
    """A stale mark cannot vouch for a counter rewound down to meet it.

    Adversarial review, round 2. The ``counter >= mark`` test passes trivially when
    both are 1 — but the file still holds executions at ``created_seq`` 2 and 3, so
    the next allocation re-issues ordinal 2. Reproduced against the previous commit,
    which opened the store happily and left::

        created_seq: [("…-A-1", 1), ("…-A-2", 2), ("…-B-2", 2), ("…-A-3", 3)]

    Two rows at 2, so ``active_executions``/``export`` stopped being an order. The
    records are what close it: ``MAX(created_seq) <= exec_counter`` holds for every
    file this store wrote.
    """
    path = tmp_path / "plans.db"
    first = SqlitePlanStore(path=path, now=_fixed_now, incarnation_factory=lambda: "A")
    await first.save_goal(_goal())
    await first.save_plan(_plan())
    for _ in range(3):
        await first.start_execution("p1")
    first.close()

    _write_meta(path, "exec_high_water", "1")  # an older build left the mark behind
    _write_meta(path, "exec_counter", "1")  # then an outside writer rewound to it

    with pytest.raises(PlanningError, match="still holds an execution allocated at created_seq=3"):
        SqlitePlanStore(path=path, now=_fixed_now, incarnation_factory=lambda: "B")


async def test_two_executions_cannot_share_a_created_seq(tmp_path: Path) -> None:
    """The oldest-first ordering is a property of the schema, not of the counter alone.

    Adversarial review, round 3: a *concurrently running* older build can advance
    the counter without the mark **after** this store has opened, so a subsequent
    one-row rewind leaves counter and mark agreeing at a value the file has already
    passed. The allocation-time mark test cannot see that, and re-scanning
    ``executions`` on every ``start_execution`` would put a full scan on the hot
    path. The uniqueness ``created_seq`` already has by construction is declared
    instead, so a second row at one ordinal is refused whatever route it arrives by
    — the same relationship the enforced foreign keys have to ``save_plan``'s
    app-level orphan check (ADR-0049 §1).

    Staged exactly as the finding describes: the store is open at counter 3, an
    outside writer plays the older build (a row at ``created_seq = 4``, counter
    advanced, mark untouched), then a reset script puts the counter back to 3.
    """
    path = tmp_path / "plans.db"
    store = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        await store.save_goal(_goal())
        await store.save_plan(_plan())
        for _ in range(3):
            await store.start_execution("p1")

        raw = sqlite3.connect(path)
        try:
            data = raw.execute("SELECT data FROM executions LIMIT 1").fetchone()[0]
            raw.execute(
                "INSERT INTO executions(id, plan_id, version, active, created_seq, data) "
                "VALUES ('older-build-4', 'p1', 1, 1, 4, ?)",
                (data,),
            )
            # The older build advances only the counter; the mark stays at 3.
            raw.execute("UPDATE meta SET value = '4' WHERE key = 'exec_counter'")
            # Then the reset script puts it back, so counter and mark agree again.
            raw.execute("UPDATE meta SET value = '3' WHERE key = 'exec_counter'")
            raw.commit()
        finally:
            raw.close()

        with pytest.raises(PlanningError, match="UNIQUE constraint failed"):
            await store.start_execution("p1")
    finally:
        store.close()

    seqs = [row[0] for row in sqlite3.connect(path).execute("SELECT created_seq FROM executions")]
    assert sorted(seqs) == [1, 2, 3, 4]  # no duplicate survived the refusal


async def test_a_file_already_holding_duplicate_ordinals_is_refused_at_open(
    tmp_path: Path,
) -> None:
    """A database that already lost the ordering is refused, not carried forward.

    The unique index is created at every open, so a file whose ``created_seq``
    duplicates predate this code cannot be opened — ADR-0049 §1's posture, and the
    only honest answer: nothing here can decide which of two rows at one ordinal
    came first.
    """
    path = tmp_path / "plans.db"
    store = SqlitePlanStore(path=path, now=_fixed_now)
    await store.save_goal(_goal())
    await store.save_plan(_plan())
    await store.start_execution("p1")
    store.close()

    raw = sqlite3.connect(path)
    try:
        data = raw.execute("SELECT data FROM executions LIMIT 1").fetchone()[0]
        raw.execute("DROP INDEX executions_created_seq")
        raw.execute(
            "INSERT INTO executions(id, plan_id, version, active, created_seq, data) "
            "VALUES ('dupe-1', 'p1', 1, 1, 1, ?)",
            (data,),
        )
        raw.commit()
    finally:
        raw.close()

    with pytest.raises(PlanningError, match="failed to initialise the plan store"):
        SqlitePlanStore(path=path, now=_fixed_now)


@pytest.mark.parametrize(
    "collision",
    [
        pytest.param(
            "CREATE INDEX executions_created_seq ON executions(created_seq)", id="not-unique"
        ),
        pytest.param(
            "CREATE UNIQUE INDEX executions_created_seq ON executions(id)", id="wrong-column"
        ),
        pytest.param(
            "CREATE UNIQUE INDEX executions_created_seq ON executions(created_seq) "
            "WHERE active = 1",
            id="partial",
        ),
    ],
)
async def test_an_index_that_only_shares_the_name_is_refused(
    tmp_path: Path, collision: str
) -> None:
    """``IF NOT EXISTS`` keys on the name, so the name is not evidence about the object.

    Adversarial review, round 4. A pre-existing index *called*
    ``executions_created_seq`` but shaped differently makes the creation a silent
    no-op, leaving no uniqueness constraint while every message in the module
    claims one — the same fail-open issue #349 found in a ``meta`` table this code
    did not shape. Verified against the previous commit: with a same-name
    non-unique index in place, two rows at ``created_seq = 1`` inserted cleanly.

    So the index is read back and required to be unique, total, and over exactly
    ``created_seq``.
    """
    path = tmp_path / "plans.db"
    raw = sqlite3.connect(path)
    try:
        raw.execute(
            "CREATE TABLE executions("
            "id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, version INTEGER NOT NULL, "
            "active INTEGER NOT NULL, created_seq INTEGER NOT NULL, data TEXT NOT NULL)"
        )
        raw.execute(collision)
        raw.commit()
    finally:
        raw.close()

    with pytest.raises(PlanningError, match="not a unique index over executions"):
        SqlitePlanStore(path=path, now=_fixed_now)


async def test_a_lost_high_water_mark_is_refused_at_allocation(tmp_path: Path) -> None:
    """An allocator that cannot witness its counter refuses, like one with no counter.

    Minting on an unwitnessed counter is minting on a value that may already have
    been rewound — the exact state ADR-0064 exists to detect — so the missing mark
    is a corrupt store, not a mark to silently re-create from whatever is there.
    """
    path = tmp_path / "plans.db"
    store = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        await store.save_goal(_goal())
        await store.save_plan(_plan())

        raw = sqlite3.connect(path)
        try:
            raw.execute("DELETE FROM meta WHERE key = 'exec_high_water'")
            raw.commit()
        finally:
            raw.close()

        with pytest.raises(PlanningError, match="lost its exec_high_water"):
            await store.start_execution("p1")
    finally:
        store.close()


async def test_a_duplicated_high_water_row_appearing_after_the_open_is_refused(
    tmp_path: Path,
) -> None:
    """The mark is read on the same terms as the counter, at both sites (#349).

    ``meta``'s primary key does not hold for a table this code did not create, so
    the mark can go ambiguous after the open validated it. Resolving that by row
    order would let a low sibling row wave a rewound counter through.
    """
    path = tmp_path / "plans.db"
    _hand_built_meta(
        path,
        (("schema_version", "1"), ("exec_counter", "7"), ("exec_high_water", "7")),
    )
    store = SqlitePlanStore(path=path, now=_fixed_now)
    try:
        await store.save_goal(_goal())
        await store.save_plan(_plan())

        raw = sqlite3.connect(path)
        try:
            raw.execute("INSERT INTO meta(key, value) VALUES ('exec_high_water', '2')")
            raw.commit()
        finally:
            raw.close()

        with pytest.raises(PlanningError, match="2 exec_high_water rows"):
            await store.start_execution("p1")
    finally:
        store.close()


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


async def _spin(iterations: int = 50) -> None:
    """Yield to the event loop repeatedly so a pending cancellation can unwind."""
    for _ in range(iterations):
        await asyncio.sleep(0)


@pytest.mark.integration
async def test_cancelling_a_write_does_not_release_the_connection(tmp_path: Path) -> None:
    """A cancelled write must not free the lock while its worker thread runs (ADR-0054).

    ``asyncio.to_thread`` cannot interrupt a running worker, so a cancellation that
    unwound the awaiting coroutine here would release the connection lock while the
    worker was still inside its ``BEGIN IMMEDIATE`` transaction on the shared
    connection. This blocks a worker inside ``save_goal``, cancels the awaiting
    task, and asserts the lock stays held until the worker finishes, then that a
    second write lands on an intact connection.
    """
    store = SqlitePlanStore(path=tmp_path / "cancel.db", now=_fixed_now)
    entered = threading.Event()
    release = threading.Event()
    original_save = store._save_goal_sync

    def blocking_save(goal: Goal) -> None:
        if not entered.is_set():
            entered.set()
            if not release.wait(timeout=5):  # pragma: no cover - only on a hang
                msg = "the blocked worker was never released"
                raise AssertionError(msg)
        original_save(goal)

    store._save_goal_sync = blocking_save  # type: ignore[method-assign]
    try:
        first = asyncio.ensure_future(store.save_goal(_goal("g1")))
        assert await asyncio.to_thread(entered.wait, 5), "worker never entered"
        assert store._lock.locked()

        first.cancel()
        await _spin()
        # The invariant: cancellation did NOT release the lock — the worker is
        # still running, so the connection is still exclusively held.
        assert store._lock.locked()

        second = asyncio.ensure_future(store.save_goal(_goal("g2")))
        await _spin()
        assert not second.done()
        assert store._lock.locked()

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        await second  # must not raise on a concurrently-used connection

        # The connection is intact: the deferred-to-completion first write
        # committed, and the second landed cleanly on top of it.
        assert await store.get_goal("g1") is not None
        assert await store.get_goal("g2") is not None
        assert not store._lock.locked()
    finally:
        release.set()
        store.close()
