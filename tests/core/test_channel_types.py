"""Channel value invariants and nested admission snapshots (ADR-0274 §3)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_assistant.core.channel_validation import snapshot
from ai_assistant.core.types import (
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
    SpokenChannelResult,
    SpokenReply,
    SpokenTurn,
    TextChannelPayload,
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


def test_blank_speech_and_event_results_require_their_corresponding_identity() -> None:
    conversation = ChannelIdentity(channel_type="conversation", instance_id="one")
    capture = EpisodeCaptureReport(activation_id=None, episode_id=None, state="degraded")
    with pytest.raises(ValidationError):
        ChannelResult(
            channel=conversation, capture=capture, result=SpokenChannelResult(outcome=SpokenTurn())
        )
    with pytest.raises(ValidationError):
        ChannelResult(
            channel=conversation,
            capture=capture,
            result=InformationalEventResult(summary="summary"),
        )


def test_invalid_nested_audio_snapshot_exposes_no_value_or_exception_chain() -> None:
    audio = SpokenAudio.model_construct(content="PRIVATE-AUDIO!", media_type=SpokenAudioFormat.MP4)
    supplied = ChannelInput.model_construct(
        target=NewConversation(),
        payload=SpeechChannelPayload.model_construct(audio=audio),
        context=ChannelContext(),
        conversation=None,
    )
    with pytest.raises(ValueError, match="invalid channel") as caught:
        snapshot(supplied, SpokenReply(plays=(SpokenAudioFormat.MP4,)), streaming=False)
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
        snapshot(supplied, malformed, streaming=False)
