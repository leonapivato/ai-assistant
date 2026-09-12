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
from test_engine_composing import _refusing
from test_engine_read_envelope import _recorder

from ai_assistant.core.errors import PlanningError, ToolError
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
from ai_assistant.testing import FakeModelProvider, FakePlanStore, FakeStreamingCompleter

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
