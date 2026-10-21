"""The commit step's checks: what code sets and refuses, whatever a model answers (§9:5).

Driven on values: a view built by hand, a reply as the model would write it, and the
checked decision. Code sets each support's origin, ``when`` and added at and by (§9:5);
admits the assistant's words only beside the user's later keep (§10); holds §9:7's rule
for an inference and §11:5's floor; and raises a ``conflict`` question where ADR-0328
§6:5 would refuse a retirement (§13:1). The view a commit call is shown is read from the
stores in the last cases.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from observer_support import AT, Harness, address, episode, reply

from ai_assistant.core.types import (
    ConfirmationPart,
    EvidenceItemPart,
    FindingUnwritten,
    InputPart,
    Memory,
    MemoryOperation,
    MemoryOperationKind,
    MemoryStanding,
    MemorySupport,
    MemoryWriterName,
    ObservationAttemptEnd,
    ObservationFinding,
    ObserverInferencePart,
    OpenQuestion,
    OpenQuestionKind,
    Placement,
    PlacementReach,
    PlacementSetter,
    QuestionPart,
    ReadingCertainty,
    RoundMessagePart,
    SupportDirection,
    SupportOrigin,
    SupportPart,
    part_episode,
)
from ai_assistant.orchestration.observer.commit import (
    AddSupports,
    Blocked,
    Checked,
    CommitReply,
    CommitView,
    Create,
    RaiseQuestion,
    RecordUse,
    Similar,
    Unwritten,
    checked,
    commit_view,
    meets_floor,
)
from ai_assistant.orchestration.observer.reading import (
    EpisodeReader,
    ReadEpisode,
    Reading,
    ReadPart,
    Reliance,
)
from ai_assistant.orchestration.observer.scout import parsed
from ai_assistant.testing import FakeDiagnosticSink, FakeModelProvider
from ai_assistant.testing.memories import (
    inference_support,
    legacy_support,
    memory,
    said_support,
    sourced_support,
)

_NOW = AT + timedelta(hours=1)
_LEAVING = episode("leaving", at=AT)


def _part(
    handle: str,
    part: SupportPart,
    *,
    origin: SupportOrigin = SupportOrigin.USER_MESSAGE,
    at_minutes: int = 0,
    text: str = "I prefer window seats.",
) -> ReadPart:
    occurred = AT + timedelta(minutes=at_minutes)
    episode_id = part_episode(part) or address("leaving")
    return ReadPart(
        handle=handle,
        part=part,
        episode=episode_id,
        occurred_at=occurred,
        text=text,
        origin=origin,
        when=occurred,
    )


def _input(handle: str, name: str, *, at_minutes: int = 0) -> ReadPart:
    return _part(handle, InputPart(episode=address(name)), at_minutes=at_minutes)


def _view(
    *parts: ReadPart,
    similar: tuple[Similar, ...] = (),
    reliance: Reliance | None = None,
    yes: ReadPart | None = None,
) -> CommitView:
    finding = ObservationFinding(
        id="f1",
        episode=address("leaving"),
        claim="The user prefers window seats.",
        rests_on=tuple(one.part for one in parts) or (InputPart(episode=address("leaving")),),
        relied_on=None if reliance is None else reliance.memory.id,
    )
    return CommitView(
        finding=finding,
        leaving=_LEAVING,
        parts=parts,
        similar=similar,
        reliance=reliance,
        yes_inputs={} if yes is None else {yes.episode: yes},
    )


def _support(part: str, **fields: Any) -> dict[str, Any]:
    return {"part": part, "direction": "for", "backs_as_worded": True, "how_sure": "sure", **fields}


def _checked(view: CommitView, **fields: Any) -> Checked:
    return checked(
        CommitReply.model_validate(fields), view, now=_NOW, mint=lambda: "1", placement=Placement()
    )


def _similar(handle: str, held: Memory, *, questions: dict[str, str] | None = None) -> Similar:
    return Similar(
        handle=handle,
        memory=held.model_copy(update={"revision": 1}),  # as a store returns it
        supports=tuple(None for _ in held.supports),
        questions=questions or {},
    )


def test_code_sets_each_supports_origin_when_and_writer() -> None:
    """§9:5: the origin, ``when``, added at and by are code's, never the reply's."""
    view = _view(_input("P1", "leaving"))

    decision = _checked(
        view, action="create", wording="The user prefers window seats.", supports=[_support("P1")]
    )

    assert isinstance(decision.primary, Create)
    (support,) = decision.primary.memory.supports
    assert support.origin is SupportOrigin.USER_MESSAGE
    assert support.when == AT
    assert (support.added_at, support.added_by) == (_NOW, MemoryWriterName.OBSERVER)
    assert support.source_details is None
    created = decision.primary.memory.operations[0]
    assert (created.kind, created.by, created.at) == (
        MemoryOperationKind.CREATE,
        MemoryWriterName.OBSERVER,
        _NOW,
    )
    assert decision.primary.memory.id == "observed:1"


def test_a_label_the_step_was_not_shown_fails_the_check() -> None:
    """§9:5: a support points only at a part the finding rests on."""
    view = _view(_input("P1", "leaving"))

    unknown = _checked(view, action="create", wording="x", supports=[_support("P9")])
    twice = _checked(view, action="create", wording="x", supports=[_support("P1"), _support("P1")])

    assert unknown.primary == Unwritten(FindingUnwritten.CHECK_FAILED)
    assert twice.primary == Unwritten(FindingUnwritten.CHECK_FAILED)


def test_a_confirmation_is_sure_and_keeps_the_words_the_user_approved() -> None:
    """§5:5, ADR-0328 §4:11: sure by code, and the memory worded exactly as shown."""
    yes = _part(
        "P1",
        ConfirmationPart(
            episode=address("leaving"),
            asking_activation="asking",
            question=QuestionPart(round="r", part=1),
        ),
        origin=SupportOrigin.CONFIRMATION,
        text="The user prefers window seats.",
    )

    decision = _checked(
        _view(yes),
        action="create",
        wording="User likes windows",
        supports=[_support("P1", how_sure="unsure")],
    )

    assert isinstance(decision.primary, Create)
    assert decision.primary.memory.content == "The user prefers window seats."
    assert decision.primary.memory.supports[0].how_sure is ReadingCertainty.SURE
    assert decision.primary.memory.standing is MemoryStanding.CONFIRMED


def test_the_assistants_words_alone_back_nothing() -> None:
    """§10:1-§10:2: silence is not confirmation."""
    message = _part(
        "P1",
        RoundMessagePart(episode=address("leaving"), round="r1"),
        origin=SupportOrigin.ASSISTANT_MESSAGE,
    )

    decision = _checked(_view(message), action="create", wording="x", supports=[_support("P1")])

    assert decision.primary == Unwritten(FindingUnwritten.CHECK_FAILED)


def test_the_assistants_words_are_admitted_beside_the_users_later_keep() -> None:
    """§10:1: the user, in a later episode, asked to keep what the message said."""
    message = _part(
        "P1",
        RoundMessagePart(episode=address("leaving"), round="r1"),
        origin=SupportOrigin.ASSISTANT_MESSAGE,
    )
    keep = _input("P2", "later", at_minutes=5)
    earlier = _input("P3", "leaving")

    kept = _checked(
        _view(message, keep),
        action="create",
        wording="x",
        supports=[_support("P1"), _support("P2")],
    )
    same_episode = _checked(
        _view(message, earlier),
        action="create",
        wording="x",
        supports=[_support("P1"), _support("P3")],
    )

    assert isinstance(kept.primary, Create)
    assert same_episode.primary == Unwritten(FindingUnwritten.CHECK_FAILED)


def test_a_keep_before_the_leaving_episode_admits_nothing() -> None:
    """§10:1: the keep is in the leaving episode or a later one the observer read."""
    message = _part(
        "P1",
        RoundMessagePart(episode=address("story-1"), round="r1"),
        origin=SupportOrigin.ASSISTANT_MESSAGE,
        at_minutes=-20,
    )
    keep = _input("P2", "story-2", at_minutes=-10)

    decision = _checked(
        _view(message, keep),
        action="create",
        wording="x",
        supports=[_support("P1"), _support("P2")],
    )

    assert decision.primary == Unwritten(FindingUnwritten.CHECK_FAILED)


def test_a_write_another_episode_backs_as_worded_is_carried_only_by_the_leaving_backing_it() -> (
    None
):
    """§8:2: a part of the leaving episode merely beside a later or earlier claim carries nothing.

    What is new in a later episode waits until that episode is due, and a finding a
    past episode shows was that episode's to commit.
    """
    beside = _support("P1", backs_as_worded=False, how_sure="unsure")
    for other in ("later", "past"):
        minutes = 5 if other == "later" else -5
        view = _view(_input("P1", "leaving"), _input("P2", other, at_minutes=minutes))

        carried_elsewhere = _checked(
            view, action="create", wording="x", supports=[_support("P2"), beside]
        )
        carried_here = _checked(
            view, action="create", wording="x", supports=[_support("P2"), _support("P1")]
        )
        corrected = _checked(
            view,
            action="create",
            wording="x",
            supports=[_support("P1"), _support("P2", direction="against", backs_as_worded=False)],
        )

        assert carried_elsewhere.primary == Unwritten(FindingUnwritten.CHECK_FAILED), other
        assert isinstance(carried_here.primary, Create), other
        assert isinstance(corrected.primary, Create), other


def test_an_add_or_a_recheck_another_episode_carries_is_refused() -> None:
    """§8:2: an add and a recheck are writes the leaving episode carries too."""
    held = memory("m-seat", "x", said_support(address("past")))
    view = _view(
        _input("P1", "leaving"),
        _input("P2", "later", at_minutes=5),
        similar=(_similar("M1", held),),
    )
    beside = _support("P1", backs_as_worded=False)

    added = _checked(view, action="add", memory="M1", supports=[_support("P2"), beside])
    rechecked = _checked(
        view, action="recheck", memory="M1", asks="Still?", supports=[_support("P2"), beside]
    )
    added_here = _checked(view, action="add", memory="M1", supports=[_support("P1")])

    assert added.primary == Unwritten(FindingUnwritten.CHECK_FAILED)
    assert rechecked.primary == Unwritten(FindingUnwritten.CHECK_FAILED)
    assert isinstance(added_here.primary, AddSupports)


def test_evidence_the_leaving_episode_brings_against_a_memory_carries_a_recheck_or_an_add() -> None:
    """§8:2, §13:1: an earlier or later backing of the memory does not outweigh doubt the
    leaving episode raises; it is the context, or a qualification, of that doubt."""
    held = memory("m-seat", "x", said_support(address("past")))
    doubt = _support("P1", direction="against", backs_as_worded=False)
    for other in ("past", "later"):
        minutes = -5 if other == "past" else 5
        view = _view(
            _input("P1", "leaving"),
            _input("P2", other, at_minutes=minutes),
            similar=(_similar("M1", held),),
        )

        rechecked = _checked(
            view, action="recheck", memory="M1", asks="Still?", supports=[doubt, _support("P2")]
        )
        added = _checked(view, action="add", memory="M1", supports=[doubt, _support("P2")])

        assert isinstance(rechecked.primary, RaiseQuestion), other
        assert isinstance(added.primary, AddSupports), other


def test_an_earlier_message_of_the_assistant_is_carried_by_the_users_keep_in_the_leaving() -> None:
    """§8:2, §10:1: the user's keep in the leaving episode carries the message it admits."""
    message = _part(
        "P1",
        RoundMessagePart(episode=address("past"), round="r1"),
        origin=SupportOrigin.ASSISTANT_MESSAGE,
        at_minutes=-5,
    )
    keep = _input("P2", "leaving")

    decision = _checked(
        _view(message, keep),
        action="create",
        wording="x",
        supports=[_support("P1"), _support("P2", backs_as_worded=False)],
    )

    assert isinstance(decision.primary, Create)


def test_an_inference_only_later_episodes_would_complete_waits() -> None:
    """§8:2: the leaving episode completes an inference; a later one only qualifies it."""
    leaving = _input("P1", "leaving")
    earlier = [_input(f"P{index}", f"before-{index}", at_minutes=-index) for index in (2, 3)]
    later = [_input(f"P{index}", f"after-{index}", at_minutes=index) for index in (4, 5)]

    completed_later = _inferred([leaving, *later])
    completed_here = _inferred([leaving, *earlier, later[0]])
    leaving_aside = _inferred([*earlier, *later])

    assert completed_later.primary == Unwritten(FindingUnwritten.CHECK_FAILED)
    assert isinstance(completed_here.primary, Create)
    assert leaving_aside.primary == Unwritten(FindingUnwritten.CHECK_FAILED)


def test_a_resolve_a_later_episode_answers_waits() -> None:
    """§8:2, §13:5: an answer a later episode gave resolves nothing until it is due."""
    open_question = OpenQuestion(
        id="question:1",
        kind=OpenQuestionKind.RECHECK,
        asks="Still aisle?",
        rests_on=(InputPart(episode=address("past")),),
        raised_at=AT,
        raised_by=MemoryWriterName.OBSERVER,
    )
    held = memory(
        "m-seat", "The user likes aisle seats.", said_support(address("past"))
    ).model_copy(update={"open_questions": (open_question,)})
    view = _view(
        _input("P1", "leaving"),
        _input("P2", "later", at_minutes=5),
        similar=(_similar("M1", held, questions={"Q1": "question:1"}),),
    )

    decision = _checked(
        view,
        action="create",
        wording="The user prefers window seats.",
        supports=[_support("P1"), _support("P2")],
        resolves={"memory": "M1", "question": "Q1", "part": "P2", "note": "now window"},
    )

    assert isinstance(decision.primary, Create)
    assert decision.resolve is None


def test_a_resolve_on_the_assistants_words_a_later_keep_admits_waits() -> None:
    """§8:2, §13:2: the keep a resolve would rest on in the message's place is a later one's."""
    open_question = OpenQuestion(
        id="question:1",
        kind=OpenQuestionKind.RECHECK,
        asks="Still aisle?",
        rests_on=(InputPart(episode=address("past")),),
        raised_at=AT,
        raised_by=MemoryWriterName.OBSERVER,
    )
    held = memory(
        "m-seat", "The user likes aisle seats.", said_support(address("past"))
    ).model_copy(update={"open_questions": (open_question,)})
    message = _part(
        "P1",
        RoundMessagePart(episode=address("leaving"), round="r1"),
        origin=SupportOrigin.ASSISTANT_MESSAGE,
    )
    view = _view(
        message,
        _input("P2", "later", at_minutes=5),
        similar=(_similar("M1", held, questions={"Q1": "question:1"}),),
    )

    decision = _checked(
        view,
        action="create",
        wording="The user prefers window seats.",
        supports=[_support("P1"), _support("P2")],
        resolves={"memory": "M1", "question": "Q1", "part": "P1", "note": "now window"},
    )

    assert isinstance(decision.primary, Create)
    assert decision.resolve is None


def _choices(count: int) -> list[ReadPart]:
    """A choice in the leaving episode, and one in each of ``count - 1`` before it."""
    return [
        _input("P1", "leaving"),
        *(
            _input(f"P{index}", f"choice-{index}", at_minutes=-index)
            for index in range(2, count + 1)
        ),
    ]


def _inferred(parts: list[ReadPart], **extra: Any) -> Checked:
    return _checked(
        _view(*parts),
        action="create",
        wording="The user prefers window seats.",
        supports=[_support(one.handle, backs_as_worded=False) for one in parts],
        inference={"how_sure": "likely", "note": "chosen each time"},
        **extra,
    )


def test_an_inference_needs_three_distinct_episodes() -> None:
    """§11:5: the floor, checked by code before the write."""
    below = _inferred(_choices(2))
    at = _inferred(_choices(3))

    assert below.primary == Unwritten(FindingUnwritten.BELOW_FLOOR)
    assert isinstance(at.primary, Create)
    created = at.primary.memory
    assert created.standing is MemoryStanding.INFERENCE
    lead = created.supports[0]
    assert lead.points_at == ObserverInferencePart(episode=address("leaving"))
    assert (lead.origin, lead.when, lead.backs_as_worded) == (
        SupportOrigin.OBSERVER_INFERENCE,
        AT,
        True,
    )


def test_an_inference_beside_a_backing_support_fails_the_check() -> None:
    """§9:7: its other supports are for and back nothing as worded."""
    parts = _choices(3)

    decision = _checked(
        _view(*parts),
        action="create",
        wording="x",
        supports=[_support(one.handle) for one in parts],
        inference={"how_sure": "likely"},
    )

    assert decision.primary == Unwritten(FindingUnwritten.CHECK_FAILED)


def _message(episode_id: str) -> MemorySupport:
    """A round's message of ``episode_id``, for the memory and backing nothing as worded."""
    return MemorySupport(
        points_at=RoundMessagePart(episode=address(episode_id), round="r1"),
        origin=SupportOrigin.ASSISTANT_MESSAGE,
        direction=SupportDirection.FOR,
        backs_as_worded=False,
        how_sure=ReadingCertainty.LIKELY,
        when=AT,
        added_at=AT,
        added_by=MemoryWriterName.OBSERVER,
    )


def test_the_floor_counts_neither_the_inference_nor_the_assistants_words() -> None:
    """§11:5, §10:2, §11:7: what counts toward the floor, and what needs no bar."""
    sourced = memory(
        "m",
        "x",
        sourced_support(),
        said_support(address("b"), direction=SupportDirection.AGAINST),
    )
    inferred = memory(
        "n",
        "x",
        inference_support(address("leaving")),
        _message("a"),
        _message("b"),
        _message("c"),
    )

    assert meets_floor(sourced)
    assert not meets_floor(inferred)


def test_nothing_and_a_single_observation_are_reasons_not_writes() -> None:
    view = _view(_input("P1", "leaving"))

    assert _checked(view, action="nothing").primary == Unwritten(FindingUnwritten.NOT_KEPT)
    assert _checked(view, action="single_observation").primary == Unwritten(
        FindingUnwritten.SINGLE_OBSERVATION
    )


def test_a_recheck_raises_a_question_never_resting_on_a_confirmation() -> None:
    """§13:1-§13:2: a re-check rests on the yes's input, not the confirmation."""
    held = memory("m-seat", "The user likes aisle seats.", said_support(address("past")))
    yes = _part(
        "P1",
        ConfirmationPart(
            episode=address("leaving"),
            asking_activation="asking",
            question=QuestionPart(round="r", part=1),
        ),
        origin=SupportOrigin.CONFIRMATION,
    )
    view = _view(yes, similar=(_similar("M1", held),), yes=_input("P9", "leaving"))

    decision = _checked(
        view,
        action="recheck",
        memory="M1",
        asks="Does the user still like aisle seats?",
        supports=[_support("P1", direction="against", backs_as_worded=False)],
    )

    assert isinstance(decision.primary, RaiseQuestion)
    assert decision.primary.kind is OpenQuestionKind.RECHECK
    assert decision.primary.support.points_at == InputPart(episode=address("leaving"))
    assert decision.primary.support.origin is SupportOrigin.USER_MESSAGE
    assert decision.primary.support.direction is SupportDirection.AGAINST


def test_add_supports_to_a_memory_that_states_the_claim() -> None:
    """§11:1, §12:3: the user's message added where a memory already states it."""
    held = memory("m-seat", "The user prefers window seats.", said_support(address("past")))
    view = _view(_input("P1", "leaving"), similar=(_similar("M1", held),))

    decision = _checked(view, action="add", memory="M1", supports=[_support("P1")])
    inferred = _checked(
        _view(*_choices(3), similar=(_similar("M1", held),)),
        action="add",
        memory="M1",
        supports=[_support(f"P{index}", backs_as_worded=False) for index in (1, 2, 3)],
        inference={"how_sure": "likely"},
    )

    assert isinstance(decision.primary, AddSupports)
    assert decision.primary.target.id == "m-seat"
    assert isinstance(inferred.primary, Create)
    assert inferred.primary.memory.content == held.content


def test_a_retirement_cites_a_support_backing_the_new_memory() -> None:
    """§12:4-§12:5: one proposal, the new memory and the retiring operation it cites."""
    held = memory("m-seat", "The user likes aisle seats.", sourced_support())
    view = _view(_input("P1", "leaving"), similar=(_similar("M1", held),))

    retired = _checked(
        view,
        action="end",
        memory="M1",
        wording="The user prefers window seats.",
        supports=[_support("P1")],
        cites="P1",
    )
    uncited = _checked(
        view,
        action="end",
        memory="M1",
        wording="x",
        supports=[_support("P1")],
        cites=None,
    )

    assert isinstance(retired.primary, Create)
    assert retired.primary.retiring is not None
    assert retired.primary.retiring.memory.id == "m-seat"
    assert retired.primary.retiring.kind is MemoryOperationKind.END
    assert retired.primary.retiring.cites == InputPart(episode=address("leaving"))
    assert uncited.primary == Unwritten(FindingUnwritten.CHECK_FAILED)


def test_an_end_holding_until_a_later_time_fails_the_check() -> None:
    """ADR-0328 §5:10: an end whose about-when lies after its instant."""
    held = memory("m-seat", "The user likes aisle seats.", sourced_support())
    view = _view(_input("P1", "leaving"), similar=(_similar("M1", held),))

    decision = _checked(
        view,
        action="end",
        memory="M1",
        wording="x",
        cites="P1",
        supports=[_support("P1", about_when=(_NOW + timedelta(days=3)).isoformat())],
    )

    assert decision.primary == Unwritten(FindingUnwritten.CHECK_FAILED)


def test_a_lower_standing_raises_a_conflict_instead_of_retiring() -> None:
    """ADR-0328 §6:5, §13:1: the question it needs, resting on the support, against."""
    held = memory("m-seat", "The user likes aisle seats.", said_support(address("past")))
    report = _part(
        "P1",
        EvidenceItemPart(episode=address("leaving"), digest=0, item=0),
        origin=SupportOrigin.EVIDENCE,
        text="The booking shows a window seat.",
    )
    view = _view(report, similar=(_similar("M1", held),))

    decision = _checked(
        view,
        action="replace",
        memory="M1",
        wording="The booking of 3 May shows a window seat.",
        supports=[_support("P1")],
        cites="P1",
    )

    assert isinstance(decision.primary, RaiseQuestion)
    assert decision.primary.kind is OpenQuestionKind.CONFLICT
    assert decision.primary.target.id == "m-seat"
    assert decision.primary.support.direction is SupportDirection.AGAINST
    assert decision.primary.support.points_at == report.part


def test_a_resolve_names_a_question_the_step_was_shown() -> None:
    """§13:5: the answer's support resolves the question."""
    open_question = OpenQuestion(
        id="question:1",
        kind=OpenQuestionKind.RECHECK,
        asks="Still aisle?",
        rests_on=(InputPart(episode=address("past")),),
        raised_at=AT,
        raised_by=MemoryWriterName.OBSERVER,
    )
    held = memory(
        "m-seat", "The user likes aisle seats.", said_support(address("past"))
    ).model_copy(update={"open_questions": (open_question,)})
    view = _view(
        _input("P1", "leaving"), similar=(_similar("M1", held, questions={"Q1": "question:1"}),)
    )

    decision = _checked(
        view,
        action="nothing",
        supports=[_support("P1", direction="against", backs_as_worded=False)],
        resolves={"memory": "M1", "question": "Q1", "part": "P1", "note": "now window"},
    )
    stranger = _checked(
        view,
        action="nothing",
        supports=[_support("P1")],
        resolves={"memory": "M1", "question": "Q7", "part": "P1", "note": "now window"},
    )

    assert decision.resolve is not None
    assert (decision.resolve.question, decision.resolve.note) == ("question:1", "now window")
    assert decision.resolve.support.points_at == InputPart(episode=address("leaving"))
    assert stranger.resolve is None


def test_a_reliance_finding_records_held_up_let_down_or_nothing() -> None:
    """§14:2: the commit step decides; code builds the entry."""
    held = memory("m-seat", "The user prefers window seats.", said_support(address("past")))
    relied_at = AT - timedelta(minutes=1)
    reliance = Reliance(handle="M1", memory=held, shaped="the seat", relied_at=relied_at)
    view = _view(
        _input("P1", "later", at_minutes=5), similar=(_similar("M1", held),), reliance=reliance
    )

    up = _checked(view, track_record="held_up", note="the user booked it")
    neither = _checked(view, track_record="neither")

    assert isinstance(up.primary, RecordUse)
    entry = up.primary.entry
    assert (entry.episode, entry.relied_at, entry.held_up) == (address("leaving"), relied_at, True)
    assert (entry.recorded_at, entry.recorded_by) == (_NOW, MemoryWriterName.OBSERVER)
    assert neither.primary == Unwritten(FindingUnwritten.NOT_KEPT)


async def test_the_view_shows_only_the_claim_its_parts_and_similar_memories() -> None:
    """§9:3: the claim, the parts with what they answer, similar memories with supports."""
    harness = Harness()
    leaving = episode("leaving", text="Window seats please.")
    held = memory("m-seat", "The user prefers window seats.", said_support(address("leaving")))
    await harness.hold(leaving, held)
    part = ReadPart(
        handle="P1",
        part=InputPart(episode=address("leaving")),
        episode=address("leaving"),
        occurred_at=AT,
        text="Window seats please.",
        origin=SupportOrigin.USER_MESSAGE,
        when=AT,
        answers="Window or aisle?",
    )
    reading = Reading(leaving=ReadEpisode(handle="E1", record=leaving, parts=(part,)))
    finding = ObservationFinding(
        id="f1",
        episode=address("leaving"),
        claim="The user prefers window seats.",
        rests_on=(part.part,),
        candidate="effect-1",
    )

    reader = EpisodeReader(
        memory=harness.memory,
        plans=harness.plans,
        stories=harness.stories,
        story_episodes=0,
        related=0,
    )
    view = await commit_view(
        finding, reading, reader=reader, memory=harness.memory, plans=harness.plans, similar=5
    )
    gone = await commit_view(
        finding.model_copy(update={"rests_on": (InputPart(episode=address("nowhere")),)}),
        reading,
        reader=reader,
        memory=harness.memory,
        plans=harness.plans,
        similar=5,
    )

    assert view is not None
    assert gone is None
    payload = view.payload()
    assert set(payload) == {"claim", "under_review", "parts", "memories"}
    assert payload["parts"] == [part.rendered(answers=True, exchange="E1")]
    rendered = json.loads(json.dumps(payload))
    assert rendered["memories"][0]["supports"][0]["text"] == "Window seats please."
    assert "effect-1" not in json.dumps(payload)


_EXCHANGE_KEYS = {"exchange", "occurred_at"}


def test_each_part_names_the_exchange_it_belongs_to_and_when_that_occurred() -> None:
    """§8:5: a part is attributed to its exchange from the record, one label per exchange."""
    view = _view(
        _input("P1", "leaving"),
        _input("P2", "later", at_minutes=5),
        _part(
            "P3",
            RoundMessagePart(episode=address("leaving"), round="r1"),
            origin=SupportOrigin.ASSISTANT_MESSAGE,
        ),
        _input("P4", "earlier", at_minutes=-60),
    )

    parts = json.loads(json.dumps(view.payload()))["parts"]

    assert [(one["part"], one["exchange"], one["occurred_at"]) for one in parts] == [
        ("P1", "E1", AT.isoformat()),
        ("P2", "E2", (AT + timedelta(minutes=5)).isoformat()),
        ("P3", "E1", AT.isoformat()),
        ("P4", "E3", (AT - timedelta(minutes=60)).isoformat()),
    ]


def test_the_exchange_under_review_is_the_leaving_episode_whatever_the_parts() -> None:
    """§8:2: the step is told which exchange is under review, even where no part is in it."""
    carried = _view(_input("P1", "earlier", at_minutes=-60), _input("P2", "leaving"))
    elsewhere = _view(_input("P1", "later", at_minutes=5))

    shown = json.loads(json.dumps(carried.payload()))
    other = json.loads(json.dumps(elsewhere.payload()))

    assert shown["under_review"] == "E1"
    assert carried.exchanges()[address("leaving")] == "E1"
    assert [one["exchange"] for one in shown["parts"]] == ["E2", "E1"]
    assert other["under_review"] == "E1"
    assert [one["exchange"] for one in other["parts"]] == ["E2"]


async def test_a_memorys_support_names_its_exchange_and_when_it_occurred_where_known() -> None:
    """§11:6: a stored memory's supports share the parts' labels, so occasions can be counted.

    A support on an episode a part is from takes that part's label; one on an earlier
    episode read for the call takes its own label and that episode's time; one whose
    episode is not read keeps its label and shows no time; a legacy one has neither.
    """
    harness = Harness()
    leaving = episode("leaving", text="Window seats please.")
    earlier = episode("earlier", at=AT - timedelta(days=3), text="A window seat again.")
    held = memory(
        "m-seat",
        "The user prefers window seats.",
        said_support(address("earlier")),
        said_support(address("leaving")),
        said_support(address("nowhere")),
        legacy_support({"id": "old", "content": "Likes windows."}),
    )
    await harness.hold(leaving, earlier, held)
    part = ReadPart(
        handle="P1",
        part=InputPart(episode=address("leaving")),
        episode=address("leaving"),
        occurred_at=AT,
        text="Window seats please.",
        origin=SupportOrigin.USER_MESSAGE,
        when=AT,
    )
    reading = Reading(leaving=ReadEpisode(handle="E1", record=leaving, parts=(part,)))
    finding = ObservationFinding(
        id="f1",
        episode=address("leaving"),
        claim="The user prefers window seats.",
        rests_on=(part.part,),
    )
    reader = EpisodeReader(
        memory=harness.memory,
        plans=harness.plans,
        stories=harness.stories,
        story_episodes=0,
        related=0,
    )

    view = await commit_view(
        finding, reading, reader=reader, memory=harness.memory, plans=harness.plans, similar=5
    )

    assert view is not None
    rendered = json.loads(json.dumps(view.payload()))
    supports = rendered["memories"][0]["supports"]
    assert [(one["exchange"], one["occurred_at"]) for one in supports] == [
        ("E2", (AT - timedelta(days=3)).isoformat()),
        ("E1", AT.isoformat()),
        ("E3", None),
        (None, None),
    ]
    assert rendered["parts"][0]["exchange"] == "E1"


def test_the_exchanges_add_their_keys_and_change_nothing_else_shown() -> None:
    """§9:3: beside the exchange keys and ``under_review``, the payload is as it was."""
    held = memory("m-seat", "The user prefers window seats.", said_support(address("past")))
    reliance = Reliance(handle="M1", memory=held, shaped="the seat", relied_at=AT)
    answered = replace(_input("P1", "leaving"), answers="Window or aisle?")
    view = _view(answered, similar=(_similar("M1", held),), reliance=reliance)

    payload = json.loads(json.dumps(view.payload()))

    assert set(payload) == {"claim", "under_review", "parts", "memories", "relied_on"}
    assert payload["claim"] == "The user prefers window seats."
    assert payload["parts"] == [
        {**answered.rendered(answers=True), "exchange": "E1", "occurred_at": AT.isoformat()}
    ]
    # The scout's rendering of a part, which passes no exchange, is unchanged.
    assert set(answered.rendered(answers=True)) == {
        "part",
        "from",
        "outside",
        "at",
        "text",
        "answers",
    }
    (shown,) = payload["memories"]
    assert set(shown) == {"memory", "claim", "stands", "status", "supports", "open_questions"}
    (support,) = shown["supports"]
    assert set(support) - _EXCHANGE_KEYS == {
        "from",
        "outside",
        "direction",
        "backs_as_worded",
        "counted",
        "at",
        "text",
    }
    assert (support["exchange"], support["occurred_at"]) == ("E2", None)
    assert payload["relied_on"] == {"memory": "M1", "shaped": "the seat"}


_OWNER_ONLY = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED)


def _narrow(view: CommitView, **fields: Any) -> Checked:
    """A decision whose run was supplied a record placed for the owner alone (§12:6)."""
    return checked(
        CommitReply.model_validate(fields), view, now=_NOW, mint=lambda: "1", placement=_OWNER_ONLY
    )


def test_a_narrower_supply_never_widens_onto_a_stored_memory() -> None:
    """§12:6: an operation writes no placement, so an add folds through ``ingest`` instead."""
    held = memory("m-seat", "The user prefers window seats.", said_support(address("past")))
    view = _view(_input("P1", "leaving"), similar=(_similar("M1", held),))

    added = _narrow(view, action="add", memory="M1", supports=[_support("P1")])
    recheck = _narrow(
        view,
        action="recheck",
        memory="M1",
        asks="Still?",
        supports=[_support("P1", direction="against", backs_as_worded=False)],
    )
    retired = _narrow(
        view, action="end", memory="M1", wording="x", supports=[_support("P1")], cites="P1"
    )

    assert isinstance(added.primary, Create)
    assert added.primary.memory.content == held.content
    assert added.primary.memory.placement.reach is PlacementReach.OWNER
    assert recheck.primary == Blocked()
    assert isinstance(retired.primary, Create)
    assert retired.primary.retiring is None


def test_a_narrower_supply_blocks_an_entry_and_a_resolution_on_a_wider_memory() -> None:
    """§12:6, §16:4: neither is written onto the wider memory, and neither is dropped."""
    open_question = OpenQuestion(
        id="question:1",
        kind=OpenQuestionKind.RECHECK,
        asks="Still?",
        rests_on=(InputPart(episode=address("past")),),
        raised_at=AT,
        raised_by=MemoryWriterName.OBSERVER,
    )
    held = memory("m-seat", "The user prefers window seats.", said_support(address("past")))
    asked = held.model_copy(update={"open_questions": (open_question,)})
    asked = Memory.model_validate(
        {
            **asked.model_dump(),
            "operations": (
                *held.operations,
                MemoryOperation(
                    kind=MemoryOperationKind.RAISE_QUESTION,
                    cites=InputPart(episode=address("past")),
                    at=AT,
                    by=MemoryWriterName.OBSERVER,
                    question="question:1",
                ),
            ),
        }
    )
    reliance = Reliance(handle="M1", memory=held, shaped="the seat", relied_at=AT)
    relied = _view(
        _input("P1", "later", at_minutes=5), similar=(_similar("M1", held),), reliance=reliance
    )
    answered = _view(
        _input("P1", "leaving"), similar=(_similar("M1", asked, questions={"Q1": "question:1"}),)
    )

    entry = _narrow(relied, track_record="held_up")
    resolution = _narrow(
        answered,
        action="nothing",
        supports=[_support("P1", direction="against", backs_as_worded=False)],
        resolves={"memory": "M1", "question": "Q1", "part": "P1", "note": "now window"},
    )

    assert entry.primary == Blocked()
    assert resolution.primary == Blocked()


def test_a_recheck_on_the_assistants_words_rests_on_the_users_keep() -> None:
    """§10:1, §13:2: a question rests on one support, so on the keep, never the words."""
    held = memory("m-seat", "The user likes aisle seats.", said_support(address("past")))
    message = _part(
        "P1",
        RoundMessagePart(episode=address("leaving"), round="r1"),
        origin=SupportOrigin.ASSISTANT_MESSAGE,
    )
    keep = _input("P2", "later", at_minutes=5)
    view = _view(message, keep, similar=(_similar("M1", held),))

    decision = _checked(
        view,
        action="recheck",
        memory="M1",
        asks="Still aisle?",
        supports=[_support("P1", backs_as_worded=False), _support("P2", backs_as_worded=False)],
    )

    assert isinstance(decision.primary, RaiseQuestion)
    assert decision.primary.support.points_at == keep.part


def test_a_confirmation_is_added_only_to_a_memory_its_wording_agrees_with() -> None:
    """ADR-0328 §4:6: agreement under ADR-0121 §1's predicate, or nothing."""
    yes = _part(
        "P1",
        ConfirmationPart(
            episode=address("leaving"),
            asking_activation="asking",
            question=QuestionPart(round="r", part=1),
        ),
        origin=SupportOrigin.CONFIRMATION,
        text="the USER  prefers window seats.",
    )
    agreeing = memory("m-seat", "The user prefers window seats.", said_support(address("past")))
    other = memory("m-aisle", "The user prefers aisle seats.", said_support(address("past")))

    kept = _checked(
        _view(yes, similar=(_similar("M1", agreeing),)),
        action="add",
        memory="M1",
        supports=[_support("P1")],
    )
    refused = _checked(
        _view(yes, similar=(_similar("M1", other),)),
        action="add",
        memory="M1",
        supports=[_support("P1")],
    )

    assert isinstance(kept.primary, AddSupports)
    assert refused.primary == Unwritten(FindingUnwritten.CHECK_FAILED)


def test_a_confirmed_memory_asks_on_the_yes_input() -> None:
    """§13:2: a ``policy_ask`` rests on the yes's input in the confirmation's place."""
    yes = _part(
        "P1",
        ConfirmationPart(
            episode=address("leaving"),
            asking_activation="asking",
            question=QuestionPart(round="r", part=1),
        ),
        origin=SupportOrigin.CONFIRMATION,
    )
    view = _view(yes, yes=_input("P9", "leaving"))

    decision = _checked(view, action="create", wording="x", supports=[_support("P1")])

    assert isinstance(decision.primary, Create)
    asked_on = decision.primary.asked_on
    assert asked_on is not None
    assert asked_on.points_at == InputPart(episode=address("leaving"))
    assert asked_on.direction is SupportDirection.AGAINST


async def test_a_part_the_reading_no_longer_holds_is_read_again_by_its_address() -> None:
    """§16:4: a recorded finding keeps what it rests on however the window moved."""
    harness = Harness()
    leaving = episode("leaving", text="Window seats please.")
    gone_from_window = episode("later", at=AT + timedelta(minutes=1), text="Yes, always window.")
    owner_only = memory(
        "m-seat", "The user prefers window seats.", said_support(address("private"))
    )
    private = episode("private", at=AT - timedelta(days=1), text="secret").model_copy(
        update={"placement": _OWNER_ONLY}
    )
    await harness.hold(leaving, gone_from_window, owner_only, private)
    reading = Reading(leaving=ReadEpisode(handle="E1", record=leaving, parts=()))
    finding = ObservationFinding(
        id="f1",
        episode=address("leaving"),
        claim="The user prefers window seats.",
        rests_on=(InputPart(episode=address("later")),),
    )
    reader = EpisodeReader(
        memory=harness.memory,
        plans=harness.plans,
        stories=harness.stories,
        story_episodes=0,
        related=0,
    )

    view = await commit_view(
        finding, reading, reader=reader, memory=harness.memory, plans=harness.plans, similar=5
    )

    assert view is not None
    (part,) = view.parts
    assert (part.handle, part.text, part.origin) == (
        "P1",
        "Yes, always window.",
        SupportOrigin.USER_MESSAGE,
    )
    assert _OWNER_ONLY in view.supplied, "the episode a similar memory's support resolved from"


async def test_a_similar_memorys_support_in_an_open_episode_is_not_shown() -> None:
    """ADR-0286 §6:4: an open episode has no readable record for a model-facing read."""
    harness = Harness()
    leaving = episode("leaving", text="Window seats please.")
    running = episode("running", at=AT + timedelta(minutes=9), text="unfinished words", open_=True)
    held = memory("m-seat", "The user prefers window seats.", said_support(address("running")))
    await harness.hold(leaving, running, held)
    part = ReadPart(
        handle="P1",
        part=InputPart(episode=address("leaving")),
        episode=address("leaving"),
        occurred_at=AT,
        text="Window seats please.",
        origin=SupportOrigin.USER_MESSAGE,
        when=AT,
    )
    reading = Reading(leaving=ReadEpisode(handle="E1", record=leaving, parts=(part,)))
    finding = ObservationFinding(
        id="f1",
        episode=address("leaving"),
        claim="The user prefers window seats.",
        rests_on=(part.part,),
    )
    reader = EpisodeReader(
        memory=harness.memory,
        plans=harness.plans,
        stories=harness.stories,
        story_episodes=0,
        related=0,
    )

    view = await commit_view(
        finding, reading, reader=reader, memory=harness.memory, plans=harness.plans, similar=5
    )

    assert view is not None
    assert [one.memory.id for one in view.similar] == ["m-seat"]
    assert "unfinished words" not in json.dumps(view.payload())
    assert running.placement not in view.supplied


def test_a_derived_supply_narrows_an_owner_placed_memory_of_the_same_reach() -> None:
    """ADR-0217 §3:3: the meet keeps the stronger setter, so the owner's lift lifts nothing."""
    owner_placed = Placement(
        reach=PlacementReach.OWNER, set_by=PlacementSetter.OWNER_ACT, set_at=AT
    )
    held = memory(
        "m-seat",
        "The user prefers window seats.",
        said_support(address("past")),
        placement=owner_placed,
    )
    view = _view(_input("P1", "leaving"), similar=(_similar("M1", held),))

    added = _narrow(view, action="add", memory="M1", supports=[_support("P1")])

    assert isinstance(added.primary, Create)
    assert added.primary.memory.placement.set_by is PlacementSetter.DERIVED


def test_three_parts_of_one_episode_are_one_occasion() -> None:
    """§11:5: the floor counts distinct episodes, never parts."""
    one_sitting = [
        _part(f"P{index}", InputPart(episode=address("sitting"), message=index - 1))
        for index in (1, 2, 3)
    ]

    assert _inferred(one_sitting).primary == Unwritten(FindingUnwritten.BELOW_FLOOR)


def test_the_floor_needs_fewer_against_than_for() -> None:
    """§11:5: equal counts fall short; one fewer against clears it."""

    def inferred(against: int) -> Memory:
        return memory(
            "n",
            "x",
            inference_support(address("leaving")),
            *(
                said_support(address(name), direction=SupportDirection.FOR, note="").model_copy(
                    update={"backs_as_worded": False}
                )
                for name in ("a", "b", "c")
            ),
            *(
                said_support(address(f"no-{index}"), direction=SupportDirection.AGAINST)
                for index in range(against)
            ),
        )

    assert meets_floor(inferred(3))  # four for (the inference among them), three against
    assert not meets_floor(inferred(4))
    assert not meets_floor(inferred(5))


def test_a_key_the_commit_reply_does_not_name_is_dropped_and_the_reply_kept() -> None:
    """A stray key, at the top or inside a support, an inference or a resolve, is dropped."""
    resolves = {"memory": "M1", "question": "Q1", "part": "P1", "note": "asked"}
    named: dict[str, Any] = {
        "action": "add",
        "memory": "M1",
        "supports": [_support("P1")],
        "inference": {"how_sure": "likely"},
        "resolves": resolves,
        "track_record": "neither",
    }
    stray = {
        **named,
        "command": None,
        "supports": [_support("P1", reason="x")],
        "inference": {"how_sure": "likely", "why": None},
        "resolves": {**resolves, "extra": 1},
    }

    assert parsed(reply(**stray), CommitReply) == CommitReply.model_validate(named)


def test_a_commit_reply_still_validates_every_field_it_names() -> None:
    """Only a key the shape does not name is dropped: a bad or missing one fails whole."""
    support = {"part": "P1", "direction": "for", "how_sure": "sure"}

    assert parsed(reply(action="create", supports=[support]), CommitReply) is not None
    assert parsed(reply(action="keep", supports=[support]), CommitReply) is None
    assert parsed(reply(supports=[{**support, "how_sure": "maybe"}]), CommitReply) is None
    assert parsed(reply(supports=[{"part": "P1", "how_sure": "sure"}]), CommitReply) is None
    assert parsed(reply(inference={"note": "x"}), CommitReply) is None
    assert parsed(reply(resolves={"memory": "M1", "question": "Q1"}), CommitReply) is None


#: Reasoning a commit reply opened with in a learner rerun on a copy of live data
#: (2026-10-21), where the reply should have been the bare object alone.
_REASONING = (
    "The user's own words in P1 state the claim, and the memory M1 already holds it, "
    "so the action is add."
)
_ADD = {"action": "add", "memory": "M1", "supports": [_support("P1")]}


def test_a_commit_reply_with_prose_before_its_object_is_read() -> None:
    expected = CommitReply.model_validate(_ADD)

    assert parsed(f"{_REASONING}\n\n{reply(**_ADD)}", CommitReply) == expected
    assert parsed(f"{_REASONING}\n```json\n{reply(**_ADD)}\n```", CommitReply) == expected


def test_a_commit_reply_with_prose_after_its_object_is_read() -> None:
    expected = CommitReply.model_validate(_ADD)

    assert parsed(f"{reply(**_ADD)}\n\nThat is my decision.", CommitReply) == expected


def test_of_two_objects_in_a_reply_the_one_that_validates_is_read() -> None:
    """An object that does not validate is passed over; where both validate, the last."""
    bad = reply(action="keep", memory="M1")
    end = {"action": "end", "memory": "M1", "supports": [_support("P1", direction="against")]}

    assert parsed(f"{reply(**_ADD)} or perhaps {bad}", CommitReply) == CommitReply.model_validate(
        _ADD
    )
    assert parsed(f"{bad}, no: {reply(**_ADD)}", CommitReply) == CommitReply.model_validate(_ADD)
    assert parsed(
        f"First {reply(**_ADD)}, then on reflection {reply(**end)}", CommitReply
    ) == CommitReply.model_validate(end)


def test_a_fenced_object_is_read_before_a_bare_one() -> None:
    end = {"action": "end", "memory": "M1", "supports": [_support("P1", direction="against")]}
    content = f"```json\n{reply(**_ADD)}\n```\nOr else {reply(**end)}"

    assert parsed(content, CommitReply) == CommitReply.model_validate(_ADD)


def test_backticks_inside_a_fenced_objects_string_do_not_close_its_fence() -> None:
    """The last fenced decision wins whole, though its note quotes a fence."""
    nothing = {"action": "nothing", "note": "The user quoted ``` as source text."}
    create = {"action": "create", "wording": "x", "supports": [_support("P1")]}
    content = f"```json\n{reply(**create)}\n```\nOn reflection:\n```json\n{reply(**nothing)}\n```"

    assert parsed(content, CommitReply) == CommitReply.model_validate(nothing)


def test_an_object_fenced_as_another_language_is_read_as_any_other() -> None:
    """Only an untagged or ``json`` block is offered whole; any object is still met."""
    content = f"{_REASONING}\n```python\n{reply(**_ADD)}\n```\nThat is the code."

    assert parsed(content, CommitReply) == CommitReply.model_validate(_ADD)


def test_a_container_left_open_in_a_fenced_block_holds_what_follows_it() -> None:
    """A fence never cuts the search: a support after the block is still inside the answer."""
    fragment = json.dumps({"part": "P1", "how_sure": "sure", "note": "evidence"})
    for tag in ("json", "python", ""):
        content = (
            f'```{tag}\n{{"action": "add", "memory": "M1", "supports": [\n```\n{fragment}\n]}}'
        )

        assert parsed(content, CommitReply) is None
        assert parsed(content.removesuffix("\n]}"), CommitReply) is None
    opened_on_the_fence = f'```json {{"action": "add", "supports": [\n{fragment}\n```\n]}}'
    assert parsed(opened_on_the_fence, CommitReply) is None


def test_a_fenced_reply_is_read_with_crlf_line_endings_or_no_closing_fence() -> None:
    content = f"{_REASONING}\n```json\n{reply(**_ADD)}\n```\n"
    expected = CommitReply.model_validate(_ADD)

    assert parsed(content.replace("\n", "\r\n"), CommitReply) == expected
    assert parsed(content.removesuffix("```\n"), CommitReply) == expected


def test_a_reply_with_no_object_in_it_still_fails() -> None:
    assert parsed(_REASONING, CommitReply) is None
    assert parsed(f"{_REASONING} {{ and }} nothing more", CommitReply) is None


def test_an_object_in_prose_that_does_not_validate_still_fails() -> None:
    assert parsed(f"{_REASONING}\n{reply(action='keep', memory='M1')}", CommitReply) is None
    support = {"part": "P1", "how_sure": "sure"}  # no direction
    assert parsed(f"{_REASONING}\n{reply(action='add', supports=[support])}", CommitReply) is None


def test_an_object_in_prose_naming_no_field_of_the_shape_is_not_an_answer() -> None:
    """Every field has a default, so ``{}`` validates: in prose it is no decision to take."""
    assert parsed(f"{_REASONING} The view held {{}} for P2.", CommitReply) is None
    assert parsed(f'{_REASONING} It said {{"seat": "window"}}.', CommitReply) is None
    assert parsed("{}", CommitReply) == CommitReply()  # the whole reply reads as before


def test_nothing_inside_a_malformed_object_is_read_as_the_answer() -> None:
    """A support nested in a broken decision names ``note``, a field of the whole shape too."""
    support = json.dumps(_support("P1", note="the user said so"))
    broken = '{"action": "add", "memory": "M1", "supports": [' + support + "],}"
    truncated = '{"action": "add", "memory": "M1", "supports": [' + support

    assert parsed(f"{_REASONING}\n{broken}", CommitReply) is None
    assert parsed(f"{_REASONING}\n{truncated}", CommitReply) is None


def test_nothing_inside_an_array_or_a_fence_within_a_malformed_object_is_read() -> None:
    """Neither an array's members nor a fence opened inside an unclosed object is a reply."""
    fragment = json.dumps({"part": "P1", "how_sure": "sure", "note": "evidence"})
    fenced = '{ "action": "add", "supports": [\n```json\n{"note": "evidence"}\n```'

    assert parsed(f"[{fragment}]", CommitReply) is None
    assert parsed(f"{_REASONING}\n[{fragment}]", CommitReply) is None
    assert parsed(f"{_REASONING} [P1, {fragment}", CommitReply) is None
    assert parsed(fenced, CommitReply) is None
    assert parsed(f"{_REASONING}\n{fenced}", CommitReply) is None


def test_braces_inside_an_objects_strings_do_not_end_it() -> None:
    """A brace in a string, past an escaped quote too, neither ends an object nor opens one."""
    decision = {**_ADD, "note": 'the user wrote "{" and "}"'}
    support = json.dumps(_support("P1", note="the user said so"))
    broken = '{"note": "a \\" } b", "supports": [' + support + "],}"

    assert parsed(f"{_REASONING}\n{reply(**decision)}", CommitReply) == (
        CommitReply.model_validate(decision)
    )
    assert parsed(f"{_REASONING}\n{broken}", CommitReply) is None


def test_a_brace_that_never_closes_ends_the_search() -> None:
    """What follows an unclosed ``{`` may be inside it, so none of it is read."""
    assert parsed(f"A set {{P1, P2 and then {reply(**_ADD)}", CommitReply) is None


async def _three(harness: Harness) -> None:
    """Three episodes, a minute apart: with a window of two, the oldest has left it."""
    await harness.hold(
        episode("one", at=AT - timedelta(minutes=3), text="I prefer window seats when I fly."),
        episode("two", at=AT - timedelta(minutes=2), text="What time is it?"),
        episode("three", at=AT - timedelta(minutes=1), text="Thanks."),
    )


_SCOUTED = reply(findings=[{"claim": "The user prefers window seats.", "rests_on": ["P1"]}])


async def test_a_commit_reply_with_a_stray_key_is_written() -> None:
    """End to end: the decision is checked and written as if the key were not there."""
    harness = Harness()
    await _three(harness)
    decision = reply(
        action="create",
        wording="The user prefers window seats.",
        supports=[_support("P1", command=None)],
        command=None,
    )
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_SCOUTED), commit=FakeModelProvider.scripted(decision)
    )

    outcome = await observer.run()

    assert outcome.processed == 1
    (record,) = await harness.plans.observations(["activation:one"])
    (finding,) = record.findings
    assert finding.outcome is not None
    (write,) = finding.outcome.writes
    stored = await harness.memory.get(write.memory)
    assert isinstance(stored, Memory)
    assert stored.content == "The user prefers window seats."


async def test_a_commit_reply_with_prose_around_its_object_is_written() -> None:
    """End to end: the object is the decision, and the reasoning around it is set aside."""
    harness = Harness()
    await _three(harness)
    decision = reply(
        action="create", wording="The user prefers window seats.", supports=[_support("P1")]
    )
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_SCOUTED),
        commit=FakeModelProvider.scripted(f"{_REASONING}\n\n{decision}\n\nDone."),
    )

    outcome = await observer.run()

    assert outcome.processed == 1
    (record,) = await harness.plans.observations(["activation:one"])
    (finding,) = record.findings
    assert finding.outcome is not None
    (write,) = finding.outcome.writes
    stored = await harness.memory.get(write.memory)
    assert isinstance(stored, Memory)
    assert stored.content == "The user prefers window seats."


_FRAGMENT = json.dumps({"part": "P1", "how_sure": "sure", "note": "evidence"})


@pytest.mark.parametrize(
    "content",
    [
        f"{_REASONING}\n[{_FRAGMENT}]",
        f'```json\n{{"action": "add", "memory": "M1", "supports": [\n```\n{_FRAGMENT}\n]}}',
    ],
    ids=["inside-an-array", "inside-an-object-spanning-a-fence"],
)
async def test_a_fragment_of_a_malformed_commit_reply_fails_as_unparsed(content: str) -> None:
    """§16:4: a support inside a container is no decision; the attempt fails and waits."""
    harness = Harness()
    await _three(harness)
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_SCOUTED), commit=FakeModelProvider.scripted(content)
    )

    outcome = await observer.run()

    assert outcome.waiting == 1
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.attempts[-1].end is ObservationAttemptEnd.FAILED
    (finding,) = record.findings
    assert finding.outcome is None


async def test_a_commit_reply_missing_a_required_key_still_fails_as_unparsed() -> None:
    """§16:4: a support with no direction is no decision; the attempt fails, naming commit."""
    harness = Harness()
    await _three(harness)
    sink = FakeDiagnosticSink()
    decision = reply(
        action="create",
        wording="The user prefers window seats.",
        supports=[{"part": "P1", "how_sure": "sure", "command": None}],
    )
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_SCOUTED),
        commit=FakeModelProvider.scripted(decision),
        diagnostics=sink,
    )

    outcome = await observer.run()

    assert outcome.waiting == 1
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.attempts[-1].end is ObservationAttemptEnd.FAILED
    (finding,) = record.findings
    assert finding.outcome is None
    assert json.loads(sink.recorded[-1].model_dump_json())["body"]["failure"] == {
        "class": "unparsed",
        "message": "the commit step's reply did not parse",
    }
