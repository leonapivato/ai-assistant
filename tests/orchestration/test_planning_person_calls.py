"""Planning's side of the person model's calls (ADR-0338 §3:6, §8:6; ADR-0321 §2:5, §2:7).

The stage alone, over the canonical ``FakeToolCallingCompleter``: the current time is
given in the person's zone where their profile sets one, and in the hub's default where
it is not set or there is no person (§3:6, §3:9); and the exact line of a ``pin`` or an
``unpin`` shows the memory's wording in its argument's place, while the asked call
records the id the call sends (§8:6). §2:7's test reads that wording as the argument:
every argument is shown, the memory by its words.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from test_planning import _earlier, _inputs, _stage
from test_planning_person import _inputs as _person_inputs
from test_planning_person import _sent
from test_planning_person import _stage as _person_stage

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ActionRequest,
    AskedCall,
    Profile,
    ProposedCall,
    RoundResponse,
)
from ai_assistant.orchestration.person_block import PersonBlock
from ai_assistant.orchestration.person_calls import PERSON_MODEL_CALLS, PIN, SET_PROFILE, UNPIN
from ai_assistant.orchestration.planning import CallOutcome, CallOutcomeKind, exact_line

if TYPE_CHECKING:
    from ai_assistant.core.types import FrozenJson, ToolDefinition

pytestmark = pytest.mark.anyio


def _block(**profile: str) -> PersonBlock:
    return PersonBlock(person_id=OWNER_PERSON_ID, profile=Profile(**profile))


# --- the person's zone on planning's clock (§3:6) ---------------------------------------


async def test_the_current_time_is_given_in_the_persons_zone_where_it_is_set() -> None:
    stage, completer, _ = _person_stage()

    await stage.plan(_person_inputs(person=_block(time_zone="America/New_York")))

    sent = _sent(completer)
    assert sent["now"] == "2026-10-21T05:00:00-04:00"
    assert sent["time_zone"] == "America/New_York"
    assert sent["person"]["profile"]["time_zone"]["value"] == "America/New_York"


@pytest.mark.parametrize("person", [_block(), None], ids=["zone-not-set", "no-person"])
async def test_the_hubs_zone_is_used_where_the_persons_is_not_set_or_there_is_none(
    person: PersonBlock | None,
) -> None:
    """§3:6, §3:9: ``Settings.timezone``, the hub's default, which the stage is built with."""
    stage, completer, _ = _person_stage()

    await stage.plan(_person_inputs(person=person))

    sent = _sent(completer)
    assert sent["now"] == "2026-10-21T10:00:00+01:00"
    assert sent["time_zone"] == "Europe/Lisbon"


async def test_a_zone_that_does_not_resolve_falls_back_to_the_hubs() -> None:
    """The store validates every write (§3:2); a zone that slipped past it is not used."""
    stage, completer, _ = _person_stage()

    await stage.plan(_person_inputs(person=_block(time_zone="Mars/Olympus")))

    assert _sent(completer)["time_zone"] == "Europe/Lisbon"


# --- the exact line (§8:6; ADR-0321 §2:5, §2:7) -------------------------------------------


def _needing_you(
    call_id: str,
    tool_index: int,
    parameters: dict[str, FrozenJson],
    worded: tuple[tuple[str, str], ...] = (),
) -> CallOutcome:
    return CallOutcome(
        "round:earlier",
        call_id,
        CallOutcomeKind.NEEDS_YOU,
        request=ActionRequest(tool=PERSON_MODEL_CALLS[tool_index], parameters=parameters),
        worded=worded,
    )


async def test_a_pins_question_shows_the_memorys_wording_and_records_its_id() -> None:
    calls = (
        ProposedCall(call_id="c1", name="pin", arguments={"memory": "M1"}),
        ProposedCall(call_id="c2", name="unpin", arguments={"memory": "M2"}),
        ProposedCall(call_id="c3", name="set_profile", arguments={"field": "address"}),
    )
    outcomes = (
        _needing_you("c1", 1, {"memory": "m:diet"}, worded=(("memory", "Eats no meat."),)),
        _needing_you("c2", 2, {"memory": "m:tea"}, worded=(("memory", 'Drinks "green" tea.'),)),
        _needing_you("c3", 0, {"field": "address", "value": None}),
    )
    stage, _, _ = _stage(RoundResponse(text="Shall I?", asks=("1.1", "1.2", "1.3")))

    planned = await stage.plan(
        _inputs(
            capabilities=PERSON_MODEL_CALLS,
            rounds=(_earlier(calls=calls),),
            outcomes=outcomes,
        )
    )

    assert planned.round.text.splitlines()[-3:] == [
        '1. pin — memory: "Eats no meat."',
        '2. unpin — memory: "Drinks \\"green\\" tea."',
        '3. set_profile — field: "address"; value: null',
    ]
    # The asked call records the values the call sends, the memory by its id (§2:8).
    assert [dict(one.values) for one in planned.round.asked] == [
        {"memory": "m:diet"},
        {"memory": "m:tea"},
        {"field": "address", "value": None},
    ]


async def test_a_pin_handed_on_with_no_request_is_not_asked_about() -> None:
    """A pin whose wording could not be shown is unaskable: the glue hands it on so."""
    calls = (ProposedCall(call_id="c1", name="pin", arguments={"memory": "M1"}),)
    outcomes = (CallOutcome("round:earlier", "c1", CallOutcomeKind.NEEDS_YOU),)
    stage, _, _ = _stage(RoundResponse(text="Shall I?", asks=("1.1",)))

    planned = await stage.plan(
        _inputs(capabilities=(PIN,), rounds=(_earlier(calls=calls),), outcomes=outcomes)
    )

    assert planned.round.asked == ()
    assert "pin —" not in planned.round.text


def test_the_exact_line_shows_every_argument_a_person_model_call_sends() -> None:
    """ADR-0321 §2:7 for the three, a pin's and an unpin's memory read as its wording."""
    sent: list[tuple[ToolDefinition, dict[str, FrozenJson]]] = [
        (SET_PROFILE, {"field": "time_zone", "value": "Europe/Lisbon"}),
        (PIN, {"memory": "m:diet"}),
        (UNPIN, {"memory": "m:diet"}),
    ]
    for tool, values in sent:
        call = AskedCall(part=1, tool=tool, values=values)
        worded = {"memory": "Eats no meat."} if "memory" in values else None
        line = exact_line(call, worded=worded)
        shown = {**values, **(worded or {})}
        for argument, value in shown.items():
            assert f"{argument}: {json.dumps(value, ensure_ascii=False)}" in line, (tool.id, line)
        if worded is not None:
            assert "m:diet" not in line


def test_only_a_call_that_needs_you_carries_a_wording_and_only_with_its_request() -> None:
    with pytest.raises(ValueError, match="only a call that needs the user"):
        CallOutcome("r", "c", CallOutcomeKind.DONE, worded=(("memory", "Eats no meat."),))
    with pytest.raises(ValueError, match="rides the request"):
        CallOutcome("r", "c", CallOutcomeKind.NEEDS_YOU, worded=(("memory", "Eats no meat."),))
