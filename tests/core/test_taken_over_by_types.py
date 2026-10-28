"""ADR-0352 §5:2, §6:5, §6:6: who took a handed-over activation's matter, on its record.

The processing record's ``taken_over_by`` field, defaulted so a record written before it
validates unchanged, carried only by a record frozen ``stopped`` and never naming the
record's own activation; and what ``episode_extends`` admits for it: a value in the
revision that freezes the record, and in no other.
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
    InputOrigin,
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
)
from ai_assistant.testing.parties import parties_for

_NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
_LATER = _NOW + timedelta(seconds=30)
_OWNER_ONLY = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=_NOW)

#: The activation whose record these cases build, and the one that took its matter.
_OWN = "act-absorbed"
_TAKER = "act-absorber"


def _open(**fields: object) -> EpisodeProcessingRecord:
    values: dict[str, object] = {
        "activation_id": _OWN,
        "started_at": _NOW,
        "trigger": RecordedChannelTrigger(
            target=NewConversation(),
            channel=None,
            payload=RecordedTextInput(text="book Riverside for Friday"),
            context=ChannelContext(),
            reply=WholeTextReply(),
            parties=parties_for(InputOrigin.USER),
        ),
    }
    values.update(fields)
    return EpisodeProcessingRecord.model_validate(values)


def _frozen(
    record: EpisodeProcessingRecord,
    *,
    reason: ProcessingReason = ProcessingReason.STOPPED,
    **fields: object,
) -> EpisodeProcessingRecord:
    """``record`` frozen with ``reason``, its end entry the one that reason pairs with."""
    status, rule = {
        ProcessingReason.STOPPED: (ProcessingStatus.INTERRUPTED, ControllerRule.STOPPED),
        ProcessingReason.HUB_STOPPED: (ProcessingStatus.INTERRUPTED, ControllerRule.HUB_STOPPED),
        ProcessingReason.CANCELLED: (ProcessingStatus.INTERRUPTED, ControllerRule.NOTHING_DUE),
        ProcessingReason.RETURNED: (ProcessingStatus.COMPLETED, ControllerRule.NOTHING_DUE),
    }[reason]
    end = StageEntry(
        stage=ControllerStage.END,
        due=rule,
        started_at=_LATER,
        ended_at=_LATER,
        outcome=StageOutcome.DONE,
    )
    return EpisodeProcessingRecord.model_validate(
        {
            **dict(record),
            "status": status,
            "reason": reason,
            "ended_at": _LATER,
            "stages": (*record.stages, end),
            "understanding_omitted": UnderstandingOmission.NOT_REACHED,
            **fields,
        }
    )


def _episode(record: EpisodeProcessingRecord) -> EpisodicMemory:
    return EpisodicMemory(
        id=f"activation:{_OWN}",
        content="",
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_NOW),
        occurred_at=_NOW,
        processing_record=record,
        placement=_OWNER_ONLY,
    )


def _extends(before: EpisodeProcessingRecord, after: EpisodeProcessingRecord) -> bool:
    return episode_extends(_episode(before), _episode(after))


# --- the record ---------------------------------------------------------------------------


def test_a_record_written_before_the_field_validates_unchanged() -> None:
    """§6:5: nobody by default, and ``schema_version`` does not move."""
    for record in (_open(), _frozen(_open())):
        assert record.taken_over_by is None
        assert record.schema_version == 11
        assert "taken_over_by" not in record.model_dump(exclude_defaults=True)
        stored = record.model_dump(mode="json")
        del stored["taken_over_by"]
        assert EpisodeProcessingRecord.model_validate(stored) == record


def test_a_record_frozen_stopped_names_the_activation_that_took_its_matter() -> None:
    """§5:2: the one that absorbed it, or took its input, read back as written."""
    record = _frozen(_open(), taken_over_by=_TAKER)
    assert record.taken_over_by == _TAKER
    assert EpisodeProcessingRecord.model_validate_json(record.model_dump_json()) == record


def test_an_open_record_names_nobody() -> None:
    """§6:5: only a frozen record carries one; a hand-over is recorded as it freezes."""
    with pytest.raises(ValidationError, match="frozen stopped"):
        _open(taken_over_by=_TAKER)


@pytest.mark.parametrize(
    "reason",
    [ProcessingReason.RETURNED, ProcessingReason.CANCELLED, ProcessingReason.HUB_STOPPED],
)
def test_a_record_frozen_for_another_reason_names_nobody(reason: ProcessingReason) -> None:
    """§6:5, §5:2: a hand-over is a stop, and a restart's close records nobody."""
    with pytest.raises(ValidationError, match="frozen stopped"):
        _frozen(_open(), reason=reason, taken_over_by=_TAKER)


def test_a_record_never_names_its_own_activation() -> None:
    """§6:5: the activation that took the matter is always another."""
    with pytest.raises(ValidationError, match="its own activation"):
        _frozen(_open(), taken_over_by=_OWN)


@pytest.mark.parametrize("taker", ["", "   ", 7])
def test_a_name_no_activation_could_have_is_refused(taker: object) -> None:
    """§6:5: the field is an ``Identifier``, as every activation's is."""
    with pytest.raises(ValidationError):
        _frozen(_open(), taken_over_by=taker)


# --- episode_extends ----------------------------------------------------------------------


def test_the_freezing_revision_may_name_who_took_the_matter() -> None:
    """§6:6: the revision that freezes the record sets it."""
    stored = _open()
    assert _extends(stored, _frozen(stored, taken_over_by=_TAKER))


def test_the_freezing_revision_may_leave_it_unset() -> None:
    """A stop that was no hand-over freezes the record naming nobody."""
    stored = _open()
    assert _extends(stored, _frozen(stored))


def test_no_revision_of_a_frozen_record_sets_or_changes_it() -> None:
    """§6:6, ADR-0286 §3: a frozen record is immutable, the field included."""
    unnamed = _frozen(_open())
    named = _frozen(_open(), taken_over_by=_TAKER)
    assert not _extends(unnamed, named)
    assert not _extends(named, _frozen(_open(), taken_over_by="act-other"))
    assert not _extends(named, unnamed)
