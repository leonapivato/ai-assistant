"""``PydanticAIToolCallingCompleter``: the shared contract, and what it adds.

The binding runs the suite over a pydantic-ai ``FunctionModel``, which is the world:
it plays the scripted round back in the provider's native shape (text and tool calls)
and records what each request carried. Everything is offline.

Where a vendor decides the shape, as for the thinking a round asks for (#2861), the
request is read off the wire of that vendor's real SDK over a mock transport, with the
network denied.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar, Final, cast

import httpx
import pytest
from anthropic import AsyncAnthropic
from network_guard import network_denied
from openai import AsyncOpenAI
from pydantic_ai.concurrency import ConcurrencyLimiter
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import (
    CachePoint,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.models.concurrency import ConcurrencyLimitedModel
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.instrumented import InstrumentedModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.profiles import JsonSchemaTransformer, ModelProfile
from pydantic_ai.profiles.openai import OpenAIJsonSchemaTransformer
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider
from tool_calling_completer_contract import (
    SeenTool,
    ToolCallingCompleterContract,
    Turn,
    call_turn,
)
from vendor_stacks import RequestRecorder, anthropic_success, openai_success

from ai_assistant.core.diagnostics import diagnosed_activation
from ai_assistant.core.errors import ModelError, ModelRateLimitError, ModelResponseError
from ai_assistant.core.types import (
    CallResult,
    DiagnosticKind,
    DiagnosticSource,
    ExchangeStep,
    OfferedTool,
    PlanningExchange,
    ProposedCall,
    RoundContinuation,
    RoundReport,
    RoundResponse,
)
from ai_assistant.models import PydanticAIToolCallingCompleter, tool_calling
from ai_assistant.models.tool_calling import DEFAULT_THINKING
from ai_assistant.testing import FakeDiagnosticSink

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic_ai.messages import ModelMessage, ModelResponsePart
    from pydantic_ai.models import Model
    from pydantic_ai.models import ModelRequestParameters as Parameters
    from pydantic_ai.settings import ModelSettings, ThinkingLevel
    from pydantic_ai.tools import ToolDefinition as NativeTool
    from vendor_stacks import Handler

    from ai_assistant.core.protocols import ToolCallingCompleter


def _turns(messages: list[ModelMessage]) -> tuple[Turn, ...]:
    """The request as the suite's turns, read back off pydantic-ai's history.

    A cache point is no turn, and neither is a thinking part: each is read apart.
    """
    turns: list[Turn] = []
    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, SystemPromptPart):
                    turns.append(("system", part.content))
                elif isinstance(part, UserPromptPart):
                    content = part.content
                    texts = [content] if isinstance(content, str) else list(content)
                    turns.extend(("user", one) for one in texts if isinstance(one, str))
                elif isinstance(part, ToolReturnPart):
                    turns.append(("result", part.tool_call_id, str(part.content)))
        else:
            for answered in message.parts:
                if isinstance(answered, TextPart):
                    turns.append(("text", answered.content))
                elif isinstance(answered, ToolCallPart):
                    proposed = ProposedCall(
                        call_id=answered.tool_call_id,
                        name=answered.tool_name,
                        arguments=answered.args_as_dict(),
                    )
                    turns.append(call_turn(proposed))
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
    return ModelResponse(parts=parts)


def _bare(response: RoundResponse) -> RoundResponse:
    """``response`` without its continuation, which every round now carries."""
    return response.model_copy(update={"continuation": None})


@dataclass
class _ModelWorld:
    """A ``FunctionModel`` playing one round back, and what each request carried."""

    script: Callable[[], ModelResponse]
    requests: list[tuple[Turn, ...]] = field(default_factory=list)
    tools: list[tuple[SeenTool, ...]] = field(default_factory=list)

    def answer(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.requests.append(_turns(messages))
        self.tools.append(
            tuple(
                (tool.name, tool.description or "", tool.parameters_json_schema)
                for tool in info.function_tools
            )
        )
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


def _request() -> PlanningExchange:
    return PlanningExchange(instruction="You plan one round.", briefing="what now?")


def _tool(name: str = "web_search") -> OfferedTool:
    return OfferedTool(
        name=name,
        description="Search the web.",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
    )


def _scripted(*parts: ModelResponsePart) -> _ModelWorld:
    return _ModelWorld(script=lambda: ModelResponse(parts=list(parts)))


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
    assert _bare(response) == RoundResponse(text="ok")


async def test_thinking_parts_are_dropped_and_the_text_is_the_text_parts_alone() -> None:
    world = _scripted(
        ThinkingPart("The user has answered my question, so I can book it now."),
        TextPart("I'll book Watchman for the night of November 14."),
        ThinkingPart("", id="redacted_thinking", signature="opaque"),
        ToolCallPart("web_search", {"query": "q"}, tool_call_id="a"),
    )
    response = await world.completer.respond(_request(), [_tool()])
    assert response.text == "I'll book Watchman for the night of November 14."
    assert [call.call_id for call in response.calls] == ["a"]


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
    assert _bare(response) == RoundResponse(text="ok")
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

    assert _bare(response) == RoundResponse(text="Booking it now.", calls=(response.calls[0],))
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


async def test_the_returned_entry_shows_every_tool_the_provider_was_offered() -> None:
    """#2894: every tool reaches the record, and no reserved one is added (ADR-0356 §7:4).

    Each tool is kept as planning's given entry keeps an offered one, so the two read alike.
    """
    sink = FakeDiagnosticSink()
    received: list[list[NativeTool]] = []

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        received.append(list(info.function_tools))
        return ModelResponse(parts=[TextPart("ok")])

    completer = PydanticAIToolCallingCompleter(FunctionModel(answer), diagnostics=sink)
    offered = [_tool("web_search"), _tool("book_stay")]

    with diagnosed_activation(_DIAGNOSED, clock=_diagnosed_now):
        await completer.respond(_request(), offered)

    body = sink.recorded[0].model_dump(mode="json")["body"]
    (sent,) = received
    assert body["offered_tools"] == [
        {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters_json_schema,
        }
        for tool in sent
    ]
    assert body["offered_tools"] == [tool.model_dump(mode="json") for tool in offered]


async def test_a_response_that_is_no_round_is_written_before_the_completer_raises() -> None:
    """§5:2: whether or not the response reads as a round, the tools offered included."""
    completer, sink = _diagnosing(ThinkingPart("Weighing it…"), finish="length")

    with diagnosed_activation(_DIAGNOSED, clock=_diagnosed_now), pytest.raises(ModelResponseError):
        await completer.respond(_request(), [_tool()])

    body = sink.recorded[0].model_dump(mode="json")["body"]
    assert body["read_as_round"] is False
    assert body["failure"]["class"] == "ModelResponseError"
    assert body["response"]["parts"][0]["content"] == "Weighing it…"
    assert [tool["name"] for tool in body["offered_tools"]] == ["web_search"]


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


# --- #2910: the tools are recorded as the model's request preparation sent them -------------


def _recorded_tools(sink: FakeDiagnosticSink) -> list[dict[str, Any]]:
    (entry,) = sink.recorded
    body = entry.model_dump(mode="json")["body"]
    assert "offered_tools_unprepared" not in body
    tools: list[dict[str, Any]] = body["offered_tools"]
    return tools


async def test_an_openai_models_rewritten_schemas_are_recorded_as_sent() -> None:
    """The transformer's added restriction reaches the record, read against the wire body."""
    sink = FakeDiagnosticSink()
    recorder = RequestRecorder(openai_success)
    offered = [_tool("web_search"), _tool("book_stay")]
    with network_denied(), diagnosed_activation(_DIAGNOSED, clock=_diagnosed_now):
        async with httpx.AsyncClient(transport=httpx.MockTransport(recorder)) as http_client:
            client = AsyncOpenAI(api_key=_DUMMY_KEY, http_client=http_client, max_retries=0)
            model = OpenAIChatModel("gpt-4o", provider=OpenAIProvider(openai_client=client))
            await PydanticAIToolCallingCompleter(model, diagnostics=sink).respond(
                _request(), offered
            )

    recorded = _recorded_tools(sink)
    wire = [tool["function"] for tool in cast("list[dict[str, Any]]", recorder.only["tools"])]
    assert [
        {key: tool[key] for key in ("name", "description", "parameters")} for tool in wire
    ] == recorded
    assert [tool["name"] for tool in recorded] == ["web_search", "book_stay"]
    assert [tool["description"] for tool in recorded[:2]] == [t.description for t in offered]
    # A restriction the round did not write is recorded, as the provider was sent it.
    assert "additionalProperties" not in _tool().parameters
    assert recorded[0]["parameters"]["additionalProperties"] is False


async def test_preparation_state_changed_while_the_request_is_out_does_not_reach_the_record() -> (
    None
):
    """The round-3 review's probe: the profile changes while the request is on the wire.

    The tools as prepared are taken before the request is sent, so the record is still
    what the wire carried.
    """
    sink = FakeDiagnosticSink()
    shared: list[Model] = []

    def change_then_answer(request: httpx.Request) -> httpx.Response:
        shared[0].profile["json_schema_transformer"] = None
        return openai_success(request)

    recorder = RequestRecorder(change_then_answer)
    with network_denied(), diagnosed_activation(_DIAGNOSED, clock=_diagnosed_now):
        async with httpx.AsyncClient(transport=httpx.MockTransport(recorder)) as http_client:
            client = AsyncOpenAI(api_key=_DUMMY_KEY, http_client=http_client, max_retries=0)
            shared.append(OpenAIChatModel("gpt-4o", provider=OpenAIProvider(openai_client=client)))
            await PydanticAIToolCallingCompleter(shared[0], diagnostics=sink).respond(
                _request(), [_tool()]
            )

    assert shared[0].profile.get("json_schema_transformer") is None
    recorded = _recorded_tools(sink)
    wire = [tool["function"] for tool in cast("list[dict[str, Any]]", recorder.only["tools"])]
    assert [tool["parameters"] for tool in wire] == [tool["parameters"] for tool in recorded]
    assert recorded[0]["parameters"]["additionalProperties"] is False


@pytest.mark.parametrize(
    "wrap",
    [
        pytest.param(lambda model: model, id="bare"),
        pytest.param(WrapperModel, id="wrapper"),
        pytest.param(lambda model: InstrumentedModel(WrapperModel(model)), id="instrumented"),
    ],
)
async def test_wrappers_that_hand_the_request_straight_on_are_replayed(
    wrap: Callable[[Model], Model],
) -> None:
    """The record equals what the model it wraps was given, transformer and all."""
    received: list[list[NativeTool]] = []

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        received.append(list(info.function_tools))
        return ModelResponse(parts=[TextPart("ok")])

    sink = FakeDiagnosticSink()
    model = FunctionModel(
        answer, profile=ModelProfile(json_schema_transformer=OpenAIJsonSchemaTransformer)
    )
    with diagnosed_activation(_DIAGNOSED, clock=_diagnosed_now):
        await PydanticAIToolCallingCompleter(wrap(model), diagnostics=sink).respond(
            _request(), [_tool()]
        )

    (given,) = received
    assert [tool["parameters"] for tool in _recorded_tools(sink)] == [
        tool.parameters_json_schema for tool in given
    ]
    assert given[0].parameters_json_schema["additionalProperties"] is False


async def test_a_wrapper_that_waits_before_the_model_prepares_is_not_replayed() -> None:
    """The round-4 and round-5 reviews' probe: a concurrency-limited model.

    The request waits for a slot; the profile changes while it waits, so the request is
    prepared under the change, and is changed back before the round returns. No replay
    taken outside the request can tell, so the record is marked, never the old schema.
    """
    sink = FakeDiagnosticSink()
    inner: list[Model] = []

    def restore_then_answer(request: httpx.Request) -> httpx.Response:
        inner[0].profile["json_schema_transformer"] = OpenAIJsonSchemaTransformer
        return openai_success(request)

    recorder = RequestRecorder(restore_then_answer)
    limiter = ConcurrencyLimiter(max_running=1)
    with network_denied(), diagnosed_activation(_DIAGNOSED, clock=_diagnosed_now):
        async with httpx.AsyncClient(transport=httpx.MockTransport(recorder)) as http_client:
            client = AsyncOpenAI(api_key=_DUMMY_KEY, http_client=http_client, max_retries=0)
            inner.append(OpenAIChatModel("gpt-4o", provider=OpenAIProvider(openai_client=client)))
            completer = PydanticAIToolCallingCompleter(
                ConcurrencyLimitedModel(inner[0], limiter=limiter), diagnostics=sink
            )
            await limiter.acquire("held by the test")
            pending = asyncio.ensure_future(completer.respond(_request(), [_tool()]))
            for _ in range(10):  # the round reaches the held slot within a few steps
                await asyncio.sleep(0)
            assert limiter.waiting_count == 1
            inner[0].profile["json_schema_transformer"] = None
            limiter.release()
            await pending

    body = sink.recorded[0].model_dump(mode="json")["body"]
    wire = [tool["function"] for tool in cast("list[dict[str, Any]]", recorder.only["tools"])]
    assert "additionalProperties" not in wire[0]["parameters"]
    assert body["offered_tools"][0] == _tool().model_dump(mode="json")
    assert [tool["name"] for tool in body["offered_tools"]] == ["web_search"]
    assert "may wait before" in body["offered_tools_unprepared"]["message"]


async def test_an_anthropic_models_tools_are_recorded_as_sent() -> None:
    """Planning's own model: the record and the wire carry the same definitions."""
    sink = FakeDiagnosticSink()
    with diagnosed_activation(_DIAGNOSED, clock=_diagnosed_now):
        _, body = await _anthropic_round("claude-opus-4-8", anthropic_success, diagnostics=sink)

    recorded = _recorded_tools(sink)
    wire = cast("list[dict[str, Any]]", body["tools"])
    assert [
        {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        }
        for tool in wire
    ] == recorded
    assert [tool["name"] for tool in recorded] == ["web_search"]
    assert recorded[0] == _tool().model_dump(mode="json")


class _Counting(FunctionModel):
    """A model whose own preparation keeps state: each request is numbered into its schema.

    Replaying such a preparation would record a number never sent and move the next
    request's on (the round-1 review's probe), so the record must not replay it.
    """

    def __init__(self, seen: list[object]) -> None:
        def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            del messages
            seen.append(info.function_tools[0].parameters_json_schema["properties"]["query"])
            return ModelResponse(parts=[TextPart("ok")])

        super().__init__(answer)
        self.prepared = 0

    def prepare_request(
        self, model_settings: ModelSettings | None, model_request_parameters: Parameters
    ) -> tuple[ModelSettings | None, Parameters]:
        self.prepared += 1
        settings, parameters = super().prepare_request(model_settings, model_request_parameters)
        first, *rest = parameters.function_tools
        schema = {**first.parameters_json_schema}
        schema["properties"] = {"query": {"const": self.prepared}}
        numbered = dataclasses.replace(first, parameters_json_schema=schema)
        return settings, dataclasses.replace(parameters, function_tools=[numbered, *rest])


async def test_a_preparation_that_is_not_pydantic_ais_own_is_not_replayed() -> None:
    """The requests are as they are with the record off, and the record says why not."""
    seen: list[object] = []
    sink = FakeDiagnosticSink()
    completer = PydanticAIToolCallingCompleter(_Counting(seen), diagnostics=sink)

    with diagnosed_activation(_DIAGNOSED, clock=_diagnosed_now):
        await completer.respond(_request(), [_tool()])
        await completer.respond(_request(), [_tool()])

    assert seen == [{"const": 1}, {"const": 2}]
    for entry in sink.recorded:
        body = entry.model_dump(mode="json")["body"]
        assert body["offered_tools"][0] == _tool().model_dump(mode="json")
        assert "_Counting" in body["offered_tools_unprepared"]["message"]


class _CountingTransformer(JsonSchemaTransformer):
    """A schema transformer that keeps state: each walk numbers the first property."""

    walks: ClassVar[int] = 0

    def walk(self) -> dict[str, Any]:
        schema = super().walk()
        if "query" in schema.get("properties", {}):
            type(self).walks += 1
            schema["properties"] = {"query": {"const": type(self).walks}}
        return schema

    def transform(self, schema: dict[str, Any]) -> dict[str, Any]:
        return schema


async def test_a_schema_transformer_that_is_not_pydantic_ais_own_is_not_replayed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The round-2 review's probe: the profile's hook runs other code, so no replay."""
    monkeypatch.setattr(_CountingTransformer, "walks", 0)
    seen: list[object] = []

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        seen.append(info.function_tools[0].parameters_json_schema["properties"]["query"])
        return ModelResponse(parts=[TextPart("ok")])

    sink = FakeDiagnosticSink()
    model = FunctionModel(
        answer, profile=ModelProfile(json_schema_transformer=_CountingTransformer)
    )
    completer = PydanticAIToolCallingCompleter(model, diagnostics=sink)

    with diagnosed_activation(_DIAGNOSED, clock=_diagnosed_now):
        await completer.respond(_request(), [_tool()])
        await completer.respond(_request(), [_tool()])

    assert seen == [{"const": 1}, {"const": 2}]
    for entry in sink.recorded:
        body = entry.model_dump(mode="json")["body"]
        assert body["offered_tools"][0] == _tool().model_dump(mode="json")
        assert "_CountingTransformer" in body["offered_tools_unprepared"]["message"]


def _answering() -> FunctionModel:
    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        return ModelResponse(parts=[TextPart("ok")])

    return FunctionModel(answer)


class _Wrapping(WrapperModel):
    """A wrapper whose own code sends the request, which a replay could not see into."""

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: Parameters,
    ) -> ModelResponse:
        return await super().request(messages, model_settings, model_request_parameters)


@pytest.mark.parametrize(
    ("model", "why"),
    [
        pytest.param(lambda: _Wrapping(_answering()), "_Wrapping is not", id="own-wrapper"),
        pytest.param(
            lambda: FallbackModel(_answering()), "a fallback model prepares", id="fallback"
        ),
        pytest.param(
            lambda: WrapperModel(FallbackModel(_answering())),
            "a fallback model prepares",
            id="wrapped-fallback",
        ),
    ],
)
async def test_tools_whose_preparation_cannot_be_computed_are_recorded_as_built_and_marked(
    model: Callable[[], Model], why: str
) -> None:
    """The round is not failed and the entry is not dropped: the tools are kept, marked."""
    sink = FakeDiagnosticSink()
    completer = PydanticAIToolCallingCompleter(model(), diagnostics=sink)

    with diagnosed_activation(_DIAGNOSED, clock=_diagnosed_now):
        response = await completer.respond(_request(), [_tool()])

    assert _bare(response) == RoundResponse(text="ok")
    body = sink.recorded[0].model_dump(mode="json")["body"]
    assert body["read_as_round"] is True
    assert body["offered_tools"][0] == _tool().model_dump(mode="json")
    assert [tool["name"] for tool in body["offered_tools"]] == ["web_search"]
    assert why in body["offered_tools_unprepared"]["message"]


async def test_a_preparation_that_raises_for_the_record_still_writes_the_entry_marked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure computing the tools as prepared never fails the round or drops the entry."""

    def refuse(request: object) -> list[NativeTool]:
        del request
        msg = "cannot prepare"
        raise RuntimeError(msg)

    monkeypatch.setattr(tool_calling, "_prepared", refuse)
    completer, sink = _diagnosing(ThinkingPart("Weighing it…"), finish="length")

    with diagnosed_activation(_DIAGNOSED, clock=_diagnosed_now), pytest.raises(ModelResponseError):
        await completer.respond(_request(), [_tool()])

    body = sink.recorded[0].model_dump(mode="json")["body"]
    assert body["read_as_round"] is False
    assert body["offered_tools"][0] == _tool().model_dump(mode="json")
    assert [tool["name"] for tool in body["offered_tools"]] == ["web_search"]
    assert body["offered_tools_unprepared"] == {
        "class": "RuntimeError",
        "message": "cannot prepare",
    }


# --- #3077: a round's tools and instructions are marked for the provider's cache -------------

_FIVE_MINUTES: Final = {"type": "ephemeral", "ttl": "5m"}


async def test_an_anthropic_round_marks_its_tools_and_instructions_for_caching() -> None:
    """The mark after the last tool caches the tools; the one after the system prompt both."""
    _, body = await _anthropic_round("claude-sonnet-5-5", anthropic_success)
    tools = cast("list[dict[str, Any]]", body["tools"])
    assert [tool["name"] for tool in tools] == ["web_search"]
    assert tools[-1]["cache_control"] == _FIVE_MINUTES
    assert body["system"] == [
        {"type": "text", "text": "You plan one round.", "cache_control": _FIVE_MINUTES}
    ]


async def test_an_anthropic_rounds_messages_are_not_marked() -> None:
    """The user turn is rendered afresh each round, so a mark on it would never be read."""
    _, body = await _anthropic_round("claude-sonnet-5-5", anthropic_success)
    assert "cache_control" not in body
    messages = cast("list[dict[str, Any]]", body["messages"])
    assert all("cache_control" not in block for turn in messages for block in turn["content"])


async def test_a_models_own_one_hour_instructions_are_kept_with_no_mark_before_them() -> None:
    """Anthropic refuses a five-minute entry before a one-hour one, so none is added."""
    settings = AnthropicModelSettings(anthropic_cache_instructions="1h")
    _, body = await _anthropic_round("claude-sonnet-5-5", anthropic_success, settings=settings)
    tools = cast("list[dict[str, Any]]", body["tools"])
    assert all("cache_control" not in tool for tool in tools)
    assert body["system"] == [
        {
            "type": "text",
            "text": "You plan one round.",
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        }
    ]


async def test_a_models_own_one_hour_message_cache_is_kept_with_no_mark_before_it() -> None:
    settings = AnthropicModelSettings(anthropic_cache_messages="1h")
    _, body = await _anthropic_round("claude-sonnet-5-5", anthropic_success, settings=settings)
    tools = cast("list[dict[str, Any]]", body["tools"])
    assert all("cache_control" not in tool for tool in tools)
    assert body["system"] == "You plan one round."
    messages = cast("list[dict[str, Any]]", body["messages"])
    assert messages[-1]["content"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


async def test_an_openai_round_is_given_no_cache_marks() -> None:
    """ADR-0061: the marks are Anthropic's, and another provider's request is as it was."""
    recorder = RequestRecorder(openai_success)
    with network_denied():
        async with httpx.AsyncClient(transport=httpx.MockTransport(recorder)) as http_client:
            client = AsyncOpenAI(api_key=_DUMMY_KEY, http_client=http_client, max_retries=0)
            model = OpenAIChatModel("gpt-4o", provider=OpenAIProvider(openai_client=client))
            await PydanticAIToolCallingCompleter(model).respond(_request(), [_tool()])
    sent = json.dumps(recorder.only)
    assert "cache_control" not in sent
    assert "prompt_cache" not in sent


async def test_a_sonnet_5_5_round_thinks_adaptively_within_a_widened_ceiling() -> None:
    """The default model takes adaptive thinking, never a budget, and no sampling settings."""
    _, body = await _anthropic_round("claude-sonnet-5-5", anthropic_success)
    assert body["thinking"] == {"type": "adaptive"}
    assert body["max_tokens"] == 4096 + 10000
    assert "output_config" not in body
    assert "temperature" not in body


async def test_with_the_record_on_sonnet_5_5_is_asked_for_its_summarised_thinking() -> None:
    """ADR-0314 §5:1 holds on the default model: its adaptive thinking omits the text too."""
    _, body = await _anthropic_round(
        "claude-sonnet-5-5", anthropic_success, diagnostics=FakeDiagnosticSink()
    )
    assert body["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert body["max_tokens"] == 4096 + 10000


def _answered_from_the_cache(request: httpx.Request) -> httpx.Response:
    del request
    return httpx.Response(
        200,
        json={
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-5-5",
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": 900,
                "cache_creation_input_tokens": 120,
                "cache_read_input_tokens": 6800,
                "output_tokens": 40,
            },
        },
    )


async def test_the_returned_entry_keeps_the_cache_read_and_write_tokens() -> None:
    """QA measures the saving from the record: the provider's cache usage reaches it."""
    sink = FakeDiagnosticSink()
    with diagnosed_activation(_DIAGNOSED, clock=_diagnosed_now):
        await _anthropic_round("claude-sonnet-5-5", _answered_from_the_cache, diagnostics=sink)

    usage = sink.recorded[0].model_dump(mode="json")["body"]["response"]["usage"]
    assert usage["cache_read_tokens"] == 6800
    assert usage["cache_write_tokens"] == 120
    assert usage["input_tokens"] == 900 + 120 + 6800
    assert usage["output_tokens"] == 40


# --- the continuing exchange (ADR-0356 §5, §6, §14) --------------------------------------


@dataclass
class _Capturing:
    """A ``FunctionModel`` answering each request in turn, and every history it was sent."""

    answers: list[ModelResponse]
    sent: list[list[ModelMessage]] = field(default_factory=list)

    def answer(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        self.sent.append(list(messages))
        return self.answers[len(self.sent) - 1]

    @property
    def model(self) -> FunctionModel:
        return FunctionModel(self.answer)


def _signed_round() -> ModelResponse:
    """A round with signed thinking, text and two calls, as a provider returns it."""
    return ModelResponse(
        parts=[
            ThinkingPart("Search both days first.", signature="sig-1"),
            TextPart("Checking two days."),
            ToolCallPart("web_search", {"query": "saturday"}, tool_call_id="a"),
            ToolCallPart("web_search", {"query": "sunday"}, tool_call_id="b"),
        ]
    )


def _report(*results: tuple[str, str], news: str = "Nothing has changed.") -> RoundReport:
    return RoundReport(
        results=tuple(CallResult(call_id=one, text=text) for one, text in results), news=news
    )


def _two_results() -> RoundReport:
    return _report(("a", "Saturday: rain."), ("b", "Sunday: sun."))


async def test_a_briefing_alone_is_the_system_part_and_one_user_part() -> None:
    capturing = _Capturing([ModelResponse(parts=[TextPart("ok")])])
    await PydanticAIToolCallingCompleter(capturing.model).respond(_request(), [_tool()])
    ((opening,),) = capturing.sent
    assert isinstance(opening, ModelRequest)
    assert opening.parts == [
        SystemPromptPart("You plan one round.", timestamp=opening.parts[0].timestamp),
        UserPromptPart("what now?", timestamp=opening.parts[1].timestamp),
    ]


async def test_a_round_carries_its_whole_response_as_its_continuation() -> None:
    capturing = _Capturing([_signed_round()])
    model = capturing.model
    response = await PydanticAIToolCallingCompleter(model).respond(_request(), [_tool()])
    assert response.text == "Checking two days."
    assert [call.call_id for call in response.calls] == ["a", "b"]
    assert response.continuation is not None
    assert response.continuation.model == tool_calling.model_id(model)
    (rebuilt,) = ModelMessagesTypeAdapter.validate_python(
        [response.continuation.model_dump(mode="json")["parts"]]
    )
    assert rebuilt.parts[0] == ThinkingPart("Search both days first.", signature="sig-1")


async def test_each_earlier_response_goes_back_as_returned_then_its_results_then_its_news() -> None:
    """§6:2, §5:3: the response as the provider returned it, thinking and signature included;
    its results under their ids in its order; then the news, ending on the cache point."""
    capturing = _Capturing([_signed_round(), ModelResponse(parts=[TextPart("done")])])
    completer = PydanticAIToolCallingCompleter(capturing.model)
    first = await completer.respond(_request(), [_tool()])
    exchange = _request().model_copy(
        update={"steps": (ExchangeStep(response=first, report=_two_results()),)}
    )
    await completer.respond(exchange, [_tool()])
    opening, handed, report = capturing.sent[1]
    assert _turns([opening]) == _turns([capturing.sent[0][0]])
    assert isinstance(handed, ModelResponse)
    assert handed.parts == _signed_round().parts
    assert isinstance(report, ModelRequest)
    returns = [part for part in report.parts if isinstance(part, ToolReturnPart)]
    assert [(part.tool_call_id, part.tool_name, part.content) for part in returns] == [
        ("a", "web_search", "Saturday: rain."),
        ("b", "web_search", "Sunday: sun."),
    ]
    news = report.parts[-1]
    assert isinstance(news, UserPromptPart)
    assert news.content == ["Nothing has changed.", CachePoint()]


async def test_only_the_newest_report_carries_the_cache_point() -> None:
    capturing = _Capturing([ModelResponse(parts=[TextPart("ok")])])
    steps = tuple(
        ExchangeStep(
            response=RoundResponse(
                calls=(ProposedCall(call_id=f"c{index}", name="web_search", arguments={}),)
            ),
            report=_report((f"c{index}", "found"), news=f"news {index}"),
        )
        for index in (1, 2)
    )
    exchange = _request().model_copy(update={"steps": steps})
    await PydanticAIToolCallingCompleter(capturing.model).respond(exchange, [_tool()])
    contents = [
        part.content
        for message in capturing.sent[0]
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart)
    ]
    assert contents == ["what now?", "news 1", ["news 2", CachePoint()]]


def _step(continuation: RoundContinuation | None) -> ExchangeStep:
    return ExchangeStep(
        response=RoundResponse(
            text="Checking two days.",
            calls=(
                ProposedCall(call_id="a", name="web_search", arguments={"query": "saturday"}),
                ProposedCall(call_id="b", name="web_search", arguments={"query": "sunday"}),
            ),
            continuation=continuation,
        ),
        report=_two_results(),
    )


def _whole(response: ModelResponse) -> dict[str, Any]:
    dumped: dict[str, Any] = ModelMessagesTypeAdapter.dump_python([response], mode="json")[0]
    return dumped


def _no_continuation(model: str) -> RoundContinuation | None:
    del model
    return None


def _another_models(model: str) -> RoundContinuation | None:
    del model
    return RoundContinuation(model="anthropic:another-model", parts=_whole(_signed_round()))


def _not_this_response(model: str) -> RoundContinuation | None:
    other = ModelResponse(
        parts=[ThinkingPart("other", signature="x"), TextPart("Checking two days.")]
    )
    return RoundContinuation(model=model, parts=_whole(other))


def _unreadable(model: str) -> RoundContinuation | None:
    return RoundContinuation(model=model, parts={"not": "a response"})


@pytest.mark.parametrize(
    "continuation",
    [
        pytest.param(_no_continuation, id="none"),
        pytest.param(_another_models, id="another-model"),
        pytest.param(_not_this_response, id="not-this-response"),
        pytest.param(_unreadable, id="unreadable"),
    ],
)
async def test_a_response_with_no_usable_continuation_goes_back_as_its_text_and_calls(
    continuation: Callable[[str], RoundContinuation | None],
) -> None:
    """§6:3: sent and answered, with no thinking another model could refuse."""
    capturing = _Capturing([ModelResponse(parts=[TextPart("done")])])
    model = capturing.model
    exchange = _request().model_copy(
        update={"steps": (_step(continuation(tool_calling.model_id(model))),)}
    )
    response = await PydanticAIToolCallingCompleter(model).respond(exchange, [_tool()])
    assert response.text == "done"
    handed = capturing.sent[0][1]
    assert isinstance(handed, ModelResponse)
    assert handed.parts == [
        TextPart("Checking two days."),
        ToolCallPart("web_search", {"query": "saturday"}, tool_call_id="a"),
        ToolCallPart("web_search", {"query": "sunday"}, tool_call_id="b"),
    ]


async def test_a_response_of_nothing_is_left_out_and_its_report_still_goes() -> None:
    capturing = _Capturing([ModelResponse(parts=[TextPart("ok")])])
    step = ExchangeStep(response=RoundResponse(), report=_report(news="An offer opened."))
    exchange = _request().model_copy(update={"steps": (step,)})
    await PydanticAIToolCallingCompleter(capturing.model).respond(exchange, [_tool()])
    assert all(isinstance(message, ModelRequest) for message in capturing.sent[0])
    assert _turns(capturing.sent[0])[-1] == ("user", "An offer opened.")


async def test_a_models_own_cache_settings_leave_the_newest_report_unmarked() -> None:
    """A five-minute point before a model's own one-hour mark would be refused."""
    seen: list[list[ModelMessage]] = []

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        seen.append(list(messages))
        return ModelResponse(parts=[TextPart("ok")])

    model = FunctionModel(answer, settings=AnthropicModelSettings(anthropic_cache_messages="1h"))
    exchange = _request().model_copy(update={"steps": (_step(None),)})
    await PydanticAIToolCallingCompleter(model).respond(exchange, [_tool()])
    last = seen[0][-1]
    assert isinstance(last, ModelRequest)
    news = last.parts[-1]
    assert isinstance(news, UserPromptPart)
    assert news.content == "Nothing has changed."


async def test_on_anthropics_wire_the_thinking_goes_back_signed_and_the_report_is_marked() -> None:
    """The round trip through Anthropic's real SDK: §6:2's thinking, §13's cache mark."""
    recorder = RequestRecorder(_thinking_then_text_and_a_call)
    answered = RequestRecorder(anthropic_success)
    with network_denied():
        async with httpx.AsyncClient(transport=httpx.MockTransport(recorder)) as first_client:
            first = await PydanticAIToolCallingCompleter(
                _anthropic("claude-opus-4-8", first_client)
            ).respond(_request(), [_tool()])
        step = ExchangeStep(response=first, report=_report(("toolu_1", "Watchman: booked.")))
        exchange = _request().model_copy(update={"steps": (step,)})
        async with httpx.AsyncClient(transport=httpx.MockTransport(answered)) as second_client:
            await PydanticAIToolCallingCompleter(
                _anthropic("claude-opus-4-8", second_client)
            ).respond(exchange, [_tool()])
    messages = cast("list[dict[str, Any]]", answered.only["messages"])
    assert [turn["role"] for turn in messages] == ["user", "assistant", "user"]
    assistant = messages[1]["content"]
    assert assistant[0] == {
        "type": "thinking",
        "thinking": "The user has answered my question; book Watchman.",
        "signature": "sig",
    }
    assert assistant[1] == {"type": "redacted_thinking", "data": "opaque"}
    assert [block["type"] for block in assistant[2:]] == ["text", "tool_use"]
    report = messages[2]["content"]
    assert report[0]["type"] == "tool_result"
    assert report[0]["tool_use_id"] == "toolu_1"
    assert report[-1]["text"] == "Nothing has changed."
    assert report[-1]["cache_control"] == _FIVE_MINUTES
    assert all("cache_control" not in block for block in messages[0]["content"])
