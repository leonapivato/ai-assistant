"""Structured calls over the real ``anthropic`` and ``openai`` SDKs, offline (ADR-0061 §3).

The shared ``StructuredCompleter`` suite runs here over each vendor's real SDK with
only the transport replaced, as ``test_provider_vendors.py`` runs the
``ModelProvider`` suite (see ``vendor_stacks.py`` for why that shape proves what a
pydantic-ai test double cannot). The cases after it pin what only the wire shows
(ADR-0354 §12:5): that the request body carries the schema in the vendor's native
field, that a canned refusal comes back ``refused`` with its statement, and that the
cache marks are on an Anthropic model's request in both modes and on no other's.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, cast

import httpx
import pytest
from anthropic import AsyncAnthropic
from model_provider_contract import ConversationLog, FirstAwaitGate
from network_guard import network_denied
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from structured_completer_contract import (
    REFUSAL,
    REFUSAL_CATEGORY,
    VALID_REPLY,
    VALID_VALUE,
    Answer,
    StructuredCompleterContract,
    Verdict,
    request,
    seen_reply,
)
from vendor_stacks import ANTHROPIC, OPENAI, RequestRecorder, VendorStack

from ai_assistant.core.reply_shapes import reply_schema
from ai_assistant.core.types import ReplyFailure, ReplyMode, ReplyUsage, Role, StructuredReply
from ai_assistant.models import PydanticAIProvider

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from vendor_stacks import Handler

    from ai_assistant.core.protocols import StructuredCompleter
    from ai_assistant.testing.cancellation import SuspendedCall

#: The models each vendor stack names, as its canned responses answer for them.
_ANTHROPIC_MODEL: Final = "claude-sonnet-4-5"
_OPENAI_MODEL: Final = "gpt-5"

#: An Anthropic model name pydantic-ai's profile gives no JSON-schema output, and no
#: deprecation notice.
_ANTHROPIC_WITHOUT_NATIVE: Final = "claude-without-schema-output"

_ANTHROPIC_STOP: Final = {"stop": "end_turn", "length": "max_tokens", "refused": "refusal"}
_OPENAI_FINISH: Final = {"stop": "stop", "length": "length", "refused": "stop"}


@pytest.fixture(autouse=True)
def _no_network() -> Iterator[None]:
    """Deny egress for every test in this module, as ``test_provider_vendors.py`` does."""
    with network_denied():
        yield


def anthropic_answer(answer: Answer, *, model: str = _ANTHROPIC_MODEL) -> dict[str, Any]:
    """``answer`` as an Anthropic Messages response body."""
    usage = answer.usage
    body: dict[str, Any] = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": answer.reply}] if answer.reply else [],
        "stop_reason": _ANTHROPIC_STOP[answer.ending],
        "stop_sequence": None,
        "usage": {
            # Anthropic counts its uncached input apart from what the cache read and
            # wrote; pydantic-ai reports their sum as the input.
            "input_tokens": usage.input_tokens - usage.cache_read_tokens - usage.cache_write_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_input_tokens": usage.cache_read_tokens,
            "cache_creation_input_tokens": usage.cache_write_tokens,
        },
    }
    if answer.ending == "refused":
        body["stop_details"] = {
            "type": "refusal",
            "category": REFUSAL_CATEGORY,
            "explanation": answer.refusal,
        }
    return body


def openai_answer(answer: Answer) -> dict[str, Any]:
    """``answer`` as an OpenAI chat-completions response body."""
    refused = answer.ending == "refused"
    usage = answer.usage
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1,
        "model": _OPENAI_MODEL,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None if refused else answer.reply,
                    "refusal": answer.refusal if refused else None,
                },
                "finish_reason": _OPENAI_FINISH[answer.ending],
            }
        ],
        "usage": {
            "prompt_tokens": usage.input_tokens,
            "completion_tokens": usage.output_tokens,
            "total_tokens": usage.input_tokens + usage.output_tokens,
            "prompt_tokens_details": {"cached_tokens": usage.cache_read_tokens},
        },
    }


def _answering(vendor: VendorStack, answer: Answer) -> Handler:
    body = anthropic_answer(answer) if vendor is ANTHROPIC else openai_answer(answer)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    return handler


@dataclass
class _VendorWorld:
    completer: StructuredCompleter
    recorder: RequestRecorder
    answered_by: str
    mode: ReplyMode = ReplyMode.NATIVE

    @property
    def attempts(self) -> int:
        return len(self.recorder.bodies)


class _VendorStructuredContract(StructuredCompleterContract):
    """The shared suite, bound to one real vendor stack."""

    vendor: VendorStack
    answered_by: str

    @pytest.fixture
    async def completer(self) -> AsyncIterator[StructuredCompleter]:
        async with self.vendor.opened(_answering(self.vendor, Answer(VALID_REPLY))) as model:
            yield PydanticAIProvider(model)

    @contextlib.asynccontextmanager
    async def world(self, answer: Answer) -> AsyncIterator[_VendorWorld]:
        recorder = RequestRecorder(_answering(self.vendor, answer))
        async with self.vendor.opened(recorder) as model:
            yield _VendorWorld(PydanticAIProvider(model), recorder, self.answered_by)

    @contextlib.asynccontextmanager
    async def completer_suspended_at_its_first_await(
        self,
    ) -> AsyncIterator[tuple[StructuredCompleter, SuspendedCall, ConversationLog]]:
        # Input observation happens before the wire, so the transport itself holds the
        # request at the call's one await; the subject is a genuine vendor-backed one.
        log = ConversationLog()
        gate = FirstAwaitGate()
        vendor = self.vendor

        async def held(request_: httpx.Request) -> httpx.Response:
            turns = vendor.transcript(json.loads(request_.content))
            log.record(tuple((Role(role), text, None) for role, text in turns))
            await gate.hold()
            answer = Answer(seen_reply([text for _role, text in turns]))
            return _answering(vendor, answer)(request_)

        async with httpx.AsyncClient(transport=httpx.MockTransport(held)) as http_client:
            yield PydanticAIProvider(vendor.bind(http_client)), gate, log


class TestAnthropicStackStructuredContract(_VendorStructuredContract):
    """``complete_structured`` over the real ``anthropic`` SDK passes the contract."""

    vendor = ANTHROPIC
    answered_by = f"anthropic:{_ANTHROPIC_MODEL}"


class TestOpenAIStackStructuredContract(_VendorStructuredContract):
    """``complete_structured`` over the real ``openai`` SDK passes the contract."""

    vendor = OPENAI
    answered_by = f"openai:{_OPENAI_MODEL}"

    def reported_usage(self, usage: ReplyUsage) -> ReplyUsage:
        # OpenAI reports what its cache read, and nothing of what it wrote.
        return usage.model_copy(update={"cache_write_tokens": 0})


# --- the wire ---------------------------------------------------------------------


async def _sent(
    vendor: VendorStack, answer: Answer
) -> tuple[dict[str, Any], StructuredReply[Verdict]]:
    recorder = RequestRecorder(_answering(vendor, answer))
    async with vendor.opened(recorder) as model:
        reply = await PydanticAIProvider(model).complete_structured(request(), Verdict)
    return recorder.only, reply


async def test_anthropics_request_carries_the_schema_as_its_output_format() -> None:
    body, _ = await _sent(ANTHROPIC, Answer(VALID_REPLY))
    assert body["output_config"] == {
        "format": {"type": "json_schema", "schema": reply_schema(Verdict)}
    }
    assert "tools" not in body
    assert "tool_choice" not in body


async def test_openais_request_carries_the_schema_as_its_response_format() -> None:
    body, _ = await _sent(OPENAI, Answer(VALID_REPLY))
    response_format = body["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["schema"] == reply_schema(Verdict)
    assert "tools" not in body
    assert "tool_choice" not in body


async def test_anthropics_refusal_is_returned_refused_with_its_statement() -> None:
    _, reply = await _sent(ANTHROPIC, Answer("", ending="refused", refusal=REFUSAL))
    assert reply.failure is ReplyFailure.REFUSED
    assert reply.exchange.refusal == REFUSAL
    assert reply.exchange.refusal_category == REFUSAL_CATEGORY
    assert reply.exchange.finish_reason == "content_filter"


async def test_openais_refusal_is_returned_refused_with_its_statement() -> None:
    _, reply = await _sent(OPENAI, Answer("", ending="refused", refusal=REFUSAL))
    assert reply.failure is ReplyFailure.REFUSED
    assert reply.exchange.refusal == REFUSAL


async def test_the_value_comes_back_through_each_vendors_own_parsing() -> None:
    for vendor in (ANTHROPIC, OPENAI):
        _, reply = await _sent(vendor, Answer(VALID_REPLY))
        assert reply.value == VALID_VALUE


@contextlib.asynccontextmanager
async def _anthropic(model_name: str, handler: Handler) -> AsyncIterator[AnthropicModel]:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = AsyncAnthropic(
            api_key="test-key-not-a-credential", http_client=http_client, max_retries=0
        )
        yield AnthropicModel(model_name, provider=AnthropicProvider(anthropic_client=client))


def _marked(system: list[dict[str, Any]]) -> list[bool]:
    return ["cache_control" in block for block in system]


async def test_an_anthropic_request_is_marked_for_caching_in_native_mode() -> None:
    body, reply = await _sent(ANTHROPIC, Answer(VALID_REPLY))
    assert reply.exchange.mode is ReplyMode.NATIVE
    assert _marked(body["system"]) == [True]


async def test_an_anthropic_request_is_marked_for_caching_in_prompted_mode() -> None:
    answer = anthropic_answer(Answer(VALID_REPLY), model=_ANTHROPIC_WITHOUT_NATIVE)
    recorder = RequestRecorder(lambda _request: httpx.Response(200, json=answer))
    async with _anthropic(_ANTHROPIC_WITHOUT_NATIVE, recorder) as model:
        reply = await PydanticAIProvider(model).complete_structured(request(), Verdict)
    system = cast("list[dict[str, Any]]", recorder.only["system"])
    assert reply.exchange.mode is ReplyMode.PROMPTED
    assert reply.value == VALID_VALUE
    assert "output_config" not in recorder.only
    # The system prompt, then the schema's instruction after it, and the mark on the
    # last block: the schema is inside the cached prefix (§4:5).
    assert _marked(system) == [False, True]
    assert json.dumps(reply_schema(Verdict)) in system[-1]["text"]


async def test_no_other_models_request_is_marked() -> None:
    body, _ = await _sent(OPENAI, Answer(VALID_REPLY))
    assert "cache_control" not in json.dumps(body)
