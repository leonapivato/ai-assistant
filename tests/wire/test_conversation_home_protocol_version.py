"""``PROTOCOL_VERSION`` moved for the home on each transcript message (ADR-0124 §9:2).

ADR-0386 §4:2 puts ADR-0383 §2's home on every transcript entry, and a
``TranscriptMessage`` crosses the wire: on every transcript page, every change that adds
a message, and every snapshot a device is given. ADR-0386 §1:3 leaves the version to
ADR-0124 §9:2, which advances it in the change that makes a frame one peer sends invalid
for the other. A test holds that the number moved and that the move is accounted for in
the log a reviewer reads, as the earlier moves' tests do; the cases below send a message,
a page and a change through the codec's own projection and read each back, and hold that
a message sent without a home, as a peer at the earlier version sends it, is refused.
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from typing import Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    ChatChanges,
    MessageAddedChange,
    MessageAuthor,
    RecordHome,
    TranscriptMessage,
    TranscriptPage,
)
from ai_assistant.wire import envelope
from ai_assistant.wire.codec import encode_projection, project

#: The version this lane moves to, read at the moment it landed, and the one it moves
#: from. The absolute figure has one home, ``tests/core/test_engine_surface_closure.py``.
_MOVED_TO: Final = 139
_MOVED_FROM: Final = 138

_AT: Final = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


def test_the_protocol_version_moved_past_the_figure_this_lane_reached() -> None:
    """ADR-0124 §9:2: the move, asserted as a move and not as a state."""
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_carries_an_entry_naming_this_decision_and_its_ground() -> None:
    """The entry names ADR-0386, the home and the message type, and the one before stands."""
    source = inspect.getsource(envelope)
    entry = source.split(f"#: {_MOVED_TO}: ")[-1].split("PROTOCOL_VERSION: Final")[0]
    flat = " ".join(line.removeprefix("#:").strip() for line in entry.splitlines())

    assert "ADR-0386" in flat
    assert "home" in flat
    assert "TranscriptMessage" in flat
    assert f"#: {_MOVED_FROM}: " in source, (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


def _message(home: RecordHome) -> TranscriptMessage:
    return TranscriptMessage(
        conversation_id="c-1",
        position=1,
        written_at=_AT,
        author=MessageAuthor.ASSISTANT,
        text="Booked the morning.",
        home=home,
    )


@pytest.mark.parametrize(
    "home", [RecordHome.owners(), RecordHome.shared()], ids=["owners", "shared"]
)
def test_a_messages_home_round_trips_through_the_codec(home: RecordHome) -> None:
    """ADR-0383 §2:2: the kind and the identifier both cross, in every frame that carries it."""
    message = _message(home)
    page = TranscriptPage(conversation_id="c-1", entries=(message,), as_of=1)
    changes = ChatChanges(changes=(MessageAddedChange(seq=1, message=message),), next_after=1)

    for record in (message, page, changes):
        sent: dict[str, object] = json.loads(encode_projection(project(record)))
        assert type(record).model_validate(sent) == record
    sent_message = json.loads(encode_projection(project(message)))
    assert sent_message["home"] == home.model_dump(mode="json")


def test_a_message_sent_without_a_home_is_refused() -> None:
    """ADR-0383 §5:4: a peer at the earlier version sends no home, which this one refuses."""
    sent: dict[str, object] = json.loads(encode_projection(project(_message(RecordHome.owners()))))
    del sent["home"]

    with pytest.raises(ValidationError, match="home"):
        TranscriptMessage.model_validate(sent)
