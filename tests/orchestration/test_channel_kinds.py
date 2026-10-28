"""What a channel kind declares, in code, and how a recorded place is read (ADR-0323 §9).

The Telegram kind is the first declared in code, so its shape is the general one: a
field per row of ADR-0292's table. Its admission rows are ``core``'s register, read and
never restated. A message's place is ``<channel type>:<instance id>``, and whether a
recorded place is one where the user is established is read from it, so authorizing
names no channel (§4:5, §4:8).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import Final

import pytest

from ai_assistant.core.channel_validation import declared_input
from ai_assistant.core.types import (
    ApprovalGiver,
    ChannelIdentity,
    ClaimedAuthor,
    RecordedInputMessage,
    SupportHolder,
)
from ai_assistant.orchestration.channel_kinds import (
    Audience,
    WindowSource,
    place_of,
    users_place,
)
from ai_assistant.orchestration.conversations import conversation_channel
from ai_assistant.orchestration.telegram import (
    TELEGRAM,
    TELEGRAM_DESCRIPTION,
    line_channel,
)

_AT: Final = datetime(2026, 10, 28, 9, tzinfo=UTC)


def test_a_place_is_its_channel_type_then_its_instance() -> None:
    assert place_of(conversation_channel("c-1")) == "conversation:c-1"
    assert place_of(line_channel("conn-1", 42)) == "telegram:conn-1/42"


@pytest.mark.parametrize(
    ("place", "users"),
    [
        ("conversation:c-1", True),
        ("telegram:conn-1/42", True),
        ("informational_event:mail-1", False),
        ("place:chat", False),
        ("conversation:", False),
        ("conversation", False),
        ("", False),
        (None, False),
    ],
)
def test_a_users_place_is_one_whose_kind_establishes_the_user(
    place: str | None, users: bool
) -> None:
    """§4:8: one of the user's conversations, or the line's chat."""
    assert users_place(place) is users


def test_the_telegram_kind_declares_what_its_table_states() -> None:
    """§9:1: each row in the ADR-0292 clause it names."""
    assert TELEGRAM.channel_type == "telegram"
    assert TELEGRAM.window is WindowSource.EPISODES
    assert TELEGRAM.audience is Audience.PRIVATE
    assert TELEGRAM.text_only
    assert TELEGRAM.message_limit == 4096
    assert TELEGRAM.push_filter is None
    assert TELEGRAM.description == TELEGRAM_DESCRIPTION
    assert "plain text" in TELEGRAM.description
    assert TELEGRAM.establishes_the_user
    assert TELEGRAM.approval_giver is ApprovalGiver.USER_THROUGH_TELEGRAM


def test_the_kind_reads_its_parties_per_input_from_cores_register() -> None:
    """ADR-0351 §3:1: the line's message is the owner's, a forward its sender's, claimed."""
    line = line_channel("conn-1", 42)
    typed = RecordedInputMessage(text="hi", sent_at=_AT)
    forwarded = RecordedInputMessage(
        text="see you", sent_at=_AT, forwarded_from=ClaimedAuthor(name="Sam", account_id=7)
    )
    assert TELEGRAM.input_parties(line, (typed,)) == declared_input(line, (typed,))
    parties, (message,) = TELEGRAM.input_parties(line, (forwarded,))
    assert parties == (SupportHolder.source("7", claimed=True),)
    assert message.party == parties[0]
    with pytest.raises(ValueError, match="its own channels"):
        TELEGRAM.input_parties(conversation_channel("c-1"), (typed,))


def test_a_kind_that_establishes_nobody_gives_no_approval() -> None:
    with pytest.raises(ValueError, match="establishes the user"):
        dataclasses.replace(TELEGRAM, channel_type="informational_event")


def test_a_window_says_how_many_items_it_holds_and_none_says_none() -> None:
    with pytest.raises(ValueError, match="how many items"):
        dataclasses.replace(TELEGRAM, window=WindowSource.NONE)
    with pytest.raises(ValueError, match="at least one item"):
        dataclasses.replace(TELEGRAM, window_items=0)


def test_the_lines_channel_is_keyed_by_its_connection_and_its_chat() -> None:
    """§2:3: a changed account, or a new bot for the same account, is a new place."""
    one = line_channel("conn-1", 42)
    assert one == ChannelIdentity(channel_type="telegram", instance_id="conn-1/42")
    assert line_channel("conn-2", 42) != one
    assert line_channel("conn-1", 43) != one
