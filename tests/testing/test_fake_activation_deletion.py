"""The canonical fake enforces deletion fences across concurrent capture."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import MemoryStoreError, UnknownConversationError
from ai_assistant.core.types import (
    ChannelInput,
    NewConversation,
    SpeechChannelPayload,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenReply,
)
from ai_assistant.testing import FakeAssistantEngine

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import ChannelIdentity, ChannelResult, MemoryWrite

_BUDGET = timedelta(seconds=10)


async def _receive(
    engine: FakeAssistantEngine, channel: ChannelIdentity | None = None
) -> ChannelResult:
    # Spoken: ADR-0293 §11 takes the text conversational combination off ``receive``.
    return await engine.receive(
        ChannelInput(
            target=NewConversation() if channel is None else channel,
            payload=SpeechChannelPayload(
                audio=SpokenAudio(content="YXVkaW8=", media_type=SpokenAudioFormat.MP4)
            ),
        ),
        reply=SpokenReply(plays=(SpokenAudioFormat.MP4,)),
        timeout=_BUDGET,
    )


async def test_deletion_fences_new_capture_and_keeps_the_episodes() -> None:
    """ADR-0293 §2:2, §2:3: no capture joins a deleted conversation, and none is lost."""
    engine = FakeAssistantEngine()
    first = await _receive(engine)
    assert first.channel is not None
    assert first.capture.episode_id is not None

    assert await engine.delete_conversation(first.channel.instance_id) is True

    with pytest.raises(UnknownConversationError):
        await _receive(engine, first.channel)
    assert await engine.conversation(first.channel.instance_id) is None
    assert await engine.recent_conversations() == ()
    assert await engine.episode_chunk(first.capture.episode_id) is not None
    assert await engine.forget_conversation(first.channel.instance_id) is True
    assert (await engine.episodes()).items == (), "forgetting reaches the deleted place"


async def test_a_failed_forget_can_be_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-0293 §2:4: forgetting leaves the conversation, and a repeat finishes it."""
    engine = FakeAssistantEngine()
    first = await _receive(engine)
    assert first.channel is not None
    assert first.capture.episode_id is not None
    delete = engine.episode_memory.delete

    async def fail(_record_id: str) -> bool:
        raise MemoryStoreError("controlled deletion failure")

    monkeypatch.setattr(engine.episode_memory, "delete", fail)
    with pytest.raises(MemoryStoreError):
        await engine.forget_conversation(first.channel.instance_id)
    assert await engine.conversation(first.channel.instance_id) is not None
    assert await engine.episode_chunk(first.capture.episode_id) is not None

    monkeypatch.setattr(engine.episode_memory, "delete", delete)
    assert await engine.forget_conversation(first.channel.instance_id) is True
    assert (await engine.episodes()).items == ()
    assert await engine.conversation(first.channel.instance_id) is not None


async def test_a_capture_pending_at_deletion_cannot_join_a_new_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0293 §2:7: the pending capture keeps its episode, on the deleted place."""
    engine = FakeAssistantEngine()
    first = await _receive(engine)
    assert first.channel is not None
    entered, release = asyncio.Event(), asyncio.Event()
    write = engine.episode_memory.write_atomic
    pause = True

    async def delayed(writes: Sequence[MemoryWrite]) -> Sequence[str]:
        nonlocal pause
        if pause:
            pause = False
            entered.set()
            await release.wait()
        return await write(writes)

    monkeypatch.setattr(engine.episode_memory, "write_atomic", delayed)
    pending = asyncio.create_task(_receive(engine, first.channel))
    await entered.wait()
    try:
        assert await engine.delete_conversation(first.channel.instance_id)
        fresh = await _receive(engine)
        assert fresh.channel != first.channel
    finally:
        release.set()
        old = await pending
    assert old.capture.state == "degraded"
    assert old.capture.episode_id is None
    assert fresh.channel is not None
    assert await engine.forget_conversation(fresh.channel.instance_id) is True
    assert {row.position.episode_id for row in (await engine.episodes()).items} == {
        first.capture.episode_id,
        f"activation:{old.capture.activation_id}",
    }, "the pending one stayed on the deleted place, not the fresh one"
