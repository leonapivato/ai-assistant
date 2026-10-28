"""ADR-0308 §7:2 and ADR-0315 §5: the episode's processing record on the wire.

It carries recall's second run, and its planning rounds without the retired mark.

The record crosses the wire inside ``EpisodicMemory.processing_record``. These cases
send one through the codec's own projection and read it back, and hold the shape a
peer at the earlier protocol version would refuse.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    ActivationRecall,
    BeliefBand,
    ChannelContext,
    ControllerRule,
    ControllerStage,
    EpisodeProcessingRecord,
    EpisodicMemory,
    MemoryKind,
    MemorySource,
    NewConversation,
    PlanningRound,
    ProcessingReason,
    ProcessingStatus,
    ProposedCall,
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
from ai_assistant.testing.parties import (
    OWNERS_WORDS,
)
from ai_assistant.wire.codec import encode_projection, project

_AT: Final = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def _episode(
    second: ActivationRecall | None, rounds: tuple[PlanningRound, ...] = ()
) -> EpisodicMemory:
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
            parties=OWNERS_WORDS,
        ),
        status=ProcessingStatus.COMPLETED,
        reason=ProcessingReason.RETURNED,
        understanding_omitted=UnderstandingOmission.NOT_REACHED,
        stages=stages,
        recall=ActivationRecall(
            outcome=RecallOutcome.NOTHING_FOUND, cues=(RecallCue.ACTIVATION_INPUT,)
        ),
        recall_second_run=second,
        rounds=rounds,
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


def test_the_record_is_sent_at_schema_version_eleven_with_the_second_run_named_when_absent() -> (
    None
):
    """ADR-0124 §9:2: a peer at an earlier version refuses the version as unknown."""
    sent = _sent(_episode(None))
    processing = sent["processing_record"]
    assert isinstance(processing, dict)
    assert processing["schema_version"] == 11
    assert "recall_second_run" in processing
    assert processing["recall_second_run"] is None


_ROUNDS: Final = (
    PlanningRound(
        id="round:1",
        recorded_at=_AT,
        text="I'll note that.",
        calls=(ProposedCall(call_id="c1", name="note_story", arguments={"story": "S1"}),),
        notes="then tidy",
    ),
    PlanningRound(id="round:2", follows="round:1", recorded_at=_AT),
)


def test_the_rounds_round_trip_through_the_codec_without_the_mark() -> None:
    """ADR-0315 §5: a round carries its three parts and no mark, on the wire too."""
    episode = _episode(None, _ROUNDS)
    sent = _sent(episode)
    assert EpisodicMemory.model_validate(sent) == episode
    processing = sent["processing_record"]
    assert isinstance(processing, dict)
    rounds = processing["rounds"]
    assert isinstance(rounds, list)
    assert all("another_round" not in one for one in rounds)


def test_a_record_whose_round_carries_the_mark_does_not_validate() -> None:
    """ADR-0124 §9:2: a version-9 record's round, carrying the mark, is refused here."""
    sent = _sent(_episode(None, _ROUNDS))
    processing = sent["processing_record"]
    assert isinstance(processing, dict)
    rounds = processing["rounds"]
    assert isinstance(rounds, list)
    marked = {
        **sent,
        "processing_record": {
            **processing,
            "rounds": [{**rounds[0], "another_round": True}, *rounds[1:]],
        },
    }
    with pytest.raises(ValidationError, match="extra_forbidden"):
        EpisodicMemory.model_validate(marked)
