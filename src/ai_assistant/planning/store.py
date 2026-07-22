"""An in-memory :class:`~ai_assistant.core.protocols.PlanStore` (ADR-0014 §5).

The first, dependency-free implementation of the planning contract. It keeps
goals, plans and execution state in process-local dicts, so downstream
subsystems can be built against a real store before a durable backend exists.

It implements the full contract, including the compare-and-swap write path and
the ADR-0004 data-rights operations (``export``/``delete_goal``/``clear``). It is
**not persistent**: the contract is resumable, this implementation is not, and
that gap is named in ADR-0014 §5 rather than hidden. A SQLite backend follows
the precedent `memory` set.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import ActiveExecutionError, PlanningError
from ai_assistant.core.types import GoalDeletion, PlanExport, StepStatus
from ai_assistant.planning.execution import PlanExecution

if TYPE_CHECKING:
    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import ActionPlan, ExecutionState, Goal, StepTransition


def _utcnow() -> datetime:
    return datetime.now(UTC)


class InMemoryPlanStore:
    """A non-persistent ``PlanStore`` backed by dicts, for dev and tests.

    Structurally implements :class:`~ai_assistant.core.protocols.PlanStore`.
    Goals and plans are keyed by id and upserted; execution state is written
    only through :meth:`commit_transition`.
    """

    def __init__(
        self,
        *,
        now: Clock = _utcnow,
        tracker: PlanExecution | None = None,
    ) -> None:
        """Create an empty store.

        Args:
            now: Clock for export timestamps and execution ids; injectable for
                deterministic tests. Guarded by
                :func:`~ai_assistant.core.clock.checked_clock`, so a
                non-conforming reading is a ``PlanningError`` (ADR-0026).
            tracker: The transition tracker to validate writes against. Defaults
                to a :class:`PlanExecution` sharing this store's clock. The
                *unwrapped* clock is handed on: ``PlanExecution`` wraps it under
                its own owner label, so a bad reading names the seam that read it
                rather than whichever wrapper happens to be outermost.
        """
        self._goals: dict[str, Goal] = {}
        self._plans: dict[str, ActionPlan] = {}
        self._executions: dict[str, ExecutionState] = {}
        self._clock = checked_clock(now, owner="InMemoryPlanStore")
        self._tracker = tracker or PlanExecution(now=now)
        self._sequence = 0

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

        Rejecting an orphan is what lets ``export`` promise referential
        integrity without repairing anything at read time. Rejecting a *reused*
        id is what keeps a plan an audit record: silently replacing plan ``p1``
        would rewrite what the system is recorded as having decided, and leave
        executions of the old plan pointing at steps that were never theirs.
        Re-planning takes a new id (ADR-0014 §2). An identical re-save is
        idempotent, so a retry is harmless.

        Stored as a copy for the same reason goals and executions are:
        ``frozen=True`` stops ``plan.goal_id = ...`` but not
        ``plan.__dict__["goal_id"] = ...``, so sharing the instance would let a
        caller rewrite the store's own audit record — including a nested step's
        ``capability``.
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
        """Open and store a fresh execution for ``plan_id``."""
        plan = self._plans.get(plan_id)
        if plan is None:
            msg = f"cannot start an execution for unknown plan {plan_id}"
            raise PlanningError(msg)

        self._sequence += 1
        state = self._tracker.start(plan, execution_id=f"{plan_id}-exec-{self._sequence}")
        self._executions[state.id] = state
        return state.model_copy(deep=True)

    async def commit_transition(self, transition: StepTransition) -> ExecutionState:
        """Apply one transition against the stored snapshot and persist it.

        The only write path for execution state: the tracker rejects an illegal
        move and a stale ``expected_version``, so nothing the transition graph
        forbids can reach storage.
        """
        stored = self._executions.get(transition.execution_id)
        if stored is None:
            msg = f"unknown execution {transition.execution_id}"
            raise PlanningError(msg)

        updated = self._tracker.apply(stored, transition)
        self._executions[updated.id] = updated
        return updated.model_copy(deep=True)

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
        """Return a portable, internally consistent snapshot (ADR-0004 §6).

        Raises:
            PlanningError: If the injected clock's reading is not conforming
                (ADR-0026 §4).
        """
        return PlanExport(
            exported_at=self._now(),
            goals=tuple(goal.model_copy(deep=True) for goal in self._goals.values()),
            plans=tuple(plan.model_copy(deep=True) for plan in self._plans.values()),
            executions=tuple(state.model_copy(deep=True) for state in self._executions.values()),
        )

    async def delete_goal(self, goal_id: str) -> GoalDeletion:
        """Delete a goal and its plan history, unless work is live.

        Refused while any of the goal's executions has a ``RUNNING`` step, whose
        record an executor is about to commit against. Deliberately not keyed on
        "has outstanding work": a permanently failed step never settles, so that
        would make the goal undeletable for good.
        """
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
