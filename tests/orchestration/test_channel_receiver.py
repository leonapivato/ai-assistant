"""Production receiver evidence for ADR-0274."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from test_engine import Harness

from ai_assistant.core.errors import OversizedValueError
from ai_assistant.core.types import (
    ChannelContext,
    ChannelContextItem,
    ChannelIdentity,
    ChannelInput,
    Message,
    TextChannelPayload,
)
from ai_assistant.testing import FakeModelProvider

if TYPE_CHECKING:
    from collections.abc import Sequence


_BUDGET = timedelta(seconds=10)


class ControlledModel(FakeModelProvider):
    """A deterministic model barrier with observable cancellation cleanup."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.cleaned = asyncio.Event()
        self.error: Exception | None = None
        self.answer: Message | None = None

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        self.entered.set()
        try:
            await self.release.wait()
            if self.error is not None:
                raise self.error
            if self.answer is not None:
                return self.answer
            return await super().complete(messages, model=model)
        finally:
            self.cleaned.set()


async def test_new_context_counts_towards_payload_limit_without_truncation() -> None:
    # An event: every conversational input is refused before it is measured
    # (ADR-0313 §4:1), so the one admitted combination carries the context here.
    harness = Harness(max_payload_bytes=1024)
    with pytest.raises(OversizedValueError):
        await harness.engine.receive(
            ChannelInput(
                target=ChannelIdentity(channel_type="informational_event", instance_id="source"),
                payload=TextChannelPayload(text="event"),
                context=ChannelContext(history=(ChannelContextItem(text="x" * 1024),)),
            ),
            reply=None,
            timeout=_BUDGET,
        )
    assert await harness.conversation_store.recent() == []
    assert await harness.memory.export() == []
