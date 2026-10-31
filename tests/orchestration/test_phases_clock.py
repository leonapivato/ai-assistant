"""Planning is not offered the clock, since its input carries ``now`` (#2942).

The acceptance line (#2815) is that a quick question, "what time is it?", is answered in
two model calls: understanding's, and one planning round. Offered the clock, planning
spent its first round calling it, and ADR-0315 §2:1 brought a second. The tool stays in
the registry (ADR-0048 §1); only planning's offer leaves it out, and a call naming it is
refused as any capability planning was not offered is.

The production composition's offer is pinned in ``tests/app/test_composition_phases.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from exchange_support import section, shown_text
from phases_support import chat_turn, phases_harness
from test_engine_phases import _BOOK
from understanding_support import STATED_PROPOSAL, understanding_stage

from ai_assistant.core.types import ProposedCall, RoundResponse
from ai_assistant.testing import FakeModelProvider, FakeToolCallingCompleter
from ai_assistant.tools import CURRENT_TIME

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import OfferedTool, PlanningExchange

_CLOCK: Final = str(CURRENT_TIME.capability)
_ANSWER: Final = "It's noon."


def _calls_the_clock_when_offered(
    _exchange: PlanningExchange, tools: Sequence[OfferedTool]
) -> RoundResponse:
    """A planner that reaches for the clock whenever it is offered, as #2942's did."""
    if any(one.name == _CLOCK for one in tools):
        return RoundResponse(
            text="Let me check the current time for you.",
            calls=(ProposedCall(call_id="c1", name=_CLOCK),),
        )
    return RoundResponse(text=_ANSWER)


async def test_what_time_is_it_takes_two_model_calls() -> None:
    """Understanding's call and one planning round, the clock registered but not offered."""
    understanding_model = FakeModelProvider(reply=STATED_PROPOSAL)
    completer = FakeToolCallingCompleter(response=_calls_the_clock_when_offered)
    harness = phases_harness(
        completer,
        phases={"capabilities": (_CLOCK, "remember", "book")},
        understanding=understanding_stage(model=understanding_model),
        tools=(_BOOK, CURRENT_TIME),
    )
    # ADR-0048 §1: the registry still holds the clock.
    assert [str(one.id) for one in await harness.invoker.find(_CLOCK)] == [str(CURRENT_TIME.id)]

    await chat_turn(harness, "what time is it?")

    assert len(understanding_model.calls) == 1
    (planning_round,) = completer.calls
    offered = {one.name for one in planning_round.tools}
    assert _CLOCK not in offered
    assert {"remember", "book"} <= offered
    # What planning answers from instead: its input carries the current time.
    assert section(planning_round.exchange.briefing, "## The situation").startswith("- Now: ")


async def test_a_clock_call_that_arrives_anyway_is_refused_as_not_offered() -> None:
    """No special case: it is refused as any capability planning was not offered is."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(ProposedCall(call_id="c1", name=_CLOCK),)),
        RoundResponse(text=_ANSWER),
    )
    harness = phases_harness(
        completer,
        phases={"capabilities": (_CLOCK, "remember", "book")},
        tools=(_BOOK, CURRENT_TIME),
    )

    await chat_turn(harness, "what time is it?")

    assert harness.invoker.invocations == []
    assert "no capability of that name was offered" in shown_text(completer.calls[-1])
