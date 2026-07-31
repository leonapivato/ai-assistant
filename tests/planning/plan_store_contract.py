"""Shared conformance suite for the PlanStore Protocol (ADR-0014).

Every ``PlanStore`` implementation must pass this suite (CONTRIBUTING, "Protocol
conformance suites"). A concrete test subclasses :class:`PlanStoreContract` and
overrides the ``store`` fixture.

This suite matters more than most: `InMemoryPlanStore` and `FakePlanStore`
re-implement the ADR-0014 §4 transition graph independently — the fake cannot
import the subsystem it stands in for — so this is what stops the two drifting.
It asserts only behaviour the *contract* guarantees, never how a given store
keys its ids.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

import pytest
from pydantic import ValidationError

from ai_assistant.core.errors import (
    ActiveExecutionError,
    IllegalTransitionError,
    PlanningError,
    RetriesExhaustedError,
    StaleExecutionError,
)
from ai_assistant.core.types import (
    ActionPlan,
    Goal,
    GoalStatus,
    MemorySource,
    PlanStep,
    Provenance,
    SkipReason,
    StepFailure,
    StepStatus,
    StepTransition,
    ToolFailureKind,
)
from ai_assistant.testing.cancellation import settle

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from contextlib import AbstractAsyncContextManager

    from ai_assistant.core.protocols import PlanStore
    from ai_assistant.core.types import ExecutionState
    from ai_assistant.testing.cancellation import SuspendedMidWrite

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


#: What a failure of the cancellation case below means, in one place: every
#: assertion in it is the same invariant seen from a different side.
_RELEASED_EARLY = (
    "the cancelled call released its resource while its own work was still "
    "running, so a second caller reached it concurrently"
)


def _goal(goal_id: str = "g1") -> Goal:
    return Goal(
        id=goal_id,
        statement="relocate to Lisbon",
        provenance=Provenance(
            source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_WHEN
        ),
        created_at=_WHEN,
    )


def _plan(plan_id: str = "p1", goal_id: str = "g1", *, steps: int = 1) -> ActionPlan:
    return ActionPlan(
        id=plan_id,
        goal_id=goal_id,
        steps=tuple(
            PlanStep(id=f"s{index}", intent=f"step {index}", capability="send_email")
            for index in range(1, steps + 1)
        ),
        created_at=_WHEN,
    )


def _claim(state: ExecutionState, step_id: str = "s1") -> StepTransition:
    """The transition that claims a step — bound tool plus authorisation."""
    return StepTransition(
        execution_id=state.id,
        step_id=step_id,
        to_status=StepStatus.RUNNING,
        expected_version=state.version,
        bound_tool="smtp",
        approval_ref="perm-1",
    )


class _CancellationOp(Protocol):
    """One locked ``PlanStore`` operation the ADR-0060 case drives (#370, #397).

    Each :attr:`name` selects a distinct ``async with self._lock:
    _run_to_completion(...)`` site; the suite runs the same
    cancelled-first / concurrent-second scenario against every one, so a
    regression reintroduced at any single site is caught rather than only at
    ``save_goal``. :meth:`first` and :meth:`second` act on *independent* subjects,
    so the concurrent second succeeds whatever the cancelled first's
    indeterminate effect turns out to be — which matters most for
    ``commit_transition``, whose compare-and-swap would otherwise couple them.

    **Reads are operations too** (#397). ADR-0060 §3 binds any method that acquires
    the resource, and every locked read here holds the connection lock around its
    own worker-thread SQL — so a regression replacing one read's
    ``_run_to_completion`` with a bare ``to_thread`` would hand the connection to a
    concurrent caller while that read's worker still used it, and every write case
    would still pass.
    """

    name: str

    async def prepare(self, store: PlanStore) -> None:
        """Establish anything the operation needs before it can run."""
        ...

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """The call the case suspends inside the resource and then cancels."""
        ...

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """The concurrent call barred from the resource until the first is done."""
        ...

    async def verify(self, store: PlanStore) -> None:
        """Assert the resource survived: the second call is whole and reads work."""
        ...


class _SaveGoalOp:
    """The ``save_goal`` upsert — ADR-0060's original subject."""

    name = "save_goal"

    async def prepare(self, store: PlanStore) -> None:
        """No preconditions."""

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Save the goal whose write is cancelled."""
        return store.save_goal(_goal("cancel-1"))

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Save an independent goal concurrently."""
        return store.save_goal(_goal("cancel-2"))

    async def verify(self, store: PlanStore) -> None:
        """The second goal is durable; the first is absent-or-whole; reads work."""
        assert await store.get_goal("cancel-2") == _goal("cancel-2")
        cancelled = await store.get_goal("cancel-1")
        assert cancelled is None or cancelled == _goal("cancel-1")
        assert {goal.id for goal in (await store.export()).goals} >= {"cancel-2"}


class _SavePlanOp:
    """The ``save_plan`` write, on two plans under two pre-saved goals."""

    name = "save_plan"

    async def prepare(self, store: PlanStore) -> None:
        """Save the goals the two plans hang off (``save_plan`` needs them)."""
        await store.save_goal(_goal("gA"))
        await store.save_goal(_goal("gB"))

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Save the plan whose write is cancelled."""
        return store.save_plan(_plan("pA", "gA"))

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Save an independent plan concurrently."""
        return store.save_plan(_plan("pB", "gB"))

    async def verify(self, store: PlanStore) -> None:
        """The second plan is durable; the cancelled one is absent-or-whole."""
        assert await store.get_plan("pB") == _plan("pB", "gB")
        cancelled = await store.get_plan("pA")
        assert cancelled is None or cancelled == _plan("pA", "gA")


class _StartExecutionOp:
    """The ``start_execution`` write, on two independent pre-saved plans."""

    name = "start_execution"

    async def prepare(self, store: PlanStore) -> None:
        """Save two goal+plan pairs so each execution has its own plan."""
        await store.save_goal(_goal("gA"))
        await store.save_plan(_plan("pA", "gA"))
        await store.save_goal(_goal("gB"))
        await store.save_plan(_plan("pB", "gB"))

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Start the execution whose write is cancelled."""
        return store.start_execution("pA")

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Start an independent execution concurrently."""
        return store.start_execution("pB")

    async def verify(self, store: PlanStore) -> None:
        """The second execution is live and readable."""
        assert "pB" in {state.plan_id for state in await store.active_executions()}


class _CommitTransitionOp:
    """The ``commit_transition`` compare-and-swap (#370, priority 2).

    The two calls claim a step on *different* executions, so each swap turns on
    its own execution's version and the concurrent second is decided
    independently of the cancelled first — which, shielded, may itself commit.
    """

    name = "commit_transition"

    def __init__(self) -> None:
        """Hold the two started executions the transitions claim against."""
        self._state_a: ExecutionState
        self._state_b: ExecutionState

    async def prepare(self, store: PlanStore) -> None:
        """Start two independent executions and remember their versions."""
        await store.save_goal(_goal("gA"))
        await store.save_plan(_plan("pA", "gA"))
        self._state_a = await store.start_execution("pA")
        await store.save_goal(_goal("gB"))
        await store.save_plan(_plan("pB", "gB"))
        self._state_b = await store.start_execution("pB")

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Claim a step on execution A — the swap that is cancelled."""
        return store.commit_transition(_claim(self._state_a))

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Claim a step on execution B concurrently."""
        return store.commit_transition(_claim(self._state_b))

    async def verify(self, store: PlanStore) -> None:
        """Execution B took its claim; the store still serves reads."""
        state = await store.get_execution(self._state_b.id)
        assert state is not None
        assert state.version > self._state_b.version


class _DeleteGoalOp:
    """The ``delete_goal`` write, on two independent pre-saved goals."""

    name = "delete_goal"

    async def prepare(self, store: PlanStore) -> None:
        """Save the two goals the calls delete."""
        await store.save_goal(_goal("gA"))
        await store.save_goal(_goal("gB"))

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Delete goal A — the call that is cancelled."""
        return store.delete_goal("gA")

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Delete goal B concurrently."""
        return store.delete_goal("gB")

    async def verify(self, store: PlanStore) -> None:
        """Goal B is gone; the store still serves reads."""
        assert await store.get_goal("gB") is None


class _ClearOp:
    """The ``clear`` write. No live step, so it is not refused (ADR-0014)."""

    name = "clear"

    async def prepare(self, store: PlanStore) -> None:
        """A goal to remove, so ``clear`` does real connection work."""
        await store.save_goal(_goal("gA"))

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Clear the store — the call that is cancelled."""
        return store.clear()

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Clear again concurrently."""
        return store.clear()

    async def verify(self, store: PlanStore) -> None:
        """The store is empty and still serves reads."""
        assert not (await store.export()).goals


class _ReadOp:
    """A locked ``PlanStore`` read, driven against a store seeded the same way (#397).

    The two calls are the *same* read against independent subjects, because what
    distinguishes a read op is its lock site and both calls have to enter it.
    Nothing is asserted about the cancelled read's answer — it has none, its task
    was cancelled — so :meth:`verify` pins the state the second call had to see,
    re-read once the scenario is over.
    """

    name = ""

    def __init__(self) -> None:
        """Hold the executions the read ops below address."""
        self._state_a: ExecutionState
        self._state_b: ExecutionState

    async def prepare(self, store: PlanStore) -> None:
        """Seed two independent goal/plan/execution chains for the reads to answer from."""
        await store.save_goal(_goal("gA"))
        await store.save_plan(_plan("pA", "gA"))
        self._state_a = await store.start_execution("pA")
        await store.save_goal(_goal("gB"))
        await store.save_plan(_plan("pB", "gB"))
        self._state_b = await store.start_execution("pB")

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """The read the case suspends inside the resource and then cancels."""
        raise NotImplementedError

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """The concurrent read barred from the resource until the first is done."""
        raise NotImplementedError

    async def verify(self, store: PlanStore) -> None:
        """A read cancelled mid-flight leaves the store whole and still readable."""
        assert await store.get_goal("gA") == _goal("gA")
        assert await store.get_plan("pB") == _plan("pB", "gB")
        exported = await store.export()
        assert {goal.id for goal in exported.goals} == {"gA", "gB"}


class _GetGoalOp(_ReadOp):
    """``get_goal`` — one row by id, under the connection lock."""

    name = "get_goal"

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read goal A — the call that is cancelled."""
        return store.get_goal("gA")

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read goal B concurrently."""
        return store.get_goal("gB")


class _GetPlanOp(_ReadOp):
    """``get_plan`` — its own lock site, though it shares a row reader with the others."""

    name = "get_plan"

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read plan A — the call that is cancelled."""
        return store.get_plan("pA")

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read plan B concurrently."""
        return store.get_plan("pB")


class _GetExecutionOp(_ReadOp):
    """``get_execution`` — the third ``async with self._lock`` around a row read."""

    name = "get_execution"

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read execution A — the call that is cancelled."""
        return store.get_execution(self._state_a.id)

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read execution B concurrently."""
        return store.get_execution(self._state_b.id)


class _ActiveExecutionsOp(_ReadOp):
    """``active_executions`` — the outstanding-work scan, its own lock site."""

    name = "active_executions"

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Scan for live executions — the call that is cancelled."""
        return store.active_executions()

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Scan again concurrently."""
        return store.active_executions()


class _ExportOp(_ReadOp):
    """``export`` — the whole-store read, its own lock site."""

    name = "export"

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Export everything — the call that is cancelled."""
        return store.export()

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Export again concurrently."""
        return store.export()


#: Every locked ``PlanStore`` operation ADR-0060's case is run against: each is a
#: distinct lock site with its own ``_run_to_completion`` call. The writes came
#: first (#370); the reads are the same invariant on the other half of the surface
#: (#397), since ADR-0060 §3 binds any method that acquires the resource rather
#: than any method that mutates.
_CANCELLATION_OPS: tuple[Callable[[], _CancellationOp], ...] = (
    _SaveGoalOp,
    _SavePlanOp,
    _StartExecutionOp,
    _CommitTransitionOp,
    _DeleteGoalOp,
    _ClearOp,
    _GetGoalOp,
    _GetPlanOp,
    _GetExecutionOp,
    _ActiveExecutionsOp,
    _ExportOp,
)


class PlanStoreContract:
    """Behaviour every ``PlanStore`` implementation must exhibit."""

    @pytest.fixture
    def store(self) -> PlanStore:
        """Return an empty store under test."""
        raise NotImplementedError

    async def _started(self, store: PlanStore, *, steps: int = 1) -> ExecutionState:
        await store.save_goal(_goal())
        await store.save_plan(_plan(steps=steps))
        return await store.start_execution("p1")

    # --- goals and plans ------------------------------------------------

    async def test_saves_and_reads_back_a_goal(self, store: PlanStore) -> None:
        await store.save_goal(_goal())
        stored = await store.get_goal("g1")
        assert stored is not None
        assert stored.statement == "relocate to Lisbon"

    async def test_missing_goal_reads_as_none(self, store: PlanStore) -> None:
        assert await store.get_goal("nope") is None

    async def test_saving_a_goal_twice_upserts(self, store: PlanStore) -> None:
        await store.save_goal(_goal())
        await store.save_goal(_goal())
        export = await store.export()
        assert len(export.goals) == 1

    async def test_a_plan_needs_its_goal_to_exist(self, store: PlanStore) -> None:
        """Refusing the orphan here is what lets export promise integrity."""
        with pytest.raises(PlanningError):
            await store.save_plan(_plan(goal_id="ghost"))

    async def test_execution_needs_its_plan_to_exist(self, store: PlanStore) -> None:
        with pytest.raises(PlanningError):
            await store.start_execution("ghost")

    async def test_a_plan_id_cannot_be_reused_for_a_different_plan(self, store: PlanStore) -> None:
        """Replacing a plan would rewrite the record of what was decided.

        Worse, an execution already under way refers to its plan by id, so the
        swap would pair real step history with steps that were never planned.
        Re-planning takes a new id (ADR-0014 §2).
        """
        await store.save_goal(_goal())
        await store.save_plan(_plan(steps=1))
        await store.start_execution("p1")

        with pytest.raises(PlanningError):
            await store.save_plan(_plan(steps=2))

        stored = await store.get_plan("p1")
        assert stored is not None
        assert [step.id for step in stored.steps] == ["s1"]

    async def test_a_goals_objective_cannot_be_rewritten(self, store: PlanStore) -> None:
        """Otherwise plans already recorded would come to describe a new objective."""
        await store.save_goal(_goal())
        await store.save_plan(_plan())

        rewritten = _goal().model_copy(update={"statement": "delete all mail"})
        with pytest.raises(PlanningError):
            await store.save_goal(rewritten)

        stored = await store.get_goal("g1")
        assert stored is not None
        assert stored.statement == "relocate to Lisbon"

    async def test_a_goals_status_may_still_change(self, store: PlanStore) -> None:
        """Identity is fixed; a goal's progress is exactly what should move."""
        await store.save_goal(_goal())
        await store.save_goal(_goal().model_copy(update={"status": GoalStatus.ACHIEVED}))

        stored = await store.get_goal("g1")
        assert stored is not None
        assert stored.status is GoalStatus.ACHIEVED

    async def test_saving_an_identical_plan_again_is_idempotent(self, store: PlanStore) -> None:
        """A retry must not be punished — only a *differing* plan is a conflict."""
        await store.save_goal(_goal())
        await store.save_plan(_plan())
        await store.save_plan(_plan())

        export = await store.export()
        assert len(export.plans) == 1

    # --- starting an execution ------------------------------------------

    async def test_execution_starts_derived_from_the_plan(self, store: PlanStore) -> None:
        state = await self._started(store, steps=2)
        assert state.plan_id == "p1"
        assert [step.step_id for step in state.steps] == ["s1", "s2"]
        assert all(step.status is StepStatus.PENDING for step in state.steps)
        assert state.version == 0

    # --- the transition graph -------------------------------------------

    async def test_claiming_a_step_advances_it(self, store: PlanStore) -> None:
        state = await self._started(store)
        updated = await store.commit_transition(_claim(state))
        step = updated.step("s1")
        assert step is not None
        assert step.status is StepStatus.RUNNING
        assert step.attempts == 1
        assert step.started_at is not None

    async def test_a_write_bumps_the_version(self, store: PlanStore) -> None:
        state = await self._started(store)
        updated = await store.commit_transition(_claim(state))
        assert updated.version == state.version + 1

    async def test_illegal_transition_is_rejected(self, store: PlanStore) -> None:
        """PENDING to SUCCEEDED skips the claim, so it must not be persistable."""
        state = await self._started(store)
        with pytest.raises(IllegalTransitionError):
            await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="s1",
                    to_status=StepStatus.SUCCEEDED,
                    expected_version=state.version,
                )
            )

    async def test_running_without_authorisation_is_rejected(self, store: PlanStore) -> None:
        """ADR-0004 §7: nothing executes without a decision to point at."""
        state = await self._started(store)
        with pytest.raises(IllegalTransitionError):
            await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="s1",
                    to_status=StepStatus.RUNNING,
                    expected_version=state.version,
                    bound_tool="smtp",
                )
            )

    async def test_approval_cannot_be_sought_without_a_tool_to_approve(
        self, store: PlanStore
    ) -> None:
        """Consent is to a specific action, not to an unspecified one."""
        state = await self._started(store)
        with pytest.raises(IllegalTransitionError):
            await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="s1",
                    to_status=StepStatus.AWAITING_APPROVAL,
                    expected_version=state.version,
                )
            )

    async def test_a_never_queued_step_can_be_denied_in_one_transition(
        self, store: PlanStore
    ) -> None:
        """A policy refusing outright is a denial, though nobody was asked.

        ADR-0041 §1: the record is truthful because it names the decision that
        refused it, not because a confirmation was put to anyone.

        The version count is asserted, not incidental. A store that satisfied
        this request by durably writing `AWAITING_APPROVAL` and then `SKIPPED`
        would return an indistinguishable final state while reopening the very
        window ADR-0041 closes — a failure between the two writes strands the
        step (#257). One commit is the obligation; the disposition is not.
        """
        state = await self._started(store)
        before = state.version
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.SKIPPED,
                expected_version=state.version,
                skip_reason=SkipReason.APPROVAL_DENIED,
                approval_ref="perm-1",
            )
        )

        assert state.version == before + 1

        # Read back rather than trust the return value: a denial that is only
        # in the returned object is exactly the stranding this edge exists to
        # prevent, since a restart would resurrect the step as PENDING.
        stored = await store.get_execution(state.id)
        assert stored is not None
        assert stored.version == before + 1
        step = stored.step("s1")
        assert step is not None
        assert step.status is StepStatus.SKIPPED
        assert step.skip_reason is SkipReason.APPROVAL_DENIED
        assert step.approval_ref == "perm-1"

    async def test_a_queued_step_is_still_denied_by_a_human(self, store: PlanStore) -> None:
        """ADR-0041 widens the denial rule; it does not move it (§3).

        This is the genuine human-denied path — a confirmation was shown and
        answered no — and it stays legal. Without it the suite would admit a
        store that implements only the direct edge, leaving a real user denial
        with nowhere to go and the step awaiting approval forever.
        """
        state = await self._started(store)
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.AWAITING_APPROVAL,
                expected_version=state.version,
                bound_tool="smtp",
            )
        )
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.SKIPPED,
                expected_version=state.version,
                skip_reason=SkipReason.APPROVAL_DENIED,
                approval_ref="perm-denied",
            )
        )

        step = state.step("s1")
        assert step is not None
        assert step.status is StepStatus.SKIPPED
        assert step.skip_reason is SkipReason.APPROVAL_DENIED
        assert step.approval_ref == "perm-denied"

    async def test_a_pending_denial_must_point_at_its_decision(self, store: PlanStore) -> None:
        """The `approval_ref` is the whole guard on the direct edge (ADR-0041 §2).

        Without it, `APPROVAL_DENIED` would be assertable from the status every
        step starts in, with nothing behind it — the fabricated record the
        narrower rule was protecting against.
        """
        state = await self._started(store)
        with pytest.raises(IllegalTransitionError):
            await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="s1",
                    to_status=StepStatus.SKIPPED,
                    expected_version=state.version,
                    skip_reason=SkipReason.APPROVAL_DENIED,
                )
            )

    async def test_a_denial_must_point_at_its_decision(self, store: PlanStore) -> None:
        state = await self._started(store)
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.AWAITING_APPROVAL,
                expected_version=state.version,
                bound_tool="smtp",
            )
        )
        with pytest.raises(IllegalTransitionError):
            await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="s1",
                    to_status=StepStatus.SKIPPED,
                    expected_version=state.version,
                    skip_reason=SkipReason.APPROVAL_DENIED,
                )
            )

    async def test_an_approved_step_cannot_run_a_different_tool(self, store: PlanStore) -> None:
        """Approving "smtp" must not become permission to run something else.

        This is the authorisation-laundering path: without the check, a caller
        approves a benign tool and then claims the step with a destructive one,
        carrying the benign approval along as its justification.
        """
        state = await self._started(store)
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.AWAITING_APPROVAL,
                expected_version=state.version,
                bound_tool="smtp",
            )
        )
        with pytest.raises(IllegalTransitionError):
            await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="s1",
                    to_status=StepStatus.RUNNING,
                    expected_version=state.version,
                    bound_tool="payments.delete_account",
                    approval_ref="perm-for-smtp",
                )
            )

    async def test_a_retry_cannot_swap_the_tool(self, store: PlanStore) -> None:
        """The same laundering, taken through the retry path instead."""
        state = await self._started(store)
        state = await store.commit_transition(_claim(state))
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.FAILED,
                expected_version=state.version,
                failure=StepFailure(message="boom"),
            )
        )
        with pytest.raises(IllegalTransitionError):
            await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="s1",
                    to_status=StepStatus.RUNNING,
                    expected_version=state.version,
                    bound_tool="payments.delete_account",
                )
            )

    async def test_unknown_step_is_rejected(self, store: PlanStore) -> None:
        state = await self._started(store)
        with pytest.raises(PlanningError):
            await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="ghost",
                    to_status=StepStatus.AWAITING_APPROVAL,
                    expected_version=state.version,
                )
            )

    async def test_a_full_run_reaches_succeeded_with_its_output(self, store: PlanStore) -> None:
        state = await self._started(store)
        state = await store.commit_transition(_claim(state))
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.SUCCEEDED,
                expected_version=state.version,
                output={"ref": "ABC"},
            )
        )
        step = state.step("s1")
        assert step is not None
        assert step.status is StepStatus.SUCCEEDED
        assert step.output == {"ref": "ABC"}
        assert step.finished_at is not None
        assert not state.is_active

    # --- compare-and-swap -----------------------------------------------

    async def test_a_stale_write_is_refused(self, store: PlanStore) -> None:
        """The race that would otherwise run a non-idempotent tool twice."""
        state = await self._started(store)
        first = _claim(state)
        second = _claim(state)  # computed against the same version

        await store.commit_transition(first)
        with pytest.raises(StaleExecutionError):
            await store.commit_transition(second)

    async def test_the_loser_of_a_race_did_not_change_anything(self, store: PlanStore) -> None:
        state = await self._started(store)
        await store.commit_transition(_claim(state))
        with pytest.raises(StaleExecutionError):
            await store.commit_transition(_claim(state))

        stored = await store.get_execution(state.id)
        assert stored is not None
        step = stored.step("s1")
        assert step is not None
        assert step.attempts == 1

    # --- retries ---------------------------------------------------------

    async def test_a_failed_step_can_be_retried(self, store: PlanStore) -> None:
        state = await self._started(store)
        state = await store.commit_transition(_claim(state))
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.FAILED,
                expected_version=state.version,
                failure=StepFailure(message="boom"),
            )
        )
        state = await store.commit_transition(_claim(state))
        step = state.step("s1")
        assert step is not None
        assert step.status is StepStatus.RUNNING
        assert step.attempts == 2
        assert step.failure is None, "a retry re-opens the step, clearing the last failure"

    async def test_retries_are_bounded(self, store: PlanStore) -> None:
        """The ceiling is deterministic code's to enforce (VISION §7)."""
        state = await self._started(store)
        for _ in range(3):
            state = await store.commit_transition(_claim(state))
            state = await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="s1",
                    to_status=StepStatus.FAILED,
                    expected_version=state.version,
                    failure=StepFailure(message="boom"),
                )
            )
        with pytest.raises(RetriesExhaustedError):
            await store.commit_transition(_claim(state))

    # --- failure records survive the store (ADR-0039) ---------------------

    @pytest.mark.parametrize("to_status", [StepStatus.FAILED, StepStatus.INDETERMINATE])
    async def test_a_failure_status_transition_requires_a_failure(
        self, store: PlanStore, to_status: StepStatus
    ) -> None:
        """Required on both FAILED and INDETERMINATE (ADR-0039 §2), not just FAILED.

        A suite that pinned only ``FAILED`` would certify a store fed by a
        command shape that left ``INDETERMINATE`` — the #208 half — with no
        durable account of itself.
        """
        with pytest.raises(ValidationError, match="requires a failure"):
            StepTransition(
                execution_id="e1",
                step_id="s1",
                to_status=to_status,
                expected_version=0,
            )

    @pytest.mark.parametrize(
        "to_status",
        [StepStatus.RUNNING, StepStatus.AWAITING_APPROVAL, StepStatus.SUCCEEDED],
    )
    async def test_a_non_failure_transition_forbids_a_failure(
        self, store: PlanStore, to_status: StepStatus
    ) -> None:
        with pytest.raises(ValidationError, match="only valid for a transition to FAILED"):
            StepTransition(
                execution_id="e1",
                step_id="s1",
                to_status=to_status,
                expected_version=0,
                failure=StepFailure(message="boom"),
            )

    @pytest.mark.parametrize("to_status", [StepStatus.FAILED, StepStatus.INDETERMINATE])
    async def test_a_tool_failure_round_trips_verbatim(
        self, store: PlanStore, to_status: StepStatus
    ) -> None:
        """Kind and message are unchanged after ``commit_transition`` (ADR-0039 §6).

        On ``FAILED`` *and* ``INDETERMINATE`` — the latter is the regression test
        for #208 and for ADR-0032 §5's by-value rule surviving one frame past the
        seam. Read back from the store, not the return value, so a store that
        only echoed the command would not pass.
        """
        state = await self._started(store)
        state = await store.commit_transition(_claim(state))
        failure = StepFailure(
            kind=ToolFailureKind.RATE_LIMITED, message="the upstream throttled us"
        )
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=to_status,
                expected_version=state.version,
                failure=failure,
            )
        )

        stored = await store.get_execution(state.id)
        assert stored is not None
        step = stored.step("s1")
        assert step is not None
        assert step.status is to_status
        assert step.failure == failure
        assert step.failure is not None
        assert step.failure.kind is ToolFailureKind.RATE_LIMITED
        assert step.failure.message == "the upstream throttled us"

    async def test_an_indeterminate_step_with_a_retryable_kind_is_not_run_again(
        self, store: PlanStore
    ) -> None:
        """A durable kind on an INDETERMINATE step is diagnostic, never permission.

        The graph has no ``INDETERMINATE → RUNNING`` edge (ADR-0014 §4), so a
        ``TIMED_OUT`` whose ``retryable`` is ``True`` still cannot be re-claimed
        (ADR-0039 §4). This is the case a reader of the new field is most likely
        to get wrong.
        """
        state = await self._started(store)
        state = await store.commit_transition(_claim(state))
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.INDETERMINATE,
                expected_version=state.version,
                failure=StepFailure(kind=ToolFailureKind.TIMED_OUT, message="deadline passed"),
            )
        )
        assert ToolFailureKind.TIMED_OUT.retryable  # the field says "retryable"...
        with pytest.raises(IllegalTransitionError):  # ...and the graph still refuses it
            await store.commit_transition(_claim(state))

    # --- resumption -------------------------------------------------------

    async def test_active_executions_finds_outstanding_work(self, store: PlanStore) -> None:
        state = await self._started(store)
        assert [found.id for found in await store.active_executions()] == [state.id]

    # --- execution-id non-reuse (ADR-0044 §1, #280) -----------------------

    async def test_two_executions_of_one_plan_get_distinct_ids(self, store: PlanStore) -> None:
        """A plan may have several live executions, and each is its own instance.

        ADR-0014 §5's ``active_executions`` exists precisely to resume several,
        and ADR-0044 §1 binds a parked confirmation to ``(execution_id,
        step_id)``. So two executions of one plan must never share an id, or
        one's answer would resolve the other's identical parked step.
        """
        await store.save_goal(_goal())
        await store.save_plan(_plan())
        first = await store.start_execution("p1")
        second = await store.start_execution("p1")
        assert first.id != second.id

    async def test_a_deleted_executions_id_is_never_reused(self, store: PlanStore) -> None:
        """Deleting execution ``E`` must not free its id for a later one (#280).

        This is the exact hazard ADR-0044 §1 makes non-reuse normative against:
        a conforming store that deleted ``E`` and later minted another named
        ``E`` would let ``pending_confirmation(E, step)`` (ADR-0044 §3) return a
        stale ``CONFIRM`` from the prior incarnation for the fresh one. The id is
        asserted *unequal*, never a format — the contract fixes uniqueness, not
        how a store keys its ids.
        """
        first = await self._started(store)
        await store.delete_goal("g1")
        assert await store.get_execution(first.id) is None

        await store.save_goal(_goal())
        await store.save_plan(_plan())
        second = await store.start_execution("p1")
        assert second.id != first.id

    async def test_an_execution_id_is_not_reused_after_clear(self, store: PlanStore) -> None:
        """``clear`` erases the records but must not rewind the id space.

        The same non-reuse guarantee as deletion, taken through the bulk-erase
        path: a store that reset an id counter on ``clear`` would collide a new
        execution with one a still-retained audit trail already names.
        """
        first = await self._started(store)
        await store.clear()

        await store.save_goal(_goal())
        await store.save_plan(_plan())
        second = await store.start_execution("p1")
        assert second.id != first.id

    async def test_a_finished_execution_is_not_active(self, store: PlanStore) -> None:
        state = await self._started(store)
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.SKIPPED,
                expected_version=state.version,
                skip_reason=SkipReason.SUPERSEDED,
            )
        )
        assert await store.active_executions() == []

    # --- stored state is the store's own ----------------------------------

    async def test_a_retained_goal_reference_cannot_edit_stored_state(
        self, store: PlanStore
    ) -> None:
        """ADR-0068 freezes ``Goal``, so a retained reference cannot rewrite it."""
        goal = _goal()
        await store.save_goal(goal)
        with pytest.raises(ValidationError):
            goal.statement = "tampered"

        stored = await store.get_goal("g1")
        assert stored is not None
        assert stored.statement == "relocate to Lisbon"

    async def test_mutating_a_returned_goal_cannot_edit_stored_state(
        self, store: PlanStore
    ) -> None:
        await store.save_goal(_goal())
        got = await store.get_goal("g1")
        assert got is not None
        with pytest.raises(ValidationError):
            got.statement = "tampered"

        fresh = await store.get_goal("g1")
        assert fresh is not None
        assert fresh.statement == "relocate to Lisbon"

    async def test_mutating_a_returned_plan_cannot_edit_stored_state(
        self, store: PlanStore
    ) -> None:
        """``frozen=True`` stops attribute assignment, not ``__dict__`` writes.

        Sharing the stored instance would therefore let a caller rewrite the
        audit record in place — including a nested step's ``capability``, which
        is what the executor later binds a tool to.
        """
        await store.save_goal(_goal())
        await store.save_plan(_plan())

        got = await store.get_plan("p1")
        assert got is not None
        got.__dict__["goal_id"] = "tampered"
        got.steps[0].__dict__["capability"] = "payments.delete_account"

        fresh = await store.get_plan("p1")
        assert fresh is not None
        assert fresh.goal_id == "g1"
        assert fresh.steps[0].capability == "send_email"

    async def test_a_retained_plan_reference_cannot_edit_stored_state(
        self, store: PlanStore
    ) -> None:
        await store.save_goal(_goal())
        plan = _plan()
        await store.save_plan(plan)
        plan.__dict__["goal_id"] = "tampered"

        stored = await store.get_plan("p1")
        assert stored is not None
        assert stored.goal_id == "g1"

    async def test_an_exported_plan_cannot_edit_stored_state(self, store: PlanStore) -> None:
        await store.save_goal(_goal())
        await store.save_plan(_plan())

        export = await store.export()
        export.plans[0].__dict__["goal_id"] = "tampered"

        again = await store.export()
        assert again.plans[0].goal_id == "g1"

    async def test_mutating_a_returned_execution_cannot_edit_stored_state(
        self, store: PlanStore
    ) -> None:
        """Execution state is the audit record; only commit_transition may move it.

        ADR-0068 freezes ``ExecutionState`` and its ``StepExecution`` elements, so
        the audit record cannot be edited in place at all — neither the nested
        step status nor the version.
        """
        state = await self._started(store)
        with pytest.raises(ValidationError):
            state.steps[0].status = StepStatus.SUCCEEDED
        with pytest.raises(ValidationError):
            state.version = 99

        fresh = await store.get_execution(state.id)
        assert fresh is not None
        assert fresh.steps[0].status is StepStatus.PENDING
        assert fresh.version == 0

    async def test_active_executions_come_back_oldest_first(self, store: PlanStore) -> None:
        """Sorting ids would interleave plans and put exec-10 before exec-2."""
        await store.save_goal(_goal())
        expected = []
        for index in range(1, 13):
            await store.save_plan(_plan(plan_id=f"p{index}"))
            expected.append((await store.start_execution(f"p{index}")).id)

        assert [state.id for state in await store.active_executions()] == expected

    # --- data rights (ADR-0004) -------------------------------------------

    async def test_export_carries_the_stored_state(self, store: PlanStore) -> None:
        await self._started(store)
        export = await store.export()
        assert [goal.id for goal in export.goals] == ["g1"]
        assert [plan.id for plan in export.plans] == ["p1"]
        assert len(export.executions) == 1

    async def test_export_round_trips_through_json(self, store: PlanStore) -> None:
        await self._started(store)
        export = await store.export()
        assert type(export).model_validate_json(export.model_dump_json()) == export

    async def test_deleting_a_goal_cascades(self, store: PlanStore) -> None:
        state = await self._started(store)
        result = await store.delete_goal("g1")

        assert result.deleted
        assert result.plans_removed == 1
        assert result.executions_removed == 1
        assert await store.get_goal("g1") is None
        assert await store.get_plan("p1") is None
        assert await store.get_execution(state.id) is None

    async def test_deletion_is_refused_while_a_step_is_live(self, store: PlanStore) -> None:
        state = await self._started(store)
        await store.commit_transition(_claim(state))

        result = await store.delete_goal("g1")
        assert not result.deleted
        assert result.blocked_by == (state.id,)
        assert await store.get_goal("g1") is not None

    async def test_deletion_succeeds_once_the_live_step_resolves(self, store: PlanStore) -> None:
        """Cancel-then-delete: the round-trip the refusal above asks for."""
        state = await self._started(store)
        state = await store.commit_transition(_claim(state))
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.INDETERMINATE,
                expected_version=state.version,
                failure=StepFailure(message="whether the tool acted is unknown"),
            )
        )
        result = await store.delete_goal("g1")
        assert result.deleted

    async def test_deletion_reports_erased_indeterminate_steps(self, store: PlanStore) -> None:
        """The user must learn an action may have completed before its record went."""
        state = await self._started(store)
        state = await store.commit_transition(_claim(state))
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.INDETERMINATE,
                expected_version=state.version,
                failure=StepFailure(message="whether the tool acted is unknown"),
            )
        )
        result = await store.delete_goal("g1")
        assert result.indeterminate_steps == ("s1",)

    async def test_a_permanently_failed_step_does_not_block_deletion(
        self, store: PlanStore
    ) -> None:
        """Otherwise one failure would void the erasure right for good."""
        state = await self._started(store)
        state = await store.commit_transition(_claim(state))
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.FAILED,
                expected_version=state.version,
                failure=StepFailure(message="boom"),
            )
        )
        assert state.is_active
        result = await store.delete_goal("g1")
        assert result.deleted

    async def test_deleting_an_unknown_goal_reports_refusal(self, store: PlanStore) -> None:
        result = await store.delete_goal("ghost")
        assert not result.deleted

    async def test_clear_empties_the_store(self, store: PlanStore) -> None:
        await self._started(store)
        assert await store.clear() > 0
        assert await store.get_goal("g1") is None

    async def test_clear_is_refused_while_a_step_is_live(self, store: PlanStore) -> None:
        state = await self._started(store)
        await store.commit_transition(_claim(state))
        with pytest.raises(ActiveExecutionError):
            await store.clear()

    # --- cancellation (ADR-0060) -------------------------------------------

    #: Whether this implementation acquires nothing whose safety outlives the
    #: coroutine — no connection, lock, spawned task, file handle or transaction
    #: that a ``CancelledError`` could unwind past. ``core.protocols``' clause is
    #: then vacuously satisfied and there is nothing for the case below to
    #: observe. Left ``False``, the suite requires the implementation to prove the
    #: invariant by overriding :meth:`store_suspended_mid_write` — so a new
    #: durable backend that reintroduces ADR-0054's bug fails here rather than
    #: passing a suite that never looked. Opting out is a visible declaration in
    #: the subclass, exactly as ``serves_a_fixed_instant`` is for the context
    #: provider.
    acquires_no_shared_resource: bool = False

    def store_suspended_mid_write(
        self,
    ) -> AbstractAsyncContextManager[SuspendedMidWrite[PlanStore]]:
        """Supply a store whose named locked operation can be stopped *inside* its resource.

        Override unless :attr:`acquires_no_shared_resource` is set. The suite
        cancels the call while it is suspended and then watches what a second
        caller can reach, which is the only way to tell the fixed code from the
        broken code: pre-ADR-0054 the store raised ``CancelledError`` correctly
        and released the connection anyway, so a case that asserts only
        propagation certifies the bug (ADR-0060 §3).

        The returned :class:`SuspendedMidWrite` carries the store, its
        :class:`ResourceLog`, and an ``arm(operation)`` lever the case calls —
        *after* its preconditions — to hold the next entry into that operation
        (#370, #397). Every distinct ``async with self._lock`` site is a separate
        place the same regression can reappear — the locked *reads* included, since
        ADR-0060 §3 binds any method that acquires the resource — so the case is run
        against each; ``arm``
        is where the implementation says how it stops a given one — a worker
        thread parked mid-SQL, a fake's single modelled resource. Returned as a
        context manager so the subject is disposed of the way that implementation
        needs.

        The :class:`ResourceLog` records each call's time *inside* the resource,
        and the case reads it once the scenario is over. It is not redundant with
        the blocked-caller check below: that one is decisive only where queueing
        is loop-bound (a fake on an ``asyncio.Lock``), while a store whose work
        runs on an executor can leave a second call pending for reasons that have
        nothing to do with the resource. The log settles that case directly.
        """
        raise NotImplementedError

    @pytest.mark.optional_obligation
    @pytest.mark.parametrize("make_op", _CANCELLATION_OPS, ids=lambda op: op().name)
    async def test_a_cancelled_operation_holds_its_resource_until_the_work_finishes(
        self, make_op: Callable[[], _CancellationOp]
    ) -> None:
        """``core.protocols``' cancellation clause, on every locked operation (ADR-0060).

        A cancelled call must not hand the resource to the next caller while the
        work it started is still using it. The second call is what makes this a
        test of the invariant rather than of propagation: a single cancelled call
        in isolation looks identical either way. Run once per locked operation, so
        a regression reintroduced at any one lock site — not just ``save_goal`` —
        is caught.

        **Named for an operation, not a write.** ADR-0060 §3 binds any method that
        acquires the resource; the writes were covered first (#370) and the locked
        reads are the same invariant on the other half of the surface (#397). A read
        that released the connection under cancellation while its worker still held
        it is the identical ADR-0054 hazard, and no write case can see it.

        The first call's *effect* is deliberately not asserted here (the op's
        ``verify`` pins only what a caller may rely on). The clause's third
        paragraph makes it indeterminate to the caller — under ADR-0054's shield a
        cancelled write that reached ``COMMIT`` is durably written — so the two
        calls are independent subjects and what is pinned is that the second is
        whole and the store still serves reads.
        """
        if self.acquires_no_shared_resource:
            pytest.skip("implementation acquires nothing whose safety outlives the coroutine")

        op = make_op()
        async with self.store_suspended_mid_write() as harness:
            store = harness.store
            await op.prepare(store)
            # Arm *after* the preconditions, so a fake arming its one resource
            # suspends the operation under test rather than a setup write.
            suspended = harness.arm(op.name)
            visited_before = harness.log.visits

            first = asyncio.ensure_future(op.first(store))
            second: asyncio.Task[object] | None = None
            try:
                await suspended.reached()
                first.cancel()
                await settle()

                second = asyncio.ensure_future(op.second(store))
                await settle()
                assert not second.done(), _RELEASED_EARLY

                # Again, because deferring one cancellation is not the contract:
                # a second delivered while the deferred wait runs must not escape
                # and unwind out of the resource either (ADR-0054's helper loops
                # on `while not done.is_set()` for exactly this).
                first.cancel()
                await settle()
                assert not second.done(), _RELEASED_EARLY
            finally:
                suspended.release()

            with pytest.raises(asyncio.CancelledError):
                await first
            assert second is not None
            await second

            # Decisive where the blocked-caller check above is not: the two calls
            # were never inside the resource at the same time. A delta, because a
            # fake's preconditions pass through the same logged resource.
            assert not harness.log.overlapped, _RELEASED_EARLY
            assert harness.log.visits - visited_before == 2, (
                "both calls should have reached the resource by now"
            )

            await op.verify(store)
