"""Shared channel receiver behavior for engine, canonical fake, and wire client."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

from ai_assistant.core.errors import ChannelProcessingTimeoutError, UnknownConversationError

if TYPE_CHECKING:
    from ai_assistant.core.protocols import AssistantEngine
from ai_assistant.core.types import (
    ActivationEnding,
    ActivationStop,
    ChannelContext,
    ChannelContextItem,
    ChannelIdentity,
    ChannelInput,
    ChannelResult,
    ControllerStage,
    ConversationInputOptions,
    EpisodicMemory,
    InformationalEventResult,
    InputOrigin,
    NewConversation,
    ProcessingReason,
    ProcessingStatus,
    RecordedChannelTrigger,
    RecordedSpeechInput,
    RecordedTextInput,
    SpeechChannelPayload,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenChannelResult,
    SpokenReply,
    StreamingTextReply,
    TextChannelPayload,
    UnderstandingOmission,
    UnderstandingProducer,
    WholeTextReply,
)

_BUDGET = timedelta(seconds=10)


#: A recording the fake and the engine's scripted transcriber both hear words in.
_RECORDING = SpokenAudio(content="YXVkaW8=", media_type=SpokenAudioFormat.MP4)
_PLAYS = SpokenReply(plays=(SpokenAudioFormat.MP4,))


def speech_input(
    target: ChannelIdentity | NewConversation | None = None,
    *,
    context: ChannelContext | None = None,
) -> ChannelInput:
    """A spoken input to a conversation, the one conversational combination ``receive`` keeps.

    ADR-0293 §11 takes the text conversational combination off the surface, so a clause
    about how ``receive`` admits and records a conversation's input is held over speech.
    """
    return ChannelInput(
        target=NewConversation() if target is None else target,
        payload=SpeechChannelPayload(audio=_RECORDING),
        context=ChannelContext() if context is None else context,
    )


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
    # ADR-0276 §5, §7: every pass this suite captures through here reaches the
    # understanding stage, which is entered once and records exactly one version — 1,
    # by the one producer — carried to capture with no omission beside it.
    processing = episode.processing_record
    assert processing.understanding_omitted is None
    assert [version.version for version in processing.understanding] == [1]
    assert processing.understanding[0].producer is UnderstandingProducer.INTERPRETATION
    assert processing.understanding_elided == 0
    assert_a_channel_stage_record(episode)
    return episode


def assert_a_channel_stage_record(episode: EpisodicMemory) -> None:
    """ADR-0280 §7: a channel pass's record ends in exactly one ``end`` entry, last."""
    assert episode.processing_record is not None
    assert episode.processing_record.schema_version == 6
    stages = [entry.stage for entry in episode.processing_record.stages]
    assert stages
    assert stages[-1] is ControllerStage.END
    assert ControllerStage.END not in stages[:-1]


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

    async def test_channel_speech_continues_and_preserves_identity(
        self, engine: AssistantEngine
    ) -> None:
        first = await engine.receive(speech_input(), reply=_PLAYS, timeout=_BUDGET)
        assert first.channel is not None
        assert isinstance(first.result, SpokenChannelResult)
        assert first.result.outcome.outcome is not None
        assert first.channel.instance_id == first.result.outcome.outcome.conversation_id
        second = await engine.receive(speech_input(first.channel), reply=_PLAYS, timeout=_BUDGET)
        third = await engine.receive(speech_input(), reply=_PLAYS, timeout=_BUDGET)
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

    async def test_a_stop_naming_an_ended_activation_answers_already_ended(
        self, engine: AssistantEngine
    ) -> None:
        """ADR-0297 §5:4: its episode stands at its address, and nothing is written."""
        result = await engine.receive(speech_input(), reply=_PLAYS, timeout=_BUDGET)
        before = await captured_episode(engine, result)
        assert result.capture.activation_id is not None

        answer = await engine.stop_activation(result.capture.activation_id)

        assert answer is ActivationStop.ALREADY_ENDED
        after = await read_episode(engine, before.id)
        assert after == before
        assert after.processing_record is not None
        assert after.processing_record.reason is not ProcessingReason.STOPPED
        assert result.channel is not None
        digest = await engine.conversation(result.channel.instance_id)
        assert digest is not None
        assert digest.state.last_ended is ActivationEnding.DONE

    async def test_a_stop_naming_no_activation_answers_no_such_activation(
        self, engine: AssistantEngine
    ) -> None:
        """ADR-0297 §5:5: nothing running, no episode at its address, nothing written."""
        before = await engine.episodes()

        answer = await engine.stop_activation(str(uuid4()))

        assert answer is ActivationStop.NO_SUCH_ACTIVATION
        assert await engine.episodes() == before

    async def test_a_stop_naming_no_identifier_is_refused(self, engine: AssistantEngine) -> None:
        """An activation id is an identifier, refused before anything is read."""
        with pytest.raises(ValueError, match="activation_id"):
            await engine.stop_activation("  ")

    async def test_channel_supplied_context_does_not_require_a_stored_transcript(
        self,
        engine: AssistantEngine,
    ) -> None:
        result = await engine.receive(
            speech_input(
                context=ChannelContext(
                    history=(ChannelContextItem(text="Source history", source="untrusted"),),
                    reply_to=ChannelContextItem(item_id="not-a-stored-turn", text="Quoted text"),
                ),
            ),
            reply=_PLAYS,
            timeout=_BUDGET,
        )
        assert isinstance(result.result, SpokenChannelResult)
        spoken = result.result.outcome.outcome
        assert spoken is not None
        assert spoken.reference is None
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
        assert episode.outcome == spoken.reply
        assert processing.trigger.origin is InputOrigin.USER

    async def test_channel_speech_and_text_share_identity(self, engine: AssistantEngine) -> None:
        text = await engine.converse("Hello", timeout=_BUDGET)
        assert text.conversation_id is not None
        identity = ChannelIdentity(channel_type="conversation", instance_id=text.conversation_id)
        result = await engine.receive(speech_input(identity), reply=_PLAYS, timeout=_BUDGET)
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
        assert processing.status is ProcessingStatus.COMPLETED
        assert processing.reason is ProcessingReason.RETURNED
        assert isinstance(processing.trigger, RecordedChannelTrigger)
        assert processing.trigger.context == event_input().context
        assert isinstance(processing.trigger.payload, RecordedTextInput)
        assert processing.trigger.payload.text == "The thermostat entered eco mode at 18:00."
        assert processing.trigger.origin is InputOrigin.OUTSIDE

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
        # ADR-0276 §5: a deadline that expired ahead of the stage is `not_reached`,
        # which is neither a failed understanding nor a branch the pass took.
        assert episode.processing_record.understanding == ()
        assert episode.processing_record.understanding_omitted is UnderstandingOmission.NOT_REACHED
        assert_a_channel_stage_record(episode)
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

    @pytest.mark.parametrize("reply", [WholeTextReply(), StreamingTextReply()])
    @pytest.mark.parametrize("fresh", [True, False])
    async def test_channel_text_conversation_is_refused_and_starts_nothing(
        self, engine: AssistantEngine, reply: WholeTextReply | StreamingTextReply, fresh: bool
    ) -> None:
        """ADR-0293 §11: the text conversational combination is off the surface.

        A typed message is written into a conversation as an act in the medium, so
        ``receive`` refuses one before any work — whichever reply it offers, and whether
        it names a conversation or asks for a new one — and nothing is recorded.
        """
        held = await engine.converse("Hello", timeout=_BUDGET)
        assert held.conversation_id is not None
        before = await engine.episodes()
        target = (
            NewConversation()
            if fresh
            else ChannelIdentity(channel_type="conversation", instance_id=held.conversation_id)
        )
        supplied = ChannelInput(target=target, payload=TextChannelPayload(text="Hello"))
        with pytest.raises(ValueError, match="unsupported channel"):
            await engine.receive(supplied, reply=reply, timeout=_BUDGET)  # type: ignore[arg-type]  # the refused combination, on purpose
        assert await engine.episodes() == before

    async def test_channel_unknown_conversation_is_not_allocated(
        self, engine: AssistantEngine
    ) -> None:
        with pytest.raises(UnknownConversationError):
            await engine.receive(
                speech_input(ChannelIdentity(channel_type="conversation", instance_id="absent")),
                reply=_PLAYS,
                timeout=_BUDGET,
            )

    async def test_channel_exact_input_and_whole_conversation_deletion(
        self, engine: AssistantEngine
    ) -> None:
        first = await engine.converse("  café\nexact input ", timeout=_BUDGET)
        assert first.conversation_id is not None
        await engine.converse(
            "  café\nexact input ", timeout=_BUDGET, conversation_id=first.conversation_id
        )
        event = await engine.receive(event_input(), reply=None, timeout=_BUDGET)
        channel = ChannelIdentity(channel_type="conversation", instance_id=first.conversation_id)
        typed = (await engine.episodes(channel=channel)).items
        assert len(typed) == 2
        episode = await read_episode(engine, typed[-1].position.episode_id)
        assert episode.processing_record is not None
        trigger = episode.processing_record.trigger
        assert isinstance(trigger, RecordedChannelTrigger)
        assert isinstance(trigger.payload, RecordedTextInput)
        assert trigger.payload.text == "  café\nexact input "
        assert await engine.forget_conversation(first.conversation_id)
        for row in typed:
            assert await engine.episode_chunk(row.position.episode_id) is None
        assert event.capture.episode_id is not None
        assert await engine.episode_chunk(event.capture.episode_id) is not None

    async def test_legacy_wrappers_each_record_once(self, engine: AssistantEngine) -> None:
        text = await engine.converse("legacy", timeout=_BUDGET)
        assert text.conversation_id is not None
        assert not text.capture_degraded
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
        assert len(page.items) == 2
        assert len({row.activation_id for row in page.items}) == 2
