"""Tests for the shared memory domain types."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from ai_assistant.core.types import (
    MAX_EVIDENCE_CITATIONS,
    TERMINAL_DEFERRAL_STATES,
    BeliefBand,
    CurrentContext,
    DataTier,
    DeferralAdmission,
    DeferralAdmissionOutcome,
    DeferralClaim,
    DeferralState,
    DeferredProposal,
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
    ObservationOutcome,
    PreferenceMemory,
    ProceduralMemory,
    Provenance,
    Role,
    SemanticMemory,
    TimeOfDay,
    UserConfirmation,
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


# --- a derived belief may not claim certainty (ADR-0077 §7) ------------------
# The question ADR-0072 §3 declined and filed for the lane with the first
# producer that could breach it. Enforced on the *value* rather than at the
# `MemoryPolicy` gate, because the gate is not the only path a `Provenance`
# takes: `Goal` carries one and reaches no gate at all, which is the half of
# #432 this closes.


@pytest.mark.parametrize("source", [MemorySource.OBSERVED, MemorySource.INFERRED])
def test_a_derived_provenance_may_not_claim_full_confidence(source: MemorySource) -> None:
    assert band_of(source) is BeliefBand.DERIVED  # the rule is on the band, not the name

    with pytest.raises(ValidationError, match="DERIVED"):
        Provenance(source=source, confidence=1.0, last_updated=_WHEN)


@pytest.mark.parametrize("source", [MemorySource.OBSERVED, MemorySource.INFERRED])
def test_a_derived_provenance_accepts_anything_below_full(source: MemorySource) -> None:
    """The bound is exclusive at 1.0 only; the rest of the range is untouched."""
    assert Provenance(source=source, confidence=0.999, last_updated=_WHEN).confidence == 0.999
    assert Provenance(source=source, confidence=0.0, last_updated=_WHEN).confidence == 0.0


def test_an_external_provenance_may_still_claim_full_confidence() -> None:
    """`EXTERNAL` is in the ATTESTED band, and ADR-0038 §2a lets it be certain."""
    prov = Provenance(source=MemorySource.EXTERNAL, confidence=1.0, last_updated=_WHEN)

    assert band_of(prov.source) is BeliefBand.ATTESTED
    assert prov.confidence == 1.0


def test_the_two_confidence_rules_do_not_overlap() -> None:
    """Each band's rule binds its own sources and no others.

    Asserted over the whole enum so a `MemorySource` added later cannot land in
    the derived band with the rule silently not applying to it.
    """
    for source in MemorySource:
        band = band_of(source)
        forbidden = 1.0 if band is BeliefBand.DERIVED else 0.5
        if band is BeliefBand.ATTESTED:
            continue  # neither rule binds it
        with pytest.raises(ValidationError):
            Provenance(source=source, confidence=forbidden, last_updated=_WHEN)


# --- the evidence bound is not on this type (ADR-0086 §1, §2) ----------------


def test_provenance_admits_more_citations_than_the_bound() -> None:
    """The bound is a ``MemoryWriter`` obligation, and this is the other half of it.

    A ``max_length=MAX_EVIDENCE_CITATIONS`` on ``evidence`` is the obvious
    implementation and is the wrong one: a pydantic validator runs on
    *deserialisation* as well as on construction, and ``SqliteMemoryStore``
    reconstructs every record through the model on every read. A deployment
    running since ADR-0077's observer shipped may already hold a belief above the
    bound — four disjoint batches of 20 is 80 — and on the day such a validator
    landed, ``get``, ``list_beliefs`` and ``export`` would all start failing on it.
    "A belief that becomes unreadable through any implementation" is the sentence
    ADR-0084 §4 asked ADR-0086 to make false.

    So this case fails the moment anyone adds that ``max_length``, which no
    assertion about a *writer's* output can do — a writer that truncates correctly
    satisfies its whole suite whether or not the type also refuses.
    """
    over_bound = tuple(f"ev-{index:03d}" for index in range(MAX_EVIDENCE_CITATIONS + 16))

    prov = Provenance(
        source=MemorySource.OBSERVED, confidence=0.6, last_updated=_WHEN, evidence=over_bound
    )

    assert prov.evidence == over_bound
    # And it survives a round trip through the serialised form, which is the path
    # a stored record actually takes back out of a store.
    assert Provenance.model_validate_json(prov.model_dump_json()).evidence == over_bound


def test_a_feedback_event_is_not_bounded_either() -> None:
    """ADR-0086 §1 says so explicitly, and the reason is the placement.

    A ``FeedbackEvent`` carrying more ids than the bound is constructible, and
    ``RuleBasedFeedbackProcessor`` copies all of them into the record it proposes.
    Nothing there is stored: the proposal crosses ``MemoryWriter``, which installs
    the retained subset and records the elision like any other. A second
    enforcement point at the feedback boundary would put one rule in two places to
    drift.
    """
    over_bound = tuple(f"ev-{index:03d}" for index in range(MAX_EVIDENCE_CITATIONS + 1))

    event = FeedbackEvent(
        kind=FeedbackKind.CORRECTION,
        memory_kind=MemoryKind.SEMANTIC,
        content="the office is in Boston",
        evidence=over_bound,
        created_at=_WHEN,
    )

    assert event.evidence == over_bound


def test_provenance_defaults_to_having_elided_nothing() -> None:
    """Additive with a default, so a record stored before ADR-0086 deserialises at 0.

    Nothing migrates, and every ``Goal`` carries one too — always zero, since the
    bound is scoped to ``MemoryRecord`` installs and nothing accumulates on the
    goal path (ADR-0086 §1, §4).
    """
    prov = Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=_WHEN)

    assert prov.evidence_elided == 0
    with pytest.raises(ValidationError):  # a count, so never negative
        Provenance(
            source=MemorySource.OBSERVED,
            confidence=0.6,
            last_updated=_WHEN,
            evidence_elided=-1,
        )


# --- what one observation produced (ADR-0077 §9) -----------------------------


def test_an_observation_outcome_defaults_to_nothing_seen_and_nothing_lost() -> None:
    outcome = ObservationOutcome()

    assert outcome.proposals == ()
    assert outcome.discarded_unusable == 0
    assert outcome.discarded_over_limit == 0


def test_an_observation_outcomes_unusable_count_is_non_negative() -> None:
    with pytest.raises(ValidationError):
        ObservationOutcome(discarded_unusable=-1)


def test_an_observation_outcomes_over_limit_count_is_non_negative() -> None:
    with pytest.raises(ValidationError):
        ObservationOutcome(discarded_over_limit=-1)


def test_an_observation_outcome_is_frozen() -> None:
    """It is a report of what happened, so it must not be editable after the fact."""
    outcome = ObservationOutcome(discarded_unusable=1)

    with pytest.raises(ValidationError):
        outcome.discarded_unusable = 0


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


# --- the deferred question: the values that cross the queue's seam (ADR-0078) --


def _ask() -> MemoryDecision:
    return MemoryDecision(kind=MemoryDecisionKind.ASK_USER, reason="which of these do you hold?")


def _question(**changes: object) -> DeferredProposal:
    """A well-formed ``PENDING`` question, with ``changes`` applied."""
    fields: dict[str, object] = {
        "id": "d1",
        "proposal": MemoryUpdateProposal(proposed=_semantic("1"), rationale="because"),
        "decision": _ask(),
        "state": DeferralState.PENDING,
        "deferred_at": _WHEN,
        "retention": timedelta(days=30),
        "expires_at": _WHEN + timedelta(days=30),
    }
    return DeferredProposal(**(fields | changes))  # type: ignore[arg-type]  # the case names its own fields


def test_a_deferred_proposal_is_frozen_including_the_question_it_holds() -> None:
    question = _question()
    with pytest.raises(ValidationError):
        question.state = DeferralState.ACCEPTED
    with pytest.raises(ValidationError):
        question.proposal.rationale = "rewritten"


def test_a_deferred_proposal_refuses_a_field_it_does_not_declare() -> None:
    # ``extra="forbid"``: a caller inventing ``claim_id`` would otherwise get a
    # record that silently carried a capability no read is allowed to publish.
    with pytest.raises(ValidationError):
        _question(claim_id="a-token")


def test_a_deferred_proposal_refuses_a_secret_tier_proposal() -> None:
    # ADR-0004 §3 is unconditional — Tier 0 secrets live in the OS keyring, never in
    # a database or a committed file — and a durable queue is a file. Enforced on the
    # record so no conforming store can hold one however it is called (ADR-0078 §1).
    secret = MemoryUpdateProposal(
        proposed=_semantic("1"), rationale="because", sensitivity=DataTier.SECRET
    )
    with pytest.raises(ValidationError, match="SECRET"):
        _question(proposal=secret)


def test_answerability_is_half_open_at_the_instant_it_names() -> None:
    # ``Validity.live_at``'s own convention, adopted for consistency rather than
    # preference: two deadline notions in one memory system that disagree at the
    # instant they name is a defect waiting for the first test that lands on it.
    question = _question(retention=timedelta(days=1), expires_at=_WHEN + timedelta(days=1))
    assert question.is_answerable_at(_WHEN) is True
    assert question.is_answerable_at(_WHEN + timedelta(days=1) - timedelta(microseconds=1)) is True
    assert question.is_answerable_at(_WHEN + timedelta(days=1)) is False


def test_ask_me_forever_is_never_answerable_out_and_never_purgeable() -> None:
    forever = _question(retention=None, expires_at=None)
    assert forever.is_answerable_at(_WHEN + timedelta(days=10_000)) is True
    assert forever.is_purgeable_at(_WHEN + timedelta(days=10_000)) is False
    rejected = _question(
        retention=None,
        expires_at=None,
        state=DeferralState.REJECTED,
        answered_at=_WHEN,
    )
    # The half an implementation handling only the ``PENDING`` case gets wrong.
    assert rejected.is_purgeable_at(_WHEN + timedelta(days=10_000)) is False
    assert rejected.speaks_for_its_key_at(_WHEN + timedelta(days=10_000)) is True


def test_purges_two_anchors_are_different_on_purpose() -> None:
    # A terminal row is retained for one further lifetime because the no-nagging rule
    # reads it; a lapsed one has no such dependant, so giving it the same grace would
    # hold an unanswered Tier 1 proposal for **twice** the configured lifetime
    # (ADR-0078 §2).
    day = timedelta(days=1)
    lapsed = _question(retention=day, expires_at=_WHEN + day)
    assert lapsed.is_purgeable_at(_WHEN + day - timedelta(microseconds=1)) is False
    assert lapsed.is_purgeable_at(_WHEN + day) is True
    rejected = _question(
        retention=day,
        expires_at=_WHEN + day,
        state=DeferralState.REJECTED,
        answered_at=_WHEN + day,
    )
    assert rejected.is_purgeable_at(_WHEN + 2 * day - timedelta(microseconds=1)) is False
    assert rejected.is_purgeable_at(_WHEN + 2 * day) is True


def test_an_applying_row_is_never_purgeable_at_any_age() -> None:
    # The only durable record that an answer was begun. Destroying it while its
    # ingest may still be running would let the memory write commit against a
    # question that no longer exists, so the fact that an answer was given would
    # survive nowhere (ADR-0078 §2, §9).
    applying = _question(state=DeferralState.APPLYING, claimed_at=_WHEN)
    assert applying.is_purgeable_at(_WHEN + timedelta(days=10_000)) is False
    assert applying.speaks_for_its_key_at(_WHEN + timedelta(days=10_000)) is True


def test_an_applying_row_may_name_the_successor_its_answer_raised() -> None:
    # Stamped when the successor is admitted, in the same commit, so the parent
    # carries it while its own answer is still in flight — the state a cancellation
    # caught after the successor's admission leaves behind (ADR-0078 §9).
    parent = _question(state=DeferralState.APPLYING, claimed_at=_WHEN, successor_id="d2")
    assert parent.successor_id == "d2"


def test_a_lapsed_or_settled_key_stops_speaking() -> None:
    day = timedelta(days=1)
    lapsed = _question(retention=day, expires_at=_WHEN + day)
    assert lapsed.speaks_for_its_key_at(_WHEN + day) is False
    accepted = _question(
        state=DeferralState.ACCEPTED,
        claimed_at=_WHEN,
        answered_at=_WHEN,
        outcome_record_id="r1",
    )
    assert accepted.speaks_for_its_key_at(_WHEN) is False


def test_a_user_confirmation_requires_a_real_digest_and_a_named_question() -> None:
    proposal = MemoryUpdateProposal(proposed=_semantic("1"), rationale="because")
    confirmation = UserConfirmation(
        deferral_id="d1", question_key=proposal.question_key, confirmed_at=_WHEN, retires=("r1",)
    )
    assert confirmation.retires == ("r1",)
    with pytest.raises(ValidationError):
        UserConfirmation(deferral_id="d1", question_key="not-a-digest", confirmed_at=_WHEN)
    with pytest.raises(ValidationError):
        UserConfirmation(deferral_id="  ", question_key=proposal.question_key, confirmed_at=_WHEN)


def test_a_secret_tier_proposal_cannot_carry_a_confirmation() -> None:
    # A confirmation exists only because a question was queued, claimed and
    # answered — and a secret-tier proposal is never queued (ADR-0078 §1). The
    # pairing is a contradiction, not a case the applier should be left to rule on,
    # so it is unconstructable rather than merely refused downstream.
    proposal = MemoryUpdateProposal(proposed=_semantic("1"), rationale="because")
    confirmation = UserConfirmation(
        deferral_id="d1", question_key=proposal.question_key, confirmed_at=_WHEN
    )
    with pytest.raises(ValidationError, match="SECRET"):
        MemoryUpdateProposal(
            proposed=_semantic("1"),
            rationale="because",
            sensitivity=DataTier.SECRET,
            confirmation=confirmation,
        )


def test_a_proposal_carries_no_confirmation_by_default() -> None:
    assert MemoryUpdateProposal(proposed=_semantic("1"), rationale="because").confirmation is None


def test_an_ingest_result_carries_no_conflicts_by_default() -> None:
    # Additive, so no existing producer moves (ADR-0078 §4).
    result = MemoryIngestResult(decision=_ask())
    assert result.conflicts == ()


def test_the_fingerprint_and_the_key_are_lowercase_sha256_hex() -> None:
    proposal = MemoryUpdateProposal(proposed=_semantic("1"), rationale="because", conflicts=("c1",))
    for digest in (proposal.proposal_fingerprint, proposal.question_key):
        assert len(digest) == 64
        assert digest == digest.lower()
        assert set(digest) <= set("0123456789abcdef")
    # The key delegates to the fingerprint *and* the conflicts, so the two layers
    # cannot be the same value.
    assert proposal.question_key != proposal.proposal_fingerprint


def test_the_key_ignores_the_confirmation_attached_to_a_proposal() -> None:
    # What lets the writer recompute the key of a proposal it has just attached an
    # authority to: a confirmation is authority rather than content, and a key that
    # moved when one was attached would refuse every honest answer (ADR-0078 §7).
    proposal = MemoryUpdateProposal(proposed=_semantic("1"), rationale="because", conflicts=("c1",))
    confirmed = proposal.model_copy(
        update={
            "confirmation": UserConfirmation(
                deferral_id="d1", question_key=proposal.question_key, confirmed_at=_WHEN
            )
        }
    )
    assert confirmed.question_key == proposal.question_key


def test_the_key_ignores_the_rationale() -> None:
    # The projection is over the record and the tier: two producers explaining the
    # same proposal differently are asking one question.
    first = MemoryUpdateProposal(proposed=_semantic("1"), rationale="because")
    second = MemoryUpdateProposal(proposed=_semantic("1"), rationale="for another reason")
    assert first.question_key == second.question_key


@pytest.mark.parametrize(
    ("outcome", "deferral", "valid"),
    [
        (DeferralAdmissionOutcome.ADMITTED, True, True),
        (DeferralAdmissionOutcome.ADMITTED, False, False),
        (DeferralAdmissionOutcome.SUPPRESSED, True, True),
        (DeferralAdmissionOutcome.SUPPRESSED, False, False),
        (DeferralAdmissionOutcome.REFUSED, False, True),
        (DeferralAdmissionOutcome.REFUSED, True, False),
    ],
)
def test_a_deferral_admission_has_exactly_three_shapes(
    outcome: DeferralAdmissionOutcome, deferral: bool, valid: bool
) -> None:
    # Pinned the way ``MemoryDecision._outcome_fields_are_consistent`` pins a
    # ruling's. Reaching for ``admission.deferral`` on a refusal is the dereference
    # this validator exists to make impossible to write by accident (ADR-0078 §2).
    held = _question() if deferral else None
    if valid:
        assert DeferralAdmission(outcome=outcome, deferral=held).outcome is outcome
    else:
        with pytest.raises(ValidationError):
            DeferralAdmission(outcome=outcome, deferral=held)


def test_a_deferral_claim_pairs_the_question_with_its_token() -> None:
    # One value rather than two strings a caller could swap, the reason
    # ``ParkedBinding`` is one.
    claim = DeferralClaim(
        deferral=_question(state=DeferralState.APPLYING, claimed_at=_WHEN), claim_id="a-token"
    )
    assert claim.claim_id == "a-token"
    with pytest.raises(ValidationError):
        claim.claim_id = "another"
    with pytest.raises(ValidationError):
        DeferralClaim(
            deferral=_question(state=DeferralState.APPLYING, claimed_at=_WHEN), claim_id="   "
        )


def test_the_terminal_states_are_exactly_the_four_that_record_an_answer() -> None:
    # Exported as a frozenset so a consumer can branch exhaustively rather than
    # re-enumerating the members (ADR-0078 §2).
    assert {
        DeferralState.ACCEPTED,
        DeferralState.REJECTED,
        DeferralState.STALE,
        DeferralState.REDEFERRED,
    } == TERMINAL_DEFERRAL_STATES
    assert DeferralState.PENDING not in TERMINAL_DEFERRAL_STATES
    assert DeferralState.APPLYING not in TERMINAL_DEFERRAL_STATES


def test_there_is_no_expired_deferral_state() -> None:
    # Expiry is read-time-relative and never stamped, exactly as
    # ``MemoryRecord.expires_at`` is: nothing has to run for a question to stop
    # being answerable, and there is no sweep whose failure re-opens one
    # (ADR-0078 §2, §6).
    assert "EXPIRED" not in DeferralState.__members__
