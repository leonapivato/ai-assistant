"""Shared conformance suite for the ToolCallingCompleter Protocol (ADR-0307 §10).

Every ``ToolCallingCompleter`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`ToolCallingCompleterContract`, overrides the ``completer`` fixture, and
implements :meth:`ToolCallingCompleterContract.world`, which builds a subject
scripted to answer with one :class:`RoundResponse` and reports what reached the
model underneath it. What plays the script is the implementation's
business: the canonical fake is its own script, and the provider-backed
implementation stands up a programmable pydantic-ai model.

The suite asserts what is universal to the seam: which requests are refused before
any model is contacted (ADR-0066 §1, ADR-0307 §2:6), that a round comes back in its
three parts with nothing lost or invented (ADR-0315 §3:1), that the notes are a part
of the response and never a call (ADR-0315 §3:2, §3:3), and that the offered tools and
the rendered request reach the model as given.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import pytest

from ai_assistant.core.errors import ModelError
from ai_assistant.core.protocols import ToolCallingCompleter
from ai_assistant.core.types import (
    Message,
    OfferedTool,
    ProposedCall,
    Role,
    RoundResponse,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: One conversation turn as the model saw it: its role and its text.
type Turn = tuple[Role, str]

#: One offered tool as the model saw it: its name, description and schema.
type SeenTool = tuple[str, str, Mapping[str, object]]

#: The shapes ADR-0066 §1's precondition refuses, as role sequences.
_REFUSED_SHAPES = [
    pytest.param([], id="empty"),
    pytest.param([Role.USER, Role.ASSISTANT], id="ends-on-assistant"),
    pytest.param([Role.ASSISTANT], id="lone-assistant"),
]


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
        """The conversation each contact carried, oldest contact first."""
        ...

    @property
    def offered(self) -> tuple[tuple[SeenTool, ...], ...]:
        """The capabilities each contact offered, without any tool of the subject's own."""
        ...


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


def _request() -> list[Message]:
    return [
        Message(role=Role.SYSTEM, content="You plan one round."),
        Message(role=Role.USER, content='{"understanding": "the user wants the weather"}'),
    ]


def _history(roles: Sequence[Role]) -> list[Message]:
    return [Message(role=role, content=f"{role.value} turn") for role in roles]


def _full_round() -> RoundResponse:
    return RoundResponse(
        text="Looking that up now.",
        calls=(
            ProposedCall(
                call_id="call-1",
                name="web_search",
                arguments={"query": "weather Lisbon", "looking_for": "tomorrow's forecast"},
            ),
            ProposedCall(call_id="call-2", name="remember", arguments={"fact": "in Lisbon"}),
        ),
        notes="The user is travelling; check the forecast before suggesting plans.",
    )


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

    async def test_an_empty_request_is_refused(self, completer: ToolCallingCompleter) -> None:
        with pytest.raises(ModelError) as caught:
            await completer.respond([], [_search_tool()])
        assert not caught.value.retryable
        assert not caught.value.routable

    @pytest.mark.parametrize("roles", _REFUSED_SHAPES)
    async def test_a_malformed_history_is_refused_before_the_model(self, roles: list[Role]) -> None:
        scripted = self.world(_full_round())
        with pytest.raises(ModelError) as caught:
            await scripted.completer.respond(_history(roles), [_search_tool()])
        assert not caught.value.retryable
        assert not caught.value.routable
        assert scripted.attempts == 0

    async def test_a_tool_turn_is_refused_because_a_round_is_asked_afresh(self) -> None:
        scripted = self.world(_full_round())
        history = [*_request(), Message(role=Role.TOOL, content="result", name="web_search")]
        history.append(Message(role=Role.USER, content="and?"))
        with pytest.raises(ModelError) as caught:
            await scripted.completer.respond(history, [_search_tool()])
        assert not caught.value.retryable
        assert not caught.value.routable
        assert scripted.attempts == 0

    async def test_two_tools_of_one_name_are_refused_before_the_model(self) -> None:
        scripted = self.world(_full_round())
        with pytest.raises(ModelError) as caught:
            await scripted.completer.respond(_request(), [_search_tool(), _search_tool()])
        assert not caught.value.retryable
        assert not caught.value.routable
        assert scripted.attempts == 0

    async def test_a_round_comes_back_in_its_three_parts(self) -> None:
        scripted = self.world(_full_round())
        response = await scripted.completer.respond(_request(), [_search_tool(), _remember_tool()])
        assert response == _full_round()
        assert scripted.attempts == 1

    async def test_the_notes_are_never_calls(self) -> None:
        only_notes = RoundResponse(text="", notes="nothing to do yet")
        response = await self.world(only_notes).completer.respond(_request(), [_search_tool()])
        assert response.calls == ()
        assert response.notes == "nothing to do yet"

    async def test_a_round_of_text_alone_carries_no_calls_or_notes(self) -> None:
        response = await self.world(RoundResponse(text="It is sunny.")).completer.respond(
            _request(), [_search_tool()]
        )
        assert response == RoundResponse(text="It is sunny.")

    async def test_a_round_of_calls_alone_has_empty_text(self) -> None:
        calls_only = RoundResponse(
            calls=(
                ProposedCall(
                    call_id="c", name="web_search", arguments={"query": "q", "looking_for": "l"}
                ),
            )
        )
        response = await self.world(calls_only).completer.respond(_request(), [_search_tool()])
        assert response.text == ""
        assert response.calls == calls_only.calls

    async def test_the_offered_tools_reach_the_model_as_given(self) -> None:
        scripted = self.world(RoundResponse(text="ok"))
        tools = [_search_tool(), _remember_tool()]
        await scripted.completer.respond(_request(), tools)
        assert scripted.offered == (
            tuple((tool.name, tool.description, tool.model_dump()["parameters"]) for tool in tools),
        )

    async def test_no_tools_is_an_admissible_round(self) -> None:
        scripted = self.world(RoundResponse(text="Nothing to call."))
        response = await scripted.completer.respond(_request(), [])
        assert response == RoundResponse(text="Nothing to call.")
        assert scripted.offered == ((),)

    async def test_the_rendered_request_reaches_the_model_as_given(self) -> None:
        scripted = self.world(RoundResponse(text="ok"))
        request = _request()
        await scripted.completer.respond(request, [_search_tool()])
        assert scripted.observed == (tuple((m.role, m.content) for m in request),)

    async def test_a_caller_mutating_its_lists_afterwards_changes_nothing_observed(self) -> None:
        scripted = self.world(RoundResponse(text="ok"))
        request = _request()
        tools = [_search_tool()]
        expected = tuple((m.role, m.content) for m in request)
        await scripted.completer.respond(request, tools)
        request.append(Message(role=Role.USER, content="added later"))
        tools.clear()
        assert scripted.observed == (expected,)
        assert len(scripted.offered[0]) == 1
