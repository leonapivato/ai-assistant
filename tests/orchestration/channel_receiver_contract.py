"""Shared channel receiver behavior for engine, canonical fake, and wire client."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import ChannelProcessingTimeoutError, UnknownConversationError

if TYPE_CHECKING:
    from ai_assistant.core.protocols import AssistantEngine
from ai_assistant.core.streams import closing_stream
from ai_assistant.core.types import (
    ChannelContext,
    ChannelContextItem,
    ChannelIdentity,
    ChannelInput,
    ChannelResult,
    ConversationInputOptions,
    InformationalEventResult,
    NewConversation,
    ReplyChunk,
    SpeechChannelPayload,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenChannelResult,
    SpokenReply,
    StreamingTextReply,
    TextChannelPayload,
    TextChannelResult,
    WholeTextReply,
)

_BUDGET = timedelta(seconds=10)


def event_input() -> ChannelInput:
    """An input-only adapter's source-local identity and material."""
    return ChannelInput(
        target=ChannelIdentity(channel_type="informational_event", instance_id="thermostat-1"),
        payload=TextChannelPayload(text="The thermostat entered eco mode at 18:00."),
        context=ChannelContext(reply_to=ChannelContextItem(item_id="local-17")),
    )


class ChannelReceiverContract:
    """Channel obligations shared by every AssistantEngine implementation."""

    async def test_channel_text_continues_and_preserves_identity(
        self, engine: AssistantEngine
    ) -> None:
        first = await engine.receive(
            ChannelInput(target=NewConversation(), payload=TextChannelPayload(text="Hello")),
            reply=WholeTextReply(),
            timeout=_BUDGET,
        )
        assert first.channel is not None
        assert isinstance(first.result, TextChannelResult)
        assert first.channel.instance_id == first.result.outcome.conversation_id
        second = await engine.receive(
            ChannelInput(target=first.channel, payload=TextChannelPayload(text="Continue")),
            reply=WholeTextReply(),
            timeout=_BUDGET,
        )
        third = await engine.receive(
            ChannelInput(target=NewConversation(), payload=TextChannelPayload(text="Another")),
            reply=WholeTextReply(),
            timeout=_BUDGET,
        )
        assert second.channel == first.channel
        assert third.channel != first.channel

    async def test_channel_supplied_context_does_not_require_a_stored_transcript(
        self,
        engine: AssistantEngine,
    ) -> None:
        result = await engine.receive(
            ChannelInput(
                target=NewConversation(),
                payload=TextChannelPayload(text="Hello"),
                context=ChannelContext(
                    history=(ChannelContextItem(text="Source history", source="untrusted"),),
                    reply_to=ChannelContextItem(item_id="not-a-stored-turn", text="Quoted text"),
                ),
            ),
            reply=WholeTextReply(),
            timeout=_BUDGET,
        )
        assert isinstance(result.result, TextChannelResult)
        assert result.result.outcome.reference is None

    async def test_channel_stream_ends_in_its_authoritative_wrapper(
        self, engine: AssistantEngine
    ) -> None:
        stream = engine.receive_streaming(
            ChannelInput(target=NewConversation(), payload=TextChannelPayload(text="Hello")),
            reply=StreamingTextReply(),
            timeout=_BUDGET,
        )
        async with closing_stream(stream) as values:
            result = [value async for value in values]
        terminal = result[-1]
        assert isinstance(terminal, ChannelResult)
        assert isinstance(terminal.result, TextChannelResult)
        assert all(isinstance(value, ReplyChunk) for value in result[:-1])
        joined = "".join(value.text for value in result if isinstance(value, ReplyChunk))
        assert joined == (terminal.result.outcome.reply or "")

    async def test_channel_speech_and_text_share_identity(self, engine: AssistantEngine) -> None:
        text = await engine.converse("Hello", timeout=_BUDGET)
        assert text.conversation_id is not None
        identity = ChannelIdentity(channel_type="conversation", instance_id=text.conversation_id)
        result = await engine.receive(
            ChannelInput(
                target=identity,
                payload=SpeechChannelPayload(
                    audio=SpokenAudio(content="YXVkaW8=", media_type=SpokenAudioFormat.MP4),
                ),
            ),
            reply=SpokenReply(plays=(SpokenAudioFormat.MP4,)),
            timeout=_BUDGET,
        )
        assert result.channel == identity
        assert isinstance(result.result, SpokenChannelResult)
        assert result.result.outcome.heard is not None

    async def test_channel_event_returns_a_summary_and_creates_no_conversation(
        self,
        engine: AssistantEngine,
    ) -> None:
        before = await engine.recent_conversations()
        result = await engine.receive(event_input(), reply=None, timeout=_BUDGET)
        assert result.channel == event_input().target
        assert isinstance(result.result, InformationalEventResult)
        assert result.result.summary.strip()
        assert await engine.recent_conversations() == before

    @pytest.mark.parametrize("budget", [timedelta(0), timedelta(seconds=-1)])
    async def test_channel_event_nonpositive_budget_is_a_typed_failure(
        self,
        engine: AssistantEngine,
        budget: timedelta,
    ) -> None:
        with pytest.raises(ChannelProcessingTimeoutError):
            await engine.receive(event_input(), reply=None, timeout=budget)

    @pytest.mark.parametrize("kind", ["unknown", "conversation", "informational_event"])
    async def test_channel_unsupported_combinations_are_refused(
        self,
        engine: AssistantEngine,
        kind: str,
    ) -> None:
        supplied = ChannelInput(
            target=ChannelIdentity(channel_type=kind, instance_id="unused"),
            payload=TextChannelPayload(text="Hello"),
            conversation=ConversationInputOptions(),
        )
        with pytest.raises(ValueError, match="unsupported channel"):
            await engine.receive(supplied, reply=None, timeout=_BUDGET)

    async def test_channel_unknown_conversation_is_not_allocated(
        self, engine: AssistantEngine
    ) -> None:
        with pytest.raises(UnknownConversationError):
            await engine.receive(
                ChannelInput(
                    target=ChannelIdentity(channel_type="conversation", instance_id="absent"),
                    payload=TextChannelPayload(text="Hello"),
                ),
                reply=WholeTextReply(),
                timeout=_BUDGET,
            )
