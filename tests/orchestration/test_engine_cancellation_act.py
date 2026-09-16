"""ADR-0261 §§2, 6 and 7 at the engine: the act's answer, its one retry, and the listing.

§14's arms in the halves §13 books on **L2**: arm 1 (a cancellation recorded before the
walk), arm 2 (a cancellation after a claim an earlier turn committed), arm 6's L2 half
(the act has no window, asserted as the absence of every partial state, over the engine),
arm 7 (the post-cancellation prohibition) and arm 10's L2 half (the two surfaces, and
where they part).

**What this lane's act does not do.** On the abandoning path it *"commits no attempt,
computes no ``AttemptOutcome`` and takes no outstanding-effect read of its own"* — §2 and
§3 put all three inside the one call — so every assertion here about an ended attempt's
outcome, and about what was outstanding, is an assertion about what **one store call**
answered and wrote. The listing's ``has_outstanding_effect`` call is the other path and is
this lane's only caller of that member.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import pytest
from test_engine import AT, PATIENT, Harness, NoStepPlanner, tool
from test_engine_goal_association import _associating, _goal, _seed

from ai_assistant.core.errors import ClaimRefused, PlanningError, StaleExecutionError
from ai_assistant.core.types import (
    ActionPlan,
    ActionRequest,
    AssociationVerdict,
    AttemptOutcome,
    AttemptState,
    Disposition,
    GoalAbandonment,
    GoalAttempt,
    GoalStatus,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    PlanStep,
    ProposedAction,
    StepFailure,
    StepStatus,
    StepTransition,
    TurnReference,
)
from ai_assistant.testing import FakeAuditTrail, FakePlanStore

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.protocols import AuditTrail, PlanStore
    from ai_assistant.core.types import ExecutionState, FrozenJson, ToolDefinition, UtcInstant

_GOAL: Final = "goal-booking"
_CAPABILITY: Final = "look_up"
_BOOKING: Final = "book_room"

#: Byte-identical across both turns, which is what makes the second turn's step carry the
#: **same** ``EffectKey`` as the first one's — the premise of a ``COMPLETED`` answer.
_PARAMETERS: Final[dict[str, FrozenJson]] = {"nights": 2}
_OUTPUT: Final[dict[str, FrozenJson]] = {"booking": "bk-9"}


def _reading() -> ToolDefinition:
    """One declaration, whose *side-effecting* flag is deliberately not the point.

    ADR-0261 §6: *"outstanding is the step's status and never the presence of an effect
    key"*, and *"a claimed **read** answers true exactly as a claimed write does"* — so
    every arm below is stated over a tool that performs no effect at all, which is the
    shape a predicate narrowed to side-effecting steps would fail.
    """
    return tool(tool_id="lookup", side_effecting=False, capability=_CAPABILITY)


async def _an_attempt_with_a_claimed_step(  # noqa: PLR0913 — the store, the trail the ruling is recorded in, and the four facts that identify one seeded attempt; every one is a distinct fact about the row being built
    plans: PlanStore,
    trail: AuditTrail,
    *,
    goal_id: str,
    attempt_id: str,
    plan_ordinal: int,
    status: StepStatus,
) -> ExecutionState:
    """Seed one attempt of ``goal_id`` whose single step reached ``status``.

    The claim is committed exactly as an earlier turn's walk commits one — under the
    attempt, carrying its ``bound_tool`` and its ``approval_ref`` — so what the arms below
    read is the durable record a turn leaves and not a hand-made one.
    """
    step = PlanStep(
        id=f"s-{plan_ordinal}",
        intent="look the reservation up",
        capability=_CAPABILITY,
        parameters={"reference": "R-9"},
    )
    plan = ActionPlan(
        id=f"p-{plan_ordinal}",
        goal_id=goal_id,
        steps=(step,),
        created_at=AT,
        targets_revision=1,
    )
    await plans.save_plan(plan)
    state = await plans.start_execution(plan.id)
    await plans.open_attempt(
        GoalAttempt(
            id=attempt_id,
            goal_id=goal_id,
            opened_at=AT,
            plan_ids=(plan.id,),
            execution_ids=(state.id,),
        )
    )
    if status is StepStatus.PENDING:
        return state
    decision = PermissionDecision.from_request(
        ActionRequest(
            tool=_reading(),
            parameters=step.parameters,
            goal=goal_id,
            intended_action=step.intended_action,
            step_id=step.id,
            execution_id=state.id,
        ),
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="arm"),
        id=f"d-{plan_ordinal}",
        decided_at=AT,
    )
    await trail.record(decision)
    claimed = await plans.commit_transition(
        StepTransition(
            execution_id=state.id,
            step_id=step.id,
            to_status=StepStatus.RUNNING,
            expected_version=state.version,
            bound_tool="lookup",
            approval_ref=decision.id,
            attempt_id=attempt_id,
        )
    )
    if status is StepStatus.RUNNING:
        return claimed
    return await plans.commit_transition(
        StepTransition(
            execution_id=claimed.id,
            step_id=step.id,
            to_status=status,
            expected_version=claimed.version,
            failure=(
                StepFailure(
                    message=(
                        "the step was found running with nothing executing it, "
                        "so whether the tool acted is unknown"
                    ),
                    kind=None,
                )
                if status is StepStatus.INDETERMINATE
                else None
            ),
        )
    )


def _harness(plans: FakePlanStore, trail: FakeAuditTrail) -> Harness:
    """An engine over a store a case seeded, planning nothing of its own."""
    return Harness(
        planner=NoStepPlanner(),
        plans=plans,
        trail=trail,
        associator=_associating(AssociationVerdict.CONTINUES),
    )


# --- arms 1 and 7: a cancellation the walk then meets -------------------------


async def test_a_step_claimed_after_the_act_is_refused_and_nothing_is_dispatched() -> None:
    """Arm 1 (§H.4 test 1) and arm 7's first half, over one seeded attempt.

    "Assert the claim is refused with ``ClaimRefused`` … the step stands ``PENDING`` at
    its stored version, and that the act answered ``ABANDONED``." Per the sequencing
    ruling the cancellation is **recorded before the walk**, which is what this is: the
    act runs, and the claim a walk would then make is put to the store directly.

    **And whether the claim names the cancelled attempt or another** (arm 7): a second
    attempt of the same goal is ended by the same act, so a claim naming it is refused
    too — *"a claim of a step of the cancelled attempt's execution is refused whether it
    names that attempt or another"*.
    """
    plans = FakePlanStore(now=lambda: AT)
    trail = FakeAuditTrail()
    harness = _harness(plans, trail)
    goal = await _seed(plans, _goal(_GOAL, "book a room in Lisbon", conversation="conversation-1"))
    state = await _an_attempt_with_a_claimed_step(
        plans, trail, goal_id=_GOAL, attempt_id="a-1", plan_ordinal=1, status=StepStatus.PENDING
    )
    await _an_attempt_with_a_claimed_step(
        plans, trail, goal_id=_GOAL, attempt_id="a-2", plan_ordinal=2, status=StepStatus.PENDING
    )

    assert await harness.engine.abandon_goal(goal.id) is GoalAbandonment.ABANDONED

    # Naming the cancelled attempt: ADR-0255 §3's **state** limb, re-classed onto
    # `ClaimRefused` by §7 — "a user act ended, paused or cancelled this attempt".
    with pytest.raises(ClaimRefused):
        await _claim(plans, state, naming="a-1")
    # Naming **another** attempt, which the same act also cancelled: refused all the
    # same, on the limb that says this attempt never opened this execution — a defect of
    # the walk, so it keeps the plain class §7 leaves it on.
    with pytest.raises(PlanningError) as other:
        await _claim(plans, state, naming="a-2")
    assert not isinstance(other.value, ClaimRefused)
    stored = await plans.get_execution(state.id)
    assert stored is not None
    step = stored.step("s-1")
    assert step is not None
    # "It commits nothing, leaves the step at the status and version it stood at."
    assert step.status is StepStatus.PENDING
    assert stored.version == state.version
    assert harness.invoker.invocations == []
    # Both attempts of the goal are ended by the one act — it is stated over the **set**.
    assert {one.state for one in await plans.attempts_of(_GOAL)} == {AttemptState.CANCELLED}
    closed = await plans.get_goal(_GOAL)
    assert closed is not None
    assert closed.status is GoalStatus.ABANDONED


async def _claim(plans: PlanStore, state: ExecutionState, *, naming: str) -> ExecutionState:
    """The `→ RUNNING` transition a walk would put to the store for this step."""
    return await plans.commit_transition(
        StepTransition(
            execution_id=state.id,
            step_id="s-1",
            to_status=StepStatus.RUNNING,
            expected_version=state.version,
            bound_tool="lookup",
            approval_ref="d-1",
            attempt_id=naming,
        )
    )


# --- arm 2: a claim an earlier turn committed ---------------------------------


async def test_cancelling_over_a_claimed_step_answers_that_an_effect_was_in_flight() -> None:
    """Arm 2 (§H.4 test 2), whole.

    "Assert the step's status is one of ``SUCCEEDED``/``FAILED``/``INDETERMINATE`` and
    **never ``SKIPPED``**, that its ``approval_ref`` is set, that the act answered
    ``ABANDONED_EFFECT_IN_FLIGHT`` over an ``INDETERMINATE`` step, and that the cancelled
    attempt's outcome is ``UNCERTAIN``."

    **The act moves no step and ends no execution** (ADR-0250 §12, ADR-0261 §2): the step
    a claim already carried keeps the status its own disposal gave it, which is what
    *"never ``SKIPPED``"* is a property of — there is no writer to give it one.
    """
    plans = FakePlanStore(now=lambda: AT)
    trail = FakeAuditTrail()
    harness = _harness(plans, trail)
    goal = await _seed(plans, _goal(_GOAL, "book a room in Lisbon", conversation="conversation-1"))
    state = await _an_attempt_with_a_claimed_step(
        plans,
        trail,
        goal_id=_GOAL,
        attempt_id="a-1",
        plan_ordinal=1,
        status=StepStatus.INDETERMINATE,
    )

    answer = await harness.engine.abandon_goal(goal.id)

    assert answer is GoalAbandonment.ABANDONED_EFFECT_IN_FLIGHT
    stored = await plans.get_execution(state.id)
    assert stored is not None
    step = stored.step("s-1")
    assert step is not None
    assert step.status is StepStatus.INDETERMINATE
    assert step.status in {StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.INDETERMINATE}
    assert step.approval_ref == "d-1"
    (attempt,) = await plans.attempts_of(_GOAL)
    assert attempt.state is AttemptState.CANCELLED
    assert attempt.outcome is AttemptOutcome.UNCERTAIN


async def test_the_answer_is_the_predicate_over_the_whole_goal_and_not_this_attempt() -> None:
    """Arm 6's goal-wide limb, and the arm no per-attempt fact can pass.

    "An **older** terminal attempt's ``INDETERMINATE`` step, on a goal whose current
    attempt holds only pending work, answers ``ABANDONED_EFFECT_IN_FLIGHT``" — the act
    ends no attempt on account of it at all, that attempt being terminal already.
    """
    plans = FakePlanStore(now=lambda: AT)
    trail = FakeAuditTrail()
    harness = _harness(plans, trail)
    goal = await _seed(plans, _goal(_GOAL, "book a room in Lisbon", conversation="conversation-1"))
    await _an_attempt_with_a_claimed_step(
        plans,
        trail,
        goal_id=_GOAL,
        attempt_id="a-old",
        plan_ordinal=1,
        status=StepStatus.INDETERMINATE,
    )
    await harness.engine.abandon_goal(goal.id)
    await _reopen(plans)
    await _an_attempt_with_a_claimed_step(
        plans, trail, goal_id=_GOAL, attempt_id="a-new", plan_ordinal=2, status=StepStatus.PENDING
    )
    frozen = await plans.get_attempt("a-old")
    assert frozen is not None

    assert await harness.engine.abandon_goal(_GOAL) is (GoalAbandonment.ABANDONED_EFFECT_IN_FLIGHT)

    by_id = {one.id: one for one in await plans.attempts_of(_GOAL)}
    # The older attempt was terminal already, so the act ends no attempt on its account
    # and leaves it byte-identical — the answer is the goal's and never that attempt's.
    assert by_id["a-old"] == frozen
    assert by_id["a-old"].state is AttemptState.CANCELLED
    assert by_id["a-old"].outcome is AttemptOutcome.UNCERTAIN
    # The current attempt held only pending work, so nothing about **it** was outstanding.
    assert by_id["a-new"].state is AttemptState.CANCELLED
    assert by_id["a-new"].outcome is AttemptOutcome.CANCELLED


async def _reopen(plans: PlanStore) -> None:
    """Take the goal back up, ADR-0250 §13's own act: ``ACTIVE`` over a closed goal.

    §5 rules that the reopen *"leaves the cancelled attempts of the abandonment
    standing"*, which is what makes an **older, already terminal** attempt carrying an
    ``INDETERMINATE`` step a state the corpus actually reaches — and the only one it
    reaches, since ADR-0262 §4 admits no ordinary ending over an unsettled step and
    ``close_goal_abandoned`` computes its own outcome rather than proposing one.
    """
    goal = await plans.get_goal(_GOAL)
    assert goal is not None
    await plans.set_goal_status(
        _GOAL, status=GoalStatus.ACTIVE, at=AT, expected_version=goal.version
    )


# --- arm 6's L2 half: the act has no window -----------------------------------


class _FaultingClosure(FakePlanStore):
    """A store whose closing write fails on its first call and then behaves."""

    def __init__(self, *, now: Any) -> None:
        super().__init__(now=now)
        self.closings = 0
        self.fault: Exception | None = None

    async def close_goal_abandoned(
        self, goal_id: str, /, *, at: UtcInstant, expected_version: int
    ) -> bool:
        self.closings += 1
        fault, self.fault = self.fault, None
        if fault is not None:
            raise fault
        return await super().close_goal_abandoned(goal_id, at=at, expected_version=expected_version)


async def test_a_failing_call_leaves_no_partial_act_and_a_re_run_closes_the_goal() -> None:
    """Arm 6's first limb, over the engine: the act propagates and a retry performs it.

    "A ``close_goal_abandoned`` that raises leaves the goal ``ACTIVE``, every attempt in
    the state it was, ``Goal.version`` unadvanced and **nothing written**; the act
    propagates rather than answering, and a **retry of the act** closes the goal and
    returns the answer."

    The fault is a plain ``PlanningError`` rather than a ``StaleExecutionError``: §2's one
    retry is for the stale class alone, and a store fault is not a lost compare-and-swap.
    """
    plans = _FaultingClosure(now=lambda: AT)
    trail = FakeAuditTrail()
    harness = _harness(plans, trail)
    goal = await _seed(plans, _goal(_GOAL, "book a room in Lisbon", conversation="conversation-1"))
    await _an_attempt_with_a_claimed_step(
        plans, trail, goal_id=_GOAL, attempt_id="a-1", plan_ordinal=1, status=StepStatus.PENDING
    )
    plans.fault = PlanningError("the store lost the write")

    with pytest.raises(PlanningError):
        await harness.engine.abandon_goal(goal.id)

    still = await plans.get_goal(_GOAL)
    assert still is not None
    assert still.status is GoalStatus.ACTIVE
    assert still.version == goal.version
    (attempt,) = await plans.attempts_of(_GOAL)
    assert attempt.state is AttemptState.RUNNING
    assert plans.closings == 1

    assert await harness.engine.abandon_goal(goal.id) is GoalAbandonment.ABANDONED
    assert plans.closings == 2
    closed = await plans.get_goal(_GOAL)
    assert closed is not None
    assert closed.status is GoalStatus.ABANDONED


class _RacingCloser(FakePlanStore):
    """A store that lets one act overtake another around the first closing call.

    ``before`` runs **inside** that call and before it applies — so the
    ``StaleExecutionError`` the act then takes is the store's own compare-and-swap and not
    a scripted one — and ``after`` runs as the refusal leaves, which is ADR-0261 §14 arm
    6's *"between the stale refusal and the re-read"*.
    """

    def __init__(self, *, now: Any) -> None:
        super().__init__(now=now)
        self.closings = 0
        self.before: Any = None
        self.after: Any = None

    async def close_goal_abandoned(
        self, goal_id: str, /, *, at: UtcInstant, expected_version: int
    ) -> bool:
        self.closings += 1
        before, self.before = self.before, None
        after, self.after = self.after, None
        if before is not None:
            await before(self)
        try:
            return await super().close_goal_abandoned(
                goal_id, at=at, expected_version=expected_version
            )
        except StaleExecutionError:
            if after is not None:
                await after(self)
            raise


async def test_an_act_overtaken_by_a_second_closer_answers_already_closed() -> None:
    """Arm 6's concurrent closer: the retry re-reads and never writes ``ABANDONED`` twice.

    "Where a second caller closes the goal between the act's first read and its call, the
    act's ``StaleExecutionError`` retry re-reads, finds the goal closed and answers
    ``ALREADY_CLOSED`` — never a second ``ABANDONED`` write."

    The call count is what pins it: **one** call in the whole act, the retry re-taking the
    act's first-read decision rather than the call.
    """

    async def _close_it_first(plans: _RacingCloser) -> None:
        goal = await plans.get_goal(_GOAL)
        assert goal is not None
        await FakePlanStore.close_goal_abandoned(plans, _GOAL, at=AT, expected_version=goal.version)

    plans = _RacingCloser(now=lambda: AT)
    trail = FakeAuditTrail()
    harness = _harness(plans, trail)
    goal = await _seed(plans, _goal(_GOAL, "book a room in Lisbon", conversation="conversation-1"))
    plans.before = _close_it_first

    assert await harness.engine.abandon_goal(goal.id) is GoalAbandonment.ALREADY_CLOSED

    assert plans.closings == 1


async def test_an_act_overtaken_by_a_deleter_answers_no_such_goal_and_calls_no_second_time() -> (
    None
):
    """Arm 6's concurrent deleter, which pins the retry to the **decision**.

    "Where the goal is deleted between the stale refusal and the re-read, the act answers
    ``NO_SUCH_GOAL`` and **makes no second call at all** — the arm that pins the retry to
    re-taking the act's first-read decision rather than the call."
    """

    async def _engage_it(plans: _RacingCloser) -> None:
        """Advance ``Goal.version`` under the act, so its own call is refused stale."""
        goal = await plans.get_goal(_GOAL)
        assert goal is not None
        await plans.engage_goal(
            _GOAL, at=AT, conversation_id="conversation-2", expected_version=goal.version
        )

    async def _delete_it(plans: _RacingCloser) -> None:
        await plans.delete_goal(_GOAL)

    plans = _RacingCloser(now=lambda: AT)
    trail = FakeAuditTrail()
    harness = _harness(plans, trail)
    goal = await _seed(plans, _goal(_GOAL, "book a room in Lisbon", conversation="conversation-1"))
    plans.before = _engage_it
    plans.after = _delete_it

    assert await harness.engine.abandon_goal(goal.id) is GoalAbandonment.NO_SUCH_GOAL

    assert plans.closings == 1


async def test_a_second_refusal_propagates_and_the_act_ends_there() -> None:
    """§2's bound, stated as a fact about the act rather than as a comment.

    "**A second refusal propagates** and the act ends there, having written nothing either
    time … the bound being deliberate, because a writer that raced the act once can race
    it again and an unbounded act would spin against it." Two calls, and no third.
    """

    class _AlwaysStale(FakePlanStore):
        def __init__(self, *, now: Any) -> None:
            super().__init__(now=now)
            self.closings = 0

        async def close_goal_abandoned(
            self, goal_id: str, /, *, at: UtcInstant, expected_version: int
        ) -> bool:
            del goal_id, at, expected_version
            self.closings += 1
            msg = "the goal has advanced since the caller read it"
            raise StaleExecutionError(msg)

    plans = _AlwaysStale(now=lambda: AT)
    trail = FakeAuditTrail()
    harness = _harness(plans, trail)
    goal = await _seed(plans, _goal(_GOAL, "book a room in Lisbon", conversation="conversation-1"))

    with pytest.raises(StaleExecutionError):
        await harness.engine.abandon_goal(goal.id)

    assert plans.closings == 2
    still = await plans.get_goal(_GOAL)
    assert still is not None
    assert still.status is GoalStatus.ACTIVE


# --- arm 10's L2 half: the two surfaces, and where they part ------------------


async def test_the_act_and_the_listing_say_the_same_thing_and_then_it_clears() -> None:
    """Arm 10, whole, over the two surfaces this lane computes.

    "Abandoning a goal whose **older** attempt holds an ``INDETERMINATE`` step answers
    ``ABANDONED_EFFECT_IN_FLIGHT``, the listing row beside it reads ``effect_in_flight``
    **true**, and no adapter derives either. **And it clears**: once that step is resolved
    ``SUCCEEDED`` the field reads **false**, while the cancelled attempt's ``outcome``
    still reads ``UNCERTAIN``."

    That last pair is the assertion that pins the field to ADR-0255 §6's authoritative
    record rather than to the immutable terminal outcome: a flag derived from the outcome
    could never go false.
    """
    plans = FakePlanStore(now=lambda: AT)
    trail = FakeAuditTrail()
    harness = _harness(plans, trail)
    goal = await _seed(
        plans,
        _goal(_GOAL, "book a room in Lisbon", conversation="conversation-1"),
        engaged_in="conversation-1",
    )
    older = await _an_attempt_with_a_claimed_step(
        plans,
        trail,
        goal_id=_GOAL,
        attempt_id="a-old",
        plan_ordinal=1,
        status=StepStatus.INDETERMINATE,
    )
    await harness.engine.abandon_goal(goal.id)
    await _reopen(plans)
    await _an_attempt_with_a_claimed_step(
        plans, trail, goal_id=_GOAL, attempt_id="a-new", plan_ordinal=2, status=StepStatus.PENDING
    )

    assert await harness.engine.abandon_goal(_GOAL) is (GoalAbandonment.ABANDONED_EFFECT_IN_FLIGHT)
    (row,) = await harness.engine.goals()
    assert row.id == _GOAL
    assert row.status is GoalStatus.ABANDONED
    assert row.effect_in_flight is True

    stored = await plans.get_execution(older.id)
    assert stored is not None
    await plans.commit_transition(
        StepTransition(
            execution_id=stored.id,
            step_id="s-1",
            to_status=StepStatus.SUCCEEDED,
            expected_version=stored.version,
        )
    )

    (cleared,) = await harness.engine.goals()
    assert cleared.effect_in_flight is False
    by_id = {one.id: one for one in await plans.attempts_of(_GOAL)}
    assert by_id["a-old"].outcome is AttemptOutcome.UNCERTAIN


async def test_the_acts_answer_is_a_snapshot_the_listing_is_not_required_to_agree_with() -> None:
    """Arm 10's race, asserted as correct rather than as a defect.

    "Where the step resolves ``SUCCEEDED`` **after** the act's one call and before the
    listing is taken, the act still answers ``ABANDONED_EFFECT_IN_FLIGHT`` and the listing
    reads **false** — R78's *completed* disposition, carried because the act's instant is
    the instant the writes took. **No arm asserts that the two agree across two
    instants.**"
    """
    plans = FakePlanStore(now=lambda: AT)
    trail = FakeAuditTrail()
    harness = _harness(plans, trail)
    goal = await _seed(
        plans,
        _goal(_GOAL, "book a room in Lisbon", conversation="conversation-1"),
        engaged_in="conversation-1",
    )
    running = await _an_attempt_with_a_claimed_step(
        plans, trail, goal_id=_GOAL, attempt_id="a-1", plan_ordinal=1, status=StepStatus.RUNNING
    )

    answer = await harness.engine.abandon_goal(goal.id)
    stored = await plans.get_execution(running.id)
    assert stored is not None
    await plans.commit_transition(
        StepTransition(
            execution_id=stored.id,
            step_id="s-1",
            to_status=StepStatus.SUCCEEDED,
            expected_version=stored.version,
        )
    )

    assert answer is GoalAbandonment.ABANDONED_EFFECT_IN_FLIGHT
    (row,) = await harness.engine.goals()
    assert row.effect_in_flight is False


# --- the listing takes one call per listed goal -------------------------------


class _CountingReads(FakePlanStore):
    """Records which goals the listing asked the outstanding-effect question about."""

    def __init__(self, *, now: Any) -> None:
        super().__init__(now=now)
        self.asked: list[str] = []

    async def has_outstanding_effect(self, goal_id: str, /) -> bool:
        self.asked.append(goal_id)
        return await super().has_outstanding_effect(goal_id)


async def test_the_listing_takes_one_outstanding_effect_call_per_listed_goal() -> None:
    """§6's bound on the *engine's* reads, asserted over the call and over the page.

    "**The engine takes one call per listed goal**, where a walk would call
    ``attempts_of`` then ``get_execution`` over a history ADR-0249 §5 and §12 leave
    append-only and unbounded." *Listed* is the page, not the export: a goal the paging
    arguments left out is a goal no surface is shown, and asking about it would be a read
    the bound exists to prevent.

    **And the answer is read per call and never cached**: the second listing asks again.
    """
    plans = _CountingReads(now=lambda: AT)
    trail = FakeAuditTrail()
    harness = _harness(plans, trail)
    for ordinal in (1, 2, 3):
        await _seed(
            plans,
            _goal(f"g-{ordinal}", f"goal {ordinal}", conversation="conversation-1"),
            engaged_in="conversation-1",
        )
    await _an_attempt_with_a_claimed_step(
        plans, trail, goal_id="g-2", attempt_id="a-2", plan_ordinal=2, status=StepStatus.RUNNING
    )

    page = await harness.engine.goals(limit=2)

    assert [one.id for one in page] == plans.asked
    assert len(plans.asked) == 2
    assert {one.id: one.effect_in_flight for one in page}["g-2"] is True

    plans.asked.clear()
    await harness.engine.goals(limit=2)
    assert len(plans.asked) == 2


# --- arm 7's second half: a completed effect is reported, never re-dispatched --


class _Booking(NoStepPlanner):
    """A planner that mints one act on its first call and repeats it afterwards.

    The ``A`` label indexes ``GoalBrief.actions`` extended by this call's own
    ``PlannerOutput.actions`` (ADR-0265 §4), so every later call finds the same act on the
    brief under ``A1`` and proposes none of its own — which is what makes the two steps
    two attempts at **one** intended action rather than two acts.
    """

    def __init__(self) -> None:
        self.turns = 0

    async def plan(self, goal: Any, **fields: Any) -> Any:
        produced = await super().plan(goal, **fields)
        self.turns += 1
        step = PlanStep(
            id=f"step-{self.turns}",
            intent="book it",
            capability=_BOOKING,
            parameters=_PARAMETERS,
            intended_action="A1",
        )
        return produced.model_copy(
            update={
                "actions": (ProposedAction(intent="book the room"),) if self.turns == 1 else (),
                "plan": produced.plan.model_copy(update={"steps": (step,)}),
            }
        )


async def _books(
    parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
) -> FrozenJson:
    """The callable, which must be reached exactly once across the two turns."""
    del parameters, idempotency_key
    return _OUTPUT


async def test_an_effect_the_cancelled_attempt_completed_is_reported_not_dispatched_again() -> None:
    """Arm 7's second half, end to end over a cancellation and ADR-0250 §13's reopen.

    "An effect the attempt completed answers ``COMPLETED``/``UNCERTAIN`` to a later plan
    of the goal rather than being dispatched again."

    **The act itself withdraws nothing** — ADR-0250 §12 binds verbatim: it *"does not end
    an execution and does not cancel anything in flight"*, and this ADR's own title is
    that a dispatched effect is **reported rather than withdrawn**. What stops the second
    dispatch is the effect row ADR-0259 §2 already holds against the goal, which the
    cancellation neither moves nor invalidates.
    """
    planner = _Booking()
    harness = Harness(
        planner=planner,
        associator=_associating(AssociationVerdict.CONTINUES),
        tools=(tool(tool_id="rooms", capability=_BOOKING),),
        tool_handler=_books,
    )

    conversation = (await harness.conversations.begin(None)).id
    acted = await harness.engine.converse(
        "book the room for the trip", timeout=PATIENT, conversation_id=conversation
    )
    assert acted.step is not None
    assert acted.step.disposition is Disposition.EXECUTED
    goal_id = acted.turn.goal.goal_id if acted.turn is not None else ""

    assert await harness.engine.abandon_goal(goal_id) is GoalAbandonment.ABANDONED

    later = (await harness.conversations.begin(None)).id
    borrowed = await harness.engine.converse(
        "did that booking go through?",
        timeout=PATIENT,
        conversation_id=later,
        reference=TurnReference(goal_id=goal_id),
    )

    assert borrowed.step is not None
    assert borrowed.satisfied_from_earlier == (borrowed.step.step_id,)
    record = next(one for one in borrowed.step.state.steps if one.step_id == borrowed.step.step_id)
    assert record.satisfied_by_step == acted.step.step_id
    assert record.attempts == 0, "nothing ran under it"
    assert len(harness.invoker.invocations) == 1, "the effect was reported, not repeated"
