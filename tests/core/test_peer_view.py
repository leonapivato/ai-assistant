"""ADR-0349 §6:7-§6:10: the peer view, the one read function's second view.

``project_episode`` handed an activation's effect records returns another activation's
own work: computed from its episode as stored, open or frozen, and those records alone
(§6:8); showing its input withheld where it is not the user's own, its latest meaning,
its rounds' notes and its evidence with their marks, and its effects done or unknown
(§6:9); and never a round's message but through a message effect, a failed call, a
call's values, recall or story links (§6:10).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from ai_assistant.core.episode_encoding import project_episode
from ai_assistant.core.types import (
    PEER_COULDNT_FINISH_LINE,
    ActivationDigest,
    ActivationEffect,
    ActivationUnderstanding,
    ChannelContext,
    ChannelIdentity,
    ControllerRule,
    ControllerStage,
    DigestOutcome,
    EpisodeProcessingRecord,
    EpisodeProjection,
    EpisodicMemory,
    EvidenceItem,
    JoinedInput,
    MemorySource,
    PeerEffect,
    PeerNotes,
    PeerView,
    Placement,
    PlacementReach,
    PlacementSetter,
    PlanningRound,
    ProcessingReason,
    ProcessingStatus,
    ProjectedEvidence,
    ProjectedText,
    Provenance,
    RecordedChannelTrigger,
    RecordedInputMessage,
    RecordedTextInput,
    StageEntry,
    StageOutcome,
    SupportHolder,
    ToolOutcome,
    UnderstandingProducer,
    UnderstandingReferent,
    WholeTextReply,
    parties_are_outside,
    parties_are_persons_own,
)
from ai_assistant.testing.parties import ASSISTANTS_WORDS, OWNERS_WORDS, UNIDENTIFIED_WORDS

_NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
_LATER = _NOW + timedelta(seconds=30)
_PLACE = ChannelIdentity(channel_type="conversation", instance_id="c-1")
_EVENTS = ChannelIdentity(channel_type="informational_event", instance_id="calendar")
_OWNER_ONLY = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=_NOW)
_ACTIVATION = "act-search"


def _trigger(parties: tuple[SupportHolder, ...] = OWNERS_WORDS, text: str = "find flights") -> Any:
    own = parties_are_persons_own(parties)
    channel = _PLACE if own else _EVENTS
    return RecordedChannelTrigger(
        target=channel,
        channel=channel,
        payload=RecordedTextInput(text=text),
        context=ChannelContext(),
        reply=WholeTextReply() if own else None,
        parties=parties,
    )


def _understanding(version: int, meaning: str) -> ActivationUnderstanding:
    return ActivationUnderstanding(
        version=version,
        recorded_at=_NOW,
        producer=UnderstandingProducer.INTERPRETATION,
        meaning=meaning,
    )


def _round(index: int, text: str = "", *, notes: str | None = None, marked: bool = False) -> Any:
    return PlanningRound(
        id=f"r{index}",
        follows=None if index == 1 else f"r{index - 1}",
        recorded_at=_NOW,
        text=text,
        notes=notes,
        notes_marked=marked,
    )


def _stage(stage: ControllerStage, due: ControllerRule) -> StageEntry:
    return StageEntry(
        stage=stage, due=due, started_at=_NOW, ended_at=_NOW, outcome=StageOutcome.DONE
    )


def _record(*, frozen: bool = False, **fields: Any) -> EpisodeProcessingRecord:
    values: dict[str, Any] = {
        "activation_id": _ACTIVATION,
        "started_at": _NOW,
        "trigger": _trigger(),
        "understanding": (_understanding(1, "find flights to Lisbon"),),
        "stages": (_stage(ControllerStage.UNDERSTANDING, ControllerRule.NOT_UNDERSTOOD),),
    }
    values.update(fields)
    if frozen:
        values |= {
            "status": ProcessingStatus.COMPLETED,
            "reason": ProcessingReason.RETURNED,
            "ended_at": _LATER,
            "stages": (
                *values["stages"],
                _stage(ControllerStage.END, ControllerRule.NOTHING_DUE),
            ),
        }
    return EpisodeProcessingRecord.model_validate(values)


def _episode(record: EpisodeProcessingRecord, *, external: bool = False) -> EpisodicMemory:
    is_open = record.is_open
    return EpisodicMemory(
        id=f"activation:{record.activation_id}",
        content="" if is_open else "find flights to Lisbon",
        provenance=Provenance(
            source=MemorySource.OBSERVED,
            confidence=0.5,
            last_updated=_NOW,
            derived_from_external=external,
        ),
        occurred_at=_NOW,
        placement=_OWNER_ONLY,
        processing_record=record,
    )


def _call(id_: str, outcome: ToolOutcome | None, *, round_: str = "r1", **extra: Any) -> Any:
    return ActivationEffect(
        id=id_,
        activation_id=_ACTIVATION,
        round=round_,
        capability="search_flights",
        values_digest="a" * 64,
        decision_id=f"d-{id_}",
        claimed_at=_NOW,
        outcome=outcome,
        reason="the airline refused" if outcome is ToolOutcome.FAILED else None,
        **extra,
    )


def _message(id_: str, outcome: ToolOutcome | None, *, round_: str | None = "r1") -> Any:
    return ActivationEffect(
        id=id_,
        activation_id=_ACTIVATION,
        round=round_,
        place="c-1",
        claimed_at=_NOW,
        outcome=outcome,
        position=3 if outcome is ToolOutcome.SUCCEEDED else None,
        reason="the place refused" if outcome is ToolOutcome.FAILED else None,
    )


def _peer(episode: EpisodicMemory, effects: Any = (), **fields: Any) -> PeerView:
    return project_episode(
        episode, excerpt_chars=fields.pop("bound", 200), effects=effects, **fields
    )


# --- §6:8: computed from the episode as stored, open or frozen ---------------------


def test_an_open_episode_is_read_and_says_it_runs() -> None:
    view = _peer(_episode(_record()))

    assert isinstance(view, PeerView)
    assert (view.status, view.reason) == (None, None)
    assert view.channel == _PLACE
    assert view.parties == OWNERS_WORDS
    assert not view.relayed


def test_a_frozen_episode_says_how_it_ended() -> None:
    """§6:6, §4:10: a reader says that it has ended."""
    view = _peer(_episode(_record(frozen=True)))

    assert (view.status, view.reason) == (ProcessingStatus.COMPLETED, ProcessingReason.RETURNED)


def test_the_projection_still_refuses_an_open_episode() -> None:
    """ADR-0286 §6:4 stands for every reader but a share's."""
    with pytest.raises(ValueError, match="never a model input"):
        project_episode(_episode(_record()), excerpt_chars=200)
    assert isinstance(
        project_episode(_episode(_record(frozen=True)), excerpt_chars=200), EpisodeProjection
    )


# --- §6:9: what it took in -------------------------------------------------------------


def _joined(*parties: SupportHolder | None, relayed: bool = False) -> tuple[JoinedInput, ...]:
    """One joined input of two messages, each of the party given, or the owner's."""
    first, second = (*parties, *OWNERS_WORDS * 2)[:2]
    return (
        JoinedInput(
            joined_at=_NOW,
            channel=_PLACE,
            messages=(
                RecordedInputMessage(text="only direct", sent_at=_NOW, party=first),
                RecordedInputMessage(text="under 400", sent_at=_NOW, party=second),
            ),
            taken_over_from="act-older",
            relayed=relayed,
        ),
    )


def test_the_users_input_and_every_input_it_holds_are_shown_cut() -> None:
    joined = _joined()
    view = _peer(_episode(_record(joined=joined)), bound=8)

    assert view.input == ProjectedText(text="find fli", full_chars=12)
    assert view.joined == (ProjectedText(text="only dir", full_chars=22),)
    assert view.parties == OWNERS_WORDS
    assert _peer(_episode(_record(joined=joined))).joined[0].text == "only direct\n\nunder 400"


@pytest.mark.parametrize(
    ("joined", "parties"),
    [
        pytest.param(_joined(None, None), None, id="unknown"),
        pytest.param(
            _joined(SupportHolder.unknown(), SupportHolder.unknown()),
            (*OWNERS_WORDS, SupportHolder.unknown()),
            id="outside",
        ),
        pytest.param(_joined(relayed=True), OWNERS_WORDS, id="relayed"),
    ],
)
def test_input_is_withheld_where_any_input_it_holds_is_not_the_users_own(
    joined: tuple[JoinedInput, ...], parties: tuple[SupportHolder, ...] | None
) -> None:
    """ADR-0351 §8:5: read over every input it holds, each with its parties and its mark."""
    view = _peer(_episode(_record(joined=joined)))

    assert view.parties == parties
    assert view.input is None
    assert view.joined == ()
    assert parties_are_outside(view.parties, relayed=view.relayed)


@pytest.mark.parametrize("parties", [UNIDENTIFIED_WORDS, ASSISTANTS_WORDS])
def test_input_that_is_not_the_users_own_is_withheld(parties: tuple[SupportHolder, ...]) -> None:
    """§6:9: as ``project_episode`` renders it with ``admit_outside_input`` false."""
    view = _peer(_episode(_record(trigger=_trigger(parties, "a report from outside"))))

    assert view.parties == parties
    assert view.input is None
    assert view.joined == ()


def test_outside_input_is_never_admitted_to_a_peer_view() -> None:
    with pytest.raises(ValueError, match="admits no outside input"):
        project_episode(
            _episode(_record()), excerpt_chars=200, effects=(), admit_outside_input=True
        )  # type: ignore[call-overload]  # the overload refuses it too: asserted at run time
    with pytest.raises(ValueError, match="carries no candidate"):
        project_episode(_episode(_record()), excerpt_chars=200, effects=(), candidates=("x",))  # type: ignore[call-overload]  # the overload refuses it too: asserted at run time


# --- §6:9: what it is doing --------------------------------------------------------------


def test_the_latest_meaning_is_shown() -> None:
    record = _record(
        understanding=(_understanding(1, "find flights"), _understanding(2, "find direct flights"))
    )

    assert _peer(_episode(record)).meaning == "find direct flights"


def test_a_running_referent_s_excerpt_is_never_shown() -> None:
    """ADR-0353 §10:6, §16:4: the peer view of an episode whose understanding cites a
    ``running`` referent shows its meaning and nothing of the referent, its excerpt least
    of all, so no read chains through it."""
    excerpt = "RUNNING-EXCERPT book Luigi's for four"
    cited = ActivationUnderstanding(
        version=1,
        recorded_at=_NOW,
        producer=UnderstandingProducer.INTERPRETATION,
        meaning="move the running booking to Saturday",
        meaning_referents=(
            UnderstandingReferent(
                kind="running", id="activation:act-booking", source="c-1", excerpt=excerpt
            ),
        ),
    )
    for frozen in (False, True):
        view = _peer(_episode(_record(frozen=frozen, understanding=(cited,))))

        assert view.meaning == "move the running booking to Saturday"
        assert excerpt not in view.model_dump_json()
        assert "act-booking" not in view.model_dump_json()


def test_no_understanding_shows_no_meaning() -> None:
    assert _peer(_episode(_record(understanding=()))).meaning is None


# --- §6:9: what it found -----------------------------------------------------------------


def _found() -> EpisodeProcessingRecord:
    return _record(
        rounds=(
            _round(1, notes="TAP has a 9:40 direct"),
            _round(2, "Here are three options.", notes="the 9:40 is cheapest", marked=True),
            _round(3),
        ),
        digests=(
            ActivationDigest(
                result="R1",
                question="what does the page say",
                outcome=DigestOutcome.ANSWERED,
                evidence=(EvidenceItem(text="TAP 9:40, 312 EUR", source="R1"),),
                recorded_at=_NOW,
            ),
        ),
    )


def test_notes_and_evidence_are_shown_with_their_marks_to_an_owner_reader() -> None:
    view = _peer(_episode(_found()), owner_records=True)

    assert view.notes == (
        PeerNotes(notes=ProjectedText(text="TAP has a 9:40 direct", full_chars=21)),
        PeerNotes(notes=ProjectedText(text="the 9:40 is cheapest", full_chars=20), marked=True),
    )
    assert view.evidence == (
        ProjectedEvidence(text=ProjectedText(text="TAP 9:40, 312 EUR", full_chars=17)),
    )


def test_notes_and_evidence_keep_their_owner_only_placement() -> None:
    """ADR-0307 §4:4, ADR-0308 §5:6: placed for the owner alone, so withheld by default."""
    view = _peer(_episode(_found()))

    assert view.notes == ()
    assert view.evidence == ()


# --- §6:9: what it did --------------------------------------------------------------------


def test_effects_done_or_unknown_are_shown_in_claim_order() -> None:
    record = _found()
    effects = (
        _call("e1", ToolOutcome.SUCCEEDED),
        _call("e2", ToolOutcome.FAILED),
        _call("e3", None),
        _message("m1", ToolOutcome.INDETERMINATE, round_="r2"),
        _message("m2", ToolOutcome.SUCCEEDED, round_="r2"),
        _message("m3", None, round_="r2"),
        _message("m4", ToolOutcome.FAILED, round_="r2"),
    )

    view = _peer(_episode(record), effects)

    assert view.did == (
        PeerEffect(outcome=ToolOutcome.SUCCEEDED, capability="search_flights"),
        PeerEffect(
            outcome=ToolOutcome.INDETERMINATE,
            message=ProjectedText(text="Here are three options.", full_chars=23),
        ),
        PeerEffect(
            outcome=ToolOutcome.SUCCEEDED,
            message=ProjectedText(text="Here are three options.", full_chars=23),
        ),
    )


def test_the_couldnt_finish_message_is_its_fixed_line_alone() -> None:
    """§6:9, ADR-0307 §10: the record names no round, and nothing else it did is shown."""
    record = _record(understanding=(), frozen=True, understanding_omitted="not_reached")
    effects = (_message("m1", ToolOutcome.SUCCEEDED, round_=None),)

    view = _peer(_episode(record), effects)

    assert view.did == (PeerEffect(outcome=ToolOutcome.SUCCEEDED, couldnt_finish=True),)
    assert PEER_COULDNT_FINISH_LINE
    assert (view.meaning, view.notes, view.evidence) == (None, (), ())


def test_a_message_whose_round_the_episode_does_not_hold_shows_no_text() -> None:
    view = _peer(_episode(_found()), (_message("m1", ToolOutcome.SUCCEEDED, round_="r9"),))

    assert view.did == (PeerEffect(outcome=ToolOutcome.SUCCEEDED),)


# --- §6:10: what it never shows ------------------------------------------------------


def test_a_rounds_message_is_never_shown_from_the_round_itself() -> None:
    """§6:8: a message not yet sent is never shown, so a round's text reaches a peer only
    through a message effect done or unknown."""
    view = _peer(_episode(_found()), (_message("m1", None, round_="r2"),), owner_records=True)

    assert view.did == ()
    assert "Here are three options." not in view.model_dump_json()


def test_the_view_carries_no_field_beyond_its_work() -> None:
    """§6:10: no recall, story link, draft, approval, call value or result, response or
    round; the fields are the work §6:9 names and the facts a reader renders it by."""
    assert set(PeerView.model_fields) == {
        "channel",
        "parties",
        "relayed",
        "input",
        "joined",
        "meaning",
        "notes",
        "evidence",
        "did",
        "status",
        "reason",
        "derived_from_external",
    }
    assert set(PeerEffect.model_fields) == {"outcome", "capability", "message", "couldnt_finish"}


def test_a_call_shows_its_capability_and_never_its_values() -> None:
    view = _peer(_episode(_found()), (_call("e1", ToolOutcome.SUCCEEDED),))

    assert "a" * 64 not in view.model_dump_json()
    assert "d-e1" not in view.model_dump_json()


def test_the_external_flag_is_carried_for_the_readers_record() -> None:
    """§6:13: an outside episode a share shows counts in the reader's record."""
    assert _peer(_episode(_record(), external=True)).derived_from_external
    assert not _peer(_episode(_record())).derived_from_external


# --- refusals -----------------------------------------------------------------------------


def test_another_activations_effect_is_refused() -> None:
    other = _call("e1", ToolOutcome.SUCCEEDED).model_copy(update={"activation_id": "act-other"})
    with pytest.raises(ValueError, match="the activation it reads alone"):
        _peer(_episode(_record()), (other,))


def test_an_episode_with_no_processing_record_has_no_peer_view() -> None:
    episode = EpisodicMemory(
        id="harness-row",
        content="The user asked: what is on today?",
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_NOW),
        occurred_at=_NOW,
    )
    with pytest.raises(ValueError, match="has a processing record"):
        _peer(episode)


def test_a_bound_below_one_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        _peer(_episode(_record()), bound=0)


@pytest.mark.parametrize(
    "fields",
    [
        {"outcome": ToolOutcome.FAILED, "capability": "x"},
        {"outcome": ToolOutcome.SUCCEEDED, "capability": "x", "couldnt_finish": True},
        {
            "outcome": ToolOutcome.SUCCEEDED,
            "capability": "x",
            "message": ProjectedText(text="hi", full_chars=2),
        },
        {
            "outcome": ToolOutcome.SUCCEEDED,
            "couldnt_finish": True,
            "message": ProjectedText(text="hi", full_chars=2),
        },
    ],
)
def test_a_peer_effect_is_done_or_unknown_and_one_thing(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PeerEffect(**fields)


def test_a_peer_view_shows_input_only_where_it_is_the_users_own() -> None:
    with pytest.raises(ValidationError, match="the user's own"):
        PeerView(parties=UNIDENTIFIED_WORDS, input=ProjectedText(text="x", full_chars=1))
    with pytest.raises(ValidationError, match="the user's own"):
        PeerView(parties=OWNERS_WORDS, relayed=True, input=ProjectedText(text="x", full_chars=1))
    with pytest.raises(ValidationError, match="exactly with its reason"):
        PeerView(parties=OWNERS_WORDS, status=ProcessingStatus.COMPLETED)
