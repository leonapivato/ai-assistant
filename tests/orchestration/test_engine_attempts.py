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
    DriveWithheld,
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
    TurnReference,
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


async def test_a_failed_step_ends_the_attempt_failed() -> None:
    """§5's ``ANSWERED`` "asserts … that **no step failed**" — and A10 now says what it earns.

    :attr:`~ai_assistant.core.types.Disposition.EXECUTED` says the tool was *reached*,
    not that it succeeded — a tool that raises leaves that disposition beside a step
    whose :class:`~ai_assistant.core.types.StepStatus` is ``FAILED``. §13 left **which**
    ``AttemptOutcome`` such an attempt earns to A10, and ADR-0262 §4's limb 1 answers it:
    no criterion is met, ``failed`` holds, and the attempt is **not** at rung 2 — the
    tool here is ``side_effecting`` and ``REVERSIBLE``, discloses nothing and carries no
    egress binding — so the member is ``FAILED``.

    **This case asserted ``RUNNING`` and no outcome before A10 landed**, which was §4's
    stated cost taken rather than an outcome nothing established. The cost is now paid
    rather than taken: the record says the work failed, and §6's statement for that
    member says exactly that and *"no criterion of this goal was established"*.
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
    assert attempt.state is AttemptState.ENDED, "and ADR-0262 §4's limb 1 ended it"
    assert attempt.outcome is AttemptOutcome.FAILED
    assert attempt.ended_at is not None
    goal = await harness.plans.get_goal(stored.goal_id)
    assert goal is not None
    assert goal.status is GoalStatus.ACTIVE, "R53: an attempt ending closes no goal"


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
    # ADR-0262 §4's limb 3, which this case reaches once A10 decides the member rather
    # than ADR-0249 §5's `ANSWERED` being the only answer a pass can write. The tool
    # that parked did so because it discloses off-device, which is §3's **rung 2**; the
    # goal carries no criterion, so `fully_met` is false and nothing is `unmet`. "A
    # consequential act ran and nothing verified it, which is what `UNCERTAIN` says and
    # what `ANSWERED` would deny."
    assert moved.outcome is AttemptOutcome.UNCERTAIN
    assert moved.ended_at == AT
    assert resumed.attempt_report is not None
    assert resumed.attempt_report.outcome is AttemptOutcome.UNCERTAIN
    assert resumed.attempt_report.continues is True, "§6: an open goal whose work is unfinished"


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


async def test_a_refused_confirmation_ends_the_attempt_condition_prevented() -> None:
    """§5: a condition blocked, so ``ANSWERED`` is not true of this pass — and A10 says what is.

    §13 left **which** ``AttemptOutcome`` a refused act earns to A10, and ADR-0262 §4's
    limb 2 answers it: no criterion is met, none is ``unmet``, ``blocked`` holds — the
    step is ``SKIPPED`` carrying ``SkipReason.APPROVAL_DENIED`` — nothing failed, and
    nothing was claimed, so the attempt is at **rung 0**. The member is
    ``CONDITION_PREVENTED``, whose §6 statement says the action was *"prevented before it
    ran"* — true of the user's own refusal, which is one of ``blocked``'s two sources.

    **This case asserted ``RUNNING`` and no outcome before A10 landed.** What ends the
    attempt now is the comparison rather than the answer being ``ANSWERED``-shaped.
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
    assert moved.state is AttemptState.ENDED, "no longer waiting, and §4's limb 2 ended it"
    assert moved.outcome is AttemptOutcome.CONDITION_PREVENTED
    assert moved.ended_at is not None
    assert resumed.attempt_report is not None
    assert resumed.attempt_report.outcome is AttemptOutcome.CONDITION_PREVENTED
    assert resumed.attempt_report.continues is False, "§6: a prevented attempt offers nothing"


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

    **The association is the production one** (ADR-0250 §3 step 1): the turn carries a
    ``TurnReference`` naming the goal, which "wins outright and costs no model call" and
    reaches this route without a candidate set, an associator answer or a patched loop.
    """
    plans = _Recording()
    earlier = _earlier()
    await plans.save_goal(earlier)
    harness = Harness(planner=_Continuing(), plans=plans)

    outcome = await harness.engine.converse(
        "two plus two", timeout=PATIENT, reference=TurnReference(goal_id=earlier.id)
    )

    assert outcome.turn is not None
    (appended,) = plans.appended
    assert appended.goal_id == earlier.id
    assert appended.expected_version == earlier.version, (
        "ADR-0250 §20 arm 34: the engagement stamp is written at the persistence "
        "boundary and not at the association, so the revision is written against the "
        "version the loop read and the stamp follows it"
    )
    assert appended.interpretation.revision == 2
    assert appended.interpretation.raised_by is not None
    (constraint,) = appended.interpretation.constraints
    assert (constraint.ground, constraint.span) == (Ground.USER_STATED, "two")
    stored = await plans.get_goal(earlier.id)
    assert stored is not None
    assert stored.interpretation[0] == earlier.interpretation[0], "prior revision unedited"
    assert stored.version == 2, (
        "§12's own write advanced the token once and ADR-0250 §1's engagement stamp "
        "advanced it again: `engage_goal` is a mutation of the goal like any other"
    )
    assert stored.last_engaged_in is not None, "ADR-0250 §1: the turn engaged the goal"
    (opened,) = plans.opened
    assert opened.goal_id == earlier.id, "a new attempt on the same goal"


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
    # ADR-0262 §4's limb 6. Nothing was claimed, so the attempt is at **rung 0**; the
    # step is `SKIPPED` carrying `SkipReason.NO_CAPABLE_TOOL`, which is neither of the
    # two reasons §4's `blocked` reads, and nothing failed. ADR-0249 §5's `ANSWERED`
    # asserts "a reply exists, no step failed and no condition blocked" — each true here
    # — and "it asserts nothing about whether the reply is correct", which is what makes
    # it honest of a turn that found no tool and said so.
    assert attempt.outcome is AttemptOutcome.ANSWERED
    assert outcome.attempt_report is not None
    assert outcome.attempt_report.outcome is AttemptOutcome.ANSWERED


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


@pytest.mark.parametrize("approved", [True, False])
async def test_a_recovered_park_no_attempt_owns_resolves_nothing(*, approved: bool) -> None:
    """ADR-0255 §5's first limb, on **either** answer, before any ruling is resolved.

    A park recovered from durable state has no live turn (ADR-0052 §3), so
    ``orchestration`` resolves the attempt from the store — and *"where no attempt names
    it … the resume is refused, before any ruling is resolved and before anything is
    claimed"*. Refusing there rather than at the store's own conjunct is what keeps the
    answer: ADR-0036 §2's unique index and ADR-0044 §2(b)'s per-binding rule make a
    resolution **single-use**, so a refusal one authored resolution later would spend the
    one answer the binding admits and strand the step exactly as #257 describes.

    **The declining answer is refused too**, and §5's never-gated clause does not reach
    it: that clause is stated of the three dispatch predicates a walk re-evaluates — the
    dependency rule, ``when`` and ``resolves`` — and this is not one of them. It is the
    question of which record the act belongs to, which a *no* answers no better than a
    *yes*, and a denial recorded against a park nothing owns is a disposition written
    into a record with no attempt to account for it.

    The state is the one a store written before ADR-0255 §3 can hold, or one ADR-0249
    §12's migration left: reachable here only by writing the row, because every public
    member that could produce it now refuses.
    """
    plans = _Recording()
    harness = Harness(tools=(confirmable(),), plans=plans)
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    (stored,) = plans.opened
    # A pre-decision row, by construction: `commit_attempt` never removes a reference.
    held = await harness.plans.get_attempt(stored.id)
    assert held is not None
    plans._attempts[stored.id] = held.model_copy(update={"execution_ids": ()})

    with pytest.raises(PlanningError, match="cannot name exactly one attempt"):
        await harness.engine.resume(
            parked.step.confirmation.token, approved=approved, timeout=PATIENT
        )

    assert harness.invoker.invocations == [], "nothing was invoked"
    assert [one for one in await harness.trail.export() if one.resolves is not None] == [], (
        "and no ruling was resolved, so the one answer the binding admits is unspent"
    )
    execution = await harness.plans.get_execution(parked.step.state.id)
    assert execution is not None
    step = execution.step("step-1")
    assert step is not None
    assert step.status is StepStatus.AWAITING_APPROVAL, "the step stands where it stood"
    assert len(await harness.engine.pending_confirmations()) == 1, (
        "and the question is still enumerable, so it is still answerable"
    )


@pytest.mark.parametrize("approved", [True, False])
async def test_a_recovered_park_two_attempts_own_resolves_nothing(*, approved: bool) -> None:
    """ADR-0255 §5's second limb: the ambiguous ownership §3 describes.

    *"Where no attempt names it, **and where more than one does** — the legacy state §3
    describes — the resume is refused."* §3's exclusivity makes that state unreachable
    through either attempt-writing member, so it survives only in a store written before
    the decision — and **no lane resolves it by picking the live one, the newest one or
    any one**: the append order is not retained and the tuples carry no instant, so a
    choice would invent an ownership nobody recorded.

    The refusal is the engine's and it is taken first; the store's own conjunct refuses
    the same state from the other side, one authored resolution later, which is the
    answer this arm exists to keep.
    """
    plans = _Recording()
    harness = Harness(tools=(confirmable(),), plans=plans)
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    (stored,) = plans.opened
    # A pre-decision row again: `open_attempt` and `commit_attempt` both refuse it now.
    plans._attempts["a-second"] = GoalAttempt(
        id="a-second",
        goal_id=stored.goal_id,
        opened_at=AT,
        execution_ids=(parked.step.state.id,),
    )

    with pytest.raises(PlanningError, match="cannot name exactly one attempt"):
        await harness.engine.resume(
            parked.step.confirmation.token, approved=approved, timeout=PATIENT
        )

    assert harness.invoker.invocations == [], "nothing was invoked"
    assert [one for one in await harness.trail.export() if one.resolves is not None] == [], (
        "and no ruling was resolved"
    )
    execution = await harness.plans.get_execution(parked.step.state.id)
    assert execution is not None
    step = execution.step("step-1")
    assert step is not None
    assert step.status is StepStatus.AWAITING_APPROVAL


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


async def test_a_failed_boundary_write_leaves_the_attempt_paused_and_the_claim_refused() -> None:
    """§12's boundary meeting ADR-0255 §3's paused limb, which rules the outcome.

    The boundary write is what moves a resumed attempt out of
    ``AWAITING_AUTHORIZATION`` (ADR-0254 §14), and ADR-0255 §3 refuses a claim under a
    paused attempt: *"A resume that nevertheless finds the attempt paused is refused
    rather than excused, which is the fail-closed direction."* So where the store
    refuses that write, the step is **not** claimed and the tool is **not** reached —
    which is a change from what this arm pinned before ADR-0255, and is the direction
    that keeps *paused* true of a paused system rather than the one that keeps the act.

    **§12's own guarantee still holds and is what separates the two failures.** The
    boundary is reported rather than raised, so the resumption does not fail *because
    the bookkeeping did* — it ends at the claim, on the claim's own refusal. The
    residual is §3's, stated there and booked to A8: the resolving ruling **is**
    recorded, so the one answer ADR-0044 §2b admits is spent on a claim that never
    landed, and the step stands ``AWAITING_APPROVAL`` at its stored version with
    nothing invoked.

    **Since ADR-0261 §7 the resumption *returns* rather than raising, and that is the
    one thing this arm now pins differently.** The driver catches the ``ClaimRefused``
    its own claim made, ends there, retries nothing and composes — *"a refused claim is
    not a fault"* — and the outcome carries where the goal stands. ADR-0255 §3's *"a
    resume that nevertheless finds the attempt paused is **refused** rather than
    excused"* is untouched: it is about what the **store** does with the claim, and the
    store still refuses it, nothing is invoked and the step keeps its entry status.
    ``ATTEMPT_PAUSED`` is true of the record the read finds, which is what §7 makes the
    field mean — *"where the goal stands, never why the step was not claimed"*.
    """

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
    harness = Harness(tools=(confirmable(),), plans=plans)
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    (stored,) = plans.opened

    withheld = await harness.engine.resume(
        parked.step.confirmation.token, approved=True, timeout=PATIENT
    )

    assert withheld.drive_withheld is DriveWithheld.ATTEMPT_PAUSED, "where the goal stands"
    assert withheld.step is None, "nothing was driven, so the outcome projects no step"
    assert plans.refused == 1, "the boundary's write really was refused"
    assert harness.invoker.invocations == [], "and nothing was invoked under a paused attempt"
    execution = await harness.plans.get_execution(parked.step.state.id)
    assert execution is not None
    claimed = execution.step("step-1")
    assert claimed is not None
    assert claimed.status is StepStatus.AWAITING_APPROVAL, "the step is at its entry status"
    attempt = await harness.plans.get_attempt(stored.id)
    assert attempt is not None
    assert attempt.state is AttemptState.AWAITING_AUTHORIZATION, "still waiting on the user"
    # §3's residual, which is the reason it is called the real one: the answer was
    # recorded before the claim (ADR-0037 §4's steps 5 and 6), so the approval is spent.
    resolving = [one for one in await harness.trail.export() if one.resolves is not None]
    assert len(resolving) == 1, "the resolving ruling was recorded before the refused claim"


async def test_a_refused_boundary_write_is_recovered_on_a_declining_answer() -> None:
    """The recovery's other half: a declining answer, over a row the boundary never moved.

    ``ANSWERED`` asserts a reply exists, no step failed and no condition blocked (§5),
    and a **declining** answer fails the third. §13 left which member such an attempt
    earns to A10, and ADR-0262 §4's limb 2 answers it — ``CONDITION_PREVENTED``, the
    user's own refusal being one of ``blocked``'s two sources.

    **What this arm is about is unchanged, and it is the state rather than the member**:
    wherever the boundary's write was refused the stored row still says
    ``AWAITING_AUTHORIZATION``, and the finishing commit is what repairs it. An
    implementation that wrote the state only alongside a terminal outcome would leave
    §5's paused state at ``VERIFY`` over a question nobody can answer again.

    **And the attempt does not end on this turn**, which is the same clause read the
    other way. ADR-0262 §4 admits an ending *"exactly where"* the attempt's state is
    none of its three paused members, and this row is one of them at the instant the
    commit is computed — §12's arm 7 requires an ``AWAITING_AUTHORIZATION`` attempt to
    stay non-terminal with no outcome, and it does not except the turn that is answering
    it. So this turn takes the recovery transition and nothing else, and the next turn
    that engages the goal runs its own comparison against the then-current criteria.
    That is §4's own stated cost, and it is bounded by an act that already runs.

    **The two approving answers this arm used to carry — the tool failing and the
    composition producing nothing — are unreachable behind a refused boundary write
    since ADR-0255 §3**: the write is what leaves ``AWAITING_AUTHORIZATION``, and a
    claim under a paused attempt is refused, so no tool runs and no composition is
    reached. The arm above pins that, and the recovery this one is about is driven
    through the answer that claims nothing.
    """

    class _FailingOnTheBoundary(_Recording):
        """Refuses exactly the resumption's ``EXECUTE`` write."""

        async def commit_attempt(self, transition: AttemptTransition) -> GoalAttempt:
            """Raise on the transition the boundary makes, and serve every other."""
            if transition.to_phase is AttemptPhase.EXECUTE:
                msg = "the plan store is unavailable"
                raise PlanningError(msg)
            return await super().commit_attempt(transition)

    plans = _FailingOnTheBoundary()
    harness = Harness(tools=(confirmable(),), plans=plans)
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None

    await harness.engine.resume(parked.step.confirmation.token, approved=False, timeout=PATIENT)

    (stored,) = plans.opened
    attempt = await harness.plans.get_attempt(stored.id)
    assert attempt is not None
    assert attempt.phase is AttemptPhase.VERIFY, "the phase says where it stands"
    assert attempt.state is AttemptState.RUNNING, "and it is no longer waiting on the user"
    assert attempt.outcome is None, "§4 ends no attempt whose stored state is paused"
    assert attempt.ended_at is None
    goal = await harness.plans.get_goal(stored.goal_id)
    assert goal is not None
    assert goal.status is GoalStatus.ACTIVE, "and no GoalStatus moved"
