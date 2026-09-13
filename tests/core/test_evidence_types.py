"""ADR-0252's evidence contract: the row's four axes and §2's three relations.

The **type-level** half of ADR-0252 §18's arms. What a store does with a row is
``tests/planning/plan_store_contract.py``'s; what a *loop* composes into one is I2's
(§17). What is here is everything the types themselves decide: which shapes construct,
which refuse, and what the coverage and overlap relations answer — because those
relations are read by §6's sufficiency tests, §7's conflict test, §8's refresh limbs
and §9's invalidation predicate, and "a second statement of it is a second place for
the unbounded case to be got wrong".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    MAX_APPLICABILITY_VALUES,
    MAX_EVIDENCE_RECORDS,
    MAX_SUPPORTED_REGIONS,
    EvidenceApplicability,
    EvidenceBasis,
    EvidenceHistory,
    EvidenceStanding,
    GoalElement,
    GoalEvidence,
    GoalInterpretation,
    Ground,
    ReadKind,
    ReadOutcomeKind,
    TimeWindow,
    evidence_order,
    support_covers,
    support_covers_support,
    support_overlaps,
)

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)
_SATURDAY = TimeWindow(start=datetime(2026, 1, 3, tzinfo=UTC), end=datetime(2026, 1, 4, tzinfo=UTC))
_SUNDAY = TimeWindow(start=datetime(2026, 1, 4, tzinfo=UTC), end=datetime(2026, 1, 5, tzinfo=UTC))
_WEEK = TimeWindow(start=datetime(2026, 1, 1, tzinfo=UTC), end=datetime(2026, 1, 8, tzinfo=UTC))


def _row(**overrides: object) -> GoalEvidence:
    """A ``STANDING`` ``READ_OUTCOME`` row, in the shape ADR-0252 §1 admits."""
    fields: dict[str, object] = {
        "id": "ev1",
        "goal_id": "g1",
        "attempt_id": "a1",
        "basis": EvidenceBasis.READ_OUTCOME,
        "read_kind": ReadKind.SIGHTED_QUERY,
        "supported": (EvidenceApplicability(topics=("weather",)),),
        "supported_elided": 0,
        "read_at": _WHEN,
        "records": ("m1",),
        "returned": 1,
        "admitted": 1,
        "verdict": ReadOutcomeKind.RETURNED_RECORDS.value,
        "standing": EvidenceStanding.STANDING,
    }
    fields.update(overrides)
    return GoalEvidence(**fields)  # type: ignore[arg-type]


# --- §1: the row's four validator axes -------------------------------------


def test_the_two_bases_are_closed_and_spelled_by_member_name() -> None:
    """§1: "closed at exactly two members", each valued by its lower-cased name."""
    assert [member.value for member in EvidenceBasis] == ["read_outcome", "interpretation"]


def test_a_read_outcome_row_carries_a_kind_and_no_declaration() -> None:
    """§1's first axis, in both directions."""
    assert _row().read_kind is ReadKind.SIGHTED_QUERY

    with pytest.raises(ValidationError, match="read_kind and no declaration"):
        _row(read_kind=None, records=(), returned=0, admitted=0)
    with pytest.raises(ValidationError, match="read_kind and no declaration"):
        _row(declaration="d1")


def test_an_interpretation_row_constructs_and_no_count_invariant_refuses_it() -> None:
    """§1's first axis on the second basis, and ADR-0252 §18 arm 24's last sentence.

    "An ``INTERPRETATION`` row constructs: exactly one member of ``records``,
    ``returned`` and ``admitted`` both 0, no ``read_kind``, a required ``declaration``
    — and no count invariant refuses it." That is why §1 states **no** inequality over
    ``len(records)``: one read over every row would demand ``1 <= 0`` here and make the
    basis unconstructible.
    """
    row = _row(
        basis=EvidenceBasis.INTERPRETATION,
        read_kind=None,
        declaration="step-decl-1",
        records=("m1",),
        returned=0,
        admitted=0,
        verdict="qualifies",
    )

    assert row.basis is EvidenceBasis.INTERPRETATION
    assert (row.returned, row.admitted, row.records) == (0, 0, ("m1",))


@pytest.mark.parametrize(
    "verdict",
    ["free-form prose about what the read found", "qualifies", "", "RETURNED_RECORDS"],
    ids=["prose", "an-interpretation-vocabulary-value", "blank", "the-member-name-not-its-value"],
)
def test_a_read_outcome_verdict_is_one_of_read_outcome_kinds_seven(verdict: str) -> None:
    """§5: the vocabulary is decided by ``basis`` and by nothing else.

    "``verdict`` carries the value of a typed outcome and **never a prose summary**",
    and a ``READ_OUTCOME`` row's is "the value of the ``ReadOutcomeKind`` member
    ADR-0251 §2's classifier assigned to that ask". The field is an ``EncodableText``,
    so without this limb any sentence a model wrote satisfies it — and a row carrying
    one would be persisted, reach ``EvidenceDigest``, and be read as an outcome by §6's
    tests and §8's fifth limb.

    ``"RETURNED_RECORDS"`` is in the cases because §5 adopts the vocabulary "whole and
    not re-minted": what a row carries is the member's **value**, and the member's
    name is not it.
    """
    for member in ReadOutcomeKind:
        assert _row(verdict=member.value).verdict == member.value

    with pytest.raises(ValidationError, match="one of ReadOutcomeKind's seven"):
        _row(verdict=verdict)


def test_an_interpretation_verdict_is_never_a_read_outcome_kind() -> None:
    """§5's disjointness clause, which is normative on the **later** vocabulary.

    "No member of an interpretation enumeration takes a value equal to any of
    ``ReadOutcomeKind``'s seven", because "the digest carries ``verdict`` and **not**
    ``basis``", so "a planner told ``'empty'`` without being told of what would be told
    nothing". Which members that enumeration has is A5's and A7's to fix (§15); that it
    may not collide with these seven is fixed here, and a stored row is where the later
    vocabulary reaches this decision.
    """
    fields: dict[str, object] = {
        "basis": EvidenceBasis.INTERPRETATION,
        "read_kind": None,
        "declaration": "step-decl-1",
        "records": ("m1",),
        "returned": 0,
        "admitted": 0,
    }
    assert _row(**fields, verdict="qualifies").verdict == "qualifies"

    with pytest.raises(ValidationError, match="the two vocabularies are"):
        _row(**fields, verdict=ReadOutcomeKind.EMPTY.value)


@pytest.mark.parametrize(
    "broken",
    [
        pytest.param({"read_kind": ReadKind.SIGHTED_QUERY}, id="a-read-kind"),
        pytest.param({"declaration": None}, id="no-declaration"),
        pytest.param({"records": ()}, id="no-record"),
        pytest.param({"records": ("m1", "m2")}, id="two-records"),
        pytest.param({"returned": 1, "admitted": 1}, id="a-count"),
    ],
)
def test_an_interpretation_row_refuses_every_other_shape(broken: dict[str, object]) -> None:
    """§1: "a verdict over two records is not one this decision admits"."""
    fields: dict[str, object] = {
        "basis": EvidenceBasis.INTERPRETATION,
        "read_kind": None,
        "declaration": "step-decl-1",
        "records": ("m1",),
        "returned": 0,
        "admitted": 0,
        "verdict": "qualifies",
    }
    fields.update(broken)

    with pytest.raises(ValidationError):
        _row(**fields)


@pytest.mark.parametrize("kind", [ReadKind.WEB_SEARCH, ReadKind.LOCAL_FILE])
def test_the_two_ephemeral_kinds_count_and_name_nothing(kind: ReadKind) -> None:
    """§1's second axis and arm 24: "ephemeral kinds count, durable kinds name".

    A ``WEB_SEARCH`` row and a successful single-file ``LOCAL_FILE`` row "each carry
    ``records`` **empty** with ``returned`` saying how many came back", because the
    records they would name are minted for one turn and resolve in no store (ADR-0231
    §16, ADR-0230 §10) — so a durable row naming one would state a warrant it cannot
    show. **The split is by where the record lives and not by which ADR minted it.**
    """
    assert _row(read_kind=kind, records=(), returned=3, admitted=2).records == ()

    with pytest.raises(ValidationError, match="names no record"):
        _row(read_kind=kind, records=("m1",), returned=1, admitted=1)


@pytest.mark.parametrize(
    "kind", [ReadKind.SIGHTED_QUERY, ReadKind.CITATION_HOP, ReadKind.STRUCTURED_READ]
)
def test_the_three_durable_kinds_name_what_they_returned(kind: ReadKind) -> None:
    """§1's second axis: ``len(records)`` equals ``returned``, bounded at 32.

    "Or equals :data:`MAX_EVIDENCE_RECORDS` where ``returned`` exceeds it, with
    ``returned`` still carrying the true count" — so the truncation needs no second
    counter, because the figure that discloses it is the field beside it.
    """
    named = tuple(f"m{index}" for index in range(3))
    assert _row(read_kind=kind, records=named, returned=3, admitted=1).records == named

    bounded = tuple(f"m{index}" for index in range(MAX_EVIDENCE_RECORDS))
    assert _row(read_kind=kind, records=bounded, returned=99, admitted=1).returned == 99

    with pytest.raises(ValidationError, match="records for returned"):
        _row(read_kind=kind, records=("m1",), returned=2, admitted=1)
    with pytest.raises(ValidationError, match="records for returned"):
        _row(read_kind=kind, records=(*bounded, "m99"), returned=99, admitted=1)


def test_admitted_never_exceeds_returned() -> None:
    """§1's third axis: ``admitted`` counts how many of the returned records were new."""
    with pytest.raises(ValidationError, match="exceeds returned"):
        _row(records=("m1",), returned=1, admitted=2)


@pytest.mark.parametrize(
    ("standing", "arguments"),
    [
        pytest.param(EvidenceStanding.STANDING, {}, id="standing-carries-neither"),
        pytest.param(
            EvidenceStanding.INAPPLICABLE,
            {"inapplicable_at_revision": 2},
            id="inapplicable-names-its-revision",
        ),
        pytest.param(
            EvidenceStanding.SUPERSEDED,
            {"superseded_by": "ev2"},
            id="superseded-names-what-did-it",
        ),
    ],
)
def test_each_standing_carries_exactly_its_own_argument(
    standing: EvidenceStanding, arguments: dict[str, object]
) -> None:
    """§1's fourth axis, the admitted half."""
    assert _row(standing=standing, **arguments).standing is standing


@pytest.mark.parametrize(
    ("standing", "arguments"),
    [
        pytest.param(
            EvidenceStanding.STANDING, {"superseded_by": "ev2"}, id="standing-with-an-argument"
        ),
        pytest.param(
            EvidenceStanding.STANDING,
            {"inapplicable_at_revision": 2},
            id="standing-with-the-other",
        ),
        pytest.param(EvidenceStanding.SUPERSEDED, {}, id="superseded-by-nothing-stated"),
        pytest.param(EvidenceStanding.INAPPLICABLE, {}, id="inapplicable-at-no-revision"),
        pytest.param(
            EvidenceStanding.SUPERSEDED,
            {"superseded_by": "ev2", "inapplicable_at_revision": 2},
            id="both-marks-at-once",
        ),
    ],
)
def test_a_row_that_says_it_was_displaced_without_saying_by_what_is_unconstructible(
    standing: EvidenceStanding, arguments: dict[str, object]
) -> None:
    """§1's fourth axis: "the mark and its argument travel together".

    ADR-0249 §1's own move one type over — "the type is what expresses the
    correspondence rather than a rule to remember" — and it is what makes ADR-0252's
    correction 1 auditable: "retained historical disagreements do not permanently block
    progress" is only checkable if **every retirement names what did it**.
    """
    with pytest.raises(ValidationError):
        _row(standing=standing, **arguments)


def test_a_row_carries_no_content_field() -> None:
    """§1: "a ``GoalEvidence`` carries no content", and ``extra="forbid"`` says so.

    "No record text, no snippet, no title, no excerpt, no query, no label, no rendered
    result and no prose of any kind." The containment is a property of the type, so an
    implementation that rendered every field of every row discloses none of those,
    because there is none on the value to disclose.
    """
    forbidden = {"text", "snippet", "title", "excerpt", "query", "label", "summary", "rationale"}
    assert set(GoalEvidence.model_fields) & forbidden == set()

    with pytest.raises(ValidationError):
        _row(snippet="it will rain")


def test_supported_is_bounded_and_refused_rather_than_trimmed() -> None:
    """§2's ``MAX_SUPPORTED_REGIONS``, enforced by the type rather than by a producer.

    "A durable sequence in ``core`` left to be bounded by a producer's arithmetic is
    exactly what ADR-0086 §1 refuses." It **refuses** rather than keeping the first 32
    silently, because a validator that trimmed would leave ``supported_elided``
    unadvanced — which is the silent truncation ADR-0086 §4 forbids. Keeping the first
    32 and advancing the count is the *composer's* act.
    """
    regions = tuple(
        EvidenceApplicability(topics=(f"t{index}",)) for index in range(MAX_SUPPORTED_REGIONS)
    )
    assert len(_row(supported=regions).supported) == MAX_SUPPORTED_REGIONS

    with pytest.raises(ValidationError, match="regions and ADR-0252 §2 bounds it"):
        _row(supported=(*regions, EvidenceApplicability(topics=("one-too-many",))))


# --- §2: the applicability and its three relations --------------------------


def test_an_applicability_applies_at_least_one_axis() -> None:
    """§2: "``None`` is the one spelling of *not applied*".

    A value applying nothing is expressed by the field holding it being absent, or —
    for ``supported`` — by the tuple being empty, exactly as it is on ``StructuredAsk``
    (ADR-0240 §2). So a region applying no axis has no meaning to carry.
    """
    with pytest.raises(ValidationError, match="applies at least one axis"):
        EvidenceApplicability()
    with pytest.raises(ValidationError, match="applies at least one axis"):
        EvidenceApplicability(elided=3)


@pytest.mark.parametrize("axis", ["participants", "topics", "about_person"])
def test_an_applied_sequence_axis_is_never_empty(axis: str) -> None:
    """§2: an applied-and-empty axis is the second spelling ``None`` already has."""
    with pytest.raises(ValidationError, match="applied and empty"):
        EvidenceApplicability(**{axis: ()})  # type: ignore[arg-type]


@pytest.mark.parametrize("axis", ["participants", "topics", "about_person"])
def test_a_label_axis_is_bounded_at_thirty_two(axis: str) -> None:
    """§2's ``MAX_APPLICABILITY_VALUES``, refused rather than trimmed."""
    values = tuple(f"v{index}" for index in range(MAX_APPLICABILITY_VALUES))
    assert EvidenceApplicability(**{axis: values}) is not None  # type: ignore[arg-type]

    with pytest.raises(ValidationError, match="bounds each axis"):
        EvidenceApplicability(**{axis: (*values, "one-too-many")})  # type: ignore[arg-type]


def test_a_window_is_adr_0237s_and_is_not_re_expressed() -> None:
    """§2: ``TimeWindow`` "is used exactly as ADR-0237 §2 defines it".

    The half-open reading, the unset ends, the refusal of a window with both ends unset
    and the refusal of one whose ``end`` is not strictly after its ``start`` are that
    ADR's and are inherited whole — so an applicability cannot hold a window this
    corpus refuses, because there is no second window type to hold it in.
    """
    with pytest.raises(ValidationError):
        TimeWindow()
    assert EvidenceApplicability(window=_SATURDAY).window == _SATURDAY


def test_coverage_is_directional_over_windows() -> None:
    """§2's coverage, by ADR-0117 §3's containment predicate, with the direction stated.

    "``B``'s window as that predicate's contained extent ``E`` and ``A``'s as its
    containing coverage ``C``." The predicate is not symmetric and the two readings
    differ on every unbounded end, which is why the direction is stated rather than
    left to a reader.
    """
    week = EvidenceApplicability(window=_WEEK)
    saturday = EvidenceApplicability(window=_SATURDAY)

    assert week.covers(saturday)
    assert not saturday.covers(week)
    assert week.covers(week)


def test_an_unbounded_extent_end_is_contained_only_by_an_unbounded_coverage_end() -> None:
    """ADR-0117 §3's own decisive sentence, reused rather than restated.

    A bounded reading contains no unbounded extent: a source that states no bound on
    one side has said nothing about the region beyond it, so a bounded coverage cannot
    account for it.
    """
    open_ended = EvidenceApplicability(window=TimeWindow(start=_SATURDAY.start))
    bounded = EvidenceApplicability(window=_WEEK)

    assert not bounded.covers(open_ended)
    assert open_ended.covers(EvidenceApplicability(window=_SUNDAY))
    assert open_ended.covers(open_ended)


def test_an_axis_the_coverer_does_not_apply_covers_no_applied_axis() -> None:
    """§2: "an axis ``A`` does not apply covers no applied axis of ``B``".

    "An unapplied axis means *this applicability says nothing about that axis*, and a
    value that says nothing about the people a step names has not established anything
    about them." Reading an absent axis as *everything* would be the same substitution
    ADR-0240 §2 refuses at the ask, arriving at the response instead.
    """
    topics_only = EvidenceApplicability(topics=("weather",))
    topics_and_people = EvidenceApplicability(topics=("weather",), participants=("Alice",))

    assert not topics_only.covers(topics_and_people)
    assert topics_and_people.covers(topics_only), "an axis B does not apply is covered by anything"


def test_participants_fold_case_and_topics_do_not() -> None:
    """§6's per-axis comparison and ADR-0252 §18 arm 32, which is the fold's whole point.

    "Two ``TopicLabel``s that differ only by Unicode normalisation are **two** topics",
    because ADR-0213 §3 gives a topic exactly one relation — equality of the stored
    characters — and any wider matching rule is "reserved to a later ADR, which is the
    only instrument that may lift the clause". "Two ``participants`` values differing
    only by case **are** one participant, and so are two ``about_person`` values", by
    ADR-0101 §2's canonical caseless equality.
    """
    precomposed = EvidenceApplicability(topics=("caf\u00e9",))
    decomposed = EvidenceApplicability(topics=("cafe\u0301",))
    assert not precomposed.covers(decomposed)
    assert not precomposed.overlaps(decomposed)

    upper = EvidenceApplicability(participants=("ALICE",), about_person=("BOB",))
    lower = EvidenceApplicability(participants=("alice",), about_person=("bob",))
    assert upper.covers(lower)
    assert lower.covers(upper)
    assert upper.overlaps(lower)


def test_overlap_requires_agreement_on_every_shared_axis() -> None:
    """§2's overlap, and ADR-0252 §18 arm 9's *Saturday, weather* / *Sunday, weather*.

    "A shared label does not bridge disjoint periods": the two rows share the ``topics``
    axis and both apply ``window``, their windows are disjoint, so they do not overlap
    and neither is about the other's ground — and neither covers the other either.
    Defining overlap as *there exists something both cover* would make them overlap
    through a topics-only value that omits the window.
    """
    saturday = EvidenceApplicability(window=_SATURDAY, topics=("weather",))
    sunday = EvidenceApplicability(window=_SUNDAY, topics=("weather",))

    assert not saturday.overlaps(sunday)
    assert not sunday.overlaps(saturday)
    assert not saturday.covers(sunday)
    assert not sunday.covers(saturday)


def test_overlap_ignores_an_axis_only_one_side_applies_but_needs_one_in_common() -> None:
    """§2: "an axis only one of them applies is ignored", and they must share one."""
    topics = EvidenceApplicability(topics=("weather",))
    topics_and_window = EvidenceApplicability(topics=("weather",), window=_SATURDAY)
    window_only = EvidenceApplicability(window=_SATURDAY)

    assert topics.overlaps(topics_and_window)
    assert not topics.overlaps(window_only), "no axis in common is no overlap"
    assert window_only.overlaps(topics_and_window)


def test_touching_windows_share_no_instant() -> None:
    """ADR-0237 §2's half-open reading decides the ends: ``[start, end)``.

    An instant equal to a window's ``end`` is outside it, so Saturday and Sunday touch
    and do not overlap.
    """
    assert not EvidenceApplicability(window=_SATURDAY).overlaps(
        EvidenceApplicability(window=_SUNDAY)
    )
    assert EvidenceApplicability(window=_SATURDAY).overlaps(EvidenceApplicability(window=_WEEK))


def test_a_tuple_covers_by_one_region_and_never_by_a_union() -> None:
    """§2's tuple relations, and arm 12: "regions are not merged".

    "A row composed from a record covering ``[09:00, 10:00)`` and a record covering
    ``[15:00, 16:00)`` satisfies no condition declaring noon; a row composed from
    *Alice on Saturday* and *Bob on Sunday* satisfies no condition naming Alice on
    Sunday." An aggregate asserts the **conjunction** of what several records said,
    where the records only ever said their own parts.
    """
    alice_saturday = EvidenceApplicability(window=_SATURDAY, participants=("Alice",))
    bob_sunday = EvidenceApplicability(window=_SUNDAY, participants=("Bob",))
    alice_sunday = EvidenceApplicability(window=_SUNDAY, participants=("Alice",))

    assert not support_covers((alice_saturday, bob_sunday), required=alice_sunday)
    assert support_covers((alice_saturday, bob_sunday), required=alice_saturday)


def test_an_empty_supported_covers_nothing_in_either_relation() -> None:
    """§2 and ADR-0249 §10: "an absent ``supported`` supports nothing".

    An empty covering tuple covers no applicability, and an empty **covered** tuple is
    covered by nothing — a refresh has nothing to account for, so §8 limb 4's
    non-emptiness is a property of this function rather than a rule each caller keeps.
    """
    region = EvidenceApplicability(topics=("weather",))

    assert not support_covers((), required=region)
    assert not support_covers_support((region,), earlier=())
    assert not support_overlaps((), other=(region,))


def test_a_wider_refresh_covers_a_narrower_row_and_never_the_reverse() -> None:
    """§8 limb 4 and arm 8, at the relation the limb is stated over.

    "A later affirmative row covering **Saturday** does **not** supersede a standing row
    covering **the whole week**" — letting it would retire the week row and take its
    Sunday support with it, "evidence the system holds, paid for, and has not
    contradicted". "A later row covering the **week** does supersede a Saturday row",
    because everything the older row established the newer one establishes too.
    """
    week = (EvidenceApplicability(window=_WEEK),)
    saturday = (EvidenceApplicability(window=_SATURDAY),)

    assert support_covers_support(week, earlier=saturday)
    assert not support_covers_support(saturday, earlier=week)


def test_a_tuple_covers_a_tuple_region_by_region() -> None:
    """§2: "every region of ``T`` is covered by some region of ``S``".

    "A later row with two regions retires an earlier row only where each of its regions
    is covered by one of them."
    """
    later = (
        EvidenceApplicability(window=_SATURDAY, topics=("weather",)),
        EvidenceApplicability(window=_SUNDAY, topics=("weather",)),
    )
    earlier = (EvidenceApplicability(window=_SUNDAY, topics=("weather",)),)
    unmatched = (EvidenceApplicability(window=_WEEK, topics=("weather",)),)

    assert support_covers_support(later, earlier=earlier)
    assert not support_covers_support(later, earlier=unmatched)


def test_the_relations_read_no_count() -> None:
    """§1, §5 and arm 25: "sufficiency never reads a count".

    "Two rows differing **only** in those two fields" reach the same verdict, which is
    the arm that pins sufficiency out of productivity. The half I1 lands is §2's
    relations, which take applicabilities and are handed no count at all — a property of
    the signatures, asserted here so a later lane cannot quietly widen them.
    """
    productive = _row(records=("m1",), returned=1, admitted=1)
    duplicated = _row(records=("m1",), returned=1, admitted=0)

    assert productive.supported == duplicated.supported
    assert support_covers_support(
        productive.supported, earlier=duplicated.supported
    ) is support_covers_support(duplicated.supported, earlier=productive.supported)


# --- §10: grounding an element on a row -------------------------------------


def test_a_from_evidence_element_carries_exactly_one_reference() -> None:
    """§10: the fourth admitted shape, and neither-nor-both.

    "A ``FROM_EVIDENCE`` element carries **exactly one** of ``evidence_id`` — the record
    of the labelled supply ADR-0249 §7 stamps — and ``evidence_row_id`` — a
    ``GoalEvidence`` row **of the same goal**."
    """
    by_record = GoalElement(text="it rains", ground=Ground.FROM_EVIDENCE, evidence_id="m1")
    by_row = GoalElement(text="it rains", ground=Ground.FROM_EVIDENCE, evidence_row_id="ev1")

    assert by_record.evidence_row_id is None
    assert by_row.evidence_id is None

    with pytest.raises(ValidationError, match="exactly one of"):
        GoalElement(text="it rains", ground=Ground.FROM_EVIDENCE)
    with pytest.raises(ValidationError, match="exactly one of"):
        GoalElement(
            text="it rains",
            ground=Ground.FROM_EVIDENCE,
            evidence_id="m1",
            evidence_row_id="ev1",
        )


@pytest.mark.parametrize("ground", [Ground.USER_STATED, Ground.INFERRED])
def test_the_other_two_grounds_carry_no_row_reference(ground: Ground) -> None:
    """§10: "``USER_STATED`` and ``INFERRED`` carry neither, exactly as before"."""
    with pytest.raises(ValidationError):
        GoalElement(
            text="it rains",
            ground=ground,
            evidence_row_id="ev1",
            span="it rains" if ground is Ground.USER_STATED else None,
        )


def test_an_outcome_grounds_on_a_row_on_the_same_validator_shape() -> None:
    """§10 and arm 19, because ADR-0249 §1 validates the outcome "as a ``GoalElement``'s".

    "A ``GoalInterpretation`` whose outcome is ``FROM_EVIDENCE`` carries exactly one of
    ``outcome_evidence_id`` and ``outcome_evidence_row_id``."
    """
    revision = GoalInterpretation(
        revision=1,
        outcome="book the campsite",
        outcome_ground=Ground.FROM_EVIDENCE,
        outcome_evidence_row_id="ev1",
        recorded_at=_WHEN,
    )
    assert revision.outcome_evidence_id is None

    with pytest.raises(ValidationError, match="exactly one of"):
        GoalInterpretation(
            revision=1,
            outcome="book the campsite",
            outcome_ground=Ground.FROM_EVIDENCE,
            outcome_evidence_id="m1",
            outcome_evidence_row_id="ev1",
            recorded_at=_WHEN,
        )


def test_a_goal_blob_written_before_this_decision_still_decodes() -> None:
    """§13: "the stored ``goals`` blobs are not rewritten either".

    The new fields are "optional with an absent or empty default" and §10's validator
    **adds** a shape while leaving ADR-0249 §1's three untouched, so every element an
    earlier version wrote decodes unchanged, **as the ``FROM_EVIDENCE`` element it
    was**. "No lane back-fills ``evidence_row_id`` from ``evidence_id``", which would
    assert a row that never existed.
    """
    legacy = '{"text":"it rains","ground":"from_evidence","evidence_id":"m1","span":null}'

    element = GoalElement.model_validate_json(legacy)

    assert element.evidence_id == "m1"
    assert element.evidence_row_id is None


# --- §12: the order, the marks and the history ------------------------------


def test_the_order_is_read_at_then_id() -> None:
    """§12's total order, stated once so three stores cannot re-derive it differently."""
    rows = [
        _row(id="b", read_at=_WHEN + timedelta(minutes=1)),
        _row(id="b", read_at=_WHEN),
        _row(id="a", read_at=_WHEN),
    ]

    assert [row.id for row in sorted(rows, key=evidence_order)] == ["a", "b", "b"]


def test_a_history_refuses_a_row_of_another_goal() -> None:
    """§12: "every row of ``rows`` carries that ``goal_id``"."""
    assert EvidenceHistory(goal_id="g1", rows=(_row(),)).elided == 0

    with pytest.raises(ValidationError, match="holds rows of"):
        EvidenceHistory(goal_id="g1", rows=(_row(goal_id="g2"),))
