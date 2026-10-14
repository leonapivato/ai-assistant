"""The canonical fake enforces deletion fences across concurrent capture.

A conversation's episode is captured from the activation the fake's reader runs for a
written message (ADR-0293 §6), the one conversational input left since ``converse``
retired (ADR-0309 §5:1).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import MemoryStoreError, UnknownConversationError
from ai_assistant.core.types import ChatDevice, DeviceAccess, UserMessage
from ai_assistant.testing import FakeAssistantEngine

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import MemoryWrite


async def _fresh(engine: FakeAssistantEngine) -> str:
    """Start a conversation on one device, as the chat space starts one (ADR-0293 §2:1)."""
    await engine.set_my_devices([ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)])
    return (await engine.start_conversation()).id


async def _write(engine: FakeAssistantEngine, conversation: str, message_id: str) -> None:
    """Write one message, which the fake's reader takes in on a task of its own."""
    await engine.write_message(
        conversation, message=UserMessage(device_id="phone", message_id=message_id, text="hello")
    )


async def _settled(engine: FakeAssistantEngine, *, leaving: int = 0) -> None:
    """Wait until no more than ``leaving`` of the reader's reads are still running."""
    async with asyncio.timeout(10):
        while len(engine._chat_reads) > leaving:
            await asyncio.wait(set(engine._chat_reads), return_when=asyncio.FIRST_COMPLETED)


async def _episodes(engine: FakeAssistantEngine) -> set[str]:
    return {row.position.episode_id for row in (await engine.episodes()).items}


async def test_deletion_fences_new_capture_and_keeps_the_episodes() -> None:
    """ADR-0293 §2:2, §2:3: no capture joins a deleted conversation, and none is lost."""
    engine = FakeAssistantEngine()
    conversation = await _fresh(engine)
    await _write(engine, conversation, "m-1")
    await _settled(engine)
    (episode,) = await _episodes(engine)

    assert await engine.delete_conversation(conversation) is True

    with pytest.raises(UnknownConversationError):
        await _write(engine, conversation, "m-2")
    await _settled(engine)
    assert await engine.conversation(conversation) is None
    assert await engine.recent_conversations() == ()
    assert await engine.episode_chunk(episode) is not None
    assert await _episodes(engine) == {episode}, "the refused message captured nothing"
    assert await engine.forget_conversation(conversation) is True
    assert (await engine.episodes()).items == (), "forgetting reaches the deleted place"


async def test_a_failed_forget_can_be_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-0293 §2:4: forgetting leaves the conversation, and a repeat finishes it."""
    engine = FakeAssistantEngine()
    conversation = await _fresh(engine)
    await _write(engine, conversation, "m-1")
    await _settled(engine)
    (episode,) = await _episodes(engine)
    delete = engine.episode_memory.delete

    async def fail(_record_id: str) -> bool:
        raise MemoryStoreError("controlled deletion failure")

    monkeypatch.setattr(engine.episode_memory, "delete", fail)
    with pytest.raises(MemoryStoreError):
        await engine.forget_conversation(conversation)
    assert await engine.conversation(conversation) is not None
    assert await engine.episode_chunk(episode) is not None

    monkeypatch.setattr(engine.episode_memory, "delete", delete)
    assert await engine.forget_conversation(conversation) is True
    assert (await engine.episodes()).items == ()
    assert await engine.conversation(conversation) is not None


async def test_a_capture_pending_at_deletion_cannot_join_a_new_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0293 §2:7: the pending capture keeps its episode, on the deleted place."""
    engine = FakeAssistantEngine()
    first = await _fresh(engine)
    await _write(engine, first, "m-1")
    await _settled(engine)
    (earlier,) = await _episodes(engine)
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
    await _write(engine, first, "m-2")
    await entered.wait()
    try:
        assert await engine.delete_conversation(first)
        fresh = await _fresh(engine)
        assert fresh != first
        await _write(engine, fresh, "m-3")
        await _settled(engine, leaving=1)
        captured = await _episodes(engine) - {earlier}
    finally:
        release.set()
    await _settled(engine)
    pending = await _episodes(engine) - captured - {earlier}
    assert len(captured) == 1
    assert len(pending) == 1
    assert await engine.forget_conversation(fresh) is True
    assert await _episodes(engine) == {earlier, *pending}, (
        "the pending one stayed on the deleted place, not the fresh one"
    )
