"""Planning's side of the person model's calls (ADR-0338 §3:6, §8:6; ADR-0321 §2:5, §2:7).

The stage alone, over the canonical ``FakeToolCallingCompleter``: the current time is
given in the person's zone where their profile sets one, and in the hub's default where
it is not set or there is no person (§3:6, §3:9); and the exact line of a ``pin`` or an
``unpin`` shows the memory's wording in its argument's place (§8:6). §2:7's test reads
that wording as the argument: every argument is shown, the memory by its words.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from exchange_support import section
from test_planning_person import _inputs as _person_inputs
from test_planning_person import _sent
from test_planning_person import _stage as _person_stage

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    Profile,
    RequestedCall,
)
from ai_assistant.orchestration.person_block import PersonBlock
from ai_assistant.orchestration.person_calls import PIN, SET_PROFILE, UNPIN
from ai_assistant.orchestration.planning import exact_line

if TYPE_CHECKING:
    from ai_assistant.core.types import FrozenJson, ToolDefinition

pytestmark = pytest.mark.anyio


def _block(**profile: str) -> PersonBlock:
    return PersonBlock(person_id=OWNER_PERSON_ID, profile=Profile(**profile))


# --- the person's zone on planning's clock (§3:6) ---------------------------------------


def _now_line(briefing: str) -> str:
    """The situation's first line: the current time, and the zone every time is in."""
    (now,) = [
        line
        for line in section(briefing, "## The situation").split("\n")
        if line.startswith("- Now:")
    ]
    return now


async def test_the_current_time_is_given_in_the_persons_zone_where_it_is_set() -> None:
    stage, completer, _ = _person_stage()

    await stage.plan(_person_inputs(person=_block(time_zone="America/New_York")))

    assert _now_line(_sent(completer)) == (
        "- Now: Wednesday 21 October 2026, 5:00 am, in the owner's time zone "
        "(America/New_York). Every time below is in this zone."
    )


@pytest.mark.parametrize("person", [_block(), None], ids=["zone-not-set", "no-person"])
async def test_the_hubs_zone_is_used_where_the_persons_is_not_set_or_there_is_none(
    person: PersonBlock | None,
) -> None:
    """§3:6, §3:9: ``Settings.timezone``, the hub's default, which the stage is built with."""
    stage, completer, _ = _person_stage()

    await stage.plan(_person_inputs(person=person))

    assert _now_line(_sent(completer)).startswith(
        "- Now: Wednesday 21 October 2026, 10:00 am, in the hub's time zone (Europe/Lisbon)."
    )


async def test_a_zone_that_does_not_resolve_falls_back_to_the_hubs() -> None:
    """The store validates every write (§3:2); a zone that slipped past it is not used."""
    stage, completer, _ = _person_stage()

    await stage.plan(_person_inputs(person=_block(time_zone="Mars/Olympus")))

    now = _now_line(_sent(completer))
    assert "in the hub's time zone (Europe/Lisbon)" in now
    assert "Mars/Olympus" not in _sent(completer)


# --- the exact line (§8:6; ADR-0321 §2:5, §2:7) -------------------------------------------


def test_the_exact_line_shows_every_argument_a_person_model_call_sends() -> None:
    """ADR-0321 §2:7 for the three, a pin's and an unpin's memory read as its wording."""
    sent: list[tuple[ToolDefinition, dict[str, FrozenJson]]] = [
        (SET_PROFILE, {"field": "time_zone", "value": "Europe/Lisbon"}),
        (PIN, {"memory": "m:diet"}),
        (UNPIN, {"memory": "m:diet"}),
    ]
    for tool, values in sent:
        call = RequestedCall(tool=tool, values=values)
        worded = {"memory": "Eats no meat."} if "memory" in values else None
        line = exact_line(call, worded=worded)
        shown = {**values, **(worded or {})}
        for argument, value in shown.items():
            assert f"{argument}: {json.dumps(value, ensure_ascii=False)}" in line, (tool.id, line)
        if worded is not None:
            assert "m:diet" not in line
