"""Planning's side of the yes path: asking, the exact line and approved actions (ADR-0321).

Driven directly over the canonical ``FakeToolCallingCompleter``, with the helpers of
``test_planning``; nothing here is wired into the controller.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

import pytest
from test_planning import (
    _call,
    _earlier,
    _inputs,
    _instruction,
    _remembered,
    _sent,
    _stage,
    _tool,
)

from ai_assistant.core.types import (
    ActionRequest,
    AskedCall,
    LabelKind,
    MemorySource,
    PlanningLabel,
    PlanningRound,
    QuestionPart,
    RoundResponse,
)
from ai_assistant.orchestration.planning import (
    APPROVED_ACTION_ARGUMENT,
    APPROVED_ACTION_TOOL,
    DELIBERATE_REPEAT,
    LOOKING_FOR,
    ApprovedAction,
    CallOutcome,
    CallOutcomeKind,
    PlaceWindow,
    PlannedCall,
    RefusedCall,
    exact_line,
)

if TYPE_CHECKING:
    from ai_assistant.core.types import SemanticMemory, ToolDefinition

_BOOK: Final = _tool("book")
_SEARCH: Final = _tool("web_search")
_REMEMBER: Final = _tool(
    "remember",
    parameters_schema={
        "type": "object",
        "properties": {
            "statement": {"type": "string"},
            "episode": {"type": "string"},
        },
        "required": ["statement", "episode"],
        "additionalProperties": False,
    },
    system_supplied=("episode",),
)
_TOOLS: Final = (_SEARCH, _BOOK, _REMEMBER)

#: The booking a round proposed, and the request authorizing ruled on, the hub's value
#: for ``client_reference`` filled in.
_SLOT: Final = "2026-10-12 19:00"
_FILLED: Final = "ref-filled-by-the-hub"


def _booking(slot: str = _SLOT) -> ActionRequest:
    return ActionRequest(tool=_BOOK, parameters={"slot": slot, "client_reference": _FILLED})


def _needs_you(
    round_id: str, call_id: str, request: ActionRequest | None = None, **fields: Any
) -> CallOutcome:
    return CallOutcome(
        round_id,
        call_id,
        CallOutcomeKind.NEEDS_YOU,
        reason="the permission policy asks the user about this call",
        request=request,
        **fields,
    )


def _proposed(*slots: str) -> PlanningRound:
    """An earlier round that proposed one booking per slot, calls ``c1``, ``c2``…."""
    return _earlier(
        calls=tuple(_call(f"c{n}", "book", slot=slot) for n, slot in enumerate(slots, 1))
    )


async def _asked(
    *,
    asks: tuple[str, ...],
    outcomes: tuple[CallOutcome, ...],
    rounds: tuple[PlanningRound, ...],
    text: str = "Shall I book it?",
    **fields: Any,
) -> tuple[Any, Any]:
    stage, completer, _ = _stage(RoundResponse(text=text, asks=asks))
    planned = await stage.plan(
        _inputs(capabilities=_TOOLS, rounds=rounds, outcomes=outcomes, **fields)
    )
    return planned, completer


# --- the standing instructions (§2:9, §2:11, §3) -----------------------------------------------


async def test_the_instruction_says_how_approval_works_and_retires_no_route() -> None:
    """§2:9: the yes path, said plainly; #2853's "no answer can let it run" is gone."""
    stage, completer, _ = _stage()
    await stage.plan(_inputs())
    instruction = _instruction(completer)
    assert (
        "How approval works here: some actions need the user's yes before they run. When one "
        "does, you ask them, and the system shows them the action's exact details. Their yes "
        "in reply lets that exact action run, once. You never approve anything on the user's "
        "behalf, and there is no other route: no confirmation emails, no links or codes, and "
        "no steps on the user's end."
    ) in instruction
    for retired in (
        "cannot be done yet",
        "there is no way yet for them to approve it",
        "Never ask them to confirm, approve or say go ahead",
    ):
        assert retired not in instruction


async def test_the_instruction_carries_the_line_of_care() -> None:
    """§2:11: one line of care, which grants and withholds nothing."""
    stage, completer, _ = _stage()
    await stage.plan(_inputs())
    assert (
        "Check with the user first when you are unsure what they meant, or when a mistake "
        "would be costly, even where their authority already covers the action. Checking is "
        "care: it grants nothing and withholds nothing."
    ) in _instruction(completer)


async def test_the_instruction_says_how_to_ask_and_how_answers_go() -> None:
    """§2:1-§2:4, §2:12; planning's side of §3:5, §3:8-§3:9."""
    stage, completer, _ = _stage()
    await stage.plan(_inputs())
    instruction = _instruction(completer)
    assert "a call no message asks about is dropped" in instruction
    assert "explain the action in your own words, with the details that matter" in instruction
    assert "name the call in asks by the reference shown with its outcome" in instruction
    assert "The system adds the exact details below your message" in instruction
    assert "numbered where there are several" in instruction
    assert "no buttons and no options" in instruction
    assert "ask which they mean, and never guess" in instruction
    assert "ask again, with the new values where they changed them" in instruction


async def test_a_deny_is_never_asked_about_and_is_said_plainly() -> None:
    """§2:10, §8:7: the instruction and the refused outcome both say so."""
    earlier = _proposed(_SLOT)
    refused = CallOutcome(
        earlier.id, "c1", CallOutcomeKind.REFUSED, reason="the permission policy denies it"
    )
    planned, completer = await _asked(asks=("1.1",), outcomes=(refused,), rounds=(earlier,))
    assert (
        "where it was refused because the user's settings do not allow it, tell them "
        "plainly that it is not allowed"
    ) in _instruction(completer)
    shown = _sent(completer)["rounds"][0]["calls"][0]
    assert shown["outcome"].startswith(
        "refused before it ran, so nothing in it ran, and no yes lets it run: never ask the "
        "user about it"
    )
    assert "ask_as" not in shown
    assert planned.round.asked == ()
    assert planned.message == "Shall I book it?"


async def test_a_place_that_takes_no_message_is_told_nothing_is_asked() -> None:
    """§7:3: a timer's or an event's activation asks nothing, and the call will not run."""
    stage, completer, _ = _stage()
    await stage.plan(_inputs(place=PlaceWindow(takes_message=False)))
    instruction = _instruction(completer)
    assert "How approval works here" in instruction
    assert "This activation cannot message the user, so a call that needs them is not" in (
        instruction
    )
    assert "name the call in asks" not in instruction


# --- the per-call notes (§2:10, §4:11) -----------------------------------------------------------


async def test_a_call_needing_a_yes_is_shown_with_its_reference_and_reason() -> None:
    earlier = _proposed(_SLOT)
    _, completer = await _asked(
        asks=(), outcomes=(_needs_you(earlier.id, "c1", _booking()),), rounds=(earlier,)
    )
    assert _sent(completer)["rounds"][0]["calls"][0] == {
        "capability": "book",
        "arguments": {"slot": _SLOT},
        "outcome": (
            "needs the user's yes: ask them about it if you judge it right, explaining it in "
            "your own words, and name it in asks by its ask_as reference; the exact details "
            "will be filled in below your message"
        ),
        "ask_as": "1.1",
        "because": "the permission policy asks the user about this call",
    }


async def test_a_call_needing_the_user_where_no_message_goes_will_not_run() -> None:
    """§7:3: not asked about, whatever the response names."""
    earlier = _proposed(_SLOT)
    planned, completer = await _asked(
        asks=("1.1",),
        outcomes=(_needs_you(earlier.id, "c1", _booking()),),
        rounds=(earlier,),
        place=PlaceWindow(takes_message=False),
    )
    shown = _sent(completer)["rounds"][0]["calls"][0]
    assert shown["outcome"] == (
        "needs the user, and this activation cannot message them, so it will not run and is "
        "not asked about"
    )
    assert "ask_as" not in shown
    assert planned.round.asked == ()
    assert planned.round.text == "Shall I book it?"
    assert planned.message is None


async def test_a_call_already_waiting_on_the_user_is_not_asked_again() -> None:
    """§4:11: authorizing found it identical to a call still waiting on the user."""
    earlier = _proposed(_SLOT)
    waiting = _needs_you(
        earlier.id, "c1", _booking(), already_asked=QuestionPart(round="round:old", part=1)
    )
    planned, completer = await _asked(asks=("1.1",), outcomes=(waiting,), rounds=(earlier,))
    shown = _sent(completer)["rounds"][0]["calls"][0]
    assert shown["outcome"] == (
        "already asked about and waiting on the user's answer, so it is not asked about again"
    )
    assert "ask_as" not in shown
    assert planned.round.asked == ()
    assert planned.message == "Shall I book it?"


async def test_a_call_an_earlier_round_of_this_activation_asked_about_is_not_asked_again() -> None:
    """Two parts for one call would be two spendable yeses for it."""
    first = _proposed(_SLOT)
    asking = _earlier(
        "round:asking",
        follows=first.id,
        text="Shall I book it?",
        asked=(AskedCall(part=1, tool=_BOOK, values=_booking().parameters),),
    )
    planned, completer = await _asked(
        asks=("1.1",),
        outcomes=(_needs_you(first.id, "c1", _booking()),),
        rounds=(first, asking),
    )
    shown = _sent(completer)["rounds"][0]["calls"][0]
    assert shown["outcome"].startswith("already asked about")
    assert shown["asked_in"] == "round 2's message, part 1"
    assert planned.round.asked == ()


async def test_a_call_whose_request_was_not_handed_on_cannot_be_asked_about() -> None:
    earlier = _proposed(_SLOT)
    planned, completer = await _asked(
        asks=("1.1",), outcomes=(_needs_you(earlier.id, "c1"),), rounds=(earlier,)
    )
    shown = _sent(completer)["rounds"][0]["calls"][0]
    assert shown["outcome"] == "needs the user, and it cannot be asked about, so it will not run"
    assert planned.round.asked == ()


def test_only_a_call_that_needs_the_user_carries_what_a_question_shows() -> None:
    with pytest.raises(ValueError, match="only a call that needs the user"):
        CallOutcome("r", "c", CallOutcomeKind.REFUSED, request=_booking())
    with pytest.raises(ValueError, match="only a call that needs the user"):
        CallOutcome("r", "c", CallOutcomeKind.DONE, deliberate_repeat=True)
    old = _remembered("m-old", MemorySource.USER_ASSERTED, "I live in Milan")
    with pytest.raises(ValueError, match="ride the request"):
        CallOutcome("r", "c", CallOutcomeKind.NEEDS_YOU, replaces=(old,))


# --- asking and the exact line (§2:3, §2:5-§2:8) -------------------------------------------------


async def test_a_named_call_is_asked_with_its_exact_line_and_recorded() -> None:
    earlier = _proposed(_SLOT)
    planned, _ = await _asked(
        asks=("1.1",),
        outcomes=(_needs_you(earlier.id, "c1", _booking(), deliberate_repeat=True),),
        rounds=(earlier,),
        text="I can book the table for 7pm tomorrow. Shall I?",
    )
    line = f'book — slot: "{_SLOT}"'
    assert planned.round.text == f"I can book the table for 7pm tomorrow. Shall I?\n\n{line}"
    assert planned.message == planned.round.text
    assert _FILLED not in planned.message
    (asked,) = planned.round.asked
    assert asked.part == 1
    assert asked.tool == _BOOK
    assert asked.values == {"slot": _SLOT, "client_reference": _FILLED}
    assert asked.binding is None
    assert asked.deliberate_repeat is True
    assert asked.replaces == ()


async def test_several_calls_are_numbered_by_part_in_the_order_named() -> None:
    """§2:6: each line's number is its call's part."""
    earlier = _proposed("2026-10-12 19:00", "2026-10-13 20:00")
    outcomes = (
        _needs_you(earlier.id, "c1", _booking("2026-10-12 19:00")),
        _needs_you(earlier.id, "c2", _booking("2026-10-13 20:00")),
    )
    planned, _ = await _asked(asks=("1.2", "1.1"), outcomes=outcomes, rounds=(earlier,))
    assert [one.part for one in planned.round.asked] == [1, 2]
    assert [one.values["slot"] for one in planned.round.asked] == [
        "2026-10-13 20:00",
        "2026-10-12 19:00",
    ]
    assert planned.round.text.splitlines()[-2:] == [
        '1. book — slot: "2026-10-13 20:00"',
        '2. book — slot: "2026-10-12 19:00"',
    ]


@pytest.mark.parametrize("name", ["9.9", "R1", "c1", "1.2", " "])
async def test_a_name_that_resolves_to_no_askable_call_is_dropped(name: str) -> None:
    """§2:3: a done call, an unknown reference and a provider id name nothing askable."""
    earlier = _proposed(_SLOT, "2026-10-13 20:00")
    outcomes = (
        _needs_you(earlier.id, "c1", _booking()),
        CallOutcome(earlier.id, "c2", CallOutcomeKind.DONE),
    )
    asks = (name,) if name.strip() else ()
    planned, _ = await _asked(asks=asks, outcomes=outcomes, rounds=(earlier,))
    assert planned.round.asked == ()
    assert planned.round.text == "Shall I book it?"


async def test_a_name_is_resolved_with_its_surrounding_space_ignored() -> None:
    earlier = _proposed(_SLOT)
    planned, _ = await _asked(
        asks=(" 1.1 ",), outcomes=(_needs_you(earlier.id, "c1", _booking()),), rounds=(earlier,)
    )
    assert [one.part for one in planned.round.asked] == [1]


async def test_two_names_for_one_call_ask_about_it_once() -> None:
    earlier = _proposed(_SLOT, _SLOT)
    outcomes = (
        _needs_you(earlier.id, "c1", _booking()),
        _needs_you(earlier.id, "c2", _booking()),
    )
    planned, _ = await _asked(asks=("1.1", "1.2"), outcomes=outcomes, rounds=(earlier,))
    assert len(planned.round.asked) == 1
    assert not planned.round.text.splitlines()[-1].startswith("1.")


async def test_a_message_with_no_text_is_the_exact_lines_alone() -> None:
    earlier = _proposed(_SLOT)
    planned, _ = await _asked(
        asks=("1.1",),
        outcomes=(_needs_you(earlier.id, "c1", _booking()),),
        rounds=(earlier,),
        text="  ",
    )
    assert planned.message == f'book — slot: "{_SLOT}"'


async def test_an_unrecordable_call_is_not_asked_about() -> None:
    """§2:8: a deliberate repeat of a capability safe to repeat makes no asked call."""
    earlier = _earlier(calls=(_call("c1", "web_search", query="rome"),))
    request = ActionRequest(tool=_SEARCH, parameters={"query": "rome"})
    outcome = _needs_you(earlier.id, "c1", request, deliberate_repeat=True)
    planned, _ = await _asked(asks=("1.1",), outcomes=(outcome,), rounds=(earlier,))
    assert planned.round.asked == ()


def test_the_exact_line_keeps_every_value_whole_on_one_line() -> None:
    """§8:9: an email's full text, its line breaks and quotes included, on its line."""
    body = 'Hi Sam,\n\nI\'m running "late".\nBest'
    mail = _tool(
        "book",
        id="send_email",
        capability="send_email",
        parameters_schema={
            "type": "object",
            "properties": {
                "to": {"type": "array", "items": {"type": "string"}},
                "body": {"type": "string"},
            },
        },
        system_supplied=(),
    )
    call = AskedCall(part=1, tool=mail, values={"to": ["sam@example.com"], "body": body})
    line = exact_line(call)
    assert "\n" not in line
    assert line == f'send_email — to: ["sam@example.com"]; body: {json.dumps(body)}'
    assert json.loads(line.split("body: ", 1)[1]) == body


def test_the_exact_line_leaves_out_what_the_hub_fills_and_its_own_marks() -> None:
    """§2:5: ``system_supplied``, the *looking for* and the *deliberate repeat* mark."""
    open_book = _tool("book", system_supplied=())
    call = AskedCall(
        part=2,
        tool=open_book,
        values={
            "slot": _SLOT,
            "client_reference": _FILLED,
            LOOKING_FOR: "a free table",
            DELIBERATE_REPEAT: True,
        },
    )
    assert exact_line(call, filled=("client_reference",), numbered=True) == (
        f'2. book — slot: "{_SLOT}"'
    )


# --- memory asks (§5:1, §5:5) --------------------------------------------------------------------


def _remember_request(statement: str) -> ActionRequest:
    return ActionRequest(
        tool=_REMEMBER, parameters={"statement": statement, "episode": "activation:a1"}
    )


async def test_a_remember_is_asked_with_its_statement_and_what_it_replaces() -> None:
    earlier = _earlier(calls=(_call("c1", "remember", statement="I live in Rome"),))
    old: SemanticMemory = _remembered("m-old", MemorySource.USER_ASSERTED, "I live in Milan")
    reported = _remembered("m-mail", MemorySource.EXTERNAL, "Lives at Via Roma 1, Milan")
    outcome = _needs_you(
        earlier.id, "c1", _remember_request("I live in Rome"), replaces=(old, reported)
    )
    planned, completer = await _asked(
        asks=("1.1",), outcomes=(outcome,), rounds=(earlier,), text="Shall I remember that?"
    )
    (asked,) = planned.round.asked
    assert asked.replaces == ("m-old", "m-mail")
    assert planned.round.text.splitlines()[-1] == (
        'remember — statement: "I live in Rome"; replacing: "I live in Milan", '
        '"Lives at Via Roma 1, Milan"'
    )
    replacing = _sent(completer)["rounds"][0]["calls"][0]["replacing"]
    assert replacing[0]["label"] == "M1"
    assert replacing[0]["fact"] == "I live in Milan"
    assert replacing[1] == {
        "item": (
            "a remembered fact resting on outside content, not shown to you; the exact "
            "details show it to the user"
        )
    }


# --- approved actions (§4:2) ---------------------------------------------------------------------

_PART: Final = QuestionPart(round="round:asking", part=1)


def _approved(tool: ToolDefinition = _BOOK, **values: Any) -> ApprovedAction:
    recorded = values or {"slot": _SLOT, "client_reference": _FILLED}
    return ApprovedAction(part=_PART, call=AskedCall(part=1, tool=tool, values=recorded))


async def _planned_with(*calls: Any, approved: tuple[ApprovedAction, ...]) -> tuple[Any, Any]:
    stage, completer, _ = _stage(RoundResponse(text="Booking it.", calls=calls))
    planned = await stage.plan(_inputs(capabilities=_TOOLS, approved=approved))
    return planned, completer


async def test_an_approved_action_is_shown_under_an_a_label_with_its_details() -> None:
    planned, completer = await _planned_with(approved=(_approved(),))
    assert _sent(completer)["approved_actions"] == [
        {
            "label": "A1",
            "capability": "book",
            "details": f'book — slot: "{_SLOT}"',
            "approved": "by the user's yes in this input, to the question that showed it",
        }
    ]
    assert (
        PlanningLabel(label="A1", kind=LabelKind.APPROVED_ACTION, id="round:asking#1")
        in planned.labels
    )
    (tool,) = (one for one in completer.last_call.tools if one.name == APPROVED_ACTION_TOOL)
    parameters = tool.model_dump()["parameters"]
    assert parameters["properties"][APPROVED_ACTION_ARGUMENT]["enum"] == ["A1"]
    assert parameters["required"] == [APPROVED_ACTION_ARGUMENT]
    assert LOOKING_FOR not in parameters["properties"]
    assert f"propose {APPROVED_ACTION_TOOL} naming its label" in _instruction(completer)


async def test_nothing_approved_offers_no_tool_and_no_section() -> None:
    planned, completer = await _planned_with(
        _call("c1", APPROVED_ACTION_TOOL, action="A1"), approved=()
    )
    assert "approved_actions" not in _sent(completer)
    assert all(one.name != APPROVED_ACTION_TOOL for one in completer.last_call.tools)
    assert APPROVED_ACTION_TOOL not in _instruction(completer)
    (refused,) = planned.refused
    assert refused.reason == "no capability of that name was offered"


async def test_an_approved_action_proposed_by_label_carries_the_recorded_values() -> None:
    """§4:2: code fills in the values; the hub's own are left for it to fill again."""
    recorded = ApprovedAction(
        part=_PART,
        call=AskedCall(
            part=1,
            tool=_BOOK,
            values={"slot": _SLOT, "client_reference": _FILLED},
            deliberate_repeat=True,
        ),
    )
    planned, _ = await _planned_with(
        _call("c1", APPROVED_ACTION_TOOL, action="A1"), approved=(recorded,)
    )
    (call,) = planned.calls
    assert call == PlannedCall(
        _call("c1", "book", slot=_SLOT), deliberate_repeat=True, approved_part=_PART
    )
    assert planned.round.calls == (_call("c1", APPROVED_ACTION_TOOL, action="A1"),)


@pytest.mark.parametrize(
    ("arguments", "reason"),
    [
        (
            {"action": "A1", "slot": "2026-12-31 23:00"},
            "an approved action is proposed by its label alone: its values are the ones the "
            "user approved",
        ),
        ({"action": "A7"}, "'A7' names nothing you were shown"),
        ({"action": 1}, "'action' names the action by its A label"),
        ({}, "'action' names the action by its A label"),
    ],
)
async def test_an_approved_action_is_proposed_by_its_label_alone(
    arguments: dict[str, Any], reason: str
) -> None:
    """Nothing planning sends beside the label changes the values (§4:2)."""
    planned, _ = await _planned_with(
        _call("c1", APPROVED_ACTION_TOOL, **arguments), approved=(_approved(),)
    )
    assert planned.calls == ()
    assert planned.refused == (RefusedCall(_call("c1", APPROVED_ACTION_TOOL, **arguments), reason),)


async def test_a_label_of_another_kind_names_no_approved_action() -> None:
    earlier = _earlier(calls=(_call("c1", "web_search", query="rome", looking_for="hotels"),))
    stage, _, _ = _stage(RoundResponse(calls=(_call("c2", APPROVED_ACTION_TOOL, action="R1"),)))
    planned = await stage.plan(
        _inputs(
            capabilities=_TOOLS,
            rounds=(earlier,),
            outcomes=(
                CallOutcome(earlier.id, "c1", CallOutcomeKind.DONE, result_id="res-1", result=1),
            ),
            approved=(_approved(),),
        )
    )
    (refused,) = planned.refused
    assert refused.reason == "'R1' names a result, not an approved action"


async def test_an_approved_read_that_may_carry_outside_text_says_what_it_looks_for() -> None:
    search = _approved(_SEARCH, query="hotels in rome")
    planned, completer = await _planned_with(
        _call("c1", APPROVED_ACTION_TOOL, action="A1"),
        _call("c2", APPROVED_ACTION_TOOL, action="A1", looking_for="a quiet one"),
        approved=(search,),
    )
    (tool,) = (one for one in completer.last_call.tools if one.name == APPROVED_ACTION_TOOL)
    assert LOOKING_FOR in tool.model_dump()["parameters"]["properties"]
    (refused,) = planned.refused
    assert refused.reason == f"{LOOKING_FOR!r} must say what you are looking for"
    (call,) = planned.calls
    assert call.looking_for == "a quiet one"
    assert call.call == _call("c2", "web_search", query="hotels in rome")
    assert call.approved_part == _PART


def test_an_approved_actions_call_is_the_one_its_part_names() -> None:
    with pytest.raises(ValueError, match="recorded under its part"):
        ApprovedAction(
            part=QuestionPart(round="round:asking", part=2),
            call=AskedCall(part=1, tool=_BOOK, values=_booking().parameters),
        )
