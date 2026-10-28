"""A structured call's thinking summary: what is asked for, and what comes back (ADR-0355).

The request cases run over the real ``anthropic`` and ``openai`` SDKs with only the
transport replaced (ADR-0061 §3), since what a request carries is only honestly seen
on the wire: a provider built without ``thinking_summaries`` sends, byte for byte, the
body the base tree sent (§2:2), and one built with it differs only where §3 says. The
reading cases run over a pydantic-ai ``FunctionModel`` and over the Anthropic SDK:
the summary is the thinking parts' text, kept on the exchange and out of the reply,
the value and any failure (§4:1, §4:2).
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

import httpx
import pytest
from anthropic import AsyncAnthropic
from network_guard import network_denied
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai.messages import ModelResponse, TextPart, ThinkingPart, ToolCallPart
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import RequestUsage

from ai_assistant.core.types import Message, ReplyFailure, Role, StructuredReply
from ai_assistant.models import PydanticAIProvider
from ai_assistant.models.structured import THINKS_UNASKED

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator

    from pydantic_ai.messages import FinishReason, ModelMessage
    from pydantic_ai.models import Model


@pytest.fixture(autouse=True)
def _no_network() -> Iterator[None]:
    """Deny egress for every test in this module, as the vendor suites do."""
    with network_denied():
        yield


class _Answer(BaseModel):
    """Which answer, and how sure. Text the schema never carries."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(description="The answer.")
    confidence: int = Field(description="From 1 to 5.")


_CONVERSATION: Final = (
    Message(role=Role.SYSTEM, content="Answer the question."),
    Message(role=Role.USER, content="Is the sky blue?"),
)
_REPLY: Final = '{"answer": "yes", "confidence": 4}'
_VALUE: Final = _Answer(answer="yes", confidence=4)

#: Anthropic's configuration a request keeping the summary carries (§3:1).
_SUMMARISED: Final = {"type": "adaptive", "display": "summarized"}

# What the base tree, `71f14b323`, put on the wire for `_CONVERSATION` asking for
# `_Answer` through a provider with no thinking setting (§8:1's first item). Captured
# from that tree's own `src/`, not written by hand: a change to either byte string is a
# change to a request this decision promised to leave alone.

#: ``claude-sonnet-5-5``, which pydantic-ai's profile sends in native mode.
_BASE_SONNET_5_5_NATIVE: Final = (
    b'{"max_tokens":4096,"messages":[{"role":"user","content":[{"text":"Is the sky blue?",'
    b'"type":"text"}]}],"model":"claude-sonnet-5-5","output_config":{"format":{"type":'
    b'"json_schema","schema":{"type":"object","properties":{"answer":{"type":"string"},'
    b'"confidence":{"type":"integer"}},"additionalProperties":false,"required":["answer",'
    b'"confidence"]}}},"stream":false,"system":[{"type":"text","text":"Answer the question.",'
    b'"cache_control":{"type":"ephemeral","ttl":"5m"}}]}'
)

#: ``claude-opus-5-5``, which pydantic-ai's profile sends in prompted mode.
_BASE_OPUS_5_5_PROMPTED: Final = (
    b'{"max_tokens":4096,"messages":[{"role":"user","content":[{"text":"Is the sky blue?",'
    b'"type":"text"}]}],"model":"claude-opus-5-5","stream":false,"system":[{"type":"text",'
    b'"text":"Answer the question."},{"type":"text","text":"Reply with one JSON object and '
    b'nothing else, matching this JSON schema:\\n\\n{\\"additionalProperties\\": false, '
    b'\\"properties\\": {\\"answer\\": {\\"type\\": \\"string\\"}, \\"confidence\\": '
    b'{\\"type\\": \\"integer\\"}}, \\"required\\": [\\"answer\\", \\"confidence\\"], '
    b'\\"type\\": \\"object\\"}","cache_control":{"type":"ephemeral","ttl":"5m"}}]}'
)


# --- the wire -----------------------------------------------------------------


@dataclass
class _Wire:
    """Every request a vendor SDK put on the wire, answered with one canned body."""

    answer: dict[str, Any]
    requests: list[httpx.Request] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json=self.answer)

    @property
    def only(self) -> httpx.Request:
        assert len(self.requests) == 1, f"expected one request, got {len(self.requests)}"
        return self.requests[0]


def _anthropic_body(
    model_name: str, content: list[dict[str, Any]] | None = None, *, stop: str = "end_turn"
) -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model_name,
        "content": [{"type": "text", "text": _REPLY}] if content is None else content,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


_OPENAI_BODY: Final = {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "created": 1,
    "model": "gpt-5",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": _REPLY},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


@contextlib.asynccontextmanager
async def _anthropic(
    wire: _Wire, model_name: str, settings: AnthropicModelSettings | None = None
) -> AsyncIterator[AnthropicModel]:
    async with httpx.AsyncClient(transport=httpx.MockTransport(wire)) as http_client:
        client = AsyncAnthropic(
            api_key="test-key-not-a-credential", http_client=http_client, max_retries=0
        )
        yield AnthropicModel(
            model_name, provider=AnthropicProvider(anthropic_client=client), settings=settings
        )


@contextlib.asynccontextmanager
async def _openai(wire: _Wire) -> AsyncIterator[OpenAIChatModel]:
    async with httpx.AsyncClient(transport=httpx.MockTransport(wire)) as http_client:
        client = AsyncOpenAI(
            api_key="test-key-not-a-credential", http_client=http_client, max_retries=0
        )
        yield OpenAIChatModel("gpt-5", provider=OpenAIProvider(openai_client=client))


type _Opener = contextlib.AbstractAsyncContextManager[Model]


async def _structured_request(
    opened: Callable[[_Wire], _Opener], answer: dict[str, Any], **built: bool
) -> tuple[httpx.Request, StructuredReply[_Answer]]:
    wire = _Wire(answer)
    async with opened(wire) as model:
        reply = await PydanticAIProvider(model, **built).complete_structured(
            list(_CONVERSATION), _Answer
        )
    return wire.only, reply


def _on_anthropic(
    model_name: str, settings: AnthropicModelSettings | None = None
) -> Callable[[_Wire], _Opener]:
    return lambda wire: _anthropic(wire, model_name, settings)


def _wrapped_anthropic(model_name: str) -> Callable[[_Wire], _Opener]:
    @contextlib.asynccontextmanager
    async def opened(wire: _Wire) -> AsyncIterator[Model]:
        async with _anthropic(wire, model_name) as model:
            yield WrapperModel(model)

    return opened


def _beta(request: httpx.Request) -> tuple[str, str | None]:
    """What a request says of Anthropic's betas: its URL, and its beta header."""
    return str(request.url), request.headers.get("anthropic-beta")


# --- §2:2: kept off, the request is the base tree's, byte for byte ----------------


@pytest.mark.parametrize(
    ("model_name", "pinned"),
    [
        pytest.param("claude-sonnet-5-5", _BASE_SONNET_5_5_NATIVE, id="sonnet-5-5-native"),
        pytest.param("claude-opus-5-5", _BASE_OPUS_5_5_PROMPTED, id="opus-5-5-prompted"),
    ],
)
@pytest.mark.parametrize(
    "built",
    [pytest.param({}, id="by-default"), pytest.param({"thinking_summaries": False}, id="false")],
)
async def test_a_provider_not_keeping_summaries_sends_the_base_trees_body(
    model_name: str, pinned: bytes, built: dict[str, bool]
) -> None:
    sent, reply = await _structured_request(
        _on_anthropic(model_name), _anthropic_body(model_name), **built
    )
    assert sent.content == pinned
    assert sent.headers.get("anthropic-beta") is None
    assert reply.value == _VALUE
    assert reply.exchange.thinking is None


# --- §3:1, §3:5: kept on, one key alone -------------------------------------------


@pytest.mark.parametrize(
    "model_name",
    [
        pytest.param("claude-sonnet-5-5", id="sonnet-5-5-native"),
        pytest.param("claude-opus-5-5", id="opus-5-5-prompted"),
    ],
)
async def test_a_provider_keeping_summaries_adds_the_summarised_configuration_alone(
    model_name: str,
) -> None:
    off, _ = await _structured_request(
        _on_anthropic(model_name), _anthropic_body(model_name), thinking_summaries=False
    )
    on, reply = await _structured_request(
        _on_anthropic(model_name), _anthropic_body(model_name), thinking_summaries=True
    )
    sent_off = json.loads(off.content)
    sent_on = json.loads(on.content)
    assert sent_on.pop("thinking") == _SUMMARISED
    assert sent_on == sent_off
    # Spelled out, so a reading of "the same" that let these move cannot pass.
    assert "effort" not in sent_on.get("output_config", {})
    assert sent_on["max_tokens"] == sent_off["max_tokens"]
    assert _beta(on) == _beta(off)
    assert reply.value == _VALUE


async def test_a_model_that_wraps_a_listed_anthropic_model_asks_too() -> None:
    sent, _ = await _structured_request(
        _wrapped_anthropic("claude-sonnet-5-5"),
        _anthropic_body("claude-sonnet-5-5"),
        thinking_summaries=True,
    )
    assert json.loads(sent.content)["thinking"] == _SUMMARISED


def test_the_models_are_the_ones_anthropic_documents_as_thinking_unasked() -> None:
    """§3:2's closed tuple, matched exactly: a name is added only with the vendor's word."""
    assert THINKS_UNASKED == (
        "claude-opus-5-5",
        "claude-opus-5",
        "claude-sonnet-5-5",
        "claude-sonnet-5",
        "claude-haiku-5-5",
        "claude-fable-5-1",
        "claude-fable-5",
        "claude-mythos-5-1",
        "claude-mythos-5",
        "claude-mythos-preview",
    )


# --- §3:4: everywhere else, the request it sends anyway ---------------------------


_UNCHANGED: Final = [
    pytest.param(_on_anthropic("claude-opus-4-8"), "claude-opus-4-8", id="opus-4-8"),
    pytest.param(_on_anthropic("claude-sonnet-4-6"), "claude-sonnet-4-6", id="sonnet-4-6"),
    pytest.param(
        _on_anthropic("claude-sonnet-5-5-20261001"),
        "claude-sonnet-5-5-20261001",
        id="a-listed-name-not-matched-exactly",
    ),
    pytest.param(
        _on_anthropic("claude-sonnet-5-5", {"anthropic_thinking": {"type": "adaptive"}}),
        "claude-sonnet-5-5",
        id="listed-with-its-own-anthropic-thinking",
    ),
    pytest.param(
        _on_anthropic("claude-sonnet-5-5", {"thinking": "low"}),
        "claude-sonnet-5-5",
        id="listed-with-its-own-unified-thinking",
    ),
    pytest.param(
        _on_anthropic("claude-sonnet-5-5", {"thinking": False}),
        "claude-sonnet-5-5",
        id="listed-with-its-unified-thinking-off",
    ),
]


@pytest.mark.parametrize(("opened", "model_name"), _UNCHANGED)
async def test_elsewhere_a_provider_keeping_summaries_sends_the_request_it_would_anyway(
    opened: Callable[[_Wire], _Opener], model_name: str
) -> None:
    off, _ = await _structured_request(
        opened, _anthropic_body(model_name), thinking_summaries=False
    )
    on, _ = await _structured_request(opened, _anthropic_body(model_name), thinking_summaries=True)
    assert on.content == off.content
    assert _beta(on) == _beta(off)


async def test_an_openai_request_is_the_request_it_would_be_anyway() -> None:
    off, _ = await _structured_request(_openai, _OPENAI_BODY, thinking_summaries=False)
    on, reply = await _structured_request(_openai, _OPENAI_BODY, thinking_summaries=True)
    assert on.content == off.content
    assert reply.value == _VALUE


@pytest.mark.parametrize("thinking_summaries", [False, True], ids=["off", "on"])
async def test_a_plain_completion_is_the_same_whether_summaries_are_kept_or_not(
    thinking_summaries: bool,
) -> None:
    """§2:1: the argument bears on ``complete_structured`` alone."""
    bodies: list[bytes] = []
    for built in (False, thinking_summaries):
        wire = _Wire(_anthropic_body("claude-sonnet-5-5"))
        async with _anthropic(wire, "claude-sonnet-5-5") as model:
            await PydanticAIProvider(model, thinking_summaries=built).complete(list(_CONVERSATION))
        bodies.append(wire.only.content)
    assert bodies[0] == bodies[1]
    assert b'"thinking"' not in bodies[1]


# --- §4:1: what comes back, over the Anthropic SDK ---------------------------------


async def test_anthropics_summarised_thinking_comes_back_on_the_exchange() -> None:
    content = [
        {"type": "thinking", "thinking": "The sky scatters blue light.", "signature": "s1"},
        {"type": "redacted_thinking", "data": "opaque"},
        {"type": "thinking", "thinking": "", "signature": "s2"},
        {"type": "text", "text": _REPLY},
    ]
    _, reply = await _structured_request(
        _on_anthropic("claude-sonnet-5-5"),
        _anthropic_body("claude-sonnet-5-5", content),
        thinking_summaries=True,
    )
    assert reply.value == _VALUE
    assert reply.exchange.reply == _REPLY
    assert reply.exchange.thinking == "The sky scatters blue light."


async def test_an_omitted_display_comes_back_as_no_summary() -> None:
    content = [
        {"type": "thinking", "thinking": "", "signature": "s1"},
        {"type": "text", "text": _REPLY},
    ]
    _, reply = await _structured_request(
        _on_anthropic("claude-sonnet-5-5"),
        _anthropic_body("claude-sonnet-5-5", content),
        thinking_summaries=True,
    )
    assert reply.exchange.thinking is None


# --- §4:1, §4:2: what comes back, over a scripted model ----------------------------


async def _answer(
    *parts: TextPart | ThinkingPart | ToolCallPart,
    finish: FinishReason = "stop",
    thinking_summaries: bool = True,
) -> StructuredReply[_Answer]:
    # A usage of its own, so the reported tokens are not estimated from the parts.
    usage = RequestUsage(input_tokens=3, output_tokens=2)
    response = ModelResponse(parts=list(parts), usage=usage, finish_reason=finish)

    async def respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return response

    provider = PydanticAIProvider(FunctionModel(respond), thinking_summaries=thinking_summaries)
    return await provider.complete_structured(list(_CONVERSATION), _Answer)


def _without_thinking(reply: StructuredReply[_Answer]) -> StructuredReply[_Answer]:
    return reply.model_copy(
        update={"exchange": reply.exchange.model_copy(update={"thinking": None})}
    )


_THOUGHT: Final = ThinkingPart(content=_REPLY)  # thinking that would read as the shape

_OUTCOMES: Final = [
    pytest.param([TextPart(content=_REPLY)], "stop", None, id="valid"),
    pytest.param([TextPart(content=_REPLY)], "content_filter", ReplyFailure.REFUSED, id="refused"),
    pytest.param([TextPart(content='{"answer": ')], "length", ReplyFailure.CUT, id="cut"),
    pytest.param([], "stop", ReplyFailure.EMPTY, id="empty"),
    pytest.param([TextPart(content="nope")], "stop", ReplyFailure.INVALID, id="invalid"),
    pytest.param(
        [
            TextPart(content=_REPLY),
            ToolCallPart(tool_name="final_result", args={}, tool_call_id="c1"),
        ],
        "stop",
        ReplyFailure.INVALID,
        id="invalid-by-a-call",
    ),
]


@pytest.mark.parametrize("thinking_summaries", [True, False], ids=["kept", "not-kept"])
@pytest.mark.parametrize(("parts", "finish", "failure"), _OUTCOMES)
async def test_thinking_parts_change_no_reply_value_or_failure(
    parts: list[TextPart | ToolCallPart],
    finish: FinishReason,
    failure: ReplyFailure | None,
    thinking_summaries: bool,
) -> None:
    without = await _answer(*parts, finish=finish, thinking_summaries=thinking_summaries)
    with_ = await _answer(
        _THOUGHT,
        *parts,
        ThinkingPart(content="and how sure"),
        finish=finish,
        thinking_summaries=thinking_summaries,
    )
    assert without.failure is failure
    assert (without.value is None) == (failure is not None)
    assert _without_thinking(with_) == without
    assert with_.exchange.reply == without.exchange.reply


async def test_the_summary_is_the_parts_text_in_order_joined_by_a_blank_line() -> None:
    reply = await _answer(
        ThinkingPart(content="First."),
        TextPart(content='{"answer": "yes", '),
        ThinkingPart(content=""),
        ThinkingPart(content="", signature="redacted", id="redacted_thinking"),
        ThinkingPart(content="Second,\nin two lines."),
        TextPart(content='"confidence": 4}'),
    )
    assert reply.value == _VALUE
    assert reply.exchange.thinking == "First.\n\nSecond,\nin two lines."


async def test_no_part_with_text_is_no_summary() -> None:
    reply = await _answer(ThinkingPart(content=""), TextPart(content=_REPLY))
    assert reply.exchange.thinking is None
    assert (await _answer(TextPart(content=_REPLY))).exchange.thinking is None


async def test_a_provider_not_keeping_summaries_keeps_none_even_where_a_part_has_text() -> None:
    reply = await _answer(
        ThinkingPart(content="The sky scatters blue light."),
        TextPart(content=_REPLY),
        thinking_summaries=False,
    )
    assert reply.value == _VALUE
    assert reply.exchange.thinking is None


async def test_a_summary_no_record_can_hold_is_kept_with_its_replacement() -> None:
    reply = await _answer(ThinkingPart(content="half \ud800 a pair"), TextPart(content=_REPLY))
    assert reply.exchange.thinking == "half � a pair"
    assert reply.value == _VALUE
