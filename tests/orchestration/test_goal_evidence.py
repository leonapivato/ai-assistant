"""ADR-0252 §17's I2 at the loop: what a servicing establishes, made durable.

§18's arms that are I2's, and only those. The previous lane's PR (#2310) lists which
§18 items it discharged at the contract and the store and which it left here; of those,
this file carries **11, 13, 14, 18, 27, 28, 37, 38** whole, **7, 8, 9, 10** in the half
that is §8's predicate — the store's half of 7 and 10 is I1's — and the composition
halves of **4**, **5**, **12**, **24** and **31**.

**The arms I2 does not carry are the ones that read §6's four sufficiency tests or §7's
conflict predicate** (§18 items 3, 6, 29, 30, 33, 34, 35 and the satisfaction halves of
4, 5, 12, 31), and §9's invalidation *predicate* (items 1, 2). §6 says of its own tests
that they "have no caller in this decision", §9's two operands are a declared
applicability no type in the tree carries, and §17 gives neither this lane: "the first
lane that can dispatch against evidence is the lane that can also invalidate it".

**A turn-shaped arm is driven through the real path** — the production
:class:`~ai_assistant.orchestration.loop.LearningLoop` over the real
:func:`~ai_assistant.orchestration.reads.service_read_request`, with a scripted planner
and canonical fakes — and reads the rows off ``RespondedTurn.evidence``, which is what
``Engine`` writes. §8's six-limb test is stated over two *stored* rows and is asserted
over rows, because a predicate over a pair is a statement about a pair rather than about
a turn; the write that applies its result is exercised end to end in the last section,
on both conforming stores.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest
from test_loop_search import (
    _ASK,
    _RESULT,
    ActionPlanFor,
    _belief,
    _bounded,
    _clock,
    _CostedSearcher,
    _loop,
    _servicer,
)

from ai_assistant.core.types import (
    MAX_APPLICABILITY_VALUES,
    MAX_EVIDENCE_RECORDS,
    MAX_SUPPORTED_REGIONS,
    Attestation,
    EpisodicMemory,
    EvidenceApplicability,
    EvidenceBasis,
    EvidenceStanding,
    Goal,
    GoalElement,
    GoalEvidence,
    GoalInterpretation,
    Ground,
    MemorySource,
    Placement,
    ProposedElement,
    ProposedUnderstanding,
    Provenance,
    ReadAsk,
    ReadKind,
    ReadOutcomeKind,
    ReadRequest,
    ReportedExtent,
    SearchRefusal,
    SemanticMemory,
    StructuredAsk,
    TimeWindow,
    Validity,
)
from ai_assistant.orchestration.evidence import (
    ANSWERING,
    affirmative,
    as_of_of,
    composed_row,
    digest_of,
    digests,
    ordered_history,
    refresh_set,
    refreshes,
    region_of,
    rendered_region,
    rendered_support,
    requested_of,
    supported_of,
)
from ai_assistant.orchestration.loop import ConversationalOperation
from ai_assistant.testing import FakeMemoryStore, FakePlanner, FakeWebSearcher
from ai_assistant.testing.queries import DEFAULT_COMPOSED_QUERY

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import MemoryRecord


_NOW: Final = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)

#: Saturday and Sunday of one week, and the week that contains both — the periods
#: ADR-0252 §18's arms 1, 2, 8 and 9 are all stated over.
_SATURDAY: Final = TimeWindow(
    start=datetime(2026, 9, 12, tzinfo=UTC), end=datetime(2026, 9, 13, tzinfo=UTC)
)
_SUNDAY: Final = TimeWindow(
    start=datetime(2026, 9, 13, tzinfo=UTC), end=datetime(2026, 9, 14, tzinfo=UTC)
)
_WEEK: Final = TimeWindow(
    start=datetime(2026, 9, 7, tzinfo=UTC), end=datetime(2026, 9, 14, tzinfo=UTC)
)


def _region(**axes: object) -> EvidenceApplicability:
    """One region, spelled by the axes a case applies."""
    return EvidenceApplicability(**axes)  # type: ignore[arg-type]


def _row(  # noqa: PLR0913 — one keyword per field §8's six limbs read, all defaulted
    row_id: str = "row-1",
    *,
    goal_id: str = "goal-1",
    attempt_id: str = "attempt-1",
    kind: ReadKind | None = ReadKind.STRUCTURED_READ,
    supported: Sequence[EvidenceApplicability] = (),
    verdict: str = ReadOutcomeKind.RETURNED_RECORDS.value,
    read_at: datetime = _NOW,
    as_of: datetime | None = None,
    standing: EvidenceStanding = EvidenceStanding.STANDING,
    superseded_by: str | None = None,
    records: tuple[str, ...] = (),
    returned: int = 0,
) -> GoalEvidence:
    """A stored ``READ_OUTCOME`` row, defaulted to one that establishes nothing."""
    return GoalEvidence(
        id=row_id,
        goal_id=goal_id,
        attempt_id=attempt_id,
        basis=EvidenceBasis.READ_OUTCOME,
        read_kind=kind,
        supported=tuple(supported),
        supported_elided=0,
        read_at=read_at,
        as_of=as_of,
        records=records,
        returned=returned,
        admitted=0,
        verdict=verdict,
        standing=standing,
        superseded_by=superseded_by,
    )


def _episode(  # noqa: PLR0913 — one keyword per axis a record can carry into a region; that is the point of the helper
    record_id: str,
    *,
    participants: Sequence[str] = (),
    topics: Sequence[str] = (),
    extent: ReportedExtent | None = None,
    reported_at: datetime | None = None,
    validity: Validity | None = None,
) -> EpisodicMemory:
    """One episode a read returned, with exactly the axes a case wants on it."""
    attested = extent is not None or reported_at is not None
    return EpisodicMemory(
        id=record_id,
        content="we talked about the weather",
        occurred_at=_NOW,
        participants=tuple(participants),
        topics=tuple(topics),
        validity=validity if validity is not None else Validity(),
        provenance=Provenance(
            source=MemorySource.EXTERNAL if attested else MemorySource.OBSERVED,
            confidence=0.9,
            last_updated=_NOW,
            attestation=(
                Attestation(
                    reported_by="weather-service",
                    reported_at=reported_at if reported_at is not None else _NOW,
                    extent=extent,
                )
                if attested
                else None
            ),
        ),
    )


def _ask_of(kind: ReadKind) -> ReadAsk:
    """One ask of each kind, carrying exactly the argument that kind admits."""
    match kind:
        case ReadKind.SIGHTED_QUERY:
            return ReadAsk(kind=kind, query="sunday weather")
        case ReadKind.STRUCTURED_READ:
            return ReadAsk(kind=kind, structure=StructuredAsk(topics=("weather",)))
        case ReadKind.CITATION_HOP:
            return ReadAsk(kind=kind, labels=("M1",))
        case ReadKind.LOCAL_FILE:
            return ReadAsk(kind=kind, entry="F1")
        case ReadKind.WEB_SEARCH | ReadKind.FORECAST_READ:
            return ReadAsk(kind=kind)


def _bare(record_id: str, *, about_person: str | None = None) -> SemanticMemory:
    """A belief carrying no axis at all unless a case gives it one."""
    return SemanticMemory(
        id=record_id,
        content="the tower is in Porto",
        fact="the tower is in Porto",
        about_person=about_person,
        placement=Placement(),
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=_NOW),
    )


# --------------------------------------------------------------------------- #
# §3: what `requested` is composed from, and what it is never composed from    #
# --------------------------------------------------------------------------- #


def test_only_a_structured_read_composes_a_requested() -> None:
    """§3: "One kind of five produces a ``requested``, and that is the rule working".

    A composed query is a model completion ADR-0228 §11 rules "no lane … treats as
    evidence of anything"; a hop's and a file's only argument is a label, which ADR-0249
    §9 says no lane persists as a reference; and a ``WEB_SEARCH`` ask has "no field".
    Each absence is a clause of the corpus rather than an omission to repair.
    """
    structured = StructuredAsk(window=_SUNDAY, topics=("weather",))

    composed = requested_of(ReadAsk(kind=ReadKind.STRUCTURED_READ, structure=structured))

    assert composed == _region(window=_SUNDAY, topics=("weather",))
    assert requested_of(ReadAsk(kind=ReadKind.SIGHTED_QUERY, query="sunday weather")) is None
    assert requested_of(ReadAsk(kind=ReadKind.CITATION_HOP, labels=("M1",))) is None
    assert requested_of(ReadAsk(kind=ReadKind.LOCAL_FILE, entry="F1")) is None
    assert requested_of(ReadAsk(kind=ReadKind.WEB_SEARCH)) is None


def test_a_structured_read_carrying_a_query_contributes_the_structure_alone() -> None:
    """§3: "An ask carrying a ``query`` beside its structure contributes the structure alone".

    The query is the same model completion it is on a ``SIGHTED_QUERY``, and a kind that
    happens to carry one beside a typed part does not launder it into the row.
    """
    ask = ReadAsk(
        kind=ReadKind.STRUCTURED_READ,
        structure=StructuredAsk(topics=("weather",)),
        query="what will sunday be like",
    )

    composed = requested_of(ask)

    assert composed == _region(topics=("weather",))
    assert "sunday" not in repr(composed), "no text of the query reaches the row"


# --------------------------------------------------------------------------- #
# §3: what `supported` is composed from — one region per record, never per ask #
# --------------------------------------------------------------------------- #


def test_a_region_is_composed_from_one_records_own_values() -> None:
    """§3 source 1: participants, topics, about_person and the window, per record.

    ``about_person`` "is one value and reaches the axis as a one-member tuple", and the
    window comes from the attestation's declared extent and from nowhere else.
    """
    episode = _episode(
        "e1",
        participants=("Alice", "Bob"),
        topics=("weather",),
        extent=ReportedExtent(extends_from=_SUNDAY.start, extends_until=_SUNDAY.end),
    )

    region = region_of(episode)

    assert region == _region(
        window=_SUNDAY, participants=("Alice", "Bob"), topics=("weather",), elided=0
    )
    assert region_of(_bare("b1", about_person="Alice")) == _region(about_person=("Alice",))


def test_a_record_applying_no_axis_contributes_no_region() -> None:
    """§3: "A record carrying **no** applied axis contributes **no region**"."""
    assert region_of(_bare("b1")) is None
    assert supported_of((_bare("b1"), _bare("b2"))) == ((), 0)


def test_regions_are_never_merged() -> None:
    """§18 arm 12's composition half, and §2's reason for it.

    "An aggregate asserts the **conjunction** of what several records said, where the
    records only ever said their own parts." Two records covering ``[09:00, 10:00)`` and
    ``[15:00, 16:00)`` compose **two** regions, so nothing anywhere holds the enclosing
    interval a condition about noon would pass against.
    """
    morning = TimeWindow(
        start=datetime(2026, 9, 13, 9, tzinfo=UTC), end=datetime(2026, 9, 13, 10, tzinfo=UTC)
    )
    afternoon = TimeWindow(
        start=datetime(2026, 9, 13, 15, tzinfo=UTC), end=datetime(2026, 9, 13, 16, tzinfo=UTC)
    )
    records = (
        _episode(
            "e1", extent=ReportedExtent(extends_from=morning.start, extends_until=morning.end)
        ),
        _episode(
            "e2", extent=ReportedExtent(extends_from=afternoon.start, extends_until=afternoon.end)
        ),
    )

    regions, elided = supported_of(records)

    assert regions == (_region(window=morning), _region(window=afternoon))
    assert elided == 0
    noon = _region(
        window=TimeWindow(
            start=datetime(2026, 9, 13, 12, tzinfo=UTC), end=datetime(2026, 9, 13, 13, tzinfo=UTC)
        )
    )
    assert not any(region.covers(noon) for region in regions), "no region spans the gap"


def test_alice_on_saturday_and_bob_on_sunday_cover_no_alice_on_sunday() -> None:
    """§2's second manufactured coverage, asserted over the composition that avoids it."""
    records = (
        _episode(
            "e1",
            participants=("Alice",),
            extent=ReportedExtent(extends_from=_SATURDAY.start, extends_until=_SATURDAY.end),
        ),
        _episode(
            "e2",
            participants=("Bob",),
            extent=ReportedExtent(extends_from=_SUNDAY.start, extends_until=_SUNDAY.end),
        ),
    )

    regions, _ = supported_of(records)

    wanted = _region(window=_SUNDAY, participants=("Alice",))
    assert not any(region.covers(wanted) for region in regions)


# --------------------------------------------------------------------------- #
# §18 arm 13: an unrepresentable interval applies no window, and nor does a     #
# `Validity`                                                                   #
# --------------------------------------------------------------------------- #


def test_an_unrepresentable_extent_applies_no_window_and_advances_elided() -> None:
    """§3: both ends unset is declined, and the decline is disclosed.

    "Declining the axis makes the region cover **no** applied window, where carrying it
    as unbounded would make it cover **every** one." The count is what distinguishes a
    source that declared nothing from one whose declaration could not be expressed.
    """
    unbounded = _episode("e1", topics=("weather",), extent=ReportedExtent())

    region = region_of(unbounded)

    assert region == _region(topics=("weather",), elided=1)
    assert region is not None
    assert region.window is None


def test_a_record_declaring_only_an_occurred_at_applies_no_window() -> None:
    """§3: "A record's ``occurred_at`` is not a declaration of coverage".

    An episode's is an *instant*, and treating it as covering a period is exactly the
    assertion ADR-0237 §7 forbids. Nothing is elided: no extent was declared, so none
    was declined.
    """
    region = region_of(_episode("e1", topics=("weather",)))

    assert region == _region(topics=("weather",), elided=0)


def test_a_validity_is_never_read_as_a_declared_interval() -> None:
    """§18 arm 13's third clause, and §3's prohibition — the fallback pinned out.

    A weather record written on Saturday with ``valid_from`` set and no
    ``ReportedExtent`` declares an interval running from Saturday with no end. Read as
    coverage it would have supported **every** later date off a persistence timestamp no
    source ever said anything with.
    """
    for validity in (
        Validity(valid_from=_SATURDAY.start),
        Validity(valid_until=_SUNDAY.end),
        Validity(valid_from=_SATURDAY.start, valid_until=_SUNDAY.end),
    ):
        region = region_of(_episode("e1", topics=("weather",), validity=validity))

        assert region == _region(topics=("weather",), elided=0), (
            "no end of a Validity contributes to any region's window, on any kind"
        )
        assert region is not None
        assert not region.covers(_region(window=_SUNDAY))


# --------------------------------------------------------------------------- #
# §2: the two bounds, and every truncation narrows                             #
# --------------------------------------------------------------------------- #


def test_a_label_axis_keeps_the_first_thirty_two_and_counts_the_rest() -> None:
    """§18 arm 20's composition half: the region's own bound and its own count."""
    many = tuple(f"p{one}" for one in range(MAX_APPLICABILITY_VALUES + 3))

    region = region_of(_episode("e1", participants=many))

    assert region is not None
    assert region.participants == many[:MAX_APPLICABILITY_VALUES]
    assert region.elided == 3


def test_a_blank_value_is_dropped_and_counted_and_never_repaired() -> None:
    """§2: "dropped, never stripped, never case-folded and never repaired"."""
    region = region_of(_episode("e1", participants=("  Alice  ", "   ", "")))

    assert region is not None
    assert region.participants == ("  Alice  ",), "the surviving value keeps its own bytes"
    assert region.elided == 2


def test_supported_keeps_the_first_thirty_two_regions_and_counts_the_rest() -> None:
    """§2: ``MAX_SUPPORTED_REGIONS``, and the row's own count beside it."""
    records = tuple(
        _episode(f"e{one}", topics=("weather",)) for one in range(MAX_SUPPORTED_REGIONS + 2)
    )

    regions, elided = supported_of(records)

    assert len(regions) == MAX_SUPPORTED_REGIONS
    assert elided == 2


# --------------------------------------------------------------------------- #
# §1, §4: which kinds name and which count, and where `as_of` comes from       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "kind", [ReadKind.SIGHTED_QUERY, ReadKind.CITATION_HOP, ReadKind.STRUCTURED_READ]
)
def test_a_durable_kind_names_its_records(kind: ReadKind) -> None:
    """§18 arm 24's composition half: ``len(records) == returned`` on the three."""
    records = (_bare("b1"), _bare("b2"))

    row = composed_row(
        row_id="row-1",
        goal_id="goal-1",
        attempt_id="attempt-1",
        ask=_ask_of(kind),
        outcome=ReadOutcomeKind.RETURNED_RECORDS,
        records=records,
        admitted=2,
        read_at=_NOW,
    )

    assert row.records == ("b1", "b2")
    assert row.returned == 2


@pytest.mark.parametrize("kind", [ReadKind.WEB_SEARCH, ReadKind.LOCAL_FILE])
def test_an_ephemeral_kind_counts_and_names_nothing(kind: ReadKind) -> None:
    """§18 arm 24: "no minted or fetched id reaches either row", and the count stands alone."""
    records = (_bare("minted-1"),)

    row = composed_row(
        row_id="row-1",
        goal_id="goal-1",
        attempt_id="attempt-1",
        ask=_ask_of(kind),
        outcome=ReadOutcomeKind.RETURNED_RECORDS,
        records=records,
        admitted=1,
        read_at=_NOW,
    )

    assert row.records == ()
    assert row.returned == 1, "the true count, with nothing to resolve it against"


def test_a_row_over_more_records_than_the_bound_keeps_the_first_and_still_counts_them_all() -> None:
    """§1: the first 32 identifiers, and ``returned`` continuing to carry the true count."""
    records = tuple(_bare(f"b{one}") for one in range(MAX_EVIDENCE_RECORDS + 5))

    row = composed_row(
        row_id="row-1",
        goal_id="goal-1",
        attempt_id="attempt-1",
        ask=_ask_of(ReadKind.SIGHTED_QUERY),
        outcome=ReadOutcomeKind.RETURNED_RECORDS,
        records=records,
        admitted=0,
        read_at=_NOW,
    )

    assert len(row.records) == MAX_EVIDENCE_RECORDS
    assert row.returned == MAX_EVIDENCE_RECORDS + 5


def test_as_of_is_the_earliest_declared_instant_or_nothing() -> None:
    """§18 arm 27, and §4's reason for the earliest.

    "A row composed from three records the source reported at three moments speaks for
    the picture as of the oldest of them; taking the newest would let one fresh record
    make two stale ones look current."
    """
    earlier, later = _NOW - timedelta(hours=2), _NOW - timedelta(minutes=5)
    attested = (
        _episode("e1", topics=("a",), reported_at=later),
        _episode("e2", reported_at=earlier),
    )

    assert as_of_of(ReadKind.SIGHTED_QUERY, attested) == earlier
    assert as_of_of(ReadKind.SIGHTED_QUERY, (_bare("b1"),)) is None, (
        "the owner's own store-written beliefs declare no reading-level instant"
    )


def test_a_local_file_row_carries_as_of_absent_although_its_record_states_an_instant() -> None:
    """§18 arm 27's third clause, and §4's stated exception.

    ADR-0230 §5 sets a fetched record's ``reported_at`` to "the instant the file was
    read", so the generic rule would fill ``as_of`` with the value ``read_at`` already
    carries — and a row carrying it twice would be indistinguishable from one that
    filled ``as_of`` **from** ``read_at``.
    """
    fetched = (_episode("f1", topics=("notes",), reported_at=_NOW),)

    assert as_of_of(ReadKind.LOCAL_FILE, fetched) is None
    assert as_of_of(ReadKind.SIGHTED_QUERY, fetched) == _NOW, "and every other kind takes it"


# --------------------------------------------------------------------------- #
# §5, §8: the affirmative partition and the six-limb refresh test              #
# --------------------------------------------------------------------------- #


def test_the_affirmative_partition_is_over_the_closed_vocabulary_and_reads_no_count() -> None:
    """§5, and §18 arm 4's verdict half.

    ``EMPTY``, ``REFUSED``, ``FAILED`` and ``EXPIRED`` are non-answering; the other
    three answered with records. **``DUPLICATE`` is answering**, which §5 calls the
    correction round 2 forced: "whether the supply already held them is a fact about
    *this turn's supply* and not about the response".
    """
    assert {
        ReadOutcomeKind.RETURNED_RECORDS,
        ReadOutcomeKind.DUPLICATE,
        ReadOutcomeKind.TRUNCATED,
    } == ANSWERING
    for member in ReadOutcomeKind:
        assert affirmative(_row(verdict=member.value)) is (member in ANSWERING)
    assert affirmative(_row(verdict=ReadOutcomeKind.DUPLICATE.value)), "arm 4's own clause"


def test_a_later_covering_answering_row_refreshes_the_earlier_one() -> None:
    """§18 arm 7's predicate half: all six limbs hold, so the earlier row is refreshed.

    "The arm runs within one attempt as well as across two", because ordinary resumption
    keeps the attempt (ADR-0250 §12) and a refresh may not depend on the attempt
    boundary — so the same pair is asserted with the attempt shared and with it moved.
    """
    earlier = _row("row-1", supported=(_region(window=_WEEK),), read_at=_NOW - timedelta(hours=1))
    for attempt in ("attempt-1", "attempt-2"):
        later = _row("row-2", attempt_id=attempt, supported=(_region(window=_WEEK),), read_at=_NOW)

        assert refreshes(later, earlier)
        assert refresh_set(later, (earlier,)) == ("row-1",)


def test_a_narrower_refresh_retires_nothing_and_a_wider_one_does() -> None:
    """§18 arm 8, and §8 limb 4's reason: "a refresh may only retire what it can account for".

    A fresh read of Saturday *overlaps* a standing row supporting the whole week, and
    letting it supersede would retire the week row and take its Sunday support with it.
    """
    week = _row("row-week", supported=(_region(window=_WEEK),), read_at=_NOW - timedelta(hours=1))
    saturday = _row(
        "row-sat", supported=(_region(window=_SATURDAY),), read_at=_NOW - timedelta(hours=1)
    )
    later_saturday = _row("row-2", supported=(_region(window=_SATURDAY),), read_at=_NOW)
    later_week = _row("row-3", supported=(_region(window=_WEEK),), read_at=_NOW)

    assert not refreshes(later_saturday, week), "the week row keeps its Sunday support"
    assert refreshes(later_week, saturday)
    assert refresh_set(later_saturday, (week, saturday)) == ("row-sat",)


def test_a_shared_label_does_not_bridge_disjoint_periods() -> None:
    """§18 arm 9: *Saturday, weather* and *Sunday, weather* neither overlap nor cover."""
    saturday = _region(window=_SATURDAY, topics=("weather",))
    sunday = _region(window=_SUNDAY, topics=("weather",))

    assert not saturday.covers(sunday)
    assert not sunday.covers(saturday)
    assert not saturday.overlaps(sunday)
    assert not refreshes(
        _row("row-2", supported=(sunday,), read_at=_NOW),
        _row("row-1", supported=(saturday,), read_at=_NOW - timedelta(hours=1)),
    )


@pytest.mark.parametrize(
    "verdict",
    [
        ReadOutcomeKind.EMPTY,
        ReadOutcomeKind.REFUSED,
        ReadOutcomeKind.FAILED,
        ReadOutcomeKind.EXPIRED,
    ],
)
def test_a_failed_refresh_retires_nothing(verdict: ReadOutcomeKind) -> None:
    """§18 arm 10, first clause, and §8 limb 5's reason.

    "Permitting it to supersede would mean that *asking again and getting nothing*
    silently retired the answer we had." #2096 item 8 one level down: **a later read may
    confirm and displace, and may never retire by failing.**
    """
    earlier = _row("row-1", supported=(_region(window=_WEEK),), read_at=_NOW - timedelta(hours=1))
    later = _row("row-2", supported=(_region(window=_WEEK),), read_at=_NOW, verdict=verdict.value)

    assert not refreshes(later, earlier)
    assert refresh_set(later, (earlier,)) == ()


def test_a_row_that_does_not_move_the_effective_instant_retires_nothing() -> None:
    """§18 arm 10's second clause, including round 2's own case (§8 limb 6).

    "``E`` read at 10:00 with ``as_of`` 09:59 is not superseded by ``L`` read at 10:05
    with ``as_of`` 08:00", because the limb is stated over the instant §6 test 4
    evaluates. And **strictly** later, not merely not-earlier: two rows sharing an
    effective instant supersede one another in neither direction, which is what makes
    the relation a strict partial order rather than one whose outcome depends on
    evaluation order.
    """
    ten = datetime(2026, 9, 13, 10, tzinfo=UTC)
    established = _row(
        "row-1", supported=(_region(window=_WEEK),), read_at=ten, as_of=ten - timedelta(minutes=1)
    )
    stale_source = _row(
        "row-2",
        supported=(_region(window=_WEEK),),
        read_at=ten + timedelta(minutes=5),
        as_of=ten - timedelta(hours=2),
    )

    assert not refreshes(stale_source, established), "a later read of an older statement"
    same_instant = _row("row-3", supported=(_region(window=_WEEK),), read_at=ten, as_of=ten)
    assert not refreshes(same_instant, _row("row-4", supported=(_region(window=_WEEK),), as_of=ten))


def test_what_never_supersedes_is_refused_limb_by_limb() -> None:
    """§8's "what never supersedes", each stated so a later lane cannot read it back in."""
    week = (_region(window=_WEEK),)
    earlier = _row("row-1", supported=week, read_at=_NOW - timedelta(hours=1))
    later = _row("row-2", supported=week, read_at=_NOW)

    assert not refreshes(later, earlier.model_copy(update={"read_kind": ReadKind.SIGHTED_QUERY}))
    assert not refreshes(
        later,
        earlier.model_copy(
            update={"standing": EvidenceStanding.SUPERSEDED, "superseded_by": "row-0"}
        ),
    )
    assert not refreshes(later.model_copy(update={"supported": ()}), earlier)
    assert not refreshes(later, earlier.model_copy(update={"supported": ()}))
    assert not refreshes(later, earlier.model_copy(update={"source": "a-reader"})), (
        "an absent source is equal to absent and never to a present value"
    )
    assert refresh_set(later, (later,)) == (), "and never the row being written"


def test_an_interpretation_row_refreshes_nothing_on_this_tree() -> None:
    """§5's settling test is not evaluable until the enumeration lands, so it declines.

    §14 rules that "no lane of this decision produces an ``INTERPRETATION`` row" and §17
    repeats it for both lanes, so no such row exists on any tree this predicate runs on.
    Declining is §8 limb 5's own fail-closed direction: it retires nothing. The lane that
    lands ``InterpretationVerdict`` lands this limb with it (#2333).
    """
    week = (_region(window=_WEEK),)
    interpretation = {
        "basis": EvidenceBasis.INTERPRETATION,
        "read_kind": None,
        "declaration": "element-1",
        "records": ("b1",),
        "verdict": "qualifies",
    }
    earlier = _row("row-1", supported=week, read_at=_NOW - timedelta(hours=1)).model_copy(
        update=interpretation
    )
    later = _row("row-2", supported=week, read_at=_NOW).model_copy(update=interpretation)

    assert not affirmative(later)
    assert not refreshes(later, earlier)


# --------------------------------------------------------------------------- #
# §11: the digest the planner sees                                             #
# --------------------------------------------------------------------------- #


def test_the_digest_renders_two_regions_distinguishably() -> None:
    """§18 arm 28, and §11's reason.

    "A rendering that concatenated two regions' axes would show the planner one
    applicability spanning both, which is the manufactured conjunction §2 exists to
    prevent — arriving at the model instead of at the coverage test, where it would be
    *worse*."
    """
    one = _region(window=_SATURDAY, participants=("Alice",))
    two = _region(topics=("weather", "travel"), about_person=("Bob",))

    digest = digest_of(_row(supported=(one, two)))

    assert digest.supported is not None
    assert rendered_region(one) in digest.supported
    assert rendered_region(two) in digest.supported
    assert digest.supported == f"{rendered_region(one)} {rendered_region(two)}"
    assert digest.supported.count("(") == 2, "one delimiter per region, so two read as two"


def test_a_region_renders_its_applied_axes_in_field_order_by_field_name() -> None:
    """§11: window, participants, topics, about_person; unapplied axes omitted.

    A window's ends render as ISO-8601 UTC instants and "an unset end as the absence of
    that end", label values render byte for byte in the region's own order, and a
    non-zero ``elided`` renders as a count.
    """
    rendered = rendered_region(
        _region(window=_SUNDAY, participants=("  Bob  ", "Alice"), topics=("weather",), elided=2)
    )

    assert rendered == (
        "(window=[2026-09-13T00:00:00+00:00, 2026-09-14T00:00:00+00:00); "
        "participants=7:  Bob  ,5:Alice; topics=7:weather; elided=2)"
    )
    assert rendered_region(_region(window=TimeWindow(start=_SUNDAY.start))) == (
        "(window=[2026-09-13T00:00:00+00:00, ))"
    )
    assert rendered_region(_region(window=TimeWindow(end=_SUNDAY.end))) == (
        "(window=[, 2026-09-14T00:00:00+00:00))"
    )


def test_a_value_carrying_a_delimiter_cannot_be_read_as_two_regions() -> None:
    """§11: regions stay distinguishable **whatever the values contain**.

    Every label axis carries model-reachable text — ``participants`` and
    ``about_person`` are ``NonBlankEncodableText``, and a ``TopicLabel`` is constrained
    only in case, length and whitespace runs — so a value may hold a comma, a semicolon,
    a parenthesis or (on two of the three axes) a newline. Without a count, one region
    holding ``"x) (topics=y"`` renders exactly as two regions holding ``"x"`` and
    ``"y"``: a **manufactured conjunction** reaching the planner through the rendering,
    which is the failure §2's regions exist to prevent.

    The count is what separates them, and the value still reaches the seam byte for
    byte — which is the other half §11 requires and which escaping would have broken.
    """
    one_region = rendered_support((_region(topics=("x) (topics=y",)),), 0)
    two_regions = rendered_support((_region(topics=("x",)), _region(topics=("y",))), 0)

    assert one_region != two_regions
    assert one_region == "(topics=12:x) (topics=y)"
    assert two_regions == "(topics=1:x) (topics=1:y)"


@pytest.mark.parametrize(
    "value",
    ["a, b", "a; b", "a) (b", "a\nb", "elided=9", "5:spoof", "a=b", "καφές"],
)
def test_a_value_reaches_the_seam_byte_for_byte_behind_its_count(value: str) -> None:
    """§11: "label values render **byte for byte**", and the count says how many.

    Asserted over each delimiter the rendering uses, over a spoofed count, and over a
    multi-byte value — the last because the count is the value's **UTF-8 byte length**
    and a character count would disagree with it exactly there.
    """
    rendered = rendered_region(_region(participants=(value,)))

    assert rendered == f"(participants={len(value.encode())}:{value})"
    assert value in rendered, "the value's own bytes, unaltered and unescaped"


def test_two_values_on_one_axis_never_read_as_one() -> None:
    """§11 again, at the axis rather than at the region.

    ``("a, b",)`` and ``("a", "b")`` are two different applicabilities — the first
    supports one participant whose name contains a comma, the second supports two — and
    a rendering that collapsed them would have the planner reason from an applicability
    no record carried.
    """
    assert rendered_region(_region(participants=("a, b",))) == "(participants=4:a, b)"
    assert rendered_region(_region(participants=("a", "b"))) == "(participants=1:a,1:b)"


def test_an_absent_requested_and_an_empty_supported_render_as_absent_members() -> None:
    """§11, which is what makes "an absent ``supported`` supports nothing" legible."""
    digest = digest_of(_row(supported=()))

    assert digest.requested is None
    assert digest.supported is None


def test_the_digest_carries_no_identifier_and_says_nothing_about_sufficiency() -> None:
    """§18 arm 28: no row id, no memory id, and no member saying *satisfied*.

    Nor does it carry ``basis``, ``read_kind``, ``source``, ``declaration``, ``records``,
    ``returned``, ``admitted``, the marks, or the row's goal or attempt: "there is none
    on the value to disclose".
    """
    row = _row(
        "row-secret",
        goal_id="goal-secret",
        attempt_id="attempt-secret",
        supported=(_region(topics=("weather",)),),
        records=("memory-secret",),
        returned=1,
    )

    digest = digest_of(row)

    rendered = digest.model_dump_json()
    for secret in ("row-secret", "goal-secret", "attempt-secret", "memory-secret"):
        assert secret not in rendered
    assert set(type(digest).model_fields) == {
        "requested",
        "supported",
        "read_at",
        "as_of",
        "verdict",
        "standing",
    }


def test_every_row_is_projected_in_the_total_order_marked_ones_included() -> None:
    """§11: "Every row is projected, ``INAPPLICABLE`` and ``SUPERSEDED`` ones included".

    "A digest sequence filtered to ``STANDING`` would make the member constant and the
    sentence false." The order is §12's — ``read_at`` oldest first, ties broken by ``id``
    ascending — which is what the ``E`` labels are ordinals into.
    """
    older = _row("row-b", read_at=_NOW - timedelta(hours=1))
    tie_a = _row("row-a", standing=EvidenceStanding.SUPERSEDED, superseded_by="row-b")
    tie_c = GoalEvidence(
        **{
            **_row("row-c").model_dump(),
            "standing": EvidenceStanding.INAPPLICABLE,
            "inapplicable_at_revision": 2,
        }
    )

    projected = digests((tie_c, tie_a, older))

    assert [one.standing for one in projected] == [
        EvidenceStanding.STANDING,
        EvidenceStanding.SUPERSEDED,
        EvidenceStanding.INAPPLICABLE,
    ]
    assert [one.id for one in ordered_history((tie_c, tie_a, older))] == [
        "row-b",
        "row-a",
        "row-c",
    ]


# --------------------------------------------------------------------------- #
# §14: the production rule, driven through the real path                       #
# --------------------------------------------------------------------------- #


async def _rows_of(
    *asks: ReadAsk,
    refusal: SearchRefusal | None = None,
    seeded: Sequence[tuple[str, str]] = (("belief-1", "the bell tower is in Porto"),),
    extra: Sequence[MemoryRecord] = (),
) -> tuple[GoalEvidence, ...]:
    """Run one production turn asking for ``asks``, and return the rows it composed.

    **The turn is a production one end to end** — the real ``LearningLoop`` over the real
    :func:`~ai_assistant.orchestration.reads.service_read_request`, a real
    ``SearchServicer`` over canonical fakes, and a planner whose only scripting is which
    request its first plan carries — so what is read off ``RespondedTurn.evidence`` is
    what ``Engine`` writes, composed from the records a source actually returned.

    Args:
        asks: What the first plan asks for.
        refusal: What the searcher answers the composed query with, or ``None``.
        seeded: The beliefs the store holds, as ``(id, content)`` pairs. At least one
            non-episodic record is what ADR-0240 §5's separator condition needs, so a
            structured read reaches the store at all.
        extra: Any further records the store holds, built by a case for the axes it
            wants a region composed from.

    Returns:
        The rows the turn composed, in the order it composed them.
    """
    memory = FakeMemoryStore(now=_clock)
    for record_id, content in seeded:
        await memory.add(_belief(record_id, content))
    for record in extra:
        await memory.add(record)
    planner = FakePlanner(now=_clock, read_request=ReadRequest(asks=asks), revision=ActionPlanFor())
    searcher = FakeWebSearcher(
        results=(_RESULT,),
        refusals=None if refusal is None else {DEFAULT_COMPOSED_QUERY: refusal},
    )
    responded = await _loop(
        planner=planner,
        memory=memory,
        search=_servicer(searcher=_CostedSearcher(searcher), granted=True),
    ).respond(_ASK, narrow=_bounded(), operation=ConversationalOperation.CONVERSE)
    return responded.evidence


async def test_every_outcome_entry_writes_exactly_one_row() -> None:
    """§18 arm 37, and §14's production rule.

    "A **completed** servicing produces **exactly one** ``READ_OUTCOME`` row per ask it
    reached that produced an outcome entry", and the member the entry carries "decides
    the row's ``verdict`` and decides nothing about whether the row is written".
    """
    rows = await _rows_of(
        ReadAsk(kind=ReadKind.WEB_SEARCH),
        ReadAsk(kind=ReadKind.SIGHTED_QUERY, query="bell tower"),
    )

    assert [row.read_kind for row in rows] == [ReadKind.WEB_SEARCH, ReadKind.SIGHTED_QUERY], (
        "one row per entry, in ADR-0226 §6's servicing order and not the request's"
    )
    assert len({row.id for row in rows}) == 2, "each minted by the loop's own id factory"
    assert all(row.basis is EvidenceBasis.READ_OUTCOME for row in rows)
    assert all(row.standing is EvidenceStanding.STANDING for row in rows)
    assert all(row.source is None for row in rows), "§1: absent on every row these producers write"
    assert all(row.declaration is None for row in rows), "§1: absent on every READ_OUTCOME row"


@pytest.mark.parametrize(
    ("refusal", "verdict"),
    [
        (SearchRefusal.NO_RESULT, ReadOutcomeKind.EMPTY),
        (SearchRefusal.PROVIDER_REFUSED, ReadOutcomeKind.REFUSED),
        (SearchRefusal.TRANSPORT_FAILED, ReadOutcomeKind.FAILED),
        (SearchRefusal.DEADLINE_EXPIRED, ReadOutcomeKind.EXPIRED),
    ],
)
async def test_a_non_answering_entry_is_still_recorded_with_supported_empty(
    refusal: SearchRefusal, verdict: ReadOutcomeKind
) -> None:
    """§18 arms 5 and 37: "``EMPTY`` … ``REFUSED``, ``FAILED`` and ``EXPIRED`` … are each recorded".

    §18 arm 5's composition half is here too: an ``EMPTY`` row carries ``supported``
    empty, and **nothing composes an assertion that the thing did not happen** — the row
    records that an ask was made and came back with nothing, which is all ADR-0237 §7
    permits a consumer to read off it.
    """
    rows = await _rows_of(ReadAsk(kind=ReadKind.WEB_SEARCH), refusal=refusal)

    [search] = [one for one in rows if one.read_kind is ReadKind.WEB_SEARCH]
    assert search.verdict == verdict.value
    assert search.supported == ()
    assert search.records == ()
    assert not affirmative(search)


async def test_a_turn_that_asked_for_no_read_composes_no_row() -> None:
    """§14: a turn that did not fire has no entry, so it writes nothing."""
    responded = await _loop(planner=FakePlanner(now=_clock)).respond(
        _ASK, narrow=_bounded(), operation=ConversationalOperation.CONVERSE
    )

    assert responded.evidence == ()


async def test_a_query_naming_a_period_supports_no_period_where_the_episodes_declare_none() -> None:
    """§18 arm 11, driven through a real structured read.

    "A ``STRUCTURED_READ`` whose returned episodes declare no interval carries
    ``requested`` with its window and ``supported`` whose regions apply **no** window,
    and satisfies no condition that declares one." This is the addendum's own sentence
    made mechanical: *a query asking for Sunday's forecast does not establish that its
    result describes Sunday.*
    """
    episode = _episode("e-sunday", topics=("weather",))
    ask = ReadAsk(
        kind=ReadKind.STRUCTURED_READ, structure=StructuredAsk(window=_SUNDAY, topics=("weather",))
    )

    rows = await _rows_of(ask, extra=(episode,))

    [structured] = [one for one in rows if one.read_kind is ReadKind.STRUCTURED_READ]
    assert structured.requested == _region(window=_SUNDAY, topics=("weather",))
    assert structured.supported == (_region(topics=("weather",)),)
    assert not any(region.covers(_region(window=_SUNDAY)) for region in structured.supported), (
        "what was asked for is not what the response established"
    )


async def test_a_web_search_row_is_written_and_supports_nothing() -> None:
    """§18 arm 38, over the records ADR-0231 §16 actually mints.

    "``topics`` empty, ``about_person`` absent, ``extent`` ``None``" — so the row carries
    ``supported`` empty "while still being written, exported and rendered in the digest".
    Such a row is not useless: it records durably that the source was asked and what
    became of the ask.
    """
    rows = await _rows_of(ReadAsk(kind=ReadKind.WEB_SEARCH))

    [search] = [one for one in rows if one.read_kind is ReadKind.WEB_SEARCH]
    assert search.verdict == ReadOutcomeKind.RETURNED_RECORDS.value, "the source did answer"
    assert search.supported == (), "and established no applicability at all"
    assert search.records == (), "and named no record, because none resolves in a store"
    assert search.returned == 1, "while the count says one came back"
    assert digest_of(search).supported is None, "which the digest renders as an absent member"


async def test_no_axis_is_inferred_from_the_query_the_ordering_or_the_response() -> None:
    """§3's prohibition list, asserted where a composition could reach for each route.

    ``supported`` is never derived from ``requested``, from the ask, the query, the
    labels or the entry; never from the fact that a read completed; never from a
    ``ReadOutcomeKind`` member on its own; never from a model's sentence; and never from
    any inspection of a record's text. The sighted query names *Sunday* and *weather* in
    its own text and the seeded belief's content says both; the row composed from that
    response carries neither, because the record applied no axis.
    """
    seeded = (("belief-1", "sunday will be rainy weather in Porto"),)

    rows = await _rows_of(
        ReadAsk(kind=ReadKind.SIGHTED_QUERY, query="sunday weather"), seeded=seeded
    )

    [query] = [one for one in rows if one.read_kind is ReadKind.SIGHTED_QUERY]
    assert query.requested is None, "a composed query is a model completion, not a record"
    assert query.supported == (), "and nothing was read out of the record's own text"
    assert query.records == ("belief-1",), "the record it returned is named, being store-resident"


# --------------------------------------------------------------------------- #
# §10: the `E` label space, over the sequence the planner was handed           #
# --------------------------------------------------------------------------- #


def _continuing() -> Goal:
    """A goal an earlier turn opened, so this turn's history is a real one."""
    return Goal(
        id="goal-earlier",
        conversation_id="c-1",
        interpretation=(
            GoalInterpretation(
                revision=1,
                outcome="book a campsite",
                outcome_ground=Ground.USER_STATED,
                outcome_span="book a campsite",
                recorded_at=_NOW,
                raised_by="turn-earlier",
            ),
        ),
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_NOW),
        created_at=_NOW,
        last_engaged_at=_NOW,
        version=4,
    )


async def _grounded_on(label: str, *, history: Sequence[GoalEvidence]) -> GoalElement | None:
    """Run a turn whose planner grounds one condition on ``label``, and return it.

    The turn is a production one: the real loop, the real resolver, and the history
    handed in exactly as ``Engine`` hands it — which is the point, because §10's label
    is an ordinal into *the sequence the call was handed* and an arm over the resolver
    alone would not be reading that sequence.

    Args:
        label: What the planner named.
        history: This goal's evidence rows, as the store holds them.

    Returns:
        The element the revision recorded, or ``None`` where the ground resolved to
        nothing and it was dropped.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("m-seed", "the campsite takes bookings"))
    planner = FakePlanner(
        now=_clock,
        understanding=ProposedUnderstanding(
            retains_outcome=True,
            conditions=(
                ProposedElement(
                    text="sunday is forecast dry", ground=Ground.FROM_EVIDENCE, evidence_label=label
                ),
            ),
        ),
    )

    responded = await _loop(planner=planner, memory=memory).respond(
        _ASK,
        narrow=_bounded(),
        operation=ConversationalOperation.CONVERSE,
        continuing=_continuing(),
        evidence=history,
    )

    record = responded.goal
    assert record is not None
    conditions = record.goal.interpretation[-1].conditions
    return conditions[0] if conditions else None


async def test_an_e_label_resolves_against_evidence_and_an_m_label_against_memories() -> None:
    """§18 arm 18, first clause, and §10's prefix rule.

    "The prefix is the whole of what decides which sequence ``orchestration`` resolves it
    against", and the element carries **exactly one** of ``evidence_id`` and
    ``evidence_row_id`` — so the two spaces are mutually exclusive at the value as well
    as at the label. ``ProposedElement`` gains no field for it.
    """
    history = (_row("row-old", read_at=_NOW - timedelta(hours=1)), _row("row-new", read_at=_NOW))

    by_row = await _grounded_on("E2", history=history)
    by_record = await _grounded_on("M1", history=history)

    assert by_row is not None
    assert by_row.evidence_row_id == "row-new", "the row at 1-based index 2 of §12's order"
    assert by_row.evidence_id is None
    assert by_record is not None
    assert by_record.evidence_id == "m-seed"
    assert by_record.evidence_row_id is None


@pytest.mark.parametrize("label", ["E3", "E0", "E01", "X1", "E", ""])
async def test_a_label_that_names_nothing_drops_the_element_silently(label: str) -> None:
    """§18 arm 18: out of range, below 1, padded, of neither form, and bare.

    "A label of neither form, an *n* below 1 or beyond the sequence's length, and an
    ``E`` label naming a row the store no longer holds each resolve to nothing", and the
    element is dropped — "not an error, not a park, not a degradation of the turn". The
    third case needs no arm of its own: a row §13's elision dropped is not in the history
    the call was handed, so its ordinal is past the end like any other.
    """
    history = (_row("row-old", read_at=_NOW - timedelta(hours=1)), _row("row-new", read_at=_NOW))

    assert await _grounded_on(label, history=history) is None


async def test_the_outcome_grounds_on_a_row_on_the_same_rule_as_an_element() -> None:
    """§10: "``GoalInterpretation`` gains ``outcome_evidence_row_id`` on the same rule".

    ADR-0249 §1 validates the outcome's arguments "as a ``GoalElement``'s are", so the
    outcome resolves through the same two label spaces and carries exactly one argument.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("m-seed", "the campsite takes bookings"))
    planner = FakePlanner(
        now=_clock,
        understanding=ProposedUnderstanding(
            outcome="book the campsite for sunday",
            outcome_ground=Ground.FROM_EVIDENCE,
            outcome_evidence_label="E1",
        ),
    )

    responded = await _loop(planner=planner, memory=memory).respond(
        _ASK,
        narrow=_bounded(),
        operation=ConversationalOperation.CONVERSE,
        continuing=_continuing(),
        evidence=(_row("row-only"),),
    )

    record = responded.goal
    assert record is not None
    revision = record.goal.interpretation[-1]
    assert revision.outcome_ground is Ground.FROM_EVIDENCE
    assert revision.outcome_evidence_row_id == "row-only"
    assert revision.outcome_evidence_id is None


async def test_a_retained_outcome_keeps_its_row_reference_byte_for_byte() -> None:
    """§10 with ADR-0249 §7's retention: the fourth argument is copied forward too.

    A retained outcome that quietly lost its row reference would break §7's "copied
    forward **byte for byte**" on the one argument this decision adds.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("m-seed", "the campsite takes bookings"))
    earlier = _continuing()
    grounded = earlier.model_copy(
        update={
            "interpretation": (
                earlier.interpretation[0].model_copy(
                    update={
                        "outcome_ground": Ground.FROM_EVIDENCE,
                        "outcome_span": None,
                        "outcome_evidence_row_id": "row-only",
                    }
                ),
            )
        }
    )
    planner = FakePlanner(
        now=_clock, understanding=ProposedUnderstanding(retains_outcome=True, constraints=())
    )

    responded = await _loop(planner=planner, memory=memory).respond(
        _ASK,
        narrow=_bounded(),
        operation=ConversationalOperation.CONVERSE,
        continuing=grounded,
        evidence=(_row("row-only"),),
    )

    record = responded.goal
    assert record is not None
    assert record.goal.interpretation[-1].outcome_evidence_row_id == "row-only"


async def test_the_planner_is_handed_one_digest_per_row_in_the_label_order() -> None:
    """§11 at the seam: the sequence the `E` labels are ordinals into.

    Read off the argument the planner was **actually handed**, which is the only place
    the correspondence between the label space and the projection is checkable.
    """
    history = (_row("row-new", read_at=_NOW), _row("row-old", read_at=_NOW - timedelta(hours=1)))
    planner = FakePlanner(now=_clock)

    await _loop(planner=planner, memory=FakeMemoryStore(now=_clock)).respond(
        _ASK,
        narrow=_bounded(),
        operation=ConversationalOperation.CONVERSE,
        continuing=_continuing(),
        evidence=history,
    )

    [call] = planner.calls
    assert call[7] == digests(history)
    assert [one.read_at for one in call[7]] == [_NOW - timedelta(hours=1), _NOW]
