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

from observer_support import AT, Harness, address, episode, placing, read_as, reply

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
    RECHECK_HELD,
    UNREAD_NOTE,
    PlacementRead,
    PlacementView,
    Retrieved,
    labelled,
    placement_of,
    retrieved,
)
from ai_assistant.orchestration.observer.replies import PlacementReplyShape
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


def _view(harness_memory: Memory, *more: Memory) -> PlacementView:
    return PlacementView(
        framed=_framed(),
        texts={},
        retrieved=(
            Retrieved(handle="M1", memory=harness_memory, questions={"Q1": "q-1"}),
            *(Retrieved(handle=f"M{index}", memory=one) for index, one in enumerate(more, start=2)),
        ),
    )


def _read(view: PlacementView, text: str) -> PlacementRead | None:
    read = read_as(text, PlacementReplyShape)
    return None if read is None else placement_of(read, view)


def _placed(view: PlacementView, text: str) -> MemoryPlacement | None:
    read = _read(view, text)
    return None if read is None else read.placement


def _stored(record_id: str = "m-seat", content: str = _SEAT, **fields: object) -> Memory:
    held = _held(record_id, content, said_support(address("past")), **fields)
    return held.model_copy(update={"revision": 1})


def test_a_reply_naming_each_memory_once_is_a_placement_at_the_revisions_read() -> None:
    """ADR-0346 §6:2, §6:6: one relation each, with its note, at the revision read."""
    stored = _held("m-seat", _SEAT, said_support(address("past"))).model_copy(
        update={"revision": 7}
    )
    view = _view(stored)

    read = _read(view, placing(("M1", "contained", "Part of what it says.")))

    assert read is not None
    (pair,) = read.placement.pairs
    assert (pair.memory, pair.revision, pair.relation) == (
        "m-seat",
        7,
        PlacedRelation.CONTAINED,
    )
    assert pair.note == "Part of what it says."
    assert read.placement.answers is None
    assert read.set_aside == ()


def test_a_reply_placing_no_memory_shown_readably_is_refused() -> None:
    """ADR-0329 §16:4: a reply that places nothing it was shown is no placement."""
    view = _view(_stored())

    assert _placed(view, reply(relations=[])) is None
    assert _placed(view, placing(("M1", "restates", "a"), ("M1", "restates", "b"))) is None
    assert _placed(view, placing(("M2", "restates", "Same."))) is None
    assert _placed(view, placing(("M1", "contradicts", "No."))) is None
    assert _placed(view, placing(("M1", "weakens", " "))) is None, "a note is owed"
    assert _placed(view, placing(("M1", "independent", ""))) is not None


def test_a_pair_the_reply_does_not_place_readably_is_unclear_and_the_rest_stand() -> None:
    """#3398, ADR-0345 §4:3: one unreadable pair never fails the attempt that placed others."""
    view = _view(_stored(), _stored("m-aisle", "The user likes aisle seats."))

    text = reply(
        relations=[
            {"memory": "M1", "relation": "restates", "note": "Same."},
            {"memory": "M2", "relation": "contradicts", "note": "No."},
            {"memory": "M7", "relation": "restates", "note": "Never shown."},
        ]
    )
    read = _read(view, text)
    unplaced = _read(view, placing(("M1", "restates", "Same.")))

    assert read is not None
    assert [(one.memory, one.relation, one.note) for one in read.placement.pairs] == [
        ("m-seat", PlacedRelation.RESTATES, "Same."),
        ("m-aisle", PlacedRelation.UNCLEAR, UNREAD_NOTE),
    ]
    assert read.set_aside == (
        {"memory": "M7", "why": "no memory was shown under this label"},
        {"memory": "M2", "why": "no relation of the set"},
    )
    assert unplaced is not None
    assert unplaced.placement.pairs[1].relation is PlacedRelation.UNCLEAR
    assert unplaced.set_aside == ({"memory": "M2", "why": "left unplaced"},)


def test_the_reply_shape_reads_an_unreadable_relation_as_unclear() -> None:
    """What any reader of the shape reads is what the stage reads (prompt_cases)."""
    read = read_as(
        placing(("M1", "contradicts", "No."), ("M2", "weakens", " "), ("M3", "restates", "Same.")),
        PlacementReplyShape,
    )
    unreadable = read_as(
        placing(("M1", "contradicts", "No."), ("M2", "weakens", " ")), PlacementReplyShape
    )

    assert read is not None
    assert [(one.relation, one.note) for one in read.relations] == [
        ("unclear", UNREAD_NOTE),
        ("unclear", UNREAD_NOTE),
        ("restates", "Same."),
    ]
    assert unreadable is None, "a reply placing nothing readably is refused by any reader"
    assert read_as(reply(relations=[]), PlacementReplyShape) is None


def test_an_answered_question_is_named_on_a_memory_shown() -> None:
    """ADR-0346 §6:2: at most one open question the new memory answers."""
    view = _view(_stored())

    answered = _placed(
        view,
        placing(("M1", "restates", "Same."), answers={"memory": "M1", "question": "Q1"}),
    )
    unknown = _read(
        view,
        placing(("M1", "restates", "Same."), answers={"memory": "M1", "question": "Q9"}),
    )

    assert answered is not None
    assert answered.answers == PlacedAnswer(memory="m-seat", question="q-1")
    assert unknown is not None, "an answer it was not shown never fails the attempt"
    assert unknown.placement.answers is None
    assert unknown.set_aside == (
        {
            "answer": {"memory": "M1", "question": "Q9"},
            "why": "no open question shown under these labels",
        },
    )


def test_a_recheck_on_a_memory_holding_an_open_one_is_kept_for_the_diagnostic_record() -> None:
    """ADR-0348 §4:2 (#3413): the writer raises no second check, so code keeps it beside.

    The pair is placed as named, since the writer writes nothing for it (§4:1), and the
    relation and its note are kept with what was set aside. A memory whose recheck was
    answered holds no open one, and a question of another kind holds no check.
    """
    asked = OpenQuestion(
        id="q-1",
        kind=OpenQuestionKind.RECHECK,
        asks="Does the 10am slot hold?",
        rests_on=(said_support(address("past")).points_at,),
        raised_at=AT,
        raised_by=MemoryWriterName.OBSERVER,
    )
    answered = asked.model_copy(
        update={"resolved_at": AT, "resolved_by": asked.rests_on[0], "resolution": "yes"}
    )
    conflict = asked.model_copy(update={"kind": OpenQuestionKind.CONFLICT})
    note = "Worth checking; an open question already asks this, so it is not needed."

    def read(*questions: OpenQuestion) -> PlacementRead:
        stored = _stored().model_copy(update={"open_questions": questions})
        found = _read(_view(stored), placing(("M1", "recheck", note)))
        assert found is not None
        return found

    held = read(asked)
    (pair,) = held.placement.pairs
    assert pair.relation is PlacedRelation.RECHECK
    assert held.set_aside == (
        {
            "memory": "M1",
            "relation": "recheck",
            "note": note,
            "why": RECHECK_HELD,
        },
    )
    assert read(answered).set_aside == ()
    assert read(conflict).set_aside == ()
    assert read().set_aside == ()


def test_a_list_of_answers_takes_the_first_naming_a_question_shown() -> None:
    """#3398: a list is read, never refused; one is taken and the rest are set aside."""
    view = _view(_stored())
    text = reply(
        relations=[{"memory": "M1", "relation": "restates", "note": "Same."}],
        answers=[
            {"memory": "M2", "question": "Q1"},
            {"memory": "M1", "question": "Q1"},
            {"memory": "M1", "question": "Q1"},
        ],
    )

    read = _read(view, text)
    empty = _placed(
        view, reply(relations=[{"memory": "M1", "relation": "independent"}], answers=[])
    )

    assert read is not None
    assert read.placement.answers == PlacedAnswer(memory="m-seat", question="q-1")
    assert [one["why"] for one in read.set_aside] == [
        "no open question shown under these labels",
        "a placement answers one question at most",
    ]
    assert empty is not None
    assert empty.answers is None


def test_no_label_of_the_call_reaches_a_note() -> None:
    """#3402: a note is stored, so the call's labels are put in words."""
    question = OpenQuestion(
        id="q-1",
        kind=OpenQuestionKind.RECHECK,
        asks="Is it still true?",
        rests_on=(said_support(address("past")).points_at,),
        raised_at=AT,
        raised_by=MemoryWriterName.OBSERVER,
    )
    asked = _stored().model_copy(update={"open_questions": (question,)})
    view = _view(asked, _stored("m-aisle", "Aisle, please."))

    placement = _placed(
        view,
        placing(
            ("M1", "recheck", "Bears on M2 and on M1's open question Q1, not on M12 or Q3."),
            ("M2", "independent", ""),
        ),
    )

    assert placement is not None
    assert placement.pairs[0].note == (
        'Bears on "Aisle, please." and on "The user prefers window seats."\'s open question '
        '"Is it still true?", not on M12 or Q3.'
    )


def test_the_calls_labels_stand_nowhere_in_its_data_so_each_is_a_reference() -> None:
    """#3402: "an M1 Mac" in a wording and "M1" as a label, in one note, each kept apart.

    The memories are labelled past every label the data holds, so the note's own text
    stays as written and every label of the call it cites is put in words.
    """
    question = OpenQuestion(
        id="q-1",
        kind=OpenQuestionKind.RECHECK,
        asks="Who reports Q1 sales now?",
        rests_on=(said_support(address("past")).points_at,),
        raised_at=AT,
        raised_by=MemoryWriterName.OBSERVER,
    )
    mac = _stored(content="The user works on an M1 Mac.")
    sales = _stored("m-sales", "The user reports sales to Dana.").model_copy(
        update={"open_questions": (question,)}
    )
    view = labelled(
        PlacementView(
            framed=_framed(),
            texts={},
            retrieved=(
                Retrieved(handle="M1", memory=mac),
                Retrieved(handle="M2", memory=sales, questions={"Q1": "q-1"}),
            ),
        )
    )

    placement = _placed(
        view,
        placing(
            ("M2", "recheck", "Is the M1 Mac still the user's, given M3 and Q2?"),
            ("M3", "independent", ""),
        ),
    )

    assert [one.handle for one in view.retrieved] == ["M2", "M3"]
    assert view.retrieved[1].questions == {"Q2": "q-1"}
    assert placement is not None
    assert placement.pairs[0].note == (
        'Is the M1 Mac still the user\'s, given "The user reports sales to Dana." and '
        '"Who reports Q1 sales now?"?'
    )


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
