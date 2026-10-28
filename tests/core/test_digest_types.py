"""ADR-0308 §7's types: a digest, its evidence, and the episode that keeps them.

What the episode records (``EvidenceItem``, ``DigestOutcome``, ``ActivationDigest``,
``EpisodeProcessingRecord.digests``), the appends ``episode_extends`` admits for them,
and what ``project_episode`` renders of them (§5:5 to §5:6, as ADR-0312 §4 confines
the placement to later readers).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ai_assistant.core.episode_encoding import episode_extends, project_episode
from ai_assistant.core.types import (
    ActivationDigest,
    ChannelContext,
    ControllerRule,
    ControllerStage,
    DigestOutcome,
    EpisodeProcessingRecord,
    EpisodeProjection,
    EpisodicMemory,
    EvidenceItem,
    MemorySource,
    NewConversation,
    Placement,
    PlacementReach,
    PlacementSetter,
    ProcessingReason,
    ProcessingStatus,
    ProjectedEvidence,
    ProjectedText,
    Provenance,
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

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_LATER = _NOW + timedelta(seconds=30)
_OWNER_ONLY = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=_NOW)


def _item(text: str = "the lower loop closes on the 15th", source: str = "R1") -> EvidenceItem:
    return EvidenceItem(text=text, source=source)


def _digest(
    result: str | None = "R1",
    *,
    outcome: DigestOutcome = DigestOutcome.ANSWERED,
    evidence: tuple[EvidenceItem, ...] = (),
    question: str = "when does the loop close",
) -> ActivationDigest:
    return ActivationDigest(
        result=result, question=question, outcome=outcome, evidence=evidence, recorded_at=_NOW
    )


def _open(**fields: object) -> EpisodeProcessingRecord:
    values: dict[str, object] = {
        "activation_id": "activation",
        "started_at": _NOW,
        "trigger": RecordedChannelTrigger(
            target=NewConversation(),
            channel=None,
            payload=RecordedTextInput(text="is the loop open?"),
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


def _episode(record: EpisodeProcessingRecord) -> EpisodicMemory:
    return EpisodicMemory(
        id="activation:activation",
        content="",
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_NOW),
        occurred_at=_NOW,
        processing_record=record,
        placement=_OWNER_ONLY,
    )


# --- the evidence item -----------------------------------------------------------------


def test_an_item_is_its_text_its_source_by_label_and_its_mark() -> None:
    item = _item()
    assert item.model_dump() == {
        "text": "the lower loop closes on the 15th",
        "source": "R1",
        "outside": True,
    }


def test_an_items_mark_is_always_set() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem.model_validate({"text": "t", "source": "R1", "outside": False})


@pytest.mark.parametrize("source", ["", "R0", "r1", "X1", "R01", "result:abc", " R1"])
def test_an_items_source_is_a_planning_label(source: str) -> None:
    with pytest.raises(ValidationError):
        _item(source=source)


def test_a_record_held_by_id_is_named_by_its_own_label() -> None:
    assert _item(source="M3").source == "M3"


@pytest.mark.parametrize("text", ["", "   "])
def test_an_item_says_something(text: str) -> None:
    with pytest.raises(ValidationError):
        _item(text=text)


def test_an_item_carries_nothing_more() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem.model_validate({"text": "t", "source": "R1", "question": "q"})


# --- the digest ---------------------------------------------------------------------------


def test_the_outcome_is_answered_or_failed() -> None:
    assert [member.value for member in DigestOutcome] == ["answered", "failed"]


def test_a_digest_that_answered_may_carry_no_evidence() -> None:
    """§4:8: "nothing here answers it" is a valid answer, an empty list."""
    assert _digest().evidence == ()


def test_a_failed_digest_records_no_evidence() -> None:
    with pytest.raises(ValidationError, match="records no evidence"):
        _digest(outcome=DigestOutcome.FAILED, evidence=(_item(),))


def test_recalls_digest_names_no_result() -> None:
    assert _digest(None, evidence=(_item(source="M1"),)).result is None


@pytest.mark.parametrize("result", ["M1", "S1", "R0", "result:abc", ""])
def test_a_digest_names_its_result_by_an_r_label(result: str) -> None:
    with pytest.raises(ValidationError, match="R label"):
        _digest(result)


def test_a_digest_states_its_question() -> None:
    with pytest.raises(ValidationError):
        _digest(question=" ")


# --- the record ---------------------------------------------------------------------------


def test_the_record_defaults_to_no_digests() -> None:
    assert _open().digests == ()


def test_a_record_with_digests_round_trips() -> None:
    record = _open(
        digests=(
            _digest(evidence=(_item(), _item("open until then", "R1"))),
            _digest("R2", outcome=DigestOutcome.FAILED),
        )
    )
    assert EpisodeProcessingRecord.model_validate_json(record.model_dump_json()) == record


def test_the_same_result_may_be_digested_again() -> None:
    """§6:7: a follow-up sends a held result to a digest answering a new question."""
    record = _open(digests=(_digest(), _digest(question="is it open on weekends")))
    assert len(record.digests) == 2


# --- episode_extends ----------------------------------------------------------------------


def _extends(before: EpisodeProcessingRecord, after: EpisodeProcessingRecord) -> bool:
    return episode_extends(_episode(before), _episode(after))


def test_a_digest_appended_extends() -> None:
    assert _extends(_open(), _open(digests=(_digest(),)))
    stored = _open(digests=(_digest(),))
    assert _extends(stored, _open(digests=(_digest(), _digest("R2"))))


def test_the_freezing_revision_keeps_the_digests() -> None:
    stored = _open(digests=(_digest(),))
    assert _extends(stored, _frozen(stored))


def test_a_recorded_digest_is_never_edited() -> None:
    stored = _open(digests=(_digest(evidence=(_item(),)),))
    assert not _extends(stored, _open(digests=(_digest(evidence=(_item("other"),)),)))


def test_a_recorded_digest_is_never_dropped() -> None:
    stored = _open(digests=(_digest(), _digest("R2")))
    assert not _extends(stored, _open(digests=(_digest(),)))


def test_a_digest_is_never_inserted_ahead_of_one_recorded() -> None:
    stored = _open(digests=(_digest("R2"),))
    assert not _extends(stored, _open(digests=(_digest(), _digest("R2"))))


# --- project_episode ----------------------------------------------------------------------


def _projected(*, owner_records: bool) -> EpisodeProjection:
    record = _frozen(
        _open(
            digests=(
                _digest(evidence=(_item("closes on the 15th"), _item("open daily"))),
                _digest("R2", outcome=DigestOutcome.FAILED),
                _digest(None, evidence=(_item("parks reopen in May", "M1"),)),
            )
        )
    )
    return project_episode(_episode(record), excerpt_chars=10, owner_records=owner_records)


def test_an_owner_reader_is_shown_each_items_text_and_mark_and_no_source() -> None:
    """§5:5: the text and the mark, never the label, which names nothing later."""
    assert _projected(owner_records=True).evidence == (
        ProjectedEvidence(text=ProjectedText(text="closes on ", full_chars=18)),
        ProjectedEvidence(text=ProjectedText(text="open daily", full_chars=10)),
        ProjectedEvidence(text=ProjectedText(text="parks reop", full_chars=19)),
    )
    assert "source" not in ProjectedEvidence.model_fields


def test_another_reader_is_shown_no_evidence() -> None:
    """§5:6: evidence is placed for the owner alone, as episode notes are."""
    assert _projected(owner_records=False).evidence == ()


def test_the_default_reader_keeps_the_owner_only_placement() -> None:
    """ADR-0312 §4:3: the placement governs every later reader."""
    record = _frozen(_open(digests=(_digest(evidence=(_item(),)),)))
    assert project_episode(_episode(record), excerpt_chars=50).evidence == ()


def test_a_projection_without_a_processing_record_carries_no_evidence() -> None:
    with pytest.raises(ValidationError, match="carries its content alone"):
        EpisodeProjection(
            occurred_at=_NOW,
            capture_modality=_episode(_open()).capture.modality,
            evidence=(ProjectedEvidence(text=ProjectedText(text="t", full_chars=1)),),
        )


def test_a_projected_items_mark_is_always_set() -> None:
    with pytest.raises(ValidationError):
        ProjectedEvidence.model_validate({"text": {"text": "t", "full_chars": 1}, "outside": False})
