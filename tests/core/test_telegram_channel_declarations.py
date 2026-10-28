"""The ``telegram`` channel type's declarations in ``core`` (ADR-0323 §4, §15's first rows).

Its input origin is declared per input — ``outside`` for an input that takes in a
forward, ``user`` otherwise (§4:11, ADR-0284 §2:2); it is a type whose kind establishes
the user as an author in its places, as the hub chat's is (§4:8); and it is admitted by
its reader in the hub alone, never by ``receive``'s dispatch table (§4:1, §4:3). The
recorded input keeps each message it took in, dated, with a forward's sender claimed
(§4:10, §5:4).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.channel_validation import (
    establishes_the_user,
    input_origin,
    snapshot,
)
from ai_assistant.core.types import (
    ApprovalGiver,
    ChannelContext,
    ChannelIdentity,
    ChannelInput,
    ClaimedAuthor,
    InputOrigin,
    NewConversation,
    RecordedChannelTrigger,
    RecordedInputMessage,
    RecordedTextInput,
    TextChannelPayload,
    WholeTextReply,
)
from ai_assistant.testing.parties import line_input

LINE: Final = ChannelIdentity(channel_type="telegram", instance_id="conn-0001/424242")
AT: Final = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)


def test_the_lines_origin_is_declared_per_input() -> None:
    """§4:11: ``user`` for an input taking in no forward, ``outside`` for one that does."""
    assert input_origin(LINE) is InputOrigin.USER
    assert input_origin(LINE, takes_in_forward=True) is InputOrigin.OUTSIDE


@pytest.mark.parametrize(
    "target",
    [NewConversation(), ChannelIdentity(channel_type="informational_event", instance_id="x")],
)
def test_a_kind_taking_in_no_forward_declares_no_origin_for_one(
    target: NewConversation | ChannelIdentity,
) -> None:
    with pytest.raises(ValueError, match="takes in no forward"):
        input_origin(target, takes_in_forward=True)


def test_the_kinds_that_establish_the_user_are_the_chat_and_the_line() -> None:
    """§4:8: one of the user's conversations, or the line's chat, and nothing else."""
    assert establishes_the_user("conversation")
    assert establishes_the_user("telegram")
    assert not establishes_the_user("informational_event")
    assert not establishes_the_user("email")


@pytest.mark.parametrize("reply", [None, WholeTextReply()], ids=["no-reply", "whole-text"])
def test_receive_admits_no_telegram_input(reply: WholeTextReply | None) -> None:
    """§4:1, §4:3: only the line's reader establishes the user, so no caller injects one."""
    supplied = ChannelInput(target=LINE, payload=TextChannelPayload(text="yes, do it"))
    with pytest.raises(ValueError, match="unsupported channel"):
        snapshot(supplied, reply)


def test_the_line_has_its_own_approval_giver() -> None:
    """§4:9: added beside the hub chat's, never renaming it."""
    assert {one.value for one in ApprovalGiver} == {
        "user_through_hub_chat",
        "user_through_telegram",
    }


def _trigger(*messages: RecordedInputMessage) -> RecordedChannelTrigger:
    return RecordedChannelTrigger(
        target=LINE,
        channel=LINE,
        payload=RecordedTextInput(text="\n\n".join(one.text for one in messages)),
        context=ChannelContext(),
        reply=WholeTextReply(),
        # ADR-0351 §2:6: an input of messages carries their parties, as the line
        # declares each.
        parties=line_input(messages)[0],
        messages=line_input(messages)[1],
    )


def test_the_recorded_input_keeps_each_message_dated_with_a_forwards_sender() -> None:
    """§4:10, §5:4: separate and dated in the episode, a forward's author claimed."""
    forwarded = RecordedInputMessage(
        text="Lunch?",
        sent_at=AT,
        position=7,
        forwarded_from=ClaimedAuthor(name="Sam", account_id=77),
    )
    own = RecordedInputMessage(text="Is that ok?", sent_at=AT, position=8)

    trigger = _trigger(forwarded, own)
    again = RecordedChannelTrigger.model_validate_json(trigger.model_dump_json())

    assert again == trigger
    assert again.messages[0].forwarded_from == ClaimedAuthor(name="Sam", account_id=77)


def test_a_trigger_recording_no_messages_reads_as_before() -> None:
    """A channel that records none leaves them empty, and a stored trigger reads whole."""
    stored: dict[str, object] = {
        "kind": "channel_input",
        "target": {"kind": "channel", "channel_type": "conversation", "instance_id": "c"},
        "channel": None,
        "payload": {"modality": "text", "text": "hi"},
        "context": {"history": [], "reply_to": None},
        "reply": {"kind": "whole_text"},
        "parties": [{"kind": "person", "identifier": "person:owner"}],
    }
    assert RecordedChannelTrigger.model_validate(stored).messages == ()


def test_a_recorded_message_refuses_a_naive_time_and_an_unknown_field() -> None:
    with pytest.raises(ValidationError):
        RecordedInputMessage(text="hi", sent_at=datetime(2026, 1, 1))  # noqa: DTZ001 — the naive time refused
    with pytest.raises(ValidationError):
        RecordedInputMessage.model_validate({"text": "hi", "sent_at": AT, "author": "me"})
