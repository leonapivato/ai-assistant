"""ADR-0358 §11: what each call showed, on its entry, and the full view's keyword.

The types are ``core``'s, so these hold their validators, the record's extension rule and
the projection on values alone: ``ShownRecord``, ``ShownText``, ``CallShowed``,
``RecordedCall.showed``, ``project_episode``'s ``full_view`` and the parts it carries,
``ProjectedUnderstanding``, ``ProjectedRecall`` and ``ProjectedProposal``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

import pytest
from pydantic import ValidationError
from test_planning_round_types import _LATER, _NOW, _call, _episode, _open, _round

from ai_assistant.core.episode_encoding import episode_extends, project_episode
from ai_assistant.core.types import (
    ActivationDigest,
    ActivationRecall,
    ActivationUnderstanding,
    BeliefBand,
    CallOutcomeKind,
    CallShowed,
    ControllerRule,
    ControllerStage,
    DigestOutcome,
    EpisodeProcessingRecord,
    EpisodeProjection,
    EvidenceItem,
    MemoryKind,
    ProcessingReason,
    ProcessingStatus,
    ProjectedCall,
    ProjectedRecall,
    ProjectedText,
    ProjectedUnderstanding,
    RecallCue,
    RecalledItem,
    RecallOutcome,
    RecallProvenance,
    RecordedCall,
    ShownRecord,
    ShownRecordKind,
    ShownText,
    StageEntry,
    StageOutcome,
    UnclearPoint,
    UnderstandingProducer,
)

_SHOWED: Final = CallShowed(
    parts=(
        ShownText(text="Two memories match:"),
        ShownRecord(kind=ShownRecordKind.MEMORY, id=" mem-dentist "),
        ShownRecord(kind=ShownRecordKind.STORY, id="story-teeth", summary_version=3),
        ShownRecord(kind=ShownRecordKind.EPISODE, id="activation:earlier"),
    ),
    cut=True,
)


def _entry(round_id: str = "r1", call_id: str = "c1", **fields: object) -> RecordedCall:
    values: dict[str, object] = {
        "round": round_id,
        "call_id": call_id,
        "capability": "search_memory",
        "effect": False,
        "outcome": CallOutcomeKind.DONE,
        "recorded_at": _NOW,
    }
    values.update(fields)
    return RecordedCall.model_validate(values)


# --- what a call showed (§11:2-§11:4) -------------------------------------------------


def test_a_done_call_keeps_what_its_result_showed_by_reference() -> None:
    """§11:2: each record by its kind and id, a story also by its summary version."""
    entry = _entry(showed=_SHOWED)
    assert entry.showed == _SHOWED
    assert RecordedCall.model_validate_json(entry.model_dump_json()) == entry
    dumped = entry.model_dump(mode="json")["showed"]
    assert dumped["parts"][1] == {
        "shown": "record",
        "kind": "memory",
        "id": " mem-dentist ",
        "summary_version": None,
    }
    assert dumped["cut"] is True


@pytest.mark.parametrize(
    "outcome",
    [
        None,
        CallOutcomeKind.NOT_DONE,
        CallOutcomeKind.UNKNOWN,
        CallOutcomeKind.NEEDS_YOU,
        CallOutcomeKind.REFUSED,
    ],
)
def test_only_a_call_that_was_done_keeps_what_it_showed(outcome: CallOutcomeKind | None) -> None:
    """§11:2: for a call that was done."""
    with pytest.raises(ValidationError, match="only a call that was done"):
        _entry(outcome=outcome, reason=None, showed=CallShowed())


@pytest.mark.parametrize("kind", [ShownRecordKind.MEMORY, ShownRecordKind.EPISODE])
def test_only_a_story_is_held_by_a_summary_version(kind: ShownRecordKind) -> None:
    ShownRecord(kind=ShownRecordKind.STORY, id="story-new")
    with pytest.raises(ValidationError, match="only a story"):
        ShownRecord(kind=kind, id="record", summary_version=1)


def test_a_part_of_the_result_is_text_or_a_record_and_text_is_never_blank() -> None:
    showed = CallShowed.model_validate(
        {
            "parts": [
                {"shown": "text", "text": "Done."},
                {"shown": "record", "kind": "episode", "id": "e"},
            ]
        }
    )
    assert [type(one) for one in showed.parts] == [ShownText, ShownRecord]
    with pytest.raises(ValidationError):
        ShownText(text="  ")
    with pytest.raises(ValidationError):
        CallShowed.model_validate({"parts": [{"shown": "copy", "text": "the memory's words"}]})


def test_a_result_that_showed_only_what_it_held_for_a_digest_keeps_no_part() -> None:
    """§11:3: of outside text held for a digest, the entry holds nothing; an empty
    addition is not one that was never kept."""
    entry = _entry(showed=CallShowed())
    assert entry.showed is not None
    assert entry.showed.parts == ()


def test_the_record_kinds_are_the_ones_the_full_view_reads_again() -> None:
    """§10:6: a memory, a story or another episode."""
    assert [one.value for one in ShownRecordKind] == ["memory", "episode", "story"]


# --- what was stored before (§11:6) ---------------------------------------------------


def test_an_entry_written_before_the_addition_validates_unchanged() -> None:
    """§11:6: an entry stored without ``showed``, in a record at version 12, reads back
    keeping nothing of what its call showed."""
    stored = _entry().model_dump(mode="json")
    del stored["showed"]
    entry = RecordedCall.model_validate(stored)
    assert entry.showed is None
    record = _open(rounds=(_round("r1", calls=(_call("c1", "search_memory"),)),)).model_dump(
        mode="json"
    )
    record["call_records"] = [stored]
    assert record["schema_version"] == 12
    assert EpisodeProcessingRecord.model_validate(record).call_records == (entry,)


def test_an_open_episode_takes_an_entry_with_what_it_showed_appended() -> None:
    """ADR-0356 §8:6: an entry with the addition is appended as any is, and never
    changed after."""
    rounds = (_round("r1", calls=(_call("c1", "search_memory"), _call("c2", "search_memory"))),)
    first = _open(rounds=rounds, call_records=(_entry(showed=_SHOWED),))
    appended = first.model_copy(
        update={"call_records": (_entry(showed=_SHOWED), _entry("r1", "c2", showed=CallShowed()))}
    )
    assert episode_extends(_episode(first), _episode(appended))
    rewritten = first.model_copy(update={"call_records": (_entry(showed=CallShowed()),)})
    assert not episode_extends(_episode(first), _episode(rewritten))


# --- the full view (§11:5, §10:3) -----------------------------------------------------


def _item(kind: MemoryKind, id_: str) -> RecalledItem:
    return RecalledItem(
        kind=kind,
        id=id_,
        excerpt="the words the run kept",
        provenance=RecallProvenance.USER,
        standing=BeliefBand.ASSERTED,
        rests_on_recorded_external_content=False,
        found_by=(RecallCue.ACTIVATION_INPUT,),
    )


def _version(
    version: int, meaning: str, at: timedelta, **fields: object
) -> ActivationUnderstanding:
    return ActivationUnderstanding.model_validate(
        {
            "version": version,
            "recorded_at": _NOW + at,
            "producer": UnderstandingProducer.INTERPRETATION,
            "meaning": meaning,
            **fields,
        }
    )


def _full_record() -> EpisodeProcessingRecord:
    """Two understanding versions, both recall runs, a pre-entry call and two entries."""
    rounds = (
        _round(
            "r1",
            notes="looking",
            calls=(_call("c1", "search_memory"), _call("c2")),
            recorded_at=_NOW + timedelta(seconds=2),
        ),
        _round(
            "r2",
            follows="r1",
            notes="done",
            calls=(_call("c3", "read_story"),),
            recorded_at=_NOW + timedelta(seconds=6),
        ),
    )
    opened = _open(
        rounds=rounds,
        understanding=(
            _version(1, "book the dentist", timedelta(seconds=1)),
            _version(
                2,
                "book the dentist on Thursday",
                timedelta(seconds=4),
                unclear=(UnclearPoint(gap="which week", readings=("this", "next")),),
            ),
        ),
        recall=ActivationRecall(
            outcome=RecallOutcome.FOUND,
            cues=(RecallCue.ACTIVATION_INPUT,),
            items=(_item(MemoryKind.MEMORY, " mem-dentist "), _item(MemoryKind.SEMANTIC, "fact")),
        ),
        recall_second_run=ActivationRecall(
            outcome=RecallOutcome.FOUND,
            cues=(RecallCue.UNDERSTOOD_MEANING,),
            items=(_item(MemoryKind.EPISODIC, "activation:earlier"),),
        ),
        call_records=(
            _entry("r1", "c1", showed=_SHOWED),
            _entry("r2", "c3", capability="read_story"),
        ),
    )
    end = StageEntry(
        stage=ControllerStage.END,
        due=ControllerRule.NOTHING_DUE,
        started_at=_LATER,
        ended_at=_LATER,
        outcome=StageOutcome.DONE,
    )
    return EpisodeProcessingRecord.model_validate(
        {
            **dict(opened),
            "status": ProcessingStatus.COMPLETED,
            "reason": ProcessingReason.RETURNED,
            "ended_at": _LATER,
            "stages": (end,),
        }
    )


def test_the_full_view_carries_what_each_call_showed() -> None:
    """§11:5: each ``ProjectedCall`` with what its entry showed, and ``None`` where the
    entry keeps none, which the full view reads as no longer kept (§11:6)."""
    projection = project_episode(
        _episode(_full_record()), excerpt_chars=50, owner_records=True, full_view=True
    )
    assert projection.full_view
    searched, read = projection.calls
    assert searched.showed == _SHOWED
    assert (read.capability, read.showed) == ("read_story", None)


def test_the_full_view_carries_each_understanding_version_in_its_place() -> None:
    """§10:3: each version of understanding the record holds, placed among the rounds."""
    projection = project_episode(
        _episode(_full_record()), excerpt_chars=50, owner_records=True, full_view=True
    )
    assert projection.understood == (
        ProjectedUnderstanding(position=0, version=1, meaning="book the dentist"),
        ProjectedUnderstanding(
            position=1,
            version=2,
            meaning="book the dentist on Thursday",
            unclear=(UnclearPoint(gap="which week", readings=("this", "next")),),
        ),
    )
    # The latest is still the projection's meaning, as every view has it.
    assert projection.meaning == "book the dentist on Thursday"


def test_the_full_view_says_how_many_versions_were_elided_when_recorded() -> None:
    """§10:9: a version the record elided when it recorded it is no longer kept."""
    record = _full_record().model_copy(update={"understanding_elided": 2})
    full = project_episode(_episode(record), excerpt_chars=50, owner_records=True, full_view=True)
    assert full.understood_elided == 2
    plain = project_episode(_episode(record), excerpt_chars=50, owner_records=True)
    assert plain.understood_elided == 0


def test_the_full_view_carries_what_both_recall_runs_found_by_reference_alone() -> None:
    """§10:3, §10:6: what both runs found, each record by kind and id, never the excerpt
    the run kept, so a reader reads it again as it is now held."""
    projection = project_episode(
        _episode(_full_record()), excerpt_chars=50, owner_records=True, full_view=True
    )
    assert projection.recalled == (
        ProjectedRecall(
            outcome=RecallOutcome.FOUND,
            found=(
                ShownRecord(kind=ShownRecordKind.MEMORY, id=" mem-dentist "),
                ShownRecord(kind=ShownRecordKind.MEMORY, id="fact"),
            ),
        ),
        ProjectedRecall(
            second=True,
            outcome=RecallOutcome.FOUND,
            found=(ShownRecord(kind=ShownRecordKind.EPISODE, id="activation:earlier"),),
        ),
    )
    assert "the words the run kept" not in projection.model_dump_json()


def test_the_full_view_carries_a_call_its_record_holds_no_entry_for() -> None:
    """§10:3, §10:9: a round's call with its arguments, where the record keeps nothing of
    what came of it."""
    projection = project_episode(
        _episode(_full_record()), excerpt_chars=8, owner_records=True, full_view=True
    )
    (proposal,) = projection.unrecorded
    assert (proposal.position, proposal.capability) == (0, "web_search")
    assert proposal.arguments == ProjectedText(text='{"query"', full_chars=14)


def test_without_owner_records_the_full_view_adds_nothing() -> None:
    """§10:5: on a pass that may not be shown owner-only records, the full view shows the
    input, the meaning and how the work ended, and nothing of its notes or its calls."""
    full = project_episode(_episode(_full_record()), excerpt_chars=50, full_view=True)
    plain = project_episode(_episode(_full_record()), excerpt_chars=50)
    assert full.full_view
    assert full.model_copy(update={"full_view": False}) == plain
    assert (full.calls, full.understood, full.recalled, full.unrecorded) == ((), (), (), ())
    assert full.understood_elided == 0
    assert full.meaning == "book the dentist on Thursday"


def test_every_other_view_carries_none_of_the_full_views_parts() -> None:
    """§11:5: false by default, so every reader but the look-up is shown what it was."""
    projection = project_episode(_episode(_full_record()), excerpt_chars=50, owner_records=True)
    assert not projection.full_view
    assert all(call.showed is None for call in projection.calls)
    assert (projection.understood, projection.recalled, projection.unrecorded) == ((), (), ())


def test_an_episode_recorded_before_any_entry_shows_its_calls_in_the_full_view() -> None:
    """§10:9: an episode recorded before ADR-0356's entries keeps its calls' arguments,
    and nothing of what came of them."""
    record = _full_record().model_copy(update={"call_records": ()})
    projection = project_episode(
        _episode(record), excerpt_chars=50, owner_records=True, full_view=True
    )
    assert projection.calls == ()
    assert [(one.position, one.capability) for one in projection.unrecorded] == [
        (0, "search_memory"),
        (0, "web_search"),
        (1, "read_story"),
    ]


def test_the_peer_view_is_never_a_full_view() -> None:
    """The peer view's overload takes no ``full_view``, and a caller past the type is
    refused at run time."""
    with pytest.raises(ValueError, match="never a peer view"):
        project_episode(  # type: ignore[call-overload]  # the refusal, driven past the type
            _episode(_full_record()), excerpt_chars=50, effects=(), full_view=True
        )


def test_a_projection_carries_the_full_views_parts_only_in_it() -> None:
    """The type refuses a part only the full view carries on any other projection."""
    projection = project_episode(
        _episode(_full_record()), excerpt_chars=50, owner_records=True, full_view=True
    )
    data = projection.model_dump()
    data["full_view"] = False
    with pytest.raises(ValidationError, match="only the full view"):
        EpisodeProjection.model_validate(data)
    shown = ProjectedCall(
        position=0,
        capability="search_memory",
        arguments=ProjectedText(text="{}", full_chars=2),
        effect=False,
        outcome=CallOutcomeKind.DONE,
        showed=CallShowed(),
    )
    plain = project_episode(_episode(_full_record()), excerpt_chars=50, owner_records=True)
    with pytest.raises(ValidationError, match="only the full view"):
        EpisodeProjection.model_validate(plain.model_dump() | {"calls": (shown,)})


# --- the order things happened in (§10:3) ---------------------------------------------


def _digest(result: str | None, at: timedelta, text: str) -> ActivationDigest:
    return ActivationDigest(
        result=result,
        question="what does it say?",
        outcome=DigestOutcome.ANSWERED,
        evidence=(EvidenceItem(text=text, source="R1"),),
        recorded_at=_NOW + at,
    )


def _ordered(at: timedelta) -> EpisodeProcessingRecord:
    """Rounds at ``at`` and ``2 * at`` after the start, with recall's digest before them
    and a result's digest between and after them, every part at a multiple of ``at``."""
    record = _full_record().model_copy(
        update={
            "rounds": (
                _round(
                    "r1",
                    notes="looking",
                    calls=(_call("c1", "search_memory"), _call("c2")),
                    recorded_at=_NOW + at,
                ),
                _round(
                    "r2",
                    follows="r1",
                    notes="done",
                    calls=(_call("c3", "read_story"),),
                    recorded_at=_NOW + 2 * at,
                ),
            ),
            "understanding": (
                _version(1, "book the dentist", at),
                _version(2, "book the dentist on Thursday", 2 * at),
            ),
            "digests": (
                _digest(None, timedelta(0), "recalled"),
                _digest("R1", at, "between"),
                _digest("R2", 3 * at, "after"),
            ),
        }
    )
    return EpisodeProcessingRecord.model_validate(record.model_dump())


def test_evidence_is_placed_before_between_and_after_the_rounds() -> None:
    """§10:3: in the order they happened, so a digest moved past a round moves with it."""
    projection = project_episode(
        _episode(_ordered(timedelta(seconds=2))),
        excerpt_chars=50,
        owner_records=True,
        full_view=True,
    )
    assert [(one.text.text, one.position) for one in projection.evidence] == [
        ("recalled", 0),
        ("between", 1),
        ("after", 2),
    ]


def test_a_fixed_clock_still_places_what_the_phases_order() -> None:
    """§10:3 with every part at one instant: the first understanding version and recall's
    digest precede every round by the phases' order, a later version precedes the round
    that plans on it, and a result's digest follows the rounds that could have read it."""
    projection = project_episode(
        _episode(_ordered(timedelta(0))), excerpt_chars=50, owner_records=True, full_view=True
    )
    assert [one.position for one in projection.understood] == [0, 0]
    assert [(one.text.text, one.position) for one in projection.evidence] == [
        ("recalled", 0),
        ("between", 2),
        ("after", 2),
    ]
