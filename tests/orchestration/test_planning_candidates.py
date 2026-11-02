"""What planning is told and shown once ``remember`` records candidates (ADR-0329 §6).

Driven directly over the planning stage, each outcome built by hand as the phases' glue
hands it over: the instruction, which takes no flag (ADR-0356 §4:2), a candidate's result
(§4:1, §4:4, §6:5) in the report after the round that called ``remember`` (ADR-0356 §5:4),
open questions beside a memory (§6:6) and an unprocessed episode's pending candidates in
the episode window (§6:9). ADR-0328 §13's interim, and the switch that kept its
instruction, are retired.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import pytest
from exchange_support import reported, section, tag, tags
from test_planning import (
    _TOOLS,
    FLAG_ECHO,
    FLAG_ECHO_TEXT,
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
    from ai_assistant.orchestration.planning import PlannedRound, PlanningInputs
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


# --- the instruction takes no flag (ADR-0356 §4:2) --------------------------------------


@pytest.mark.parametrize(
    "offered",
    [(REMEMBER_CANDIDATE, NOTE_RELIANCE), (REMEMBER_CANDIDATE,), (NOTE_RELIANCE,), ()],
    ids=["both", "candidates", "reliance", "neither"],
)
async def test_the_instruction_is_the_same_whichever_of_candidates_and_reliance_is_offered(
    offered: tuple[ToolDefinition, ...],
) -> None:
    """ADR-0356 §4:2: no flag; what each tool is for is in its description (ADR-0357 §7:1).

    The tool reaches the model where it is offered, and the instruction is the same.
    """
    sink = FakeDiagnosticSink()
    stage, completer = _stage(prompt=FLAG_ECHO, diagnostics=sink)

    flags = await _echoed(stage, completer, sink, _inputs(capabilities=(*_OTHERS, *offered)))

    assert flags == set()
    assert completer.last_call.exchange.instruction == FLAG_ECHO_TEXT
    names = {one.name for one in completer.last_call.tools}
    assert {one.capability for one in offered} <= names
    assert names.isdisjoint(
        {one.capability for one in (REMEMBER_CANDIDATE, NOTE_RELIANCE)}
        - {one.capability for one in offered}
    )


# --- a candidate's result (§4:1, §4:4, §6:5) -----------------------------------------------


def _remember(call_id: str = "c1") -> ProposedCall:
    return ProposedCall(
        call_id=call_id,
        name="remember",
        arguments={"fact": "prefers window seats", "why": "travel", "rests_on_input": True},
    )


async def _after_remember(
    candidate: RecordedCandidate, **fields: Any
) -> tuple[PlannedRound, FakeToolCallingCompleter]:
    """A round that calls ``remember``, then the next, reported what came of it (§5:4)."""
    stage, completer = _stage(
        RoundResponse(text="", calls=(_remember(),)), RoundResponse(text="ok")
    )
    inputs: PlanningInputs = _inputs(**fields)
    first = await stage.plan(inputs)
    outcome = CallOutcome(
        first.round.id,
        "c1",
        CallOutcomeKind.DONE,
        result_id="result:candidate",
        candidate=candidate,
    )
    planned = await stage.plan(
        replace(
            inputs,
            work=first.work,
            rounds=(first.round,),
            labels=first.labels,
            outcomes=(outcome,),
        )
    )
    return planned, completer


async def test_a_candidates_result_says_pending_and_shows_similar_memories_by_m_label() -> None:
    """§6:5: recorded and pending; §4:1: each similar memory under its own M label.

    §4:2: one whose current version rests on outside content is withheld. ADR-0358 §2:3:
    the result no longer tells planning never to say the fact is saved.
    """
    aisle = _remembered("aisle", MemorySource.USER_ASSERTED, "prefers aisle seats")
    outside = _remembered("reported", MemorySource.EXTERNAL, "window seat booked by airline")

    planned, completer = await _after_remember(
        RecordedCandidate(similar=(aisle, outside)), capabilities=(REMEMBER_CANDIDATE,)
    )

    (call,) = reported(completer.last_call)
    assert call["outcome"] == "done"
    value = call["result"]
    assert value["candidate"].startswith("recorded as a candidate for long-term memory")
    assert "the observer decides whether and how it is kept" in value["candidate"]
    assert "never that it is saved" not in value["candidate"]
    (similar,) = value["similar_memories"]
    shown = tag(similar, "memory")
    assert (shown.get("label"), shown.text) == ("M1", "prefers aisle seats")
    assert "booked by airline" not in completer.last_call.exchange.steps[-1].report.results[0].text
    # ADR-0364 §6:1: a candidate's result carries no R label; its similar memories keep theirs.
    assert [one.label for one in planned.labels] == ["M1"]


async def test_a_candidate_with_nothing_similar_says_none() -> None:
    _, completer = await _after_remember(RecordedCandidate(similar=()))

    (call,) = reported(completer.last_call)
    assert call["result"]["similar_memories"] == "none"


async def test_a_failed_lookup_is_said_and_the_candidate_is_still_recorded() -> None:
    """§4:4: the result says the similar memories could not be read; the call is done."""
    _, completer = await _after_remember(RecordedCandidate(similar=None))

    (call,) = reported(completer.last_call)
    assert call["outcome"] == "done"
    value = call["result"]
    assert value["candidate"].startswith("recorded as a candidate for long-term memory")
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

    shown = _recalled(completer)
    assert shown.get("label") == "M1"
    assert shown.get("open_questions") == "Is the dentist still Dr Rao?"


async def test_a_memory_with_no_open_question_shows_none() -> None:
    stage, completer = _stage()

    await stage.plan(
        _inputs(recalled=(_remembered("m1", MemorySource.USER_ASSERTED, "likes tea"),))
    )

    assert _recalled(completer).get("open_questions") is None


# --- ADR-0345 §12:3, §12:4: holders, disputes, a future end, and what the assistant said ---


def _held(*supports: MemorySupport, **fields: Any) -> Memory:
    return memory("m1", "Ana lives in Porto", *supports, **fields)


def _by(episode: str, holder: SupportHolder, **update: Any) -> MemorySupport:
    return said_support(episode, when=_AT, added_at=_AT).model_copy(
        update={"holder": holder, **update}
    )


_USER: Final = SupportHolder.person(OWNER_PERSON_ID)


def _recalled(completer: FakeToolCallingCompleter) -> Any:
    """The one memory the recalled-memories section shows, as its tag."""
    return tag(section(_sent(completer), "### Recalled memories"), "memory")


async def test_a_memory_the_user_alone_holds_names_no_holder() -> None:
    """§12:3: the holders are conveyed wherever they are not the owner alone."""
    stage, completer = _stage()

    await stage.plan(_inputs(recalled=(_held(_by("activation:a", _USER)),)))

    shown = _recalled(completer)
    assert shown.get("held_by") is None
    assert shown.get("disputed_by") is None


async def test_another_holder_and_a_dispute_are_conveyed() -> None:
    """§12:3: who else holds it, and who disputes it, so a disputed memory reads so."""
    stage, completer = _stage()
    held = _held(
        _by("activation:a", SupportHolder.person("tom")),
        _by("activation:b", _USER, direction=SupportDirection.AGAINST, backs_as_worded=False),
    )

    await stage.plan(_inputs(recalled=(held,)))

    shown = _recalled(completer)
    assert shown.get("held_by") == "a person the system knows"
    assert shown.get("disputed_by") == "P1"


async def test_a_future_validity_end_is_conveyed() -> None:
    """§12:3, §6:1: a memory that lapses says when."""
    stage, completer = _stage()
    end = _AT.replace(year=2027)
    held = _held(_by("activation:a", _USER, about_when=end), validity=Validity(valid_until=end))

    await stage.plan(_inputs(recalled=(held,)))

    assert _recalled(completer).get("holds_until") == "Mon 18 Oct 2027, 12:00 pm"


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

    shown = _recalled(completer)
    assert shown.get("kind") == (
        "what the system itself said, never what the owner said or a source reported"
    )
    assert shown.get("standing") is None
    assert shown.get("said_in") == "an earlier exchange at Sun 18 Oct 2026, 12:00 pm"
    assert shown.get("kept_by") == "P1"
    assert shown.get("held_by") is None


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

    episode = tag(section(_sent(completer), "## Short-term memory"), "episode", label="E1")
    assert episode.text is not None
    # ADR-0329 §6:9, which ADR-0356 leaves standing: each candidate by its fact, marked
    # pending, in the order recorded, inside the episode's short view.
    held = episode.text
    assert "prefers window seats" in held
    assert "flies to Lisbon in May" in held
    assert held.index("prefers window seats") < held.index("flies to Lisbon in May")
    assert "pending" in held


async def test_no_other_rendering_shows_a_candidate() -> None:
    """§6:9: a found episode is shown without them, even where the window would show some."""
    found = _episode("activation:found")
    stage, completer = _stage()

    await stage.plan(
        _inputs(recalled=(found,), pending={"activation:found": ("prefers window seats",)})
    )

    recalled = section(_sent(completer), "### Recalled memories")
    assert [one.get("label") for one in tags(recalled, "episode")] == ["E1"]
    assert "prefers window seats" not in _sent(completer)


async def test_an_episode_with_nothing_pending_shows_no_candidates() -> None:
    stage, completer = _stage()

    await stage.plan(_inputs(episodes=(_episode("activation:past"),)))

    episode = tag(section(_sent(completer), "## Short-term memory"), "episode", label="E1")
    assert "pending" not in (episode.text or "")
