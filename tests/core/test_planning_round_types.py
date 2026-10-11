"""ADR-0307 §10's types: a planning round, its labels, and the episode that keeps them.

The round's request and response shapes (``OfferedTool``, ``ProposedCall``,
``RoundResponse``), what the episode records (``PlanningRound``, ``PlanningLabel``,
``LabelKind``, ``EpisodeProcessingRecord.rounds`` and ``labels``), the appends
``episode_extends`` admits for them, and what ``project_episode`` renders of them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ai_assistant.core.episode_encoding import episode_extends, project_episode
from ai_assistant.core.types import (
    ChannelContext,
    ControllerRule,
    ControllerStage,
    EpisodeProcessingRecord,
    EpisodicMemory,
    InputOrigin,
    LabelKind,
    MemorySource,
    NewConversation,
    OfferedTool,
    Placement,
    PlacementReach,
    PlacementSetter,
    PlanningLabel,
    PlanningRound,
    ProcessingReason,
    ProcessingStatus,
    ProjectedRound,
    ProjectedText,
    ProposedCall,
    Provenance,
    RecordedChannelTrigger,
    RecordedTextInput,
    RoundResponse,
    StageEntry,
    StageOutcome,
    UnderstandingOmission,
    WholeTextReply,
    label_prefix,
)

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_LATER = _NOW + timedelta(seconds=30)
_OWNER_ONLY = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=_NOW)


def _call(call_id: str = "c1", name: str = "web_search") -> ProposedCall:
    return ProposedCall(call_id=call_id, name=name, arguments={"query": "q"})


def _round(round_id: str = "r1", *, follows: str | None = None, **fields: object) -> PlanningRound:
    return PlanningRound.model_validate(
        {"id": round_id, "follows": follows, "recorded_at": _NOW, **fields}
    )


def _label(label: str, kind: LabelKind, id_: str) -> PlanningLabel:
    return PlanningLabel(label=label, kind=kind, id=id_)


def _open(**fields: object) -> EpisodeProcessingRecord:
    values: dict[str, object] = {
        "activation_id": "activation",
        "started_at": _NOW,
        "trigger": RecordedChannelTrigger(
            target=NewConversation(),
            channel=None,
            payload=RecordedTextInput(text="what is on today?"),
            context=ChannelContext(),
            reply=WholeTextReply(),
            origin=InputOrigin.USER,
        ),
    }
    values.update(fields)
    return EpisodeProcessingRecord.model_validate(values)


def _frozen(record: EpisodeProcessingRecord) -> EpisodeProcessingRecord:
    end = StageEntry(
        stage=ControllerStage.END,
        due=ControllerRule.NOTHING_DUE,
        started_at=_LATER,
        ended_at=_LATER,
        outcome=StageOutcome.DONE,
    )
    return EpisodeProcessingRecord.model_validate(
        {
            **dict(record),
            "status": ProcessingStatus.COMPLETED,
            "reason": ProcessingReason.RETURNED,
            "ended_at": _LATER,
            "stages": (*record.stages, end),
            "understanding_omitted": UnderstandingOmission.NOT_REACHED,
        }
    )


def _episode(record: EpisodeProcessingRecord, *, outcome: str | None = None) -> EpisodicMemory:
    return EpisodicMemory(
        id="activation:activation",
        content="",
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_NOW),
        occurred_at=_NOW,
        outcome=outcome,
        processing_record=record,
        placement=_OWNER_ONLY,
    )


# --- the round's request and response -----------------------------------------------


def test_an_offered_tool_takes_an_object_schema() -> None:
    tool = OfferedTool(name="web_search", description="Search.", parameters={"type": "object"})
    assert tool.parameters["type"] == "object"
    with pytest.raises(ValidationError, match="JSON schema of an object"):
        OfferedTool(name="web_search", description="Search.", parameters={"type": "string"})


def test_a_proposed_calls_arguments_are_frozen_json() -> None:
    call = ProposedCall(call_id="c1", name="web_search", arguments={"tags": ["a", "b"]})
    assert call.arguments["tags"] == ("a", "b")
    with pytest.raises(TypeError):
        call.arguments["tags"] = ()  # type: ignore[index]  # the point: it is frozen


def test_a_round_response_defaults_to_no_text_calls_notes_or_mark() -> None:
    assert RoundResponse() == RoundResponse(text="", calls=(), notes=None, another_round=False)


def test_a_round_response_refuses_two_calls_under_one_id() -> None:
    with pytest.raises(ValidationError, match="distinct call ids"):
        RoundResponse(calls=(_call("same"), _call("same", "remember")))


def test_blank_notes_are_refused_so_none_means_none_written() -> None:
    with pytest.raises(ValidationError):
        RoundResponse(notes="   ")


# --- labels -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "prefix"),
    [
        (LabelKind.STORY, "S"),
        (LabelKind.EPISODE, "E"),
        (LabelKind.NOTE, "N"),
        (LabelKind.MEMORY, "M"),
        (LabelKind.RESULT, "R"),
    ],
)
def test_each_kind_has_its_prefix(kind: LabelKind, prefix: str) -> None:
    assert label_prefix(kind) == prefix
    assert _label(f"{prefix}12", kind, "x").label == f"{prefix}12"


@pytest.mark.parametrize("label", ["S0", "S01", "s1", "S", "S1 ", "X1", "S1a", "S1234567890"])
def test_a_malformed_label_is_refused(label: str) -> None:
    with pytest.raises(ValidationError, match="prefix and a number"):
        _label(label, LabelKind.STORY, "story:1")


def test_a_label_carries_its_kinds_prefix() -> None:
    with pytest.raises(ValidationError, match="its kind's prefix"):
        _label("E1", LabelKind.STORY, "story:1")


def test_a_labels_id_is_kept_exactly_as_held() -> None:
    assert _label("M1", LabelKind.MEMORY, " spaced ").id == " spaced "


# --- a recorded round ---------------------------------------------------------------


def test_a_round_keeps_its_four_parts_and_its_mark() -> None:
    one = _round(text="On it.", calls=(_call(),), notes="n", another_round=True, notes_marked=True)
    assert (one.text, one.notes, one.another_round, one.notes_marked) == ("On it.", "n", True, True)
    assert one.calls == (_call(),)


def test_a_round_marks_only_notes_it_carries() -> None:
    with pytest.raises(ValidationError, match="only a round carrying notes"):
        _round(notes_marked=True)


def test_a_round_never_follows_itself() -> None:
    with pytest.raises(ValidationError, match="never itself"):
        _round("r1", follows="r1")


def test_a_round_refuses_two_calls_under_one_id() -> None:
    with pytest.raises(ValidationError, match="distinct call ids"):
        _round(calls=(_call("same"), _call("same")))


# --- the episode record -------------------------------------------------------------


def test_the_record_defaults_to_no_rounds_and_no_labels() -> None:
    record = _open()
    assert (record.rounds, record.labels) == ((), ())


def test_each_round_follows_the_one_before_it() -> None:
    record = _open(rounds=(_round("r1"), _round("r2", follows="r1"), _round("r3", follows="r2")))
    assert [one.id for one in record.rounds] == ["r1", "r2", "r3"]


@pytest.mark.parametrize(
    "rounds",
    [
        pytest.param((_round("r1", follows="r0"),), id="first-follows-something"),
        pytest.param((_round("r1"), _round("r2")), id="second-follows-nothing"),
        pytest.param(
            (_round("r1"), _round("r2", follows="r1"), _round("r3", follows="r1")),
            id="skips-one",
        ),
        pytest.param(
            (_round("r1"), _round("r2", follows="r1"), _round("r1", follows="r2")),
            id="repeats-an-id",
        ),
    ],
)
def test_rounds_out_of_order_are_refused(rounds: tuple[PlanningRound, ...]) -> None:
    with pytest.raises(ValidationError):
        _open(rounds=rounds)


def test_a_label_names_one_thing_and_a_thing_takes_one_label() -> None:
    with pytest.raises(ValidationError, match="a label names one thing"):
        _open(
            labels=(
                _label("S1", LabelKind.STORY, "story:a"),
                _label("S1", LabelKind.STORY, "story:b"),
            )
        )
    with pytest.raises(ValidationError, match="a thing takes one label"):
        _open(
            labels=(
                _label("S1", LabelKind.STORY, "story:a"),
                _label("S2", LabelKind.STORY, "story:a"),
            )
        )


def test_one_id_may_be_two_kinds_of_thing() -> None:
    record = _open(
        labels=(_label("E1", LabelKind.EPISODE, "x"), _label("M1", LabelKind.MEMORY, "x"))
    )
    assert len(record.labels) == 2


def test_a_record_with_rounds_and_labels_round_trips() -> None:
    record = _open(
        rounds=(_round("r1", text="hi", calls=(_call(),), notes="n", notes_marked=True),),
        labels=(_label("R1", LabelKind.RESULT, "result:r1:c1"),),
    )
    assert EpisodeProcessingRecord.model_validate_json(record.model_dump_json()) == record


# --- episode_extends ------------------------------------------------------------------


def _extends(before: EpisodeProcessingRecord, after: EpisodeProcessingRecord) -> bool:
    return episode_extends(_episode(before), _episode(after))


def test_a_round_appended_extends() -> None:
    stored = _open(rounds=(_round("r1"),))
    assert _extends(stored, _open(rounds=(_round("r1"), _round("r2", follows="r1"))))


def test_labels_appended_extend() -> None:
    first = _label("S1", LabelKind.STORY, "story:a")
    stored = _open(labels=(first,))
    assert _extends(stored, _open(labels=(first, _label("E1", LabelKind.EPISODE, "e"))))


def test_a_round_and_its_labels_appended_together_extend() -> None:
    assert _extends(
        _open(),
        _open(rounds=(_round("r1"),), labels=(_label("S1", LabelKind.STORY, "story:a"),)),
    )


def test_the_freezing_revision_keeps_the_rounds() -> None:
    stored = _open(rounds=(_round("r1"),))
    assert _extends(stored, _frozen(stored))


def test_a_recorded_round_is_never_edited() -> None:
    stored = _open(rounds=(_round("r1", text="first"),))
    assert not _extends(stored, _open(rounds=(_round("r1", text="edited"),)))


def test_a_recorded_round_is_never_dropped() -> None:
    stored = _open(rounds=(_round("r1"), _round("r2", follows="r1")))
    assert not _extends(stored, _open(rounds=(_round("r1"),)))


def test_a_recorded_label_never_changes_what_it_names() -> None:
    stored = _open(labels=(_label("S1", LabelKind.STORY, "story:a"),))
    assert not _extends(stored, _open(labels=(_label("S1", LabelKind.STORY, "story:b"),)))


def test_a_label_is_never_inserted_ahead_of_one_recorded() -> None:
    later = _label("S2", LabelKind.STORY, "story:b")
    stored = _open(labels=(later,))
    assert not _extends(stored, _open(labels=(_label("S1", LabelKind.STORY, "story:a"), later)))


# --- project_episode -----------------------------------------------------------------


def _projected_rounds(*, owner_records: bool) -> tuple[ProjectedRound, ...]:
    record = _frozen(
        _open(
            rounds=(
                _round("r1", text="Looking.", notes="checking", notes_marked=True),
                _round("r2", follows="r1", notes="nothing yet"),
                _round("r3", follows="r2", text="   "),
                _round("r4", follows="r3", text="Done."),
            )
        )
    )
    return project_episode(
        _episode(record, outcome="Looking.\n\nDone."), excerpt_chars=5, owner_records=owner_records
    ).rounds


def test_an_owner_reader_is_shown_each_rounds_message_and_notes() -> None:
    assert _projected_rounds(owner_records=True) == (
        ProjectedRound(
            message=ProjectedText(text="Looki", full_chars=8),
            notes=ProjectedText(text="check", full_chars=8),
            notes_marked=True,
        ),
        ProjectedRound(notes=ProjectedText(text="nothi", full_chars=11)),
        ProjectedRound(message=ProjectedText(text="Done.", full_chars=5)),
    )


def test_another_reader_is_shown_the_messages_and_no_notes() -> None:
    assert _projected_rounds(owner_records=False) == (
        ProjectedRound(message=ProjectedText(text="Looki", full_chars=8)),
        ProjectedRound(message=ProjectedText(text="Done.", full_chars=5)),
    )


def test_the_default_reader_keeps_the_owner_only_placement() -> None:
    record = _frozen(_open(rounds=(_round("r1", notes="private"),)))
    assert project_episode(_episode(record), excerpt_chars=50).rounds == ()


def test_a_projected_round_shows_something() -> None:
    with pytest.raises(ValidationError, match="its message, its notes or both"):
        ProjectedRound()
    with pytest.raises(ValidationError, match="marks only notes it carries"):
        ProjectedRound(message=ProjectedText(text="m", full_chars=1), notes_marked=True)
