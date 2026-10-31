"""Shared conformance suite for the ToolCallingCompleter Protocol (ADR-0356 §5 to §7, §13).

Every ``ToolCallingCompleter`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`ToolCallingCompleterContract`, overrides the ``completer`` fixture, and
implements :meth:`ToolCallingCompleterContract.world`, which builds a subject
scripted to answer with one :class:`RoundResponse` and reports what reached the
model underneath it. What plays the script is the implementation's
business: the canonical fake is its own script, and the provider-backed
implementation stands up a programmable pydantic-ai model.

The suite asserts what is universal to the seam: which requests are refused before
any model is contacted, that a round comes back in its parts, its text and its calls,
with nothing lost or invented (§7:1), that no tool name is reserved (§7:4), that the
offered tools reach the model as given, and that the exchange reaches it whole and in
order: the instruction, the briefing, then each earlier response and its report, the
results under their call ids and then the news (§5:1, §5:3). An earlier response with no
continuation, or with one another model wrote, is sent and answered (§6:3). What a
continuation holds is the implementation's (§6:1), so the suite compares a response's
text and calls and never its continuation.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Protocol

import pytest

from ai_assistant.core.errors import ModelError
from ai_assistant.core.protocols import ToolCallingCompleter
from ai_assistant.core.types import (
    CallResult,
    ExchangeStep,
    OfferedTool,
    PlanningExchange,
    ProposedCall,
    RoundContinuation,
    RoundReport,
    RoundResponse,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

#: One turn's part as the model saw it, in the provider's terms but named by this suite:
#: ``("system", text)``, ``("user", text)``, ``("text", text)`` for a response's text,
#: ``("call", id, name, arguments as sorted JSON)`` and ``("result", id, text)``.
type Turn = tuple[str, ...]

#: One offered tool as the model saw it: its name, description and schema.
type SeenTool = tuple[str, str, Mapping[str, object]]


class ToolCallingWorld(Protocol):
    """A subject scripted with one response, and what reached the model under it."""

    @property
    def completer(self) -> ToolCallingCompleter:
        """The subject under test."""
        ...

    @property
    def attempts(self) -> int:
        """How many times the model underneath was contacted."""
        ...

    @property
    def observed(self) -> tuple[tuple[Turn, ...], ...]:
        """The parts each contact carried, oldest contact first, as :data:`Turn` values."""
        ...

    @property
    def offered(self) -> tuple[tuple[SeenTool, ...], ...]:
        """The capabilities each contact offered."""
        ...


def call_turn(call: ProposedCall) -> Turn:
    """A call as :data:`Turn` names it."""
    arguments = json.dumps(call.model_dump(mode="json")["arguments"], sort_keys=True)
    return ("call", call.call_id, call.name, arguments)


def exchange_turns(exchange: PlanningExchange) -> tuple[Turn, ...]:
    """What the model is to see of ``exchange``, in order (ADR-0356 §5:1, §5:3, §13)."""
    turns: list[Turn] = [("system", exchange.instruction), ("user", exchange.briefing)]
    for step in exchange.steps:
        if step.response.text:
            turns.append(("text", step.response.text))
        turns.extend(call_turn(call) for call in step.response.calls)
        turns.extend(("result", one.call_id, one.text) for one in step.report.results)
        turns.append(("user", step.report.news))
    return tuple(turns)


def _search_tool() -> OfferedTool:
    return OfferedTool(
        name="web_search",
        description="Search the web.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "looking_for": {"type": "string"},
            },
            "required": ["query", "looking_for"],
        },
    )


def _remember_tool() -> OfferedTool:
    return OfferedTool(
        name="remember",
        description="Remember a fact about the user.",
        parameters={"type": "object", "properties": {"fact": {"type": "string"}}},
    )


def _briefing() -> PlanningExchange:
    return PlanningExchange(
        instruction="You plan one round.",
        briefing="# The stimulus\nthe user wants the weather",
    )


def _search(call_id: str, query: str) -> ProposedCall:
    return ProposedCall(
        call_id=call_id,
        name="web_search",
        arguments={"query": query, "looking_for": "the forecast"},
    )


def _with_steps(*continuations: RoundContinuation | None) -> PlanningExchange:
    """A briefing and one step for each continuation, each step's call its own."""
    steps = tuple(
        ExchangeStep(
            response=RoundResponse(
                text=f"Looking up day {index}.",
                calls=(_search(f"call-{index}", f"weather day {index}"),),
                continuation=continuation,
            ),
            report=RoundReport(
                results=(CallResult(call_id=f"call-{index}", text=f"Day {index}: sunny."),),
                news="Nothing has changed since.",
            ),
        )
        for index, continuation in enumerate(continuations, start=1)
    )
    return _briefing().model_copy(update={"steps": steps})


def _full_round() -> RoundResponse:
    return RoundResponse(
        text="The user is travelling; check the forecast before suggesting plans.",
        calls=(
            _search("call-1", "weather Lisbon"),
            ProposedCall(call_id="call-2", name="remember", arguments={"fact": "in Lisbon"}),
        ),
    )


def _parts(response: RoundResponse) -> tuple[str, tuple[ProposedCall, ...]]:
    """A response's text and calls: what the suite compares, never its continuation."""
    return response.text, response.calls


class ToolCallingCompleterContract:
    """Obligations every ``ToolCallingCompleter`` implementation must meet."""

    @pytest.fixture
    def completer(self) -> ToolCallingCompleter:
        """Override: the subject, unscripted."""
        raise NotImplementedError

    def world(self, response: RoundResponse) -> ToolCallingWorld:
        """Override: a subject scripted to answer with ``response``, and its model."""
        raise NotImplementedError

    def test_satisfies_the_protocol(self, completer: ToolCallingCompleter) -> None:
        assert isinstance(completer, ToolCallingCompleter)
        assert isinstance(self.world(RoundResponse()).completer, ToolCallingCompleter)

    async def test_two_tools_of_one_name_are_refused_before_the_model(self) -> None:
        scripted = self.world(_full_round())
        with pytest.raises(ModelError) as caught:
            await scripted.completer.respond(_briefing(), [_search_tool(), _search_tool()])
        assert not caught.value.retryable
        assert not caught.value.routable
        assert scripted.attempts == 0

    async def test_a_round_comes_back_as_its_text_and_its_calls(self) -> None:
        scripted = self.world(_full_round())
        response = await scripted.completer.respond(_briefing(), [_search_tool(), _remember_tool()])
        assert _parts(response) == _parts(_full_round())
        assert scripted.attempts == 1

    async def test_a_round_of_text_alone_carries_no_calls(self) -> None:
        response = await self.world(RoundResponse(text="Nothing to do yet.")).completer.respond(
            _briefing(), [_search_tool()]
        )
        assert _parts(response) == ("Nothing to do yet.", ())

    async def test_a_round_of_calls_alone_has_empty_text(self) -> None:
        calls_only = RoundResponse(calls=(_search("c", "q"),))
        response = await self.world(calls_only).completer.respond(_briefing(), [_search_tool()])
        assert response.text == ""
        assert response.calls == calls_only.calls

    async def test_no_tool_name_is_reserved(self) -> None:
        """ADR-0356 §7:4: a tool named ``planning_round`` is offered like any other."""
        named = OfferedTool(
            name="planning_round", description="An ordinary tool.", parameters={"type": "object"}
        )
        call = ProposedCall(call_id="c", name="planning_round", arguments={})
        scripted = self.world(RoundResponse(calls=(call,)))
        response = await scripted.completer.respond(_briefing(), [named])
        assert response.calls == (call,)
        assert scripted.offered == ((("planning_round", "An ordinary tool.", {"type": "object"}),),)

    async def test_the_offered_tools_reach_the_model_as_given(self) -> None:
        scripted = self.world(RoundResponse(text="ok"))
        tools = [_search_tool(), _remember_tool()]
        await scripted.completer.respond(_briefing(), tools)
        assert scripted.offered == (
            tuple((tool.name, tool.description, tool.model_dump()["parameters"]) for tool in tools),
        )

    async def test_no_tools_is_an_admissible_round(self) -> None:
        scripted = self.world(RoundResponse(text="Nothing to call."))
        response = await scripted.completer.respond(_briefing(), [])
        assert _parts(response) == ("Nothing to call.", ())
        assert scripted.offered == ((),)

    async def test_a_briefing_alone_reaches_the_model_as_the_instruction_and_the_briefing(
        self,
    ) -> None:
        scripted = self.world(RoundResponse(text="ok"))
        await scripted.completer.respond(_briefing(), [_search_tool()])
        assert scripted.observed == (
            (("system", "You plan one round."), ("user", _briefing().briefing)),
        )

    async def test_each_step_reaches_the_model_after_the_briefing_in_order(self) -> None:
        """§5:1, §5:3: each response, then its results under their ids, then the news."""
        scripted = self.world(RoundResponse(text="ok"))
        exchange = _with_steps(None, None)
        await scripted.completer.respond(exchange, [_search_tool()])
        assert scripted.observed == (exchange_turns(exchange),)

    async def test_an_earlier_response_without_a_continuation_is_sent_and_answered(
        self,
    ) -> None:
        scripted = self.world(RoundResponse(text="done"))
        response = await scripted.completer.respond(_with_steps(None), [_search_tool()])
        assert _parts(response) == ("done", ())
        assert scripted.attempts == 1

    async def test_an_earlier_response_another_model_wrote_is_sent_and_answered(
        self,
    ) -> None:
        """§6:3: a continuation naming another model is no obstacle to the round."""
        foreign = RoundContinuation(model="elsewhere:another-model", parts={"opaque": [1, 2]})
        scripted = self.world(RoundResponse(text="done"))
        exchange = _with_steps(foreign)
        response = await scripted.completer.respond(exchange, [_search_tool()])
        assert _parts(response) == ("done", ())
        assert scripted.observed == (exchange_turns(exchange),)

    async def test_a_caller_mutating_its_tools_afterwards_changes_nothing_observed(
        self,
    ) -> None:
        scripted = self.world(RoundResponse(text="ok"))
        tools = [_search_tool()]
        await scripted.completer.respond(_briefing(), tools)
        tools.clear()
        assert len(scripted.offered[0]) == 1
