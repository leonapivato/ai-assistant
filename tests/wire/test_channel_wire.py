"""Nested channel validation and reflected streaming/error carriage (ADR-0274)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from ai_assistant.core.errors import ChannelProcessingError, ChannelProcessingTimeoutError
from ai_assistant.core.types import ChannelResult, ReplyChunk, SpokenAudio
from ai_assistant.wire.errors import UndecodableFrameError, error_payload, raise_from_payload
from ai_assistant.wire.server import _decode_arguments
from ai_assistant.wire.surface import _reaches_audio, audio_bearing, chunk_adapter, terminal_adapter


def test_nested_audio_and_reflected_terminal_are_discovered() -> None:
    assert audio_bearing("receive") == {"input"}
    assert audio_bearing("receive_streaming") == {"input"}
    assert chunk_adapter("receive_streaming")._type is ReplyChunk
    assert terminal_adapter("receive_streaming")._type is ChannelResult


class RecursiveValue(BaseModel):
    """A recursive model proves that field traversal terminates."""

    child: RecursiveValue | None = None


type AudioAlias = SpokenAudio | RecursiveValue


def test_audio_detection_follows_typing_aliases_and_handles_cycles() -> None:
    assert not _reaches_audio(RecursiveValue)
    assert _reaches_audio(AudioAlias)


@pytest.mark.parametrize("method", ["receive", "receive_streaming"])
def test_nested_audio_refusal_has_no_rejected_value_or_exception_chain(method: str) -> None:
    with pytest.raises(UndecodableFrameError) as caught:
        _decode_arguments(
            method,
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


@pytest.mark.parametrize("kind", [ChannelProcessingError, ChannelProcessingTimeoutError])
def test_event_failure_types_round_trip_through_existing_error_reflection(kind: Any) -> None:
    payload = error_payload(kind("informational event processing failed"), max_bytes=1024)
    with pytest.raises(kind, match="informational event processing failed"):
        raise_from_payload(payload)
