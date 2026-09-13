"""ADR-0250 §20's arms that name §19's M3 — the ``orchestration`` threading.

Every case here drives the **production** path: a wired :class:`Engine` over the
canonical fakes, with the association scripted at the one seam §4 exposes and nothing
reached past. What the arms are about is which calls a turn makes, what it writes, and
what its outcome carries — none of which a loop-level case can see, because the store,
the association and the outcome are all the engine's.
"""

from __future__ import annotations

from base64 import b64encode
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pytest
from test_engine import AT, PATIENT, Harness, NoStepPlanner, OneStepPlanner, tool

from ai_assistant import orchestration
from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    AssociationVerdict,
    AttemptEffort,
    AttemptKind,
    AttemptPhase,
    AttemptState,
    EngagementDisposition,
    Goal,
    GoalAssociation,
    GoalAttempt,
    GoalElement,
    GoalInterpretation,
    GoalQuestion,
    GoalQuestionDisposition,
    GoalStatus,
    Ground,
    MemorySource,
    ProposedElement,
    ProposedQuestion,
    ProposedUnderstanding,
    Provenance,
    ReferenceOutcome,
    SpokenAudio,
    SpokenAudioFormat,
    TurnReference,
)
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.planning.planner import _render_request
from ai_assistant.testing import (
    FakeConversationStore,
    FakeGoalAssociator,
    FakeModelProvider,
    FakePlanStore,
    FakeStreamingCompleter,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import PlanStore

#: The module ADR-0250 §19's M3 added, which arm 29's absence is stated over.
_GOALS: Final = Path(orchestration.__file__).parent / "goals.py"

#: The recording format the canonical fake speech seams read.
_MP4: Final = SpokenAudioFormat.MP4

_ASKED = "book the usual campsite for next weekend"
_ELSEWHERE = "what is two plus two?"


def _associating(verdict: AssociationVerdict, *labels: str) -> FakeGoalAssociator:
    """An associator scripted to one verdict, at ADR-0250 §4's own seam."""
    return FakeGoalAssociator(answer=GoalAssociation(verdict=verdict, labels=labels))


def _goal(
    goal_id: str, outcome: str, *, conversation: str, status: GoalStatus | None = None
) -> Goal:
    """A goal an earlier turn opened, as this system stores one."""
    return Goal(
        id=goal_id,
        conversation_id=conversation,
        interpretation=(
            GoalInterpretation(
                revision=1,
                outcome=outcome,
                outcome_ground=Ground.USER_STATED,
                outcome_span=outcome,
                recorded_at=AT,
                raised_by=f"turn-{goal_id}",
            ),
        ),
        status=GoalStatus.ACTIVE if status is None else status,
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT),
        created_at=AT,
    )


async def _seed(plans: PlanStore, goal: Goal, *, engaged_in: str | None = None) -> Goal:
    """Store a goal, engaging it where a case needs it in a candidate set."""
    await plans.save_goal(goal)
    if engaged_in is None:
        return goal
    return await plans.engage_goal(
        goal.id, at=AT, conversation_id=engaged_in, expected_version=goal.version
    )


_SUBJECT = ProposedUnderstanding(
    retains_outcome=True,
    criteria=(ProposedElement(text="a pitch by the river", ground=Ground.INFERRED),),
    questions=(ProposedQuestion(text="Which campsite did you mean?", about="S1"),),
)
_CONSTRAINT_SUBJECT = ProposedUnderstanding(
    retains_outcome=True,
    constraints=(ProposedElement(text="under fifty pounds", ground=Ground.INFERRED),),
    questions=(ProposedQuestion(text="How much is your budget?", about="C1"),),
)


class _Asking(NoStepPlanner):
    """A planner whose envelope a case rewrites between turns.

    **One instance across a case's turns**, because ``plan_id`` counts this planner's
    own calls: a second instance would restart the count and mint an id the store
    already holds, which ADR-0014 §2 refuses for the planner's own defect.
    """

    def __init__(self, understanding: ProposedUnderstanding | None = _SUBJECT) -> None:
        self.understanding = understanding

    async def plan(self, goal: Any, **fields: Any) -> Any:
        """Plan no step, proposing this planner's current understanding."""
        produced = await super().plan(goal, **fields)
        return produced.model_copy(update={"understanding": self.understanding})


class _AskingWithAStep(OneStepPlanner):
    """A planner that plans a step **and** raises one question about it."""

    def __init__(self, understanding: ProposedUnderstanding = _CONSTRAINT_SUBJECT) -> None:
        super().__init__()
        self._understanding = understanding

    async def plan(self, goal: Any, **fields: Any) -> Any:
        """Plan one step, proposing this planner's understanding."""
        produced = await super().plan(goal, **fields)
        return produced.model_copy(update={"understanding": self._understanding})


# --------------------------------------------------------------------------- #
# Arms 1 and 2: what a turn costs                                             #
# --------------------------------------------------------------------------- #


async def test_a_first_turn_costs_nothing_new() -> None:
    """§20 arm 1: an empty candidate set opens a goal and makes no ``associate`` call.

    "*What is two plus two?*" on a conversation's first turn: "the candidate set is
    empty, **no ``associate`` call is made**, a goal is opened at revision 1, and the
    turn's model calls are exactly today's — which keeps ADR-0249 §16 arm 1 true
    unchanged."
    """
    planner = NoStepPlanner()
    harness = Harness(planner=planner, associator=_associating(AssociationVerdict.UNDECIDED))

    outcome = await harness.engine.converse(_ELSEWHERE, timeout=PATIENT)

    assert harness.associator.call_count == 0, "§3 step 2 answers before step 3 is reached"
    assert outcome.turn is not None
    stored = await harness.plans.get_goal(outcome.turn.goal.goal_id)
    assert stored is not None
    assert len(stored.interpretation) == 1
    assert outcome.goal_engagement is not None
    assert outcome.goal_engagement.disposition is EngagementDisposition.OPENED


async def test_one_candidate_still_costs_a_call_and_a_fresh_verdict_leaves_it_alone() -> None:
    """§20 arm 2: the same request over one live goal makes the call and opens a second.

    "An ``associate`` call **is** made, a ``FRESH`` verdict opens a second goal, the
    campsite goal's ``last_engaged_at`` is **unmoved**, and its interpretation chain
    gains no revision."
    """
    harness = Harness(planner=NoStepPlanner(), associator=_associating(AssociationVerdict.FRESH))
    conversation = (await harness.conversations.begin(None)).id
    campsite = await _seed(
        harness.plans, _goal("goal-campsite", "book a campsite", conversation=conversation)
    )

    outcome = await harness.engine.converse(
        _ELSEWHERE, timeout=PATIENT, conversation_id=conversation
    )

    assert harness.associator.call_count == 1, "§3: a conversation holding a candidate pays one"
    assert outcome.turn is not None
    assert outcome.turn.goal.goal_id != campsite.id, "the answer is not composed against it"
    held = await harness.plans.get_goal(campsite.id)
    assert held is not None
    assert held.last_engaged_at is None, "§1: a turn that did not associate to it engaged nothing"
    assert len(held.interpretation) == 1, "and recorded no revision against it"


# --------------------------------------------------------------------------- #
# Arms 3 to 6: materiality, and what a raised question does                   #
# --------------------------------------------------------------------------- #


async def test_a_material_ambiguity_pauses_the_attempt_and_writes_one_question() -> None:
    """§20 arm 3: a ``criteria`` subject is material on a turn proposing no act.

    "The planner's ``ProposedQuestion`` is taken, a ``GoalQuestion`` is written, the
    attempt's state is ``AWAITING_CLARIFICATION``, its **phase does not move**, **no
    step is driven**, and the outcome carries the clarification."
    """
    harness = Harness(planner=_Asking())

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.clarification is not None
    assert outcome.clarification.text == "Which campsite did you mean?"
    assert outcome.step is None, "§10: a turn that raised a question drives no step"
    assert outcome.reply is not None, "and its answer *is* the question"
    assert outcome.goal_engagement is not None
    assert outcome.turn is not None
    stored = await harness.plans.get_goal(outcome.turn.goal.goal_id)
    assert stored is not None
    question = await harness.plans.open_question(stored.id)
    assert question is not None
    assert question.disposition is GoalQuestionDisposition.OPEN
    assert question.about == "a pitch by the river", "§7: the subject's own recorded text"
    assert question.expires_at == question.asked_at + timedelta(hours=72)
    (attempt,) = await harness.plans.attempts_of(stored.id)
    assert attempt.state is AttemptState.AWAITING_CLARIFICATION
    assert attempt.phase is AttemptPhase.PLAN, "§10: a question is a pause, not a retreat"


async def test_a_constraint_subject_on_a_turn_proposing_nothing_asks_nothing() -> None:
    """§20 arms 3 and 5: ``constraints`` is not material where nothing acts.

    "A subject that is an element of ``constraints`` on a turn proposing no
    side-effecting step is **not** material, and the question is dropped: a constraint
    bounds an action, and with no action proposed there is nothing this turn for it to
    bound."
    """
    harness = Harness(planner=_Asking(_CONSTRAINT_SUBJECT))

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.clarification is None
    assert outcome.turn is not None
    assert await harness.plans.open_question(outcome.turn.goal.goal_id) is None


async def test_a_constraint_subject_becomes_material_where_the_plan_acts() -> None:
    """§20 arms 3 and 5: §6's second limb, read over a **declaration**.

    "The ``ActionPlan`` the **same** ``PlannerOutput`` carries proposes at least one step
    whose capability the ``ToolRegistry`` declares ``ToolDefinition.side_effecting``. A
    turn about to change something outside itself is a turn whose every understood
    element is material."
    """
    harness = Harness(planner=_AskingWithAStep(), tools=(tool(side_effecting=True),))

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.clarification is not None, "§6's second limb fires on a side-effecting plan"
    assert outcome.step is None, "and §10 stops the step this plan proposed"


async def test_the_same_plan_declared_harmless_asks_nothing() -> None:
    """§20 arm 5's other half: the limb reads the declaration and nothing else.

    A registry that declares the very same capability **not** side-effecting leaves a
    ``constraints`` subject immaterial, which is what stops §6's second limb from
    becoming "ask whenever acting" (arm 4).
    """
    harness = Harness(planner=_AskingWithAStep(), tools=(tool(side_effecting=False),))

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.clarification is None
    assert outcome.step is not None, "and the turn proceeds"


async def test_no_proposed_question_on_an_acting_plan_asks_nothing() -> None:
    """§20 arm 4: the usual campsite resolves.

    "A planner that returns no ``ProposedQuestion`` on a side-effecting plan: no question
    is written, the attempt is not paused, and the turn proceeds — asserted so that the
    second materiality limb cannot become 'ask whenever acting'."
    """
    harness = Harness(planner=OneStepPlanner(), tools=(tool(side_effecting=True),))

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.clarification is None
    assert outcome.step is not None
    assert outcome.turn is not None
    assert await harness.plans.open_question(outcome.turn.goal.goal_id) is None


async def test_a_question_about_a_retained_element_carries_the_copied_forward_text() -> None:
    """§20 arm 6: a retaining ``ProposedElement`` has no ``text``, and the record still constructs.

    "The subject resolves, the question is material, and ``GoalQuestion.about`` carries
    the **text of the ``GoalElement`` retention copied forward**, non-blank, so the
    record constructs. The arm fails if the implementation reads the proposed element's
    own ``text``, which a retaining element does not have."
    """
    planner = _Asking()
    harness = Harness(planner=planner)
    first = await harness.engine.converse(_ASKED, timeout=PATIENT)
    assert first.turn is not None
    goal_id = first.turn.goal.goal_id
    question = await harness.plans.open_question(goal_id)
    assert question is not None
    await harness.plans.settle_question(
        question.id, disposition=GoalQuestionDisposition.WITHDRAWN, at=AT
    )
    planner.understanding = ProposedUnderstanding(
        retains_outcome=True,
        criteria=(ProposedElement(retains="S1"),),
        questions=(ProposedQuestion(text="Which pitch?", about="S1"),),
    )

    second = await harness.engine.converse(
        "and make it Sunday",
        timeout=PATIENT,
        reference=TurnReference(goal_id=goal_id),
    )

    assert second.clarification is not None
    raised = await harness.plans.open_question(goal_id)
    assert raised is not None
    assert raised.about == "a pitch by the river", "§7: the element retention copied forward"


# --------------------------------------------------------------------------- #
# Arms 7 to 9: answering, across a turn and across a deadline                  #
# --------------------------------------------------------------------------- #


async def test_an_unrelated_turn_and_a_restart_and_the_answer_still_reaches_its_goal() -> None:
    """§20 arm 7 and §11's Q6: the pause survives an unrelated turn **and a restart**.

    "An unrelated request during a clarification is answered normally. The paused goal
    keeps its open question and its ``AWAITING_CLARIFICATION`` attempt; the new turn
    opens or resumes another goal by §3 … When the answer eventually arrives it reaches
    the right goal by the question's own ``goal_id``, across intervening turns **and
    across a restart**."

    The restart is a **second façade over the same durable stores**, which is what §11
    says has to be true of it: *"The handle is the question's own durable ``id`` and
    needs no re-minting … no handle table holds a question, and ``pending_confirmations``
    gains nothing"*, so *"no handle table is rebuilt, no continuation is re-minted and no
    enumeration runs at start"*. The second engine's own handle table is empty, and the
    answer reaches the goal anyway.

    The planner instance and the goal-id sequence cross the restart because they stand in
    for process-independent facts — the planner's ``plan_id`` counter and production's
    ``uuid4`` — while everything the engine holds in memory does not.
    """
    goals = iter(f"g-{n}" for n in range(1, 100))
    plans = FakePlanStore(now=lambda: AT)
    conversations = FakeConversationStore(now=lambda: AT)
    planner = _Asking()
    harness = Harness(
        planner=planner,
        plans=plans,
        conversation_store=conversations,
        loop_id_factory=lambda: next(goals),
        associator=_associating(AssociationVerdict.FRESH),
    )
    paused = await harness.engine.converse(_ASKED, timeout=PATIENT)
    assert paused.turn is not None
    assert paused.clarification is not None
    campsite = paused.turn.goal.goal_id
    conversation = paused.conversation_id
    assert conversation is not None
    planner.understanding = None

    unrelated = await harness.engine.converse(
        _ELSEWHERE, timeout=PATIENT, conversation_id=conversation
    )

    assert unrelated.clarification is None, "no lane refuses a turn on account of a clarification"
    assert unrelated.turn is not None
    assert unrelated.turn.goal.goal_id != campsite
    still = await plans.open_question(campsite)
    assert still is not None, "§11: the paused goal keeps its open question"
    (attempt,) = await plans.attempts_of(campsite)
    assert attempt.state is AttemptState.AWAITING_CLARIFICATION
    # --- the restart: a second façade over the same durable stores ---
    restarted = Harness(
        planner=planner,
        plans=plans,
        conversation_store=conversations,
        loop_id_factory=lambda: next(goals),
        associator=_associating(AssociationVerdict.FRESH),
    )
    assert await restarted.engine.pending_confirmations() == (), (
        "§11: nothing is re-minted at start, and a question is not a park"
    )

    answer = await restarted.engine.converse(
        "the river one",
        timeout=PATIENT,
        conversation_id=conversation,
        reference=TurnReference(question_id=still.id),
    )

    assert answer.reference is ReferenceOutcome.ANSWERED
    assert answer.goal_engagement is not None
    assert answer.turn is not None
    assert answer.turn.goal.goal_id == campsite, "the answer reached the right goal"
    assert restarted.associator.call_count == 0, "arm 7: no ``associate`` call at all"
    settled = await plans.get_question(still.id)
    assert settled is not None
    assert settled.disposition is GoalQuestionDisposition.ANSWERED
    assert (settled.text, settled.about) == (None, None), "§8: settling clears the content"
    (resumed,) = await plans.attempts_of(campsite)
    assert resumed.id == attempt.id, "§11: the **same** attempt, not a new one"
    assert resumed.state is not AttemptState.AWAITING_CLARIFICATION, (
        "§11: the answer resumed it — and the turn then finished it in the ordinary way, "
        "which is ADR-0249 §5's `ANSWERED` and not this decision's to write"
    )


async def test_a_late_answer_replans_over_the_revised_understanding() -> None:
    """§20 arm 8: decision 3's late answer restates, rechecks and proceeds.

    "A **fresh** ``Planner.plan`` call is made over the new brief, nothing from the
    paused turn's supply or plan is reused." What "recheck" covers before A4 and A6 land
    is §11's own two subjects, and the first of them is exactly this call.
    """
    planner = _Asking()
    harness = Harness(planner=planner)
    paused = await harness.engine.converse(_ASKED, timeout=PATIENT)
    assert paused.turn is not None
    assert paused.clarification is not None
    before = paused.turn.plan.id

    answered = await harness.engine.converse(
        "the river one",
        timeout=PATIENT,
        reference=TurnReference(question_id=paused.clarification.question_id),
    )

    assert answered.turn is not None
    assert answered.turn.plan.id != before, "a fresh plan over the new brief"
    assert await harness.plans.get_plan(answered.turn.plan.id) is not None, "and it is persisted"


async def test_an_answer_after_expiry_reopens_the_work_rather_than_vanishing() -> None:
    """§20 arm 9 and decision 2: silence is neither refusal nor abandonment.

    "The question is settled ``EXPIRED`` and its content cleared; a turn carrying its
    reference still engages the goal, ``reference`` reads ``EXPIRED`` … and **nothing
    reads the expiry as a refusal or an abandonment**. The goal's status is still
    ``ACTIVE``."
    """
    clock = _Advancing()
    harness = Harness(planner=_Asking(), now=clock)
    paused = await harness.engine.converse(_ASKED, timeout=PATIENT)
    assert paused.turn is not None
    assert paused.clarification is not None
    clock.advance(timedelta(hours=73))

    late = await harness.engine.converse(
        "the river one",
        timeout=PATIENT,
        reference=TurnReference(question_id=paused.clarification.question_id),
    )

    assert late.reference is ReferenceOutcome.EXPIRED
    settled = await harness.plans.get_question(paused.clarification.question_id)
    assert settled is not None
    assert settled.disposition is GoalQuestionDisposition.EXPIRED
    assert (settled.text, settled.about) == (None, None)
    goal = await harness.plans.get_goal(paused.turn.goal.goal_id)
    assert goal is not None
    assert goal.status is GoalStatus.ACTIVE, "decision 2: an expiry decides nothing"
    assert goal.last_engaged_at is not None, "§1: and the turn engaged it"


class _Advancing:
    """A clock a case moves rather than waits on (ADR-0009)."""

    def __init__(self) -> None:
        self._now = AT

    def __call__(self) -> Any:
        return self._now

    def advance(self, by: timedelta) -> None:
        """Move the reading forward."""
        self._now += by


# --------------------------------------------------------------------------- #
# Arms 10 to 12: resumption, the ask, and what the announcement says           #
# --------------------------------------------------------------------------- #


async def test_a_goal_is_resumed_from_another_conversation_by_explicit_reference() -> None:
    """§20 arm 10 and decision 5: the user points once and the work is here.

    "``conversation_id`` still reads **A**, ``last_engaged_in`` reads **B**, the goal is
    a candidate in **both**, and the **next** turn of B associates to it by the ordinary
    rule. The arm fails if ``conversation_id`` moved."
    """
    harness = Harness(
        planner=NoStepPlanner(), associator=_associating(AssociationVerdict.CONTINUES)
    )
    first = (await harness.conversations.begin(None)).id
    second = (await harness.conversations.begin(None)).id
    campsite = await _seed(
        harness.plans, _goal("goal-campsite", "book a campsite", conversation=first)
    )

    outcome = await harness.engine.converse(
        "make it Sunday",
        timeout=PATIENT,
        conversation_id=second,
        reference=TurnReference(goal_id=campsite.id),
    )

    assert harness.associator.call_count == 0, "§13: a reference makes no associate call"
    assert outcome.reference is None, "§11: a resolved goal reference reports nothing further"
    assert outcome.goal_engagement is not None
    assert outcome.goal_engagement.disposition is EngagementDisposition.RESUMED
    held = await harness.plans.get_goal(campsite.id)
    assert held is not None
    assert held.conversation_id == first, "§13: provenance is never rewritten"
    assert held.last_engaged_in == second

    from_first = await harness.plans.candidates_for(first, limit=8)
    from_second = await harness.plans.candidates_for(second, limit=8)
    assert [goal.id for goal in from_first.goals] == [campsite.id]
    assert [goal.id for goal in from_second.goals] == [campsite.id], "a candidate in both"

    next_turn = await harness.engine.converse(
        "and a river pitch", timeout=PATIENT, conversation_id=second
    )

    assert harness.associator.call_count == 1, "and the next turn associates by the ordinary rule"
    assert next_turn.turn is not None
    assert next_turn.turn.goal.goal_id == campsite.id


async def test_two_labels_ask_rather_than_pick_and_the_undecided_outcome_is_well_formed() -> None:
    """§20 arm 11: never a silent rewrite.

    "The turn asks, opens no goal, records no revision, **engages neither goal**, drives
    nothing, and takes **no** relevance read, episodic supplement or ``Planner.plan``
    call. Its outcome carries ``turn`` ``None``, a non-``None`` ``reply`` composed by
    ``orchestration`` from the typed value, ``reply_degraded`` ``False``,
    ``goal_engagement`` ``None``, and a ``GoalDisambiguation`` whose ``candidates`` are
    the two goals' outcome statements."
    """
    planner = NoStepPlanner()
    harness = Harness(
        planner=planner, associator=_associating(AssociationVerdict.UNDECIDED, "G1", "G2")
    )
    conversation = (await harness.conversations.begin(None)).id
    one = await _seed(
        harness.plans,
        _goal("goal-one", "book a campsite", conversation=conversation),
        engaged_in=conversation,
    )
    two = await _seed(
        harness.plans,
        _goal("goal-two", "book a flight", conversation=conversation),
        engaged_in=conversation,
    )

    outcome = await harness.engine.converse(
        "make it Sunday", timeout=PATIENT, conversation_id=conversation
    )

    assert outcome.turn is None
    assert outcome.step is None
    assert outcome.goal_engagement is None
    assert outcome.clarification is None
    assert outcome.reply is not None
    assert outcome.reply_degraded is False
    assert outcome.disambiguation is not None
    assert outcome.disambiguation.candidates == ("book a campsite", "book a flight")
    assert "book a campsite" in outcome.reply, "the reply is built from the typed value"
    assert planner._calls == 0, "§3: no Planner.plan call at all"
    for goal_id in (one.id, two.id):
        held = await harness.plans.get_goal(goal_id)
        assert held is not None
        assert len(held.interpretation) == 1, "no revision recorded"
    fresh = await harness.plans.candidates_for(conversation, limit=8)
    assert [goal.last_engaged_at for goal in fresh.goals] == [AT, AT], "§1: neither engaged"


async def test_the_ask_renders_a_goal_stated_in_another_script_as_the_user_wrote_it() -> None:
    """§5: the clarification is deterministic prose the **user** reads.

    The outcome statements are quoted so that a statement carrying a quotation mark or a
    backslash is unambiguous — not encoded. A goal the user stated in their own language
    rendered as escape sequences is §5's question made unreadable by a default, and the
    ask is *"composed by ``orchestration`` from the typed value"* rather than serialised.
    """
    harness = Harness(
        planner=NoStepPlanner(), associator=_associating(AssociationVerdict.UNDECIDED)
    )
    conversation = (await harness.conversations.begin(None)).id
    await _seed(
        harness.plans,
        _goal("goal-one", "日本旅行を予約する", conversation=conversation),
        engaged_in=conversation,
    )

    outcome = await harness.engine.converse(
        "make it Sunday", timeout=PATIENT, conversation_id=conversation
    )

    assert outcome.disambiguation is not None
    assert outcome.disambiguation.candidates == ("日本旅行を予約する",)
    assert outcome.reply is not None
    assert "日本旅行を予約する" in outcome.reply, "the user reads their own words back"
    assert "\\u" not in outcome.reply, "and never an escape sequence"


async def test_the_ask_is_in_candidacy_order_whatever_order_the_labels_named() -> None:
    """§5: "``candidates`` holds exactly those goals' outcome statements, **in candidacy order**".

    The labels are an answer *about a set* and carry no ordering of their own, so a
    ``("G2", "G1")`` must ask the same question a ``("G1", "G2")`` asks. Ordering the ask
    by the labels would make what the user reads depend on which way round the model
    happened to list two goals — and §2's candidacy order is the order the set was
    rendered in and the order §1 states.
    """
    harness = Harness(
        planner=NoStepPlanner(), associator=_associating(AssociationVerdict.UNDECIDED, "G2", "G1")
    )
    conversation = (await harness.conversations.begin(None)).id
    await _seed(
        harness.plans,
        _goal("goal-one", "book a campsite", conversation=conversation),
        engaged_in=conversation,
    )
    await _seed(
        harness.plans,
        _goal("goal-two", "book a flight", conversation=conversation),
        engaged_in=conversation,
    )

    outcome = await harness.engine.converse(
        "make it Sunday", timeout=PATIENT, conversation_id=conversation
    )

    assert outcome.disambiguation is not None
    assert outcome.disambiguation.candidates == ("book a campsite", "book a flight"), (
        "§1's order — the greatest last_engaged_at first, the goal_id ascending as the "
        "tie-break — and not the order the labels arrived in"
    )


async def test_fewer_than_two_resolving_labels_asks_over_the_whole_candidacy() -> None:
    """§20 arm 11's second half, three ways over one candidate.

    "An unparseable model answer, an explicit decline with no labels, and a single label
    outside the candidacy's range. Each returns ``UNDECIDED``, each constructs a
    ``GoalDisambiguation`` whose ``candidates`` hold that one goal's outcome statement,
    and none fails the turn, invents a candidate or picks the one it has."
    """
    for labels in ((), ("G9",), ("nonsense",)):
        harness = Harness(
            planner=NoStepPlanner(),
            associator=_associating(AssociationVerdict.UNDECIDED, *labels),
        )
        conversation = (await harness.conversations.begin(None)).id
        await _seed(
            harness.plans,
            _goal("goal-one", "book a campsite", conversation=conversation),
            engaged_in=conversation,
        )

        outcome = await harness.engine.converse(
            "make it Sunday", timeout=PATIENT, conversation_id=conversation
        )

        assert outcome.disambiguation is not None, labels
        assert outcome.disambiguation.candidates == ("book a campsite",), labels
        assert outcome.turn is None, labels


async def test_an_associates_verdict_naming_a_label_outside_the_range_never_picks() -> None:
    """§3: "A label that resolves to nothing is ``UNDECIDED`` and never a pick".

    "**No implementation falls back to the focused goal, to the first candidate, to the
    most recent one, or to any tie-break at all**, because every one of those picks a
    goal the model did not name."
    """
    harness = Harness(
        planner=NoStepPlanner(), associator=_associating(AssociationVerdict.ASSOCIATES, "G7")
    )
    conversation = (await harness.conversations.begin(None)).id
    await _seed(
        harness.plans,
        _goal("goal-one", "book a campsite", conversation=conversation),
        engaged_in=conversation,
    )

    outcome = await harness.engine.converse(
        "make it Sunday", timeout=PATIENT, conversation_id=conversation
    )

    assert outcome.disambiguation is not None, "the answer is the ask"
    assert outcome.goal_engagement is None


async def test_the_engagement_says_what_moved_and_a_continuation_says_nothing_moved() -> None:
    """§20 arm 12: the announcement rule, over the facts a surface renders it from.

    ``CONTINUED`` with ``revised`` ``False`` produces no sentence; a revision that added
    an element puts its text in ``added`` with ``removed`` empty.
    """
    planner = _Asking(None)
    harness = Harness(planner=planner, associator=_associating(AssociationVerdict.CONTINUES))
    conversation = (await harness.conversations.begin(None)).id
    campsite = await _seed(
        harness.plans,
        _goal("goal-campsite", "book a campsite", conversation=conversation),
        engaged_in=conversation,
    )

    plain = await harness.engine.converse("carry on", timeout=PATIENT, conversation_id=conversation)

    assert plain.goal_engagement is not None
    assert plain.goal_engagement.disposition is EngagementDisposition.CONTINUED
    assert plain.goal_engagement.revised is False
    assert plain.goal_engagement.outcome == "book a campsite"
    assert (plain.goal_engagement.added, plain.goal_engagement.removed) == ((), ())

    planner.understanding = ProposedUnderstanding(
        retains_outcome=True,
        constraints=(ProposedElement(text="under fifty pounds", ground=Ground.INFERRED),),
    )

    revised = await harness.engine.converse(
        "and under fifty pounds", timeout=PATIENT, conversation_id=conversation
    )

    assert revised.goal_engagement is not None
    assert revised.goal_engagement.revised is True
    assert revised.goal_engagement.added == ("under fifty pounds",)
    assert revised.goal_engagement.removed == ()
    assert revised.goal_engagement.outcome_changed is False
    assert campsite.id == (revised.turn.goal.goal_id if revised.turn else None)


# --------------------------------------------------------------------------- #
# Arms 14, 15, 18, 20, 22, 24, 25, 29, 32: the rest M3 owes                    #
# --------------------------------------------------------------------------- #


async def test_a_spoken_turn_builds_no_candidacy_and_makes_no_associate_call() -> None:
    """§20 arms 14 and 15: nothing stored reaches a channel of unbounded audience.

    Arm 14's state entire: "A conversation holding two candidates — one carrying an
    ``INFERRED`` outcome, one carrying a ``USER_STATED`` outcome, a stored
    ``FROM_EVIDENCE`` constraint and an open question — driven through
    ``converse_spoken``: **no ``associate`` call is made**, no ``GoalCandidacy`` is
    constructed, the turn opens a goal of its own, and the prompt its planner receives
    contains **no byte** of either candidate's outcome text, of the stored constraint's
    text, or of the open question's text. Its brief carries this turn's request, no
    elements and no ``open_questions``. The arm is asserted over the **production**
    renderer and over the absence of the call, not over a filter."

    And arm 15's half: "no ``GoalEngagement`` carries ``RESUMED``, ``REOPENED`` or
    ``CONTINUED``". The **same** conversation driven through ``converse`` makes the call
    over **both** candidates, which is ADR-0203 §1's bounded-operation clause.
    """
    planner = _Recording()
    harness = Harness(planner=planner, associator=_associating(AssociationVerdict.CONTINUES))
    conversation = (await harness.conversations.begin(None)).id
    await _seed(
        harness.plans,
        _inferred_goal("goal-walk", "walk the pennine way", conversation=conversation),
        engaged_in=conversation,
    )
    campsite = await _seed(
        harness.plans,
        _goal_with_constraint(
            "goal-campsite",
            "book a campsite",
            constraint="under fifty pounds a night",
            conversation=conversation,
        ),
        engaged_in=conversation,
    )
    await harness.plans.open_attempt(
        GoalAttempt(
            id="attempt-campsite",
            goal_id=campsite.id,
            opened_at=AT,
            effort=AttemptEffort(kind=AttemptKind.CONVERSATIONAL),
        )
    )
    written = await harness.plans.record_question(
        GoalQuestion(
            id="question-standing",
            goal_id=campsite.id,
            attempt_id="attempt-campsite",
            text="Which of the riverside pitches did you mean?",
            about="a pitch by the river",
            asked_at=AT,
            expires_at=AT + timedelta(hours=72),
        )
    )
    assert written, "the candidate holds an open question"
    secrets = (
        "walk the pennine way",
        "book a campsite",
        "under fifty pounds a night",
        "Which of the riverside pitches did you mean?",
    )

    spoken = await harness.engine.converse_spoken(
        _spoken_audio(), plays=(_MP4,), timeout=PATIENT, conversation_id=conversation
    )

    assert harness.associator.call_count == 0, "§15: such a turn associates to no stored goal"
    assert spoken.outcome is not None
    assert spoken.outcome.disambiguation is None
    assert spoken.outcome.goal_engagement is not None
    assert spoken.outcome.goal_engagement.disposition is EngagementDisposition.OPENED
    brief = planner.briefs[-1]
    assert (brief.constraints, brief.criteria, brief.conditions) == ((), (), ()), (
        "arm 14: the brief carries no elements"
    )
    assert brief.open_questions == (), "nor any open question"
    rendered = planner.rendered()
    for secret in secrets:
        assert secret not in rendered, f"arm 14: no byte of {secret!r} reaches the prompt"
    assert "what did I say I would do this week" in rendered, (
        "and this turn's own request does — so the absences above are the filter working "
        "rather than an empty render"
    )

    await harness.engine.converse(
        "and a river pitch", timeout=PATIENT, conversation_id=conversation
    )

    assert harness.associator.call_count == 1, "ADR-0203 §1: a bounded operation runs over it all"
    (candidacy,) = harness.associator.calls
    named = {candidate.outcome for candidate in candidacy.candidates}
    assert {"walk the pennine way", "book a campsite"} <= named, (
        "over **both** candidates — the two the spoken turn was told nothing about"
    )


def _inferred_goal(goal_id: str, outcome: str, *, conversation: str) -> Goal:
    """A goal whose outcome the system inferred rather than took from the user."""
    goal = _goal(goal_id, outcome, conversation=conversation)
    (interpretation,) = goal.interpretation
    return goal.model_copy(
        update={
            "interpretation": (
                interpretation.model_copy(
                    update={"outcome_ground": Ground.INFERRED, "outcome_span": None}
                ),
            )
        }
    )


def _goal_with_constraint(
    goal_id: str, outcome: str, *, constraint: str, conversation: str
) -> Goal:
    """A goal carrying one stored ``FROM_EVIDENCE`` constraint."""
    goal = _goal(goal_id, outcome, conversation=conversation)
    (interpretation,) = goal.interpretation
    return goal.model_copy(
        update={
            "interpretation": (
                interpretation.model_copy(
                    update={
                        "constraints": (
                            GoalElement(
                                text=constraint,
                                ground=Ground.FROM_EVIDENCE,
                                evidence_id="evidence-nightly-rate",
                            ),
                        )
                    }
                ),
            )
        }
    )


def _spoken_audio() -> SpokenAudio:
    """One recording, in the format the canonical fake transcriber reads."""
    return SpokenAudio(content=b64encode(b"which campsite").decode("ascii"), media_type=_MP4)


def test_no_notification_producer_is_built_on_any_path_of_this_decision() -> None:
    """§20 arm 29, asserted over the shipped tree rather than as a reading.

    "Raising a question, a question expiring, a question superseded and a goal paused
    each produce **no** ``NotificationCandidate``, no ``NotificationPolicy`` call and no
    ``NotificationStore`` row — asserted over the shipped tree, so that the absence of a
    producer is a fact rather than a reading of this document."

    §10 makes that absence this decision's ruling rather than an oversight: "**this
    decision builds no producer at all** … A producer is a decision with its own ADR,
    its own class, its own reach level and its own budget, and it is not made by
    inference from a deadline this decision added for a different reason."
    """
    named = sorted(
        name
        for name in ("NotificationCandidate", "NotificationPolicy", "NotificationStore")
        if name in _GOALS.read_text(encoding="utf-8")
    )

    assert named == [], f"ADR-0250 §10 builds no notification producer at all (found {named})"


class _Refusing(FakePlanStore):
    """A store whose one-open gate always refuses (ADR-0250 §9)."""

    async def record_question(self, question: Any, /) -> bool:
        """Answer ``False``, as a goal already holding an open question does."""
        return False


async def test_a_refused_question_is_not_reported() -> None:
    """§20 arm 20: a question exists only where the store accepted it.

    "``record_question`` answering ``False``: the outcome's ``clarification`` is
    ``None``, the attempt's state is **not** moved, and the turn still drives no
    side-effecting step."
    """
    model = FakeModelProvider()
    harness = Harness(
        planner=_Asking(),
        plans=_Refusing(now=lambda: AT),
        composing=ComposingStage(model=model, streaming=FakeStreamingCompleter()),
    )

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.clarification is None, "§10: nothing durable is outstanding"
    assert outcome.turn is not None
    (attempt,) = await harness.plans.attempts_of(outcome.turn.goal.goal_id)
    assert attempt.state is not AttemptState.AWAITING_CLARIFICATION
    assert outcome.step is None, "§10: the turn still declines to act"
    assert any(
        "Which campsite did you mean?" in message.content for message in model.calls[-1].messages
    ), (
        "§10: **the turn still declines to act in that case** and **its reply still "
        "states the ambiguity** — what is missing is a durable question to answer, not "
        "the question itself"
    )


async def test_the_candidacy_and_the_reference_carry_no_identifier() -> None:
    """§20 arm 22(b), driven from a turn carrying a ``TurnReference`` (#2306).

    "Given a candidacy built from goals with distinctive ids and a turn carrying a
    ``TurnReference`` with a distinctive ``goal_id``, the prompt the production
    associator builds contains neither string." The projection is ``orchestration``'s,
    so this half is driven here: what the loop hands the seam is captured and asserted
    over.
    """
    harness = Harness(planner=NoStepPlanner(), associator=_associating(AssociationVerdict.FRESH))
    conversation = (await harness.conversations.begin(None)).id
    await _seed(
        harness.plans,
        _goal("goal-distinctive-zzz", "book a campsite", conversation=conversation),
        engaged_in=conversation,
    )

    await harness.engine.converse(
        "something new",
        timeout=PATIENT,
        conversation_id=conversation,
        reference=TurnReference(goal_id="goal-nothing-holds-yyy"),
    )

    (candidacy,) = harness.associator.calls
    rendered = candidacy.model_dump_json()
    assert "goal-distinctive-zzz" not in rendered
    assert "goal-nothing-holds-yyy" not in rendered
    assert conversation not in rendered


async def test_an_unknown_reference_is_reported_even_where_nothing_was_engaged() -> None:
    """§20 arm 32: the handle the user gave resolved to nothing, and they are told.

    "``reference`` reads ``UNKNOWN``, ``goal_engagement`` is ``None``, and a
    ``disambiguation`` is carried. The arm fails if a ``GoalEngagement`` is constructed
    to hold the reference outcome, or if the ``UNKNOWN`` is dropped."
    """
    harness = Harness(
        planner=NoStepPlanner(), associator=_associating(AssociationVerdict.UNDECIDED)
    )
    conversation = (await harness.conversations.begin(None)).id
    await _seed(
        harness.plans,
        _goal("goal-one", "book a campsite", conversation=conversation),
        engaged_in=conversation,
    )

    outcome = await harness.engine.converse(
        "make it Sunday",
        timeout=PATIENT,
        conversation_id=conversation,
        reference=TurnReference(question_id="no-such-question"),
    )

    assert outcome.reference is ReferenceOutcome.UNKNOWN
    assert outcome.goal_engagement is None
    assert outcome.disambiguation is not None


async def test_reopening_a_closed_goal_opens_an_attempt_and_supersedes_its_question() -> None:
    """§20 arms 24 and 25: ``SUPERSEDED`` has exactly one producer.

    "Reopening a closed goal whose earlier attempt's question is still ``OPEN`` settles
    it ``SUPERSEDED`` and clears its content in the same sequence that opens the new
    attempt." And "a turn that **reopens** a closed goal opens a new attempt".
    """
    planner = _Asking()
    harness = Harness(planner=planner)
    paused = await harness.engine.converse(_ASKED, timeout=PATIENT)
    assert paused.turn is not None
    assert paused.clarification is not None
    goal_id = paused.turn.goal.goal_id
    stored = await harness.plans.get_goal(goal_id)
    assert stored is not None
    await harness.plans.set_goal_status(
        goal_id, status=GoalStatus.ACHIEVED, at=AT, expected_version=stored.version
    )
    planner.understanding = None

    reopened = await harness.engine.converse(
        "actually, carry on with that",
        timeout=PATIENT,
        reference=TurnReference(goal_id=goal_id),
    )

    assert reopened.goal_engagement is not None
    assert reopened.goal_engagement.disposition is EngagementDisposition.REOPENED
    settled = await harness.plans.get_question(paused.clarification.question_id)
    assert settled is not None
    assert settled.disposition is GoalQuestionDisposition.SUPERSEDED
    assert (settled.text, settled.about) == (None, None)
    attempts = await harness.plans.attempts_of(goal_id)
    assert len(attempts) == 2, "§12: a reopened goal starts a new attempt"
    assert attempts[-1].phase is AttemptPhase.UNDERSTAND or attempts[-1].plan_ids
    held = await harness.plans.get_goal(goal_id)
    assert held is not None
    assert held.status is GoalStatus.ACTIVE


async def test_a_label_that_resolves_to_nothing_drops_the_question_and_harms_nothing() -> None:
    """§20 arm 5's third limb: three labels that resolve to nothing, each dropped.

    "A label outside the proposal's tuples, a label of a different tuple, and a label
    naming an element ADR-0249 §7's ground resolution dropped — each **dropped** with the
    turn otherwise unharmed."
    """
    for about in ("S9", "C1", "D1"):
        harness = Harness(
            planner=_Asking(
                ProposedUnderstanding(
                    retains_outcome=True,
                    criteria=(
                        ProposedElement(text="a pitch by the river", ground=Ground.INFERRED),
                    ),
                    questions=(ProposedQuestion(text="Which one?", about=about),),
                )
            )
        )

        outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

        assert outcome.clarification is None, about
        assert outcome.turn is not None, about
        assert outcome.goal_engagement is not None, "and the turn is otherwise unharmed"


async def test_the_first_resolving_material_question_is_taken_and_the_rest_dropped() -> None:
    """§7: "At most one question is taken from a call", and it is the first that qualifies.

    "Where several come back, the loop takes the **first in tuple order** whose ``about``
    resolves and whose subject is material, and drops every other, silently. The order is
    the tuple's and there is no ranking, no scoring and no second call."
    """
    harness = Harness(
        planner=_Asking(
            ProposedUnderstanding(
                retains_outcome=True,
                constraints=(ProposedElement(text="under fifty pounds", ground=Ground.INFERRED),),
                criteria=(ProposedElement(text="a pitch by the river", ground=Ground.INFERRED),),
                questions=(
                    ProposedQuestion(text="Outside the tuples?", about="S9"),
                    ProposedQuestion(text="How much is your budget?", about="C1"),
                    ProposedQuestion(text="Which campsite did you mean?", about="S1"),
                    ProposedQuestion(text="And which weekend?", about=None),
                ),
            )
        )
    )

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.clarification is not None
    assert outcome.clarification.text == "Which campsite did you mean?", (
        "the first that both resolves and is material — the unresolvable one is dropped "
        "and the `constraints` one is immaterial on a turn proposing no act"
    )
    assert outcome.turn is not None
    (standing,) = await harness.plans.outstanding_questions()
    assert standing.goal_id == outcome.turn.goal.goal_id, "§8: one open question per goal"


async def test_a_spoken_turn_whose_planner_raised_is_never_left_silent() -> None:
    """§20 arm 13: the user hears the question.

    "A turn whose planner raised a clarification, driven through ``converse_spoken``:
    ``outcome.reply`` is non-``None``, ``spoken`` renders it, ``spoken_degraded`` is
    ``False``, and the user hears the question. The arm fails if that path yields
    ``spoken`` ``None``."
    """
    harness = Harness(planner=_Asking())

    spoken = await harness.engine.converse_spoken(_spoken_audio(), plays=(_MP4,), timeout=PATIENT)

    assert spoken.outcome is not None
    assert spoken.outcome.clarification is not None
    assert spoken.outcome.reply is not None
    assert spoken.spoken is not None, "ADR-0200 §4: `spoken` is the rendering of `reply`"
    assert spoken.spoken_degraded is False


async def test_a_referenced_turns_brief_carries_the_goal_id_the_reference_resolved_to() -> None:
    """§20 arm 33: ``GoalBrief.goal_id`` still crosses the seam on a referenced turn.

    "The brief handed to ``Planner.plan`` carries that goal's ``goal_id``,
    ``Engine._check_plan_is_for_goal`` compares the plan's against it, and the prompt
    ``_render_request`` builds contains neither string — ADR-0249 §9 asserted unchanged
    across this decision."
    """
    planner = _Recording()
    harness = Harness(planner=planner)
    conversation = (await harness.conversations.begin(None)).id
    campsite = await _seed(
        harness.plans, _goal("goal-campsite", "book a campsite", conversation=conversation)
    )

    outcome = await harness.engine.converse(
        "make it Sunday",
        timeout=PATIENT,
        conversation_id=conversation,
        reference=TurnReference(goal_id=campsite.id),
    )

    assert planner.briefs[-1].goal_id == campsite.id
    assert outcome.turn is not None
    assert outcome.turn.plan.goal_id == campsite.id, "`_check_plan_is_for_goal` compared them"


class _Recording(_Asking):
    """A planner that keeps every brief it was handed and proposes nothing."""

    def __init__(self) -> None:
        super().__init__(None)
        self.briefs: list[Any] = []
        self.fields: list[dict[str, Any]] = []

    async def plan(self, goal: Any, **fields: Any) -> Any:
        """Record the brief and what came with it, then plan as :class:`_Asking` does."""
        self.briefs.append(goal)
        self.fields.append(fields)
        return await super().plan(goal, **fields)

    def rendered(self) -> str:
        """The last call's prompt, through the **production** renderer (ADR-0249 §9)."""
        fields = self.fields[-1]
        return _render_request(
            self.briefs[-1],
            fields["context"],
            fields.get("memories", ()),
            fields.get("files", ()),
            fields.get("read_outcomes", ()),
            utterance=fields["utterance"],
            evidence=fields.get("evidence", ()),
        )


async def test_a_crash_between_the_settle_and_the_revision_leaves_a_legible_state() -> None:
    """§20 arm 31's first window, and nothing repairs it.

    "With failure injected between ``settle_question`` and ``record_interpretation``, the
    restarted system reads a question ``ANSWERED`` with its content cleared, an attempt
    still ``AWAITING_CLARIFICATION`` and an unchanged interpretation; the goal is still
    open, still a candidate, and the next turn associating to it resumes the attempt.
    **No start-up pass, sweep, reconciliation or repair runs.**"
    """
    goals = iter(f"g-{n}" for n in range(1, 100))
    plans = _FailingRevision(now=lambda: AT)
    conversations = FakeConversationStore(now=lambda: AT)
    planner = _Asking()
    harness = Harness(
        planner=planner,
        plans=plans,
        conversation_store=conversations,
        loop_id_factory=lambda: next(goals),
    )
    paused = await harness.engine.converse(_ASKED, timeout=PATIENT)
    assert paused.turn is not None
    assert paused.clarification is not None
    goal_id = paused.turn.goal.goal_id
    conversation = paused.conversation_id
    assert conversation is not None
    before = await plans.get_goal(goal_id)
    assert before is not None
    plans.fail = True

    with pytest.raises(PlanningError):
        await harness.engine.converse(
            "the river one",
            timeout=PATIENT,
            conversation_id=conversation,
            reference=TurnReference(question_id=paused.clarification.question_id),
        )

    settled = await plans.get_question(paused.clarification.question_id)
    assert settled is not None
    assert settled.disposition is GoalQuestionDisposition.ANSWERED
    assert (settled.text, settled.about) == (None, None)
    (attempt,) = await plans.attempts_of(goal_id)
    assert attempt.state is AttemptState.AWAITING_CLARIFICATION, "the answer did not land"
    goal = await plans.get_goal(goal_id)
    assert goal is not None
    assert goal.interpretation == before.interpretation, "and the interpretation is unchanged"
    assert goal.status is GoalStatus.ACTIVE, "the goal is still open and still a candidate"
    # --- the restart, which runs no start-up pass and repairs nothing ---
    plans.fail = False
    planner.understanding = None
    restarted = Harness(
        planner=planner,
        plans=plans,
        conversation_store=conversations,
        loop_id_factory=lambda: next(goals),
        associator=_associating(AssociationVerdict.CONTINUES),
    )
    assert await restarted.engine.pending_confirmations() == (), "no start-up pass runs"
    unrepaired = await plans.get_question(paused.clarification.question_id)
    assert unrepaired == settled, "nothing re-opened the question or rewrote its row"

    next_turn = await restarted.engine.converse(
        "carry on then", timeout=PATIENT, conversation_id=conversation
    )

    assert next_turn.goal_engagement is not None
    assert next_turn.turn is not None
    assert next_turn.turn.goal.goal_id == goal_id, "§11: the next turn associating to it"
    (resumed,) = await plans.attempts_of(goal_id)
    assert resumed.id == attempt.id, "the same attempt, and no new one was opened"
    assert resumed.state is not AttemptState.AWAITING_CLARIFICATION, (
        "§11: 'the next turn that associates to it resumes the attempt' — and the user's "
        "recourse for the lost answer is to say it again"
    )


class _FailingRevision(FakePlanStore):
    """A store that refuses to append a revision once ``fail`` is set."""

    fail: bool = False

    async def record_interpretation(self, revision: Any, /) -> Any:
        """Append as the fake does, or refuse where the case armed a failure."""
        if self.fail:
            msg = "the fake store refuses this write"
            raise PlanningError(msg)
        return await super().record_interpretation(revision)


async def test_a_crash_between_the_question_and_the_pause_leaves_it_answerable() -> None:
    """§20 arm 31's **second** window, and nothing repairs it either.

    "With failure injected between ``record_question`` and ``commit_attempt``, the
    restarted system reads an ``OPEN`` question on a ``RUNNING`` attempt, and that
    question is **answerable**. **No start-up pass, sweep, reconciliation or repair runs
    in either case**, and no implementation refuses a question whose attempt is not
    ``AWAITING_CLARIFICATION``."

    §11 states the same window in terms — *"a crash between them leaves an ``OPEN``
    question on an attempt still ``RUNNING``. It is answerable, its ``goal_id`` still
    reaches the goal, its deadline still frees it, and the turn that answers it moves the
    attempt by §11's ordinary path."* The restart is a second façade over the same stores,
    for the reason arm 7's case states.
    """
    goals = iter(f"g-{n}" for n in range(1, 100))
    plans = _FailingPause(now=lambda: AT)
    conversations = FakeConversationStore(now=lambda: AT)
    planner = _Asking()
    harness = Harness(
        planner=planner,
        plans=plans,
        conversation_store=conversations,
        loop_id_factory=lambda: next(goals),
    )
    plans.fail = True

    with pytest.raises(PlanningError):
        await harness.engine.converse(_ASKED, timeout=PATIENT)

    (goal,) = (await plans.export()).goals
    (attempt,) = await plans.attempts_of(goal.id)
    assert attempt.state is AttemptState.RUNNING, "the pause never landed"
    question = await plans.open_question(goal.id)
    assert question is not None
    assert question.disposition is GoalQuestionDisposition.OPEN
    assert question.attempt_id == attempt.id
    # --- the restart, which resolves nothing and is asked to resolve nothing ---
    planner.understanding = None
    restarted = Harness(
        planner=planner,
        plans=plans,
        conversation_store=conversations,
        loop_id_factory=lambda: next(goals),
    )
    assert await restarted.engine.pending_confirmations() == (), "no start-up pass runs"

    answer = await restarted.engine.converse(
        "the river one", timeout=PATIENT, reference=TurnReference(question_id=question.id)
    )

    assert answer.reference is ReferenceOutcome.ANSWERED, (
        "arm 31: no implementation refuses a question whose attempt is not AWAITING_CLARIFICATION"
    )
    assert answer.turn is not None
    assert answer.turn.goal.goal_id == goal.id
    settled = await plans.get_question(question.id)
    assert settled is not None
    assert settled.disposition is GoalQuestionDisposition.ANSWERED
    assert (settled.text, settled.about) == (None, None), "§8: settling clears the content"
    (same,) = await plans.attempts_of(goal.id)
    assert same.id == attempt.id, "§11: the same attempt, and no new one was opened"


class _FailingPause(FakePlanStore):
    """A store that refuses the transition into ``AWAITING_CLARIFICATION``."""

    fail: bool = False

    async def commit_attempt(self, transition: Any, /) -> Any:
        """Commit as the fake does, or refuse the pause where the case armed a failure."""
        if self.fail and transition.to_state is AttemptState.AWAITING_CLARIFICATION:
            msg = "the fake store refuses this write"
            raise PlanningError(msg)
        return await super().commit_attempt(transition)


async def test_a_siblings_failed_ground_does_not_drop_a_valid_questions_subject() -> None:
    """§7: a question is dropped where **its own** element is not in the recorded revision.

    "A question about an element whose ground did not resolve is itself **dropped**,
    because the element it is about is not in the recorded revision and a question about
    nothing is not a question." A **sibling**'s failure is not that: ADR-0249 §7 drops
    the sibling and records the rest, so a question about a surviving element is still a
    question about something.
    """
    harness = Harness(
        planner=_Asking(
            ProposedUnderstanding(
                retains_outcome=True,
                criteria=(
                    ProposedElement(text="a pitch by the river", ground=Ground.INFERRED),
                    ProposedElement(
                        text="near the gold standard",
                        ground=Ground.FROM_EVIDENCE,
                        evidence_label="M9",
                    ),
                ),
                questions=(ProposedQuestion(text="Which campsite did you mean?", about="S1"),),
            )
        )
    )

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.clarification is not None, "the sibling failed, not the subject"
    assert outcome.turn is not None
    question = await harness.plans.open_question(outcome.turn.goal.goal_id)
    assert question is not None
    assert question.about == "a pitch by the river"


async def test_a_question_about_an_element_whose_own_ground_failed_is_dropped() -> None:
    """§7's other half, over the element the question actually names.

    The subject's own ``FROM_EVIDENCE`` label resolves to nothing, so ADR-0249 §7 drops
    the element and §7 drops the question with it — silently, without failing the turn.
    """
    harness = Harness(
        planner=_Asking(
            ProposedUnderstanding(
                retains_outcome=True,
                criteria=(
                    ProposedElement(
                        text="near the gold standard",
                        ground=Ground.FROM_EVIDENCE,
                        evidence_label="M9",
                    ),
                    ProposedElement(text="a pitch by the river", ground=Ground.INFERRED),
                ),
                questions=(ProposedQuestion(text="Which standard?", about="S1"),),
            )
        )
    )

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.clarification is None
    assert outcome.turn is not None
    assert await harness.plans.open_question(outcome.turn.goal.goal_id) is None


async def test_a_zero_padded_candidate_label_never_selects_a_goal() -> None:
    """§3: the scheme is ``G`` and *n* "in decimal with **no padding**", and nothing else.

    "A string that does not match the form … is treated as ``UNDECIDED`` and the turn
    asks. **No implementation falls back to the focused goal, to the first candidate, to
    the most recent one, or to any tie-break at all.**"
    """
    harness = Harness(
        planner=NoStepPlanner(), associator=_associating(AssociationVerdict.ASSOCIATES, "G01")
    )
    conversation = (await harness.conversations.begin(None)).id
    campsite = await _seed(
        harness.plans,
        _goal("goal-campsite", "book a campsite", conversation=conversation),
        engaged_in=conversation,
    )

    outcome = await harness.engine.converse(
        "make it Sunday", timeout=PATIENT, conversation_id=conversation
    )

    assert outcome.disambiguation is not None, "a padded ordinal is not the form, so the turn asks"
    assert outcome.goal_engagement is None
    held = await harness.plans.get_goal(campsite.id)
    assert held is not None
    assert len(held.interpretation) == 1, "and nothing was revised against it"


async def test_a_zero_padded_subject_label_never_resolves_a_question() -> None:
    """§7 reads ADR-0249 §9's scheme over the proposal, padding included.

    The same refusal one sequence over: ``S01`` is not a label this side resolves, so the
    question is dropped rather than pointed at ``criteria``'s first element.
    """
    harness = Harness(
        planner=_Asking(
            ProposedUnderstanding(
                retains_outcome=True,
                criteria=(ProposedElement(text="a pitch by the river", ground=Ground.INFERRED),),
                questions=(ProposedQuestion(text="Which campsite?", about="S01"),),
            )
        )
    )

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.clarification is None
    assert outcome.turn is not None
    assert await harness.plans.open_question(outcome.turn.goal.goal_id) is None


async def test_an_expiry_that_loses_the_race_reports_what_the_store_holds() -> None:
    """§9's resolve-once gate, on the **expiry** settlement as well as on the answer.

    "A caller that lost the compare-and-swap records nothing, revises nothing and reports
    the settled state." A second party that answered the question between this turn's read
    and its write left a disposition that is now the truth, and §11 states the outcome over
    that disposition — so reporting ``EXPIRED`` would tell the user their answer never
    arrived.
    """
    clock = _Advancing()
    plans = _RacingSettlement(now=lambda: AT)
    harness = Harness(planner=_Asking(), plans=plans, now=clock)
    paused = await harness.engine.converse(_ASKED, timeout=PATIENT)
    assert paused.clarification is not None
    clock.advance(timedelta(hours=73))
    plans.answer_first = paused.clarification.question_id

    late = await harness.engine.converse(
        "the river one",
        timeout=PATIENT,
        reference=TurnReference(question_id=paused.clarification.question_id),
    )

    assert late.reference is ReferenceOutcome.ALREADY_SETTLED, (
        "the question was answered by somebody else, and this turn reports that"
    )
    settled = await plans.get_question(paused.clarification.question_id)
    assert settled is not None
    assert settled.disposition is GoalQuestionDisposition.ANSWERED, (
        "§9: the loser records nothing of its own — the winner's disposition stands, "
        "and no second settlement was written over it"
    )
    assert late.goal_engagement is not None, (
        "and §11 is what the turn then does: 'terminal already → nothing is settled and "
        "the turn proceeds as an ordinary engagement of the goal'. It acts on **its own "
        "request**, which the winning turn did not carry, so a revision here is that "
        "request being understood rather than one answer applied twice"
    )
    assert late.turn is not None, "which is an ordinary turn, planner call and all"


class _RacingSettlement(FakePlanStore):
    """A store that lets a second party settle the question just before this caller does."""

    answer_first: str | None = None

    async def settle_question(self, question_id: str, /, **fields: Any) -> bool:
        """Settle as the fake does, after letting the armed second party settle first."""
        if self.answer_first == question_id:
            self.answer_first = None
            await super().settle_question(
                question_id, disposition=GoalQuestionDisposition.ANSWERED, at=AT
            )
        return await super().settle_question(question_id, **fields)
