"""ADR-0357 §8 in planning: the asking ``text`` call, its exact lines and the round's record.

Driven directly over the canonical ``FakeToolCallingCompleter``, with the helpers of
``test_planning`` and ``test_planning_asks``: which ``text`` call is the round's asking
message, the calls its ``asks`` names, the exact lines planning hands the phases, what the
round records as asked (ADR-0321 §2:6, §2:8), and a second asking call refused (§8:3).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Final

import pytest
from test_planning import _call, _earlier, _inputs, _remembered, _stage
from test_planning_asks import _SLOT, _TOOLS, _booking, _needs_you, _proposed, _remember_request

from ai_assistant.core.types import (
    ActionRequest,
    AskedCall,
    MemorySource,
    PlanningRound,
    RoundResponse,
)
from ai_assistant.orchestration.message_tools import TEXT_CALL, TEXT_CAPABILITY, with_question
from ai_assistant.orchestration.planning import (
    ALREADY_ASKING,
    CallOutcome,
    CallOutcomeKind,
    PlaceWindow,
    RefusedCall,
)

_LINE: Final = f'book — slot: "{_SLOT}"'


def _text(call_id: str = "t1", **arguments: Any) -> Any:
    return _call(call_id, TEXT_CAPABILITY, **{"to": "the user", **arguments})


async def _planned(
    *calls: Any,
    outcomes: tuple[CallOutcome, ...],
    rounds: tuple[PlanningRound, ...],
    **fields: Any,
) -> Any:
    stage, _, recorder = _stage(RoundResponse(calls=calls))
    planned = await stage.plan(
        _inputs(capabilities=(*_TOOLS, TEXT_CALL), rounds=rounds, outcomes=outcomes, **fields)
    )
    return planned, recorder


async def test_the_asking_calls_named_calls_are_recorded_and_their_lines_handed_on() -> None:
    """§8:1-§8:2, §8:4: each named call recorded as asked, its exact line for the phases."""
    earlier = _proposed(_SLOT)
    planned, recorder = await _planned(
        _text(words="I can book the table for 7pm tomorrow. Shall I?", asks=["1.1"]),
        outcomes=(_needs_you(earlier.id, "c1", _booking(), deliberate_repeat=True),),
        rounds=(earlier,),
    )

    assert planned.questions == {"t1": _LINE}
    (asked,) = planned.round.asked
    assert (asked.part, asked.tool.capability) == (1, "book")
    assert dict(asked.values) == {
        "slot": _SLOT,
        "client_reference": _booking().parameters["client_reference"],
    }
    assert asked.deliberate_repeat is True
    # The round's own text asks about nothing (ADR-0356 §7:5), and the call is planned.
    assert planned.round.text == ""
    assert [one.call.call_id for one in planned.calls] == ["t1"]
    # The recorder is handed the lines, so it can tell whether the question fits.
    ((recorded, _),) = recorder.recorded
    assert recorded.asked == planned.round.asked
    assert recorder.questions == [{"t1": _LINE}]


async def test_several_calls_are_numbered_by_part_in_the_order_named() -> None:
    """ADR-0321 §2:6: each line's number is its call's part."""
    earlier = _proposed("2026-10-12 19:00", "2026-10-13 20:00")
    outcomes = (
        _needs_you(earlier.id, "c1", _booking("2026-10-12 19:00")),
        _needs_you(earlier.id, "c2", _booking("2026-10-13 20:00")),
    )
    planned, _ = await _planned(
        _text(words="Shall I book both?", asks=["1.2", "1.1"]), outcomes=outcomes, rounds=(earlier,)
    )

    assert [one.part for one in planned.round.asked] == [1, 2]
    assert planned.questions["t1"] == (
        '1. book — slot: "2026-10-13 20:00"\n2. book — slot: "2026-10-12 19:00"'
    )


@pytest.mark.parametrize("name", ["9.9", "R1", "c1", "1.2"])
async def test_a_name_that_resolves_to_no_call_needing_the_user_is_dropped(name: str) -> None:
    """§8:5: dropped, and the message goes without a line for it."""
    earlier = _proposed(_SLOT, "2026-10-13 20:00")
    outcomes = (
        _needs_you(earlier.id, "c1", _booking()),
        CallOutcome(earlier.id, "c2", CallOutcomeKind.DONE),
    )
    planned, _ = await _planned(
        _text(words="Shall I?", asks=[name]), outcomes=outcomes, rounds=(earlier,)
    )

    assert planned.round.asked == ()
    assert planned.questions == {}
    assert [one.call.call_id for one in planned.calls] == ["t1"]


async def test_two_names_for_one_call_ask_about_it_once() -> None:
    earlier = _proposed(_SLOT, _SLOT)
    outcomes = (
        _needs_you(earlier.id, "c1", _booking()),
        _needs_you(earlier.id, "c2", _booking()),
    )
    planned, _ = await _planned(
        _text(words="Shall I?", asks=["1.1", " 1.2 "]), outcomes=outcomes, rounds=(earlier,)
    )
    assert len(planned.round.asked) == 1
    assert planned.questions == {"t1": _LINE}


async def test_a_second_text_call_carrying_asks_runs_nothing() -> None:
    """§8:3, §10's test: in the order the model returned them, the second is refused."""
    earlier = _proposed(_SLOT, "2026-10-13 20:00")
    outcomes = (
        _needs_you(earlier.id, "c1", _booking()),
        _needs_you(earlier.id, "c2", _booking("2026-10-13 20:00")),
    )
    planned, _ = await _planned(
        _text("t1", words="Booking at seven?", asks=["1.1"]),
        _text("t2", words="And at eight?", asks=["1.2"]),
        _text("t3", words="Back soon."),
        outcomes=outcomes,
        rounds=(earlier,),
    )

    assert [one.call.call_id for one in planned.calls] == ["t1", "t3"]
    assert planned.refused == (RefusedCall(planned.round.calls[1], ALREADY_ASKING),)
    assert [one.values["slot"] for one in planned.round.asked] == [_SLOT]
    assert set(planned.questions) == {"t1"}


async def test_the_first_asking_call_stays_the_asking_one_though_it_names_nothing() -> None:
    """§8:3, §8:5: it carries asks, so it is the round's asking message all the same."""
    earlier = _proposed(_SLOT)
    planned, _ = await _planned(
        _text("t1", words="Shall I?", asks=["9.9"]),
        _text("t2", words="Shall I really?", asks=["1.1"]),
        outcomes=(_needs_you(earlier.id, "c1", _booking()),),
        rounds=(earlier,),
    )
    assert planned.round.asked == ()
    assert [one.call.call_id for one in planned.refused] == ["t2"]


async def test_where_the_place_takes_no_message_nothing_is_asked() -> None:
    """ADR-0321 §7:3: nothing is askable where no message goes."""
    earlier = _proposed(_SLOT)
    planned, _ = await _planned(
        _text(words="Shall I?", asks=["1.1"]),
        outcomes=(_needs_you(earlier.id, "c1", _booking()),),
        rounds=(earlier,),
        place=PlaceWindow(takes_message=False),
    )
    assert planned.round.asked == ()
    assert planned.questions == {}


async def test_a_remember_is_asked_with_its_statement_and_what_it_replaces() -> None:
    """ADR-0321 §5:5: the replaced assertions are recorded by id and shown by statement."""
    earlier = _earlier(calls=(_call("c1", "remember", statement="I live in Rome"),))
    old = _remembered("m-old", MemorySource.USER_ASSERTED, "I live in Milan")
    outcome = _needs_you(earlier.id, "c1", _remember_request("I live in Rome"), replaces=(old,))
    planned, _ = await _planned(
        _text(words="Shall I remember it?", asks=["1.1"]), outcomes=(outcome,), rounds=(earlier,)
    )

    (asked,) = planned.round.asked
    assert asked.replaces == ("m-old",)
    assert planned.questions["t1"] == (
        'remember — statement: "I live in Rome"; replacing "I live in Milan"'
    )


async def test_an_unrecordable_call_is_not_asked_about() -> None:
    """ADR-0321 §2:8: a deliberate repeat of a capability safe to repeat makes no asked call."""
    from test_planning_asks import _SEARCH  # noqa: PLC0415

    earlier = _earlier(calls=(_call("c1", "web_search", query="rome"),))
    request = ActionRequest(tool=_SEARCH, parameters={"query": "rome"})
    planned, _ = await _planned(
        _text(words="Shall I?", asks=["1.1"]),
        outcomes=(_needs_you(earlier.id, "c1", request, deliberate_repeat=True),),
        rounds=(earlier,),
    )
    assert planned.round.asked == ()


async def test_a_call_an_earlier_round_asked_is_not_askable_again() -> None:
    """ADR-0321 §4:11: shown as already asked, so a later asks naming it is dropped."""
    first = _proposed(_SLOT)
    asking = _earlier(
        "round:asking",
        follows=first.id,
        asked=(AskedCall(part=1, tool=_TOOLS[1], values=_booking().parameters),),
    )
    planned, _ = await _planned(
        _text(words="Shall I?", asks=["1.1"]),
        outcomes=(_needs_you(first.id, "c1", _booking()),),
        rounds=(first, asking),
    )
    assert planned.round.asked == ()


def test_the_question_the_phases_send_is_the_words_then_the_lines() -> None:
    """§8:2: the phases join the lines planning hands them to the words as reworded."""
    assert with_question("Shall I?", _LINE) == f"Shall I?\n\nNeeds your yes:\n{_LINE}"


async def test_the_judge_leaves_a_text_calls_via_as_written_for_the_phases() -> None:
    """ADR-0357 §2:4: ``via`` names a place or a platform, so no label check refuses it."""
    planned, _ = await _planned(_text(words="Hi.", via="telegram"), outcomes=(), rounds=())
    (call,) = planned.calls
    assert call.call.arguments["via"] == "telegram"


async def _three_rounds(*responses: RoundResponse, asked_between: bool = False) -> tuple[Any, ...]:
    """Three rounds of one work: a booking needing the user, then ``responses``."""
    stage, _, recorder = _stage(RoundResponse(calls=(_call("c1", "book", slot=_SLOT),)), *responses)
    first_inputs = _inputs(capabilities=(*_TOOLS, TEXT_CALL))
    first = await stage.plan(first_inputs)
    second_inputs = replace(
        first_inputs,
        work=first.work,
        rounds=(first.round,),
        labels=first.labels,
        outcomes=(_needs_you(first.round.id, "c1", _booking()),),
    )
    second = await stage.plan(second_inputs)
    later = () if asked_between else (CallOutcome(second.round.id, "t1", CallOutcomeKind.DONE),)
    third = await stage.plan(
        replace(
            second_inputs,
            work=second.work,
            rounds=(first.round, second.round),
            labels=(*first.labels, *second.labels),
            outcomes=(*second_inputs.outcomes, *later),
        )
    )
    return second, third, recorder


async def test_a_reference_an_earlier_step_showed_may_be_asked_rounds_later() -> None:
    """§8:1: the exchange is never re-rendered, so a reference shown in an earlier report
    still names its call after an intervening round."""
    second, third, recorder = await _three_rounds(
        RoundResponse(calls=(_text("t1", words="Checking something first."),)),
        RoundResponse(calls=(_text("t2", words="Shall I book it?", asks=["1.1"]),)),
    )

    assert second.round.asked == ()
    (asked,) = third.round.asked
    assert asked.values["slot"] == _SLOT
    assert third.questions == {"t2": _LINE}
    assert recorder.questions[-1] == {"t2": _LINE}


async def test_a_reference_asked_about_since_is_not_asked_again() -> None:
    """ADR-0321 §4:11: once a round of this activation asked it, it is not askable again."""
    second, third, _ = await _three_rounds(
        RoundResponse(calls=(_text("t1", words="Shall I book it?", asks=["1.1"]),)),
        RoundResponse(calls=(_text("t2", words="Shall I, really?", asks=["1.1"]),)),
        asked_between=True,
    )

    assert len(second.round.asked) == 1
    assert third.round.asked == ()
    assert third.questions == {}
