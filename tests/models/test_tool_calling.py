"""``PydanticAIToolCallingCompleter``: the shared contract, and what it adds.

The binding runs the suite over a pydantic-ai ``FunctionModel``, which is the world:
it plays the scripted round back in the provider's native shape (text, tool calls and
the reserved round tool) and records what each request carried. Everything is
offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from tool_calling_completer_contract import SeenTool, ToolCallingCompleterContract, Turn

from ai_assistant.core.errors import ModelError, ModelRateLimitError, ModelResponseError
from ai_assistant.core.types import Message, OfferedTool, Role, RoundResponse
from ai_assistant.models import PydanticAIToolCallingCompleter
from ai_assistant.models.tool_calling import ROUND_TOOL

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic_ai.messages import ModelMessage, ModelResponsePart

    from ai_assistant.core.protocols import ToolCallingCompleter


def _turns(messages: list[ModelMessage]) -> tuple[Turn, ...]:
    """The request as our roles, read back off pydantic-ai's history."""
    turns: list[Turn] = []
    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, SystemPromptPart):
                    turns.append((Role.SYSTEM, part.content))
                elif isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    turns.append((Role.USER, part.content))
        else:
            turns.extend(
                (Role.ASSISTANT, part.content)
                for part in message.parts
                if isinstance(part, TextPart)
            )
    return tuple(turns)


def _native(response: RoundResponse) -> ModelResponse:
    """A scripted round in the provider's native shape, as this module reads it back."""
    parts: list[ModelResponsePart] = []
    if response.text:
        parts.append(TextPart(response.text))
    parts.extend(
        ToolCallPart(call.name, call.model_dump()["arguments"], tool_call_id=call.call_id)
        for call in response.calls
    )
    if response.notes is not None or response.another_round:
        arguments: dict[str, Any] = {"another_round": response.another_round}
        if response.notes is not None:
            arguments["notes"] = response.notes
        parts.append(ToolCallPart(ROUND_TOOL, arguments, tool_call_id="round"))
    return ModelResponse(parts=parts)


@dataclass
class _ModelWorld:
    """A ``FunctionModel`` playing one round back, and what each request carried."""

    script: Callable[[], ModelResponse]
    requests: list[tuple[Turn, ...]] = field(default_factory=list)
    tools: list[tuple[SeenTool, ...]] = field(default_factory=list)
    round_tools: list[int] = field(default_factory=list)

    def answer(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.requests.append(_turns(messages))
        self.tools.append(
            tuple(
                (tool.name, tool.description or "", tool.parameters_json_schema)
                for tool in info.function_tools
                if tool.name != ROUND_TOOL
            )
        )
        self.round_tools.append(sum(tool.name == ROUND_TOOL for tool in info.function_tools))
        return self.script()

    @property
    def completer(self) -> ToolCallingCompleter:
        return PydanticAIToolCallingCompleter(default_model=FunctionModel(self.answer))

    @property
    def attempts(self) -> int:
        return len(self.requests)

    @property
    def observed(self) -> tuple[tuple[Turn, ...], ...]:
        return tuple(self.requests)

    @property
    def offered(self) -> tuple[tuple[SeenTool, ...], ...]:
        return tuple(self.tools)


def _world(response: RoundResponse) -> _ModelWorld:
    return _ModelWorld(script=lambda: _native(response))


class TestPydanticAIToolCallingCompleterContract(ToolCallingCompleterContract):
    """The provider-backed implementation passes the shared contract."""

    @pytest.fixture
    def completer(self) -> ToolCallingCompleter:
        return _world(RoundResponse(text="ok")).completer

    def world(self, response: RoundResponse) -> _ModelWorld:
        return _world(response)


def _request() -> list[Message]:
    return [
        Message(role=Role.SYSTEM, content="You plan one round."),
        Message(role=Role.USER, content="what now?"),
    ]


def _tool(name: str = "web_search") -> OfferedTool:
    return OfferedTool(
        name=name,
        description="Search the web.",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
    )


def _scripted(*parts: ModelResponsePart) -> _ModelWorld:
    return _ModelWorld(script=lambda: ModelResponse(parts=list(parts)))


async def test_the_round_tool_is_offered_once_beside_the_capabilities() -> None:
    world = _world(RoundResponse(text="ok"))
    await world.completer.respond(_request(), [_tool()])
    assert world.round_tools == [1]


async def test_a_capability_taking_the_reserved_name_is_refused_before_the_model() -> None:
    world = _world(RoundResponse(text="ok"))
    with pytest.raises(ModelError) as caught:
        await world.completer.respond(_request(), [_tool(ROUND_TOOL)])
    assert type(caught.value) is ModelError
    assert world.attempts == 0


async def test_several_round_tool_calls_join_their_notes_and_any_mark_holds() -> None:
    world = _scripted(
        ToolCallPart(ROUND_TOOL, {"notes": "first"}, tool_call_id="a"),
        ToolCallPart(ROUND_TOOL, {"notes": "second", "another_round": True}, tool_call_id="b"),
        ToolCallPart(ROUND_TOOL, {"another_round": False}, tool_call_id="c"),
    )
    response = await world.completer.respond(_request(), [])
    assert response == RoundResponse(notes="first\n\nsecond", another_round=True)


async def test_blank_notes_are_no_notes() -> None:
    world = _scripted(ToolCallPart(ROUND_TOOL, {"notes": "   "}, tool_call_id="a"))
    assert (await world.completer.respond(_request(), [])).notes is None


async def test_text_either_side_of_a_call_is_kept_apart() -> None:
    world = _scripted(
        TextPart("Searching."),
        ToolCallPart("web_search", {"query": "q"}, tool_call_id="a"),
        TextPart("Back soon."),
    )
    response = await world.completer.respond(_request(), [_tool()])
    assert response.text == "Searching.\n\nBack soon."
    assert [call.call_id for call in response.calls] == ["a"]


async def test_a_call_named_for_a_tool_not_offered_is_returned_as_proposed() -> None:
    world = _scripted(ToolCallPart("not_offered", {"x": 1}, tool_call_id="a"))
    response = await world.completer.respond(_request(), [_tool()])
    assert response.calls[0].name == "not_offered"


@pytest.mark.parametrize(
    "part",
    [
        pytest.param(ToolCallPart("web_search", "{not json", tool_call_id="a"), id="bad-json"),
        pytest.param(ToolCallPart("web_search", "[1, 2]", tool_call_id="a"), id="not-object"),
        pytest.param(ToolCallPart(ROUND_TOOL, {"notes": 3}, tool_call_id="a"), id="notes-not-text"),
        pytest.param(
            ToolCallPart(ROUND_TOOL, {"another_round": "yes"}, tool_call_id="a"),
            id="mark-not-boolean",
        ),
        pytest.param(ToolCallPart(ROUND_TOOL, {"other": 1}, tool_call_id="a"), id="extra-key"),
        pytest.param(TextPart("\ud800"), id="unencodable-text"),
    ],
)
async def test_a_response_that_is_not_a_round_is_a_response_error(
    part: ModelResponsePart,
) -> None:
    world = _scripted(part)
    with pytest.raises(ModelResponseError):
        await world.completer.respond(_request(), [_tool()])


async def test_two_calls_under_one_id_are_a_response_error() -> None:
    world = _scripted(
        ToolCallPart("web_search", {"query": "a"}, tool_call_id="same"),
        ToolCallPart("web_search", {"query": "b"}, tool_call_id="same"),
    )
    with pytest.raises(ModelResponseError):
        await world.completer.respond(_request(), [_tool()])


async def test_a_provider_failure_is_classified() -> None:
    def refuse(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        raise ModelHTTPError(status_code=429, model_name="test")

    completer = PydanticAIToolCallingCompleter(default_model=FunctionModel(refuse))
    with pytest.raises(ModelRateLimitError):
        await completer.respond(_request(), [_tool()])


def test_construction_with_a_model_name_is_offline() -> None:
    PydanticAIToolCallingCompleter(default_model="anthropic:claude-opus-4-8")
