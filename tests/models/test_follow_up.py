"""The follow-up question: its prompt, and the seam asking it of a planning round (ADR-0337 §6).

What the default says is not pinned here (ADR-0334 §9:1): the regression suite judges
what a reply does, and a promotion's review reads the wording.

As in ``test_tool_calling_replay``, a ``FunctionModel`` is the world, and where the
vendor decides the request's shape it is read off the wire of Anthropic's real SDK over
a mock transport, with the network denied.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import httpx
import pytest
from anthropic import AsyncAnthropic
from network_guard import network_denied
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import (
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
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from vendor_stacks import RequestRecorder, anthropic_success

import ai_assistant
from ai_assistant.core.diagnostics import (
    diagnosed_activation,
    diagnosed_activation_id,
    returned_written,
)
from ai_assistant.core.errors import ModelError, ModelRateLimitError
from ai_assistant.core.prompts import PromptOrigin
from ai_assistant.core.types import (
    CallResult,
    DiagnosticSource,
    ExchangeStep,
    OfferedTool,
    PlanningExchange,
    ProposedCall,
    RoundReport,
    RoundResponse,
)
from ai_assistant.models.follow_up import FOLLOW_UP_PROMPT, NOT_RUN, follow_up_round
from ai_assistant.testing import default_prompt

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage, ModelResponsePart
    from pydantic_ai.models import Model

_DUMMY_KEY: Final = "test-key-not-a-credential"
_ACTIVATION: Final = "3f0c2a8e-1b7d-4c55-9e21-6a4b8d0f1e2c"
_QUESTION: Final = "What did you have to guess?"


def _now() -> datetime:
    return datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


def _request() -> tuple[PlanningExchange, list[OfferedTool]]:
    return (
        PlanningExchange(instruction="The round's instruction.", briefing="book me a stay"),
        [
            OfferedTool(
                name="web_search",
                description="Search the web.",
                parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            )
        ],
    )


def _followed(*parts: ModelResponsePart) -> dict[str, Any]:
    """A followed round's whole response, as planning's returned entry keeps it."""
    response = ModelResponse(parts=list(parts), model_name="claude-sonnet-5-5")
    dumped: dict[str, Any] = ModelMessagesTypeAdapter.dump_python([response], mode="json")[0]
    return dumped


_PROPOSING: Final = (
    ThinkingPart("Search first.", signature="sig-1", provider_name="anthropic"),
    TextPart("Looking now."),
    ToolCallPart("web_search", {"query": "stays"}, tool_call_id="a"),
)


class _World:
    """A ``FunctionModel`` answering with fixed parts, keeping each request it was sent."""

    def __init__(self, *parts: ModelResponsePart) -> None:
        self.parts = list(parts) or [TextPart("I had to guess the dates.")]
        self.sent: list[list[ModelMessage]] = []
        self.tools: list[list[str]] = []
        self.bound: list[str | None] = []
        self.model = FunctionModel(self.answer)

    def answer(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.sent.append(messages)
        self.tools.append([one.name for one in info.function_tools])
        self.bound.append(diagnosed_activation_id())
        return ModelResponse(parts=list(self.parts))


def _never() -> FunctionModel:
    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        msg = "a model was asked"
        raise AssertionError(msg)

    return FunctionModel(answer)


async def _ask(model: Model, response: dict[str, Any] | None = None) -> str:
    exchange, tools = _request()
    followed = _followed(*_PROPOSING) if response is None else response
    return await follow_up_round(exchange, tools, followed, _QUESTION, model=model)


# --- §6:1: the prompt ---------------------------------------------------------------------------


def test_it_declares_no_flag_and_no_value() -> None:
    assert FOLLOW_UP_PROMPT.name == "follow_up"
    assert FOLLOW_UP_PROMPT.flags == frozenset()
    assert FOLLOW_UP_PROMPT.values == frozenset()


def test_its_default_ships_beside_the_module_and_renders() -> None:
    template = default_prompt(FOLLOW_UP_PROMPT)

    assert FOLLOW_UP_PROMPT.package == "ai_assistant.models"
    assert template.origin is PromptOrigin.DEFAULT
    assert template.render(flags={}, values={}).strip()


# --- §6:3, §6:4, §6:6: the round's request, its whole response, each call closed, the question


async def test_the_request_is_the_rounds_then_its_whole_response_then_each_call_closed() -> None:
    world = _World()

    await _ask(world.model)

    (sent,) = world.sent
    first, response, closing = sent
    assert isinstance(first, ModelRequest)
    assert [type(one) for one in first.parts] == [SystemPromptPart, UserPromptPart]
    assert isinstance(response, ModelResponse)
    assert response.parts[0] == ThinkingPart(
        "Search first.", signature="sig-1", provider_name="anthropic"
    )
    assert [type(one) for one in response.parts] == [ThinkingPart, TextPart, ToolCallPart]
    assert isinstance(closing, ModelRequest)
    returns = [one for one in closing.parts if isinstance(one, ToolReturnPart)]
    assert [(one.tool_call_id, one.tool_name, one.content) for one in returns] == [
        ("a", "web_search", NOT_RUN),
    ]
    last = closing.parts[-1]
    assert isinstance(last, UserPromptPart)
    assert last.content == _QUESTION
    # The offered tools stay in the request, and no other is added (ADR-0356 §7:4).
    assert world.tools == [["web_search"]]


async def test_a_response_that_proposed_no_call_is_followed_by_the_question_alone() -> None:
    world = _World()

    await _ask(world.model, _followed(TextPart("Here are two stays.")))

    closing = world.sent[0][-1]
    assert isinstance(closing, ModelRequest)
    assert [type(one) for one in closing.parts] == [UserPromptPart]


def _anthropic(name: str, http_client: httpx.AsyncClient) -> Model:
    client = AsyncAnthropic(api_key=_DUMMY_KEY, http_client=http_client, max_retries=0)
    return AnthropicModel(name, provider=AnthropicProvider(anthropic_client=client))


async def test_on_anthropics_wire_the_thinking_goes_back_signed_and_each_call_has_a_result() -> (
    None
):
    recorder = RequestRecorder(anthropic_success)
    with network_denied():
        async with httpx.AsyncClient(transport=httpx.MockTransport(recorder)) as http_client:
            answer = await _ask(_anthropic("claude-sonnet-5-5", http_client))

    body: dict[str, Any] = recorder.only
    assert answer == "anthropic reply"
    assert body["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert [one["name"] for one in body["tools"]] == ["web_search"]
    turns = body["messages"]
    assert [turn["role"] for turn in turns] == ["user", "assistant", "user"]
    said = turns[1]["content"]
    assert said[0] == {"type": "thinking", "thinking": "Search first.", "signature": "sig-1"}
    assert [one["type"] for one in said] == ["thinking", "text", "tool_use"]
    closing = turns[2]["content"]
    assert [(one["type"], one.get("tool_use_id")) for one in closing] == [
        ("tool_result", "a"),
        ("text", None),
    ]
    assert closing[-1]["text"] == _QUESTION


# --- §6:5: the answer as text, nothing run ------------------------------------------------------


async def test_it_returns_the_answers_text_and_runs_no_call_it_proposes() -> None:
    world = _World(
        TextPart("I had to guess the dates."),
        ToolCallPart("web_search", {"query": "more"}, tool_call_id="b"),
    )

    answer = await _ask(world.model)

    assert answer == "I had to guess the dates."
    assert len(world.sent) == 1


async def test_an_answer_with_no_text_is_empty() -> None:
    world = _World(ToolCallPart("web_search", {"query": "more"}, tool_call_id="b"))

    assert await _ask(world.model) == ""


# --- ADR-0335 §4:9: no entry, no activation bound ------------------------------------------------


async def test_it_writes_no_entry_and_binds_no_activation() -> None:
    world = _World()

    with diagnosed_activation(_ACTIVATION, clock=_now):
        before = returned_written(DiagnosticSource.PLANNING)
        await _ask(world.model)
        after = returned_written(DiagnosticSource.PLANNING)
    await _ask(world.model)

    assert after == before
    assert world.bound[1] is None


# --- ADR-0335 §4:7: one named model, no fallback, a failure classified ----------------------------


@pytest.mark.parametrize("wrapped", [False, True], ids=["bare", "wrapped"])
async def test_a_fallback_model_is_refused_before_any_model_is_asked(wrapped: bool) -> None:
    model: Model = FallbackModel(_never(), _never())
    if wrapped:
        model = WrapperModel(model)

    with pytest.raises(ModelError) as caught:
        await _ask(model)

    assert type(caught.value) is ModelError


async def test_a_failure_is_classified_and_no_other_model_is_asked() -> None:
    calls: list[int] = []

    def refuse(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        calls.append(1)
        raise ModelHTTPError(status_code=429, model_name="named")

    with pytest.raises(ModelRateLimitError):
        await _ask(FunctionModel(refuse))

    assert calls == [1]


@pytest.mark.parametrize(
    "response",
    [
        {"parts": "none", "kind": "response"},
        {"parts": [{"part_kind": "user-prompt", "content": "x"}], "kind": "request"},
        {},
    ],
    ids=["unreadable", "a-request", "empty"],
)
async def test_a_followed_response_that_is_none_is_refused_before_any_model(
    response: dict[str, Any],
) -> None:
    with pytest.raises(ModelError) as caught:
        await _ask(_never(), response)

    assert type(caught.value) is ModelError


async def test_a_blank_question_or_two_tools_of_one_name_are_refused_before_any_model() -> None:
    exchange, tools = _request()
    followed = _followed(*_PROPOSING)

    with pytest.raises(ModelError):
        await follow_up_round(exchange, tools, followed, "  ", model=_never())
    with pytest.raises(ModelError):
        await follow_up_round(exchange, [*tools, *tools], followed, _QUESTION, model=_never())


async def test_the_request_is_the_rounds_whole_exchange_before_the_followed_response() -> None:
    """ADR-0356 §13: the follow-up sends the round's exchange, as `respond` sends it."""
    world = _World()
    exchange, tools = _request()
    step = ExchangeStep(
        response=RoundResponse(
            text="First, the dates.",
            calls=(ProposedCall(call_id="e", name="web_search", arguments={"query": "dates"}),),
        ),
        report=RoundReport(
            results=(CallResult(call_id="e", text="14 November."),), news="Nothing changed."
        ),
    )
    stepped = exchange.model_copy(update={"steps": (step,)})

    await follow_up_round(stepped, tools, _followed(*_PROPOSING), _QUESTION, model=world.model)

    (sent,) = world.sent
    assert [type(one) for one in sent] == [ModelRequest, ModelResponse] * 2 + [ModelRequest]
    report = sent[2]
    assert isinstance(report, ModelRequest)
    returns = [one for one in report.parts if isinstance(one, ToolReturnPart)]
    assert [(one.tool_call_id, one.content) for one in returns] == [("e", "14 November.")]
    news = report.parts[-1]
    assert isinstance(news, UserPromptPart)
    assert news.content == "Nothing changed."


# --- ADR-0335 §4:9: no stage calls it -------------------------------------------------------

_ROOT: Final = Path(ai_assistant.__file__).resolve().parent

#: The one module that may name the seam: its own, where the hub-side asker is to live.
_HOME: Final = Path("models/follow_up.py")


def test_nothing_in_the_package_but_its_own_module_names_the_seam() -> None:
    # Textual on purpose, as test_tool_calling_replay's own check of its seam.
    naming = {
        path.relative_to(_ROOT)
        for path in sorted(_ROOT.rglob("*.py"))
        if "follow_up_round" in path.read_text(encoding="utf-8")
    }

    assert naming == {_HOME}
