"""Faults retain the fake's independent M36 contract behavior.

A conversation's episode is captured from the activation the fake's reader runs for a
written message (ADR-0293 §6), the one conversational input left since ``converse``
retired (ADR-0309 §5:1); an event's from ``receive`` (ADR-0313 §4:1).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import MemoryStoreError, OversizedValueError
from ai_assistant.core.types import (
    ActivationEnding,
    ChannelIdentity,
    ChannelInput,
    ChannelResult,
    ChatDevice,
    DeviceAccess,
    EpisodicMemory,
    InformationalEventResult,
    TextChannelPayload,
    UserMessage,
)
from ai_assistant.testing import FakeAssistantEngine, FakeMemoryStore

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import MemoryWrite

_BUDGET = timedelta(seconds=10)


async def _event(engine: FakeAssistantEngine, text: str = "the door opened") -> ChannelResult:
    """One informational event through ``receive``, and its receipt."""
    return await engine.receive(
        ChannelInput(
            target=ChannelIdentity(channel_type="informational_event", instance_id="door"),
            payload=TextChannelPayload(text=text),
        ),
        reply=None,
        timeout=_BUDGET,
    )


async def _written(engine: FakeAssistantEngine) -> str:
    """Start a conversation, write one message into it, and let the reader take it in."""
    await engine.set_my_devices([ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)])
    conversation = (await engine.start_conversation()).id
    await engine.write_message(
        conversation, message=UserMessage(device_id="phone", message_id="m-1", text="hello")
    )
    async with asyncio.timeout(10):
        while engine._chat_reads:
            await asyncio.gather(*engine._chat_reads)
    return conversation


class RefusingMemory(FakeMemoryStore):
    """Refuse a capture without changing the processing result."""

    async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
        raise MemoryStoreError("private diagnostic")


@pytest.mark.parametrize("fault", ["id", "write"])
async def test_capture_failure_retains_the_result_and_reports_only_confirmed_addresses(
    fault: str,
) -> None:
    engine = FakeAssistantEngine()
    if fault == "id":
        engine.activation_id_factory = lambda: "not-a-uuid"
    else:
        engine.episode_memory = RefusingMemory()
    result = await _event(engine)
    assert result.result == InformationalEventResult(ended=ActivationEnding.DONE)
    assert result.capture.state == "degraded"
    assert await engine.episode_memory.export() == []
    # An event's episode has no conversation index to commit ahead of its content, so
    # a refused write confirms no address: only the activation id it was admitted with.
    assert result.capture.episode_id is None
    assert (result.capture.activation_id is None) == (fault == "id")


async def test_rejected_input_persists_nothing() -> None:
    engine = FakeAssistantEngine(max_payload_bytes=512)
    with pytest.raises(OversizedValueError):
        await _event(engine, "x" * 1024)
    assert await engine.episode_memory.export() == []
    assert engine.conversations_held == {}


async def test_a_colliding_activation_id_moves_no_episode_to_the_second_conversation() -> None:
    """ADR-0283 §2, §7:3: insert-if-absent refuses the second write, and nothing moves.

    Forgetting the second conversation must not take the first one's episode with it.
    """
    engine = FakeAssistantEngine()
    engine.activation_id_factory = lambda: "00000000-0000-4000-8000-0000000000aa"
    address = "activation:00000000-0000-4000-8000-0000000000aa"

    first = await _written(engine)
    second = await _written(engine)

    assert first != second
    episode = await engine.episode_memory.get(address)
    assert isinstance(episode, EpisodicMemory)
    assert episode.processing_record is not None
    assert episode.processing_record.trigger.channel == ChannelIdentity(
        channel_type="conversation", instance_id=first
    ), "the first capture holds the address, and the second's degraded"
    second_digest = await engine.conversation(second)
    assert second_digest is not None
    assert second_digest.recorded_turns == 0
    assert await engine.forget_conversation(second) is False, "its place holds nothing"
    assert await engine.episode_memory.get(address) is not None
    first_digest = await engine.conversation(first)
    assert first_digest is not None
    assert first_digest.recorded_turns == 1


async def test_a_conversation_colliding_with_a_standalone_episode_cannot_claim_it() -> None:
    """ADR-0283 §7:3: the standalone episode keeps its address and leaves with no forget.

    An event records a standalone episode; a conversation's capture at the same
    address degrades, and forgetting that conversation leaves the standalone one.
    """
    engine = FakeAssistantEngine()
    engine.activation_id_factory = lambda: "00000000-0000-4000-8000-0000000000bb"
    address = "activation:00000000-0000-4000-8000-0000000000bb"
    event = await _event(engine)
    assert event.capture.state == "recorded"
    assert await engine.episode_memory.get(address) is not None

    conversation = await _written(engine)

    digest = await engine.conversation(conversation)
    assert digest is not None
    assert digest.recorded_turns == 0
    assert await engine.forget_conversation(conversation) is False, "its place holds nothing"
    assert await engine.episode_memory.get(address) is not None
