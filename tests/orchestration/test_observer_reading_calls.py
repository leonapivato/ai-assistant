"""ADR-0356 §13:2-§13:3, §14:9: the observer reads a message call's message by its entry.

For an episode recorded after ADR-0356, a round's text is its notes and what people
received comes from message calls, each recorded as an entry holding what it delivered
(§7, §8:4). The observer reads that message as a :class:`MessageCallPart`, the words its
entry delivered, with the origin a round's message takes. For one recorded before, and
under ADR-0356's interim, a round's text is its message, read as a
:class:`RoundMessagePart`. A round's notes are no part (ADR-0329 §8:6), so they are
never read as its message.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from observer_support import (
    AT,
    LABELS,
    Harness,
    Minter,
    address,
    digest,
    episode,
    framed,
    framing,
    read_as,
    remember_call,
    remembered,
)

from ai_assistant.core.types import (
    CallOutcomeKind,
    ChannelIdentity,
    DeliveryStatus,
    EpisodicMemory,
    InputPart,
    LabelKind,
    MessageCallPart,
    ObservationFinding,
    PlanningLabel,
    PlanningRound,
    ProposedCall,
    RecordedCall,
    RecordedDelivery,
    RoundMessagePart,
    StatementPart,
    SupportHolder,
    SupportOrigin,
    stamped_support,
)
from ai_assistant.orchestration.observer.framing import FramingView
from ai_assistant.orchestration.observer.framing import framed as framed_by_code
from ai_assistant.orchestration.observer.reading import EpisodeReader, Reading
from ai_assistant.orchestration.observer.replies import FramingReplyShape

_CHAT = ChannelIdentity(channel_type="conversation", instance_id="chat-1")
_NOTES = "the 9:40 is cheapest; the user asked for mornings"
_SENT_AT = AT + timedelta(seconds=40)


async def _read(harness: Harness, leaving_id: str) -> Reading:
    leaving = await harness.memory.get(address(leaving_id))
    assert isinstance(leaving, EpisodicMemory)
    reader = EpisodeReader(memory=harness.memory, plans=harness.plans, stories=harness.stories)
    return await reader.read(leaving)


def _text_call(call_id: str, words: str = "x") -> ProposedCall:
    return ProposedCall(call_id=call_id, name="text", arguments={"words": words})


def _round(text: str = "", *calls: ProposedCall, notes: str | None = _NOTES) -> PlanningRound:
    return PlanningRound(id="r1", recorded_at=AT, text=text, notes=notes, calls=calls)


def _entry(call_id: str, words: str | None, **fields: Any) -> RecordedCall:
    values: dict[str, Any] = {
        "round": "r1",
        "call_id": call_id,
        "capability": "text",
        "effect": True,
        "outcome": CallOutcomeKind.DONE,
        "delivered": None
        if words is None
        else RecordedDelivery(words=words, went=_CHAT, status=DeliveryStatus.SENT),
        "recorded_at": _SENT_AT,
    }
    values.update(fields)
    return RecordedCall.model_validate(values)


async def test_after_the_decision_a_message_is_its_calls_delivered_words() -> None:
    """§14:9: the message from its entry; the round's notes are never read as one."""
    harness = Harness()
    await harness.hold(
        episode(
            "one",
            text="Book me the cheapest morning flight.",
            rounds=(_round("", _text_call("c1"), ProposedCall(call_id="c2", name="web_search")),),
            call_records=(
                _entry("c2", None, capability="web_search", effect=False),
                _entry("c1", "Booked the 9:40 to Lisbon."),
            ),
        )
    )

    reading = await _read(harness, "one")

    given, message = reading.leaving.parts
    assert given.part == InputPart(episode=address("one"))
    assert message.part == MessageCallPart(episode=address("one"), round="r1", call_id="c1")
    assert message.text == "Booked the 9:40 to Lisbon."
    assert (message.origin, message.when) == (SupportOrigin.ASSISTANT_MESSAGE, _SENT_AT)
    assert all(_NOTES not in part.text for part in reading.leaving.parts)


async def test_before_the_decision_a_message_is_its_rounds_text() -> None:
    """§8:1, §14:9: a round recorded before keeps its text as the message it wrote."""
    harness = Harness()
    await harness.hold(episode("one", rounds=(_round("Noted, window seats."),)))

    reading = await _read(harness, "one")

    _, message = reading.leaving.parts
    assert message.part == RoundMessagePart(episode=address("one"), round="r1")
    assert (message.text, message.origin, message.when) == (
        "Noted, window seats.",
        SupportOrigin.ASSISTANT_MESSAGE,
        AT,
    )
    assert all(_NOTES not in part.text for part in reading.leaving.parts)


async def test_a_rounds_own_message_comes_before_its_calls_in_the_rounds_order() -> None:
    """Under the interim a round writes its own message, then each message call in the
    order it proposed them, whatever order their entries were appended in."""
    harness = Harness()
    await harness.hold(
        episode(
            "one",
            rounds=(_round("Here are three options.", _text_call("c1"), _text_call("c2")),),
            call_records=(_entry("c2", "And a fourth."), _entry("c1", "Booked the 9:40.")),
        )
    )

    reading = await _read(harness, "one")

    assert [part.part for part in reading.leaving.parts[1:]] == [
        RoundMessagePart(episode=address("one"), round="r1"),
        MessageCallPart(episode=address("one"), round="r1", call_id="c1"),
        MessageCallPart(episode=address("one"), round="r1", call_id="c2"),
    ]
    assert [part.text for part in reading.leaving.parts[1:]] == [
        "Here are three options.",
        "Booked the 9:40.",
        "And a fourth.",
    ]


async def test_a_message_call_that_sent_nothing_is_no_part() -> None:
    """§13:2: a call refused, or come back before anything was sent, holds no delivery."""
    harness = Harness()
    refused = _entry("c1", None, outcome=CallOutcomeKind.REFUSED, reason="never shown that place")
    await harness.hold(
        episode("one", rounds=(_round("", _text_call("c1")),), call_records=(refused,))
    )

    reading = await _read(harness, "one")

    (given,) = reading.leaving.parts
    assert isinstance(given.part, InputPart)


async def test_a_message_call_is_outside_where_the_activation_read_outside_content() -> None:
    """§13:2, ADR-0328 §4:3: it takes the origin a round's message takes, by the same fact."""
    harness = Harness()
    await harness.hold(
        episode(
            "one",
            rounds=(_round("", _text_call("c1")),),
            digests=(digest("The lower loop closes on the 15th.", at=AT),),
            call_records=(_entry("c1", "It closes on the 15th."),),
        )
    )

    reading = await _read(harness, "one")

    (message,) = [one for one in reading.leaving.parts if isinstance(one.part, MessageCallPart)]
    assert message.origin is SupportOrigin.ASSISTANT_MESSAGE_OVER_OUTSIDE


async def test_a_candidate_resting_on_an_earlier_message_call_names_its_part() -> None:
    """§13:3, ADR-0329 §9:6: an earlier exchange's assistant's message is its message call's."""
    harness = Harness()
    past = address("past")
    values = {
        "fact": "The user flies to Lisbon on Thursday.",
        "why": "travel",
        "rests_on_assistant_messages": [past],
    }
    call = remember_call(fact=values["fact"], why="travel", rests_on_assistant_messages=["E1"])
    await harness.hold(
        episode(
            "past",
            at=AT - timedelta(days=1),
            rounds=(_round("", _text_call("c1")),),
            call_records=(_entry("c1", "Booked the Thursday 9:40 to Lisbon."),),
        ),
        episode(
            "one",
            at=AT - timedelta(minutes=3),
            rounds=(PlanningRound(id="r1", recorded_at=AT, calls=(call,)),),
            labels=(PlanningLabel(label="E1", kind=LabelKind.EPISODE, id=past),),
        ),
    )
    await remembered(harness.plans, "one", "r1", values)

    reading = await _read(harness, "one")

    (hint,) = reading.hints
    (earlier,) = reading.earlier
    (sent,) = [one for one in earlier.parts if isinstance(one.part, MessageCallPart)]
    assert sent.text == "Booked the Thursday 9:40 to Lisbon."
    assert hint.rests_on == (sent.handle,)


@pytest.mark.parametrize(
    ("recorded", "cited"),
    [
        pytest.param(
            {
                "rounds": (_round("", _text_call("c1")),),
                "call_records": (_entry("c1", "Booked the Thursday 9:40 to Lisbon."),),
            },
            MessageCallPart(episode=address("one"), round="r1", call_id="c1"),
            id="after",
        ),
        pytest.param(
            {"rounds": (_round("Booked the Thursday 9:40 to Lisbon."),)},
            RoundMessagePart(episode=address("one"), round="r1"),
            id="before",
        ),
    ],
)
async def test_the_observer_cites_a_message_by_the_part_that_wrote_it(
    recorded: dict[str, Any], cited: MessageCallPart | RoundMessagePart
) -> None:
    """§14:9: after the decision by ``MessageCallPart``, before by ``RoundMessagePart``,
    each the assistant's statement of a round's message (§13:3, ADR-0345 §8:3)."""
    harness = Harness()
    await harness.hold(episode("one", text="Book the Thursday flight.", **recorded))
    reading = await _read(harness, "one")
    leaving = reading.leaving.record
    assert leaving is not None
    (message,) = [one for one in reading.leaving.parts if one.part == cited]

    view = FramingView(
        finding=ObservationFinding(
            id="f1",
            episode=leaving.id,
            claim="The user flies to Lisbon on Thursday.",
            rests_on=(message.part,),
        ),
        leaving=leaving,
        parts=(message,),
    )
    reply = read_as(
        framing(
            framed(
                "The assistant said it booked the Thursday 9:40 to Lisbon.",
                message.handle,
                marks=("assistant_statement", "occasion"),
            )
        ),
        FramingReplyShape,
    )
    assert reply is not None
    result = framed_by_code(reply, view, now=AT, mint=Minter(), labels=LABELS)

    (written,) = (one.memory for one in result.memories)
    (support,) = (stamped_support(one, leaving) for one in written.supports)
    assert support.points_at == cited
    assert (support.origin, support.holder) == (
        SupportOrigin.ASSISTANT_MESSAGE,
        SupportHolder.statement(StatementPart.ROUND_MESSAGE),
    )
