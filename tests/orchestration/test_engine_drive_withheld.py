"""ADR-0261 §7 at the engine: a refused claim ends the walk and says where the goal stands.

§14's arm 8, in the half §13 books on **L2** — "each of ``DriveWithheld``'s seven members
is produced by the state that names it, the turn **composes a reply**, and no
``Planner.plan`` call is taken on account of the refusal", together with the negative arm
("anything that is not a ``ClaimRefused`` propagates") and the arm that forces the read's
order rather than assuming it.

**Every arm here is engine-level by construction.** The class is raised inside the store,
on the ``→ RUNNING`` claim alone, and the member is decided by a read only the engine
takes — so nothing below ``AssistantEngine`` can assert either, and nothing above it can
see the refusal at all: what a surface is handed is a ``TurnOutcome`` that **returned**.

**How a refusal is produced without racing anything.** :class:`_Interposing` runs one hook
inside the store, in the same instant as the claim's compare-and-swap and before it is
applied, so the state the conjunct reads is the state the hook left. That is the sequencing
ruling's own shape — the user act is *recorded* and the walk then meets it — and it makes
every arm deterministic rather than probabilistic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import pytest
from test_engine import AT, PATIENT, Harness, OneStepPlanner, tool

from ai_assistant.core.errors import ClaimRefused, ClassifiedToolError, PlanningError
from ai_assistant.core.types import (
    AttemptOutcome,
    AttemptState,
    AttemptTransition,
    Disposition,
    DriveWithheld,
    GoalAttempt,
    GoalInterpretation,
    GoalRevision,
    GoalStatus,
    Ground,
    StepStatus,
    ToolFailure,
    ToolFailureKind,
)
from ai_assistant.orchestration.engine import _GOAL_WITHHELD
from ai_assistant.testing import FakePlanStore

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ai_assistant.core.types import ExecutionState, Goal, StepTransition

_ASKED: Final = "send the note"


class _Interposing(FakePlanStore):
    """A store that runs one hook in the same instant as the claim, before it applies.

    The hook is armed once and fires on the **first** ``→ RUNNING`` transition, which is
    this engine's one claim per turn. It runs *inside* the store call, so what the
    conjuncts then read is what it left — no sleep, no task ordering and no race.

    It also counts the claims, which is how "the claim is **not retried**" is asserted as
    a fact about the walk rather than inferred from the answer.
    """

    #: Which ``→ RUNNING`` transition the hook fires on. ``2`` is the **re-claim** a
    #: retry spends (ADR-0037 §6), which is the only instant at which an attempt can be
    #: ``ENDED`` over the step about to be claimed: ADR-0262 §4 admits an ending only
    #: where every step has settled, and ``FAILED`` is both settled and the one settled
    #: status ADR-0014 §4's graph still admits a ``→ RUNNING`` move from.
    on_claim = 1

    def __init__(self, *, now: Callable[[], Any]) -> None:
        super().__init__(now=now)
        self.before_claim: Callable[[_Interposing], Awaitable[None]] | None = None
        self.claims = 0

    async def commit_transition(self, transition: StepTransition) -> ExecutionState:
        if transition.to_status is StepStatus.RUNNING:
            self.claims += 1
            if self.claims == self.on_claim and self.before_claim is not None:
                hook, self.before_claim = self.before_claim, None
                await hook(self)
        return await super().commit_transition(transition)


class _CountingPlanner(OneStepPlanner):
    """``OneStepPlanner`` that counts its calls, for §7's *does not replan*."""

    def __init__(self) -> None:
        super().__init__()
        self.plans = 0

    async def plan(self, *args: Any, **kwargs: Any) -> Any:
        self.plans += 1
        return await super().plan(*args, **kwargs)


async def _only_goal(plans: FakePlanStore) -> Goal:
    """The single goal this turn opened, read off the store's own export."""
    export = await plans.export()
    (goal,) = export.goals
    return goal


async def _only_attempt(plans: FakePlanStore) -> GoalAttempt:
    """The single attempt this turn opened."""
    export = await plans.export()
    (attempt,) = export.attempts
    return attempt


async def _end_the_attempt(plans: FakePlanStore, *, state: AttemptState) -> None:
    """Move this turn's attempt to ``state``, terminal or paused (ADR-0249 §5)."""
    attempt = await _only_attempt(plans)
    terminal = state in {AttemptState.ENDED, AttemptState.CANCELLED}
    versions: list[tuple[str, int]] = []
    for execution_id in attempt.execution_ids:
        execution = await plans.get_execution(execution_id)
        assert execution is not None
        versions.append((execution_id, execution.version))
    await plans.commit_attempt(
        AttemptTransition(
            attempt_id=attempt.id,
            expected_version=attempt.version,
            to_state=state,
            outcome=AttemptOutcome.CANCELLED if terminal else None,
            ended_at=AT if terminal else None,
            # ADR-0262 §4: an ending names every execution the attempt holds.
            execution_versions=tuple(versions) if terminal else (),
        )
    )


async def _close_the_goal(plans: FakePlanStore, *, status: GoalStatus) -> Goal:
    """Write ``status`` over this turn's goal, under its current version."""
    goal = await _only_goal(plans)
    return await plans.set_goal_status(goal.id, status=status, at=AT, expected_version=goal.version)


async def _correct_the_goal(plans: FakePlanStore) -> None:
    """Record a second interpretation, which leaves this turn's plan behind (§8)."""
    goal = await _only_goal(plans)
    await plans.record_interpretation(
        GoalRevision(
            goal_id=goal.id,
            interpretation=GoalInterpretation(
                revision=len(goal.interpretation) + 1,
                outcome="send the other note instead",
                outcome_ground=Ground.USER_STATED,
                outcome_span="the other note",
                recorded_at=AT,
                raised_by="turn-2",
            ),
            expected_version=goal.version,
        )
    )


# --- arm 8: each member is produced by the state that names it ----------------


async def _cancelled(plans: _Interposing) -> None:
    """ADR-0261 §2's act, whole: the attempt ends ``CANCELLED`` and the goal closes."""
    goal = await _only_goal(plans)
    await plans.close_goal_abandoned(goal.id, at=AT, expected_version=goal.version)


async def _blocked(plans: _Interposing) -> None:
    """The same pair over ``BLOCKED``, which ADR-0250 §1 rules **open**.

    "No lane collapses any two of the seven — not ``GOAL_BLOCKED`` with
    ``ATTEMPT_PAUSED``": the attempt here *is* paused, and the member is still the
    goal's, because the goal's three tests are read first.
    """
    await _end_the_attempt(plans, state=AttemptState.AWAITING_CLARIFICATION)
    await _close_the_goal(plans, status=GoalStatus.BLOCKED)


async def _reopened(plans: _Interposing) -> None:
    """The act, then ADR-0250 §13's reopen: a ``CANCELLED`` attempt under an open goal."""
    await _cancelled(plans)
    await _close_the_goal(plans, status=GoalStatus.ACTIVE)


async def _ended(plans: _Interposing) -> None:
    """End the attempt, which ADR-0262 §4 admits only over settled steps (below)."""
    await _end_the_attempt(plans, state=AttemptState.ENDED)


async def _paused(plans: _Interposing) -> None:
    await _end_the_attempt(plans, state=AttemptState.AWAITING_CLARIFICATION)


async def _corrected(plans: _Interposing) -> None:
    """The attempt stays live: what refuses the claim is ADR-0249 §8's revision conjunct."""
    await _correct_the_goal(plans)


@pytest.mark.parametrize(
    ("arrange", "expected"),
    [
        pytest.param(_cancelled, DriveWithheld.GOAL_CANCELLED, id="goal-cancelled"),
        pytest.param(_blocked, DriveWithheld.GOAL_BLOCKED, id="goal-blocked"),
        pytest.param(_reopened, DriveWithheld.ATTEMPT_CANCELLED, id="attempt-cancelled"),
        pytest.param(_paused, DriveWithheld.ATTEMPT_PAUSED, id="attempt-paused"),
        pytest.param(_corrected, DriveWithheld.UNDERSTANDING_CHANGED, id="understanding-changed"),
    ],
)
async def test_each_withheld_member_is_produced_by_the_state_that_names_it(
    arrange: Callable[[_Interposing], Awaitable[None]], expected: DriveWithheld
) -> None:
    """Arm 8: seven states, seven members, and a composed reply beside each.

    **No member is derived from the class**, which is what the pair
    (``GOAL_BLOCKED``/``ATTEMPT_PAUSED``, ``GOAL_CANCELLED``/``ATTEMPT_CANCELLED``) pins:
    one class covers both raisers, and the member is decided by the read alone.
    """
    plans = _Interposing(now=lambda: AT)
    plans.before_claim = arrange
    planner = _CountingPlanner()
    harness = Harness(planner=planner, plans=plans, tools=(tool(),))

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.drive_withheld is expected
    # "The turn then returns a `TurnOutcome` with a composed reply and the refusal
    # **does not fail the turn**."
    assert outcome.reply is not None
    # "No second `Planner.plan` call is taken on account of it."
    assert planner.plans == 1
    # "It … does not retry the claim."
    assert plans.claims == 1


async def test_a_withheld_drive_dispatches_nothing_and_leaves_the_step_where_it_stood() -> None:
    """Arm 8, and arm 1's assertions over the walk: nothing ran, nothing moved.

    §7: the refusal "commits nothing, leaves the step at the status and version it stood
    at, dispatches no further step". **The step is never ``SKIPPED``** — a refused claim
    leaves no disposal at all, so there is no writer to give it one (revision 1 §H.4 test
    2's own words, read from the other side).
    """
    plans = _Interposing(now=lambda: AT)
    plans.before_claim = _cancelled
    harness = Harness(planner=_CountingPlanner(), plans=plans, tools=(tool(),))

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.drive_withheld is DriveWithheld.GOAL_CANCELLED
    # **No `StepOutcome`**: nothing was driven, so the outcome projects none.
    assert outcome.step is None
    # A `ToolInvoker` fake records no entry (arm 1).
    assert harness.invoker.invocations == []
    export = await plans.export()
    (execution,) = export.executions
    step = execution.step("step-1")
    assert step is not None
    # **Never ``SKIPPED``** (revision 1 §H.4 test 2), which `PENDING` says exactly: a
    # refused claim leaves no disposal, so there is no writer to give the step one.
    assert step.status is StepStatus.PENDING
    assert step.approval_ref is None
    assert execution.version == 0


async def test_the_reads_order_is_forced_by_an_act_landing_between_two_of_them() -> None:
    """Arm 8's order arm: the goal is read **last**, and it is the goal that answers.

    "With a ``ClaimRefused`` raised over a live attempt of an ``ACTIVE`` goal, §2's act is
    committed **between the attempt read and the goal read**, and the turn answers
    ``GOAL_CANCELLED`` — the arm that fails against an engine reading the goal first,
    which would answer ``ATTEMPT_CANCELLED`` and tell the user the goal is still open."

    The refusal is the **revision** conjunct's, which is the only raiser that fires over a
    live attempt of an open goal — so at the instant the walk ends, neither the goal test
    nor the attempt test would answer, and what makes them answer is the act this store
    commits as the attempt read returns.
    """
    read_order: list[str] = []

    class _ActsBetweenTheReads(_Interposing):
        async def get_attempt(self, attempt_id: str) -> GoalAttempt | None:
            attempt = await super().get_attempt(attempt_id)
            read_order.append("attempt")
            goal = await _only_goal(self)
            if goal.status is GoalStatus.ACTIVE:
                await self.close_goal_abandoned(goal.id, at=AT, expected_version=goal.version)
            return attempt

        async def get_goal(self, goal_id: str) -> Goal | None:
            read_order.append("goal")
            return await super().get_goal(goal_id)

    plans = _ActsBetweenTheReads(now=lambda: AT)
    plans.before_claim = _corrected
    harness = Harness(planner=_CountingPlanner(), plans=plans, tools=(tool(),))

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.drive_withheld is DriveWithheld.GOAL_CANCELLED
    # The attempt is read before the goal, which is what let the act be seen by the later
    # read. The reverse order would have answered `ATTEMPT_CANCELLED` over a goal the same
    # act closed.
    assert read_order[-2:] == ["attempt", "goal"]
    stored = await _only_attempt(plans)
    assert stored.state is AttemptState.CANCELLED


# --- the two members only a re-claim can meet ---------------------------------


class _UnavailableOnce:
    """Report a failure the tool itself classified as worth repeating (ADR-0032 §1).

    ``RATE_LIMITED`` with nothing committed is ADR-0029 §5's **first** conjunct, and the
    declaration these cases drive is ``Idempotency.NATURAL``, which is its second — so
    the executor spends a **re-claim** rather than leaving the step failed.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, parameters: object, *, idempotency_key: str | None) -> None:
        del parameters, idempotency_key
        self.calls += 1
        raise ClassifiedToolError(
            ToolFailure(kind=ToolFailureKind.RATE_LIMITED, message="the upstream throttled us"),
            effect_may_have_committed=False,
        )


async def _ended_then_achieved(plans: _Interposing) -> None:
    """The attempt ends and the goal is reached — A10's own shape (ADR-0249 §4)."""
    await _ended(plans)
    await _close_the_goal(plans, status=GoalStatus.ACHIEVED)


@pytest.mark.parametrize(
    ("arrange", "expected", "status"),
    [
        pytest.param(_ended, DriveWithheld.ATTEMPT_ENDED, GoalStatus.ACTIVE, id="attempt-ended"),
        pytest.param(
            _ended_then_achieved,
            DriveWithheld.GOAL_ACHIEVED,
            GoalStatus.ACHIEVED,
            id="goal-achieved",
        ),
    ],
)
async def test_a_re_claim_under_an_ended_attempt_is_withheld(
    arrange: Callable[[_Interposing], Awaitable[None]],
    expected: DriveWithheld,
    status: GoalStatus,
) -> None:
    """Arm 8's two remaining states, at the one instant the corpus lets them exist.

    **Why these two are shaped as a retry and the other five are not.** ADR-0262 §4 admits
    an attempt's ending only where *"every step of its executions has settled
    ``SUCCEEDED``, ``FAILED`` or ``SKIPPED``"*, and ADR-0262 §5 refuses an ``→ ACHIEVED``
    write over a goal holding a live attempt — so neither an ``ENDED`` attempt nor an
    ``ACHIEVED`` goal can stand beside a ``PENDING`` step of that attempt's execution. Of
    the three settled statuses, ADR-0014 §4's graph admits a ``→ RUNNING`` move from
    ``FAILED`` alone, so **the re-claim a retry spends is the only claim either state can
    refuse** — and it is a real claim: *"each **re-claim** a retry spends … is its own
    ``→ RUNNING`` transition"* (ADR-0255 §3, as the executor states it).

    **And ``ATTEMPT_ENDED`` leaves its goal ``ACTIVE``**, which is the whole of what it
    says beside ``GOAL_CANCELLED``: ADR-0249 §4 rules that *"an attempt reaching a
    terminal state **does not** move the goal's status"*, so asking again starts a new
    one rather than reopening anything.
    """
    plans = _Interposing(now=lambda: AT)
    plans.on_claim = 2
    plans.before_claim = arrange
    planner = _CountingPlanner()
    handler = _UnavailableOnce()
    harness = Harness(planner=planner, plans=plans, tools=(tool(),), tool_handler=handler)

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.drive_withheld is expected
    assert outcome.reply is not None
    assert planner.plans == 1
    # The first claim landed and its call was made; the **re-claim** was refused, and
    # nothing retried it again.
    assert plans.claims == 2
    assert handler.calls == 1
    goal = await _only_goal(plans)
    assert goal.status is status
    stored = await _only_attempt(plans)
    assert stored.state is AttemptState.ENDED


# --- arm 8's negative: anything that is not a `ClaimRefused` propagates --------


async def _a_successor_plan(plans: _Interposing) -> None:
    """Save a plan that supersedes the one this execution runs (ADR-0255 §3, §5).

    §7 is explicit that this limb *"stays on the non-stale ``PlanningError`` that section
    gives them and none is caught"*: a walk claiming a step of a superseded plan is **the
    turn's own defect**, because ADR-0228 §5 makes ``supersedes`` a same-turn mark and
    ADR-0255 §5 rules that a superseded plan *"drives nothing"*.
    """
    export = await plans.export()
    (plan,) = export.plans
    await plans.save_plan(
        plan.model_copy(update={"id": f"{plan.id}-successor", "supersedes": plan.id})
    )


async def _a_second_owner(plans: _Interposing) -> None:
    """Open a second attempt of the goal naming this execution (ADR-0255 §3, limb 4).

    "Nothing in the record says which owns it, and picking one would invent an ownership
    nobody recorded" — a defect, not a user act.
    """
    export = await plans.export()
    (plan,) = export.plans
    (execution,) = export.executions
    await plans.open_attempt(
        GoalAttempt(
            id="attempt-second-owner",
            goal_id=plan.goal_id,
            opened_at=AT,
            plan_ids=(plan.id,),
            execution_ids=(execution.id,),
        )
    )


@pytest.mark.parametrize(
    "arrange",
    [
        pytest.param(_a_successor_plan, id="a-step-of-a-superseded-plan"),
        pytest.param(_a_second_owner, id="two-attempts-owning-one-execution"),
    ],
)
async def test_a_refusal_that_is_not_a_claim_refused_propagates_over_a_closed_goal(
    arrange: Callable[[_Interposing], Awaitable[None]],
) -> None:
    """Arm 8's negative, "each stated over a goal whose own state would have answered".

    The goal is moved ``BLOCKED`` in the same instant — one of the three states the arm
    names — so ``GOAL_BLOCKED`` was there for the taking, and it is not taken: the class
    says *a defect of the walk* rather than *a user act*. **No report stands in for a
    defect**, and the turn does not return at all, a propagating refusal being outside
    ``drive_withheld``'s invariant rather than a case of it.

    **The goal is moved and the attempt is left live**, deliberately: ADR-0255 §3's
    *state* limb is evaluated before both of these, so an attempt a user act had ended
    would raise ``ClaimRefused`` first and this arm would assert nothing about the limb
    it names.
    """

    async def _both(plans: _Interposing) -> None:
        await arrange(plans)
        await _close_the_goal(plans, status=GoalStatus.BLOCKED)

    plans = _Interposing(now=lambda: AT)
    plans.before_claim = _both
    harness = Harness(planner=_CountingPlanner(), plans=plans, tools=(tool(),))

    with pytest.raises(PlanningError) as raised:
        await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert not isinstance(raised.value, ClaimRefused)
    assert harness.invoker.invocations == []


async def test_a_claim_refused_whose_state_the_read_cannot_see_propagates() -> None:
    """§7's own case: the class arrives, the read establishes nothing, no member is minted.

    "Where a ``ClaimRefused`` arrives but the read establishes no state, it propagates
    too" — *"a turn reporting one of those as a withheld drive would assert something
    about the step that nothing established"*. The refusal here is a genuine
    ``ClaimRefused`` from ADR-0249 §8's revision conjunct; what the read cannot do is
    reach the goal, because the plan the execution runs has gone.
    """

    class _ForgetsThePlan(_Interposing):
        """Forgets the plan **after** the claim, so the walk reaches the refusal first."""

        blind = False

        async def get_plan(self, plan_id: str) -> Any:
            return None if self.blind else await super().get_plan(plan_id)

    async def _correct_and_blind(plans: _Interposing) -> None:
        await _corrected(plans)
        plans.blind = True  # type: ignore[attr-defined]  # the subclass's own flag

    plans = _ForgetsThePlan(now=lambda: AT)
    plans.before_claim = _correct_and_blind
    harness = Harness(planner=_CountingPlanner(), plans=plans, tools=(tool(),))

    with pytest.raises(ClaimRefused):
        await harness.engine.converse(_ASKED, timeout=PATIENT)


async def test_a_turn_that_dispatched_carries_no_withheld_member() -> None:
    """The invariant's other half: ``None`` on every turn that drove (ADR-0261 §7)."""
    harness = Harness(tools=(tool(),))

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.step is not None
    assert outcome.step.disposition is Disposition.EXECUTED
    assert outcome.drive_withheld is None


# --- the one goal test the engine reaches by division rather than by name -----


def test_the_goal_test_the_engine_does_not_name_is_exactly_achieved() -> None:
    """The remainder ADR-0250 §1's division leaves is one member, and it is ``ACHIEVED``.

    ``Engine`` reaches ADR-0261 §7's third goal test as *"closed and not ``ABANDONED``"*
    rather than by naming ``GoalStatus.ACHIEVED``, because ADR-0249 §16 item 7's guard
    over ``src/`` reports every mention of that member and cannot tell this lane's **read**
    from A10's **write** — and ADR-0261 §12 records ADR-0249 §4 as superseded in nothing,
    so the guard is left exactly as it stands.

    **This is what keeps that spelling honest.** The division is ADR-0250 §1's and is
    stated over four members; a fifth, closed one would otherwise reach ``GOAL_ACHIEVED``
    by silence and tell a user their goal was reached. Here the remainder is pinned, so
    such a member fails this arm rather than the user.

    The member itself is produced end to end by
    :func:`test_a_re_claim_under_an_ended_attempt_is_withheld`, over a goal a real
    ``set_goal_status`` write reached.
    """
    unnamed = set(GoalStatus) - set(_GOAL_WITHHELD) - {GoalStatus.ACTIVE}

    assert unnamed == {GoalStatus.ACHIEVED}
