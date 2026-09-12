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
from uuid import uuid4

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import ActiveExecutionError, PlanningError, StaleExecutionError
from ai_assistant.core.types import GoalDeletion, PlanExport, StepStatus
from ai_assistant.planning.execution import PlanExecution
from ai_assistant.planning.goals import advanced, appended

if TYPE_CHECKING:
    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import (
        ActionPlan,
        AttemptTransition,
        ExecutionState,
        Goal,
        GoalAttempt,
        GoalRevision,
        StepTransition,
    )


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
        self._attempts: dict[str, GoalAttempt] = {}
        self._plans: dict[str, ActionPlan] = {}
        self._executions: dict[str, ExecutionState] = {}
        self._clock = checked_clock(now, owner="InMemoryPlanStore")
        self._tracker = tracker or PlanExecution(now=now)
        self._sequence = 0
        # A fresh random nonce per store instance. The plan-prefixed sequence
        # alone is process-local — a restarted store (this is non-persistent, so
        # every process start is one) rewinds it to 0 and would re-mint a prior
        # incarnation's id, colliding with a *persistent* audit trail that still
        # binds a CONFIRM to it (ADR-0044 §1, #280). The incarnation nonce is the
        # minted entropy that makes the id unique for the audit trail's life
        # regardless of restarts — the "minted uuids already satisfy it" path.
        self._incarnation = uuid4().hex

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
        """Persist a **new** goal (ADR-0249 §12), refusing an id already held.

        **The opening write alone, and no longer an upsert.** An upsert that replaced
        a whole goal would defeat ADR-0249 §1's append-only interpretation and §12's
        compare-and-swap in one call: every later change goes through
        :meth:`record_interpretation`, which is the only route that advances
        ``version`` and the only one that can append a revision.

        Stored as a copy for the reason plans and executions are: ``frozen=True``
        stops ``goal.status = ...`` but not ``goal.__dict__["status"] = ...``.

        Raises:
            PlanningError: If the store already holds a goal under this ``id``.
        """
        if goal.id in self._goals:
            msg = (
                f"goal {goal.id} already exists: save_goal is the opening write alone, "
                "and a later change to a goal is a record_interpretation (ADR-0249 §12)"
            )
            raise PlanningError(msg)
        self._goals[goal.id] = goal.model_copy(deep=True)
        return goal.id

    async def get_goal(self, goal_id: str) -> Goal | None:
        """Return the goal with ``goal_id``, or ``None``."""
        stored = self._goals.get(goal_id)
        return None if stored is None else stored.model_copy(deep=True)

    async def record_interpretation(self, revision: GoalRevision) -> Goal:
        """Append one interpretation revision, compare-and-swap (ADR-0249 §12).

        The read, the comparison and the write are one step: there is no ``await``
        between reading the stored version and writing the appended goal, so nothing
        can interleave and no decision is taken on a separate read.

        Raises:
            StaleExecutionError: If the stored version has moved on.
            PlanningError: If ``goal_id`` names no stored goal, or the revision does
                not follow the goal's current one.
        """
        stored = self._goals.get(revision.goal_id)
        if stored is None:
            msg = f"cannot record an interpretation for unknown goal {revision.goal_id}"
            raise PlanningError(msg)
        if stored.version != revision.expected_version:
            msg = (
                f"goal {revision.goal_id} is at version {stored.version}, not "
                f"{revision.expected_version}: re-read it and recompute the revision"
            )
            raise StaleExecutionError(msg)
        updated = appended(stored, revision.interpretation)
        self._goals[updated.id] = updated
        return updated.model_copy(deep=True)

    async def open_attempt(self, attempt: GoalAttempt) -> str:
        """Persist a new attempt for a stored goal (ADR-0249 §12).

        Raises:
            PlanningError: If ``goal_id`` names no stored goal, or the store already
                holds an attempt under this ``id``.
        """
        if attempt.goal_id not in self._goals:
            msg = f"attempt {attempt.id} refers to unknown goal {attempt.goal_id}"
            raise PlanningError(msg)
        if attempt.id in self._attempts:
            msg = (
                f"attempt {attempt.id} already exists; a change to an attempt is a "
                "commit_attempt, which is its only mutation route (ADR-0249 §12)"
            )
            raise PlanningError(msg)
        self._attempts[attempt.id] = attempt.model_copy(deep=True)
        return attempt.id

    async def get_attempt(self, attempt_id: str) -> GoalAttempt | None:
        """Return the attempt with ``attempt_id``, or ``None``."""
        stored = self._attempts.get(attempt_id)
        return None if stored is None else stored.model_copy(deep=True)

    async def attempts_of(self, goal_id: str) -> tuple[GoalAttempt, ...]:
        """Return every attempt of ``goal_id``, in ``opened_at`` order.

        The id is the tie-break, so two attempts opened at one instant are enumerated
        in a fixed order rather than in insertion order.
        """
        return tuple(
            attempt.model_copy(deep=True)
            for attempt in sorted(
                (one for one in self._attempts.values() if one.goal_id == goal_id),
                key=lambda one: (one.opened_at, one.id),
            )
        )

    async def commit_attempt(self, transition: AttemptTransition) -> GoalAttempt:
        """Apply one attempt transition, compare-and-swap (ADR-0249 §12).

        The attempt's **only** mutation route, and — as for
        :meth:`record_interpretation` — the read, the comparison and the write are
        one step.

        Raises:
            StaleExecutionError: If the stored version has moved on.
            IllegalTransitionError: If the move is not legal from where it stands.
            PlanningError: If the attempt does not exist, or the result is not a shape
                ADR-0249 §5 admits.
        """
        stored = self._attempts.get(transition.attempt_id)
        if stored is None:
            msg = f"unknown attempt {transition.attempt_id}"
            raise PlanningError(msg)
        if stored.version != transition.expected_version:
            msg = (
                f"attempt {transition.attempt_id} is at version {stored.version}, not "
                f"{transition.expected_version}: re-read it and recompute the transition"
            )
            raise StaleExecutionError(msg)
        updated = advanced(stored, transition)
        self._attempts[updated.id] = updated
        return updated.model_copy(deep=True)

    async def save_plan(self, plan: ActionPlan) -> str:
        """Persist a plan, requiring its goal to exist and its id to be free.

        Rejecting an orphan is what lets ``export`` promise referential
        integrity without repairing anything at read time. Rejecting a *reused*
        id is what keeps a plan an audit record: silently replacing plan ``p1``
        would rewrite what the system is recorded as having decided, and leave
        executions of the old plan pointing at steps that were never theirs.
        Re-planning takes a new id (ADR-0014 §2). An identical re-save is
        idempotent, so a retry is harmless.

        **An unstamped ``targets_revision`` is refused too** (ADR-0249 §8). The
        unstamped state exists only between the planner's return and the loop's
        stamp, and closing the window here rather than trusting it to close itself is
        the same move the ``supersedes`` check below makes. A plan **already on disk**
        carrying ``None`` decodes — ADR-0249 §12's migration writes exactly such rows
        — and ADR-0249 §8's not-driven rule is what then reads it.

        **A ``supersedes`` that does not resolve is refused** (ADR-0228 §5): one
        naming a plan this store does not hold, one naming the saving plan's own
        ``id``, and one naming a plan under a different ``goal_id``. That is
        ADR-0014 §5's export promise kept at write time, exactly as the orphan check
        above keeps it for ``goal_id`` — a plan whose predecessor is missing is a
        supersession whose subject has been lost, discovered only by whoever reads
        the export back.

        Stored as a copy for the same reason goals and executions are:
        ``frozen=True`` stops ``plan.goal_id = ...`` but not
        ``plan.__dict__["goal_id"] = ...``, so sharing the instance would let a
        caller rewrite the store's own audit record — including a nested step's
        ``capability``.
        """
        if plan.goal_id not in self._goals:
            msg = f"plan {plan.id} refers to unknown goal {plan.goal_id}"
            raise PlanningError(msg)
        if plan.targets_revision is None:
            msg = (
                f"plan {plan.id} carries no targets_revision: the unstamped state "
                "exists only between the planner's return and the loop's stamp, and "
                "the window is closed at the store (ADR-0249 §8)"
            )
            raise PlanningError(msg)
        if plan.supersedes is not None:
            if plan.supersedes == plan.id:
                msg = f"plan {plan.id} supersedes itself; a plan cannot replace the plan it is"
                raise PlanningError(msg)
            predecessor = self._plans.get(plan.supersedes)
            if predecessor is None:
                msg = f"plan {plan.id} supersedes unknown plan {plan.supersedes}"
                raise PlanningError(msg)
            if predecessor.goal_id != plan.goal_id:
                msg = (
                    f"plan {plan.id} supersedes plan {plan.supersedes}, which is under goal "
                    f"{predecessor.goal_id} rather than {plan.goal_id}; a revision replaces "
                    "a plan for the same goal"
                )
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
        """Open and store a fresh execution for ``plan_id``.

        The id is ``{plan_id}-exec-{incarnation}-{sequence}``. ``_sequence`` is
        monotonic and **never** reset within a store's life — not by
        :meth:`delete_goal`, not by :meth:`clear` — so ids never collide *within*
        one incarnation. ``_incarnation`` is a per-store random nonce, so ids
        never collide *across* restarts either (this store is non-persistent, so
        a restart rewinds the sequence to 0). Together they give the non-reuse
        guarantee ADR-0044 §1 makes normative — an id unique for the life of the
        audit trail (#280) — so a deleted or prior-incarnation execution's id can
        never be minted again and let a stale parked ``CONFIRM`` recover onto a
        new execution.
        """
        plan = self._plans.get(plan_id)
        if plan is None:
            msg = f"cannot start an execution for unknown plan {plan_id}"
            raise PlanningError(msg)

        self._sequence += 1
        execution_id = f"{plan_id}-exec-{self._incarnation}-{self._sequence}"
        state = self._tracker.start(plan, execution_id=execution_id)
        self._executions[state.id] = state
        return state.model_copy(deep=True)

    async def commit_transition(self, transition: StepTransition) -> ExecutionState:
        """Apply one transition against the stored snapshot and persist it.

        The only write path for execution state: the tracker rejects an illegal
        move and a stale ``expected_version``, so nothing the transition graph
        forbids can reach storage.

        **And a ``→ RUNNING`` claim carries ADR-0249 §8's further condition** — the
        plan the execution runs targets its goal's current revision. The plan and the
        goal are read **inside the same step** as the claim: there is no ``await``
        between the read and the write, so nothing can interleave and no decision is
        taken on a separate read.

        Raises:
            StaleExecutionError: If the stored version has moved on, or a
                ``→ RUNNING`` claim names a plan that does not target its goal's
                current revision.
            IllegalTransitionError: If the move is not legal from the step's current
                status.
            PlanningError: If the execution or step does not exist.
        """
        stored = self._executions.get(transition.execution_id)
        if stored is None:
            msg = f"unknown execution {transition.execution_id}"
            raise PlanningError(msg)
        self._refuse_a_stale_target(stored, transition)
        updated = self._tracker.apply(stored, transition)
        self._executions[updated.id] = updated
        return updated.model_copy(deep=True)

    def _refuse_a_stale_target(self, stored: ExecutionState, transition: StepTransition) -> None:
        """Refuse a ``→ RUNNING`` claim on a plan targeting a stale revision (§8).

        **The store's guard and not the driver's**, in ADR-0014 §5's own words:
        "Optimistic concurrency turns that into a detectable, retryable failure, and
        it belongs to the store because the store is the only place with a total
        order over writes." A plan whose ``targets_revision`` is absent — the one
        route being a row ADR-0249 §12 migrated — names no revision and is therefore
        not driven either.

        Args:
            stored: The execution the transition claims a step of.
            transition: The move being applied.

        Raises:
            StaleExecutionError: If the claim names a plan that does not target its
                goal's current interpretation revision.
        """
        if transition.to_status is not StepStatus.RUNNING:
            return
        plan = self._plans.get(stored.plan_id)
        goal = None if plan is None else self._goals.get(plan.goal_id)
        if plan is None or goal is None:  # pragma: no cover — save_plan refuses an orphan
            return
        if plan.targets_revision != goal.revision:
            msg = (
                f"plan {plan.id} targets revision {plan.targets_revision} and goal "
                f"{goal.id} stands at {goal.revision}: a plan that does not target the "
                f"goal's current understanding is not driven (ADR-0249 §8)"
            )
            raise StaleExecutionError(msg)

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
            attempts=tuple(one.model_copy(deep=True) for one in self._attempts.values()),
        )

    async def delete_goal(self, goal_id: str) -> GoalDeletion:
        """Delete a goal, its plan history and its attempts, unless work is live.

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
        # ADR-0249 §12: the cascade reaches attempts, which **extends** ADR-0014 §5's
        # "a goal the user deletes must not leave its plan history behind" rather than
        # re-promising it. The live-step refusal above is unchanged and keys on a
        # RUNNING step, so an attempt in a non-terminal state does not block a
        # deletion no execution blocks.
        for attempt_id in [one.id for one in self._attempts.values() if one.goal_id == goal_id]:
            del self._attempts[attempt_id]
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

        removed = len(self._goals) + len(self._attempts) + len(self._plans) + len(self._executions)
        self._goals.clear()
        self._attempts.clear()
        self._plans.clear()
        self._executions.clear()
        return removed
