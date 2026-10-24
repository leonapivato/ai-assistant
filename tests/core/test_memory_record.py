"""The memory record (ADR-0328 §§3-9, §15): its shape, its computed values, its operations.

A memory is a statement resting on supports; its standing is computed from them; every
change to it is an operation citing one. These cases pin what ``core`` holds of that:
the validators that make a malformed memory unconstructable, the values §7 computes on
read, the one function both writers apply an operation through, and the projections
§15 has a surface read.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.types import (
    Attestation,
    Belief,
    BeliefBand,
    BeliefSummary,
    EpisodicMemory,
    EvidenceItemPart,
    InputPart,
    LegacyPart,
    Memory,
    MemoryKind,
    MemoryOperation,
    MemoryOperationKind,
    MemoryRecord,
    MemoryRetirement,
    MemorySource,
    MemoryStanding,
    MemoryStatus,
    MemorySupport,
    MemoryUpdateProposal,
    MemoryWriterName,
    ObserverInferencePart,
    OpenQuestion,
    OpenQuestionKind,
    PinPart,
    Provenance,
    ReadingCertainty,
    RecallCue,
    RecalledItem,
    RecallProvenance,
    RememberCallPart,
    SupportDirection,
    SupportOrigin,
    TrackRecordEntry,
    belief_summary,
    belief_view,
    episode_summary,
    episode_view,
    origin_is_outside,
    origin_standing,
    part_episode,
    record_attestation,
    record_band,
    record_rests_on_outside_content,
    record_transaction_time,
    standing_band,
    standing_rank,
)
from ai_assistant.testing.memories import (
    AT,
    HELD_EPISODE,
    confirmed_support,
    inference_support,
    legacy_support,
    memory,
    message_support,
    pinned_support,
    remembered_support,
    said_support,
    sourced_support,
    support_with_origin,
)

_LATER = AT + timedelta(days=1)
_SOURCE = Attestation(reported_by="calendar:work", reported_at=AT)


def _operation(
    kind: MemoryOperationKind,
    cites: MemorySupport,
    *,
    at: datetime = _LATER,
    **fields: object,
) -> MemoryOperation:
    return MemoryOperation.model_validate(
        {"kind": kind, "cites": cites.points_at, "at": at, "by": MemoryWriterName.REMEMBER} | fields
    )


def _logged(held: Memory, operation: MemoryOperation, *added: MemorySupport) -> Memory:
    """``held`` with ``operation`` logged and ``added`` carried, validated as a record.

    Built from the record's own shape, so these cases test what ``core`` computes from a
    record (§6, §7) and not how a writer applies an operation, which is ``memory``'s
    (§11:3; ``tests/memory/test_operations.py``).
    """
    return Memory.model_validate(
        held.model_dump()
        | {"supports": (*held.supports, *added), "operations": (*held.operations, operation)}
    )


# --- the origin table (§4) --------------------------------------------------------


@pytest.mark.parametrize(
    ("origin", "standing", "outside"),
    [
        (SupportOrigin.USER_MESSAGE, MemoryStanding.SAID, False),
        (SupportOrigin.OUTSIDE_INPUT, MemoryStanding.SOURCE, True),
        (SupportOrigin.CONFIRMATION, MemoryStanding.CONFIRMED, False),
        (SupportOrigin.EVIDENCE, MemoryStanding.SOURCE, True),
        (SupportOrigin.ASSISTANT_MESSAGE, MemoryStanding.SOURCE, False),
        (SupportOrigin.ASSISTANT_MESSAGE_OVER_OUTSIDE, MemoryStanding.SOURCE, True),
        (SupportOrigin.REMEMBERED, MemoryStanding.INFERENCE, False),
        (SupportOrigin.REMEMBERED_OVER_OUTSIDE, MemoryStanding.INFERENCE, True),
        (SupportOrigin.LEGACY, MemoryStanding.INFERENCE, False),
        (SupportOrigin.LEGACY_OUTSIDE, MemoryStanding.INFERENCE, True),
        (SupportOrigin.PINNED, MemoryStanding.CONFIRMED, False),
    ],
)
def test_the_origin_table_ranks_every_origin(
    origin: SupportOrigin, standing: MemoryStanding, outside: bool
) -> None:
    """§4's origin table, row by row, over the whole enum."""
    assert origin_standing(origin) is standing
    assert origin_is_outside(origin) is outside


def test_the_four_standings_are_ordered_and_grouped_into_the_three_bands() -> None:
    """§6:1 and §6:4: confirmed above said above source above inference."""
    order = [
        MemoryStanding.CONFIRMED,
        MemoryStanding.SAID,
        MemoryStanding.SOURCE,
        MemoryStanding.INFERENCE,
    ]
    assert sorted(MemoryStanding, key=standing_rank, reverse=True) == order
    assert [standing_band(one) for one in order] == [
        BeliefBand.ASSERTED,
        BeliefBand.ASSERTED,
        BeliefBand.ATTESTED,
        BeliefBand.DERIVED,
    ]


# --- a support (§4) ---------------------------------------------------------------


def test_a_support_takes_only_the_origins_its_part_admits() -> None:
    with pytest.raises(ValidationError, match="cannot take"):
        MemorySupport(
            points_at=InputPart(episode=HELD_EPISODE),
            origin=SupportOrigin.EVIDENCE,
            direction=SupportDirection.FOR,
            backs_as_worded=True,
            added_at=AT,
            added_by=MemoryWriterName.REMEMBER,
        )


def test_a_confirmation_is_sure_and_a_remember_call_is_not_judged() -> None:
    """§4:11: code sets how sure where code alone reads the part."""
    with pytest.raises(ValidationError, match="sure"):
        MemorySupport.model_validate(confirmed_support().model_dump() | {"how_sure": None})
    with pytest.raises(ValidationError, match="not judged"):
        MemorySupport.model_validate(
            remembered_support().model_dump() | {"how_sure": ReadingCertainty.LIKELY}
        )


# --- a pin's support (ADR-0338 §4:4) ---------------------------------------------


def test_a_pin_is_a_part_addressed_by_the_pins_id_and_takes_only_pinned() -> None:
    """§4:4: the part table gains a pin, by its id; the origin table gains ``pinned``."""
    support = pinned_support("pin-7")
    assert support.points_at == PinPart(pin="pin-7")
    assert support.origin is SupportOrigin.PINNED
    assert not support.outside
    with pytest.raises(ValidationError, match="cannot take"):
        MemorySupport.model_validate(support.model_dump() | {"origin": SupportOrigin.CONFIRMATION})
    with pytest.raises(ValidationError, match="cannot take"):
        MemorySupport.model_validate(said_support().model_dump() | {"origin": SupportOrigin.PINNED})
    with pytest.raises(ValidationError):
        PinPart(pin=" ")


def test_a_pin_points_into_no_episode() -> None:
    """ADR-0338 §4:5: the person-model store holds the pin, so §4:7's check does not bind."""
    assert part_episode(PinPart(pin="pin-1")) is None
    assert pinned_support().points_at.part == "pin"


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"backs_as_worded": False}, "as worded"),
        ({"how_sure": ReadingCertainty.LIKELY}, "sure"),
        ({"how_sure": None}, "sure"),
        ({"when": None}, "instant the pin was made"),
        ({"about_when": AT}, "about-when"),
        ({"source_details": Attestation(reported_by="x", reported_at=AT)}, "source details"),
        ({"added_by": MemoryWriterName.REMEMBER}, "only the observer"),
    ],
    ids=[
        "not-as-worded",
        "likely",
        "not-judged",
        "undated",
        "about-when",
        "source-details",
        "not-the-observer",
    ],
)
def test_a_pinned_support_is_for_as_worded_sure_and_dated_at_the_pin(
    change: dict[str, object], match: str
) -> None:
    """§4:4, §4:6: ``for``, as worded, ``sure``, the pin's instant, nothing else; observer's."""
    with pytest.raises(ValidationError, match=match):
        MemorySupport.model_validate(pinned_support().model_dump() | change)


def test_a_pinned_support_may_be_added_against_a_memory_where_a_dispute_is_recorded() -> None:
    """ADR-0345 §3:8 adds the one other place a pin's support goes: ``against``, backing nothing.

    A placed write records a dispute by adding a memory's backing to the memory that
    contradicts it, a pin's support among them (ADR-0338 §4:5, in the addition alone).
    """
    against = MemorySupport.model_validate(
        pinned_support().model_dump()
        | {"direction": SupportDirection.AGAINST, "backs_as_worded": False}
    )
    assert against.direction is SupportDirection.AGAINST
    assert not against.backs_as_worded


def test_a_pinned_support_raises_its_memory_to_you_confirmed_this_wording() -> None:
    """ADR-0338 §4:3 through ADR-0328 §6:1's bands: inference, then confirmed, ``ASSERTED``."""
    inferred = memory("m", "c", remembered_support())
    assert inferred.standing is MemoryStanding.INFERENCE
    pinned = memory("m", "c", remembered_support(), pinned_support())
    assert pinned.standing is MemoryStanding.CONFIRMED
    assert pinned.band is BeliefBand.ASSERTED
    assert record_band(pinned) is BeliefBand.ASSERTED
    assert not pinned.rests_on_outside_content


def test_a_pinned_support_shows_on_the_single_view_as_a_pin() -> None:
    """ADR-0328 §15:2: the view carries the part's kind and its origin, never the pin's id."""
    support = pinned_support("pin-secret")
    view = belief_view(
        memory("m", "c", said_support(), support),
        now=_LATER,
        contents={support.points_at: "you pinned this"},
    )
    shown = view.supports[1]
    assert (shown.part, shown.origin, shown.content) == (
        "pin",
        SupportOrigin.PINNED,
        "you pinned this",
    )
    assert "pin-secret" not in view.model_dump_json()


def test_only_a_source_carries_source_details() -> None:
    """§4:13."""
    with pytest.raises(ValidationError, match="source details"):
        MemorySupport.model_validate(said_support().model_dump() | {"source_details": _SOURCE})
    assert sourced_support(_SOURCE).source_details == _SOURCE


def test_an_against_support_never_backs_the_claim_as_worded() -> None:
    """§4:10."""
    with pytest.raises(ValidationError, match="against"):
        MemorySupport.model_validate(
            said_support().model_dump() | {"direction": SupportDirection.AGAINST}
        )
    assert not said_support(direction=SupportDirection.AGAINST).backs_as_worded


def test_a_support_carries_a_record_exactly_when_it_is_a_legacy_one() -> None:
    """§16:4: a legacy support carries the record whole, and no other support carries one."""
    with pytest.raises(ValidationError, match="legacy"):
        MemorySupport.model_validate(said_support().model_dump() | {"carries": {"id": "x"}})
    with pytest.raises(ValidationError, match="legacy"):
        MemorySupport.model_validate(legacy_support({"id": "x"}).model_dump() | {"carries": None})


# --- a memory's shape (§3, §5) ----------------------------------------------------


def test_a_memory_rests_on_at_least_one_support_one_per_part() -> None:
    """§3:3, §4:8."""
    with pytest.raises(ValidationError):
        Memory.model_validate(memory("m", "c").model_dump() | {"supports": ()})
    with pytest.raises(ValidationError, match="one support per part"):
        memory("m", "c", said_support(), said_support())


def test_a_memory_carries_no_provenance_and_no_confidence() -> None:
    """§3:1, §10:2: its supports are its provenance."""
    assert "provenance" not in Memory.model_fields
    assert not any("confidence" in name for name in Memory.model_fields)


def test_a_log_begins_with_exactly_one_create_citing_a_backing_for_support() -> None:
    """§3:3."""
    held = said_support()
    against = said_support("activation:other", direction=SupportDirection.AGAINST)
    with pytest.raises(ValidationError, match="begins with exactly one create"):
        Memory.model_validate(
            memory("m", "c", held).model_dump()
            | {"operations": (_operation(MemoryOperationKind.END, held),)}
        )
    with pytest.raises(ValidationError, match="for support"):
        memory("m", "c", against)


def test_every_operation_cites_a_support_the_memory_carries() -> None:
    """§5:3."""
    held = said_support()
    elsewhere = said_support("activation:elsewhere")
    created = memory("m", "c", held)
    with pytest.raises(ValidationError, match="cites a support"):
        Memory.model_validate(
            created.model_dump()
            | {
                "operations": (
                    *created.operations,
                    _operation(MemoryOperationKind.ADD_SUPPORT, elsewhere),
                )
            }
        )


def test_a_status_follows_from_the_log_and_closes_the_window() -> None:
    """§3:4, §5:7."""
    created = memory("m", "c")
    with pytest.raises(ValidationError, match="status follows"):
        Memory.model_validate(created.model_dump() | {"status": MemoryStatus.ENDED})


@pytest.mark.parametrize(
    ("fields", "fault"),
    [
        ({"replaces": ("x",), "kind": MemoryOperationKind.END}, "only a create names"),
        ({"successor": "x", "kind": MemoryOperationKind.ADD_SUPPORT}, "successor"),
        ({"kind": MemoryOperationKind.REPLACE}, "narrower memory"),
        ({"kind": MemoryOperationKind.STOP_COUNTING}, "stop counting"),
        ({"kind": MemoryOperationKind.RAISE_QUESTION}, "raise question"),
    ],
)
def test_an_operations_fields_follow_its_kind(fields: dict[str, object], fault: str) -> None:
    """§5's table: each kind names exactly what it needs."""
    with pytest.raises(ValidationError, match=fault):
        MemoryOperation.model_validate(
            {
                "cites": InputPart(episode=HELD_EPISODE),
                "at": AT,
                "by": MemoryWriterName.REMEMBER,
            }
            | fields
        )


def test_a_track_record_entry_is_unique_by_episode() -> None:
    """§8:3."""
    entry = TrackRecordEntry(
        episode="activation:used",
        relied_at=AT,
        held_up=True,
        recorded_at=AT,
        recorded_by=MemoryWriterName.REMEMBER,
    )
    with pytest.raises(ValidationError, match="unique by its episode"):
        memory("m", "c", track_record=(entry, entry))


def test_an_open_question_is_only_carried_where_an_operation_raised_it() -> None:
    """§9:2."""
    held = said_support()
    question = OpenQuestion(
        id="q-1",
        kind=OpenQuestionKind.RECHECK,
        asks="is this still so?",
        rests_on=(held.points_at,),
        raised_at=AT,
        raised_by=MemoryWriterName.REMEMBER,
    )
    with pytest.raises(ValidationError, match="raised by an operation"):
        memory("m", "c", held, open_questions=(question,))


# --- standing and the values §7 computes ------------------------------------------


@pytest.mark.parametrize("origin", list(SupportOrigin), ids=str)
def test_a_memorys_standing_is_its_backing_supports_highest_origin(origin: SupportOrigin) -> None:
    """§6:2: one support, so its origin's rank is the standing."""
    held = memory("m", "c", support_with_origin(origin))
    assert held.standing is origin_standing(origin)
    assert held.band is standing_band(origin_standing(origin))


def test_the_highest_backing_support_decides_and_a_stopped_one_counts_for_nothing() -> None:
    """§6:2, §5:8: a lookup and a maximum, over counted supports only."""
    inferred = remembered_support()
    said = said_support()
    held = memory("m", "c", inferred, said)
    assert held.standing is MemoryStanding.SAID

    stopped = _logged(
        held, _operation(MemoryOperationKind.STOP_COUNTING, said, stops=inferred.points_at)
    )
    assert stopped.standing is MemoryStanding.SAID
    assert inferred not in stopped.counted_supports


def test_a_for_support_not_backing_the_wording_ranks_for_nothing() -> None:
    """§6:2's two conditions apart: ``for`` *and* backing the memory as worded.

    The user's message bears on the claim without stating it as worded, so it does not
    lift the standing: the remembered support over outside content alone ranks, the
    memory stands at inference in band ``DERIVED`` and rests on outside content, and
    the user's message still counts in the evidence summary.
    """
    over_outside = remembered_support(outside=True)
    related = said_support("activation:related").model_copy(update={"backs_as_worded": False})
    held = memory("m", "c", over_outside, related)

    assert (held.standing, held.band) == (MemoryStanding.INFERENCE, BeliefBand.DERIVED)
    assert held.rests_on_outside_content
    assert held.evidence_summary.supporting == 2


def test_stopping_the_highest_backing_support_lowers_the_standing_and_its_band() -> None:
    """§5:8, §6:2: a stopped support ranks for nothing, so the standing falls with it.

    The user's own backing explained away by a user-origin ``against`` support (equal
    rank, so §6:5 permits it) leaves the remembered support alone counting: the memory
    stands at inference, in band ``DERIVED``.
    """
    inferred = remembered_support()
    said = said_support()
    explaining = said_support("activation:no", direction=SupportDirection.AGAINST)
    held = memory("m", "c", said, inferred, explaining)
    assert (held.standing, held.band) == (MemoryStanding.SAID, BeliefBand.ASSERTED)

    stopped = _logged(
        held, _operation(MemoryOperationKind.STOP_COUNTING, explaining, stops=said.points_at)
    )

    assert (stopped.standing, stopped.band) == (MemoryStanding.INFERENCE, BeliefBand.DERIVED)


def test_an_against_support_never_raises_the_standing() -> None:
    """§6:2: only ``for`` supports backing as worded rank."""
    held = memory(
        "m",
        "c",
        remembered_support(),
        said_support("activation:no", direction=SupportDirection.AGAINST),
    )
    assert held.standing is MemoryStanding.INFERENCE
    assert held.evidence_summary.against == 1


def test_the_evidence_summary_counts_counted_supports_and_their_episodes() -> None:
    """§7:2."""
    held = memory(
        "m",
        "c",
        remembered_support("activation:a", when=AT),
        message_support("activation:a", when=_LATER),
        said_support("activation:b", when=AT, direction=SupportDirection.AGAINST),
    )
    summary = held.evidence_summary
    assert (summary.supporting, summary.against, summary.episodes) == (2, 1, 2)
    assert summary.latest == _LATER


def test_as_of_reads_a_sources_report_and_never_the_readers_future() -> None:
    """§7:3: source details' ``reported_at`` first, ``when`` otherwise; a future one is unusable."""
    future = AT + timedelta(days=30)
    held = memory(
        "m",
        "c",
        sourced_support(Attestation(reported_by="calendar", reported_at=AT), when=_LATER),
        remembered_support("activation:x", when=future),
    )
    assert held.as_of(_LATER) == AT
    assert held.as_of(future) == future
    assert memory("m", "c", remembered_support(when=None)).as_of(_LATER) is None


def test_learned_is_the_earliest_when_among_all_supports() -> None:
    """§7:4."""
    held = memory(
        "m",
        "c",
        said_support("activation:a", when=_LATER),
        said_support("activation:b", when=AT, direction=SupportDirection.AGAINST),
    )
    assert held.learned == AT
    assert memory("m", "c", remembered_support(when=None)).learned is None


def test_reading_certainty_is_the_best_among_backing_supports() -> None:
    """§7:5: not judged where none carries one."""
    held = memory(
        "m",
        "c",
        message_support("activation:a", how_sure=ReadingCertainty.UNSURE),
        message_support("activation:b", how_sure=ReadingCertainty.LIKELY),
    )
    assert held.reading_certainty is ReadingCertainty.LIKELY
    assert memory("m", "c", remembered_support()).reading_certainty is None


def test_rests_on_outside_content_holds_outside_the_asserted_band_only() -> None:
    """§7:6: never of an assertion, and a stopped outside support still counts here."""
    outside = remembered_support("activation:o", outside=True)
    assert memory("m", "c", outside).rests_on_outside_content
    assert not memory("m", "c", said_support(), outside).rests_on_outside_content
    sourced = memory("m", "c", sourced_support(_SOURCE))
    assert sourced.band is BeliefBand.ATTESTED
    assert sourced.rests_on_outside_content

    inferred = remembered_support()
    held = memory("m", "c", inferred, outside)
    stopped = _logged(
        held, _operation(MemoryOperationKind.STOP_COUNTING, inferred, stops=outside.points_at)
    )
    assert stopped.rests_on_outside_content


def test_transaction_time_is_the_latest_operation() -> None:
    """§7:8."""
    held = memory("m", "c", said_support(added_at=AT))
    assert held.transaction_time == AT
    grown = _logged(
        held,
        _operation(MemoryOperationKind.ADD_SUPPORT, said_support("activation:x")),
        said_support("activation:x"),
    )
    assert grown.transaction_time == _LATER


def test_legacy_and_unbacked_are_computed() -> None:
    """§7:9, §7:10."""
    assert memory("m", "c", legacy_support({"id": "m"})).is_legacy
    assert not memory("m", "c", legacy_support({"id": "m"}), said_support()).is_legacy
    held = memory("m", "c", said_support())
    assert not held.is_unbacked


def test_the_standing_attestation_is_the_latest_backing_sources() -> None:
    """§2:6: where its standing is from a source, and ``None`` otherwise."""
    early = Attestation(reported_by="calendar", reported_at=AT)
    late = Attestation(reported_by="calendar", reported_at=_LATER)
    held = memory(
        "m",
        "c",
        sourced_support(early, episode="activation:a", when=AT),
        sourced_support(late, episode="activation:b", when=_LATER),
    )
    assert held.standing_attestation == late
    assert memory("m", "c", said_support()).standing_attestation is None


def test_a_latest_source_support_stating_no_details_answers_none() -> None:
    """§2:6: the latest backing source support's details, ``None`` included.

    An older support's attribution never stands in for a newer one that states none.
    """
    older = Attestation(reported_by="old-calendar", reported_at=AT)
    held = memory(
        "m",
        "c",
        sourced_support(older, episode="activation:a", when=AT),
        message_support("activation:b", when=_LATER),
    )
    assert held.standing is MemoryStanding.SOURCE
    assert held.standing_attestation is None


def test_the_track_summary_counts_its_entries() -> None:
    """§15:1's track-record counts and last use."""

    def entry(episode: str, *, held_up: bool, at: datetime) -> TrackRecordEntry:
        return TrackRecordEntry(
            episode=episode,
            relied_at=at,
            held_up=held_up,
            recorded_at=at,
            recorded_by=MemoryWriterName.REMEMBER,
        )

    held = memory(
        "m",
        "c",
        track_record=(
            entry("activation:a", held_up=True, at=AT),
            entry("activation:b", held_up=False, at=_LATER),
        ),
    )
    summary = held.track_summary
    assert (summary.relied_on, summary.held_up, summary.let_down) == (2, 1, 1)
    assert summary.last_used == _LATER


# --- the stored-record union and its helpers (§2, §12) ----------------------------


def _episode() -> EpisodicMemory:
    return EpisodicMemory(
        id="e",
        content="it happened",
        occurred_at=AT,
        provenance=Provenance(
            source=MemorySource.OBSERVED,
            confidence=0.9,
            last_updated=_LATER,
            derived_from_external=True,
        ),
    )


def test_the_record_helpers_read_a_memory_and_an_episode_alike() -> None:
    """§12: a band, a transaction time, outside content and source details, for either."""
    sourced = memory("m", "c", sourced_support(_SOURCE, added_at=AT))
    episode = _episode()
    assert record_band(sourced) is BeliefBand.ATTESTED
    assert record_band(episode) is BeliefBand.DERIVED
    assert record_transaction_time(sourced) == AT
    assert record_transaction_time(episode) == _LATER
    assert record_rests_on_outside_content(sourced)
    assert record_rests_on_outside_content(episode)
    assert record_attestation(sourced) == _SOURCE
    assert record_attestation(episode) is None


def test_a_memory_round_trips_through_the_stored_union() -> None:
    held = memory("m", "c", sourced_support(_SOURCE), remembered_support("activation:x"))
    adapter: TypeAdapter[MemoryRecord] = TypeAdapter(MemoryRecord)
    assert adapter.validate_json(held.model_dump_json()) == held


# --- the recall item (§2:5, §2:6) -------------------------------------------------


def test_a_recall_item_names_the_memory_kind_and_one_stored_naming_semantic_still_reads() -> None:
    """§2:5: ``RecalledItem`` gains no field, and a stored ``semantic`` item stays as stored."""
    fields = {
        "id": "m",
        "excerpt": "c",
        "provenance": RecallProvenance.USER,
        "standing": BeliefBand.ASSERTED,
        "rests_on_recorded_external_content": False,
        "found_by": (RecallCue.ACTIVATION_INPUT,),
    }
    current = RecalledItem.model_validate(fields | {"kind": MemoryKind.MEMORY})
    assert current.kind is MemoryKind.MEMORY
    old = RecalledItem.model_validate(fields | {"kind": "semantic"})
    assert old.kind is MemoryKind.SEMANTIC


# --- the projections (§15) --------------------------------------------------------


def test_the_listing_carries_every_value_15_1_names_and_no_confidence() -> None:
    """§15:1, §15:3."""
    held = memory(
        "m",
        "the office moved",
        remembered_support("activation:a", when=AT),
        message_support("activation:b", when=_LATER, how_sure=ReadingCertainty.LIKELY),
    )
    summary = belief_summary(held, now=_LATER, supports_gone=False)
    assert summary.standing is MemoryStanding.SOURCE
    assert summary.band is BeliefBand.ATTESTED
    assert summary.status is MemoryStatus.CURRENT
    assert summary.as_of == _LATER
    assert summary.learned == AT
    assert summary.evidence.supporting == 2
    assert summary.reading_certainty is ReadingCertainty.LIKELY
    assert summary.track_record.relied_on == 0
    assert not summary.legacy
    assert not summary.unbacked
    assert not any("confidence" in name or "elided" in name for name in BeliefSummary.model_fields)


def test_the_single_view_resolves_each_support_or_shows_it_gone() -> None:
    """§15:2, §15:7: a gone support still counts and carries no id."""
    first = said_support("activation:a")
    second = remembered_support("activation:b")
    held = memory("m", "c", first, second)
    view = belief_view(held, now=_LATER, contents={first.points_at: "what the user wrote"})
    assert [one.content for one in view.supports] == ["what the user wrote", None]
    assert [one.gone for one in view.supports] == [False, True]
    assert all(one.counts for one in view.supports)
    assert not view.supports_gone
    assert belief_view(held, now=_LATER, contents={}).supports_gone
    assert "points_at" not in view.supports[0].model_dump()


def test_a_legacy_view_is_marked() -> None:
    carried = legacy_support({"id": "m", "content": "c"})
    view = belief_view(memory("m", "c", carried), now=_LATER, contents={carried.points_at: "c"})
    assert view.legacy
    assert view.standing is MemoryStanding.INFERENCE


def test_parts_point_into_their_episodes() -> None:
    """The episodes a memory's supports point at are read off the parts (§4)."""
    assert EvidenceItemPart(episode="e", digest=0, item=1).episode == "e"
    assert RememberCallPart(episode="e", effect="x").episode == "e"
    assert LegacyPart(record="r").record == "r"
    assert sourced_support(_SOURCE).points_at.part == "evidence_item"
    assert support_with_origin(SupportOrigin.OUTSIDE_INPUT).outside


def test_an_episode_a_caller_asked_for_is_projected_without_a_standing() -> None:
    """ADR-0074 §6: ``--kind episodic`` lists episodes, and ``forget`` shows one.

    An episode has no standing, no status and no supports; its band and outside mark
    are its provenance's (§12), and it was learned when it happened.
    """
    episode = _episode()
    summary = episode_summary(episode)
    view = episode_view(episode)
    assert (summary.kind, summary.standing, summary.status) == ("episodic", None, None)
    assert summary.band is BeliefBand.DERIVED
    assert summary.rests_on_outside_content
    assert summary.learned == AT
    assert view.supports == ()
    assert view.model_dump(exclude={"supports"}) == summary.model_dump()


def test_an_attested_episodes_projection_carries_its_attestation() -> None:
    """ADR-0189 §2:1 still binds an episode's projection (ADR-0328 §18 scopes it off a memory).

    An ``EXTERNAL`` episode projects as ``ATTESTED`` with what reported it and when, on
    the listing and on the single view; a memory's projection carries none.
    """
    episode = EpisodicMemory(
        id="e",
        content="a source's report",
        occurred_at=AT,
        provenance=Provenance(
            source=MemorySource.EXTERNAL,
            confidence=0.9,
            last_updated=_LATER,
            attestation=_SOURCE,
        ),
    )
    assert episode_summary(episode).band is BeliefBand.ATTESTED
    assert episode_summary(episode).attestation == _SOURCE
    assert episode_view(episode).attestation == _SOURCE
    assert episode_summary(_episode()).attestation is None


def test_a_memorys_projection_carries_the_source_details_its_standing_rests_on() -> None:
    """§2:6's value on the listing, so it can say which source and when (ADR-0189 §1, §4).

    A memory from a source carries its latest backing source support's details; one at
    any other standing carries none, and a projection claiming some is refused.
    """
    sourced = belief_view(memory("m", "c", sourced_support(_SOURCE)), now=_LATER, contents={})
    assert sourced.attestation == _SOURCE
    said = belief_view(memory("m", "c", said_support()), now=_LATER, contents={})
    assert said.attestation is None
    with pytest.raises(ValidationError, match="from a source"):
        BeliefSummary.model_validate(
            said.model_dump(exclude={"supports"}) | {"attestation": _SOURCE}
        )


def test_a_projection_says_which_kind_it_is_and_carries_its_shape() -> None:
    """A memory's projection carries a standing and supports; an episode's neither."""
    held = belief_view(memory("m", "c"), now=_LATER, contents={})
    assert held.kind == "memory"
    with pytest.raises(ValidationError, match="standing"):
        BeliefSummary.model_validate(held.model_dump(exclude={"supports"}) | {"standing": None})
    with pytest.raises(ValidationError, match="supports"):
        Belief.model_validate(held.model_dump() | {"supports": ()})
    episodic = episode_summary(_episode()).model_dump()
    with pytest.raises(ValidationError, match="standing"):
        BeliefSummary.model_validate(
            episodic | {"standing": MemoryStanding.SAID, "status": MemoryStatus.CURRENT}
        )


# --- ADR-0329's additions: the observer's inference and the retiring proposal -----


def test_an_observers_inference_ranks_at_inference_and_is_not_outside() -> None:
    """ADR-0329 §9:7: the origin ranks at inference and is not outside content."""
    origin = SupportOrigin.OBSERVER_INFERENCE
    assert origin_standing(origin) is MemoryStanding.INFERENCE
    assert not origin_is_outside(origin)
    assert inference_support().added_by is MemoryWriterName.OBSERVER


def test_an_observers_inference_is_addressed_by_its_episode_and_takes_its_origin() -> None:
    """ADR-0329 §9:7: the part is the episode's; only that origin points at it."""
    held = inference_support("activation:drawn")
    assert held.points_at == ObserverInferencePart(episode="activation:drawn")
    with pytest.raises(ValidationError, match="cannot take"):
        MemorySupport.model_validate(held.model_dump() | {"origin": SupportOrigin.REMEMBERED})
    with pytest.raises(ValidationError, match="cannot take"):
        MemorySupport.model_validate(said_support().model_dump() | {"origin": "observer_inference"})


def test_an_observers_inference_carries_no_source_details() -> None:
    """ADR-0329 §9:7: "it carries no source details"."""
    with pytest.raises(ValidationError, match="no source details"):
        MemorySupport.model_validate(inference_support().model_dump() | {"source_details": _SOURCE})


def _stored(record: Memory) -> Memory:
    """``record`` as a store returns it, carrying a revision."""
    return record.model_copy(update={"revision": 1})


@pytest.mark.parametrize(
    "kind",
    [MemoryOperationKind.END, MemoryOperationKind.MARK_WRONG, MemoryOperationKind.REPLACE],
    ids=str,
)
def test_a_retirement_is_an_end_a_mark_wrong_or_a_replace(kind: MemoryOperationKind) -> None:
    """ADR-0329 §12:4: one retiring operation, on a stored memory."""
    retired = _stored(memory("old", "c"))
    retirement = MemoryRetirement(memory=retired, kind=kind, cites=InputPart(episode="e"))
    assert retirement.kind is kind


@pytest.mark.parametrize(
    "kind",
    [
        kind
        for kind in MemoryOperationKind
        if kind
        not in {
            MemoryOperationKind.END,
            MemoryOperationKind.MARK_WRONG,
            MemoryOperationKind.REPLACE,
        }
    ],
    ids=str,
)
def test_a_retirement_by_any_other_operation_is_unconstructable(
    kind: MemoryOperationKind,
) -> None:
    """ADR-0329 §12:4: a proposal retires a memory, so only a retiring kind is carried."""
    with pytest.raises(ValidationError, match="§12:4"):
        MemoryRetirement(
            memory=_stored(memory("old", "c")), kind=kind, cites=InputPart(episode="e")
        )


def test_a_retirement_names_a_memory_a_store_returned() -> None:
    """The write is conditional on the revision read, so the memory carries one."""
    with pytest.raises(ValidationError, match="revision"):
        MemoryRetirement(
            memory=memory("old", "c"), kind=MemoryOperationKind.END, cites=InputPart(episode="e")
        )


def test_a_proposal_does_not_retire_the_memory_it_proposes() -> None:
    """ADR-0329 §12:4, ADR-0328 §5:6: the retired memory and the new one are two."""
    new = memory("same", "c")
    with pytest.raises(ValidationError, match="other than the one it proposes"):
        MemoryUpdateProposal(
            proposed=new,
            rationale="r",
            retiring=MemoryRetirement(
                memory=_stored(memory("same", "old")),
                kind=MemoryOperationKind.END,
                cites=new.supports[0].points_at,
            ),
        )


def test_a_retiring_operation_moves_no_proposal_key() -> None:
    """ADR-0328 §11:11's criterion is over the memory: a retirement keys nothing."""
    new = memory("new", "c")
    bare = MemoryUpdateProposal(proposed=new, rationale="r")
    retiring = bare.model_copy(
        update={
            "retiring": MemoryRetirement(
                memory=_stored(memory("old", "o")),
                kind=MemoryOperationKind.END,
                cites=new.supports[0].points_at,
            )
        }
    )
    assert retiring.proposal_fingerprint == bare.proposal_fingerprint
    assert retiring.question_key == bare.question_key
