"""``PydanticAIToolCallingCompleter``: the shared contract, and what it adds.

The binding runs the suite over a pydantic-ai ``FunctionModel``, which is the world:
it plays the scripted round back in the provider's native shape (text, tool calls and
the reserved round tool) and records what each request carried. Everything is
offline.

Where a vendor decides the shape, as for the thinking a round asks for (#2861), the
request is read off the wire of that vendor's real SDK over a mock transport, with the
network denied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import httpx
import pytest
from anthropic import AsyncAnthropic
from network_guard import network_denied
from openai import AsyncOpenAI
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider
from tool_calling_completer_contract import SeenTool, ToolCallingCompleterContract, Turn
from vendor_stacks import RequestRecorder, anthropic_success, openai_success

from ai_assistant.core.diagnostics import diagnosed_activation
from ai_assistant.core.errors import ModelError, ModelRateLimitError, ModelResponseError
from ai_assistant.core.types import (
    DiagnosticKind,
    DiagnosticSource,
    Message,
    OfferedTool,
    Role,
    RoundResponse,
)
from ai_assistant.models import PydanticAIToolCallingCompleter
from ai_assistant.models.tool_calling import DEFAULT_THINKING, ROUND_TOOL
from ai_assistant.testing import FakeDiagnosticSink

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic_ai.messages import ModelMessage, ModelResponsePart
    from pydantic_ai.models import Model
    from pydantic_ai.settings import ThinkingLevel
    from vendor_stacks import Handler

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
    if response.notes is not None:
        arguments: dict[str, Any] = {"notes": response.notes}
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


async def test_several_round_tool_calls_join_their_notes() -> None:
    world = _scripted(
        ToolCallPart(ROUND_TOOL, {"notes": "first"}, tool_call_id="a"),
        ToolCallPart(ROUND_TOOL, {"notes": "second"}, tool_call_id="b"),
        ToolCallPart(ROUND_TOOL, {}, tool_call_id="c"),
    )
    response = await world.completer.respond(_request(), [])
    assert response == RoundResponse(notes="first\n\nsecond")


async def test_the_round_tool_offers_the_notes_alone() -> None:
    """ADR-0315 §3:3: the reserved tool carries the notes, and no mark."""
    seen: list[dict[str, Any]] = []

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        seen.extend(
            tool.parameters_json_schema for tool in info.function_tools if tool.name == ROUND_TOOL
        )
        return ModelResponse(parts=[TextPart("ok")])

    await PydanticAIToolCallingCompleter(FunctionModel(answer)).respond(_request(), [])
    (schema,) = seen
    assert set(schema["properties"]) == {"notes"}
    assert schema["additionalProperties"] is False


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
            ToolCallPart(ROUND_TOOL, {"notes": "n", "another_round": True}, tool_call_id="a"),
            id="retired-mark",
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


# --- room to think before it writes (#2861) -----------------------------------------------

#: A literal dummy key, so no vendor client reads one from the environment.
_DUMMY_KEY: Final = "test-key-not-a-credential"


@dataclass
class _Seen:
    """What each ``FunctionModel`` request carried, after pydantic-ai prepared it."""

    thinking: list[ThinkingLevel | None] = field(default_factory=list)
    max_tokens: list[int | None] = field(default_factory=list)


def _seeing(seen: _Seen, *, takes_thinking: bool) -> FunctionModel:
    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        seen.thinking.append(info.model_request_parameters.thinking)
        seen.max_tokens.append((info.model_settings or {}).get("max_tokens"))
        return ModelResponse(parts=[TextPart("ok")])

    profile = ModelProfile(supports_thinking=True) if takes_thinking else None
    return FunctionModel(answer, profile=profile)


async def test_a_round_thinks_at_the_providers_default_effort_by_default() -> None:
    seen = _Seen()
    await PydanticAIToolCallingCompleter(_seeing(seen, takes_thinking=True)).respond(
        _request(), [_tool()]
    )
    assert DEFAULT_THINKING is True
    assert seen.thinking == [True]


@pytest.mark.parametrize("level", [True, "low", "high", False])
async def test_the_thinking_setting_reaches_a_model_that_takes_it(level: ThinkingLevel) -> None:
    seen = _Seen()
    completer = PydanticAIToolCallingCompleter(_seeing(seen, takes_thinking=True), thinking=level)
    await completer.respond(_request(), [_tool()])
    assert seen.thinking == [level]


async def test_thinking_widens_the_ceiling_by_the_levels_budget() -> None:
    seen = _Seen()
    for level in (True, "low", "high"):
        completer = PydanticAIToolCallingCompleter(
            _seeing(seen, takes_thinking=True), thinking=level
        )
        await completer.respond(_request(), [_tool()])
    assert seen.max_tokens == [4096 + 10000, 4096 + 2048, 4096 + 16384]


@pytest.mark.parametrize("takes_thinking", [True, False], ids=["takes-thinking", "no-thinking"])
async def test_asking_for_no_thinking_leaves_the_ceiling_alone(takes_thinking: bool) -> None:
    seen = _Seen()
    completer = PydanticAIToolCallingCompleter(
        _seeing(seen, takes_thinking=takes_thinking), thinking=False
    )
    await completer.respond(_request(), [_tool()])
    assert seen.max_tokens == [None]


async def test_a_model_without_thinking_keeps_the_request_it_had() -> None:
    seen = _Seen()
    response = await PydanticAIToolCallingCompleter(_seeing(seen, takes_thinking=False)).respond(
        _request(), [_tool()]
    )
    assert seen.thinking == [None]
    assert seen.max_tokens == [None]
    assert response == RoundResponse(text="ok")


async def test_thinking_parts_are_dropped_and_the_text_is_the_text_parts_alone() -> None:
    world = _scripted(
        ThinkingPart("The user has answered my question, so I can book it now."),
        TextPart("I'll book Watchman for the night of November 14."),
        ThinkingPart("", id="redacted_thinking", signature="opaque"),
        ToolCallPart("web_search", {"query": "q"}, tool_call_id="a"),
        ToolCallPart(ROUND_TOOL, {"notes": "booking"}, tool_call_id="b"),
    )
    response = await world.completer.respond(_request(), [_tool()])
    assert response.text == "I'll book Watchman for the night of November 14."
    assert [call.call_id for call in response.calls] == ["a"]
    assert response.notes == "booking"


async def test_a_round_that_only_thought_and_called_writes_no_text() -> None:
    world = _scripted(
        ThinkingPart("Nothing to say until the search is back."),
        ToolCallPart("web_search", {"query": "q"}, tool_call_id="a"),
    )
    response = await world.completer.respond(_request(), [_tool()])
    assert response.text == ""
    assert [call.name for call in response.calls] == ["web_search"]


def _anthropic(
    name: str, http_client: httpx.AsyncClient, settings: AnthropicModelSettings | None = None
) -> Model:
    client = AsyncAnthropic(api_key=_DUMMY_KEY, http_client=http_client, max_retries=0)
    return AnthropicModel(
        name, provider=AnthropicProvider(anthropic_client=client), settings=settings
    )


async def _anthropic_round(
    name: str,
    handler: Handler,
    *,
    thinking: ThinkingLevel = DEFAULT_THINKING,
    settings: AnthropicModelSettings | None = None,
    diagnostics: FakeDiagnosticSink | None = None,
) -> tuple[RoundResponse, dict[str, object]]:
    """One round over Anthropic's real SDK, and the request body it put on the wire."""
    recorder = RequestRecorder(handler)
    with network_denied():
        async with httpx.AsyncClient(transport=httpx.MockTransport(recorder)) as http_client:
            completer = PydanticAIToolCallingCompleter(
                _anthropic(name, http_client, settings), thinking=thinking, diagnostics=diagnostics
            )
            response = await completer.respond(_request(), [_tool()])
    return response, recorder.only


async def test_an_adaptive_anthropic_model_is_asked_to_think_adaptively() -> None:
    _, body = await _anthropic_round("claude-opus-4-8", anthropic_success)
    assert body["thinking"] == {"type": "adaptive"}
    assert body["max_tokens"] == 4096 + 10000
    assert "output_config" not in body


async def test_a_budget_anthropic_model_is_given_a_ceiling_above_its_budget() -> None:
    _, body = await _anthropic_round("claude-haiku-4-5", anthropic_success)
    assert body["thinking"] == {"type": "enabled", "budget_tokens": 10000}
    assert body["max_tokens"] == 4096 + 10000


async def test_a_models_own_thinking_budget_is_given_room_on_top() -> None:
    settings = AnthropicModelSettings(
        anthropic_thinking={"type": "enabled", "budget_tokens": 12000}
    )
    _, body = await _anthropic_round("claude-haiku-4-5", anthropic_success, settings=settings)
    assert body["thinking"] == {"type": "enabled", "budget_tokens": 12000}
    assert body["max_tokens"] == 4096 + 12000


async def test_a_models_own_larger_ceiling_is_kept() -> None:
    settings = AnthropicModelSettings(
        max_tokens=20000, anthropic_thinking={"type": "enabled", "budget_tokens": 12000}
    )
    _, body = await _anthropic_round("claude-haiku-4-5", anthropic_success, settings=settings)
    assert body["thinking"] == {"type": "enabled", "budget_tokens": 12000}
    assert body["max_tokens"] == 20000


async def test_a_models_own_smaller_ceiling_is_widened_for_the_thinking() -> None:
    settings = AnthropicModelSettings(max_tokens=1000)
    _, body = await _anthropic_round("claude-haiku-4-5", anthropic_success, settings=settings)
    assert body["thinking"] == {"type": "enabled", "budget_tokens": 10000}
    assert body["max_tokens"] == 4096 + 10000


async def test_no_thinking_puts_the_request_it_had_on_the_anthropic_wire() -> None:
    _, body = await _anthropic_round("claude-opus-4-8", anthropic_success, thinking=False)
    assert "thinking" not in body
    assert body["max_tokens"] == 4096


def _thinking_then_text_and_a_call(request: httpx.Request) -> httpx.Response:
    del request
    return httpx.Response(
        200,
        json={
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-4-8",
            "content": [
                {
                    "type": "thinking",
                    "thinking": "The user has answered my question; book Watchman.",
                    "signature": "sig",
                },
                {"type": "redacted_thinking", "data": "opaque"},
                {"type": "text", "text": "I'll book Watchman for the night of November 14."},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "web_search",
                    "input": {"query": "Watchman"},
                },
            ],
            "stop_reason": "tool_use",
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    )


async def test_an_anthropic_response_with_thinking_yields_a_round_without_it() -> None:
    response, _ = await _anthropic_round("claude-opus-4-8", _thinking_then_text_and_a_call)
    assert response.text == "I'll book Watchman for the night of November 14."
    assert [(call.call_id, call.name) for call in response.calls] == [("toolu_1", "web_search")]
    assert response.notes is None


async def test_an_openai_model_without_thinking_keeps_the_request_it_had() -> None:
    recorder = RequestRecorder(openai_success)
    with network_denied():
        async with httpx.AsyncClient(transport=httpx.MockTransport(recorder)) as http_client:
            client = AsyncOpenAI(api_key=_DUMMY_KEY, http_client=http_client, max_retries=0)
            model = OpenAIChatModel("gpt-4o", provider=OpenAIProvider(openai_client=client))
            await PydanticAIToolCallingCompleter(model).respond(_request(), [_tool()])
    body = recorder.only
    assert "reasoning_effort" not in body
    assert "max_tokens" not in body
    assert "max_completion_tokens" not in body


@pytest.mark.parametrize(
    "parts",
    [
        pytest.param([ThinkingPart("Still weighing which campground…")], id="only-thinking"),
        pytest.param(
            [ThinkingPart("Booking it."), TextPart("I'll book Watchman for the night of")],
            id="text-cut",
        ),
    ],
)
async def test_a_response_cut_at_its_ceiling_is_a_response_error(
    parts: list[ModelResponsePart],
) -> None:
    world = _ModelWorld(script=lambda: ModelResponse(parts=parts, finish_reason="length"))
    with pytest.raises(ModelResponseError):
        await world.completer.respond(_request(), [_tool()])


def _thinking_cut_at_the_ceiling(request: httpx.Request) -> httpx.Response:
    del request
    return httpx.Response(
        200,
        json={
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-4-8",
            "content": [{"type": "thinking", "thinking": "Weighing it…", "signature": "sig"}],
            "stop_reason": "max_tokens",
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 14096},
        },
    )


async def test_an_anthropic_response_whose_thinking_took_the_ceiling_is_a_response_error() -> None:
    with pytest.raises(ModelResponseError):
        await _anthropic_round("claude-opus-4-8", _thinking_cut_at_the_ceiling)


@pytest.mark.parametrize("level", [True, "high", False])
@pytest.mark.parametrize("wrapped", [False, True], ids=["bare", "wrapped"])
async def test_a_fallback_model_keeps_the_request_it_had(
    level: ThinkingLevel,
    wrapped: bool,
) -> None:
    def refuse(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        raise ModelHTTPError(status_code=429, model_name="primary")

    seen = _Seen()
    fallback: Model = FallbackModel(
        FunctionModel(refuse, profile=ModelProfile(supports_thinking=True)),
        _seeing(seen, takes_thinking=True),
    )
    if wrapped:
        fallback = WrapperModel(fallback)
    response = await PydanticAIToolCallingCompleter(fallback, thinking=level).respond(
        _request(), [_tool()]
    )
    assert response == RoundResponse(text="ok")
    assert seen.thinking == [None]
    assert seen.max_tokens == [None]


# --- ADR-0314 §5: planning's thinking reaches the diagnostic record, and nothing else ---------

_DIAGNOSED: Final = "3f2b8c4e-1d5a-4e7b-9c0d-2a6f8e1b7c35"


def _diagnosed_now() -> datetime:
    return datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


async def test_with_the_record_on_adaptive_thinking_is_asked_for_its_summarised_text() -> None:
    """§5:1: adaptive thinking omits its text unless the request asks for the summary."""
    sink = FakeDiagnosticSink()
    _, body = await _anthropic_round("claude-opus-4-8", anthropic_success, diagnostics=sink)
    assert body["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert body["max_tokens"] == 4096 + 10000


async def test_with_the_record_on_budget_thinking_keeps_the_request_it_had() -> None:
    """Only where the provider otherwise omits the text is the request changed."""
    _, body = await _anthropic_round(
        "claude-haiku-4-5", anthropic_success, diagnostics=FakeDiagnosticSink()
    )
    assert body["thinking"] == {"type": "enabled", "budget_tokens": 10000}


async def test_with_the_record_on_a_models_own_thinking_setting_is_kept() -> None:
    settings = AnthropicModelSettings(anthropic_thinking={"type": "adaptive"})
    _, body = await _anthropic_round(
        "claude-opus-4-8", anthropic_success, settings=settings, diagnostics=FakeDiagnosticSink()
    )
    assert body["thinking"] == {"type": "adaptive"}


async def test_with_the_record_on_no_thinking_still_asks_for_none() -> None:
    _, body = await _anthropic_round(
        "claude-opus-4-8", anthropic_success, thinking=False, diagnostics=FakeDiagnosticSink()
    )
    assert "thinking" not in body


def _diagnosing(
    *parts: ModelResponsePart, finish: str | None = None
) -> tuple[PydanticAIToolCallingCompleter, FakeDiagnosticSink]:
    sink = FakeDiagnosticSink()

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        return ModelResponse(parts=list(parts), finish_reason=finish)  # type: ignore[arg-type]

    return PydanticAIToolCallingCompleter(FunctionModel(answer), diagnostics=sink), sink


async def test_the_completer_writes_the_whole_response_thinking_included() -> None:
    """§5:2: every part in order; §5:3: the round itself carries no thinking."""
    completer, sink = _diagnosing(
        ThinkingPart("They answered, so book it."),
        TextPart("Booking it now."),
        ToolCallPart("web_search", {"query": "q"}, tool_call_id="a"),
    )

    with diagnosed_activation(_DIAGNOSED, clock=_diagnosed_now):
        response = await completer.respond(_request(), [_tool()])

    assert response == RoundResponse(text="Booking it now.", calls=(response.calls[0],), notes=None)
    (entry,) = sink.recorded
    assert (entry.activation_id, entry.source, entry.kind) == (
        _DIAGNOSED,
        DiagnosticSource.PLANNING,
        DiagnosticKind.RETURNED,
    )
    body = entry.model_dump(mode="json")["body"]
    assert body["read_as_round"] is True
    parts = body["response"]["parts"]
    assert [part["part_kind"] for part in parts] == ["thinking", "text", "tool-call"]
    assert parts[0]["content"] == "They answered, so book it."


async def test_a_response_that_is_no_round_is_written_before_the_completer_raises() -> None:
    """§5:2: whether or not the response reads as a round."""
    completer, sink = _diagnosing(ThinkingPart("Weighing it…"), finish="length")

    with diagnosed_activation(_DIAGNOSED, clock=_diagnosed_now), pytest.raises(ModelResponseError):
        await completer.respond(_request(), [_tool()])

    body = sink.recorded[0].model_dump(mode="json")["body"]
    assert body["read_as_round"] is False
    assert body["failure"]["class"] == "ModelResponseError"
    assert body["response"]["parts"][0]["content"] == "Weighing it…"


async def test_where_no_response_came_back_the_completer_writes_nothing() -> None:
    """§5:2: then planning's module writes the entry, with the failure."""
    sink = FakeDiagnosticSink()

    def refuse(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        raise ModelHTTPError(status_code=429, model_name="primary")

    completer = PydanticAIToolCallingCompleter(FunctionModel(refuse), diagnostics=sink)
    with diagnosed_activation(_DIAGNOSED, clock=_diagnosed_now), pytest.raises(ModelError):
        await completer.respond(_request(), [_tool()])

    assert sink.recorded == ()


async def test_with_no_activation_bound_the_completer_writes_nothing() -> None:
    """§5:4: the completer reads the binding, and writes nothing where none is bound."""
    completer, sink = _diagnosing(TextPart("ok"))

    await completer.respond(_request(), [_tool()])

    assert sink.recorded == ()
