"""The canonical fake respects the channel wrapper's streaming ceiling."""

from __future__ import annotations

from datetime import timedelta

from ai_assistant.core.types import (
    ChannelInput,
    ChannelResult,
    NewConversation,
    ReplyChunk,
    StreamingTextReply,
    TextChannelPayload,
    TextChannelResult,
)
from ai_assistant.orchestration.payloads import canonical_payload
from ai_assistant.testing import FakeAssistantEngine


async def test_fake_stops_before_a_chunk_whose_wrapped_terminal_would_overflow() -> None:
    supplied = ChannelInput(target=NewConversation(), payload=TextChannelPayload(text="hello"))
    wide = FakeAssistantEngine()
    values = [
        value
        async for value in wide.receive_streaming(
            supplied,
            reply=StreamingTextReply(),
            timeout=timedelta(seconds=10),
        )
    ]
    baseline = values[-1]
    assert isinstance(baseline, ChannelResult)
    limit = len(canonical_payload(baseline)) - 1
    tight = FakeAssistantEngine(max_payload_bytes=limit)
    bounded = [
        value
        async for value in tight.receive_streaming(
            supplied,
            reply=StreamingTextReply(),
            timeout=timedelta(seconds=10),
        )
    ]
    terminal = bounded[-1]
    assert isinstance(terminal, ChannelResult)
    assert isinstance(terminal.result, TextChannelResult)
    assert terminal.result.outcome.reply_degraded
    assert len(canonical_payload(terminal)) <= limit
    assert terminal.result.outcome.reply == "".join(
        value.text for value in bounded if isinstance(value, ReplyChunk)
    )
