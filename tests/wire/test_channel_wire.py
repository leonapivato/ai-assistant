"""Nested channel validation and reflected streaming/error carriage (ADR-0274)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from ai_assistant.core.errors import ChannelProcessingError, ChannelProcessingTimeoutError
from ai_assistant.core.types import (
    ActivationEnding,
    ChannelIdentity,
    ChannelResult,
    EpisodeCaptureReport,
    InformationalEventResult,
    SpokenAudio,
)
from ai_assistant.wire.codec import encode_projection, project
from ai_assistant.wire.errors import UndecodableFrameError, error_payload, raise_from_payload
from ai_assistant.wire.server import _decode_arguments
from ai_assistant.wire.surface import _reaches_audio, audio_bearing, return_adapter


def test_nested_audio_is_discovered() -> None:
    assert audio_bearing("receive") == {"input"}


class RecursiveValue(BaseModel):
    """A recursive model proves that field traversal terminates."""

    child: RecursiveValue | None = None


type AudioAlias = SpokenAudio | RecursiveValue


def test_audio_detection_follows_typing_aliases_and_handles_cycles() -> None:
    assert not _reaches_audio(RecursiveValue)
    assert _reaches_audio(AudioAlias)


def test_nested_audio_refusal_has_no_rejected_value_or_exception_chain() -> None:
    with pytest.raises(UndecodableFrameError) as caught:
        _decode_arguments(
            "receive",
            {
                "input": {
                    "target": {"kind": "new_conversation"},
                    "payload": {
                        "modality": "speech",
                        "audio": {
                            "content": "PRIVATE-AUDIO!",
                            "media_type": "audio/mp4",
                        },
                    },
                },
                "reply": {"kind": "spoken", "plays": ["audio/mp4"]},
                "timeout": "PT10S",
            },
        )
    assert "PRIVATE" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_raw_unsupported_combination_is_refused_before_dispatch_without_payload() -> None:
    with pytest.raises(UndecodableFrameError) as caught:
        _decode_arguments(
            "receive",
            {
                "input": {
                    "target": {"kind": "new_conversation"},
                    "payload": {"modality": "text", "text": "PRIVATE-EVENT"},
                },
                "reply": None,
                "timeout": "PT10S",
            },
        )
    assert "PRIVATE" not in str(caught.value)
    assert caught.value.__context__ is None


@pytest.mark.parametrize("reply", [{"kind": "whole_text"}, {"kind": "streaming_text"}])
@pytest.mark.parametrize(
    "target",
    [
        {"kind": "new_conversation"},
        {"kind": "channel", "channel_type": "conversation", "instance_id": "c"},
    ],
)
def test_a_text_conversational_frame_is_refused_before_dispatch(
    reply: dict[str, str], target: dict[str, str]
) -> None:
    """ADR-0293 §11: the hub refuses the text conversational combination at decode."""
    with pytest.raises(UndecodableFrameError):
        _decode_arguments(
            "receive",
            {
                "input": {"target": target, "payload": {"modality": "text", "text": "hello"}},
                "reply": reply,
                "timeout": "PT10S",
            },
        )


@pytest.mark.parametrize("kind", [ChannelProcessingError, ChannelProcessingTimeoutError])
def test_event_failure_types_round_trip_through_existing_error_reflection(kind: Any) -> None:
    payload = error_payload(kind("informational event processing failed"), max_bytes=1024)
    with pytest.raises(kind, match="informational event processing failed"):
        raise_from_payload(payload)


@pytest.mark.parametrize("ended", list(ActivationEnding))
def test_an_events_result_round_trips_with_how_it_ended(ended: ActivationEnding) -> None:
    """ADR-0313 §4:4, §6:4: ``receive``'s event result carries ``ended`` and no summary."""
    sent = ChannelResult(
        channel=ChannelIdentity(channel_type="informational_event", instance_id="thermostat-1"),
        capture=EpisodeCaptureReport(activation_id=None, episode_id=None, state="degraded"),
        result=InformationalEventResult(ended=ended),
    )
    projected = json.loads(encode_projection(project(sent)))

    assert projected["result"] == {"kind": "informational_event", "ended": ended.value}
    assert return_adapter("receive").validate_python(projected) == sent


def test_an_events_result_carrying_a_summary_does_not_validate() -> None:
    """A peer at 97 sends ``summary`` and no ``ended``, which a peer at 98 refuses."""
    older = {
        "channel": {"channel_type": "informational_event", "instance_id": "thermostat-1"},
        "capture": {"activation_id": None, "episode_id": None, "state": "degraded"},
        "result": {"kind": "informational_event", "summary": "The thermostat entered eco mode."},
    }
    with pytest.raises(ValidationError):
        return_adapter("receive").validate_python(older)
