"""ADR-0308 §7:2: the episode's processing record carries recall's second run on the wire.

The record crosses the wire inside ``EpisodicMemory.processing_record``. These cases
send one through the codec's own projection and read it back, and hold the shape a
peer at the earlier protocol version would refuse.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Final

from ai_assistant.core.types import (
    ActivationRecall,
    BeliefBand,
    ChannelContext,
    ControllerRule,
    ControllerStage,
    EpisodeProcessingRecord,
    EpisodicMemory,
    InputOrigin,
    MemoryKind,
    MemorySource,
    NewConversation,
    ProcessingReason,
    ProcessingStatus,
    Provenance,
    RecallCue,
    RecalledItem,
    RecallOutcome,
    RecallProvenance,
    RecordedChannelTrigger,
    RecordedTextInput,
    StageEntry,
    StageOutcome,
    UnderstandingOmission,
    WholeTextReply,
)
from ai_assistant.wire.codec import encode_projection, project

_AT: Final = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def _episode(second: ActivationRecall | None) -> EpisodicMemory:
    stages = (
        StageEntry(
            stage=ControllerStage.RECALL,
            due=ControllerRule.UNDERSTOOD_NOT_RECALLED,
            started_at=_AT,
            ended_at=_AT,
            outcome=StageOutcome.DONE,
        ),
        StageEntry(
            stage=ControllerStage.END,
            due=ControllerRule.NOTHING_DUE,
            started_at=_AT,
            ended_at=_AT,
            outcome=StageOutcome.DONE,
        ),
    )
    record = EpisodeProcessingRecord(
        activation_id="a1",
        started_at=_AT,
        ended_at=_AT,
        trigger=RecordedChannelTrigger(
            target=NewConversation(),
            channel=None,
            payload=RecordedTextInput(text="when?"),
            context=ChannelContext(),
            reply=WholeTextReply(),
            origin=InputOrigin.USER,
        ),
        status=ProcessingStatus.COMPLETED,
        reason=ProcessingReason.RETURNED,
        understanding_omitted=UnderstandingOmission.NOT_REACHED,
        stages=stages,
        recall=ActivationRecall(
            outcome=RecallOutcome.NOTHING_FOUND, cues=(RecallCue.ACTIVATION_INPUT,)
        ),
        recall_second_run=second,
    )
    return EpisodicMemory(
        id="activation:a1",
        content="when?",
        occurred_at=_AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_AT),
        processing_record=record,
    )


_SECOND: Final = ActivationRecall(
    outcome=RecallOutcome.FOUND,
    cues=(RecallCue.UNDERSTOOD_MEANING, RecallCue.UNDERSTOOD_PHRASE),
    items=(
        RecalledItem(
            kind=MemoryKind.SEMANTIC,
            id="said",
            excerpt="the dentist is Dr Rao",
            provenance=RecallProvenance.USER,
            standing=BeliefBand.ASSERTED,
            rests_on_recorded_external_content=False,
            found_by=(RecallCue.UNDERSTOOD_MEANING, RecallCue.UNDERSTOOD_PHRASE),
        ),
    ),
)


def _sent(episode: EpisodicMemory) -> dict[str, object]:
    sent: dict[str, object] = json.loads(encode_projection(project(episode)))
    return sent


def test_the_second_run_round_trips_through_the_codec() -> None:
    episode = _episode(_SECOND)
    assert EpisodicMemory.model_validate(_sent(episode)) == episode


def test_the_record_is_sent_at_schema_version_nine_with_the_second_run_named_when_absent() -> None:
    """ADR-0124 §9:2: a peer at 94 refuses the field as extra and the version as unknown."""
    sent = _sent(_episode(None))
    processing = sent["processing_record"]
    assert isinstance(processing, dict)
    assert processing["schema_version"] == 9
    assert "recall_second_run" in processing
    assert processing["recall_second_run"] is None
