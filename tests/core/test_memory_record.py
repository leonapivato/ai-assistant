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
    MemorySource,
    MemoryStanding,
    MemoryStatus,
    MemorySupport,
    MemoryWriterName,
    OpenQuestion,
    OpenQuestionKind,
    Provenance,
    ReadingCertainty,
    RecallCue,
    RecalledItem,
    RecallProvenance,
    RememberCallPart,
    SupportDirection,
    SupportOrigin,
    TrackRecordEntry,
    Validity,
    applied_operation,
    belief_summary,
    belief_view,
    episode_summary,
    episode_view,
    origin_is_outside,
    origin_standing,
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
    legacy_support,
    memory,
    message_support,
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

    stopped = applied_operation(
        held,
        _operation(MemoryOperationKind.STOP_COUNTING, said, stops=inferred.points_at),
    )
    assert stopped.standing is MemoryStanding.SAID
    assert inferred not in stopped.counted_supports


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

    stopped = applied_operation(
        held,
        _operation(MemoryOperationKind.STOP_COUNTING, explaining, stops=said.points_at),
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
    stopped = applied_operation(
        held,
        _operation(MemoryOperationKind.STOP_COUNTING, inferred, stops=outside.points_at),
    )
    assert stopped.rests_on_outside_content


def test_transaction_time_is_the_latest_operation() -> None:
    """§7:8."""
    held = memory("m", "c", said_support(added_at=AT))
    assert held.transaction_time == AT
    grown = applied_operation(
        held,
        _operation(MemoryOperationKind.ADD_SUPPORT, said_support("activation:x")),
        support=said_support("activation:x"),
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


# --- applied_operation (§5) -------------------------------------------------------


def test_add_support_adds_once_and_an_add_of_a_carried_part_changes_nothing() -> None:
    """§4:8, §5:3."""
    held = memory("m", "c", remembered_support())
    added = said_support("activation:x")
    grown = applied_operation(
        held, _operation(MemoryOperationKind.ADD_SUPPORT, added), support=added
    )
    assert grown.supports == (*held.supports, added)
    assert grown.standing is MemoryStanding.SAID
    assert (
        applied_operation(grown, _operation(MemoryOperationKind.ADD_SUPPORT, added), support=added)
        is grown
    )


def test_an_operations_support_must_be_the_one_it_cites() -> None:
    held = memory("m", "c")
    with pytest.raises(ValueError, match="the one it cites"):
        applied_operation(
            held,
            _operation(MemoryOperationKind.ADD_SUPPORT, said_support("activation:x")),
            support=said_support("activation:y"),
        )


def test_a_create_is_never_applied() -> None:
    held = memory("m", "c")
    with pytest.raises(ValueError, match="create"):
        applied_operation(held, held.operations[0])


def test_an_end_closes_the_window_at_its_about_when_and_ends_the_memory() -> None:
    """§5:10, §5:7."""
    held = memory("m", "c", remembered_support())
    ending = MemorySupport.model_validate(
        said_support("activation:end").model_dump() | {"about_when": AT + timedelta(hours=1)}
    )
    ended = applied_operation(held, _operation(MemoryOperationKind.END, ending), support=ending)
    assert ended.status is MemoryStatus.ENDED
    assert ended.validity.valid_until == AT + timedelta(hours=1)
    # Nothing is removed (§5:5).
    assert set(held.supports) <= set(ended.supports)
    assert ended.operations[: len(held.operations)] == held.operations


def test_an_end_whose_about_when_is_after_its_instant_is_refused() -> None:
    held = memory("m", "c", remembered_support())
    later = MemorySupport.model_validate(
        said_support("activation:end").model_dump() | {"about_when": _LATER + timedelta(days=1)}
    )
    with pytest.raises(ValueError, match="about-when"):
        applied_operation(held, _operation(MemoryOperationKind.END, later), support=later)


def test_a_close_clamps_and_never_extends_the_window() -> None:
    """ADR-0080 §1 kept by §5:11."""
    held = memory("m", "c", remembered_support(), validity=Validity(valid_until=AT))
    ended = applied_operation(
        held,
        _operation(MemoryOperationKind.MARK_WRONG, said_support("activation:no")),
        support=said_support("activation:no"),
    )
    assert ended.validity.valid_until == AT
    assert ended.status is MemoryStatus.WRONG


def test_a_replace_names_its_successor_and_ends_the_memory() -> None:
    held = memory("m", "c", remembered_support())
    narrower = said_support("activation:narrower")
    replaced = applied_operation(
        held,
        _operation(MemoryOperationKind.REPLACE, narrower, successor="m-2"),
        support=narrower,
    )
    assert replaced.status is MemoryStatus.ENDED
    assert replaced.operations[-1].successor == "m-2"


def test_a_lower_standing_never_retires_a_higher_one() -> None:
    """§6:5: the open question it needs is raised instead."""
    held = memory("m", "c", said_support())
    inferred = remembered_support("activation:guess")
    with pytest.raises(ValueError, match="ranks below"):
        applied_operation(held, _operation(MemoryOperationKind.END, inferred), support=inferred)


def test_a_lower_standing_never_stops_a_higher_support() -> None:
    said = said_support()
    inferred = remembered_support("activation:guess")
    held = memory("m", "c", said, inferred)
    with pytest.raises(ValueError, match="ranks below"):
        applied_operation(
            held,
            _operation(MemoryOperationKind.STOP_COUNTING, inferred, stops=said.points_at),
        )


def test_a_question_is_raised_and_resolved_by_operations() -> None:
    """§9:2."""
    held = memory("m", "c", remembered_support())
    cites = held.supports[0]
    question = OpenQuestion(
        id="q-1",
        kind=OpenQuestionKind.RECHECK,
        asks="is this still so?",
        rests_on=(cites.points_at,),
        raised_at=_LATER,
        raised_by=MemoryWriterName.REMEMBER,
    )
    raised = applied_operation(
        held,
        _operation(MemoryOperationKind.RAISE_QUESTION, cites, question="q-1"),
        question=question,
    )
    assert raised.open_questions == (question,)
    answer = said_support("activation:answer")
    resolved = applied_operation(
        raised,
        _operation(
            MemoryOperationKind.RESOLVE_QUESTION,
            answer,
            question="q-1",
            note="the user said so",
        ),
        support=answer,
    )
    (closed,) = resolved.open_questions
    assert closed.resolved
    assert closed.resolved_by == answer.points_at
    with pytest.raises(ValueError, match="carries open"):
        applied_operation(
            resolved,
            _operation(MemoryOperationKind.RESOLVE_QUESTION, answer, question="q-1", note="x"),
        )


def test_a_raise_question_cites_a_support_the_question_rests_on() -> None:
    """§5's table: a raise question cites a support the question rests on."""
    first = remembered_support("activation:first")
    second = remembered_support("activation:second")
    held = memory("m", "c", first, second)
    question = OpenQuestion(
        id="q-1",
        kind=OpenQuestionKind.RECHECK,
        asks="is this still so?",
        rests_on=(second.points_at,),
        raised_at=_LATER,
        raised_by=MemoryWriterName.REMEMBER,
    )
    with pytest.raises(ValueError, match="rests on"):
        applied_operation(
            held,
            _operation(MemoryOperationKind.RAISE_QUESTION, first, question="q-1"),
            question=question,
        )


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
