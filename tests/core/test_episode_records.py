"""Intrinsic activation shape and canonical cursor rules from ADR-0275."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ai_assistant.core.episode_encoding import check_list, encode_cursor
from ai_assistant.core.types import (
    ChannelContext,
    ChannelIdentity,
    EpisodeCaptureReport,
    EpisodeCursor,
    EpisodePosition,
    EpisodeProcessingRecord,
    EpisodeResponseKind,
    EpisodicMemory,
    MemorySource,
    NewConversation,
    ProcessingReason,
    ProcessingStatus,
    Provenance,
    RecordedChannelTrigger,
    RecordedSpeechInput,
    RecordedTextInput,
    SpokenAudioFormat,
    SpokenReply,
)

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _processing(kind: EpisodeResponseKind) -> EpisodeProcessingRecord:
    return EpisodeProcessingRecord(
        activation_id="activation",
        started_at=_NOW,
        ended_at=_NOW,
        trigger=RecordedChannelTrigger(
            target=NewConversation(),
            channel=None,
            payload=RecordedSpeechInput(media_type=SpokenAudioFormat.WEBM_OPUS, transcript=None),
            context=ChannelContext(),
            conversation=None,
            reply=SpokenReply(plays=(SpokenAudioFormat.WEBM_OPUS,)),
        ),
        status=ProcessingStatus.FAILED,
        reason=ProcessingReason.TRANSCRIPTION_FAILED,
        response_kind=kind,
        model_eligible=False,
    )


@pytest.mark.parametrize("outcome", [None, "", "   "])
@pytest.mark.parametrize(
    "kind", [EpisodeResponseKind.CONVERSATION_REPLY, EpisodeResponseKind.INFORMATIONAL_SUMMARY]
)
def test_recorded_response_requires_nonblank_sole_outcome(
    outcome: str | None, kind: EpisodeResponseKind
) -> None:
    with pytest.raises(ValidationError, match="nonblank outcome"):
        EpisodicMemory(
            id="episode",
            content="input",
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_NOW),
            occurred_at=_NOW,
            processing_record=_processing(kind),
            outcome=outcome,
        )


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


def test_no_response_refuses_outcome() -> None:
    with pytest.raises(ValidationError, match="no outcome"):
        EpisodicMemory(
            id="episode",
            content="input",
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_NOW),
            occurred_at=_NOW,
            processing_record=_processing(EpisodeResponseKind.NONE),
            outcome="text",
        )


def test_recording_keeps_reversed_clock_and_exact_transcript_without_audio() -> None:
    data = _processing(EpisodeResponseKind.NONE).model_dump(mode="json")
    data["ended_at"] = "2025-12-31T23:59:59Z"
    data["trigger"]["payload"]["transcript"] = "  exact text\n"
    record = EpisodeProcessingRecord.model_validate(data)
    assert record.ended_at < record.started_at
    assert isinstance(record.trigger, RecordedChannelTrigger)
    assert isinstance(record.trigger.payload, RecordedSpeechInput)
    assert record.trigger.payload.transcript == "  exact text\n"
    data["trigger"]["payload"]["audio"] = "secret audio"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        EpisodeProcessingRecord.model_validate(data)


def test_recorded_event_refuses_conversational_reply_shape() -> None:
    channel = ChannelIdentity(channel_type="informational_event", instance_id="calendar")
    with pytest.raises(ValidationError, match="unsupported recorded channel"):
        RecordedChannelTrigger(
            target=channel,
            channel=channel,
            payload=RecordedTextInput(text=""),
            context=ChannelContext(),
            conversation=None,
            reply=SpokenReply(plays=(SpokenAudioFormat.WEBM_OPUS,)),
        )


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
