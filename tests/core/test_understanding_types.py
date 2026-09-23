"""The activation-understanding types and the additive record fields of ADR-0276 §2 and §7."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ai_assistant.core.errors import AssistantError, UnderstandingError
from ai_assistant.core.types import (
    UNDERSTANDING_REFERENT_EXCERPT_CHARS,
    ActivationUnderstanding,
    ChannelContext,
    EpisodeProcessingRecord,
    EpisodeResponseKind,
    NewConversation,
    ProcessingReason,
    ProcessingStatus,
    ProposedActivationUnderstanding,
    ProposedReference,
    ProposedRelationship,
    RecordedChannelTrigger,
    RecordedTextInput,
    UnderstandingGround,
    UnderstandingOmission,
    UnderstandingProducer,
    UnderstandingReference,
    UnderstandingReferent,
    UnderstandingRelationship,
    UnresolvedMatter,
    WholeTextReply,
)

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_INPUT = UnderstandingReferent(kind="input", excerpt="book the dentist")
_EPISODE = UnderstandingReferent(
    kind="episode", id="episode-1", source="conversation", excerpt="the dentist is on Elm"
)


def _understanding(**overrides: object) -> ActivationUnderstanding:
    fields: dict[str, object] = {
        "version": 1,
        "recorded_at": _NOW,
        "producer": UnderstandingProducer.INTERPRETATION,
        "meaning": "book the dentist appointment",
        "meaning_ground": UnderstandingGround.STATED,
    }
    fields.update(overrides)
    return ActivationUnderstanding.model_validate(fields)


def _record(**overrides: object) -> EpisodeProcessingRecord:
    fields: dict[str, object] = {
        "activation_id": "activation",
        "started_at": _NOW,
        "ended_at": _NOW,
        "trigger": RecordedChannelTrigger(
            target=NewConversation(),
            channel=None,
            payload=RecordedTextInput(text="book the dentist"),
            context=ChannelContext(),
            conversation=None,
            reply=WholeTextReply(),
        ),
        "status": ProcessingStatus.COMPLETED,
        "reason": ProcessingReason.RETURNED,
        "response_kind": EpisodeResponseKind.NONE,
        "model_eligible": True,
        "understanding_omitted": UnderstandingOmission.NOT_REACHED,
    }
    fields.update(overrides)
    return EpisodeProcessingRecord.model_validate(fields)


# --- §2: three closed enumerations ------------------------------------------


def test_the_three_enumerations_carry_exactly_the_members_the_adr_lists() -> None:
    """ADR-0276 §2's tables are complete; a member is valued by its lower-cased name."""
    assert {member.value for member in UnderstandingGround} == {"stated", "supplied", "inferred"}
    assert {member.value for member in UnderstandingOmission} == {
        "routed",
        "no_text",
        "no_input",
        "failed",
        "not_reached",
    }
    assert {member.value for member in UnderstandingProducer} == {"interpretation"}
    for enum in (UnderstandingGround, UnderstandingOmission, UnderstandingProducer):
        assert all(member.value == member.name.lower() for member in enum)


def test_processing_reason_gains_understanding_failed() -> None:
    """§6: the reason the classifier will assign to a pass ``UnderstandingError`` ended."""
    assert ProcessingReason.UNDERSTANDING_FAILED.value == "understanding_failed"
    assert ProcessingReason("understanding_failed") is ProcessingReason.UNDERSTANDING_FAILED


def test_understanding_error_is_an_assistant_error_with_the_standard_constructor() -> None:
    """§6: a new ``AssistantError`` subclass carrying a message and no content field."""
    error = UnderstandingError("second output did not parse")
    assert isinstance(error, AssistantError)
    assert str(error) == "second output did not parse"
    assert not {name for name in vars(error) if name != "details_elided"}


# --- §2: the proposed form validates no grounding ---------------------------


def test_a_proposal_carries_labels_and_no_identity() -> None:
    """The model's output: labels of §3's scheme, and no id, timestamp, version or producer."""
    proposal = ProposedActivationUnderstanding(
        meaning="compare the two quotes",
        meaning_ground=UnderstandingGround.SUPPLIED,
        meaning_labels=("H1", "P2"),
        references=(ProposedReference(phrase="the two quotes", labels=("H1", "P2")),),
        relationships=(
            ProposedRelationship(
                statement="the second quote followed the first",
                labels=("P2",),
                ground=UnderstandingGround.SUPPLIED,
            ),
        ),
        unresolved=(UnresolvedMatter(matter="which currency", why_it_matters="totals differ"),),
    )
    assert set(ProposedActivationUnderstanding.model_fields) == {
        "meaning",
        "meaning_ground",
        "meaning_labels",
        "references",
        "relationships",
        "unresolved",
    }
    assert proposal.references[0].labels == ("H1", "P2")
    for forbidden in ("version", "recorded_at", "producer", "id"):
        with pytest.raises(ValidationError):
            ProposedActivationUnderstanding.model_validate(
                {**proposal.model_dump(), forbidden: "x"}
            )


def test_a_proposal_accepts_supplied_with_no_label() -> None:
    """§2: ``supplied`` naming nothing is §6's grounding defect, never a parse failure."""
    proposal = ProposedActivationUnderstanding(
        meaning="compare the two quotes",
        meaning_ground=UnderstandingGround.SUPPLIED,
        relationships=(
            ProposedRelationship(statement="one follows", ground=UnderstandingGround.SUPPLIED),
        ),
    )
    assert proposal.meaning_labels == ()
    assert proposal.relationships[0].labels == ()


@pytest.mark.parametrize("blank", ["", "   "])
def test_proposal_texts_are_non_blank(blank: str) -> None:
    """Every text a proposal carries reuses ``NonBlankEncodableText``."""
    with pytest.raises(ValidationError):
        ProposedActivationUnderstanding(meaning=blank, meaning_ground=UnderstandingGround.STATED)
    with pytest.raises(ValidationError):
        ProposedReference(phrase=blank)
    with pytest.raises(ValidationError):
        UnresolvedMatter(matter="x", why_it_matters=blank)


# --- §2: the recorded form names its sources ----------------------------------


def test_a_recorded_supplied_meaning_names_a_referent() -> None:
    """§2: ``meaning_ground=supplied`` with empty ``meaning_referents`` is refused by the type."""
    with pytest.raises(ValidationError, match="supplied meaning"):
        _understanding(meaning_ground=UnderstandingGround.SUPPLIED)
    recorded = _understanding(
        meaning_ground=UnderstandingGround.SUPPLIED, meaning_referents=(_EPISODE,)
    )
    assert recorded.meaning_referents == (_EPISODE,)


def test_a_recorded_supplied_relationship_names_a_referent() -> None:
    """§2: a relationship with ``ground=supplied`` carries a non-empty ``referents``."""
    with pytest.raises(ValidationError, match="supplied relationship"):
        _understanding(
            relationships=(
                UnderstandingRelationship(
                    statement="one follows", ground=UnderstandingGround.SUPPLIED
                ),
            )
        )
    recorded = _understanding(
        relationships=(
            UnderstandingRelationship(
                statement="one follows", referents=(_EPISODE,), ground=UnderstandingGround.SUPPLIED
            ),
        )
    )
    assert recorded.relationships[0].referents == (_EPISODE,)


@pytest.mark.parametrize("ground", [UnderstandingGround.STATED, UnderstandingGround.INFERRED])
def test_stated_and_inferred_need_no_referent(ground: UnderstandingGround) -> None:
    """Only ``supplied`` names its source; the other two grounds carry none."""
    recorded = _understanding(
        meaning_ground=ground,
        relationships=(UnderstandingRelationship(statement="one follows", ground=ground),),
    )
    assert recorded.meaning_referents == ()


def test_a_recorded_understanding_carries_no_label() -> None:
    """§2: the recorded form has referents where the proposal had labels, and nothing else."""
    assert set(ActivationUnderstanding.model_fields) == {
        "version",
        "recorded_at",
        "producer",
        "meaning",
        "meaning_ground",
        "meaning_referents",
        "references",
        "relationships",
        "unresolved",
        "grounding_dropped",
    }
    for model in (ActivationUnderstanding, UnderstandingReference, UnderstandingRelationship):
        assert "labels" not in model.model_fields
        assert "meaning_labels" not in model.model_fields


def test_referent_kinds_and_the_exactly_as_stored_episode_id() -> None:
    """§2: three kinds; an episode ``id`` is carried exactly as stored, blank included."""
    assert UnderstandingReferent(kind="input", excerpt="").id is None
    item = UnderstandingReferent(kind="channel_item", id=None, source="email", excerpt="x")
    assert item.id is None
    blank = UnderstandingReferent(kind="episode", id="  ", source="conversation", excerpt="x")
    assert blank.id == "  "
    with pytest.raises(ValidationError):
        UnderstandingReferent(kind="record", excerpt="x")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        UnderstandingReferent(kind="episode", id="e", source="", excerpt="x")


def test_an_excerpt_is_bounded_at_two_hundred_and_forty_characters() -> None:
    """§2: a bounded prefix, at most 240 characters, and the bound is a type bound."""
    assert UNDERSTANDING_REFERENT_EXCERPT_CHARS == 240
    UnderstandingReferent(kind="input", excerpt="é" * 240)
    with pytest.raises(ValidationError):
        UnderstandingReferent(kind="input", excerpt="é" * 241)


@pytest.mark.parametrize(
    ("field", "value"),
    [("version", 0), ("version", 2**31), ("grounding_dropped", -1), ("grounding_dropped", 2**31)],
)
def test_version_and_dropped_count_ranges(field: str, value: int) -> None:
    """§2: ``version`` in ``[1, 2**31)`` and ``grounding_dropped`` in ``[0, 2**31)``."""
    with pytest.raises(ValidationError):
        _understanding(**{field: value})
    assert _understanding(version=2**31 - 1, grounding_dropped=2**31 - 1).version == 2**31 - 1


def test_recorded_understanding_round_trips_through_its_dump() -> None:
    """The shape crosses the wire by ``model_dump`` (protocol 58); it decodes to itself."""
    recorded = _understanding(
        meaning_ground=UnderstandingGround.SUPPLIED,
        meaning_referents=(_INPUT, _EPISODE),
        references=(UnderstandingReference(phrase="the dentist", referents=(_EPISODE,)),),
        relationships=(
            UnderstandingRelationship(
                statement="same dentist as before",
                referents=(_EPISODE,),
                ground=UnderstandingGround.SUPPLIED,
            ),
        ),
        unresolved=(UnresolvedMatter(matter="which day", why_it_matters="two were offered"),),
        grounding_dropped=2,
    )
    assert ActivationUnderstanding.model_validate(recorded.model_dump(mode="json")) == recorded
    assert recorded.model_config.get("frozen") is True


# --- §7: schema_version 2, three fields, exactly one of history and omission ----


def test_the_record_is_schema_version_two_with_three_understanding_fields() -> None:
    """§7: ``schema_version`` becomes ``Literal[2]``; no reader for a version-1 record exists."""
    record = _record()
    assert record.schema_version == 2
    assert record.understanding == ()
    assert record.understanding_omitted is UnderstandingOmission.NOT_REACHED
    assert record.understanding_elided == 0
    with pytest.raises(ValidationError):
        _record(schema_version=1)
    with pytest.raises(ValidationError):
        EpisodeProcessingRecord.model_validate({**record.model_dump(), "schema_version": 1})


def test_a_record_carries_exactly_one_of_its_understanding_and_an_omission() -> None:
    """§7: exactly one of a non-empty ``understanding`` and a non-``None`` omission value."""
    versions = (_understanding(), _understanding(version=2, meaning="revised"))
    with_versions = _record(understanding=versions, understanding_omitted=None)
    assert with_versions.understanding == versions
    with pytest.raises(ValidationError, match="either its understanding or why it has none"):
        _record(understanding=(), understanding_omitted=None)
    with pytest.raises(ValidationError, match="either its understanding or why it has none"):
        _record(understanding=versions, understanding_omitted=UnderstandingOmission.FAILED)
    for omission in UnderstandingOmission:
        assert _record(understanding_omitted=omission).understanding_omitted is omission


def test_the_elided_count_rides_a_non_empty_history() -> None:
    """§7: ``understanding_elided`` counts dropped versions; the type ties it to nothing."""
    record = _record(
        understanding=(_understanding(),), understanding_omitted=None, understanding_elided=3
    )
    assert record.understanding_elided == 3


@pytest.mark.parametrize("elided", [-1, 2**31])
def test_the_elided_count_is_bounded(elided: int) -> None:
    """§7: ``understanding_elided`` in ``[0, 2**31)``."""
    with pytest.raises(ValidationError):
        _record(understanding_elided=elided)


def test_a_record_with_understanding_round_trips_through_its_dump() -> None:
    """The record crosses the wire inside ``EpisodicMemory.processing_record`` (protocol 54, 59)."""
    record = _record(
        understanding=(_understanding(meaning_referents=(_INPUT,)),),
        understanding_omitted=None,
        understanding_elided=1,
    )
    assert EpisodeProcessingRecord.model_validate(record.model_dump(mode="json")) == record
    assert "understanding_omitted" in record.model_dump()
