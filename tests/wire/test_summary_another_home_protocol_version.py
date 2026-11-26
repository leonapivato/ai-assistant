"""``PROTOCOL_VERSION`` moved for a summary's refusal of a name across homes (ADR-0124 §9:2).

ADR-0383 §4:7 has the story store refuse a summary version naming a story of another
home, by a ``like_another`` flag or a summary version read. It refuses by its own typed
outcome (ADR-0289 §3:15), so ``StorySummaryRefusalReason`` gains ``another_home``, and
it crosses the wire on the ``StorySummaryRefusal`` a ``StoryNoteOutcome`` carries. A peer
at the earlier version cannot decode the new value, so a frame carrying it is invalid for
that peer, and the version moves in the change that adds it. A test holds that the number
moved, that the move is accounted for in the log a reviewer reads, and that the value
crosses the codec and is refused by a decoder that lacks it.
"""

from __future__ import annotations

import inspect
import json
from typing import Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    StoryNoteOutcome,
    StorySummaryRefusal,
    StorySummaryRefusalReason,
)
from ai_assistant.wire import envelope
from ai_assistant.wire.codec import encode_projection, project

#: The version this lane moves to, read at the moment it landed, and the one it moves
#: from. The absolute figure has one home, ``tests/core/test_engine_surface_closure.py``.
_MOVED_TO: Final = 142
_MOVED_FROM: Final = 141


def test_the_protocol_version_moved_past_the_figure_this_lane_reached() -> None:
    """ADR-0124 §9:2: the move, asserted as a move and not as a state."""
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_carries_an_entry_naming_the_enumeration_and_its_ground() -> None:
    """The entry names ADR-0383 §4:7, the enumeration and the value; the one before stands."""
    source = inspect.getsource(envelope)
    entry = source.split(f"#: {_MOVED_TO}: ")[-1].split("PROTOCOL_VERSION: Final")[0]
    flat = " ".join(line.removeprefix("#:").strip() for line in entry.splitlines())

    assert "ADR-0383 §4:7" in flat
    assert "StorySummaryRefusalReason" in flat
    assert "another_home" in flat
    assert f"#: {_MOVED_FROM}: " in source, (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


def _refused() -> StoryNoteOutcome:
    return StoryNoteOutcome(
        refusal=StorySummaryRefusal(
            reason=StorySummaryRefusalReason.ANOTHER_HOME, story_id="story:y"
        )
    )


def test_the_value_round_trips_through_the_codec() -> None:
    """The value crosses as its string, in the frame the store's answer travels in."""
    record = _refused()
    sent: dict[str, object] = json.loads(encode_projection(project(record)))

    assert StoryNoteOutcome.model_validate(sent) == record
    assert "another_home" in json.dumps(sent)


def test_a_decoder_without_the_value_refuses_it() -> None:
    """What a peer at the earlier version meets: a value its enumeration does not hold."""
    sent = json.loads(encode_projection(project(_refused())))
    refusal = sent["refusal"]
    assert isinstance(refusal, dict)
    refusal["reason"] = "not_a_value_of_this_version"

    with pytest.raises(ValidationError, match="reason"):
        StoryNoteOutcome.model_validate(sent)
