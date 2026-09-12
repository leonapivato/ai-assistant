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
from ai_assistant.core.types import (
    GoalDeletion,
    GoalQuestionDisposition,
    PlanExport,
    StepStatus,
)
from ai_assistant.planning.execution import PlanExecution
from ai_assistant.planning.goals import advanced, appended, bounded, capped, engaged, settled
from ai_assistant.planning.goals import with_status as _with_status

if TYPE_CHECKING:
    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import (
        ActionPlan,
        AttemptTransition,
        ExecutionState,
        Goal,
        GoalAttempt,
        GoalCandidates,
        GoalQuestion,
        GoalRevision,
        GoalStatus,
        StepTransition,
        UtcInstant,
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
        self._questions: dict[str, GoalQuestion] = {}
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
        # ADR-0249 §2's bound is stated over **the write**, so the opening write takes
        # it too: a goal handed in with more revisions than the ceiling admits is
        # stored trimmed, with the count saying how many went.
        stored = bounded(goal)
        self._goals[stored.id] = stored.model_copy(deep=True)
        return stored.id

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

    def _goal_for_write(self, goal_id: str, expected_version: int, what: str) -> Goal:
        """Read a goal for a compare-and-swap write, or refuse (ADR-0250 §9).

        The read and the comparison happen with no ``await`` between them and the
        caller writes in the same step, so nothing can interleave and no decision is
        taken on a separate read — which is ADR-0014 §5's discipline stated once for
        both of this decision's goal writes rather than twice.

        Args:
            goal_id: The goal to read.
            expected_version: The ``Goal.version`` the caller computed against.
            what: What the caller is about to do, for the refusal message.

        Returns:
            The stored goal.

        Raises:
            StaleExecutionError: If the stored version has moved on.
            PlanningError: If ``goal_id`` names no stored goal.
        """
        stored = self._goals.get(goal_id)
        if stored is None:
            msg = f"cannot {what} unknown goal {goal_id}"
            raise PlanningError(msg)
        if stored.version != expected_version:
            msg = (
                f"goal {goal_id} is at version {stored.version}, not {expected_version}: "
                f"re-read it and recompute the write"
            )
            raise StaleExecutionError(msg)
        return stored

    async def engage_goal(
        self, goal_id: str, /, *, at: UtcInstant, conversation_id: str, expected_version: int
    ) -> Goal:
        """Stamp the goal's engagement, compare-and-swap (ADR-0250 §1, §9).

        The **one** writer of ``last_engaged_at`` and ``last_engaged_in``. It writes
        nothing else, and :attr:`Goal.conversation_id` is never rewritten.

        Raises:
            StaleExecutionError: If the stored version has moved on.
            PlanningError: If ``goal_id`` names no stored goal.
        """
        stored = self._goal_for_write(goal_id, expected_version, "engage")
        updated = engaged(stored, at=at, conversation_id=conversation_id)
        self._goals[updated.id] = updated
        return updated.model_copy(deep=True)

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

        The goal's **only** status-mutation route. It refuses no member of the
        vocabulary, because A10 and A3 write ``ACHIEVED`` and ``BLOCKED`` through this
        same route and a store that refused one would be a second place the vocabulary
        is decided.

        Raises:
            StaleExecutionError: If the stored version has moved on.
            PlanningError: If ``goal_id`` names no stored goal.
        """
        stored = self._goal_for_write(goal_id, expected_version, "set the status of")
        updated = _with_status(stored, status=status)
        self._goals[updated.id] = updated
        return updated.model_copy(deep=True)

    async def candidates_for(self, conversation_id: str, /, *, limit: int) -> GoalCandidates:
        """Return this conversation's candidate goals, capped (ADR-0250 §2, §9).

        Membership is the two-field test §2 states — the goal was **opened in** this
        conversation, or was **last engaged in** it — open or closed alike, so a goal
        carried into a second conversation is a candidate in two of them and in no
        more, because ``last_engaged_in`` holds one value.

        Raises:
            PlanningError: If ``limit`` is not positive.
        """
        return capped(
            (
                goal.model_copy(deep=True)
                for goal in self._goals.values()
                if conversation_id in (goal.conversation_id, goal.last_engaged_in)
            ),
            limit=limit,
        )

    async def record_question(self, question: GoalQuestion, /) -> bool:
        """Write an ``OPEN`` question, or refuse a second on one goal (§9).

        The read of the existing question and the write are one indivisible step:
        there is no ``await`` between them, so two turns of one conversation cannot
        both be admitted against the same goal.

        Raises:
            PlanningError: If ``goal_id`` or ``attempt_id`` names no stored record, or
                this store already holds a question under this ``id``.
        """
        if question.goal_id not in self._goals:
            msg = f"cannot record a question for unknown goal {question.goal_id}"
            raise PlanningError(msg)
        attempt = self._attempts.get(question.attempt_id)
        if attempt is None:
            msg = f"cannot record a question for unknown attempt {question.attempt_id}"
            raise PlanningError(msg)
        if attempt.goal_id != question.goal_id:
            # ADR-0014 §5's closure kept at write time, as `commit_attempt` keeps it
            # for an attempt's own references: `delete_goal` cascades one goal's
            # attempts and questions together, so a question naming *another* goal's
            # attempt outlives that attempt and makes the next export unvalidatable.
            msg = (
                f"question {question.id} names attempt {question.attempt_id}, which "
                f"belongs to goal {attempt.goal_id} and not to {question.goal_id}: a "
                f"question's attempt is one its own goal holds (ADR-0250 §9)"
            )
            raise PlanningError(msg)
        if question.id in self._questions:
            msg = f"question {question.id} already exists"
            raise PlanningError(msg)
        if any(
            held.goal_id == question.goal_id and held.disposition is GoalQuestionDisposition.OPEN
            for held in self._questions.values()
        ):
            return False
        self._questions[question.id] = question.model_copy(deep=True)
        return True

    async def get_question(self, question_id: str, /) -> GoalQuestion | None:
        """Return the question under that id, whatever its disposition (§9)."""
        stored = self._questions.get(question_id)
        return None if stored is None else stored.model_copy(deep=True)

    async def open_question(self, goal_id: str, /) -> GoalQuestion | None:
        """Return that goal's open question, or ``None`` (ADR-0250 §9)."""
        for held in self._questions.values():
            if held.goal_id == goal_id and held.disposition is GoalQuestionDisposition.OPEN:
                return held.model_copy(deep=True)
        return None

    async def outstanding_questions(self) -> tuple[GoalQuestion, ...]:
        """Return every ``OPEN`` question, in ``asked_at`` order (ADR-0250 §9).

        It takes no view of the clock: an expired question is still ``OPEN`` until
        something settles it, and settling it is the caller's (§12).
        """
        return tuple(
            held.model_copy(deep=True)
            for held in sorted(
                (
                    one
                    for one in self._questions.values()
                    if one.disposition is GoalQuestionDisposition.OPEN
                ),
                key=lambda one: (one.asked_at, one.id),
            )
        )

    async def settle_question(
        self, question_id: str, /, *, disposition: GoalQuestionDisposition, at: UtcInstant
    ) -> bool:
        """Settle an ``OPEN`` question, clearing its content (ADR-0250 §9).

        The resolve-once gate: the read, the comparison and the write are one step, so
        one of two racing callers answers ``True`` and the other ``False``, and the
        content is cleared exactly once.

        Raises:
            PlanningError: If ``disposition`` is ``OPEN``, which settles nothing.
        """
        if disposition is GoalQuestionDisposition.OPEN:
            # Refused whatever the question's state, because it is a malformed command
            # rather than a lost race: `settle_question` moves an OPEN question to a
            # terminal member, and OPEN settles nothing (ADR-0250 §9).
            msg = (
                "settle_question moves an OPEN question to a terminal member: OPEN "
                "settles nothing and no disposition is inferred from silence "
                "(ADR-0250 §9, §12)"
            )
            raise PlanningError(msg)
        stored = self._questions.get(question_id)
        if stored is None or stored.disposition is not GoalQuestionDisposition.OPEN:
            return False
        self._questions[question_id] = settled(stored, disposition=disposition, at=at)
        return True

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
        for plan_id in attempt.plan_ids:
            self._refuse_a_dangling_plan(attempt, plan_id)
        for execution_id in attempt.execution_ids:
            self._refuse_a_dangling_execution(attempt, execution_id)
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
        if transition.add_plan_id is not None:
            self._refuse_a_dangling_plan(stored, transition.add_plan_id)
        if transition.add_execution_id is not None:
            self._refuse_a_dangling_execution(stored, transition.add_execution_id)
        updated = advanced(stored, transition)
        self._attempts[updated.id] = updated
        return updated.model_copy(deep=True)

    def _refuse_a_dangling_plan(self, attempt: GoalAttempt, plan_id: str) -> None:
        """Refuse a plan reference that does not resolve under this attempt's goal.

        **ADR-0014 §5's export promise kept at write time rather than repaired at read
        time**, which is the division ADR-0228 §5 already records for ``supersedes``:
        "every ``goal_id``/``plan_id`` referenced by an included record resolves within
        the same export", and an attempt's ``plan_ids`` are such references (ADR-0249
        §11). A store that accepted one it does not hold would produce a ``PlanExport``
        that does not validate — discovered by whoever reads the export back.

        **Under this attempt's own goal, and not merely somewhere in the store.** An
        attempt is of one goal and its plans are that goal's (ADR-0228 §1), and it is
        also what keeps the closure true across a deletion: ``delete_goal`` cascades a
        goal's plans, executions and attempts together, so a reference confined to one
        goal cannot outlive its target.

        Args:
            attempt: The attempt the reference is being written onto.
            plan_id: The plan the write names.

        Raises:
            PlanningError: If the plan is not one this attempt's goal holds.
        """
        plan = self._plans.get(plan_id)
        if plan is None or plan.goal_id != attempt.goal_id:
            msg = (
                f"attempt {attempt.id} names plan {plan_id}, which this store does not "
                f"hold under goal {attempt.goal_id}; an export naming a plan it does "
                "not carry does not validate (ADR-0014 §5, ADR-0249 §11)"
            )
            raise PlanningError(msg)

    def _refuse_a_dangling_execution(self, attempt: GoalAttempt, execution_id: str) -> None:
        """Refuse an execution reference that does not resolve under this goal (§11).

        :meth:`_refuse_a_dangling_plan`'s reasoning over the second reference an
        attempt accumulates, reached through the plan the execution runs.

        Args:
            attempt: The attempt the reference is being written onto.
            execution_id: The execution the write names.

        Raises:
            PlanningError: If the execution is not one this attempt's goal holds.
        """
        state = self._executions.get(execution_id)
        plan = None if state is None else self._plans.get(state.plan_id)
        if plan is None or plan.goal_id != attempt.goal_id:
            msg = (
                f"attempt {attempt.id} names execution {execution_id}, which this store "
                f"does not hold under goal {attempt.goal_id}; an export naming an "
                "execution it does not carry does not validate (ADR-0014 §5)"
            )
            raise PlanningError(msg)

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
            questions=tuple(one.model_copy(deep=True) for one in self._questions.values()),
        )

    async def delete_goal(self, goal_id: str) -> GoalDeletion:
        """Delete a goal, its plan history, its attempts and its questions.

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
        # ADR-0250 §9: and it reaches that goal's questions, **open and terminal
        # alike**. An open question does not block a deletion, on ADR-0073 §5's ruling
        # that "the store deletes what it is told to delete", and `GoalDeletion`
        # reports them exactly as ADR-0249 §12 has it report attempts — which is to say
        # the record carries no count for either.
        for question_id in [one.id for one in self._questions.values() if one.goal_id == goal_id]:
            del self._questions[question_id]
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

        removed = (
            len(self._goals)
            + len(self._attempts)
            + len(self._questions)
            + len(self._plans)
            + len(self._executions)
        )
        self._goals.clear()
        self._attempts.clear()
        self._questions.clear()
        self._plans.clear()
        self._executions.clear()
        return removed
