"""ADR-0356 §14:9: the matters pass and the tidy-up, over an episode before and after it.

Both read an episode through ``core``'s one projection with owner-only records withheld
(ADR-0312 §4:3), and show the assistant's reply as the episode records it, its
``outcome``: the words each message call delivered, as its entry holds them, after the
decision (§8:9), and the messages its rounds' text wrote before. A round's notes are
placed for the owner alone (ADR-0307 §4:4), so neither shows them, and neither reads
them as the message.
"""

from __future__ import annotations

import json
from typing import Any, Final

import pytest
from story_support import AT, episode, memory_of
from test_matters_pass import _pass, _raise
from test_matters_pass import _shown as _shown_to_the_pass
from test_matters_pass import _stories as _pass_stories
from test_matters_pass import _story as _pass_story
from test_story_tidy_up import _note, _reply, _shown, _stories, _story, _tidy_up

from ai_assistant.core.types import (
    CallOutcomeKind,
    ChannelIdentity,
    DeliveryStatus,
    EpisodeProcessingRecord,
    EpisodicMemory,
    PlanningRound,
    ProposedCall,
    RecordedCall,
    RecordedDelivery,
    StoryFlag,
    StoryFlagKind,
)
from ai_assistant.testing import FakeModelProvider

_NOTES: Final = "Riverside had two pitches left; the user wants the quieter one"
_SENT: Final = "I booked pitch 4 at Riverside for the 18th."
_SAID: Final = "Riverside has pitch 4 free on the 18th."
_CHAT: Final = ChannelIdentity(channel_type="conversation", instance_id="c-1")


def _after(activation_id: str) -> EpisodicMemory:
    """An episode recorded after the decision: notes, no text, a message call's entry."""
    planned = PlanningRound(
        id="r1",
        recorded_at=AT,
        notes=_NOTES,
        calls=(ProposedCall(call_id="c1", name="text", arguments={"words": _SENT}),),
    )
    entry = RecordedCall(
        round="r1",
        call_id="c1",
        capability="text",
        effect=True,
        outcome=CallOutcomeKind.DONE,
        delivered=RecordedDelivery(words=_SENT, went=_CHAT, status=DeliveryStatus.SENT),
        recorded_at=AT,
    )
    return _with(episode(activation_id), rounds=(planned,), call_records=(entry,), outcome=_SENT)


def _before(activation_id: str) -> EpisodicMemory:
    """An episode recorded before the decision: its round's text is the message it wrote."""
    planned = PlanningRound(id="r1", recorded_at=AT, text=_SAID, notes=_NOTES)
    return _with(episode(activation_id), rounds=(planned,), outcome=_SAID)


def _with(record: EpisodicMemory, *, outcome: str, **fields: Any) -> EpisodicMemory:
    processing = record.processing_record
    assert processing is not None
    rebuilt = EpisodeProcessingRecord.model_validate({**dict(processing), **fields})
    return record.model_copy(update={"processing_record": rebuilt, "outcome": outcome})


_SHAPES: Final = [
    pytest.param(_after, _SENT, id="after"),
    pytest.param(_before, _SAID, id="before"),
]


@pytest.mark.parametrize(("recorded", "reply"), _SHAPES)
async def test_the_tidy_up_shows_the_message_and_never_the_notes(recorded: Any, reply: str) -> None:
    stories = _stories()
    memory = await memory_of(recorded("a-1"))
    trip = await _story(stories, "a-1")
    await _note(stories, trip, "Camping at Riverside in mid-October.")
    model = FakeModelProvider(_reply(["A camping trip."]))

    await _tidy_up(model, stories, memory).run(trip)

    shown = _shown(model)
    (rendered,) = shown["episodes"]
    assert rendered["assistants_reply"] == reply
    assert _NOTES not in json.dumps(shown)


@pytest.mark.parametrize(("recorded", "reply"), _SHAPES)
async def test_the_matters_pass_shows_the_message_and_never_the_notes(
    recorded: Any, reply: str
) -> None:
    stories = _pass_stories()
    memory = await memory_of(recorded("a-1"), episode("a-2", text="Book the dentist."))
    trip = await _pass_story(stories, "a-1", "a-2")
    await _raise(stories, trip, StoryFlag(kind=StoryFlagKind.TWO_MATTERS))
    model = FakeModelProvider(json.dumps({"decision": "leave"}))

    await _pass(model, stories, memory).run()

    shown = _shown_to_the_pass(model)
    first, _ = shown["episodes"]
    assert first["assistants_reply"] == reply
    assert _NOTES not in json.dumps(shown)
