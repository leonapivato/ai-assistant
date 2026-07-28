"""Tests for the shared memory domain types."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from ai_assistant.core.types import (
    BeliefBand,
    CurrentContext,
    DataTier,
    EpisodicMemory,
    FeedbackEvent,
    FeedbackKind,
    MemoryDecision,
    MemoryDecisionKind,
    MemoryIngestResult,
    MemoryKind,
    MemoryRecord,
    MemorySource,
    MemoryUpdateProposal,
    MemoryWrite,
    MemoryWriteMode,
    Message,
    PreferenceMemory,
    ProceduralMemory,
    Provenance,
    Role,
    SemanticMemory,
    TimeOfDay,
    Validity,
    band_of,
)

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)
_LATER = datetime(2026, 6, 1, tzinfo=UTC)


def test_validity_defaults_to_a_fully_open_window() -> None:
    window = Validity()
    assert window.valid_from is None
    assert window.valid_until is None
    # An open window is live at any instant.
    assert window.live_at(_WHEN) is True


def test_validity_accepts_an_ordered_interval() -> None:
    window = Validity(valid_from=_WHEN, valid_until=_LATER)
    assert window.valid_from == _WHEN
    assert window.valid_until == _LATER


def test_validity_rejects_an_inverted_window() -> None:
    with pytest.raises(ValidationError, match="valid_until must be after valid_from"):
        Validity(valid_from=_LATER, valid_until=_WHEN)


def test_validity_rejects_an_empty_window_with_equal_endpoints() -> None:
    with pytest.raises(ValidationError, match="valid_until must be after valid_from"):
        Validity(valid_from=_WHEN, valid_until=_WHEN)


@pytest.mark.parametrize(
    ("window", "instant", "expected"),
    [
        # Half-open [from, until): live iff valid_from <= now < valid_until.
        (Validity(valid_until=_LATER), _WHEN, True),  # before the close: live
        (Validity(valid_until=_LATER), _LATER, False),  # at valid_until: retired
        (Validity(valid_from=_LATER), _WHEN, False),  # before it opens: not live
        (Validity(valid_from=_WHEN), _WHEN, True),  # at valid_from: live
        (Validity(valid_from=_WHEN, valid_until=_LATER), _WHEN, True),  # inside
    ],
)
def test_validity_live_at_enforces_both_ends_half_open(
    window: Validity, instant: datetime, *, expected: bool
) -> None:
    assert window.live_at(instant) is expected


def test_user_asserted_provenance_must_be_certain() -> None:
    with pytest.raises(ValidationError, match="must have confidence"):
        Provenance(source=MemorySource.USER_ASSERTED, confidence=0.5, last_updated=_WHEN)


def test_user_asserted_provenance_accepts_full_confidence() -> None:
    prov = Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_WHEN)
    assert prov.confidence == 1.0


def test_inferred_provenance_may_be_uncertain() -> None:
    prov = Provenance(source=MemorySource.INFERRED, confidence=0.5, last_updated=_WHEN)
    assert prov.confidence == 0.5


def test_confidence_is_bounded() -> None:
    with pytest.raises(ValidationError):
        Provenance(source=MemorySource.INFERRED, confidence=1.5, last_updated=_WHEN)


# --- bands: the standing a source places a belief in (ADR-0072 §2) -----------

# The ratified partition, written out member by member so that adding a
# `MemorySource` without choosing its band fails the suite as well as mypy.
_EXPECTED_BANDS = {
    MemorySource.USER_ASSERTED: BeliefBand.ASSERTED,
    MemorySource.OBSERVED: BeliefBand.DERIVED,
    MemorySource.INFERRED: BeliefBand.DERIVED,
    MemorySource.EXTERNAL: BeliefBand.ATTESTED,
}


@pytest.mark.parametrize("source", list(MemorySource))
def test_band_of_classifies_every_memory_source(source: MemorySource) -> None:
    """The mapping is total: every source has a band, and it is the ratified one."""
    assert source in _EXPECTED_BANDS, f"{source} has no ratified band (ADR-0072 §2)"
    assert band_of(source) is _EXPECTED_BANDS[source]


def test_the_expected_partition_covers_the_whole_source_enum() -> None:
    """A new `MemorySource` must be classified here, not silently left out."""
    assert set(_EXPECTED_BANDS) == set(MemorySource)


def test_every_band_is_reachable_from_some_source() -> None:
    """Three bands, all of them populated — none is decorative (ADR-0072 §2)."""
    assert {band_of(source) for source in MemorySource} == set(BeliefBand)


def test_external_is_neither_asserted_nor_derived() -> None:
    """`EXTERNAL` gets its own band; folding it either way was rejected (ADR-0072 §2)."""
    assert band_of(MemorySource.EXTERNAL) is BeliefBand.ATTESTED
    assert band_of(MemorySource.EXTERNAL) not in {BeliefBand.ASSERTED, BeliefBand.DERIVED}


def test_band_values_are_stable_strings() -> None:
    """The wire values are part of the contract — a `StrEnum` that compares as `str`."""
    assert [band.value for band in BeliefBand] == ["asserted", "derived", "attested"]
    assert isinstance(BeliefBand.DERIVED, str)
    assert str(BeliefBand.ASSERTED) == "asserted"


def test_naive_expires_at_is_refused() -> None:
    """Rejected, not assumed UTC (ADR-0023 §3).

    ``core`` cannot know whether the caller meant UTC or their own wall clock,
    and coercing resolves that ambiguity in the fabricating direction every time.
    """
    prov = Provenance(source=MemorySource.INFERRED, confidence=0.4, last_updated=_WHEN)
    with pytest.raises(ValidationError, match="expires_at must be timezone-aware"):
        SemanticMemory(
            id="1",
            content="c",
            fact="f",
            provenance=prov,
            expires_at=datetime(2026, 1, 2),  # noqa: DTZ001 — a naive value is the subject
        )


def test_naive_last_updated_is_refused() -> None:
    """``Provenance.last_updated`` had no validator at all before ADR-0023."""
    with pytest.raises(ValidationError, match="last_updated must be timezone-aware"):
        Provenance(
            source=MemorySource.INFERRED,
            confidence=0.4,
            last_updated=datetime(2026, 1, 2),  # noqa: DTZ001 — a naive value is the subject
        )


def test_naive_occurred_at_is_refused() -> None:
    """``EpisodicMemory.occurred_at`` had no validator at all before ADR-0023."""
    prov = Provenance(source=MemorySource.INFERRED, confidence=0.4, last_updated=_WHEN)
    with pytest.raises(ValidationError, match="occurred_at must be timezone-aware"):
        EpisodicMemory(
            id="1",
            content="c",
            provenance=prov,
            occurred_at=datetime(2026, 1, 2),  # noqa: DTZ001 — a naive value is the subject
        )


def test_naive_valid_until_is_refused() -> None:
    """``SemanticMemory.valid_until`` had no validator at all before ADR-0023."""
    prov = Provenance(source=MemorySource.INFERRED, confidence=0.4, last_updated=_WHEN)
    with pytest.raises(ValidationError, match="valid_until must be timezone-aware"):
        SemanticMemory(
            id="1",
            content="c",
            fact="f",
            provenance=prov,
            valid_until=datetime(2026, 1, 2),  # noqa: DTZ001 — a naive value is the subject
        )


def test_previously_unvalidated_fields_convert_an_aware_value_to_utc() -> None:
    """The three fields that had no rule now get the whole rule, not half of it."""
    berlin = datetime(2026, 1, 2, 10, tzinfo=ZoneInfo("Europe/Berlin"))  # 09:00 UTC
    record = EpisodicMemory(
        id="1",
        content="c",
        provenance=Provenance(source=MemorySource.INFERRED, confidence=0.4, last_updated=berlin),
        occurred_at=berlin,
    )

    assert record.occurred_at == datetime(2026, 1, 2, 9, tzinfo=UTC)
    assert record.occurred_at.tzinfo is UTC
    assert record.provenance.last_updated.tzinfo is UTC


def test_aware_expires_at_is_left_unchanged() -> None:
    prov = Provenance(source=MemorySource.INFERRED, confidence=0.4, last_updated=_WHEN)
    deadline = datetime(2026, 1, 2, tzinfo=UTC)
    record = SemanticMemory(id="1", content="c", fact="f", provenance=prov, expires_at=deadline)
    assert record.expires_at == deadline


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"kind": "episodic", "occurred_at": _WHEN}, EpisodicMemory),
        ({"kind": "semantic", "fact": "f"}, SemanticMemory),
        ({"kind": "preference", "preference": "concise"}, PreferenceMemory),
        ({"kind": "procedural", "situation": "s"}, ProceduralMemory),
    ],
)
def test_discriminated_union_resolves_by_kind(
    payload: dict[str, object], expected: type[object]
) -> None:
    adapter: TypeAdapter[MemoryRecord] = TypeAdapter(MemoryRecord)
    record = adapter.validate_python(
        {
            "id": "1",
            "content": "c",
            "provenance": {"source": "inferred", "confidence": 0.4, "last_updated": _WHEN},
            **payload,
        }
    )
    assert isinstance(record, expected)


def _semantic(record_id: str) -> SemanticMemory:
    return SemanticMemory(
        id=record_id,
        content="c",
        fact="f",
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.4, last_updated=_WHEN),
    )


def test_memory_write_defaults_to_upsert() -> None:
    write = MemoryWrite(record=_semantic("1"))
    assert write.mode is MemoryWriteMode.UPSERT


def test_memory_write_coerces_a_valid_mode_string_to_the_enum() -> None:
    # A raw string at construction is validated to the enum member, so the store's
    # identity check (`is MemoryWriteMode.INSERT_IF_ABSENT`) still holds.
    write = MemoryWrite(record=_semantic("1"), mode="insert_if_absent")  # type: ignore[arg-type]
    assert write.mode is MemoryWriteMode.INSERT_IF_ABSENT


def test_memory_write_is_frozen_so_mode_cannot_be_reassigned() -> None:
    # Frozen blocks *any* post-construction reassignment of mode. This is what
    # stops a raw-string overwrite (`write.mode = "insert_if_absent"`) from
    # bypassing the enum and silently downgrading an insert-if-absent to an upsert
    # that clobbers a colliding record (ADR-0046 §3-4).
    write = MemoryWrite(record=_semantic("1"), mode=MemoryWriteMode.INSERT_IF_ABSENT)
    with pytest.raises(ValidationError):
        write.mode = MemoryWriteMode.UPSERT


@pytest.mark.parametrize(
    "kind", [MemoryDecisionKind.REINFORCE, MemoryDecisionKind.SUPERSEDE], ids=str
)
def test_fold_decision_requires_target(kind: MemoryDecisionKind) -> None:
    with pytest.raises(ValidationError, match="requires target_id"):
        MemoryDecision(kind=kind, reason="x")


def test_store_temporary_decision_requires_ttl() -> None:
    with pytest.raises(ValidationError, match="requires ttl"):
        MemoryDecision(kind=MemoryDecisionKind.STORE_TEMPORARY, reason="x")


def test_accept_decision_needs_no_extra_fields() -> None:
    decision = MemoryDecision(kind=MemoryDecisionKind.ACCEPT, reason="ok")
    assert decision.target_id is None


def test_store_temporary_decision_rejects_non_positive_ttl() -> None:
    with pytest.raises(ValidationError, match="positive ttl"):
        MemoryDecision(kind=MemoryDecisionKind.STORE_TEMPORARY, reason="x", ttl=timedelta(0))
    with pytest.raises(ValidationError, match="positive ttl"):
        MemoryDecision(kind=MemoryDecisionKind.STORE_TEMPORARY, reason="x", ttl=timedelta(days=-1))


def test_decision_rejects_fields_foreign_to_its_kind() -> None:
    with pytest.raises(ValidationError, match="target_id is only valid"):
        MemoryDecision(kind=MemoryDecisionKind.ACCEPT, reason="x", target_id="other")
    with pytest.raises(ValidationError, match="ttl is only valid"):
        MemoryDecision(kind=MemoryDecisionKind.ACCEPT, reason="x", ttl=timedelta(days=1))


def test_current_context_constructs_and_forbids_extra_fields() -> None:
    ctx = CurrentContext(
        now=_WHEN,
        time_of_day=TimeOfDay.MORNING,
        is_weekend=False,
        within_working_hours=True,
    )
    assert ctx.time_of_day is TimeOfDay.MORNING

    with pytest.raises(ValidationError):
        CurrentContext(
            now=_WHEN,
            time_of_day=TimeOfDay.MORNING,
            is_weekend=False,
            within_working_hours=True,
            calendar="busy",  # type: ignore[call-arg]  # extra field must be rejected
        )


def test_current_context_now_naive_is_refused() -> None:
    """Advisory or durable makes no difference — ADR-0023 §4 refuses the category.

    ``core`` cannot classify a value's provenance, so the rule follows from where
    the type sits, not from what the field is later used for.
    """
    with pytest.raises(ValidationError, match="now must be timezone-aware"):
        CurrentContext(
            now=datetime(2026, 1, 1, 12),  # noqa: DTZ001 — a naive value is the subject
            time_of_day=TimeOfDay.AFTERNOON,
            is_weekend=False,
            within_working_hours=True,
        )


def test_current_context_now_aware_is_converted_to_utc() -> None:
    """``CurrentContext.now`` used to keep an aware non-UTC value verbatim."""
    ctx = CurrentContext(
        now=datetime(2026, 1, 1, 9, tzinfo=ZoneInfo("America/New_York")),
        time_of_day=TimeOfDay.MORNING,
        is_weekend=False,
        within_working_hours=True,
    )
    assert ctx.now == datetime(2026, 1, 1, 14, tzinfo=UTC)
    assert ctx.now.tzinfo is UTC


def test_feedback_event_constructs_with_defaults() -> None:
    event = FeedbackEvent(
        kind=FeedbackKind.PREFERENCE,
        memory_kind=MemoryKind.PREFERENCE,
        content="prefers concise replies",
        created_at=_WHEN,
    )
    assert event.subject is None
    assert event.evidence == ()


def test_feedback_event_created_at_naive_is_refused() -> None:
    with pytest.raises(ValidationError, match="created_at must be timezone-aware"):
        FeedbackEvent(
            kind=FeedbackKind.CORRECTION,
            memory_kind=MemoryKind.SEMANTIC,
            content="office is in Boston",
            created_at=datetime(2026, 1, 1, 9),  # noqa: DTZ001 — a naive value is the subject
        )


def test_feedback_event_created_at_aware_is_converted_to_utc() -> None:
    # 09:00 in New York (UTC-5 in January) is 14:00 UTC — the same instant, in UTC.
    aware = datetime(2026, 1, 1, 9, tzinfo=ZoneInfo("America/New_York"))
    event = FeedbackEvent(
        kind=FeedbackKind.CORRECTION,
        memory_kind=MemoryKind.SEMANTIC,
        content="office is in Boston",
        created_at=aware,
    )
    assert event.created_at == datetime(2026, 1, 1, 14, tzinfo=UTC)
    assert event.created_at.utcoffset() == timedelta(0)


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_feedback_event_rejects_blank_content(blank: str) -> None:
    with pytest.raises(ValidationError, match="content must not be empty"):
        FeedbackEvent(
            kind=FeedbackKind.PREFERENCE,
            memory_kind=MemoryKind.PREFERENCE,
            content=blank,
            created_at=_WHEN,
        )


def test_feedback_event_strips_content() -> None:
    event = FeedbackEvent(
        kind=FeedbackKind.PREFERENCE,
        memory_kind=MemoryKind.PREFERENCE,
        content="  prefers tea  ",
        created_at=_WHEN,
    )
    assert event.content == "prefers tea"


def test_proposal_defaults_to_personal_sensitivity() -> None:
    record = SemanticMemory(
        id="1",
        content="c",
        fact="f",
        provenance=Provenance(source=MemorySource.INFERRED, confidence=0.4, last_updated=_WHEN),
    )
    proposal = MemoryUpdateProposal(proposed=record, rationale="because")
    assert proposal.sensitivity is DataTier.PERSONAL


# --- ADR-0068: the memory record graph is frozen all the way down -------


def test_message_is_frozen() -> None:
    message = Message(role=Role.USER, content="hi")
    with pytest.raises(ValidationError):
        message.content = "rewritten"


def test_memory_record_is_frozen_including_its_nested_models() -> None:
    """A record and every model it reaches reject post-construction edits."""
    record = _semantic("1")
    with pytest.raises(ValidationError):
        record.content = "rewritten"
    with pytest.raises(ValidationError):
        record.provenance.confidence = 0.9  # the nested Provenance is frozen
    with pytest.raises(ValidationError):
        record.validity.valid_until = _LATER  # the nested Validity is frozen


def test_memory_update_proposal_is_frozen_including_its_record() -> None:
    proposal = MemoryUpdateProposal(proposed=_semantic("1"), rationale="because")
    with pytest.raises(ValidationError):
        proposal.rationale = "rewritten"
    with pytest.raises(ValidationError):
        proposal.proposed.content = "rewritten"  # the nested record is frozen


def test_memory_decision_and_ingest_result_are_frozen() -> None:
    decision = MemoryDecision(kind=MemoryDecisionKind.ACCEPT, reason="ok")
    with pytest.raises(ValidationError):
        decision.reason = "rewritten"
    result = MemoryIngestResult(decision=decision, record_id="r1")
    with pytest.raises(ValidationError):
        result.record_id = "other"
    with pytest.raises(ValidationError):
        result.decision.reason = "rewritten"  # the nested decision is frozen


def test_current_context_is_frozen() -> None:
    ctx = CurrentContext(
        now=_WHEN, time_of_day=TimeOfDay.MORNING, is_weekend=False, within_working_hours=True
    )
    with pytest.raises(ValidationError):
        ctx.is_weekend = True


def test_feedback_event_is_frozen() -> None:
    event = FeedbackEvent(
        kind=FeedbackKind.PREFERENCE,
        memory_kind=MemoryKind.PREFERENCE,
        content="prefers tea",
        created_at=_WHEN,
    )
    with pytest.raises(ValidationError):
        event.content = "rewritten"


def test_memory_write_is_deeply_immutable() -> None:
    """ADR-0065's counterexample resolved: the frozen wrapper's record is frozen too."""
    write = MemoryWrite(record=_semantic("1"))
    with pytest.raises(ValidationError):
        write.record.content = "rewritten"


def test_construction_coerces_a_list_to_a_tuple_on_the_wire() -> None:
    """A ``list`` on the wire is accepted and read back as an immutable tuple.

    ``model_validate`` takes the coercion path a JSON/dict caller uses, so an
    ex-``list`` field constructed from a list still works (ADR-0068 §1, Class C).
    """
    prov = Provenance.model_validate(
        {
            "source": MemorySource.OBSERVED,
            "confidence": 0.4,
            "last_updated": _WHEN,
            "evidence": ["e1", "e2"],
        }
    )
    assert prov.evidence == ("e1", "e2")
    assert isinstance(prov.evidence, tuple)


def test_every_ex_list_field_is_an_immutable_tuple_that_round_trips() -> None:
    """The ADR-0068 depth rule, for all five former ``list`` fields.

    Each reads back as an immutable ``tuple``; ``model_dump(mode="json")`` renders
    it as a JSON array (so there is no wire change); and ``model_validate`` of the
    dumped form reconstructs the same tuple.
    """
    prov = Provenance(
        source=MemorySource.OBSERVED, confidence=0.4, last_updated=_WHEN, evidence=("e1", "e2")
    )
    episodic = EpisodicMemory(
        id="1", content="c", provenance=prov, occurred_at=_WHEN, participants=("a", "b")
    )
    procedural = ProceduralMemory(
        id="2", content="c", provenance=prov, situation="s", steps=("one", "two")
    )
    proposal = MemoryUpdateProposal(proposed=_semantic("3"), rationale="r", conflicts=("x", "y"))
    feedback = FeedbackEvent(
        kind=FeedbackKind.PREFERENCE,
        memory_kind=MemoryKind.PREFERENCE,
        content="c",
        created_at=_WHEN,
        evidence=("ev",),
    )

    cases: list[tuple[BaseModel, str, tuple[str, ...]]] = [
        (prov, "evidence", ("e1", "e2")),
        (episodic, "participants", ("a", "b")),
        (procedural, "steps", ("one", "two")),
        (proposal, "conflicts", ("x", "y")),
        (feedback, "evidence", ("ev",)),
    ]
    for model, field, expected in cases:
        value = getattr(model, field)
        assert isinstance(value, tuple), field
        assert value == expected, field
        # A tuple serialises as a JSON array — no wire change.
        assert model.model_dump(mode="json")[field] == list(expected), field
        # And it reconstructs from its dumped form unchanged.
        restored = type(model).model_validate(model.model_dump())
        assert getattr(restored, field) == expected, field
