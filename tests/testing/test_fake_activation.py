"""Faults and empty speech retain the fake's independent M36 contract behavior."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import MemoryStoreError, OversizedValueError
from ai_assistant.core.types import (
    ChannelIdentity,
    ChannelInput,
    EpisodicMemory,
    NewConversation,
    ProcessingReason,
    ProcessingStatus,
    RecordedChannelTrigger,
    RecordedSpeechInput,
    SpeechChannelPayload,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenChannelResult,
    SpokenReply,
    TextChannelPayload,
    TextChannelResult,
    WholeTextReply,
)
from ai_assistant.testing import FakeAssistantEngine, FakeMemoryStore

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import MemoryWrite

_BUDGET = timedelta(seconds=10)
_AUDIO = SpokenAudio(content="YXVkaW8=", media_type=SpokenAudioFormat.MP4)


@pytest.mark.parametrize("target", ["new", "existing", "missing"])
async def test_empty_speech_keeps_exact_transcript_and_never_falls_back(target: str) -> None:
    engine = FakeAssistantEngine()
    engine.spoken_transcript = " \t\n"
    if target == "existing":
        engine.start_conversation("room")
    result = await engine.receive(
        ChannelInput(
            target=NewConversation()
            if target == "new"
            else ChannelIdentity(channel_type="conversation", instance_id="room"),
            payload=SpeechChannelPayload(audio=_AUDIO),
        ),
        reply=SpokenReply(plays=(SpokenAudioFormat.MP4,)),
        timeout=_BUDGET,
    )
    assert isinstance(result.result, SpokenChannelResult)
    assert result.channel is None
    assert result.result.outcome.outcome is None
    assert result.result.outcome.episode_id is None
    episodes = await engine.episode_memory.export()
    if target == "missing":
        assert result.capture.state == "degraded"
        assert result.capture.episode_id is None
        assert episodes == []
        return
    assert result.capture.state == "recorded"
    (episode,) = episodes
    assert isinstance(episode, EpisodicMemory)
    assert episode.id == result.capture.episode_id
    processing = episode.processing_record
    assert processing is not None
    assert processing.status is ProcessingStatus.COMPLETED
    assert processing.reason is ProcessingReason.NO_CONTENT
    assert not processing.model_eligible
    assert isinstance(processing.trigger, RecordedChannelTrigger)
    assert isinstance(processing.trigger.payload, RecordedSpeechInput)
    assert processing.trigger.payload.transcript == " \t\n"
    assert (processing.trigger.channel is None) == (target == "new")


class RefusingMemory(FakeMemoryStore):
    """Refuse a capture without changing the processing result."""

    async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
        raise MemoryStoreError("private diagnostic")


@pytest.mark.parametrize("fault", ["id", "write"])
async def test_capture_failure_retains_reply_and_reports_only_confirmed_addresses(
    fault: str,
) -> None:
    engine = FakeAssistantEngine()
    if fault == "id":
        engine.activation_id_factory = lambda: "not-a-uuid"
    else:
        engine.episode_memory = RefusingMemory()
    result = await engine.receive(
        ChannelInput(target=NewConversation(), payload=TextChannelPayload(text="hello")),
        reply=WholeTextReply(),
        timeout=_BUDGET,
    )
    assert isinstance(result.result, TextChannelResult)
    assert result.result.outcome.reply
    assert result.result.outcome.capture_degraded
    assert result.capture.state == "degraded"
    assert await engine.episode_memory.export() == []
    if fault == "id":
        assert result.capture.activation_id is None
        assert result.capture.episode_id is None
    else:
        assert result.capture.activation_id is not None
        assert result.capture.episode_id is not None  # index committed before the content failed


async def test_rejected_legacy_input_persists_nothing() -> None:
    engine = FakeAssistantEngine(max_payload_bytes=512)
    with pytest.raises(OversizedValueError):
        await engine.converse("x" * 1024, timeout=_BUDGET)
    assert await engine.episode_memory.export() == []
    assert engine.conversations_held == {}


async def test_recovered_control_degrades_and_replay_does_not_capture() -> None:
    engine = FakeAssistantEngine()
    engine.start_conversation("unrelated")
    confirmation = engine.park("private-token")
    first = await engine.resume(confirmation.token, approved=False, timeout=_BUDGET)
    assert first.capture_degraded
    assert await engine.episode_memory.export() == []
    second = await engine.resume(confirmation.token, approved=False, timeout=_BUDGET)
    assert not second.capture_degraded
    assert await engine.episode_memory.export() == []
