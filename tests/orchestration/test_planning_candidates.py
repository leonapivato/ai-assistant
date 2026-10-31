"""What planning is told and shown once ``remember`` records candidates (ADR-0329 §6).

Driven directly over the planning stage, each outcome built by hand as the phases' glue
hands it over: the instruction's flags (§6:1-§6:5, §6:8), a candidate's result (§4:1,
§4:4, §6:5), open questions beside a memory (§6:6) and an unprocessed episode's pending
candidates in the episode window (§6:9). ADR-0328 §13's interim, and the switch that
kept its instruction, are retired.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import pytest
from test_planning import (
    _TOOLS,
    FLAG_ECHO,
    _earlier,
    _echoed,
    _episode,
    _inputs,
    _now,
    _Recorder,
    _remembered,
    _sent,
)

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    Memory,
    MemoryMark,
    MemoryOperation,
    MemoryOperationKind,
    MemorySource,
    MemorySupport,
    MemoryWriterName,
    OpenQuestion,
    OpenQuestionKind,
    ProposedCall,
    RoundResponse,
    SupportDirection,
    SupportHolder,
    Validity,
)
from ai_assistant.orchestration.planning import (
    PLANNING_PROMPT,
    CallOutcome,
    CallOutcomeKind,
    PlanningStage,
    RecordedCandidate,
)
from ai_assistant.orchestration.reliance import NOTE_RELIANCE
from ai_assistant.orchestration.remembering import REMEMBER_CANDIDATE
from ai_assistant.testing import FakeDiagnosticSink, FakeToolCallingCompleter, default_prompt

if TYPE_CHECKING:
    from ai_assistant.core.prompts import PromptTemplate
    from ai_assistant.core.types import ToolDefinition
from ai_assistant.testing.memories import memory, message_support, said_support

_AT: Final = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)

#: The test tools but its stand-in remember, which would disagree with the real one.
_OTHERS: Final = tuple(one for one in _TOOLS if one.capability != "remember")


def _stage(
    *responses: RoundResponse,
    prompt: PromptTemplate | None = None,
    diagnostics: FakeDiagnosticSink | None = None,
) -> tuple[PlanningStage, FakeToolCallingCompleter]:
    completer = FakeToolCallingCompleter.scripted(*(responses or (RoundResponse(text="ok"),)))
    ids = iter(f"round:{n}" for n in range(100))
    stage = PlanningStage(
        prompt=default_prompt(PLANNING_PROMPT) if prompt is None else prompt,
        completer=completer,
        recorder=_Recorder(),
        excerpt_chars=200,
        now=_now,
        new_id=lambda: next(ids),
        diagnostics=diagnostics,
    )
    return stage, completer


# --- the instruction's flags (§6:1-§6:5, §6:8) -----------------------------------------------


@pytest.mark.parametrize(
    ("offered", "handed"),
    [
        ((REMEMBER_CANDIDATE, NOTE_RELIANCE), {"candidates", "reliance"}),
        ((REMEMBER_CANDIDATE,), {"candidates"}),
        ((NOTE_RELIANCE,), {"reliance"}),
        ((), set()),
    ],
    ids=["both", "candidates", "reliance", "neither"],
)
async def test_the_template_is_handed_candidates_and_reliance_where_each_is_offered(
    offered: tuple[ToolDefinition, ...], handed: set[str]
) -> None:
    """ADR-0334 §4:2; §6:1-§6:5, §6:8: each flag where its capability is offered."""
    sink = FakeDiagnosticSink()
    stage, completer = _stage(prompt=FLAG_ECHO, diagnostics=sink)

    flags = await _echoed(stage, completer, sink, _inputs(capabilities=(*_OTHERS, *offered)))

    assert {"candidates", "reliance"} & flags == handed


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

    request = completer.last_call.exchange.briefing
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


async def test_each_unresolved_open_question_goes_beside_its_memory() -> None:
    """§6:6: in words, wherever the memory reaches planning; a resolved one does not."""
    stage, completer = _stage()

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


# --- ADR-0345 §12:3, §12:4: holders, disputes, a future end, and what the assistant said ---


def _held(*supports: MemorySupport, **fields: Any) -> Memory:
    return memory("m1", "Ana lives in Porto", *supports, **fields)


def _by(episode: str, holder: SupportHolder, **update: Any) -> MemorySupport:
    return said_support(episode, when=_AT, added_at=_AT).model_copy(
        update={"holder": holder, **update}
    )


_USER: Final = SupportHolder.person(OWNER_PERSON_ID)


async def test_a_memory_the_user_alone_holds_names_no_holder() -> None:
    """§12:3: the holders are conveyed wherever they are not the owner alone."""
    stage, completer = _stage()

    await stage.plan(_inputs(recalled=(_held(_by("activation:a", _USER)),)))

    (shown,) = _sent(completer)["recalled"]
    assert "held_by" not in shown
    assert "disputed_by" not in shown


async def test_another_holder_and_a_dispute_are_conveyed() -> None:
    """§12:3: who else holds it, and who disputes it, so a disputed memory reads so."""
    stage, completer = _stage()
    held = _held(
        _by("activation:a", SupportHolder.person("tom")),
        _by("activation:b", _USER, direction=SupportDirection.AGAINST, backs_as_worded=False),
    )

    await stage.plan(_inputs(recalled=(held,)))

    (shown,) = _sent(completer)["recalled"]
    assert shown["held_by"] == ["another person (tom)"]
    assert shown["disputed_by"] == ["the user"]


async def test_a_future_validity_end_is_conveyed() -> None:
    """§12:3, §6:1: a memory that lapses says when."""
    stage, completer = _stage()
    end = _AT.replace(year=2027)
    held = _held(_by("activation:a", _USER, about_when=end), validity=Validity(valid_until=end))

    await stage.plan(_inputs(recalled=(held,)))

    (shown,) = _sent(completer)["recalled"]
    assert shown["holds_until"] == end.isoformat()


async def test_an_assistant_statement_is_conveyed_as_what_the_assistant_said() -> None:
    """§12:4: never as the user's word or a source's, citing when, and who kept it."""
    stage, completer = _stage()
    message = message_support("activation:said", when=_AT, added_at=_AT).model_copy(
        update={"backs_as_worded": False}
    )
    held = _held(
        _by("activation:kept", _USER),
        message,
        marks=(MemoryMark.ASSISTANT_STATEMENT,),
    )

    await stage.plan(_inputs(recalled=(held,)))

    (shown,) = _sent(completer)["recalled"]
    assert shown["standing"] == "the assistant said it"
    assert "never what the user said" in str(shown["item"])
    assert shown["said"] == [{"in": "an earlier exchange", "at": _AT.isoformat()}]
    assert shown["kept_by"] == ["the user"]
    assert "held_by" not in shown


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
