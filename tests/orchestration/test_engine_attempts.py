"""ADR-0249 §5, §6, §11 and §12 at the engine: the attempt is opened, stamped and ended.

The attempt-shaped half of §16's L3 arms. Every one of them is engine-level by
construction: ``LearningLoop`` holds no ``PlanStore`` and gains none (ADR-0228 §5), so
the attempt is opened **in memory** by the loop and every write of it is this
component's, at the one site that persists a plan today (§11).

What lives here is §16 item 1's attempt half (S1's six phase stamps, its stored row and
the goal's status), item 14's second clause (a turn that reaches the site records what it
actually finished on), item 19 within a turn, and §12's two-route persistence — a goal
this turn opened through ``save_goal``, a goal the store already holds through
``record_interpretation`` under the compare-and-swap.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from test_engine import (
    AT,
    PATIENT,
    Harness,
    NoStepPlanner,
    OneStepPlanner,
    confirmable,
    tool,
)
from test_engine_composing import _GatedProvider, _refusing
from test_engine_read_envelope import _recorder

from ai_assistant.core.errors import PlanningError, ToolError, UngrantableActError
from ai_assistant.core.types import (
    AttemptEffort,
    AttemptOutcome,
    AttemptPhase,
    AttemptState,
    Disposition,
    Goal,
    GoalAttempt,
    GoalInterpretation,
    GoalStatus,
    Ground,
    MemorySource,
    ProposedElement,
    ProposedUnderstanding,
    Provenance,
    StepStatus,
)
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.loop import OpenedAttempt
from ai_assistant.orchestration.runner import StepDisposition
from ai_assistant.testing import (
    FakeModelProvider,
    FakePlanStore,
    FakeRecipientGrantStore,
    FakeStreamingCompleter,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ai_assistant.core.types import AttemptTransition, GoalRevision
    from ai_assistant.orchestration.loop import RespondedTurn

_ASKED: Final = "what is two plus two?"

#: The phases a turn stamps **at the store**: the one the row is opened at, then one per
#: ``commit_attempt``. The three before it — ``UNDERSTAND``, ``INVESTIGATE`` and ``PLAN``
#: — are stamped in memory by the loop before any row exists to carry them, and are
#: asserted there (``test_loop_understanding``). §12's own rule is what joins the two
#: halves into §16 item 1's six: "§6 makes the order fixed and monotonic, so the phases an
#: attempt has passed are exactly those at or before its current one".
_STORED_PHASES: Final = [
    AttemptPhase.PLAN,
    AttemptPhase.AUTHORIZE,
    AttemptPhase.EXECUTE,
    AttemptPhase.VERIFY,
]


class _Recording(FakePlanStore):
    """The canonical store, recording the attempt writes it was asked for.

    §6 makes the six phases "six responsibilities and **six observable transitions**",
    and three of a turn's six happen before any row exists to observe them on — so what
    a case can see at the store is the phase the row was **opened** at and each
    ``to_phase`` after it. Together they are the sequence the attempt occupied.
    """

    def __init__(self) -> None:
        super().__init__(now=lambda: AT)
        self.opened: list[GoalAttempt] = []
        self.moves: list[AttemptTransition] = []
        self.appended: list[GoalRevision] = []

    async def open_attempt(self, attempt: GoalAttempt) -> str:
        """Record and delegate."""
        self.opened.append(attempt)
        return await super().open_attempt(attempt)

    async def commit_attempt(self, transition: AttemptTransition) -> GoalAttempt:
        """Record and delegate."""
        self.moves.append(transition)
        return await super().commit_attempt(transition)

    async def record_interpretation(self, revision: GoalRevision) -> Goal:
        """Record and delegate."""
        self.appended.append(revision)
        return await super().record_interpretation(revision)

    @property
    def phases(self) -> list[AttemptPhase]:
        """Every phase the attempt was stamped with at this store, in order."""
        return [one.phase for one in self.opened] + [
            move.to_phase for move in self.moves if move.to_phase is not None
        ]


# --------------------------------------------------------------------------- #
# §16 item 1 — S1, end to end                                                  #
# --------------------------------------------------------------------------- #


async def test_a_plain_question_passes_through_all_six_phases_on_one_planner_call() -> None:
    """§16 item 1 (S1): six phase stamps, and the stored row ends ``ANSWERED``.

    "*What is two plus two?* on a conversation's first turn: … **one** ``Planner.plan``
    call and **one** composing call, which is exactly today's cost; six phase stamps; no
    read request; no question; the attempt passing through all six phases and its
    **stored** row ending at ``VERIFY``/``ENDED``/``ANSWERED``, written first at §11's
    site and moved there by a same-turn ``commit_attempt`` once the answer exists; and
    the goal's status still **``ACTIVE``**."

    §6 is why the vacuous ones are stamped at all: "no phase mandates a model call, a
    store read, a park or a user interaction", and "a turn that answers a plain question
    passes through all six phases on one planner call".
    """
    plans = _Recording()
    planner = NoStepPlanner()
    composing, model = _recorder()
    harness = Harness(planner=planner, plans=plans, composing=composing)

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.turn is not None
    assert planner._calls == 1, "one Planner.plan call, which is exactly today's cost"
    assert len(model.calls) == 1, "and one composing call"
    assert outcome.turn.plan.read_request is None, "no read request"
    assert outcome.turn.goal.open_questions == (), "and no question"
    assert plans.phases == _STORED_PHASES, "in §6's order, and never backwards"
    assert plans.appended == [], "§12: an opened goal's revisions ride on save_goal"
    (stored,) = plans.opened
    assert stored.phase is AttemptPhase.PLAN, "written carrying the phase it stood at"
    assert stored.state is AttemptState.RUNNING
    assert (stored.outcome, stored.ended_at) == (None, None), "nothing claimed in advance"
    attempt = await harness.plans.get_attempt(stored.id)
    assert attempt is not None
    assert attempt.phase is AttemptPhase.VERIFY
    assert attempt.state is AttemptState.ENDED
    assert attempt.outcome is AttemptOutcome.ANSWERED
    assert attempt.ended_at == AT
    goal = await harness.plans.get_goal(outcome.turn.goal.goal_id)
    assert goal is not None
    assert goal.status is GoalStatus.ACTIVE, "§4: ACHIEVED gets no producer here"


async def test_the_attempt_references_the_plans_the_turn_produced() -> None:
    """§5: "plans, executions and authorizations are referenced by id and never inlined".

    ADR-0228 §5 persists **every** plan a turn produced, so the attempt references the
    whole sequence — and the reference resolves, which is what ``open_attempt`` refuses
    an attempt for when it does not (§12).
    """
    plans = _Recording()
    harness = Harness(planner=NoStepPlanner(), plans=plans)

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.turn is not None
    (stored,) = plans.opened
    assert stored.plan_ids == (outcome.turn.plan.id,)
    assert stored.execution_ids == (), "a no-action turn opened none"
    assert stored.effort.planner_calls == 1, "§5's ledger: the one call this turn made"


async def test_a_driving_turn_appends_its_execution_and_ends_answered() -> None:
    """§16 items 1 and 19 over a turn with a step, and §5's ``ANSWERED``.

    "An attempt the store already holds takes a plan id, then an execution id … the first
    two inside the turn that opened it, each appended in order." The execution id reaches
    the row through ``commit_attempt`` "at the moment the fact becomes true" — which is
    after ``start_execution`` and never before it.
    """
    plans = _Recording()
    harness = Harness(tools=(tool(),), plans=plans)

    outcome = await harness.engine.converse("send it", timeout=PATIENT)

    assert outcome.step is not None
    assert outcome.step.disposition is Disposition.EXECUTED
    assert plans.phases == _STORED_PHASES
    (stored,) = plans.opened
    assert stored.execution_ids == (), "not claimed in advance"
    attempt = await harness.plans.get_attempt(stored.id)
    assert attempt is not None
    assert attempt.execution_ids == (outcome.step.state.id,)
    assert attempt.state is AttemptState.ENDED
    assert attempt.outcome is AttemptOutcome.ANSWERED


async def test_a_revising_turn_drives_its_step(  # §16 item 20 at the engine
) -> None:
    """§16 item 20's consequence: "so the plan is **driveable**".

    A turn that recorded a revision holds a plan targeting revision 2, and §8 puts the
    stale-target refusal inside ``commit_transition``'s ``→ RUNNING`` claim — so this
    arm fails if the goal reaches the store at a revision the plan does not name, which
    is exactly what stamping the *input* revision, or persisting the goal before the
    revision was appended, would produce.
    """
    plans = _Recording()
    harness = Harness(planner=_DrivingContinuing(), plans=plans, tools=(tool(),))

    outcome = await harness.engine.converse("two plus two", timeout=PATIENT)

    assert outcome.step is not None
    assert outcome.step.disposition is Disposition.EXECUTED, "the claim was not refused"
    assert outcome.turn is not None
    assert outcome.turn.plan.targets_revision == 2
    stored = await plans.get_goal(outcome.turn.goal.goal_id)
    assert stored is not None
    assert stored.revision == 2


async def test_a_failed_step_ends_no_attempt() -> None:
    """§5: ``ANSWERED`` "asserts … that **no step failed**", read off the execution.

    :attr:`~ai_assistant.core.types.Disposition.EXECUTED` says the tool was *reached*,
    not that it succeeded — a tool that raises leaves that disposition beside a step
    whose :class:`~ai_assistant.core.types.StepStatus` is ``FAILED``. **Which
    ``AttemptOutcome`` such an attempt earns is A10's** (§13), so this lane writes none:
    the attempt stands at ``VERIFY``, still ``RUNNING``, which is §4's stated cost taken
    rather than an outcome nothing established.
    """

    async def _fails(parameters: object, *, idempotency_key: str | None) -> None:
        del parameters, idempotency_key
        msg = "the mail server refused it"
        raise ToolError(msg)

    plans = _Recording()
    harness = Harness(tools=(tool(),), plans=plans, tool_handler=_fails)

    outcome = await harness.engine.converse("send it", timeout=PATIENT)

    assert outcome.step is not None
    assert outcome.step.state.step("step-1") is not None
    assert outcome.step.state.step("step-1").status is StepStatus.FAILED  # type: ignore[union-attr]
    (stored,) = plans.opened
    attempt = await harness.plans.get_attempt(stored.id)
    assert attempt is not None
    assert attempt.phase is AttemptPhase.VERIFY, "the phase says where it stands"
    assert attempt.state is AttemptState.RUNNING, "and it did not end"
    assert attempt.outcome is None
    assert attempt.ended_at is None


async def test_a_turn_whose_composition_failed_ends_no_attempt() -> None:
    """§5: ``ANSWERED`` "asserts that **a reply exists**".

    ADR-0173 §8 degrades a classified composition failure rather than raising, so the
    turn returns with ``reply`` absent and ``reply_degraded`` set — and an attempt
    claiming it produced an answer would be a durable record of something that did not
    happen, which is what §12's "no lane writes an attempt that claims a result before it
    happened" rules out.
    """
    plans = _Recording()
    stage = ComposingStage(model=FakeModelProvider(_refusing), streaming=FakeStreamingCompleter())
    harness = Harness(planner=NoStepPlanner(), plans=plans, composing=stage)

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.reply is None
    assert outcome.reply_degraded is True
    (stored,) = plans.opened
    attempt = await harness.plans.get_attempt(stored.id)
    assert attempt is not None
    assert attempt.phase is AttemptPhase.VERIFY
    assert attempt.state is AttemptState.RUNNING
    assert attempt.outcome is None


async def test_a_parked_attempt_waits_and_then_moves_on_when_the_user_approves() -> None:
    """§5, §6, §12: the waiting state is written, and the resumption leaves it.

    §5 calls a goal paused when "its current attempt's state is
    ``AWAITING_CLARIFICATION``, ``AWAITING_AUTHORIZATION`` or ``BLOCKED``", and §12
    requires every later fact to reach the stored attempt through ``commit_attempt``,
    "**in this turn as in any later one**". A resumption is that later one: the attempt
    already exists and already references this execution, so moving it is bookkeeping
    rather than an association — §13's deferral of *which user acts open an attempt* is
    untouched, because none is opened here.

    Asserted over the **same stored attempt** before and after the approval, which is
    the only way the two halves can be shown to be about one record.
    """
    plans = _Recording()
    harness = Harness(tools=(confirmable(),), plans=plans)

    parked = await harness.engine.converse("send it", timeout=PATIENT)

    assert parked.step is not None
    assert parked.step.confirmation is not None, "the step parked"
    (stored,) = plans.opened
    waiting = await harness.plans.get_attempt(stored.id)
    assert waiting is not None
    assert waiting.phase is AttemptPhase.AUTHORIZE, "the authorisation has not been given"
    assert waiting.state is AttemptState.AWAITING_AUTHORIZATION
    assert (waiting.outcome, waiting.ended_at) == (None, None)
    assert parked.step.state.id in waiting.execution_ids, "the reference it is found by"

    resumed = await harness.engine.resume(
        parked.step.confirmation.token, approved=True, timeout=PATIENT
    )

    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.EXECUTED
    moved = await harness.plans.get_attempt(stored.id)
    assert moved is not None
    assert moved.phase is AttemptPhase.VERIFY, "EXECUTE and VERIFY, in §6's order"
    assert moved.state is AttemptState.ENDED
    assert moved.outcome is AttemptOutcome.ANSWERED
    assert moved.ended_at == AT


async def test_a_cancellation_during_composition_leaves_the_attempt_out_of_waiting() -> None:
    """§12: "at the moment the fact becomes true", and composing is not that moment.

    Composing runs **outside** the resolution's lock and is an arbitrarily slow model
    call, so a cancellation can land in it after the step has already executed. A
    bookkeeping commit that waited for the answer would leave an attempt whose step has
    run still recorded as awaiting the user's approval — and the token now **restates**
    rather than resolving, so nothing would ever repair it.

    The half that does depend on the answer is not committed, which is correct: no answer
    exists, so ``ANSWERED`` is not true and ``VERIFY`` is not where the attempt stands.

    **And the approval reference is already on the row, not waiting behind the
    composition.** ``StepExecution.approval_ref`` is durable the moment the step is
    claimed, so an attempt that collected it at the finishing commit alone would leave a
    ``SUCCEEDED`` execution whose decision never reached
    :attr:`~ai_assistant.core.types.GoalAttempt.authorization_ids`, and a replay restates
    without repairing it. ADR-0014 §5's "a claimed step must be traceable to the decision
    that allowed it" is what that loses.
    """
    plans = _Recording()
    provider = _GatedProvider()
    stage = ComposingStage(model=provider, streaming=FakeStreamingCompleter())
    harness = Harness(tools=(confirmable(),), plans=plans, composing=stage)
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    resuming = asyncio.create_task(
        harness.engine.resume(parked.step.confirmation.token, approved=True, timeout=PATIENT)
    )
    await asyncio.wait_for(provider.entered.wait(), timeout=5)

    resuming.cancel()
    with pytest.raises(asyncio.CancelledError):
        await resuming

    (stored,) = plans.opened
    attempt = await harness.plans.get_attempt(stored.id)
    assert attempt is not None
    assert attempt.state is AttemptState.RUNNING, "the user answered, so it is not waiting"
    assert attempt.phase is AttemptPhase.EXECUTE, "and the step it stamps really did run"
    assert attempt.outcome is None, "no answer exists, so none is claimed"
    executed = await harness.plans.get_execution(attempt.execution_ids[0])
    assert executed is not None
    claimed = executed.step("step-1")
    assert claimed is not None
    assert claimed.status is StepStatus.SUCCEEDED
    assert claimed.approval_ref is not None
    assert claimed.approval_ref in attempt.authorization_ids, "the approval survived"


async def test_a_refused_confirmation_leaves_the_attempt_unended() -> None:
    """§5: a condition blocked, so ``ANSWERED`` is not true of this pass.

    The attempt still leaves ``AWAITING_AUTHORIZATION`` — the user answered, so it is no
    longer waiting on them — and stands at ``VERIFY`` with no outcome, because **which
    ``AttemptOutcome`` a refused act earns is A10's** (§13).
    """
    plans = _Recording()
    harness = Harness(tools=(confirmable(),), plans=plans)
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None

    resumed = await harness.engine.resume(
        parked.step.confirmation.token, approved=False, timeout=PATIENT
    )

    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.DENIED
    (stored,) = plans.opened
    moved = await harness.plans.get_attempt(stored.id)
    assert moved is not None
    assert moved.phase is AttemptPhase.VERIFY
    assert moved.state is AttemptState.RUNNING, "no longer waiting, and not ended"
    assert (moved.outcome, moved.ended_at) == (None, None)


def test_the_ledger_never_decreases_when_the_clock_goes_backwards() -> None:
    """§5: "monotonically non-decreasing … and no implementation subtracts from one".

    The injected clock supplies wall-clock instants and guarantees no monotonicity
    (ADR-0009), so an adjustment backwards would otherwise make the interval negative —
    which :class:`~ai_assistant.core.types.AttemptEffort` refuses at construction and
    ``commit_attempt`` refuses as a reduction. A backward reading contributes nothing
    rather than failing a turn that has already answered.
    """
    harness = Harness(planner=NoStepPlanner())
    held = OpenedAttempt(
        attempt=GoalAttempt(
            id="a-1",
            goal_id="g-1",
            opened_at=AT,
            effort=AttemptEffort(working=timedelta(seconds=5)),
        )
    )

    backwards = harness.engine._worked(held, AT + timedelta(minutes=1))
    forwards = harness.engine._worked(held, AT - timedelta(seconds=30))

    assert backwards == timedelta(seconds=5), "unchanged, and never negative"
    assert forwards == timedelta(seconds=35), "and it does accumulate the other way"


async def test_the_ledger_covers_the_driving_and_composing_the_turn_stage_did_not() -> None:
    """§5: ``working`` accumulates the attempt's **working** intervals.

    The turn stage's own interval is stamped by the loop; everything after it —
    ``start_execution``, the drive, the composition — is this component's, and a ledger
    that stopped at the planner would permanently under-report an attempt that did work.
    Driven with a clock that advances a second per reading, so the figure is a property
    of the accounting rather than of how long the test took.
    """
    reading = 0

    def advancing() -> datetime:
        nonlocal reading
        reading += 1
        return AT + timedelta(seconds=reading)

    plans = _Recording()
    harness = Harness(tools=(tool(),), plans=plans, now=advancing)

    outcome = await harness.engine.converse("send it", timeout=PATIENT)

    assert outcome.step is not None
    (stored,) = plans.opened
    attempt = await harness.plans.get_attempt(stored.id)
    assert attempt is not None
    assert attempt.effort.working > timedelta(0), "the drive and the composition are counted"
    assert attempt.effort.planner_calls == 1, "and the loop's own counter survives"


async def test_the_attempt_records_the_decision_its_step_was_claimed_under() -> None:
    """§5: "the authorizations it took", referenced by id and never inlined.

    ADR-0014 §5 requires that "a claimed step must be traceable to the decision that
    allowed it", and ``StepExecution.approval_ref`` is where that decision's id already
    sits — so the attempt's own record of what it was allowed to do is **that**
    identifier, resolved against the trail rather than minted here.
    """
    plans = _Recording()
    harness = Harness(tools=(tool(),), plans=plans)

    outcome = await harness.engine.converse("send it", timeout=PATIENT)

    assert outcome.step is not None
    state = outcome.step.state.step("step-1")
    assert state is not None
    assert state.approval_ref is not None, "the step was claimed under a decision"
    (stored,) = plans.opened
    attempt = await harness.plans.get_attempt(stored.id)
    assert attempt is not None
    assert attempt.authorization_ids == (state.approval_ref,)
    assert await harness.trail.get(state.approval_ref) is not None, "and it resolves"


async def test_a_resumption_records_the_decision_the_user_just_gave() -> None:
    """§5, §12: appended, not replacing — the parked `CONFIRM` and the answer are two.

    "An ``add_*`` member **appends** its identifier to the corresponding tuple; an
    identifier the tuple already holds is **ignored** rather than duplicated or refused",
    so a resumption contributes the decision *it* recorded beside the one the parked turn
    took.
    """
    plans = _Recording()
    harness = Harness(tools=(confirmable(),), plans=plans)
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    (stored,) = plans.opened
    waiting = await harness.plans.get_attempt(stored.id)
    assert waiting is not None

    resumed = await harness.engine.resume(
        parked.step.confirmation.token, approved=True, timeout=PATIENT
    )

    assert resumed.step is not None
    state = resumed.step.state.step("step-1")
    assert state is not None
    assert state.approval_ref is not None
    attempt = await harness.plans.get_attempt(stored.id)
    assert attempt is not None
    assert state.approval_ref in attempt.authorization_ids
    assert len(set(attempt.authorization_ids)) == len(attempt.authorization_ids), "no duplicate"


async def test_a_cancellation_inside_the_tool_leaves_the_attempt_out_of_waiting() -> None:
    """§12: the attempt leaves waiting when the **user answers**, not when the tool returns.

    The runner may hold an arbitrarily slow tool, so a cancellation can land while the
    step is already ``RUNNING``. An attempt still recorded as awaiting the user's approval
    there is a durable misrecord that nothing repairs — the token now **restates** rather
    than resolving — and §12 puts each commit "at the moment the fact becomes true".
    """
    entered = asyncio.Event()
    release = asyncio.Event()

    async def _gated(parameters: object, *, idempotency_key: str | None) -> None:
        del parameters, idempotency_key
        entered.set()
        await release.wait()

    plans = _Recording()
    harness = Harness(tools=(confirmable(),), plans=plans, tool_handler=_gated)
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    resuming = asyncio.create_task(
        harness.engine.resume(parked.step.confirmation.token, approved=True, timeout=PATIENT)
    )
    await asyncio.wait_for(entered.wait(), timeout=5)

    resuming.cancel()
    with pytest.raises(asyncio.CancelledError):
        await resuming
    release.set()

    (stored,) = plans.opened
    attempt = await harness.plans.get_attempt(stored.id)
    assert attempt is not None
    assert attempt.state is AttemptState.RUNNING, "the user answered, so it is not waiting"
    assert attempt.phase is AttemptPhase.EXECUTE


async def test_a_turn_that_ends_before_the_site_writes_no_attempt_row() -> None:
    """§16 item 14's first clause, over the attempt.

    "A turn whose planner raises … leaves **no goal row, no attempt row and no plan
    row**" — the attempt was opened in memory and the turn ended above the one site §11
    names, so there is nothing to repair and nothing to clean up.
    """

    plans = _Recording()
    harness = Harness(planner=_Raising(), plans=plans)

    with pytest.raises(PlanningError):
        await harness.engine.converse(_ASKED, timeout=PATIENT)

    export = await harness.plans.export()
    assert (export.goals, export.plans, export.attempts) == ((), (), ())
    assert plans.opened == []
    assert plans.moves == []


# --------------------------------------------------------------------------- #
# §12 — the second persistence route, over a goal the store already holds      #
# --------------------------------------------------------------------------- #


class _Raising(NoStepPlanner):
    """A planner that refuses the call, so the turn ends above §11's site."""

    async def plan(self, goal: Any, **fields: Any) -> Any:
        """Refuse."""
        del goal, fields
        msg = "the planner is down"
        raise PlanningError(msg)


#: One retained outcome and one constraint grounded on a span of the turn's own request
#: — the smallest understanding that records a revision at all.
_ONE_CONSTRAINT: Final = ProposedUnderstanding(
    retains_outcome=True,
    constraints=(ProposedElement(text="two plus two", ground=Ground.USER_STATED, span="two"),),
)


class _Continuing(NoStepPlanner):
    """A planner that proposes an understanding and plans no step."""

    async def plan(self, goal: Any, **fields: Any) -> Any:
        """Plan as ``NoStepPlanner`` does, proposing one new constraint."""
        produced = await super().plan(goal, **fields)
        return produced.model_copy(update={"understanding": _ONE_CONSTRAINT})


class _DrivingContinuing(OneStepPlanner):
    """A planner that plans one step **and** proposes an understanding."""

    async def plan(self, goal: Any, **fields: Any) -> Any:
        """Plan as ``OneStepPlanner`` does, proposing one new constraint."""
        produced = await super().plan(goal, **fields)
        return produced.model_copy(update={"understanding": _ONE_CONSTRAINT})


def _earlier() -> Goal:
    """A goal an earlier turn opened, as this system stores one."""
    return Goal(
        id="goal-earlier",
        conversation_id="c-1",
        interpretation=(
            GoalInterpretation(
                revision=1,
                outcome="book a campsite",
                outcome_ground=Ground.USER_STATED,
                outcome_span="book a campsite",
                recorded_at=AT,
                raised_by="turn-earlier",
            ),
        ),
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT),
        created_at=AT,
        last_engaged_at=AT,
    )


async def test_a_continued_goals_revision_goes_through_record_interpretation() -> None:
    """§12: ``save_goal`` is "the opening write alone", so a continued goal takes the other route.

    The revision is appended under the compare-and-swap, against the ``version`` the loop
    read — and the attempt this turn opens is a **new** attempt on that **same** goal
    (§5, §16 item 2).

    **Which goal a turn continues is A2's** (§13), so the association is supplied here by
    a loop that states it rather than decided by anything this lane ships.
    """
    plans = _Recording()
    earlier = _earlier()
    await plans.save_goal(earlier)
    harness = Harness(planner=_Continuing(), plans=plans)
    _continue(harness, earlier)

    outcome = await harness.engine.converse("two plus two", timeout=PATIENT)

    assert outcome.turn is not None
    (appended,) = plans.appended
    assert appended.goal_id == earlier.id
    assert appended.expected_version == earlier.version
    assert appended.interpretation.revision == 2
    assert appended.interpretation.raised_by is not None
    (constraint,) = appended.interpretation.constraints
    assert (constraint.ground, constraint.span) == (Ground.USER_STATED, "two")
    stored = await plans.get_goal(earlier.id)
    assert stored is not None
    assert stored.interpretation[0] == earlier.interpretation[0], "prior revision unedited"
    assert stored.version == 1, "§12: the compare-and-swap token advanced by the write"
    (opened,) = plans.opened
    assert opened.goal_id == earlier.id, "a new attempt on the same goal"


def _continue(harness: Harness, goal: Goal) -> None:
    """Make this harness's loop continue ``goal`` rather than open one.

    A2 decides association (§13) and nothing in this lane does, so a case that needs the
    *continued* route states the association itself — at the one seam
    :meth:`LearningLoop.respond` exposes for it, rather than by reaching past the engine.
    """
    loop = harness.engine._loop
    responds = loop.respond

    async def continuing(utterance: str, **fields: object) -> RespondedTurn:
        return await responds(utterance, **fields, continuing=goal)  # type: ignore[arg-type]  # the keywords the engine passes

    loop.respond = continuing  # type: ignore[method-assign]  # a case stating the association A2 will


# --------------------------------------------------------------------------- #
# The supply a ground resolves against is the turn's own                       #
# --------------------------------------------------------------------------- #


async def test_a_recorded_element_reaches_the_stored_goal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§11, §12: the revision the loop resolved is what the store holds.

    Asserted end to end rather than at the resolver, because §11's carrier is what makes
    it true: the record travels inside ``ai_assistant.orchestration`` as data and
    ``Engine`` persists it, and a lane that built the revision and dropped the carrier
    would pass every resolver case and store nothing.
    """
    del monkeypatch
    harness = Harness(planner=_Continuing())

    outcome = await harness.engine.converse("two plus two", timeout=PATIENT)

    assert outcome.turn is not None
    stored = await harness.plans.get_goal(outcome.turn.goal.goal_id)
    assert stored is not None
    assert [one.revision for one in stored.interpretation] == [1, 2]
    (constraint,) = stored.interpretation[-1].constraints
    assert constraint.text == "two plus two"
    assert constraint.span == "two", "a span of this turn's own request"
    assert outcome.turn.goal.constraints[0].text == "two plus two", "and the brief shows it"


# --------------------------------------------------------------------------- #
# §12's authorization boundary — one placement, probed from every side          #
# --------------------------------------------------------------------------- #


async def test_an_answer_the_runner_refuses_leaves_the_attempt_waiting() -> None:
    """§12: a fact is committed when it becomes true, and a refused answer is not one.

    ADR-0235 §2 leaves the confirmation **pending** where the establishing act may not
    ride it: the runner raises before any ruling is sought, records no answer, and the
    step stays parked and answerable without the argument. So there is no moment at
    which the attempt left ``AWAITING_AUTHORIZATION``, and a commit taken on the *call*
    rather than on the *answer* would record one — the attempt would say ``EXECUTE``
    over a step still waiting for a user who has, as far as the durable record is
    concerned, not answered at all.
    """
    plans = _Recording()
    harness = Harness(
        tools=(confirmable(),), plans=plans, recipient_grants=FakeRecipientGrantStore()
    )
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    token = parked.step.confirmation.token

    with pytest.raises(UngrantableActError, match="recipients could be made standing"):
        await harness.engine.resume(
            token, approved=True, timeout=PATIENT, remember_recipients_until=AT + timedelta(days=1)
        )

    (stored,) = plans.opened
    waiting = await harness.plans.get_attempt(stored.id)
    assert waiting is not None
    assert waiting.state is AttemptState.AWAITING_AUTHORIZATION, "nothing was answered"
    assert waiting.phase is AttemptPhase.AUTHORIZE
    assert waiting.authorization_ids == (), "and no decision allowed anything"

    resumed = await harness.engine.resume(token, approved=True, timeout=PATIENT)

    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.EXECUTED
    moved = await harness.plans.get_attempt(stored.id)
    assert moved is not None
    assert moved.phase is AttemptPhase.VERIFY, "the answer that was taken did move it"
    assert len(moved.authorization_ids) == 1, "and one answer recorded one authorization"


async def test_a_cancellation_inside_the_initial_tool_keeps_the_phase_it_reached() -> None:
    """§12, on the first-turn path: the boundary is the ruling, not the runner's return.

    The mirror of the resumed case. An ``ALLOW`` under a slow tool and a ``CONFIRM``
    that parked are indistinguishable from outside ``StepRunner.run`` — which is why the
    stamp cannot simply precede the call, and why rounds 2 and 3 of this PR's review were
    right that it must not — so the runner is asked to say when the authorisation was
    **answered** and the attempt is moved there. A cancellation inside the tool then
    finds an attempt at ``EXECUTE`` naming the decision its step was claimed under,
    rather than one still recorded at ``AUTHORIZE`` over a step that is ``RUNNING``.
    """
    entered = asyncio.Event()
    release = asyncio.Event()

    async def _gated(parameters: object, *, idempotency_key: str | None) -> None:
        del parameters, idempotency_key
        entered.set()
        await release.wait()

    plans = _Recording()
    harness = Harness(tools=(tool(),), plans=plans, tool_handler=_gated)
    driving = asyncio.ensure_future(harness.engine.converse("send it", timeout=PATIENT))
    await asyncio.wait_for(entered.wait(), timeout=5)

    driving.cancel()
    with pytest.raises(asyncio.CancelledError):
        await driving
    release.set()

    (stored,) = plans.opened
    attempt = await harness.plans.get_attempt(stored.id)
    assert attempt is not None
    assert attempt.phase is AttemptPhase.EXECUTE, "the authorisation was answered"
    assert attempt.state is AttemptState.RUNNING
    assert attempt.outcome is None, "and nothing claims a result that did not happen"
    assert len(attempt.authorization_ids) == 1, "the decision the step was claimed under"
    assert await harness.trail.get(attempt.authorization_ids[0]) is not None, "and it resolves"


async def test_a_step_that_reached_no_ruling_is_still_stamped_execute() -> None:
    """§6: "a phase whose work is vacuous is stamped and left in the same instant".

    A capability no tool advertises never reaches a ruling at all, so the authorization
    boundary is never crossed and nothing stamps ``EXECUTE`` there. The turn still passes
    through all six phases, because §6 makes them "six responsibilities rather than six
    conditions" — which is what the post-drive stamp is for once the boundary has taken
    over every step that *was* ruled on.
    """
    plans = _Recording()
    harness = Harness(tools=(), plans=plans)

    outcome = await harness.engine.converse("send it", timeout=PATIENT)

    assert outcome.step is not None
    assert outcome.step.disposition is Disposition.NO_CAPABLE_TOOL
    assert plans.phases == _STORED_PHASES, "six phases, and EXECUTE among them"
    (stored,) = plans.opened
    attempt = await harness.plans.get_attempt(stored.id)
    assert attempt is not None
    assert attempt.authorization_ids == (), "nothing allowed anything"
    assert attempt.outcome is None, "and no step succeeded, so nothing is ANSWERED"


async def test_a_replay_racing_a_resolution_does_not_move_the_attempt_twice() -> None:
    """§12's compare-and-swap, over the window ``_resolve_park``'s lock is held across.

    Two callers answering one token: the first wins the lock, records the answer, crosses
    the boundary and moves the attempt; the second is queued on the same lock, finds the
    park settled and **restates**, which moves nothing. A commit taken around the
    resolution rather than inside it would let both advance the attempt's version, and
    the caller that actually executed would then meet a stale write **after** its side
    effect — a successful step whose attempt never records what became of it.

    Built on ``test_engine``'s own gate for this window, which suspends the first
    resolution after the runner has returned and before the park is replaced.
    """
    plans = _Recording()
    harness = Harness(tools=(confirmable(),), plans=plans)
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    token = parked.step.confirmation.token
    entered = asyncio.Event()
    release = asyncio.Event()

    class _GateAfterRecording:
        """Suspends the first ``resume`` after it has returned, inside the lock."""

        def __init__(self, inner: Any) -> None:
            self._inner = inner
            self._gated = False

        async def resume(self, *args: Any, **kwargs: Any) -> Any:
            result = await self._inner.resume(*args, **kwargs)
            if not self._gated:
                self._gated = True
                entered.set()
                await release.wait()
            return result

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    harness.engine._runner = _GateAfterRecording(harness.engine._runner)  # type: ignore[assignment]  # test double

    resolving = asyncio.ensure_future(harness.engine.resume(token, approved=True, timeout=PATIENT))
    await asyncio.wait_for(entered.wait(), timeout=5)
    replaying = asyncio.ensure_future(harness.engine.resume(token, approved=True, timeout=PATIENT))
    for _ in range(10):
        await asyncio.sleep(0)
    release.set()
    resolved = await resolving
    restated = await replaying

    assert resolved.step is not None
    assert resolved.step.disposition is Disposition.EXECUTED
    assert restated.turn is None, "the loser restated rather than resolving"
    (stored,) = plans.opened
    attempt = await harness.plans.get_attempt(stored.id)
    assert attempt is not None
    assert attempt.phase is AttemptPhase.VERIFY, "the winner finished its own bookkeeping"
    assert len(attempt.authorization_ids) == 1, "one answer, one authorization appended"
    to_execute = [
        one
        for one in plans.moves
        if one.to_phase is AttemptPhase.EXECUTE or one.to_state is AttemptState.RUNNING
    ]
    assert len(to_execute) == 1, "and the boundary was crossed once, not twice"


async def test_a_resolution_that_reached_no_ruling_leaves_the_question_standing() -> None:
    """§12, §6: no ruling, no move — and the confirmation is still a live question.

    ADR-0152 §7 refuses a resumed egress call whose binding has moved **before the
    resolving ruling is sought**, so no answer is recorded and the step stays durably
    ``AWAITING_APPROVAL``. ``pending_confirmations`` therefore offers it again once the
    binding is back, and it is answerable — so the attempt is still *waiting for an
    authorisation*, and an implementation that advanced it there would stamp ``EXECUTE``
    over a live question and leave §6's monotonic phase rule to refuse the approval when
    it finally arrived, consuming it without executing.

    Driven to that second answer rather than stopping at the refusal, because the refusal
    alone cannot tell a correct record from one that has merely not been contradicted yet.
    """
    plans = _Recording()
    harness = Harness(tools=(confirmable(),), plans=plans)
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None

    class _UnbindableOnce:
        """Wraps the runner, refusing the first resume before any ruling is sought."""

        def __init__(self, inner: Any) -> None:
            self._inner = inner
            self._refused = False

        async def resume(self, state: Any, step_id: str, **kwargs: Any) -> Any:
            if not self._refused:
                self._refused = True
                return StepDisposition(Disposition.EGRESS_UNBINDABLE, state)
            return await self._inner.resume(state, step_id, **kwargs)

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    harness.engine._runner = _UnbindableOnce(harness.engine._runner)  # type: ignore[assignment]  # test double

    refused = await harness.engine.resume(
        parked.step.confirmation.token, approved=True, timeout=PATIENT
    )

    assert refused.step is not None
    assert refused.step.disposition is Disposition.EGRESS_UNBINDABLE
    (stored,) = plans.opened
    waiting = await harness.plans.get_attempt(stored.id)
    assert waiting is not None
    assert waiting.state is AttemptState.AWAITING_AUTHORIZATION, "no answer was recorded"
    assert waiting.phase is AttemptPhase.AUTHORIZE, "and the phase did not move"

    (offered,) = await harness.engine.pending_confirmations()
    answered = await harness.engine.resume(offered.token, approved=True, timeout=PATIENT)

    assert answered.step is not None
    assert answered.step.disposition is Disposition.EXECUTED, "the approval still works"
    ended = await harness.plans.get_attempt(stored.id)
    assert ended is not None
    assert ended.phase is AttemptPhase.VERIFY, "EXECUTE and VERIFY, in §6's order"
    assert ended.state is not AttemptState.AWAITING_AUTHORIZATION, "it is no longer waiting"
    assert len(ended.authorization_ids) == 1, "the one ruling that was ever recorded"


async def test_the_park_is_published_only_after_the_attempt_says_it_is_waiting() -> None:
    """§12: the parking turn and the answer are two writers who never overlap.

    A park is durably answerable the instant ``→ AWAITING_APPROVAL`` is committed: from
    there ``pending_confirmations`` can enumerate it, mint a token and a ``resume`` can
    resolve it, in this process or another (ADR-0052 §2). A turn that still owed its
    attempt a write at that instant would be a second writer racing the answer, and
    **neither ordering of that race has a good outcome** — the parking turn losing the
    compare-and-swap raises out of a turn that had already parked, and the resumption
    losing it raises after the confirmation is spent, stranding the step with no token
    left to retry it.

    So the parking turn finishes with the attempt *before* the park exists, and this is
    the ordering asserted at the store: what the attempt said at the moment the park was
    published.
    """
    seen: list[AttemptState | None] = []

    class _WatchingThePublication(_Recording):
        """Reads the attempt at the instant the park becomes durable."""

        async def commit_transition(self, transition: Any) -> Any:
            """Record the attempt's state as ``→ AWAITING_APPROVAL`` commits."""
            if transition.to_status is StepStatus.AWAITING_APPROVAL and self.opened:
                held = await self.get_attempt(self.opened[0].id)
                seen.append(None if held is None else held.state)
            return await super().commit_transition(transition)

    plans = _WatchingThePublication()
    harness = Harness(tools=(confirmable(),), plans=plans)

    parked = await harness.engine.converse("send it", timeout=PATIENT)

    assert parked.step is not None
    assert parked.step.confirmation is not None, "the step parked"
    assert seen == [AttemptState.AWAITING_AUTHORIZATION], "written before it was published"
    assert plans.moves[-1].to_state is AttemptState.AWAITING_AUTHORIZATION, "and it is the last"
    assert [move.to_state for move in plans.moves].count(AttemptState.AWAITING_AUTHORIZATION) == 1
    (stored,) = plans.opened
    after = await harness.plans.get_attempt(stored.id)
    assert after is not None
    assert after.phase is AttemptPhase.AUTHORIZE, "the authorisation has not been given"


async def test_the_parking_turns_own_work_survives_the_resumption() -> None:
    """§5: the ledger accumulates and no implementation subtracts from it.

    The parking turn's interval and the resumption's are two different intervals of one
    attempt, and a resumption counts only its own — so a parking turn whose ledger write
    were dropped, or overwritten, would lose everything it did before the user was asked.
    Driven with a clock advancing a second per reading, so the figures are properties of
    the accounting rather than of how long the test took.
    """
    reading = 0

    def advancing() -> datetime:
        nonlocal reading
        reading += 1
        return AT + timedelta(seconds=reading)

    plans = _Recording()
    harness = Harness(tools=(confirmable(),), plans=plans, now=advancing)
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    (stored,) = plans.opened
    waiting = await harness.plans.get_attempt(stored.id)
    assert waiting is not None
    asked = waiting.effort.working
    assert asked > timedelta(0), "the planning and the drive up to the question are counted"

    resumed = await harness.engine.resume(
        parked.step.confirmation.token, approved=True, timeout=PATIENT
    )

    assert resumed.step is not None
    ended = await harness.plans.get_attempt(stored.id)
    assert ended is not None
    assert ended.effort.working > asked, "the resumption's interval is added to it"
    assert ended.state is AttemptState.ENDED


async def test_a_failed_boundary_write_is_recovered_by_the_finishing_commit() -> None:
    """§12's bookkeeping neither destroys the act it describes nor gives up on it.

    Two things have to hold at once when the store refuses the boundary's write. The
    approval must survive: a confirmation is answerable once (ADR-0044 §2b) and the
    resolving ruling is already in the trail by then, so a failure propagating from the
    boundary would leave the approval spent, the step ``AWAITING_APPROVAL``, a retry
    refused as already resolved and the binding absent from ``pending_confirmations`` —
    an authorised act with no route back. And the record must still be written: §12 asks
    for the facts established after the opening write, and a store that refused one
    commit and served the next has left nothing that stops the second from recording
    them.

    So the boundary is reported rather than raised, the decision's identity is kept before
    the write that may fail, and the finishing commit reads the attempt itself and commits
    what is true then — ``VERIFY``, the terminal fields, the ledger, and the authorization
    the boundary did not manage to append. Nothing is replayed and no failed transition is
    retried.

    ``StepRunner.run`` keeps the raise, and the difference is not arbitrary: nothing has
    been answered there, the step is still ``PENDING``, and the whole turn is retryable,
    so failing loudly costs a turn rather than an authorisation.
    """
    reading = 0

    def advancing() -> datetime:
        nonlocal reading
        reading += 1
        return AT + timedelta(seconds=reading)

    class _FailingOnTheBoundary(_Recording):
        """Refuses exactly the resumption's ``EXECUTE`` write, once."""

        def __init__(self) -> None:
            super().__init__()
            self.refused = 0

        async def commit_attempt(self, transition: AttemptTransition) -> GoalAttempt:
            """Raise on the transition the boundary makes, and serve every other."""
            if transition.to_phase is AttemptPhase.EXECUTE:
                self.refused += 1
                msg = "the plan store is unavailable"
                raise PlanningError(msg)
            return await super().commit_attempt(transition)

    plans = _FailingOnTheBoundary()
    harness = Harness(tools=(confirmable(),), plans=plans, now=advancing)
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    (stored,) = plans.opened
    waiting = await harness.plans.get_attempt(stored.id)
    assert waiting is not None
    asked = waiting.effort.working

    resumed = await harness.engine.resume(
        parked.step.confirmation.token, approved=True, timeout=PATIENT
    )

    assert plans.refused == 1, "the boundary's write really was refused"
    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.EXECUTED, "the approved act still ran"
    claimed = resumed.step.state.step("step-1")
    assert claimed is not None
    assert claimed.status is StepStatus.SUCCEEDED
    assert claimed.approval_ref is not None
    attempt = await harness.plans.get_attempt(stored.id)
    assert attempt is not None
    assert attempt.phase is AttemptPhase.VERIFY, "the finishing commit recorded the phase"
    assert attempt.state is AttemptState.ENDED
    assert attempt.outcome is AttemptOutcome.ANSWERED
    assert attempt.authorization_ids == (claimed.approval_ref,), "and what allowed the step"
    assert attempt.effort.working > asked, "and the resumption's own interval"


@pytest.mark.parametrize(
    ("approved", "handler", "composing"),
    [
        pytest.param(False, None, None, id="the_user_declined"),
        pytest.param(True, "raises", None, id="the_tool_failed"),
        pytest.param(True, None, "refuses", id="the_composition_produced_nothing"),
    ],
)
async def test_a_refused_boundary_write_is_recovered_on_an_answer_that_earns_nothing(
    *, approved: bool, handler: str | None, composing: str | None
) -> None:
    """The recovery's other half: the three answers that earn no ``AttemptOutcome``.

    ``ANSWERED`` asserts a reply exists, no step failed and no condition blocked (§5), and
    each of these fails one of the three. **Which member such an attempt earns instead is
    A10's** (§13), so none is written — but the attempt is not *waiting* either: the user
    answered, and the token is settled. An implementation that only wrote the state
    alongside a terminal outcome would leave a row saying ``AWAITING_AUTHORIZATION`` at
    ``VERIFY`` wherever the boundary's write was refused, which is §5's paused state over
    a question nobody can answer again.
    """

    async def _fails(parameters: object, *, idempotency_key: str | None) -> None:
        del parameters, idempotency_key
        msg = "the mail server refused it"
        raise ToolError(msg)

    class _FailingOnTheBoundary(_Recording):
        """Refuses exactly the resumption's ``EXECUTE`` write."""

        async def commit_attempt(self, transition: AttemptTransition) -> GoalAttempt:
            """Raise on the transition the boundary makes, and serve every other."""
            if transition.to_phase is AttemptPhase.EXECUTE:
                msg = "the plan store is unavailable"
                raise PlanningError(msg)
            return await super().commit_attempt(transition)

    plans = _FailingOnTheBoundary()
    harness = Harness(
        tools=(confirmable(),),
        plans=plans,
        tool_handler=_fails if handler is not None else None,
        composing=(
            None
            if composing is None
            else ComposingStage(
                model=FakeModelProvider(_refusing), streaming=FakeStreamingCompleter()
            )
        ),
    )
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None

    await harness.engine.resume(parked.step.confirmation.token, approved=approved, timeout=PATIENT)

    (stored,) = plans.opened
    attempt = await harness.plans.get_attempt(stored.id)
    assert attempt is not None
    assert attempt.phase is AttemptPhase.VERIFY, "the phase says where it stands"
    assert attempt.state is AttemptState.RUNNING, "and it is no longer waiting on the user"
    assert attempt.outcome is None, "which member it earns is A10's, so none is written"
    assert attempt.ended_at is None
