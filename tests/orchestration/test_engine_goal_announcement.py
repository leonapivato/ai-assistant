"""ADR-0250 §5's announcement, read off the reply the user is actually shown.

``tests/orchestration/test_engine_goal_association.py`` pins the **typed value** §5's
rule is stated over — which disposition owes a sentence, and what ``added`` and
``removed`` hold. What it could not see, and what issue #2332 found on production, is
that the sentence the typed value is owed had **no producer**: ``orchestration`` never
put it in the reply, and both surfaces render none of ``GoalEngagement``'s five
members on the stated ground that the reply already carries it.

So every case here reads ``outcome.reply``, whole and byte for byte. A producer that
announced the outcome alone where something moved, that summarised either tuple, that
counted instead of quoting, or that announced a grounding-only revision fails an
assertion here rather than passing a weaker one — which is what §5's *"real safeguard
against a wrong association"* has to be tested as.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from test_engine import PATIENT, Harness, NoStepPlanner
from test_engine_goal_association import _Asking, _associating, _goal, _seed

from ai_assistant.core.types import (
    AssociationVerdict,
    EngagementDisposition,
    Ground,
    ProposedElement,
    ProposedUnderstanding,
    ReplyChunk,
    TurnOutcome,
    TurnReference,
)
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.goals import announcement_of
from ai_assistant.testing import FakeModelProvider, FakeStreamingCompleter, StreamAttempt

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

#: What the canonical fake model answers with, so a case can say exactly how much of
#: the reply is the model's and how much is §5's.
_COMPOSED: Final = "fake model reply"

#: The goal every case here engages, worded as a user states one.
_OUTCOME: Final = "book a campsite"

#: The lead §5's sentence takes on the revision limb alone, spelled once so a case
#: reads as the reply it asserts rather than as a format string.
_REVISED: Final = "I have changed what I understand you are asking for"


def _reply(announcement: str) -> str:
    """The whole reply §5 owes beside :data:`_COMPOSED`.

    The sentence first and a blank line between, which is where this lane places it:
    §5's *"the user sees what the assistant now thinks they asked for, on the turn it
    changed"* is met before the answer written under that understanding, not after it.

    Args:
        announcement: The sentence §5 owes.

    Returns:
        The reply the turn carries.
    """
    return f"{announcement}\n\n{_COMPOSED}"


def _constraints(*texts: str) -> ProposedUnderstanding:
    """An understanding retaining the outcome and proposing exactly ``texts``.

    Args:
        texts: The constraint texts, in the order the planner states them.

    Returns:
        The envelope a scripted planner returns.
    """
    return ProposedUnderstanding(
        retains_outcome=True,
        constraints=tuple(ProposedElement(text=text, ground=Ground.INFERRED) for text in texts),
    )


def _harness(
    planner: object,
    *,
    streaming: StreamAttempt | None = None,
    model: FakeModelProvider | None = None,
) -> Harness:
    """A harness whose association continues the conversation's focused goal.

    Args:
        planner: The scripted planner every turn of the case runs.
        streaming: The one attempt a streamed case's seam scripts, or ``None``.
        model: The provider behind the composing stage, where a case reads back what
            was sent to it. A fresh one by default.

    Returns:
        The wired harness.
    """
    return Harness(
        planner=planner,
        associator=_associating(AssociationVerdict.CONTINUES),
        composing=ComposingStage(
            model=FakeModelProvider() if model is None else model,
            streaming=FakeStreamingCompleter(script=() if streaming is None else (streaming,)),
        ),
    )


async def _continuing(
    planner: object,
    *,
    streaming: StreamAttempt | None = None,
    model: FakeModelProvider | None = None,
) -> tuple[Harness, str, str]:
    """A harness holding one stored campsite goal the next turn continues.

    Args:
        planner: The scripted planner every turn of the case runs.
        streaming: The one attempt a streamed case's seam scripts, or ``None``.
        model: The provider behind the composing stage, or ``None`` for a fresh one.

    Returns:
        The harness, the conversation the goal was engaged in, and the goal's id.
    """
    harness = _harness(planner, streaming=streaming, model=model)
    conversation = (await harness.conversations.begin(None)).id
    goal = await _seed(
        harness.plans,
        _goal("goal-campsite", _OUTCOME, conversation=conversation),
        engaged_in=conversation,
    )
    return harness, conversation, goal.id


async def _drain(stream: AsyncIterator[ReplyChunk | TurnOutcome]) -> tuple[list[str], TurnOutcome]:
    """Read one streamed turn whole, returning its chunk texts and its outcome.

    Args:
        stream: What ``converse_streaming`` returned.

    Returns:
        The chunk texts in the order they were written, and the terminal outcome.
    """
    chunks: list[str] = []
    outcome: TurnOutcome | None = None
    async for value in stream:
        if isinstance(value, TurnOutcome):
            outcome = value
        else:
            chunks.append(value.text)
    assert outcome is not None, "ADR-0173 §4: the outcome is always the last value"
    return chunks, outcome


# --------------------------------------------------------------------------- #
# §5's silence limb: a turn that moved no word says nothing about goals        #
# --------------------------------------------------------------------------- #


async def test_an_opened_turn_that_moved_no_word_announces_nothing() -> None:
    """§5: ``OPENED`` with ``revised`` ``False`` puts no sentence in the reply.

    *"A turn whose disposition is ``OPENED`` or ``CONTINUED`` and which moved no word
    says nothing about goals at all: an ordinary topic change and an ordinary
    continuation each need neither an announcement nor a confirmation."*
    """
    harness = Harness(planner=NoStepPlanner())

    opened = await harness.engine.converse("what is two plus two?", timeout=PATIENT)

    assert opened.goal_engagement is not None
    assert opened.goal_engagement.disposition is EngagementDisposition.OPENED
    assert opened.goal_engagement.revised is False
    assert opened.reply == _COMPOSED, "the model's answer alone, and nothing prepended"


async def test_a_continued_turn_that_moved_no_word_announces_nothing() -> None:
    """§5's other silent limb, and the reason it is silent.

    *"A user adding a constraint to the thing they have been discussing for six turns
    does not need to be told which goal it is; told every time, the sentence stops
    being read, which is the failure that makes the ``RESUMED`` case worth
    announcing."*
    """
    harness, conversation, _ = await _continuing(_Asking(None))

    plain = await harness.engine.converse("carry on", timeout=PATIENT, conversation_id=conversation)

    assert plain.goal_engagement is not None
    assert plain.goal_engagement.disposition is EngagementDisposition.CONTINUED
    assert plain.goal_engagement.revised is False
    assert plain.reply == _COMPOSED


async def test_a_grounding_only_revision_is_recorded_and_not_announced() -> None:
    """§5, and §20 arm 16's last clause read off the reply rather than the value.

    *"Where ``revised`` is ``True`` and ``outcome_changed``, ``added`` and ``removed``
    are all empty, the understanding a reader would read is unchanged — what moved is
    the record of **who said it** … A sentence there would announce a change the user
    cannot see."* The arm *"fails … if a sentence is composed for it"*.
    """
    planner = _Asking(_constraints("under fifty pounds"))
    harness, conversation, _ = await _continuing(planner)
    await harness.engine.converse(
        "and under fifty pounds", timeout=PATIENT, conversation_id=conversation
    )

    planner.understanding = ProposedUnderstanding(
        retains_outcome=True,
        constraints=(
            ProposedElement(
                text="under fifty pounds", ground=Ground.USER_STATED, span="under fifty pounds"
            ),
        ),
    )
    grounded = await harness.engine.converse(
        "under fifty pounds", timeout=PATIENT, conversation_id=conversation
    )

    assert grounded.goal_engagement is not None
    assert grounded.goal_engagement.revised is True, "the revision is recorded"
    assert (
        grounded.goal_engagement.outcome_changed,
        grounded.goal_engagement.added,
        grounded.goal_engagement.removed,
    ) == (False, (), ())
    assert grounded.reply == _COMPOSED, "§5: recorded, and not announced"


# --------------------------------------------------------------------------- #
# §5's engagement limb: RESUMED and REOPENED, the goal named once              #
# --------------------------------------------------------------------------- #


async def test_a_resumption_names_the_goal_once_in_the_reply() -> None:
    """§5's first limb and §14's first place, read off the reply.

    §14: *"A paused goal is mentioned in exactly two places and in no other: 1. the
    reply of the turn that **associated to it** — which is §5's announcement, owed
    because the disposition is ``RESUMED`` or ``REOPENED``."* Once, so the statement
    appears exactly one time in the whole reply.
    """
    harness, _, goal_id = await _continuing(_Asking(None))
    second = (await harness.conversations.begin(None)).id

    resumed = await harness.engine.converse(
        "carry on with that",
        timeout=PATIENT,
        conversation_id=second,
        reference=TurnReference(goal_id=goal_id),
    )

    assert resumed.goal_engagement is not None
    assert resumed.goal_engagement.disposition is EngagementDisposition.RESUMED
    assert resumed.reply == _reply('Picking up what you asked for earlier: "book a campsite".')
    assert resumed.reply.count(_OUTCOME) == 1, "§14: named once"


async def test_a_reopening_says_the_goal_had_been_finished_with() -> None:
    """§5's first limb over ``REOPENED``, which §12 reaches through ``abandon_goal``."""
    harness, _, goal_id = await _continuing(_Asking(None))
    second = (await harness.conversations.begin(None)).id
    await harness.engine.abandon_goal(goal_id)

    reopened = await harness.engine.converse(
        "back to that one",
        timeout=PATIENT,
        conversation_id=second,
        reference=TurnReference(goal_id=goal_id),
    )

    assert reopened.goal_engagement is not None
    assert reopened.goal_engagement.disposition is EngagementDisposition.REOPENED
    assert reopened.reply == _reply(
        'Going back to something you had finished with: "book a campsite".'
    )


# --------------------------------------------------------------------------- #
# §5's revision limb: what actually moved, stated and never summarised         #
# --------------------------------------------------------------------------- #


async def test_a_turn_that_adds_two_constraints_states_both_of_them() -> None:
    """The drive that found #2332, composed rather than paraphrased.

    On production ``added=('keep it under 150 euros', 'buy from a European supplier')``
    reached the user as the model's own *"Understood, Leonardo — under €150 and from a
    European supplier"* — *"which is a model's wording, is not composed by
    ``orchestration``, and does not state the goal's ``outcome``"*. §5 owes both texts
    and the outcome, in the tuple order it states.
    """
    planner = _Asking(_constraints("keep it under 150 euros", "buy from a European supplier"))
    harness, conversation, _ = await _continuing(planner)

    revised = await harness.engine.converse(
        "keep it under 150 euros and buy from a European supplier",
        timeout=PATIENT,
        conversation_id=conversation,
    )

    assert revised.goal_engagement is not None
    assert revised.goal_engagement.added == (
        "keep it under 150 euros",
        "buy from a European supplier",
    )
    assert revised.reply == _reply(
        f'{_REVISED}: "book a campsite". I have added "keep it under 150 euros" '
        'and "buy from a European supplier".'
    )


async def test_a_replaced_element_states_the_new_text_and_the_old_one() -> None:
    """§20 arm 12's first load-bearing case, read off the reply.

    *"an element **replaced** (the date becomes Monday) puts the new text in ``added``
    and the old in ``removed``"*, and §5 obliges the sentence to state **both** —
    *"never merely that something changed, and never the outcome alone where either
    tuple is non-empty"*.
    """
    planner = _Asking(_constraints("under fifty pounds"))
    harness, conversation, _ = await _continuing(planner)
    await harness.engine.converse(
        "and under fifty pounds", timeout=PATIENT, conversation_id=conversation
    )

    planner.understanding = _constraints("under forty pounds")
    replaced = await harness.engine.converse(
        "make it forty", timeout=PATIENT, conversation_id=conversation
    )

    assert replaced.reply == _reply(
        f'{_REVISED}: "book a campsite". I have added "under forty pounds". '
        'I am no longer holding "under fifty pounds".'
    )


async def test_an_element_dropped_by_omission_is_stated_as_no_longer_held() -> None:
    """§5's removal clause, which is the whole reason ``removed`` exists.

    *"a revision whose only effect is to drop the user's stated budget is a revision
    whose only trace is an absence. ``removed`` is that trace, and a turn that dropped
    an element and said nothing would be the silent rewrite §3 and §5 exist to
    forbid."*
    """
    planner = _Asking(_constraints("under fifty pounds"))
    harness, conversation, _ = await _continuing(planner)
    await harness.engine.converse(
        "and under fifty pounds", timeout=PATIENT, conversation_id=conversation
    )

    planner.understanding = ProposedUnderstanding(retains_outcome=True)
    omitted = await harness.engine.converse(
        "forget the budget", timeout=PATIENT, conversation_id=conversation
    )

    assert omitted.goal_engagement is not None
    assert omitted.goal_engagement.added == ()
    assert omitted.reply == _reply(
        f'{_REVISED}: "book a campsite". I am no longer holding "under fifty pounds".'
    )


async def test_a_changed_outcome_is_announced_as_the_outcome_this_turn_recorded() -> None:
    """§5: the sentence *"states the goal's ``outcome`` as this turn recorded it"*.

    The limb where ``outcome_changed`` alone says something moved: both tuples are
    empty, so the outcome is the whole of what the sentence has to state, and the
    clause forbidding *"the outcome alone"* does not reach it — that clause is
    conditioned on *"where either tuple is non-empty"*.
    """
    planner = _Asking(
        ProposedUnderstanding(
            retains_outcome=False,
            outcome="book a campsite by the sea",
            outcome_ground=Ground.USER_STATED,
            outcome_span="by the sea",
        )
    )
    harness, conversation, _ = await _continuing(planner)

    restated = await harness.engine.converse(
        "by the sea, actually", timeout=PATIENT, conversation_id=conversation
    )

    assert restated.goal_engagement is not None
    assert restated.goal_engagement.outcome_changed is True
    assert (restated.goal_engagement.added, restated.goal_engagement.removed) == ((), ())
    assert restated.reply == _reply(f'{_REVISED}: "book a campsite by the sea".')


async def test_a_resumption_that_also_revised_states_both_facts_in_one_sentence() -> None:
    """Both of §5's limbs on one turn, with the goal still named once.

    §5's rule is a disjunction, so a turn can satisfy it twice over: the disposition
    is ``RESUMED`` **and** a word moved. The announcement then has to carry the
    resumption and what moved without stating the goal a second time (§14).
    """
    planner = _Asking(None)
    harness, _, goal_id = await _continuing(planner)
    second = (await harness.conversations.begin(None)).id
    planner.understanding = _constraints("under fifty pounds")

    resumed = await harness.engine.converse(
        "carry on, and under fifty pounds",
        timeout=PATIENT,
        conversation_id=second,
        reference=TurnReference(goal_id=goal_id),
    )

    assert resumed.goal_engagement is not None
    assert resumed.goal_engagement.disposition is EngagementDisposition.RESUMED
    assert resumed.goal_engagement.added == ("under fifty pounds",)
    assert resumed.reply == _reply(
        "Picking up what you asked for earlier, and I have changed what I understand "
        'it to be: "book a campsite". I have added "under fifty pounds".'
    )
    assert resumed.reply.count(_OUTCOME) == 1, "§14: still named once"


# --------------------------------------------------------------------------- #
# The streamed turn: ADR-0173 §3's join property holds over the sentence       #
# --------------------------------------------------------------------------- #


async def test_a_streamed_turn_publishes_the_sentence_first_and_still_joins() -> None:
    """ADR-0173 §3 beside ADR-0250 §5: the sentence is a chunk, and the reply joins.

    *"Where the exchange streamed chunks, ``reply`` is the text those chunks conveyed,
    joined in the order they were written."* A sentence prepended only to the terminal
    ``reply`` would break that for every streaming client; one published as its own
    opening chunk keeps it, and keeps each frame measured on its own (§11).
    """
    harness, conversation, _ = await _continuing(
        _Asking(_constraints("under fifty pounds")),
        streaming=StreamAttempt(deltas=("You prefer", " ", "hiking.")),
    )

    chunks, outcome = await _drain(
        harness.engine.converse_streaming(
            "and under fifty pounds", timeout=PATIENT, conversation_id=conversation
        )
    )

    announcement = f'{_REVISED}: "book a campsite". I have added "under fifty pounds".'
    assert chunks[0] == f"{announcement}\n\n", "its own chunk, published first"
    assert outcome.reply == "".join(chunks), "ADR-0173 §3: the reply is the join"
    assert outcome.reply == f"{announcement}\n\nYou prefer hiking."
    assert outcome.reply_degraded is False


async def test_a_stream_that_published_nothing_carries_no_announcement() -> None:
    """§5 places the sentence *"in a reply the turn was composing anyway"*.

    A composition that failed before its first chunk is ADR-0173 §6's pre-commit
    shape — ``reply`` ``None``, ``reply_degraded`` ``True``. Publishing the sentence
    there would leave a terminal ``reply`` the chunks do not join to, and would turn
    ADR-0170 §4's *"composing it produced none"* shape into an answer. The engagement
    still crosses the wire on its own member, so nothing about what the turn did is
    lost.
    """
    harness, conversation, _ = await _continuing(
        _Asking(_constraints("under fifty pounds")),
        streaming=StreamAttempt(deltas=(), fails=True),
    )

    chunks, outcome = await _drain(
        harness.engine.converse_streaming(
            "and under fifty pounds", timeout=PATIENT, conversation_id=conversation
        )
    )

    assert chunks == []
    assert outcome.reply is None
    assert outcome.reply_degraded is True
    assert outcome.goal_engagement is not None
    assert outcome.goal_engagement.added == ("under fifty pounds",)


# --------------------------------------------------------------------------- #
# §16: every word but the statements is this module's                          #
# --------------------------------------------------------------------------- #


async def test_the_sentence_reaches_no_prompt_the_model_was_given() -> None:
    """§16: *"no model composes the sentence"*, asserted over what the model was sent.

    §10's and §14's two facts reach the composing stage as **clauses** the model says
    in its own register. This one does not reach it at all: it is composed after the
    stage has finished and placed in the reply by ``orchestration``. So no message of
    any call carries a byte of it, which is what makes the sentence unable to disagree
    with the member beside it.
    """
    planner = _Asking(_constraints("under fifty pounds"))
    model = FakeModelProvider()
    harness, conversation, _ = await _continuing(planner, model=model)

    revised = await harness.engine.converse(
        "and under fifty pounds", timeout=PATIENT, conversation_id=conversation
    )

    assert revised.goal_engagement is not None
    announcement = announcement_of(revised.goal_engagement)
    assert announcement is not None
    sent = [message.content for call in model.calls for message in call.messages]
    assert sent, "the turn did call the model"
    assert not any(_REVISED in content for content in sent)
    assert not any(announcement in content for content in sent)
