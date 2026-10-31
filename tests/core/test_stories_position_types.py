"""ADR-0347 §4:1: the story store's position, as the episode's processing record keeps it.

The record's ``stories_position`` field, defaulted so a record written before it
validates unchanged, and what ``episode_extends`` admits for it: nothing. The admission
write sets it with the record's first write (ADR-0286 §2:1), so no later revision sets,
changes or clears it, the freeze included.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ai_assistant.core.episode_encoding import episode_extends
from ai_assistant.core.types import (
    ChannelContext,
    ControllerRule,
    ControllerStage,
    EpisodeProcessingRecord,
    EpisodicMemory,
    MemorySource,
    NewConversation,
    Placement,
    PlacementReach,
    PlacementSetter,
    ProcessingReason,
    ProcessingStatus,
    Provenance,
    RecordedChannelTrigger,
    RecordedTextInput,
    StageEntry,
    StageOutcome,
    UnderstandingOmission,
    WholeTextReply,
    check_story_version,
)
from ai_assistant.testing.parties import (
    OWNERS_WORDS,
)

_NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)
_LATER = _NOW + timedelta(seconds=30)
_OWNER_ONLY = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=_NOW)


def _open(**fields: object) -> EpisodeProcessingRecord:
    values: dict[str, object] = {
        "activation_id": "activation",
        "started_at": _NOW,
        "trigger": RecordedChannelTrigger(
            target=NewConversation(),
            channel=None,
            payload=RecordedTextInput(text="how is the camping trip going"),
            context=ChannelContext(),
            reply=WholeTextReply(),
            parties=OWNERS_WORDS,
        ),
    }
    values.update(fields)
    return EpisodeProcessingRecord.model_validate(values)


def _frozen(record: EpisodeProcessingRecord) -> EpisodeProcessingRecord:
    end = StageEntry(
        stage=ControllerStage.END,
        due=ControllerRule.NOTHING_DUE,
        started_at=_LATER,
        ended_at=_LATER,
        outcome=StageOutcome.DONE,
    )
    return EpisodeProcessingRecord.model_validate(
        {
            **dict(record),
            "status": ProcessingStatus.COMPLETED,
            "reason": ProcessingReason.RETURNED,
            "ended_at": _LATER,
            "stages": (*record.stages, end),
            "understanding_omitted": UnderstandingOmission.NOT_REACHED,
        }
    )


def _extends(before: EpisodeProcessingRecord, after: EpisodeProcessingRecord) -> bool:
    def episode(record: EpisodeProcessingRecord) -> EpisodicMemory:
        return EpisodicMemory(
            id="activation:activation",
            content="",
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_NOW),
            occurred_at=_NOW,
            processing_record=record,
            placement=_OWNER_ONLY,
        )

    return episode_extends(episode(before), episode(after))


# --- the record ---------------------------------------------------------------------------


def test_a_record_written_before_the_field_validates_unchanged() -> None:
    """§4:1: no position by default, and ``schema_version`` does not move."""
    record = _open()
    assert record.stories_position is None
    assert record.schema_version == 12
    assert "stories_position" not in record.model_dump(exclude_defaults=True)
    stored = record.model_dump(mode="json")
    del stored["stories_position"]
    assert EpisodeProcessingRecord.model_validate(stored) == record


@pytest.mark.parametrize("position", [0, 17, 2**63 - 1])
def test_a_record_with_a_position_round_trips(position: int) -> None:
    record = _open(stories_position=position)
    assert EpisodeProcessingRecord.model_validate_json(record.model_dump_json()) == record
    assert _frozen(record).stories_position == position


@pytest.mark.parametrize("position", [-1, 2**63, True, 1.5, "3"])
def test_a_position_no_story_store_could_report_is_refused(position: object) -> None:
    with pytest.raises(ValidationError):
        _open(stories_position=position)


# --- episode_extends ----------------------------------------------------------------------


def test_the_freezing_revision_keeps_the_position() -> None:
    stored = _open(stories_position=5)
    assert _extends(stored, _frozen(stored))


def test_no_revision_sets_changes_or_clears_the_position() -> None:
    """ADR-0286 §3, as §4:1 adds to §2:1: the admission write's value stands."""
    assert not _extends(_open(), _frozen(_open(stories_position=5)))
    assert not _extends(_open(stories_position=5), _frozen(_open(stories_position=6)))
    assert not _extends(_open(stories_position=5), _frozen(_open()))


# --- the version argument ------------------------------------------------------------------


@pytest.mark.parametrize("version", [1, 2**63 - 1])
def test_a_version_any_log_could_hold_is_returned(version: int) -> None:
    assert check_story_version(version) == version


@pytest.mark.parametrize("version", [0, -1, 2**63, True, 1.0, "1", None])
def test_a_version_no_log_could_hold_is_a_value_error(version: object) -> None:
    with pytest.raises(ValueError, match="version"):
        check_story_version(version)
