"""Channel value invariants and nested admission snapshots (ADR-0274 §3)."""

from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from ai_assistant.core import types as types_module
from ai_assistant.core.channel_validation import snapshot, validate_combination
from ai_assistant.core.types import (
    ActivationEnding,
    ChannelContext,
    ChannelContextItem,
    ChannelIdentity,
    ChannelInput,
    ChannelResult,
    EpisodeCaptureReport,
    InformationalEventResult,
    NewConversation,
    SpeechChannelPayload,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenReply,
    StreamingTextReply,
    TextChannelPayload,
    WholeTextReply,
)


def test_identity_normalizes_both_parts_and_retains_channel_type() -> None:
    identity = ChannelIdentity(channel_type=" conversation ", instance_id=" one ")
    assert identity == ChannelIdentity(channel_type="conversation", instance_id="one")
    assert identity != ChannelIdentity(channel_type="informational_event", instance_id="one")


@pytest.mark.parametrize("part", ["channel_type", "instance_id"])
def test_identity_rejects_blank_parts(part: str) -> None:
    fields = {"channel_type": "conversation", "instance_id": "one", part: " "}
    with pytest.raises(ValidationError):
        ChannelIdentity.model_validate(fields)


def test_context_attribution_alone_and_history_without_text_are_invalid() -> None:
    with pytest.raises(ValidationError):
        ChannelContextItem(source="claimed owner")
    with pytest.raises(ValidationError):
        ChannelContext(history=(ChannelContextItem(item_id="one"),))
    assert ChannelContext(reply_to=ChannelContextItem(item_id="one")).history == ()


def test_an_event_result_requires_an_event_identity() -> None:
    conversation = ChannelIdentity(channel_type="conversation", instance_id="one")
    capture = EpisodeCaptureReport(activation_id=None, episode_id=None, state="degraded")
    with pytest.raises(ValidationError):
        ChannelResult(
            channel=conversation,
            capture=capture,
            result=InformationalEventResult(ended=ActivationEnding.DONE),
        )


def test_invalid_nested_audio_snapshot_exposes_no_value_or_exception_chain() -> None:
    audio = SpokenAudio.model_construct(content="PRIVATE-AUDIO!", media_type=SpokenAudioFormat.MP4)
    supplied = ChannelInput.model_construct(
        target=NewConversation(),
        payload=SpeechChannelPayload.model_construct(audio=audio),
        context=ChannelContext(),
    )
    with pytest.raises(ValueError, match="invalid channel") as caught:
        snapshot(supplied, SpokenReply(plays=(SpokenAudioFormat.MP4,)))
    assert "PRIVATE" not in str(caught.value)
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None


def test_invalid_reply_cannot_become_an_event_with_no_reply() -> None:
    supplied = ChannelInput(
        target=ChannelIdentity(channel_type="informational_event", instance_id="one"),
        payload=TextChannelPayload(text="event"),
    )
    malformed = SpokenReply.model_construct(plays=())
    with pytest.raises(ValueError, match="invalid channel"):
        snapshot(supplied, malformed)


@pytest.mark.parametrize(
    "target", [NewConversation(), ChannelIdentity(channel_type="conversation", instance_id="one")]
)
def test_the_text_conversational_combination_is_admitted_by_no_entry(
    target: NewConversation | ChannelIdentity,
) -> None:
    """ADR-0293 §11, ADR-0309 §5:1: ``converse``'s own typed input left with ``converse``."""
    supplied = ChannelInput(target=target, payload=TextChannelPayload(text="hello"))
    with pytest.raises(ValueError, match="unsupported channel"):
        snapshot(supplied, WholeTextReply())


def test_snapshot_takes_no_typed_turn() -> None:
    """ADR-0309 §5:1: no caller is left to admit a typed turn, so no entry offers one."""
    assert "typed_turn" not in inspect.signature(snapshot).parameters
    assert "typed_turn" not in inspect.signature(validate_combination).parameters


def test_a_streaming_reply_is_admitted_by_no_entry() -> None:
    """ADR-0293 §11 retired both entries that offered it; a recorded trigger may still hold one."""
    supplied = ChannelInput(target=NewConversation(), payload=TextChannelPayload(text="hello"))
    with pytest.raises(ValueError, match="unsupported channel"):
        snapshot(supplied, StreamingTextReply())


@pytest.mark.parametrize(
    "target", [NewConversation(), ChannelIdentity(channel_type="conversation", instance_id="one")]
)
def test_the_spoken_conversational_combination_is_admitted_by_no_entry(
    target: NewConversation | ChannelIdentity,
) -> None:
    """ADR-0313 §3:2, §4:1: spoken conversation retired, so no entry admits it."""
    supplied = ChannelInput(
        target=target,
        payload=SpeechChannelPayload(
            audio=SpokenAudio(content="YXVkaW8=", media_type=SpokenAudioFormat.MP4)
        ),
    )
    with pytest.raises(ValueError, match="unsupported channel"):
        snapshot(supplied, SpokenReply(plays=(SpokenAudioFormat.MP4,)))


def test_an_input_carries_no_conversation_options() -> None:
    """ADR-0313 §4:2: ``ChannelInput`` lost ``conversation``, and a value naming it is refused."""
    assert set(ChannelInput.model_fields) == {"target", "payload", "context"}
    held = ChannelInput(target=NewConversation(), payload=TextChannelPayload(text="hi"))
    dumped = held.model_dump(mode="json")
    assert ChannelInput.model_validate(dumped) == held
    with pytest.raises(ValidationError, match="conversation"):
        ChannelInput.model_validate({**dumped, "conversation": {}})


@pytest.mark.parametrize(
    "name",
    ["SpokenTurn", "SpokenChannelResult", "ConversationInputOptions", "TextChannelResult"],
)
def test_the_retired_channel_types_are_gone_from_core(name: str) -> None:
    """ADR-0313 §3:1, §4:2, §4:6: these leave ``core`` with conversation on ``receive``."""
    assert not hasattr(types_module, name)
