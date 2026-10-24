"""Retrieval and placement: what code retrieves, the compact form, and a reply's placement.

Driven over the canonical fakes and on values (ADR-0346 §6:1-§6:4). Retrieval is code's:
by relevance to the framed wording above a threshold, then every memory naming a person
it names, up to a bound. The compact form is computed from the stored record. A placement
reply names each memory shown once, by a relation of ADR-0345 §4's closed set, with a
note where one is owed, or is refused whole.
"""

from __future__ import annotations

import json
from datetime import timedelta

from observer_support import AT, Harness, address, episode, placing, reply

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    Memory,
    MemoryOperation,
    MemoryOperationKind,
    MemoryPlacement,
    MemoryWriterName,
    OpenQuestion,
    OpenQuestionKind,
    PlacedAnswer,
    PlacedRelation,
    Placement,
    PlacementReach,
    PlacementSetter,
    SupportHolder,
)
from ai_assistant.orchestration.observer.placement import (
    PlacementReply,
    PlacementView,
    Retrieved,
    placement_of,
    retrieved,
)
from ai_assistant.orchestration.observer.replies import parsed
from ai_assistant.testing.memories import confirmed_support, memory, said_support

_SEAT = "The user prefers window seats."


def _held(record_id: str, content: str, *supports: object, **fields: object) -> Memory:
    """A stored memory, its supports held by the owner."""
    built = memory(record_id, content, *supports, **fields)  # type: ignore[arg-type]  # supports
    owned = tuple(
        one.model_copy(update={"holder": SupportHolder.person(OWNER_PERSON_ID)})
        for one in built.supports
    )
    return Memory.model_validate(built.model_copy(update={"supports": owned}).model_dump())


def _framed(content: str = _SEAT, **fields: object) -> Memory:
    return memory("observed:new", content, said_support(address("one")), **fields)


async def _retrieved(harness: Harness, framed: Memory, **bounds: object) -> list[str]:
    found = await retrieved(
        framed,
        memory=harness.memory,
        plans=harness.plans,
        threshold=float(bounds.get("threshold", 0.8)),  # type: ignore[arg-type]  # a number
        bound=int(bounds.get("bound", 5)),  # type: ignore[call-overload]  # a number
        recent=int(bounds.get("recent", 3)),  # type: ignore[call-overload]  # a number
    )
    return [one.memory.id for one in found]


async def test_a_memory_relevant_enough_to_the_wording_is_retrieved() -> None:
    """ADR-0346 §6:1: by relevance above the threshold, and no lower."""
    harness = Harness()
    await harness.hold(
        episode("past", at=AT - timedelta(days=1)),
        _held("m-seat", _SEAT, said_support(address("past"))),
        _held("m-tea", "The user drinks tea in the morning.", said_support(address("past"))),
    )

    assert await _retrieved(harness, _framed()) == ["m-seat"]


async def test_a_memory_naming_a_person_the_framed_one_names_is_retrieved_too() -> None:
    """ADR-0346 §6:1, ADR-0345 §9:6: in either field, however unlike its wording."""
    harness = Harness()
    await harness.hold(
        episode("past", at=AT - timedelta(days=1)),
        _held("m-ana", "Ana lives in Lisbon.", said_support(address("past")), subjects=("Ana",)),
        _held(
            "m-party",
            "A surprise party for Ana is planned for May.",
            said_support(address("past")),
            involved=("Ana",),
        ),
        _held("m-tom", "Tom lives in Porto.", said_support(address("past")), subjects=("Tom",)),
    )

    found = await _retrieved(harness, _framed("Ana teaches piano.", subjects=("Ana",)))

    assert sorted(found) == ["m-ana", "m-party"]


async def test_retrieval_stops_at_its_bound() -> None:
    harness = Harness()
    await harness.hold(
        episode("past", at=AT - timedelta(days=1)),
        *(
            _held(f"m-{index}", f"Ana {index} lives in Lisbon.", said_support(address("past")))
            for index in range(4)
        ),
    )

    found = await _retrieved(harness, _framed("Ana lives in Lisbon."), threshold=0.5, bound=2)

    assert len(found) == 2


async def test_the_compact_form_is_computed_from_the_stored_record() -> None:
    """ADR-0346 §6:2-§6:3: holders, standing, counts, questions, recent supports."""
    harness = Harness()
    question = OpenQuestion(
        id="q-1",
        kind=OpenQuestionKind.RECHECK,
        asks="Still true?",
        rests_on=(said_support(address("old")).points_at,),
        raised_at=AT,
        raised_by="observer",  # type: ignore[arg-type]  # a writer's name
    )
    held = _held(
        "m-seat",
        _SEAT,
        said_support(address("old"), added_at=AT - timedelta(days=3)),
        said_support(address("past"), added_at=AT - timedelta(days=1)),
    )
    raised = MemoryOperation(
        kind=MemoryOperationKind.RAISE_QUESTION,
        cites=question.rests_on[0],
        note="Still true?",
        at=AT,
        by=MemoryWriterName.OBSERVER,
        question="q-1",
    )
    stored = held.model_copy(
        update={"open_questions": (question,), "operations": (*held.operations, raised)}
    )
    await harness.hold(
        episode("old", at=AT - timedelta(days=3), text="Window, always."),
        episode("past", at=AT - timedelta(days=1), text="Window again."),
        Memory.model_validate(stored.model_dump()),
    )

    (shown,) = await retrieved(
        _framed(), memory=harness.memory, plans=harness.plans, threshold=0.8, bound=5, recent=1
    )
    rendered = json.loads(json.dumps(shown.rendered()))

    assert rendered["memory"] == "M1"
    assert rendered["wording"] == _SEAT
    assert rendered["held_by"] == ["the user"]
    assert rendered["stands"] == "you said it"
    assert (rendered["for"], rendered["against"], rendered["episodes"]) == (2, 0, 2)
    assert rendered["open_questions"] == [{"question": "Q1", "asks": "Still true?"}]
    (recent,) = rendered["recent_supports"]
    assert recent["text"] == "Window again.", "the newest support, up to the number"
    assert shown.questions == {"Q1": "q-1"}


def _view(harness_memory: Memory) -> PlacementView:
    return PlacementView(
        framed=_framed(),
        texts={},
        retrieved=(Retrieved(handle="M1", memory=harness_memory, questions={"Q1": "q-1"}),),
    )


def _placed(view: PlacementView, text: str) -> MemoryPlacement | None:
    read = parsed(text, PlacementReply)
    return None if read is None else placement_of(read, view)


def test_a_reply_naming_each_memory_once_is_a_placement_at_the_revisions_read() -> None:
    """ADR-0346 §6:2, §6:6: one relation each, with its note, at the revision read."""
    stored = _held("m-seat", _SEAT, said_support(address("past"))).model_copy(
        update={"revision": 7}
    )
    view = _view(stored)

    placement = _placed(view, placing(("M1", "contained", "Part of what it says.")))

    assert placement is not None
    (pair,) = placement.pairs
    assert (pair.memory, pair.revision, pair.relation) == (
        "m-seat",
        7,
        PlacedRelation.CONTAINED,
    )
    assert pair.note == "Part of what it says."
    assert placement.answers is None


def test_a_reply_that_does_not_place_every_memory_once_is_refused() -> None:
    """ADR-0346 §6:2: a placement the writer would refuse is never sent to it."""
    stored = _held("m-seat", _SEAT, said_support(address("past"))).model_copy(
        update={"revision": 1}
    )
    view = _view(stored)

    assert _placed(view, reply(relations=[])) is None
    assert _placed(view, placing(("M1", "restates", "a"), ("M1", "restates", "b"))) is None
    assert _placed(view, placing(("M2", "restates", "Same."))) is None
    assert _placed(view, placing(("M1", "contradicts", "No."))) is None
    assert _placed(view, placing(("M1", "weakens", " "))) is None, "a note is owed"
    assert _placed(view, placing(("M1", "independent", ""))) is not None


def test_an_answered_question_is_named_on_a_memory_shown() -> None:
    """ADR-0346 §6:2: at most one open question the new memory answers."""
    stored = _held("m-seat", _SEAT, said_support(address("past"))).model_copy(
        update={"revision": 1}
    )
    view = _view(stored)

    answered = _placed(
        view,
        placing(("M1", "restates", "Same."), answers={"memory": "M1", "question": "Q1"}),
    )
    unknown = _placed(
        view,
        placing(("M1", "restates", "Same."), answers={"memory": "M1", "question": "Q9"}),
    )

    assert answered is not None
    assert answered.answers == PlacedAnswer(memory="m-seat", question="q-1")
    assert unknown is None


def test_the_placement_call_is_shown_the_framed_memory_and_the_compact_forms() -> None:
    """ADR-0346 §6:2: given the memory as framed and each retrieved one; nothing else."""
    stored = _held("m-seat", _SEAT, said_support(address("past"))).model_copy(
        update={"revision": 1}
    )

    payload = _view(stored).payload()

    rendered = json.loads(json.dumps(payload))
    assert rendered["memory"]["wording"] == _SEAT
    assert [one["memory"] for one in rendered["stored"]] == ["M1"]


async def test_a_confirmations_asking_episode_is_supplied_with_its_shown_wording() -> None:
    """ADR-0329 §12:6: the approved wording is read from the asking episode, so it joins."""
    harness = Harness()
    owner_only = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED)
    yes = confirmed_support(address("yes"), asking_activation="asking")
    await harness.hold(
        episode("yes", at=AT - timedelta(days=1), text="yes"),
        episode("asking", at=AT - timedelta(days=1, minutes=1), text="").model_copy(
            update={"placement": owner_only}
        ),
        _held("m-seat", _SEAT, yes),
    )

    (shown,) = await retrieved(
        _framed(), memory=harness.memory, plans=harness.plans, threshold=0.8, bound=5, recent=3
    )

    assert owner_only in shown.supplied
