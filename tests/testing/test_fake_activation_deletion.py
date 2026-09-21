"""The canonical fake enforces deletion fences across concurrent capture."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import TranscriptArchiveError, UnknownConversationError
from ai_assistant.core.types import (
    ChannelInput,
    NewConversation,
    TextChannelPayload,
    WholeTextReply,
)
from ai_assistant.testing import FakeAssistantEngine

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import ChannelIdentity, ChannelResult, MemoryWrite

_BUDGET = timedelta(seconds=10)


async def _receive(
    engine: FakeAssistantEngine, channel: ChannelIdentity | None = None
) -> ChannelResult:
    return await engine.receive(
        ChannelInput(
            target=NewConversation() if channel is None else channel,
            payload=TextChannelPayload(text="hello"),
        ),
        reply=WholeTextReply(),
        timeout=_BUDGET,
    )


async def test_archive_deletion_fences_new_capture_and_failed_deletion_can_be_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeAssistantEngine()
    first = await _receive(engine)
    assert first.channel is not None
    entered, release = asyncio.Event(), asyncio.Event()
    discard = engine.archive.discard

    async def fail(_address: str) -> None:
        entered.set()
        await release.wait()
        raise TranscriptArchiveError("controlled archive failure")

    monkeypatch.setattr(engine.archive, "discard", fail)
    forgetting = asyncio.create_task(engine.forget_conversation(first.channel.instance_id))
    await entered.wait()
    try:
        with pytest.raises(UnknownConversationError):
            await _receive(engine, first.channel)
    finally:
        release.set()
        with pytest.raises(TranscriptArchiveError):
            await forgetting
    assert await engine.conversation(first.channel.instance_id) is None
    assert await engine.recent_conversations() == ()
    assert first.capture.episode_id is not None
    assert await engine.episode_chunk(first.capture.episode_id) is not None
    with pytest.raises(UnknownConversationError):
        await _receive(engine, first.channel)
    monkeypatch.setattr(engine.archive, "discard", discard)
    assert await engine.forget_conversation(first.channel.instance_id)
    assert (await engine.episodes()).items == ()


async def test_a_capture_pending_at_deletion_cannot_join_a_new_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        assert await engine.forget_conversation(first.channel.instance_id)
        fresh = await _receive(engine)
        assert fresh.channel != first.channel
    finally:
        release.set()
        old = await pending
    assert old.capture.state == "degraded"
    assert old.capture.episode_id is None
    assert {row.position.episode_id for row in (await engine.episodes()).items} == {
        fresh.capture.episode_id
    }
