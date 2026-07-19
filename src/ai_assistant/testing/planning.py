"""Canonical test doubles for the planning contracts (ADR-0014).

The shared fakes for :class:`~ai_assistant.core.protocols.Planner` and
:class:`~ai_assistant.core.protocols.PlanStore`, so a subsystem that depends on
planning (orchestration, tools, ...) can test against real, contract-correct
implementations *without importing the planning subsystem's internals*
(CLAUDE.md golden rule 1).

They deliberately re-implement the transition graph rather than importing
``ai_assistant.planning``: importing it would defeat the purpose, since a
consumer's tests would then pull in the very subsystem the fake stands in for.
The shared conformance suite is what keeps the two implementations honest — both
must pass it, so a divergence is a test failure rather than a latent surprise.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ai_assistant.core.errors import (
    ActiveExecutionError,
    IllegalTransitionError,
    PlanningError,
    RetriesExhaustedError,
    StaleExecutionError,
)
from ai_assistant.core.types import (
    ActionPlan,
    ExecutionState,
    GoalDeletion,
    PlanExport,
    SkipReason,
    StepExecution,
    StepStatus,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.types import CurrentContext, Goal, MemoryRecord, StepTransition

#: Mirror of the ADR-0014 §4 graph; see the module docstring on duplication.
_LEGAL_TRANSITIONS: dict[StepStatus, frozenset[StepStatus]] = {
    StepStatus.PENDING: frozenset(
        {StepStatus.RUNNING, StepStatus.AWAITING_APPROVAL, StepStatus.SKIPPED}
    ),
    StepStatus.AWAITING_APPROVAL: frozenset({StepStatus.RUNNING, StepStatus.SKIPPED}),
    StepStatus.RUNNING: frozenset(
        {StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.INDETERMINATE}
    ),
    StepStatus.FAILED: frozenset({StepStatus.RUNNING}),
    StepStatus.SUCCEEDED: frozenset(),
    StepStatus.SKIPPED: frozenset(),
    StepStatus.INDETERMINATE: frozenset(),
}

#: Which skip reasons are truthful from which status; mirrors ADR-0014 §4.
_LEGAL_SKIP_REASONS: dict[StepStatus, frozenset[SkipReason]] = {
    StepStatus.PENDING: frozenset(
        {SkipReason.UNMET_DEPENDENCY, SkipReason.NO_CAPABLE_TOOL, SkipReason.SUPERSEDED}
    ),
    StepStatus.AWAITING_APPROVAL: frozenset({SkipReason.APPROVAL_DENIED, SkipReason.SUPERSEDED}),
}

_MAX_ATTEMPTS = 3


def _utcnow() -> datetime:
    return datetime.now(UTC)


class FakePlanner:
    """A ``Planner`` that returns a scripted plan and records how it was called.

    Structurally implements :class:`~ai_assistant.core.protocols.Planner`.
    """

    def __init__(
        self, plan: ActionPlan | None = None, *, now: Callable[[], datetime] = _utcnow
    ) -> None:
        """Create a planner.

        Args:
            plan: The plan to return. When ``None``, a single-step plan is
                synthesised for whichever goal it is asked about.
            now: Clock for synthesised plans; injectable for deterministic tests.
        """
        self._plan = plan
        self._now = now
        self.calls: list[tuple[Goal, CurrentContext, tuple[MemoryRecord, ...]]] = []

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
    ) -> ActionPlan:
        """Return the scripted plan, recording the arguments it was given."""
        self.calls.append((goal, context, tuple(memories)))
        if self._plan is not None:
            return self._plan
        return ActionPlan(
            id=f"{goal.id}-plan",
            goal_id=goal.id,
            steps=(),
            created_at=self._now(),
            rationale="synthesised by FakePlanner",
        )


class FakePlanStore:
    """A non-persistent ``PlanStore`` test double backed by dicts.

    Structurally implements :class:`~ai_assistant.core.protocols.PlanStore`,
    including the compare-and-swap write path and the data-rights operations.
    """

    def __init__(self, *, now: Callable[[], datetime] = _utcnow) -> None:
        """Create an empty store with an injectable clock."""
        self._goals: dict[str, Goal] = {}
        self._plans: dict[str, ActionPlan] = {}
        self._executions: dict[str, ExecutionState] = {}
        self._now = now
        self._sequence = 0

    async def save_goal(self, goal: Goal) -> str:
        """Persist a goal, or update the parts of one that may change.

        ``status`` and ``deadline`` move over a goal's life. ``statement``,
        ``provenance`` and ``created_at`` are its identity: rewriting them would
        make every plan and execution already recorded against this id describe
        an objective the user never set — the same audit hazard ``save_plan``
        refuses, and the reason a changed objective needs a new goal.
        """
        existing = self._goals.get(goal.id)
        if existing is not None:
            identity = ("statement", "provenance", "created_at")
            changed = [
                field for field in identity if getattr(existing, field) != getattr(goal, field)
            ]
            if changed:
                msg = (
                    f"goal {goal.id} already exists and its {', '.join(changed)} cannot "
                    "change: plans and executions already recorded against it would "
                    "silently come to describe a different objective. Use a new id."
                )
                raise PlanningError(msg)
        self._goals[goal.id] = goal.model_copy(deep=True)
        return goal.id

    async def get_goal(self, goal_id: str) -> Goal | None:
        """Return the goal with ``goal_id``, or ``None``."""
        stored = self._goals.get(goal_id)
        return None if stored is None else stored.model_copy(deep=True)

    async def save_plan(self, plan: ActionPlan) -> str:
        """Persist a plan, requiring its goal to exist and its id to be free.

        Re-planning must take a new id so the previous plan stays an intact
        audit record; an identical re-save is idempotent (ADR-0014 §2).
        """
        if plan.goal_id not in self._goals:
            msg = f"plan {plan.id} refers to unknown goal {plan.goal_id}"
            raise PlanningError(msg)
        existing = self._plans.get(plan.id)
        if existing is not None and existing != plan:
            msg = (
                f"plan {plan.id} already exists and differs; re-planning must use a new "
                "id so the previous plan stays an intact audit record"
            )
            raise PlanningError(msg)
        self._plans[plan.id] = plan.model_copy(deep=True)
        return plan.id

    async def get_plan(self, plan_id: str) -> ActionPlan | None:
        """Return the plan with ``plan_id``, or ``None``."""
        stored = self._plans.get(plan_id)
        return None if stored is None else stored.model_copy(deep=True)

    async def start_execution(self, plan_id: str) -> ExecutionState:
        """Open and store a fresh execution, derived from the plan's steps."""
        plan = self._plans.get(plan_id)
        if plan is None:
            msg = f"cannot start an execution for unknown plan {plan_id}"
            raise PlanningError(msg)

        self._sequence += 1
        state = ExecutionState(
            id=f"{plan_id}-exec-{self._sequence}",
            plan_id=plan.id,
            steps=tuple(StepExecution(step_id=step.id) for step in plan.steps),
            version=0,
            updated_at=self._now(),
        )
        self._executions[state.id] = state
        return state.model_copy(deep=True)

    async def commit_transition(self, transition: StepTransition) -> ExecutionState:
        """Apply one transition against the stored snapshot and persist it."""
        stored = self._executions.get(transition.execution_id)
        if stored is None:
            msg = f"unknown execution {transition.execution_id}"
            raise PlanningError(msg)

        if transition.expected_version != stored.version:
            msg = (
                f"execution {stored.id} is at version {stored.version}, "
                f"but the write was computed against {transition.expected_version}"
            )
            raise StaleExecutionError(msg)

        current = stored.step(transition.step_id)
        if current is None:
            msg = f"execution {stored.id} has no step {transition.step_id}"
            raise PlanningError(msg)

        if transition.to_status not in _LEGAL_TRANSITIONS[current.status]:
            msg = (
                f"step {current.step_id} cannot go from {current.status} to {transition.to_status}"
            )
            raise IllegalTransitionError(msg)

        updated = self._advance(current, transition)
        state = ExecutionState.model_validate(
            stored.model_copy(
                update={
                    "steps": tuple(
                        updated if step.step_id == updated.step_id else step
                        for step in stored.steps
                    ),
                    "version": stored.version + 1,
                    "updated_at": self._now(),
                }
            ).model_dump()
        )
        self._executions[state.id] = state
        return state.model_copy(deep=True)

    def _advance(self, step: StepExecution, transition: StepTransition) -> StepExecution:
        """Build the step's next value, re-validating so invariants still bite."""
        if transition.to_status is StepStatus.RUNNING:
            updated = self._to_running(step, transition)
        elif transition.to_status is StepStatus.AWAITING_APPROVAL:
            updated = self._to_awaiting_approval(step, transition)
        elif transition.to_status is StepStatus.SKIPPED:
            updated = self._to_skipped(step, transition)
        else:
            updated = step.model_copy(
                update={
                    "status": transition.to_status,
                    "output": transition.output,
                    "error": transition.error,
                    "finished_at": self._now(),
                }
            )
        return StepExecution.model_validate(updated.model_dump())

    def _to_awaiting_approval(
        self, step: StepExecution, transition: StepTransition
    ) -> StepExecution:
        """Queue the step for approval; there must be a specific tool to approve."""
        bound_tool = transition.bound_tool or step.bound_tool
        if bound_tool is None:
            msg = f"step {step.step_id} cannot await approval without a bound_tool"
            raise IllegalTransitionError(msg)
        return step.model_copy(
            update={"status": StepStatus.AWAITING_APPROVAL, "bound_tool": bound_tool}
        )

    def _to_skipped(self, step: StepExecution, transition: StepTransition) -> StepExecution:
        """Skip the step, checking the reason is one this status could produce."""
        if transition.skip_reason not in _LEGAL_SKIP_REASONS.get(step.status, frozenset()):
            msg = (
                f"step {step.step_id} cannot be skipped as {transition.skip_reason} "
                f"from {step.status}"
            )
            raise IllegalTransitionError(msg)

        approval_ref = transition.approval_ref or step.approval_ref
        if transition.skip_reason is SkipReason.APPROVAL_DENIED and approval_ref is None:
            msg = f"step {step.step_id} cannot record a denial without an approval_ref"
            raise IllegalTransitionError(msg)

        return step.model_copy(
            update={
                "status": StepStatus.SKIPPED,
                "skip_reason": transition.skip_reason,
                "approval_ref": approval_ref,
            }
        )

    def _to_running(self, step: StepExecution, transition: StepTransition) -> StepExecution:
        """Claim the step, enforcing the retry ceiling and the approval rule."""
        if step.status is StepStatus.FAILED and step.attempts >= _MAX_ATTEMPTS:
            msg = f"step {step.step_id} has used its {_MAX_ATTEMPTS} attempts"
            raise RetriesExhaustedError(msg)

        approval_ref = transition.approval_ref or step.approval_ref
        bound_tool = transition.bound_tool or step.bound_tool
        if approval_ref is None or bound_tool is None:
            msg = f"step {step.step_id} cannot run without both an approval_ref and a bound_tool"
            raise IllegalTransitionError(msg)

        if step.bound_tool is not None and bound_tool != step.bound_tool:
            # An approval covers the tool it was granted for; swapping the tool
            # here would launder it into permission for a different action.
            msg = (
                f"step {step.step_id} is bound to {step.bound_tool} and cannot switch "
                f"to {bound_tool}"
            )
            raise IllegalTransitionError(msg)

        return step.model_copy(
            update={
                "status": StepStatus.RUNNING,
                "attempts": step.attempts + 1,
                "bound_tool": bound_tool,
                "approval_ref": approval_ref,
                "started_at": self._now(),
                "finished_at": None,
                "error": None,
                "output": None,
            }
        )

    async def get_execution(self, execution_id: str) -> ExecutionState | None:
        """Return the execution with ``execution_id``, or ``None``."""
        stored = self._executions.get(execution_id)
        return None if stored is None else stored.model_copy(deep=True)

    async def active_executions(self) -> list[ExecutionState]:
        """Return every execution with outstanding work, oldest first.

        Insertion order, not sorted id order: ids embed a plan prefix, so
        sorting them would interleave plans and put ``exec-10`` before
        ``exec-2``.
        """
        return [
            state.model_copy(deep=True) for state in self._executions.values() if state.is_active
        ]

    async def export(self) -> PlanExport:
        """Return a portable, internally consistent snapshot."""
        return PlanExport(
            exported_at=self._now(),
            goals=tuple(goal.model_copy(deep=True) for goal in self._goals.values()),
            plans=tuple(plan.model_copy(deep=True) for plan in self._plans.values()),
            executions=tuple(state.model_copy(deep=True) for state in self._executions.values()),
        )

    async def delete_goal(self, goal_id: str) -> GoalDeletion:
        """Delete a goal and its plan history, refusing while work is live."""
        if goal_id not in self._goals:
            return GoalDeletion(deleted=False, blocked_by=("<no such goal>",))

        plan_ids = {plan.id for plan in self._plans.values() if plan.goal_id == goal_id}
        executions = [state for state in self._executions.values() if state.plan_id in plan_ids]

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

        for state in executions:
            del self._executions[state.id]
        for plan_id in plan_ids:
            del self._plans[plan_id]
        del self._goals[goal_id]

        return GoalDeletion(
            deleted=True,
            plans_removed=len(plan_ids),
            executions_removed=len(executions),
            indeterminate_steps=indeterminate,
        )

    async def clear(self) -> int:
        """Delete everything, refusing while any execution has a live step."""
        live = sorted(state.id for state in self._executions.values() if state.has_live_step)
        if live:
            msg = f"cannot clear while executions are live: {', '.join(live)}"
            raise ActiveExecutionError(msg)

        removed = len(self._goals) + len(self._plans) + len(self._executions)
        self._goals.clear()
        self._plans.clear()
        self._executions.clear()
        return removed


__all__ = ["FakePlanStore", "FakePlanner", "SkipReason"]
