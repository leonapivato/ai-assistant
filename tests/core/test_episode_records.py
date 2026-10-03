"""Intrinsic activation shape and canonical cursor rules from ADR-0275."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ai_assistant.core.episode_encoding import check_list, encode_cursor
from ai_assistant.core.types import (
    ChannelContext,
    ChannelIdentity,
    ControllerRule,
    ControllerStage,
    EpisodeCaptureReport,
    EpisodeCursor,
    EpisodePosition,
    EpisodeProcessingRecord,
    EpisodicMemory,
    InputOrigin,
    MemorySource,
    NewConversation,
    ProcessingReason,
    ProcessingStatus,
    Provenance,
    RecordedChannelTrigger,
    RecordedResumeTrigger,
    RecordedSpeechInput,
    RecordedTextInput,
    SpokenAudioFormat,
    SpokenReply,
    UnderstandingOmission,
)
from ai_assistant.testing.activation import ended_pass

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _processing() -> EpisodeProcessingRecord:
    return EpisodeProcessingRecord(
        activation_id="activation",
        started_at=_NOW,
        ended_at=_NOW,
        trigger=RecordedChannelTrigger(
            target=NewConversation(),
            channel=None,
            payload=RecordedSpeechInput(media_type=SpokenAudioFormat.WEBM_OPUS, transcript=None),
            context=ChannelContext(),
            reply=SpokenReply(plays=(SpokenAudioFormat.WEBM_OPUS,)),
            origin=InputOrigin.USER,
        ),
        status=ProcessingStatus.FAILED,
        reason=ProcessingReason.TRANSCRIPTION_FAILED,
        understanding_omitted=UnderstandingOmission.NOT_REACHED,
        stages=ended_pass(_NOW, ControllerRule.NO_TEXT_INPUT),
    )


@pytest.mark.parametrize("outcome", ["", "   "])
def test_recorded_response_requires_nonblank_sole_outcome(outcome: str) -> None:
    """ADR-0284 §4:1: the response is nonblank text, or there is none."""
    with pytest.raises(ValidationError, match="nonblank outcome"):
        EpisodicMemory(
            id="episode",
            content="input",
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_NOW),
            occurred_at=_NOW,
            processing_record=_processing(),
            outcome=outcome,
        )


@pytest.mark.parametrize("outcome", [None, "the reply"])
def test_a_processing_record_episode_has_a_response_or_none(outcome: str | None) -> None:
    """ADR-0284 §4:1: ``outcome`` is the response, or ``None`` where none was sent."""
    record = EpisodicMemory(
        id="episode",
        content="input",
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_NOW),
        occurred_at=_NOW,
        processing_record=_processing(),
        outcome=outcome,
    )
    assert record.outcome == outcome


@pytest.mark.parametrize(
    "removed",
    [
        {"response_kind": "conversation_reply"},
        {"model_eligible": True},
        {"reply_degraded": False},
        {"spoken_degraded": False},
    ],
)
def test_the_removed_record_fields_are_refused(removed: dict[str, object]) -> None:
    """ADR-0284 §4, §6: the schema-5 record carries none of the removed fields."""
    data = {**_processing().model_dump(mode="json"), **removed}
    with pytest.raises(ValidationError, match="extra_forbidden"):
        EpisodeProcessingRecord.model_validate(data)


def test_the_episode_carries_no_disposition() -> None:
    """ADR-0284 §5:3: the verdict is on the stage entry, never on the episode."""
    record = EpisodicMemory(
        id="episode",
        content="input",
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_NOW),
        occurred_at=_NOW,
        processing_record=_processing(),
    )
    assert "disposition" not in EpisodicMemory.model_fields
    assert "disposition" not in record.model_dump(mode="json")


def test_the_record_is_schema_version_six() -> None:
    """ADR-0286 §13: ``schema_version`` is ``Literal[6]``; an earlier one is refused."""
    data = _processing().model_dump(mode="json")
    assert data["schema_version"] == 6
    with pytest.raises(ValidationError, match="literal_error"):
        EpisodeProcessingRecord.model_validate({**data, "schema_version": 5})


def test_absent_processing_retains_other_producer_outcomes() -> None:
    record = EpisodicMemory(
        id="episode",
        content="input",
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_NOW),
        occurred_at=_NOW,
        outcome="",
    )
    assert record.processing_record is None
    assert record.outcome == ""


def test_recording_keeps_reversed_clock_and_exact_transcript_without_audio() -> None:
    data = _processing().model_dump(mode="json")
    data["ended_at"] = "2025-12-31T23:59:59Z"
    data["trigger"]["payload"]["transcript"] = "  exact text\n"
    record = EpisodeProcessingRecord.model_validate(data)
    assert record.ended_at is not None
    assert record.ended_at < record.started_at
    assert isinstance(record.trigger, RecordedChannelTrigger)
    assert isinstance(record.trigger.payload, RecordedSpeechInput)
    assert record.trigger.payload.transcript == "  exact text\n"
    data["trigger"]["payload"]["audio"] = "secret audio"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        EpisodeProcessingRecord.model_validate(data)


def test_the_trigger_checks_no_combination_per_channel_type() -> None:
    """ADR-0284 §3:2: admission's dispatch table is the one place that checks it.

    A recorded event trigger carrying a spoken reply shape is a combination admission
    refuses (``core/channel_validation.py``); the recorded trigger itself does not.
    """
    channel = ChannelIdentity(channel_type="informational_event", instance_id="calendar")
    trigger = RecordedChannelTrigger(
        target=channel,
        channel=channel,
        payload=RecordedTextInput(text=""),
        context=ChannelContext(),
        reply=SpokenReply(plays=(SpokenAudioFormat.WEBM_OPUS,)),
        origin=InputOrigin.OUTSIDE,
    )
    assert trigger.channel == channel


def test_the_trigger_holds_its_channel_to_its_target() -> None:
    """ADR-0284 §3:2: where the target names a channel and ``channel`` is set, they agree."""
    target = ChannelIdentity(channel_type="conversation", instance_id="one")
    with pytest.raises(ValidationError, match="channel is its target"):
        RecordedChannelTrigger(
            target=target,
            channel=ChannelIdentity(channel_type="conversation", instance_id="two"),
            payload=RecordedTextInput(text="hello"),
            context=ChannelContext(),
            reply=None,
            origin=InputOrigin.USER,
        )
    resolved = RecordedChannelTrigger(
        target=NewConversation(),
        channel=target,
        payload=RecordedTextInput(text="hello"),
        context=ChannelContext(),
        reply=None,
        origin=InputOrigin.USER,
    )
    assert resolved.channel == target


def test_the_trigger_requires_its_origin_and_carries_no_conversation_options() -> None:
    """ADR-0284 §2:1 and §3:1: ``origin`` is required, and ``conversation`` is gone."""
    data = _processing().trigger.model_dump(mode="json")
    del data["origin"]
    with pytest.raises(ValidationError, match="missing"):
        RecordedChannelTrigger.model_validate(data)
    with pytest.raises(ValidationError, match="extra_forbidden"):
        RecordedChannelTrigger.model_validate(
            {**_processing().trigger.model_dump(mode="json"), "conversation": None}
        )


def test_a_resume_records_its_stages() -> None:
    """ADR-0284 §5:4-§5:5: a stageless resume is refused; one end entry, last, admits it."""
    resume = _processing().model_copy(
        update={
            "trigger": RecordedResumeTrigger(channel=None, approved=True),
            "understanding_omitted": UnderstandingOmission.NO_INPUT,
        }
    )
    data = resume.model_dump(mode="json")
    with pytest.raises(ValidationError, match="exactly one end entry"):
        EpisodeProcessingRecord.model_validate({**data, "stages": []})
    admitted = EpisodeProcessingRecord.model_validate(data)
    assert [entry.stage for entry in admitted.stages] == [ControllerStage.END]


def test_recorded_capture_requires_both_addresses() -> None:
    with pytest.raises(ValidationError, match="requires both"):
        EpisodeCaptureReport(activation_id=None, episode_id="episode", state="recorded")


def test_cursor_rejects_unknown_version_and_noncanonical_spelling() -> None:
    cursor = EpisodeCursor(
        after=EpisodePosition(occurred_at=_NOW, episode_id=""), channel=None, status=None
    )
    spelling = encode_cursor(cursor)
    assert check_list(None, None, spelling, 1)[2] == cursor
    with pytest.raises(ValueError, match="cursor"):
        check_list(None, None, spelling + "=", 1)
    with pytest.raises(ValidationError, match="literal_error"):
        EpisodeCursor.model_validate({**cursor.model_dump(), "schema_version": 2})
