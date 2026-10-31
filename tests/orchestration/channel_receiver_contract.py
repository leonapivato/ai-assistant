"""Shared channel receiver behavior for engine, canonical fake, and wire client."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

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
    EpisodicMemory,
    InformationalEventResult,
    NewConversation,
    ProcessingReason,
    ProcessingStatus,
    RecordedChannelTrigger,
    RecordedTextInput,
    SpeechChannelPayload,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenReply,
    TextChannelPayload,
    UnderstandingOmission,
    UnderstandingProducer,
    parties_are_outside,
)

_BUDGET = timedelta(seconds=10)
_TEXT = TextChannelPayload(text="Hello")
_SPEECH = SpeechChannelPayload(
    audio=SpokenAudio(content="YXVkaW8=", media_type=SpokenAudioFormat.MP4)
)
_PLAYS = SpokenReply(plays=(SpokenAudioFormat.MP4,))


def _channel(kind: str) -> ChannelIdentity:
    return ChannelIdentity(channel_type=kind, instance_id="unused")


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
    assert episode.processing_record.schema_version == 12
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

    async def test_channel_event_returns_how_it_ended_and_creates_no_conversation(
        self,
        engine: AssistantEngine,
    ) -> None:
        """ADR-0313 §4:3-§4:4: an event returns how its activation ended, nothing it wrote."""
        before = await engine.recent_conversations()
        result = await engine.receive(event_input(), reply=None, timeout=_BUDGET)
        assert result.channel == event_input().target
        assert isinstance(result.result, InformationalEventResult)
        assert result.result.ended is ActivationEnding.DONE
        assert set(result.result.model_dump()) == {"kind", "ended"}
        assert await engine.recent_conversations() == before
        episode = await captured_episode(engine, result)
        processing = episode.processing_record
        assert processing is not None
        assert processing.status is ProcessingStatus.COMPLETED
        assert processing.reason is ProcessingReason.RETURNED
        assert isinstance(processing.trigger, RecordedChannelTrigger)
        assert processing.trigger.context == event_input().context
        assert isinstance(processing.trigger.payload, RecordedTextInput)
        assert processing.trigger.payload.text == "The thermostat entered eco mode at 18:00."
        assert parties_are_outside(processing.trigger.parties)

    @pytest.mark.parametrize("budget", [timedelta(0), timedelta(seconds=-1)])
    async def test_channel_event_whose_budget_runs_out_couldnt_finish(
        self,
        engine: AssistantEngine,
        budget: timedelta,
    ) -> None:
        """ADR-0313 §4:5: the timeout is the activation's budget, and running out is a result."""
        result = await engine.receive(event_input(), reply=None, timeout=budget)
        assert result.channel == event_input().target
        assert isinstance(result.result, InformationalEventResult)
        assert result.result.ended is ActivationEnding.COULDNT_FINISH
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

    @pytest.mark.parametrize(
        ("target", "payload", "reply"),
        [
            (_channel("unknown"), _TEXT, None),
            # ADR-0293 §11: the text conversational combination, whatever the reply.
            (_channel("conversation"), _TEXT, None),
            (NewConversation(), _TEXT, None),
            # ADR-0313 §3:2: the spoken conversational combination retired.
            (_channel("conversation"), _SPEECH, _PLAYS),
            (NewConversation(), _SPEECH, _PLAYS),
            # §4:1: an event is text with no reply, and nothing else.
            (_channel("informational_event"), _TEXT, _PLAYS),
            (_channel("informational_event"), _SPEECH, None),
        ],
        ids=[
            "unknown-text",
            "conversation-text",
            "new-conversation-text",
            "conversation-speech-spoken",
            "new-conversation-speech-spoken",
            "event-text-spoken",
            "event-speech",
        ],
    )
    async def test_channel_unsupported_combinations_are_refused(
        self,
        engine: AssistantEngine,
        target: ChannelIdentity | NewConversation,
        payload: TextChannelPayload | SpeechChannelPayload,
        reply: SpokenReply | None,
    ) -> None:
        """ADR-0313 §4:1: one combination is admitted, and any other is refused first.

        Refused before processing: no activation is captured and no conversation is
        created, the spoken conversational one included (§3:2).
        """
        conversations = await engine.recent_conversations()
        supplied = ChannelInput(target=target, payload=payload)
        with pytest.raises(ValueError, match="unsupported channel"):
            await engine.receive(supplied, reply=reply, timeout=_BUDGET)
        assert (await engine.episodes()).items == ()
        assert await engine.recent_conversations() == conversations

    def test_spoken_conversation_is_no_member(self, engine: AssistantEngine) -> None:
        """ADR-0313 §3:1: ``converse_spoken`` left the surface, on every implementation."""
        assert not hasattr(engine, "converse_spoken")
