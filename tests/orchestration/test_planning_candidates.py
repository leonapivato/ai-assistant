"""What planning is told and shown once ``remember`` records candidates (ADR-0329 §6).

Driven directly over the planning stage, each outcome built by hand as the phases' glue
hands it over: the instruction (§6:1-§6:5, §6:8), a candidate's result (§4:1, §4:4,
§6:5), open questions beside a memory (§6:6) and an unprocessed episode's pending
candidates in the episode window (§6:9). With the switch off the instruction is today's,
as ``test_planning`` shows untouched.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

import pytest
from test_planning import (
    _TOOLS,
    _earlier,
    _episode,
    _inputs,
    _instruction,
    _now,
    _Recorder,
    _remembered,
    _sent,
)

from ai_assistant.core.types import (
    MemoryOperation,
    MemoryOperationKind,
    MemorySource,
    MemoryWriterName,
    OpenQuestion,
    OpenQuestionKind,
    ProposedCall,
    RoundResponse,
)
from ai_assistant.orchestration.planning import (
    CallOutcome,
    CallOutcomeKind,
    PlanningStage,
    RecordedCandidate,
)
from ai_assistant.orchestration.reliance import NOTE_RELIANCE
from ai_assistant.orchestration.remembering import REMEMBER, REMEMBER_CANDIDATE
from ai_assistant.testing import FakeToolCallingCompleter
from ai_assistant.testing.memories import memory, said_support

_AT: Final = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
_CANDIDATES_PARAGRAPH: Final = "Remember records a candidate for your long-term memory"
_RELIANCE_PARAGRAPH: Final = "Note the memories you relied on with note_reliance"

#: The test tools but its stand-in remember, which would disagree with the real one.
_OTHERS: Final = tuple(one for one in _TOOLS if one.capability != "remember")


def _stage(
    *responses: RoundResponse, candidates: bool = True
) -> tuple[PlanningStage, FakeToolCallingCompleter]:
    completer = FakeToolCallingCompleter.scripted(*(responses or (RoundResponse(text="ok"),)))
    ids = iter(f"round:{n}" for n in range(100))
    stage = PlanningStage(
        completer=completer,
        recorder=_Recorder(),
        excerpt_chars=200,
        now=_now,
        new_id=lambda: next(ids),
        candidates=candidates,
    )
    return stage, completer


# --- the instruction (§6:1-§6:5, §6:8) -----------------------------------------------------


async def test_the_instruction_says_what_a_candidate_is_for_and_how_to_reply() -> None:
    """§6:1-§6:5, §5:1: the page and memory, eagerness, naming a memory, asking, replying."""
    stage, completer = _stage()

    await stage.plan(_inputs(capabilities=(*_OTHERS, REMEMBER_CANDIDATE, NOTE_RELIANCE)))

    instruction = _instruction(completer)
    assert _CANDIDATES_PARAGRAPH in instruction
    for said in (
        # §6:1: what a candidate is for, beside a story note, nothing copied.
        "true and useful if this matter ended or were forgotten",
        "write a story note for what matters to this matter",
        "with nothing copied from one to the other",
        # §6:2: single observations; eager about the user's world, strict for trivia.
        "Record single observations as candidates too",
        "people, places, preferences, constraints and plans, and strict for trivia",
        # §6:3: naming a memory only for something new; a judgment alone is no candidate.
        "record a candidate naming it by its M label",
        "is never a candidate by itself",
        # §6:4: asking only for a conflict that matters.
        "only where it conflicts with the candidate and the conflict matters",
        # §5:1: confirm.
        "Set confirm where you want the user's yes to the fact's wording",
        # §6:5: will remember, never saved.
        '"got it, I\'ll remember"',
        "never that it is saved",
    ):
        assert said in instruction
    # §6:8: reliance, where offered.
    assert _RELIANCE_PARAGRAPH in instruction
    assert "not for one only mentioned in passing" not in instruction
    assert "never for one only mentioned in passing" in instruction


async def test_reliance_is_said_only_where_it_is_offered() -> None:
    stage, completer = _stage()

    await stage.plan(_inputs(capabilities=(*_OTHERS, REMEMBER_CANDIDATE)))

    assert _CANDIDATES_PARAGRAPH in _instruction(completer)
    assert _RELIANCE_PARAGRAPH not in _instruction(completer)


async def test_with_the_switch_off_the_instruction_is_todays() -> None:
    """ADR-0328 §13:6: the interim's instruction does not change, whatever is offered."""
    stage, completer = _stage(candidates=False)

    await stage.plan(_inputs(capabilities=(*_OTHERS, REMEMBER, NOTE_RELIANCE)))

    assert "candidate" not in _instruction(completer)
    assert _RELIANCE_PARAGRAPH not in _instruction(completer)


# --- a candidate's result (§4:1, §4:4, §6:5) -----------------------------------------------


def _remember(call_id: str = "c1") -> ProposedCall:
    return ProposedCall(
        call_id=call_id,
        name="remember",
        arguments={"fact": "prefers window seats", "why": "travel", "rests_on_input": True},
    )


async def test_a_candidates_result_says_pending_and_shows_similar_memories_by_m_label() -> None:
    """§6:5: recorded and pending; §4:1: each similar memory under its own M label.

    §4:2: one whose current version rests on outside content is withheld.
    """
    earlier = _earlier(calls=(_remember(),))
    aisle = _remembered("aisle", MemorySource.USER_ASSERTED, "prefers aisle seats")
    reported = _remembered("reported", MemorySource.EXTERNAL, "window seat booked by airline")
    outcome = CallOutcome(
        earlier.id,
        "c1",
        CallOutcomeKind.DONE,
        result_id="result:candidate",
        candidate=RecordedCandidate(similar=(aisle, reported)),
    )
    stage, completer = _stage()

    planned = await stage.plan(
        _inputs(capabilities=(REMEMBER_CANDIDATE,), rounds=(earlier,), outcomes=(outcome,))
    )

    request = completer.last_call.messages[1].content
    (call,) = _sent(completer)["rounds"][0]["calls"]
    assert call["outcome"] == "done"
    value = call["result"]["value"]
    assert value["candidate"].startswith("recorded as a candidate, and pending")
    assert "never that it is saved" in value["candidate"]
    assert [(one["label"], one["fact"]) for one in value["similar_memories"]] == [
        ("M1", "prefers aisle seats")
    ]
    assert "booked by airline" not in request
    assert [one.label for one in planned.labels] == ["R1", "M1"]


async def test_a_candidate_with_nothing_similar_says_none() -> None:
    earlier = _earlier(calls=(_remember(),))
    outcome = CallOutcome(
        earlier.id,
        "c1",
        CallOutcomeKind.DONE,
        result_id="result:candidate",
        candidate=RecordedCandidate(similar=()),
    )
    stage, completer = _stage()

    await stage.plan(_inputs(rounds=(earlier,), outcomes=(outcome,)))

    (call,) = _sent(completer)["rounds"][0]["calls"]
    assert call["result"]["value"]["similar_memories"] == "none"


async def test_a_failed_lookup_is_said_and_the_candidate_is_still_recorded() -> None:
    """§4:4: the result says the similar memories could not be read; the call is done."""
    earlier = _earlier(calls=(_remember(),))
    outcome = CallOutcome(
        earlier.id,
        "c1",
        CallOutcomeKind.DONE,
        result_id="result:candidate",
        candidate=RecordedCandidate(similar=None),
    )
    stage, completer = _stage()

    await stage.plan(_inputs(rounds=(earlier,), outcomes=(outcome,)))

    (call,) = _sent(completer)["rounds"][0]["calls"]
    assert call["outcome"] == "done"
    value = call["result"]["value"]
    assert value["candidate"].startswith("recorded as a candidate, and pending")
    assert value["similar_memories"] == "could not be read; the candidate is still recorded"


def test_a_candidates_result_carries_the_id_its_label_names_and_no_raw_result() -> None:
    with pytest.raises(ValueError, match="the id acting minted"):
        CallOutcome("r", "c1", CallOutcomeKind.DONE, candidate=RecordedCandidate(similar=()))
    with pytest.raises(ValueError, match="as what was looked up"):
        CallOutcome(
            "r",
            "c1",
            CallOutcomeKind.DONE,
            result_id="result:x",
            result={"similar": []},
            candidate=RecordedCandidate(similar=()),
        )


# --- open questions beside a memory (§6:6) -------------------------------------------------


def _questioned() -> Any:
    support = said_support(when=_AT, added_at=_AT)
    asked = OpenQuestion(
        id="q1",
        kind=OpenQuestionKind.CONFLICT,
        asks="Is the dentist still Dr Rao?",
        rests_on=(support.points_at,),
        raised_at=_AT,
        raised_by=MemoryWriterName.OBSERVER,
    )
    settled = OpenQuestion(
        id="q2",
        kind=OpenQuestionKind.RECHECK,
        asks="Was it Tuesdays?",
        rests_on=(support.points_at,),
        raised_at=_AT,
        raised_by=MemoryWriterName.OBSERVER,
        resolved_at=_AT,
        resolved_by=support.points_at,
        resolution="the user said so",
    )

    def operation(kind: MemoryOperationKind, question: str | None = None) -> MemoryOperation:
        return MemoryOperation(
            kind=kind,
            cites=support.points_at,
            at=_AT,
            by=MemoryWriterName.OBSERVER,
            question=question,
        )

    return memory(
        "m1",
        "my dentist is Dr Rao",
        support,
        operations=(
            operation(MemoryOperationKind.CREATE),
            operation(MemoryOperationKind.RAISE_QUESTION, "q1"),
            operation(MemoryOperationKind.RAISE_QUESTION, "q2"),
            operation(MemoryOperationKind.RESOLVE_QUESTION, "q2"),
        ),
        open_questions=(asked, settled),
    )


@pytest.mark.parametrize("candidates", [True, False], ids=["switch-on", "switch-off"])
async def test_each_unresolved_open_question_goes_beside_its_memory(candidates: bool) -> None:
    """§6:6: in words, wherever the memory reaches planning; a resolved one does not.

    Nothing raises one before the observer runs, so on today's data this shows nothing,
    and it reads the same with the switch either way.
    """
    stage, completer = _stage(candidates=candidates)

    await stage.plan(_inputs(recalled=(_questioned(),)))

    (shown,) = _sent(completer)["recalled"]
    assert shown["label"] == "M1"
    assert shown["open_questions"] == ["Is the dentist still Dr Rao?"]


async def test_a_memory_with_no_open_question_shows_none() -> None:
    stage, completer = _stage()

    await stage.plan(
        _inputs(recalled=(_remembered("m1", MemorySource.USER_ASSERTED, "likes tea"),))
    )

    (shown,) = _sent(completer)["recalled"]
    assert "open_questions" not in shown


# --- the episode window's pending candidates (§6:9) ----------------------------------------


async def test_an_unprocessed_episodes_candidates_are_shown_with_it_marked_pending() -> None:
    """§6:9: each by its fact and marked pending, in the order recorded."""
    window = _episode("activation:past")
    stage, completer = _stage()

    await stage.plan(
        _inputs(
            episodes=(window,),
            pending={"activation:past": ("prefers window seats", "flies to Lisbon in May")},
        )
    )

    (shown,) = _sent(completer)["episode_window"]
    assert shown["candidates"] == [
        {
            "fact": "prefers window seats",
            "status": "pending: recorded for long-term memory, not yet kept",
        },
        {
            "fact": "flies to Lisbon in May",
            "status": "pending: recorded for long-term memory, not yet kept",
        },
    ]


async def test_no_other_rendering_shows_a_candidate() -> None:
    """§6:9: a found episode is shown without them, even where the window would show some."""
    found = _episode("activation:found")
    stage, completer = _stage()

    await stage.plan(
        _inputs(recalled=(found,), pending={"activation:found": ("prefers window seats",)})
    )

    (shown,) = _sent(completer)["recalled"]
    assert "candidates" not in shown


async def test_an_episode_with_nothing_pending_shows_no_candidates() -> None:
    stage, completer = _stage()

    await stage.plan(_inputs(episodes=(_episode("activation:past"),)))

    (shown,) = _sent(completer)["episode_window"]
    assert "candidates" not in shown
