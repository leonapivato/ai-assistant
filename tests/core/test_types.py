"""Tests for the shared memory domain types."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from ai_assistant.core.types import (
    MAX_EVIDENCE_CITATIONS,
    Attestation,
    BeliefBand,
    DataTier,
    EpisodicMemory,
    FeedbackEvent,
    FeedbackKind,
    MemoryBase,
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
    Placement,
    PlacementReach,
    PlacementSetter,
    PreferenceMemory,
    ProceduralMemory,
    Provenance,
    QuestionPart,
    Role,
    SemanticMemory,
    UserConfirmation,
    Validity,
    band_of,
    rests_on_recorded_external_content,
)

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)
_LATER = datetime(2026, 6, 1, tzinfo=UTC)

#: The attestation an `EXTERNAL` provenance must carry since ADR-0092 §1. Named so
#: the cases below say "attested" once rather than repeating the two halves.
_ATTESTED_BY = Attestation(reported_by="calendar:work", reported_at=_WHEN)


def _attestation_for(source: MemorySource) -> Attestation | None:
    """What ``source`` is obliged to carry: an attestation iff it is ``ATTESTED``.

    The iff of ADR-0092 §1, read from :func:`band_of` rather than from a list of
    sources, so a `MemorySource` added later gets the right answer here without an
    edit and the cases below stay total over the enum.
    """
    return _ATTESTED_BY if band_of(source) is BeliefBand.ATTESTED else None


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
# takes.


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
    prov = Provenance(
        source=MemorySource.EXTERNAL,
        confidence=1.0,
        last_updated=_WHEN,
        attestation=_ATTESTED_BY,
    )

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
            continue  # neither *confidence* rule binds it
        with pytest.raises(ValidationError):
            Provenance(
                source=source,
                confidence=forbidden,
                last_updated=_WHEN,
                attestation=_attestation_for(source),
            )


# --- the attestation: what reported it, and when (ADR-0092 §1, §3) -----------


def test_an_attestation_carries_both_halves() -> None:
    """The two halves ADR-0073 §4 asks for, held together in one value."""
    attestation = Attestation(reported_by="calendar:work", reported_at=_WHEN)

    assert attestation.reported_by == "calendar:work"
    assert attestation.reported_at == _WHEN


@pytest.mark.parametrize("missing", ["reported_by", "reported_at"], ids=str)
def test_neither_half_of_an_attestation_is_optional(missing: str) -> None:
    """A half-answer is unconstructable, which is the whole point of the object.

    ADR-0092 §2 rejected two nullable fields on `Provenance` for exactly this: they
    admit four states, two of which are half-answers a surface renders as "your
    calendar had this as of ___" or attributes to nobody. Both fields required
    inside one optional slot makes those states unreachable rather than merely
    discouraged.
    """
    fields = {"reported_by": "calendar:work", "reported_at": _WHEN}
    del fields[missing]

    with pytest.raises(ValidationError):
        Attestation(**fields)  # type: ignore[arg-type]  # the point is the missing field


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"], ids=repr)
def test_a_blank_reporter_is_refused(blank: str) -> None:
    """`reported_by` is non-empty (ADR-0092 §1): a source that identifies nothing.

    It is the only durable handle the record keeps on where it came from, because
    ADR-0092 §6 rules that an import's id is ours and minted per sync — so a blank
    here is a record that can never say who reported it.
    """
    with pytest.raises(ValidationError):
        Attestation(reported_by=blank, reported_at=_WHEN)


def test_a_naive_report_time_is_refused() -> None:
    """`reported_at` is a `UtcInstant`, so ADR-0023 §3's refusal reaches it too."""
    with pytest.raises(ValidationError):
        Attestation(reported_by="calendar:work", reported_at=datetime(2026, 1, 1))  # noqa: DTZ001


def test_an_attested_provenance_must_carry_an_attestation() -> None:
    """The first half of the iff: set when the band is `ATTESTED` (ADR-0092 §1).

    ADR-0073 §4 makes carrying both halves "a precondition of [the producer]
    shipping", and this is what turns that from procedural into structural: a
    precondition a producer satisfies by remembering is one it can fail by
    forgetting, and the failure is silent — an attested record with no attestation
    renders exactly the misleading answer §4's floor forbids.
    """
    with pytest.raises(ValidationError, match="must carry an attestation"):
        Provenance(source=MemorySource.EXTERNAL, confidence=1.0, last_updated=_WHEN)


@pytest.mark.parametrize(
    "source",
    [source for source in MemorySource if band_of(source) is not BeliefBand.ATTESTED],
    ids=str,
)
def test_a_non_attested_provenance_may_not_carry_an_attestation(source: MemorySource) -> None:
    """The second half of the iff: absent otherwise (ADR-0092 §1).

    This half keeps `source` the single classifier. ADR-0072 §4 rules that
    classification "is keyed on ``source`` and never on ``confidence``, so no
    producer can promote a belief into the asserted band by claiming certainty"; an
    attestation on an `INFERRED` record would be the same laundering by a different
    field — a derived guess wearing a citation to a system that never reported it.

    Parametrised by *band* rather than by a written-out list of sources, so a
    `MemorySource` added later is covered without an edit.
    """
    confidence = 1.0 if source is MemorySource.USER_ASSERTED else 0.6

    with pytest.raises(ValidationError, match="must not carry an attestation"):
        Provenance(
            source=source,
            confidence=confidence,
            last_updated=_WHEN,
            attestation=_ATTESTED_BY,
        )


def test_the_attestation_rule_is_stated_over_the_whole_source_enum() -> None:
    """Totality, the shape `_EXPECTED_BANDS` uses: every source, both directions.

    A `MemorySource` added later cannot slip past the iff by being absent from a
    hand-written list — the obligation is derived from `band_of`, which is itself
    total and mechanically enforced (ADR-0072 §2).
    """
    for source in MemorySource:
        confidence = 1.0 if source is MemorySource.USER_ASSERTED else 0.6
        obliged = band_of(source) is BeliefBand.ATTESTED
        permitted = _ATTESTED_BY if obliged else None
        refused = None if obliged else _ATTESTED_BY

        prov = Provenance(
            source=source,
            confidence=confidence,
            last_updated=_WHEN,
            attestation=permitted,
        )
        assert (prov.attestation is not None) is obliged
        with pytest.raises(ValidationError):
            Provenance(
                source=source,
                confidence=confidence,
                last_updated=_WHEN,
                attestation=refused,
            )


def test_a_report_time_before_our_revision_is_the_normal_case() -> None:
    """Monday's report, revised into the store on Tuesday (ADR-0092 §3).

    The two fields are two different clocks — `reported_at` is the source's, and
    `last_updated` is ours (ADR-0045 §3) — so this ordering is the point of
    carrying both, not an anomaly. A consumer treating the pair as an ordering
    invariant has misunderstood which clock each belongs to.
    """
    prov = Provenance(
        source=MemorySource.EXTERNAL,
        confidence=0.9,
        last_updated=_LATER,
        attestation=Attestation(reported_by="calendar:work", reported_at=_WHEN),
    )

    assert prov.attestation is not None
    assert prov.attestation.reported_at < prov.last_updated


def test_a_report_time_in_our_future_is_not_refused() -> None:
    """Source clocks skew, and skew is a rendering concern (ADR-0092 §3).

    A validator comparing the two would refuse a record that is perfectly
    encodable, perfectly readable and merely early — inventing a read-path failure,
    which is precisely what ADR-0086 §3's admissibility test permits this
    validator to avoid. Nothing in `core` compares them.
    """
    prov = Provenance(
        source=MemorySource.EXTERNAL,
        confidence=0.9,
        last_updated=_WHEN,
        attestation=Attestation(reported_by="calendar:work", reported_at=_LATER),
    )

    assert prov.attestation is not None
    assert prov.attestation.reported_at > prov.last_updated


def test_an_attested_provenance_round_trips_through_json() -> None:
    """The validator runs on *decode* too, which is why the store scan preceded it.

    `SqliteMemoryStore` reconstructs every record through the model on every read,
    so this is the path ADR-0086 §3's admissibility test is about: what the type
    accepts here is what a deployment can read back.
    """
    prov = Provenance(
        source=MemorySource.EXTERNAL, confidence=0.9, last_updated=_WHEN, attestation=_ATTESTED_BY
    )

    restored = Provenance.model_validate_json(prov.model_dump_json())

    assert restored == prov
    assert restored.attestation == _ATTESTED_BY


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


# --- currency's confirming instant (ADR-0109) --------------------------------


def test_provenance_defaults_to_an_unknown_confirming_instant() -> None:
    """``None`` is ADR-0103 §9's *unknown*, and it is what a record decodes at.

    ``is None`` exactly, never merely falsy: unknown is a distinct state rather
    than a small number, and no surface may read it as either fresh or stale. The
    sibling case that keeps this from being vacuous is the one below, which
    constructs a concrete instant over the same field — without it, ``is None``
    passes against a type that has no such field at all.

    Additive with a default is also the whole of ADR-0109 §8's no-migration claim:
    a record stored before this decision deserialises here, at ``None``.
    """
    prov = Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=_WHEN)

    assert prov.last_confirmed_at is None


def test_no_validator_pins_the_confirming_instant_to_the_two_it_could_be_ordered_by() -> None:
    """The absence is the decision (ADR-0109 §8), so both states construct.

    Each candidate invariant refuses something legitimate, which is ADR-0086 §3's
    test — "does it refuse something that already worked":

    * ``last_confirmed_at <= last_updated`` would refuse the *ordinary* attested
      case rather than a pathological one. A ``reported_at`` in our future "is not
      refused" (ADR-0092 §3) and ADR-0109 §4 stores it as it stands, so a record
      legitimately carries a confirming instant later than the write that stored
      it.
    * ``last_confirmed_at == attestation.reported_at`` for the ``ATTESTED`` band
      would refuse precisely the survivor ADR-0103 §6 mandates: after a
      corroborating fold the record keeps the *target's* attestation while the
      instant may have advanced to the incoming derived record's. The two fields
      are not redundant, and their disagreement is meaningful rather than drift.

    Pinned here rather than left implicit, so a later lane adding either validator
    breaks this case instead of discovering the problem in somebody's store —
    ADR-0107 §4's precedent for stating an absence as a ruling.
    """
    ahead_of_the_write = Provenance(
        source=MemorySource.OBSERVED,
        confidence=0.6,
        last_updated=_WHEN,
        last_confirmed_at=_LATER,
    )
    assert ahead_of_the_write.last_confirmed_at == _LATER
    assert ahead_of_the_write.last_confirmed_at > ahead_of_the_write.last_updated

    disagreeing = Provenance(
        source=MemorySource.EXTERNAL,
        confidence=0.9,
        last_updated=_LATER,
        attestation=_ATTESTED_BY,
        last_confirmed_at=_LATER,
    )
    assert disagreeing.attestation is not None
    assert disagreeing.last_confirmed_at != disagreeing.attestation.reported_at


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


# --- the derived-taint marker and its predicate (ADR-0106 §1, §2, §10) -------


def test_a_record_decoded_without_the_marker_reads_false() -> None:
    """ADR-0106 §10's first clause, and the whole of its no-backfill argument.

    Decoded from a mapping that has never heard of the field — the shape a record
    stored before this decision deserialises from — rather than merely constructed
    without it, because the claim is about the *read* path. A pre-field derived
    record decodes ``False`` and that is true of it: no ``EXTERNAL`` citation
    exists to have been recorded. A pre-field attested record decodes ``False``
    too and that says nothing about it at all, which is why the predicate below
    and not the field is what any consumer asks.
    """
    stored = {"source": MemorySource.OBSERVED.value, "confidence": 0.6, "last_updated": _WHEN}

    prov = Provenance.model_validate(stored)

    assert prov.derived_from_external is False


def test_the_predicate_is_true_for_an_attested_record_carrying_no_marker() -> None:
    """ADR-0106 §10's second clause: it fails an implementation that reads the field.

    An import's externality is already recorded — the ``ATTESTED`` band is reached
    only through a source whose whole meaning is that someone else reported the
    belief — so the marker is absent there by design (ADR-0106 §1). A predicate
    that read ``derived_from_external`` instead of the band would call the most
    plainly external record in the store untainted.
    """
    prov = Provenance(
        source=MemorySource.EXTERNAL,
        confidence=0.9,
        last_updated=_WHEN,
        attestation=_ATTESTED_BY,
    )

    assert prov.derived_from_external is False
    assert rests_on_recorded_external_content(prov) is True


def test_the_predicate_is_false_for_a_user_assertion_carrying_the_marker() -> None:
    """ADR-0106 §10's third clause: it fails an implementation that drops the band guard.

    ADR-0106 §7 forbids a band-keyed validator on the field, so this record
    constructs — and an unguarded disjunction would report the user's own word as
    resting on external content, which ADR-0098 §1 forbids in principle. The
    record is malformed rather than adversarial, and the honest answer honours the
    classifier the corpus keys everything else on (ADR-0072 §4).
    """
    prov = Provenance(
        source=MemorySource.USER_ASSERTED,
        confidence=1.0,
        last_updated=_WHEN,
        derived_from_external=True,
    )

    assert rests_on_recorded_external_content(prov) is False


@pytest.mark.parametrize("marked", [True, False])
@pytest.mark.parametrize(
    "source", [s for s in MemorySource if band_of(s) is BeliefBand.DERIVED], ids=str
)
def test_the_predicate_reads_the_marker_in_the_derived_band(
    source: MemorySource, marked: bool
) -> None:
    """The one band where the field decides, over every source in it.

    Without this the two cases above are jointly satisfied by a predicate that
    ignores the field entirely and answers from ``band_of`` alone.
    """
    prov = Provenance(
        source=source, confidence=0.6, last_updated=_WHEN, derived_from_external=marked
    )

    assert rests_on_recorded_external_content(prov) is marked


def test_the_marker_survives_a_json_round_trip() -> None:
    """It is durable state on a stored record, not a transient of the write path."""
    prov = Provenance(
        source=MemorySource.INFERRED, confidence=0.6, last_updated=_WHEN, derived_from_external=True
    )

    restored = Provenance.model_validate_json(prov.model_dump_json())

    assert restored.derived_from_external is True
    assert restored == prov


@pytest.mark.parametrize("marked", [True, False])
@pytest.mark.parametrize("source", list(MemorySource), ids=str)
def test_no_validator_conditions_the_marker_on_the_band(source: MemorySource, marked: bool) -> None:
    """The absence is the decision (ADR-0106 §7), so every band constructs both ways.

    A validator asserting ``ATTESTED ⟹ True`` would refuse, on *decode*, every
    attested record ``readers.calendar`` has already written — ADR-0086 §3's "does
    it refuse something that already worked", answered yes. ADR-0092 §1 could land
    such a validator because ADR-0092 §2 had verified the band was empty; that
    verification has expired, and on this axis "now or never" is answered *never*.
    Stated over the whole enum rather than over the two interesting members, so a
    ``MemorySource`` added later is covered without an edit here.
    """
    prov = Provenance(
        source=source,
        confidence=1.0 if source is MemorySource.USER_ASSERTED else 0.6,
        last_updated=_WHEN,
        attestation=_attestation_for(source),
        derived_from_external=marked,
    )

    assert prov.derived_from_external is marked


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


def test_a_conditional_write_without_an_expectation_is_refused_at_construction() -> None:
    # ADR-0219 §2's validator, first state. An IF_UNCHANGED element carrying no
    # expectation reaches write time with nothing to compare — and §1's reservation
    # of `0` means a store comparing against a *defaulted* one would simply always
    # refuse, which is a write that mysteriously never lands rather than a caller
    # mistake anybody can see. Refused where it is made instead.
    with pytest.raises(ValidationError, match="expected_revision"):
        MemoryWrite(record=_semantic("1"), mode=MemoryWriteMode.IF_UNCHANGED)


@pytest.mark.parametrize(
    "mode", [MemoryWriteMode.UPSERT, MemoryWriteMode.INSERT_IF_ABSENT], ids=str
)
def test_an_expectation_on_a_non_conditional_write_is_refused(mode: MemoryWriteMode) -> None:
    # ADR-0219 §2's validator, second state: an expectation no mode honours. Taking
    # it silently would let a caller believe a write was conditional when the store
    # was never asked to compare anything — the fail-open direction, on the door the
    # mode exists to close.
    with pytest.raises(ValidationError, match="expected_revision"):
        MemoryWrite(record=_semantic("1"), mode=mode, expected_revision=1)


def test_a_negative_expectation_is_refused() -> None:
    # `ge=0` on the field. No store issues a negative stamp, so a negative
    # expectation is a caller that computed one rather than read one.
    with pytest.raises(ValidationError):
        MemoryWrite(record=_semantic("1"), mode=MemoryWriteMode.IF_UNCHANGED, expected_revision=-1)


def test_a_conditional_write_carrying_its_expectation_constructs() -> None:
    # The positive case beside the two refusals, so the validator is shown to admit
    # the one state it must. `0` is admissible at construction — §1 closes it at the
    # store, where no row can carry it — and the two closures are deliberately two.
    write = MemoryWrite(
        record=_semantic("1"), mode=MemoryWriteMode.IF_UNCHANGED, expected_revision=7
    )
    assert write.mode is MemoryWriteMode.IF_UNCHANGED
    assert write.expected_revision == 7


def test_a_record_no_store_has_stored_carries_the_default_revision() -> None:
    # ADR-0219 §1: `0` is issued by no store and is the field's default, so a record
    # a caller constructed is distinguishable from every record a store has stored
    # — and no caller-constructed default can equal a stored value.
    assert _semantic("1").revision == 0
    # `ge=0` at construction. `model_copy(update=...)` deliberately bypasses
    # validation, so the refusal is asserted where a value actually arrives.
    with pytest.raises(ValidationError):
        SemanticMemory.model_validate(_semantic("1").model_dump() | {"revision": -1})


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


def test_feedback_event_constructs_with_defaults() -> None:
    event = FeedbackEvent(
        kind=FeedbackKind.PREFERENCE,
        memory_kind=MemoryKind.PREFERENCE,
        content="prefers concise replies",
        created_at=_WHEN,
    )
    assert event.subject is None
    assert event.evidence == ()
    assert event.guarded is False


def test_a_feedback_events_guard_is_absent_by_default_and_carried_when_set() -> None:
    """ADR-0217 §7: the owner's explicit placement act at write, defaulting to none.

    Defaulted so that no existing producer becomes wrong on the day the member
    lands: ``False`` is **not an act of any kind**, and a record built from it
    carries §6's default placement, which is ADR-0199 §3's placement of its class.
    That is also what makes ``assistant learn --guarded`` a purely additive
    follow-on consumer lane rather than a change nothing compiles without
    (ADR-0217 §11) — nothing is red between the two.

    It is a ``bool`` and not a :class:`Placement`, because the act it records has
    exactly one direction: there is no widening act at write, which on a fresh
    record would be a no-op, and the reach and setter it writes are fixed by §7
    rather than chosen by the caller. A ``Placement`` on the event would let a
    client author a setter — ``DERIVED`` above all, the one stamp §3's closing
    clause forbids an owner's act to lift — over the wire.
    """
    guarded = FeedbackEvent(
        kind=FeedbackKind.PREFERENCE,
        memory_kind=MemoryKind.PREFERENCE,
        content="prefers concise replies",
        created_at=_WHEN,
        guarded=True,
    )

    assert guarded.guarded is True
    assert FeedbackEvent.model_validate_json(guarded.model_dump_json()) == guarded


def test_feedback_event_memory_kind_is_optional_and_absent_by_default() -> None:
    """ADR-0122 §1: a field every producer had to fill, some of which cannot.

    That is the whole defect. The CLI did not know, could not know, and was made to
    answer anyway — and the answer it invented was indistinguishable at every layer
    downstream from one a user had chosen deliberately. ``None`` means "resolve it
    from the belief this touches"; it never means the record type is *unknowable*,
    and it is never stored on a record.

    It is ``None`` rather than a sentinel ``MemoryKind`` member because a member
    would enter every exhaustive ``match`` over ``MemoryKind`` in the tree — and
    every kind filter on ``search`` and ``list_beliefs`` — to express a state no
    record ever carries. ``MemoryKind`` is a record's *type*; a request that has not
    chosen one is not a type.
    """
    event = FeedbackEvent(
        kind=FeedbackKind.CORRECTION,
        content="the office is in Boston",
        created_at=_WHEN,
    )

    assert event.memory_kind is None
    assert {member.value for member in MemoryKind} == {
        "semantic",
        "preference",
        "procedural",
        "episodic",
    }, "no sentinel member was added"


def test_an_absent_memory_kind_is_rendered_as_null_rather_than_omitted() -> None:
    """ADR-0122 §1: "absent" is spelled ``null``, and the codec needs no change.

    ``wire``'s ``project`` renders a model through ``model_dump()``, which emits
    every field including a defaulted one and gives ``None`` a form of its own — so
    an unpinned correction crosses as ``"memory_kind": null`` rather than as a
    missing member, and no projection change is owed. It is also exactly why the
    *protocol version* is owed: a version 1 hub refuses that ``null`` for a required
    ``MemoryKind``, inside a ``learn`` rather than at the handshake, unless the two
    versions disagree at connect.
    """
    event = FeedbackEvent(
        kind=FeedbackKind.CORRECTION,
        content="the office is in Boston",
        created_at=_WHEN,
    )

    assert "memory_kind" in event.model_dump()
    assert event.model_dump()["memory_kind"] is None


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


# --- the subject axis: whom a belief is about (ADR-0100) ---------------------


def _believed(subject: str | None = None) -> SemanticMemory:
    """One well-formed semantic record, varying only its stated subject."""
    return SemanticMemory(
        id="r1",
        content="prefers a window seat",
        fact="prefers a window seat",
        about_person=subject,
        provenance=Provenance(
            source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_WHEN
        ),
    )


def test_a_record_states_no_subject_by_default() -> None:
    """``None`` is "no subject stated", which ADR-0100 §3 reads as the owner's.

    Not "unknown", and not a spelling of the owner: there is no user identity in
    this system to name them by (ADR-0036 §3, ADR-0097 §1), so the absence is the
    owner's only spelling and a second one could never be reconciled with it.
    """
    assert _believed().about_person is None


def test_a_stated_subject_is_kept_byte_for_byte() -> None:
    """A label is stored exactly as given (ADR-0100 §6).

    Surrounding whitespace is the case that matters, because it is the one a
    validator is most tempted to tidy: :data:`Identifier` strips, and this field
    must not. Verbatim storage is what leaves every later matching rule available
    — none can be recovered from labels normalised on the way in.
    """
    assert _believed("  Marta  ").about_person == "  Marta  "


def test_two_spellings_of_one_name_are_two_subjects() -> None:
    """Nothing in this type resolves a label to a person (ADR-0100 §6).

    ``"Marta"`` and ``"marta"`` are two subjects to every piece of code in the
    system until ADR-0101's matching rule is implemented — a cost paid
    deliberately, in the one place it can be paid off later without rewriting
    stored data.
    """
    assert _believed("Marta").about_person != _believed("marta").about_person


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_a_record_refuses_a_blank_subject(blank: str) -> None:
    """Two states, never three (ADR-0100 §1).

    A record stating ``""`` as its subject is a producer that meant to speak and
    said nothing, and it must not be representable — ADR-0092 §2's discipline for
    making half-states unconstructable, applied to a single datum.
    """
    with pytest.raises(ValidationError, match="must not be blank"):
        _believed(blank)


def test_the_subject_enters_a_proposal_fingerprint() -> None:
    """A belief about Marta is not the same offer as one about the owner.

    ``proposal_fingerprint`` projects the whole record minus three bookkeeping
    fields, so the subject enters it with no change to that projection —
    deliberately (ADR-0100 §1): the two are different things to be asked to
    accept, exactly as ADR-0078 §7 argues of ``validity``.
    """
    owners = MemoryUpdateProposal(proposed=_believed(), rationale="because")
    martas = MemoryUpdateProposal(proposed=_believed("Marta"), rationale="because")

    assert owners.proposal_fingerprint != martas.proposal_fingerprint


def test_the_confirming_instant_enters_a_proposal_fingerprint() -> None:
    """ADR-0078 §7's criterion applied, not amended (ADR-0109 §8).

    The projection is "the whole record minus the fields that are bookkeeping
    about the record rather than the belief it states", and ``core/types.py``
    records that the criterion "decides the next one rather than an inventory
    having to be extended by whoever adds it". ``last_confirmed_at`` is a fact
    about the belief — when the world last confirmed it — so it is *in*, and the
    checkable form of that is two proposals differing only here.

    Contrast ``provenance.last_updated``, which is excluded because two identical
    observations a minute apart carry different stamps and the user would be
    nagged by the mechanism whose job is to stop that. The nag is unreachable
    through this field in any band: a ``DERIVED`` re-observation of the same
    episodes yields the same maximum, an ``ATTESTED`` re-import carries the same
    ``reported_at``, and two distinct utterances are a second confirming act
    rather than a second look at one.
    """
    when = _WHEN
    later = _LATER

    def proposed(confirmed_at: datetime) -> MemoryUpdateProposal:
        record = _believed().model_copy(
            update={
                "provenance": Provenance(
                    source=MemorySource.USER_ASSERTED,
                    confidence=1.0,
                    last_updated=when,
                    last_confirmed_at=confirmed_at,
                )
            }
        )
        return MemoryUpdateProposal(proposed=record, rationale="because")

    assert proposed(when).proposal_fingerprint != proposed(later).proposal_fingerprint
    # ...and it is genuinely *this* field doing it: the same value twice agrees,
    # so the inequality above is not two arbitrary digests over a jittering record.
    assert proposed(later).proposal_fingerprint == proposed(later).proposal_fingerprint


def test_a_feedback_event_states_no_subject_by_default() -> None:
    event = FeedbackEvent(
        kind=FeedbackKind.PREFERENCE,
        memory_kind=MemoryKind.PREFERENCE,
        content="prefers a window seat",
        created_at=_WHEN,
    )
    assert event.about_person is None


def test_a_feedback_event_keeps_its_scope_and_its_subject_apart() -> None:
    """``subject`` is a preference scope; ``about_person`` is whom it is about.

    Side by side on one type is the clearest statement that they are two axes
    (ADR-0100 §7), and the older field keeps its name and its meaning — no lane
    may rename it on ADR-0100's authority (#688).
    """
    event = FeedbackEvent(
        kind=FeedbackKind.PREFERENCE,
        memory_kind=MemoryKind.PREFERENCE,
        content="prefers a window seat",
        subject="travel",
        about_person="Marta",
        created_at=_WHEN,
    )

    assert event.subject == "travel"
    assert event.about_person == "Marta"


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_a_feedback_event_refuses_a_blank_subject(blank: str) -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        FeedbackEvent(
            kind=FeedbackKind.PREFERENCE,
            memory_kind=MemoryKind.PREFERENCE,
            content="prefers a window seat",
            about_person=blank,
            created_at=_WHEN,
        )


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


# --- a memory proposal: its authority and its question key (ADR-0078) -------


def _ask() -> MemoryDecision:
    return MemoryDecision(kind=MemoryDecisionKind.ASK_USER, reason="which of these do you hold?")


def test_a_user_confirmation_requires_a_real_digest_and_a_named_question() -> None:
    proposal = MemoryUpdateProposal(proposed=_semantic("1"), rationale="because")
    confirmation = UserConfirmation(
        question=QuestionPart(round="d1", part=1),
        question_key=proposal.question_key,
        confirmed_at=_WHEN,
        retires=("r1",),
    )
    assert confirmation.retires == ("r1",)
    with pytest.raises(ValidationError):
        UserConfirmation(
            question=QuestionPart(round="d1", part=1),
            question_key="not-a-digest",
            confirmed_at=_WHEN,
        )
    with pytest.raises(ValidationError):
        UserConfirmation(
            question=QuestionPart(round="  ", part=1),
            question_key=proposal.question_key,
            confirmed_at=_WHEN,
        )


def test_a_secret_tier_proposal_cannot_carry_a_confirmation() -> None:
    # A confirmation exists only because a question was queued, claimed and
    # answered — and a secret-tier proposal is never queued (ADR-0078 §1). The
    # pairing is a contradiction, not a case the applier should be left to rule on,
    # so it is unconstructable rather than merely refused downstream.
    proposal = MemoryUpdateProposal(proposed=_semantic("1"), rationale="because")
    confirmation = UserConfirmation(
        question=QuestionPart(round="d1", part=1),
        question_key=proposal.question_key,
        confirmed_at=_WHEN,
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
                question=QuestionPart(round="d1", part=1),
                question_key=proposal.question_key,
                confirmed_at=_WHEN,
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


def test_a_record_whose_model_dump_lies_is_fingerprinted_on_its_real_field_state() -> None:
    """``model_dump`` is an ordinary attribute, and this fingerprint is a key.

    An instance can shadow the method through ``__dict__`` — the bypass
    ``frozen=True`` leaves open, and the one ``permissions/_detachment.py`` and
    :attr:`RecipientGrant.subject_digest` already close about the same method — so
    a projection built by *calling* it would fingerprint whatever that mapping
    described rather than the record. The
    consequence here is ADR-0078 §7's: the coordinator digests at admission and
    the writer recomputes at answer time, so a record able to nominate its own
    fingerprint is a record able to collide with a question the user has already
    answered, or to escape one they have not.
    """
    record = _semantic("1")
    elsewhere = _semantic("1").model_copy(update={"fact": "something else entirely"})
    record.__dict__["model_dump"] = elsewhere.model_dump
    proposal = MemoryUpdateProposal(proposed=record, rationale="because")

    honest = MemoryUpdateProposal(proposed=_semantic("1"), rationale="because")
    lie = MemoryUpdateProposal(proposed=elsewhere, rationale="because")

    assert proposal.proposal_fingerprint == honest.proposal_fingerprint
    assert proposal.proposal_fingerprint != lie.proposal_fingerprint


def test_a_subclass_of_a_record_is_fingerprinted_under_the_declared_union() -> None:
    """The projection is taken under ``MemoryRecord``, not ``type(proposed)``.

    The same rule ``_detached_tool`` states by rebuilding as a
    :class:`ToolDefinition` and never as ``type(value)``: a subclass's extra
    fields are outside the schema the key is taken under rather than silently
    inside it. Otherwise two proposals agreeing in every field
    :data:`MemoryRecord` declares would be two questions on a difference the user
    was never shown — ``topics``' argument (ADR-0213 §10), reached through the
    type instead of through a field.
    """

    class NotedSemanticMemory(SemanticMemory):
        note_to_self: str = "not part of the belief"

    subclassed = NotedSemanticMemory(
        id="1",
        content="c",
        fact="f",
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.4, last_updated=_WHEN),
    )
    proposal = MemoryUpdateProposal(proposed=subclassed, rationale="because")
    plain = MemoryUpdateProposal(proposed=_semantic("1"), rationale="because")

    assert proposal.proposal_fingerprint == plain.proposal_fingerprint


def test_the_fingerprint_and_the_key_survive_a_json_round_trip() -> None:
    """ADR-0078 §10 item 24's parity, pinned where the projection is taken.

    The projection is built in JSON mode precisely so a proposal reconstructed
    from a serialised form digests identically to the one it was serialised from
    — "the failure it guards is not a mismatch on some input but a mismatch on
    *every* input". The store's conformance suite owns the clause end to end;
    this guards the serializer this projection resolves, so a change to it that
    left JSON mode behind is a red test here rather than a hub whose every
    asserted conflict has stopped being confirmable.
    """
    proposal = MemoryUpdateProposal(proposed=_semantic("1"), rationale="because", conflicts=("c1",))

    rebuilt = MemoryUpdateProposal.model_validate(proposal.model_dump(mode="json"))

    assert rebuilt.proposal_fingerprint == proposal.proposal_fingerprint
    assert rebuilt.question_key == proposal.question_key


# --- ADR-0217 §1: the question ADR-0204 put on the warrant moved ------------


def test_the_warrant_no_longer_carries_who_may_receive_the_record() -> None:
    """ADR-0217 §1: the field is removed from :class:`Provenance`, not kept beside.

    ADR-0204 §1 placed ``supplied_withheld_content`` here correctly, under
    :class:`MemoryBase`'s own placement rule — *what material stood in front of the
    producer* is this class's question. What moved is the question: two further
    setters now write the slot, so it asks *who may receive this record*, which is
    the envelope's. Keeping a boolean warrant fact beside the placement would put two
    recorded values in front of one read, and "a supply site that consulted the
    placement and not the mark would speak a record ADR-0204 withholds, and the
    mistake is silent".

    The arms this replaces — the decode default, the round trip, and the band-blind
    construction — are taken over :class:`Placement` in
    ``tests/core/test_placement.py``, which is where the answer now lives.
    """
    assert "supplied_withheld_content" not in Provenance.model_fields
    assert "placement" in MemoryBase.model_fields


@pytest.mark.parametrize("source", list(MemorySource), ids=str)
def test_no_validator_conditions_a_placement_on_the_band(source: MemorySource) -> None:
    """Every band carries a narrowed record, because the question is about supply.

    ADR-0204 §1's arm, restated over reach ``OWNER`` in place of ``True`` (ADR-0217
    §10's equivalence). The question has an answer for a record of any band — an
    episode capture narrows, a belief a producer derived inherits, and a calendar
    import carries the default because its producer's inputs are not records of this
    store. Stated over the whole enum so a ``MemorySource`` added later is covered
    without an edit here.
    """
    record = SemanticMemory(
        id="s1",
        content="a fact",
        fact="a fact",
        provenance=Provenance(
            source=source,
            confidence=1.0 if source is MemorySource.USER_ASSERTED else 0.6,
            last_updated=_WHEN,
            attestation=_attestation_for(source),
        ),
        placement=Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED),
    )

    assert record.placement.reach is PlacementReach.OWNER
