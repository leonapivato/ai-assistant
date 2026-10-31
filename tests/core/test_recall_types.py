"""The recall types and the additive record field of ADR-0281 §2, §6 and §7."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    RECALLED_ITEMS_MAX,
    UNDERSTANDING_REFERENT_EXCERPT_CHARS,
    ActivationRecall,
    Attestation,
    BeliefBand,
    ChannelContext,
    ControllerRule,
    ControllerStage,
    EpisodeProcessingRecord,
    MemoryKind,
    NewConversation,
    ProcessingReason,
    ProcessingStatus,
    RecallCue,
    RecalledItem,
    RecallOutcome,
    RecallProvenance,
    RecordedChannelTrigger,
    RecordedTextInput,
    StageEntry,
    StageOutcome,
    UnderstandingOmission,
    UnderstandingReferent,
    WholeTextReply,
)
from ai_assistant.testing.parties import (
    OWNERS_WORDS,
)

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_LATER = _NOW + timedelta(seconds=1)


def _item(**overrides: object) -> RecalledItem:
    fields: dict[str, object] = {
        "kind": MemoryKind.MEMORY,
        "id": "memory-1",
        "excerpt": "The dentist is Dr Rao on Elm Street.",
        "provenance": RecallProvenance.USER,
        "standing": BeliefBand.ASSERTED,
        "rests_on_recorded_external_content": False,
        "found_by": (RecallCue.ACTIVATION_INPUT,),
    }
    fields.update(overrides)
    return RecalledItem.model_validate(fields)


def _recall(**overrides: object) -> ActivationRecall:
    fields: dict[str, object] = {
        "outcome": RecallOutcome.FOUND,
        "cues": (RecallCue.ACTIVATION_INPUT,),
        "items": (_item(),),
    }
    fields.update(overrides)
    return ActivationRecall.model_validate(fields)


def _record(**overrides: object) -> EpisodeProcessingRecord:
    fields: dict[str, object] = {
        "activation_id": "activation",
        "started_at": _NOW,
        "ended_at": _LATER,
        "trigger": RecordedChannelTrigger(
            target=NewConversation(),
            channel=None,
            payload=RecordedTextInput(text="book the dentist"),
            context=ChannelContext(),
            reply=WholeTextReply(),
            parties=OWNERS_WORDS,
        ),
        "status": ProcessingStatus.COMPLETED,
        "reason": ProcessingReason.RETURNED,
        "understanding_omitted": UnderstandingOmission.NOT_REACHED,
        "stages": (
            StageEntry(
                stage=ControllerStage.END,
                due=ControllerRule.NOTHING_DUE,
                started_at=_LATER,
                ended_at=_LATER,
                outcome=StageOutcome.DONE,
            ),
        ),
    }
    fields.update(overrides)
    return EpisodeProcessingRecord.model_validate(fields)


# --- §2: the stage and the rule are added, nothing renamed --------------------


def test_the_recall_stage_and_rule_are_members_that_make_a_stage_due() -> None:
    assert ControllerStage("recall") is ControllerStage.RECALL
    assert ControllerRule("not_recalled") is ControllerRule.NOT_RECALLED
    entry = StageEntry(
        stage=ControllerStage.RECALL,
        due=ControllerRule.NOT_RECALLED,
        started_at=_NOW,
        ended_at=_LATER,
        outcome=StageOutcome.FAILED,
    )
    assert entry.outcome is StageOutcome.FAILED


def test_not_recalled_cannot_end_a_pass() -> None:
    with pytest.raises(ValidationError, match="end entry"):
        StageEntry(
            stage=ControllerStage.END,
            due=ControllerRule.NOT_RECALLED,
            started_at=_LATER,
            ended_at=_LATER,
            outcome=StageOutcome.DONE,
        )


# --- §6: closed enumerations ----------------------------------------------------


def test_the_recall_enumerations_carry_exactly_the_members_the_adr_lists() -> None:
    assert [member.value for member in RecallOutcome] == [
        "found",
        "nothing_found",
        "failed",
        "timed_out",
    ]
    # ADR-0308 §7: the second run's kinds of cue, added and never renamed; ADR-0353
    # §14:4 adds each unclear point's gap, renaming none.
    assert [member.value for member in RecallCue] == [
        "activation_input",
        "understood_meaning",
        "understood_phrase",
        "understood_gap",
    ]
    assert [member.value for member in RecallProvenance] == ["user", "outside"]


# --- §6: a recalled item ----------------------------------------------------------


def test_an_item_carries_its_structured_origin_as_stored() -> None:
    attestation = Attestation(reported_by="calendar", reported_at=_NOW)
    item = _item(
        standing=BeliefBand.ATTESTED,
        rests_on_recorded_external_content=True,
        attestation=attestation,
        provenance=RecallProvenance.OUTSIDE,
    )
    assert (item.standing, item.rests_on_recorded_external_content, item.attestation) == (
        BeliefBand.ATTESTED,
        True,
        attestation,
    )


def test_an_episode_is_recallable() -> None:
    assert _item(kind=MemoryKind.EPISODIC).kind is MemoryKind.EPISODIC


def test_a_memory_is_recallable() -> None:
    """ADR-0328 §2:5: an item that recalls a memory names the memory kind."""
    assert _item(kind=MemoryKind.MEMORY).kind is MemoryKind.MEMORY


def test_an_item_stored_naming_semantic_still_validates() -> None:
    """ADR-0328 §2:5, §16:7: an item stored before the memory record stays as stored."""
    stored = _item(kind=MemoryKind.MEMORY).model_dump(mode="json") | {"kind": "semantic"}
    assert RecalledItem.model_validate(stored).kind is MemoryKind.SEMANTIC


def test_only_episodes_semantic_records_and_memories_are_recallable() -> None:
    """The recallable kinds are every member ``MemoryKind`` now has (ADR-0328 §10:5)."""
    assert set(MemoryKind) == {MemoryKind.EPISODIC, MemoryKind.SEMANTIC, MemoryKind.MEMORY}
    with pytest.raises(ValidationError):
        RecalledItem.model_validate(_item().model_dump(mode="json") | {"kind": "preference"})


def test_an_item_keeps_a_stored_id_exactly_as_stored() -> None:
    assert _item(id="  spaced id ").id == "  spaced id "


def test_an_excerpt_is_bounded_like_a_referents() -> None:
    _item(excerpt="x" * UNDERSTANDING_REFERENT_EXCERPT_CHARS)
    with pytest.raises(ValidationError):
        _item(excerpt="x" * (UNDERSTANDING_REFERENT_EXCERPT_CHARS + 1))


def test_an_empty_excerpt_is_a_valid_one() -> None:
    assert _item(excerpt="").excerpt == ""


def test_an_item_names_what_found_it() -> None:
    with pytest.raises(ValidationError):
        _item(found_by=())


def test_an_item_carries_no_stories_by_default() -> None:
    """ADR-0300 §7:2, §12:1: empty by default."""
    assert _item().stories == ()


def test_an_episode_item_carries_its_stories_in_the_order_given() -> None:
    """ADR-0300 §7:2: in the order the store returned them, never re-sorted."""
    item = _item(kind=MemoryKind.EPISODIC, stories=("story:b", "story:a"))
    assert item.stories == ("story:b", "story:a")


@pytest.mark.parametrize("kind", [MemoryKind.SEMANTIC, MemoryKind.MEMORY])
def test_a_memory_item_carries_no_stories(kind: MemoryKind) -> None:
    """ADR-0300 §7:2: "A semantic item carries none, enforced by validator"; a memory neither."""
    with pytest.raises(ValidationError, match="only an episode's item carries stories"):
        _item(kind=kind, stories=("story:a",))


def test_a_story_id_is_never_blank() -> None:
    with pytest.raises(ValidationError):
        _item(kind=MemoryKind.EPISODIC, stories=(" ",))


def test_an_item_written_before_stories_validates_unchanged() -> None:
    """ADR-0300 §12:1: the field defaults to empty, so an older record's JSON still reads."""
    older = _item(kind=MemoryKind.EPISODIC).model_dump(mode="json")
    del older["stories"]
    assert RecalledItem.model_validate(older).stories == ()


def test_an_item_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        _item(score=0.9)


# --- §6: the recall result ----------------------------------------------------------


def test_a_found_recall_carries_items() -> None:
    assert len(_recall().items) == 1
    with pytest.raises(ValidationError, match="exactly when"):
        _recall(items=())


@pytest.mark.parametrize(
    "outcome", [RecallOutcome.NOTHING_FOUND, RecallOutcome.FAILED, RecallOutcome.TIMED_OUT]
)
def test_a_recall_that_is_not_found_carries_no_items(outcome: RecallOutcome) -> None:
    assert _recall(outcome=outcome, items=()).items == ()
    with pytest.raises(ValidationError, match="exactly when"):
        _recall(outcome=outcome)


def test_a_recall_names_the_cues_it_searched_with() -> None:
    with pytest.raises(ValidationError):
        _recall(cues=())


def test_a_recall_is_bounded_by_the_types_ceiling() -> None:
    _recall(items=tuple(_item(id=f"m{n}") for n in range(RECALLED_ITEMS_MAX)))
    with pytest.raises(ValidationError):
        _recall(items=tuple(_item(id=f"m{n}") for n in range(RECALLED_ITEMS_MAX + 1)))


# --- §6: the record field, and the schema-4 rule --------------------------------------


def test_the_record_defaults_to_no_recall_at_the_current_schema_version() -> None:
    record = _record()
    assert record.recall is None
    assert record.schema_version == 12


def test_a_schema_3_record_is_refused() -> None:
    with pytest.raises(ValidationError):
        _record(schema_version=3)


def test_the_record_carries_a_recall_result() -> None:
    recall = _recall()
    assert _record(recall=recall).recall == recall


def test_a_record_round_trips_with_its_recall() -> None:
    record = _record(recall=_recall(outcome=RecallOutcome.NOTHING_FOUND, items=()))
    assert EpisodeProcessingRecord.model_validate_json(record.model_dump_json()) == record


# --- ADR-0308 §7: the second run's record ----------------------------------------------


def _second_run(**overrides: object) -> ActivationRecall:
    fields: dict[str, object] = {
        "cues": (RecallCue.UNDERSTOOD_MEANING, RecallCue.UNDERSTOOD_PHRASE),
        "items": (_item(found_by=(RecallCue.UNDERSTOOD_MEANING, RecallCue.UNDERSTOOD_PHRASE)),),
    }
    fields.update(overrides)
    return _recall(**fields)


def test_the_record_defaults_to_no_second_run() -> None:
    assert _record().recall_second_run is None


def test_the_record_carries_the_second_run_beside_the_first() -> None:
    first, second = _recall(), _second_run()
    record = _record(recall=first, recall_second_run=second)
    assert (record.recall, record.recall_second_run) == (first, second)


def test_a_record_round_trips_with_its_second_run() -> None:
    record = _record(recall=_recall(), recall_second_run=_second_run())
    assert EpisodeProcessingRecord.model_validate_json(record.model_dump_json()) == record


def test_a_second_run_that_failed_carries_its_cues_and_no_items() -> None:
    failed = _second_run(outcome=RecallOutcome.FAILED, items=())
    assert _record(recall_second_run=failed).recall_second_run == failed
    with pytest.raises(ValidationError):
        _second_run(outcome=RecallOutcome.FAILED)


# --- §7: the memory referent ----------------------------------------------------------


def test_a_referent_may_name_a_memory() -> None:
    referent = UnderstandingReferent(
        kind="memory", id="memory-1", source="semantic memory", excerpt="Dr Rao"
    )
    assert referent.kind == "memory"
