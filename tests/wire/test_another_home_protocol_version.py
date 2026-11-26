"""``PROTOCOL_VERSION`` moved for the refusals of a write across homes (ADR-0124 §9:2).

ADR-0383 §4:7 has the story store refuse a member, a merge or a move across homes and
the conversation store refuse a reply to a message of another home. Each refuses by its
own typed outcome (ADR-0289 §3:15; ``SendOutcome``), so each enumeration gains
``another_home``, and both cross the wire: a ``StoryOutcome``'s refusal and a
``MessageReceipt``. A peer at the earlier version cannot decode the new value, so a frame
carrying it is invalid for that peer, and the version moves in the change that adds it.
A test holds that the number moved, that the move is accounted for in the log a reviewer
reads, and that each value crosses the codec and is refused by a decoder that lacks it.
"""

from __future__ import annotations

import inspect
import json
from typing import Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    MessageReceipt,
    SendOutcome,
    StoryOutcome,
    StoryRefusal,
    StoryRefusalReason,
)
from ai_assistant.wire import envelope
from ai_assistant.wire.codec import encode_projection, project

#: The version this lane moves to, read at the moment it landed, and the one it moves
#: from. The absolute figure has one home, ``tests/core/test_engine_surface_closure.py``.
_MOVED_TO: Final = 141
_MOVED_FROM: Final = 140


def test_the_protocol_version_moved_past_the_figure_this_lane_reached() -> None:
    """ADR-0124 §9:2: the move, asserted as a move and not as a state."""
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_carries_an_entry_naming_both_enumerations_and_its_ground() -> None:
    """The entry names ADR-0383 §4:7, both enumerations and the value, and the one before stands."""
    source = inspect.getsource(envelope)
    entry = source.split(f"#: {_MOVED_TO}: ")[-1].split("PROTOCOL_VERSION: Final")[0]
    flat = " ".join(line.removeprefix("#:").strip() for line in entry.splitlines())

    assert "ADR-0383 §4:7" in flat
    assert "StoryRefusalReason" in flat
    assert "SendOutcome" in flat
    assert "another_home" in flat
    assert f"#: {_MOVED_FROM}: " in source, (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


def _refused() -> StoryOutcome:
    return StoryOutcome(
        refusal=StoryRefusal(reason=StoryRefusalReason.ANOTHER_HOME, story_id="story:y")
    )


def _receipt() -> MessageReceipt:
    return MessageReceipt(conversation_id="c-1", outcome=SendOutcome.ANOTHER_HOME)


@pytest.mark.parametrize("record", [_refused(), _receipt()], ids=["story", "message"])
def test_each_value_round_trips_through_the_codec(record: StoryOutcome | MessageReceipt) -> None:
    """The value crosses as its string, in the frame each store's answer travels in."""
    sent: dict[str, object] = json.loads(encode_projection(project(record)))

    assert type(record).model_validate(sent) == record
    assert "another_home" in json.dumps(sent)


def test_a_decoder_without_the_value_refuses_it() -> None:
    """What a peer at the earlier version meets: a value its enumeration does not hold."""
    sent = json.loads(encode_projection(project(_receipt())))
    sent["outcome"] = "not_a_value_of_this_version"

    with pytest.raises(ValidationError, match="outcome"):
        MessageReceipt.model_validate(sent)
