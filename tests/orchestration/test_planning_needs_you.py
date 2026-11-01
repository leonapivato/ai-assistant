"""Planning's side of asking for a yes, after the question path retired (ADR-0361 §2, §8:5).

Driven directly over the canonical ``FakeToolCallingCompleter``, with the helpers of
``test_planning``. A call that comes back needing the person's yes ran nothing, and its
outcome says to ask through ``request_approval``, or why nothing can be asked (§2:4-§2:5):
no message asks, no round records an asked call, and no tool runs an approved action of
a question's. The exact line a card and a ticket show is rendered by one renderer for
every capability (ADR-0321 §2:5, ADR-0361 §2:11).
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Final

import pytest
from exchange_support import reported
from test_planning import _call, _earlier, _inputs, _stage, _tool

from ai_assistant.core.types import (
    ActionRequest,
    PlanningRound,
    RequestedCall,
    RoundResponse,
)
from ai_assistant.orchestration.approvals import ALREADY_ON_A_CARD
from ai_assistant.orchestration.planning import (
    DELIBERATE_REPEAT,
    LOOKING_FOR,
    CallOutcome,
    CallOutcomeKind,
    exact_line,
)

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

_SLOT: Final = "2026-10-12 19:00"
_FILLED: Final = "ref-filled-by-the-hub"


def _needs_you(round_id: str, call_id: str, reason: str | None = None) -> CallOutcome:
    return CallOutcome(
        round_id,
        call_id,
        CallOutcomeKind.NEEDS_YOU,
        reason=reason or "the permission policy asks the user about this call",
    )


def _proposed(*slots: str) -> PlanningRound:
    """An earlier round that proposed one booking per slot, calls ``c1``, ``c2``…."""
    return _earlier(
        calls=tuple(_call(f"c{n}", "book", slot=slot) for n, slot in enumerate(slots, 1))
    )


async def _reported(
    outcome: CallOutcome, *, text: str = "Shall I book it?", **fields: Any
) -> tuple[Any, dict[str, Any]]:
    """A work whose first round proposes a booking, which comes back as ``outcome``.

    Returns:
        The work's second round, and what its report says came of the booking.
    """
    proposed = _proposed(_SLOT)
    stage, completer, _ = _stage(RoundResponse(calls=proposed.calls), RoundResponse(text=text))
    inputs = _inputs(capabilities=_TOOLS, **fields)
    first = await stage.plan(inputs)
    planned = await stage.plan(
        replace(
            inputs,
            work=first.work,
            rounds=(first.round,),
            labels=(*inputs.labels, *first.labels),
            outcomes=(replace(outcome, round_id=first.round.id),),
        )
    )
    return planned, reported(completer.calls[1], 0)[0]


# --- what a call needing a yes is shown as (ADR-0361 §2:4-§2:5) ---------------------------


async def test_a_call_needing_a_yes_is_asked_for_by_request_approval() -> None:
    """§2:4: it ran nothing, and is asked about through request_approval alone."""
    planned, shown = await _reported(_needs_you("r", "c1"), approvals=True, person_id="owner")
    assert shown == {
        "outcome": (
            "needs the person's yes, so nothing ran: to ask, call request_approval with this "
            "call's capability and the same arguments, and say in why what it does"
        ),
        "because": "the permission policy asks the user about this call",
    }
    assert planned.round.asked == ()


async def test_in_an_activation_that_is_no_persons_nothing_is_asked() -> None:
    """§2:5: no request can be written for no one."""
    _, shown = await _reported(_needs_you("r", "c1"), approvals=True)
    assert shown["outcome"] == (
        "needs the person's yes, and this activation is no person's, so it will not run and "
        "is not asked about"
    )


async def test_where_the_approvals_channel_is_not_wired_nothing_can_ask() -> None:
    """§2:4, §4:10: no input approves anything, so with no card nothing can ask."""
    planned, shown = await _reported(_needs_you("r", "c1"), person_id="owner")
    assert shown["outcome"] == "needs a yes, and it cannot be asked about, so it will not run"
    assert "ask_as" not in shown
    assert planned.round.asked == ()


async def test_a_call_a_pending_request_holds_says_it_waits_on_its_card() -> None:
    """§2:8: an identical call already on a card is not asked about again."""
    _, shown = await _reported(
        _needs_you("r", "c1", ALREADY_ON_A_CARD), approvals=True, person_id="owner"
    )
    assert shown == {"outcome": ALREADY_ON_A_CARD}


async def test_a_deny_is_never_asked_about_and_is_said_plainly() -> None:
    """ADR-0321 §2:10's second case, as ADR-0361 §2:3 keeps it: the refused outcome says so."""
    refused = CallOutcome("r", "c1", CallOutcomeKind.REFUSED, reason="the policy denies it")
    planned, shown = await _reported(refused, approvals=True, person_id="owner")
    assert shown["outcome"].startswith(
        "refused before it ran, so nothing in it ran, and no yes lets it run: never ask about it"
    )
    assert planned.round.asked == ()


async def test_no_round_records_an_asked_call_and_no_question_tool_is_offered() -> None:
    """§8:5: the round records no asked call, and only a ticket's tool runs an approval."""
    planned, _ = await _reported(_needs_you("r", "c1"), approvals=True, person_id="owner")
    assert planned.round.asked == ()
    assert planned.work is not None
    offered = {one.name: one for one in planned.work.tools}
    assert "run_approved_action" not in offered
    assert "run_approved" in offered


# --- the exact line (ADR-0321 §2:5, §2:7) --------------------------------------------------


_BREAKS: Final = ("\n", "\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029")


@pytest.mark.parametrize("brk", _BREAKS, ids=[f"U+{ord(one):04X}" for one in _BREAKS])
@pytest.mark.parametrize("where", ["name", "value", "replaced"])
def test_no_character_breaks_an_exact_line(brk: str, where: str) -> None:
    """§2:5: one line per call, whatever a name, value or statement holds.

    Each text still decodes, from the line, to exactly what the call carries.
    """
    text = f"extra{brk}2. book — slot"
    replacing: tuple[str, ...] = ()
    if where == "name":
        values = {"slot": _SLOT, "client_reference": _FILLED, text: "20:00"}
        call = RequestedCall(tool=_BOOK, values=values)
    elif where == "value":
        call = RequestedCall(tool=_BOOK, values={"slot": text, "client_reference": _FILLED})
    else:
        request = _remember_request("I live in Rome")
        call = RequestedCall(tool=request.tool, values=request.parameters)
        replacing = (text,)
    (line,) = exact_line(call, replacing=replacing).splitlines()
    assert brk not in line
    quoted = line[line.index('"extra') : line.index('slot"') + len('slot"')]
    assert json.loads(quoted) == text


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
    call = RequestedCall(tool=mail, values={"to": ["sam@example.com"], "body": body})
    line = exact_line(call)
    assert "\n" not in line
    assert line == f'send_email — to: ["sam@example.com"]; body: {json.dumps(body)}'
    assert json.loads(line.split("body: ", 1)[1]) == body


def test_the_exact_line_leaves_out_what_the_hub_fills_and_its_own_marks() -> None:
    """§2:5: ``system_supplied``, the *looking for* and the *deliberate repeat* mark."""
    open_book = _tool("book", system_supplied=())
    call = RequestedCall(
        tool=open_book,
        values={
            "slot": _SLOT,
            "client_reference": _FILLED,
            LOOKING_FOR: "a free table",
            DELIBERATE_REPEAT: True,
        },
    )
    assert exact_line(call, filled=("client_reference",)) == f'book — slot: "{_SLOT}"'


def _remember_request(statement: str) -> ActionRequest:
    return ActionRequest(
        tool=_REMEMBER, parameters={"statement": statement, "episode": "activation:a1"}
    )
