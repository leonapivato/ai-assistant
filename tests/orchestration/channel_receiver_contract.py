"""Shared channel receiver behavior for engine, canonical fake, and wire client."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

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
    EpisodeResponseKind,
    EpisodicMemory,
    InformationalEventResult,
    NewConversation,
    ProcessingReason,
    ProcessingStatus,
    RecordedChannelTrigger,
    RecordedSpeechInput,
    RecordedTextInput,
    ReplyChunk,
    SpeechChannelPayload,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenChannelResult,
    SpokenReply,
    StreamingTextReply,
    TextChannelPayload,
    TextChannelResult,
    UnderstandingOmission,
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


async def captured_episode(engine: AssistantEngine, result: ChannelResult) -> EpisodicMemory:
    """Read the receipt's complete record through the owner inspection surface."""
    receipt = result.capture
    assert receipt.state == "recorded"
    assert receipt.activation_id is not None
    assert str(UUID(receipt.activation_id)) == receipt.activation_id
    assert UUID(receipt.activation_id).version == 4
    assert receipt.episode_id is not None
    episode = await read_episode(engine, receipt.episode_id)
    assert episode.processing_record is not None
    assert episode.processing_record.activation_id == receipt.activation_id
    # ADR-0276 §8 step 2: every capture records that the understanding stage was not
    # reached, which is true of every pass until step 3 lands the stage.
    assert episode.processing_record.understanding == ()
    assert episode.processing_record.understanding_omitted is UnderstandingOmission.NOT_REACHED
    return episode


async def read_episode(engine: AssistantEngine, address: str) -> EpisodicMemory:
    """Collect the canonical immutable detail, including records beyond one chunk."""
    chunk = await engine.episode_chunk(address, max_bytes=311)
    assert chunk is not None
    version = chunk.version
    parts = [chunk.text]
    while chunk.next_offset is not None:
        chunk = await engine.episode_chunk(
            address, version=version, offset=chunk.next_offset, max_bytes=311
        )
        assert chunk is not None
        assert chunk.text
        parts.append(chunk.text)
    return EpisodicMemory.model_validate_json("".join(parts))


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
        episodes = [await captured_episode(engine, result) for result in (first, second, third)]
        assert len({episode.id for episode in episodes}) == 3
        assert (
            len(
                {
                    episode.processing_record.activation_id
                    for episode in episodes
                    if episode.processing_record is not None
                }
            )
            == 3
        )
        assert len((await engine.episodes()).items) == 3
        assert await read_episode(engine, episodes[0].id) == episodes[0]

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
        episode = await captured_episode(engine, result)
        processing = episode.processing_record
        assert processing is not None
        assert isinstance(processing.trigger, RecordedChannelTrigger)
        assert processing.trigger.context.history == (
            ChannelContextItem(text="Source history", source="untrusted"),
        )
        assert processing.trigger.context.reply_to == ChannelContextItem(
            item_id="not-a-stored-turn", text="Quoted text"
        )
        assert processing.trigger.channel == result.channel
        assert processing.links.predecessor_episode_id is None
        assert episode.outcome == result.result.outcome.reply
        assert processing.model_eligible

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
        episode = await captured_episode(engine, terminal)
        assert episode.outcome == terminal.result.outcome.reply
        assert len((await engine.episodes()).items) == 1

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
        episode = await captured_episode(engine, result)
        assert result.result.outcome.episode_id == episode.id
        processing = episode.processing_record
        assert processing is not None
        assert isinstance(processing.trigger, RecordedChannelTrigger)
        assert isinstance(processing.trigger.payload, RecordedSpeechInput)
        assert processing.trigger.payload.transcript == result.result.outcome.heard
        assert "audio" not in processing.trigger.payload.model_dump()
        assert len((await engine.episodes(channel=identity)).items) == 2

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
        episode = await captured_episode(engine, result)
        assert episode.outcome == result.result.summary
        processing = episode.processing_record
        assert processing is not None
        assert not processing.model_eligible
        assert processing.status is ProcessingStatus.COMPLETED
        assert processing.reason is ProcessingReason.RETURNED
        assert processing.response_kind is EpisodeResponseKind.INFORMATIONAL_SUMMARY
        assert isinstance(processing.trigger, RecordedChannelTrigger)
        assert processing.trigger.context == event_input().context
        assert isinstance(processing.trigger.payload, RecordedTextInput)
        assert processing.trigger.payload.text == "The thermostat entered eco mode at 18:00."
        assert episode.disposition is None

    @pytest.mark.parametrize("budget", [timedelta(0), timedelta(seconds=-1)])
    async def test_channel_event_nonpositive_budget_is_a_typed_failure(
        self,
        engine: AssistantEngine,
        budget: timedelta,
    ) -> None:
        with pytest.raises(ChannelProcessingTimeoutError):
            await engine.receive(event_input(), reply=None, timeout=budget)
        (summary,) = (await engine.episodes()).items
        episode = await read_episode(engine, summary.position.episode_id)
        assert episode.processing_record is not None
        assert episode.processing_record.status is ProcessingStatus.FAILED
        assert episode.processing_record.reason is ProcessingReason.TIMEOUT
        assert episode.outcome is None

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
        assert (await engine.episodes()).items == ()

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

    async def test_channel_exact_input_and_whole_conversation_deletion(
        self, engine: AssistantEngine
    ) -> None:
        supplied = ChannelInput(
            target=NewConversation(), payload=TextChannelPayload(text="  café\nexact input ")
        )
        first = await engine.receive(supplied, reply=WholeTextReply(), timeout=_BUDGET)
        assert first.channel is not None
        second = await engine.receive(
            supplied.model_copy(update={"target": first.channel}),
            reply=WholeTextReply(),
            timeout=_BUDGET,
        )
        event = await engine.receive(event_input(), reply=None, timeout=_BUDGET)
        episode = await captured_episode(engine, first)
        assert episode.processing_record is not None
        trigger = episode.processing_record.trigger
        assert isinstance(trigger, RecordedChannelTrigger)
        assert isinstance(trigger.payload, RecordedTextInput)
        assert trigger.payload.text == "  café\nexact input "
        assert await engine.forget_conversation(first.channel.instance_id)
        assert first.capture.episode_id is not None
        assert second.capture.episode_id is not None
        assert await engine.episode_chunk(first.capture.episode_id) is None
        assert await engine.episode_chunk(second.capture.episode_id) is None
        assert event.capture.episode_id is not None
        assert await engine.episode_chunk(event.capture.episode_id) is not None

    async def test_legacy_wrappers_each_record_once(self, engine: AssistantEngine) -> None:
        text = await engine.converse("legacy", timeout=_BUDGET)
        assert text.conversation_id is not None
        assert not text.capture_degraded
        stream = engine.converse_streaming(
            "stream", conversation_id=text.conversation_id, timeout=_BUDGET
        )
        async with closing_stream(stream) as values:
            streamed = [value async for value in values]
        assert streamed
        spoken = await engine.converse_spoken(
            SpokenAudio(content="YXVkaW8=", media_type=SpokenAudioFormat.MP4),
            plays=(SpokenAudioFormat.MP4,),
            timeout=_BUDGET,
            conversation_id=text.conversation_id,
        )
        assert spoken.episode_id is not None
        page = await engine.episodes(
            channel=ChannelIdentity(channel_type="conversation", instance_id=text.conversation_id)
        )
        assert len(page.items) == 3
        assert len({row.activation_id for row in page.items}) == 3
