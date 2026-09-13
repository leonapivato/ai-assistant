"""ADR-0250's three promoted operations, its focus rule, and the arms around them.

``goals``, ``withdraw_clarification`` and ``abandon_goal`` (§§12, 15); §1's four
engaging acts and what leaves focus alone; §14's elision disclosure; §11's crash
windows; and the brief's one open-question text (§8). Each is driven through the
production engine, because each is a fact about what the store holds afterwards.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from test_engine import AT, PATIENT, Harness, NoStepPlanner
from test_engine_goal_association import (
    _Advancing,
    _Asking,
    _associating,
    _goal,
    _seed,
)

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    MAX_ASSOCIATION_CANDIDATES,
    AssociationVerdict,
    AttemptState,
    ClarificationWithdrawal,
    EngagementDisposition,
    GoalAbandonment,
    GoalQuestionDisposition,
    GoalStatus,
    Ground,
    ProposedElement,
    ProposedUnderstanding,
    ReferenceOutcome,
    TurnReference,
)
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.testing import FakeModelProvider, FakeStreamingCompleter

if TYPE_CHECKING:
    from ai_assistant.core.types import GoalBrief

_ASKED: Final = "book the usual campsite for next weekend"


# --------------------------------------------------------------------------- #
# §15: the listing                                                            #
# --------------------------------------------------------------------------- #


async def test_goals_lists_what_is_outstanding_in_the_engagement_order() -> None:
    """§15: the listing a user learns what is outstanding from, in §1's order.

    "The **focused goal** … with the **greatest ``last_engaged_at``**, with the
    ``goal_id`` ascending as the tie-break, and a goal whose ``last_engaged_at`` is
    absent sorts **after** every goal carrying one."
    """
    harness = Harness(planner=NoStepPlanner())
    conversation = (await harness.conversations.begin(None)).id
    await _seed(harness.plans, _goal("g-never", "an untouched goal", conversation=conversation))
    older = _goal("g-older", "book a flight", conversation=conversation)
    await harness.plans.save_goal(older)
    await harness.plans.engage_goal(
        older.id, at=AT, conversation_id=conversation, expected_version=older.version
    )
    newer = _goal("g-newer", "book a campsite", conversation=conversation)
    await harness.plans.save_goal(newer)
    await harness.plans.engage_goal(
        newer.id,
        at=AT + timedelta(hours=1),
        conversation_id=conversation,
        expected_version=newer.version,
    )

    listed = await harness.engine.goals()

    assert [summary.id for summary in listed] == ["g-newer", "g-older", "g-never"]
    assert [summary.outcome for summary in listed] == [
        "book a campsite",
        "book a flight",
        "an untouched goal",
    ]
    assert all(not summary.paused for summary in listed), "no attempt, so nothing is paused"


async def test_goals_computes_paused_and_carries_the_open_question() -> None:
    """§15: ``paused`` is computed and never stored, and the engine computes it.

    ADR-0249 §5's own derivation: "the goal's status is ``ACTIVE`` and its current
    attempt's state is ``AWAITING_CLARIFICATION``, ``AWAITING_AUTHORIZATION`` or
    ``BLOCKED``" — "**The engine computes it**, so that two surfaces cannot render it
    differently … and **no adapter derives it**."
    """
    harness = Harness(planner=_Asking())

    paused = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert paused.clarification is not None
    (summary,) = await harness.engine.goals()
    assert summary.paused is True
    assert summary.status is GoalStatus.ACTIVE
    assert summary.clarification is not None
    assert summary.clarification.question_id == paused.clarification.question_id
    assert summary.clarification.text == "Which campsite did you mean?"


async def test_goals_refuses_a_non_positive_limit_and_a_negative_offset() -> None:
    """§15: paged on ADR-0085 §3's own convention, refused as every other page is."""
    harness = Harness(planner=NoStepPlanner())

    with pytest.raises(ValueError, match="positive"):
        await harness.engine.goals(limit=0)
    with pytest.raises(ValueError, match=r"offset must be in"):
        await harness.engine.goals(offset=-1)


# --------------------------------------------------------------------------- #
# §12: the two acts on one goal                                               #
# --------------------------------------------------------------------------- #


async def test_withdrawing_frees_the_slot_and_leaves_the_pause() -> None:
    """§12: "Withdrawing removes the question and not the pause".

    "The attempt stays ``AWAITING_CLARIFICATION`` and the goal stays open; what the act
    buys is the freedom to ask again." It records no answer, revises no interpretation
    and engages no goal.
    """
    harness = Harness(planner=_Asking())
    paused = await harness.engine.converse(_ASKED, timeout=PATIENT)
    assert paused.turn is not None
    assert paused.clarification is not None
    before = await harness.plans.get_goal(paused.turn.goal.goal_id)
    assert before is not None

    answer = await harness.engine.withdraw_clarification(paused.clarification.question_id)

    assert answer is ClarificationWithdrawal.WITHDRAWN
    settled = await harness.plans.get_question(paused.clarification.question_id)
    assert settled is not None
    assert settled.disposition is GoalQuestionDisposition.WITHDRAWN
    assert (settled.text, settled.about) == (None, None)
    (attempt,) = await harness.plans.attempts_of(before.id)
    assert attempt.state is AttemptState.AWAITING_CLARIFICATION, "the pause is not lifted"
    after = await harness.plans.get_goal(before.id)
    assert after is not None
    assert after.version == before.version, "§12: it engages no goal and revises nothing"


async def test_withdrawing_twice_and_withdrawing_nothing_are_both_results() -> None:
    """§12: "An unknown id is ``NOTHING_TO_WITHDRAW`` and **never a raise**".

    Which is ``AssistantEngineContract::test_a_refusal_is_a_result_and_not_an_exception``
    binding at this seam.
    """
    harness = Harness(planner=_Asking())
    paused = await harness.engine.converse(_ASKED, timeout=PATIENT)
    assert paused.clarification is not None

    assert (
        await harness.engine.withdraw_clarification(paused.clarification.question_id)
    ) is ClarificationWithdrawal.WITHDRAWN
    assert (
        await harness.engine.withdraw_clarification(paused.clarification.question_id)
    ) is ClarificationWithdrawal.NOTHING_TO_WITHDRAW
    assert (
        await harness.engine.withdraw_clarification("no-such-question")
    ) is ClarificationWithdrawal.NOTHING_TO_WITHDRAW


async def test_abandoning_closes_the_goal_and_settles_its_question() -> None:
    """§12: ``abandon_goal`` is the only thing in this system that writes ``ABANDONED``.

    "Abandoning writes the goal's status through ``PlanStore.set_goal_status`` and
    settles its open question ``WITHDRAWN``, and does nothing else. It does **not** move
    the attempt's state, does not write an ``AttemptOutcome``, does not end an execution
    and does not cancel anything in flight."
    """
    harness = Harness(planner=_Asking())
    paused = await harness.engine.converse(_ASKED, timeout=PATIENT)
    assert paused.turn is not None
    assert paused.clarification is not None
    goal_id = paused.turn.goal.goal_id

    answer = await harness.engine.abandon_goal(goal_id)

    assert answer is GoalAbandonment.ABANDONED
    held = await harness.plans.get_goal(goal_id)
    assert held is not None
    assert held.status is GoalStatus.ABANDONED
    settled = await harness.plans.get_question(paused.clarification.question_id)
    assert settled is not None
    assert settled.disposition is GoalQuestionDisposition.WITHDRAWN
    (attempt,) = await harness.plans.attempts_of(goal_id)
    assert attempt.state is AttemptState.AWAITING_CLARIFICATION, "§12: the attempt is A9's"
    assert attempt.outcome is None


async def test_abandoning_twice_and_abandoning_nothing_are_both_results() -> None:
    """§12: the vocabulary's other two members, each a result and never a raise."""
    harness = Harness(planner=NoStepPlanner())
    opened = await harness.engine.converse(_ASKED, timeout=PATIENT)
    assert opened.turn is not None
    goal_id = opened.turn.goal.goal_id

    assert (await harness.engine.abandon_goal(goal_id)) is GoalAbandonment.ABANDONED
    assert (await harness.engine.abandon_goal(goal_id)) is GoalAbandonment.ALREADY_CLOSED
    assert (await harness.engine.abandon_goal("no-such-goal")) is GoalAbandonment.NO_SUCH_GOAL


async def test_an_abandoned_goal_leaves_the_open_set() -> None:
    """§12: "An abandoned goal leaves the open set, so nothing associates to it".

    It is still a **candidate** — §2 keeps a closed goal in the set "while the
    conversation that reaches it is retained" — and it is no longer the focused goal,
    which is what §1's open/closed split is for.
    """
    harness = Harness(
        planner=NoStepPlanner(), associator=_associating(AssociationVerdict.CONTINUES)
    )
    conversation = (await harness.conversations.begin(None)).id
    campsite = await _seed(
        harness.plans,
        _goal("goal-campsite", "book a campsite", conversation=conversation),
        engaged_in=conversation,
    )
    await harness.engine.abandon_goal(campsite.id)

    outcome = await harness.engine.converse(
        "carry on", timeout=PATIENT, conversation_id=conversation
    )

    assert outcome.goal_engagement is not None
    assert outcome.goal_engagement.disposition is EngagementDisposition.OPENED, (
        "§3: a CONTINUES over a conversation with no focused goal opens one instead"
    )
    assert outcome.turn is not None
    assert outcome.turn.goal.goal_id != campsite.id


# --------------------------------------------------------------------------- #
# §1: focus, and what does not move it                                        #
# --------------------------------------------------------------------------- #


async def test_an_undecided_turn_moves_no_engagement_and_no_candidate_read_does() -> None:
    """§20 arm 18's negative half: a candidate read and an undecided turn leave both.

    "Not a listing, not an export, not a retrieval, not a candidate-set read … and not a
    turn whose association came back ``UNDECIDED`` — a turn that asked **which** goal has
    engaged none of them, and stamping the candidates would reorder the very set the next
    turn's question is asked over."
    """
    harness = Harness(
        planner=NoStepPlanner(),
        associator=_associating(AssociationVerdict.UNDECIDED, "G1", "G2"),
    )
    conversation = (await harness.conversations.begin(None)).id
    for index, outcome in enumerate(("book a campsite", "book a flight")):
        await _seed(
            harness.plans,
            _goal(f"goal-{index}", outcome, conversation=conversation),
            engaged_in=conversation,
        )
    read = await harness.plans.candidates_for(conversation, limit=MAX_ASSOCIATION_CANDIDATES)
    before = {goal.id: goal.version for goal in read.goals}

    await harness.engine.converse("make it Sunday", timeout=PATIENT, conversation_id=conversation)
    await harness.engine.goals()

    again = await harness.plans.candidates_for(conversation, limit=MAX_ASSOCIATION_CANDIDATES)
    assert {goal.id: goal.version for goal in again.goals} == before


async def test_a_resumed_park_engages_the_goal_its_park_names() -> None:
    """§20 arm 18: §1's third act, "on the path that dispatches".

    Driven at the seam a park's id is answerable from — the goal id the park carries —
    because ADR-0249 §11 makes that id "an identifier and **not** a resolution guarantee"
    and this act is what reads it.
    """
    harness = Harness(planner=NoStepPlanner())
    conversation = (await harness.conversations.begin(None)).id
    campsite = await _seed(
        harness.plans, _goal("goal-campsite", "book a campsite", conversation=conversation)
    )

    await harness.engine._engage(campsite.id, conversation_id=conversation)

    held = await harness.plans.get_goal(campsite.id)
    assert held is not None
    assert held.last_engaged_at is not None
    assert held.last_engaged_in == conversation
    assert held.conversation_id == conversation, "§13: provenance is never rewritten"


async def test_an_engagement_of_a_goal_the_store_lost_is_not_a_fault() -> None:
    """ADR-0249 §11: "a resolution guarantee" is exactly what a park's goal id is not.

    "No lane repairs, back-fills or refuses such a park", so a resumption naming a goal
    no row holds engages nothing and raises nothing.
    """
    harness = Harness(planner=NoStepPlanner())
    conversation = (await harness.conversations.begin(None)).id

    await harness.engine._engage("no-such-goal", conversation_id=conversation)
    await harness.engine._engage(None, conversation_id=conversation)


# --------------------------------------------------------------------------- #
# §14: the elision, keyed on what the turn did                                #
# --------------------------------------------------------------------------- #


async def test_the_elision_reaches_composing_on_an_opened_turn_and_not_on_a_continued_one() -> None:
    """§20 arm 21: the disclosure is keyed on the disposition and never on the verdict.

    "The disclosure appears on an ``OPENED`` turn and on a turn carrying a
    ``disambiguation``, and **not** on a ``CONTINUED``, a ``RESUMED`` or a ``REOPENED``.
    The arm fails if the disclosure is keyed on the verdict."
    """
    model = FakeModelProvider()
    harness = Harness(
        planner=NoStepPlanner(),
        associator=_associating(AssociationVerdict.FRESH),
        composing=ComposingStage(model=model, streaming=FakeStreamingCompleter()),
    )
    conversation = (await harness.conversations.begin(None)).id
    for index in range(MAX_ASSOCIATION_CANDIDATES + 2):
        await _seed(
            harness.plans,
            _goal(f"goal-{index:02d}", f"objective {index}", conversation=conversation),
            engaged_in=conversation,
        )

    await harness.engine.converse("something new", timeout=PATIENT, conversation_id=conversation)

    (candidacy,) = harness.associator.calls
    assert len(candidacy.candidates) == MAX_ASSOCIATION_CANDIDATES, "§2: capped at the constant"
    assert candidacy.elided == 2, "and the true remainder, which a flag would discard"
    assert any(
        "older objectives" in message.content.lower() for message in model.calls[-1].messages
    ), "§14: an OPENED turn says older objectives were not considered"

    harness.associator.answer = harness.associator.answer.model_copy(
        update={"verdict": AssociationVerdict.CONTINUES}
    )

    await harness.engine.converse("carry on", timeout=PATIENT, conversation_id=conversation)

    assert not any(
        "older objectives" in message.content.lower() for message in model.calls[-1].messages
    ), "§14: a goal was found, so reciting what was not looked at would be noise"


# --------------------------------------------------------------------------- #
# §8, §11, §16: the brief, a crash window, and an early end                   #
# --------------------------------------------------------------------------- #


async def test_the_brief_carries_the_goals_open_question_and_nothing_more() -> None:
    """§8: ``GoalBrief.open_questions`` carries at most one text.

    "The goal's open question's ``text`` where one stands, and nothing where none does.
    It carries no id, no subject, no deadline and no disposition … it is there so that a
    planner does not raise a question the system is already asking."
    """
    planner = _Recording()
    harness = Harness(planner=planner)
    first = await harness.engine.converse(_ASKED, timeout=PATIENT)
    assert first.turn is not None
    assert first.clarification is not None

    await harness.engine.converse(
        "and Sunday", timeout=PATIENT, reference=TurnReference(goal_id=first.turn.goal.goal_id)
    )

    assert planner.briefs[0].open_questions == (), "the opening turn's goal held none"
    assert planner.briefs[-1].open_questions == ("Which campsite did you mean?",)


class _Recording(_Asking):
    """An asking planner that keeps every brief it was handed."""

    def __init__(self) -> None:
        super().__init__()
        self.briefs: list[GoalBrief] = []

    async def plan(self, goal: Any, **fields: Any) -> Any:
        """Record the brief, then plan as :class:`_Asking` does."""
        self.briefs.append(goal)
        return await super().plan(goal, **fields)


async def test_a_settled_question_is_not_reported_expired() -> None:
    """§20 arm 17: ``EXPIRED`` is read off the disposition and never off a clock.

    "A question answered an hour after it was asked and referenced a week later is
    ``ALREADY_SETTLED``, not ``EXPIRED``: it was answered, and a reply saying otherwise
    would tell the user their answer never arrived."
    """
    clock = _Advancing()
    planner = _Asking()
    harness = Harness(planner=planner, now=clock)
    paused = await harness.engine.converse(_ASKED, timeout=PATIENT)
    assert paused.clarification is not None
    question_id = paused.clarification.question_id
    planner.understanding = None
    clock.advance(timedelta(hours=1))
    answered = await harness.engine.converse(
        "the river one", timeout=PATIENT, reference=TurnReference(question_id=question_id)
    )
    assert answered.reference is ReferenceOutcome.ANSWERED
    clock.advance(timedelta(days=7))

    again = await harness.engine.converse(
        "still the river one", timeout=PATIENT, reference=TurnReference(question_id=question_id)
    )

    assert again.reference is ReferenceOutcome.ALREADY_SETTLED


async def test_a_turn_that_fails_before_its_persistence_site_writes_no_question() -> None:
    """§20 arm 34: a turn that ends early persists nothing new.

    "A turn whose planner raises, one rejected for capacity and one that fails before the
    planner is reached each leave **no question row** and no engagement stamp" — ADR-0228
    §5's clause asserted over this decision's record kinds as well.
    """
    harness = Harness(planner=_Raising())

    with pytest.raises(PlanningError):
        await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert await harness.plans.outstanding_questions() == ()
    assert (await harness.plans.export()).goals == (), "no goal row, so no stamp either"


class _Raising(NoStepPlanner):
    """A planner that fails the turn before it can reach its persistence site."""

    async def plan(self, goal: Any, **fields: Any) -> Any:
        """Raise, as a planner that cannot produce a plan does."""
        msg = "the fake planner declines"
        raise PlanningError(msg)


async def test_a_grounding_only_revision_is_recorded_and_announces_nothing() -> None:
    """§20 arm 16: the revision invariant over the one shape a reader would not read.

    "``revised`` ``True`` with all three empty **also** constructs, and is driven from a
    real planner return — a constraint restated with the **same text** and a
    ``USER_STATED`` ground where the previous revision held ``INFERRED``. That turn
    records the revision, and **announces nothing**."
    """
    planner = _Asking(
        ProposedUnderstanding(
            retains_outcome=True,
            constraints=(ProposedElement(text="under fifty pounds", ground=Ground.INFERRED),),
        )
    )
    harness = Harness(planner=planner)
    first = await harness.engine.converse("book a campsite under fifty pounds", timeout=PATIENT)
    assert first.turn is not None
    goal_id = first.turn.goal.goal_id
    planner.understanding = ProposedUnderstanding(
        retains_outcome=True,
        constraints=(
            ProposedElement(
                text="under fifty pounds", ground=Ground.USER_STATED, span="under fifty pounds"
            ),
        ),
    )

    second = await harness.engine.converse(
        "under fifty pounds",
        timeout=PATIENT,
        reference=TurnReference(goal_id=goal_id),
    )

    assert second.goal_engagement is not None
    assert second.goal_engagement.revised is True, "§5: a revision was recorded"
    assert second.goal_engagement.outcome_changed is False
    assert second.goal_engagement.added == ()
    assert second.goal_engagement.removed == (), (
        "§5: what moved is the record of who said it, which no reply states"
    )
