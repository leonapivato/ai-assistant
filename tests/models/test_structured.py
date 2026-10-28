"""``PydanticAIProvider.complete_structured``: one request, a shape, and what came back.

The shared ``StructuredCompleter`` suite runs here over a pydantic-ai ``FunctionModel``
in each mode, and the cases after it pin what only this implementation decides
(ADR-0354 §4, §5): which mode a model is sent in, that no output tool is ever offered,
the schema the request carries, the settings it is sent with, that a thinking part is
no part of the reply and a call makes it ``invalid``, that a fallback model is refused,
and how a failure of the exchange is classified. The run over the real vendor SDKs is
``test_structured_vendors.py``.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from model_provider_contract import ConversationLog, FirstAwaitGate
from pydantic import BaseModel, Field
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import (
    ModelResponse,
    NativeToolCallPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
)
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.usage import RequestUsage
from pydantic_transport import rendered_turns
from structured_completer_contract import (
    VALID_REPLY,
    VALID_VALUE,
    Answer,
    StructuredCompleterContract,
    Verdict,
    request,
    seen_reply,
)

from ai_assistant.core.errors import (
    ModelError,
    ModelRateLimitError,
    ModelUnavailableError,
)
from ai_assistant.core.reply_shapes import reply_schema, reply_shape_version
from ai_assistant.core.types import ReplyFailure, ReplyMode, StructuredReply
from ai_assistant.models import PydanticAIProvider, Route, RoutingProvider
from ai_assistant.models.structured import PROMPTED_INSTRUCTION

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from pydantic_ai.messages import FinishReason, ModelMessage

    from ai_assistant.core.protocols import StructuredCompleter
    from ai_assistant.testing.cancellation import SuspendedCall

#: The name each scripted model goes by, and so the second half of who answered.
_MODEL_NAME = "scripted"

_NATIVE = ModelProfile(supports_json_schema_output=True)
_PROMPTED = ModelProfile(supports_json_schema_output=False)

_FINISH: dict[str, FinishReason] = {
    "stop": "stop",
    "length": "length",
    "refused": "content_filter",
}


def response_for(answer: Answer) -> ModelResponse:
    """``answer`` as the provider response a pydantic-ai model returns."""
    return ModelResponse(
        parts=[TextPart(content=answer.reply)] if answer.reply else [],
        usage=RequestUsage(
            input_tokens=answer.usage.input_tokens,
            output_tokens=answer.usage.output_tokens,
            cache_read_tokens=answer.usage.cache_read_tokens,
            cache_write_tokens=answer.usage.cache_write_tokens,
        ),
        finish_reason=_FINISH[answer.ending],
        provider_details={"refusal": answer.refusal} if answer.refusal is not None else None,
    )


@dataclass
class _Scripted:
    """A ``FunctionModel`` answering every request with one response, recording each."""

    response: ModelResponse
    infos: list[AgentInfo] = field(default_factory=list)
    histories: list[list[ModelMessage]] = field(default_factory=list)

    async def respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.histories.append(list(messages))
        self.infos.append(info)
        return self.response


@dataclass
class _ModelWorld:
    """One subject over a scripted ``FunctionModel``, and what reached that model."""

    scripted: _Scripted
    completer: StructuredCompleter
    mode: ReplyMode
    answered_by: str = f"function:{_MODEL_NAME}"

    @property
    def attempts(self) -> int:
        return len(self.scripted.infos)


def _world(response: ModelResponse, profile: ModelProfile = _NATIVE) -> _ModelWorld:
    scripted = _Scripted(response)
    model = FunctionModel(scripted.respond, model_name=_MODEL_NAME, profile=profile)
    mode = ReplyMode.NATIVE if profile is _NATIVE else ReplyMode.PROMPTED
    return _ModelWorld(scripted=scripted, completer=PydanticAIProvider(model), mode=mode)


class _ProviderContract(StructuredCompleterContract):
    """The shared suite over a ``FunctionModel``, in one mode."""

    profile: ModelProfile

    @pytest.fixture
    def completer(self) -> StructuredCompleter:
        return _world(response_for(Answer(VALID_REPLY)), self.profile).completer

    @contextlib.asynccontextmanager
    async def world(self, answer: Answer) -> AsyncIterator[_ModelWorld]:
        yield _world(response_for(answer), self.profile)

    @contextlib.asynccontextmanager
    async def completer_suspended_at_its_first_await(
        self,
    ) -> AsyncIterator[tuple[StructuredCompleter, SuspendedCall, ConversationLog]]:
        # A direct implementation suspends on its transport (ADR-0069 §3): here the
        # model's own request, the call's first and only await.
        log = ConversationLog()
        gate = FirstAwaitGate()

        async def held(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
            observed = rendered_turns(messages)
            log.record(observed)
            await gate.hold()
            return ModelResponse(parts=[TextPart(seen_reply([turn[1] for turn in observed]))])

        model = FunctionModel(held, model_name=_MODEL_NAME, profile=self.profile)
        yield PydanticAIProvider(default_model=model), gate, log


class TestPydanticAIProviderNativeContract(_ProviderContract):
    """``PydanticAIProvider`` passes the contract for a model with native support."""

    profile = _NATIVE


class TestPydanticAIProviderPromptedContract(_ProviderContract):
    """``PydanticAIProvider`` passes the contract for a model without it."""

    profile = _PROMPTED


# --- the shapes the cases below send -------------------------------------------


class _Place(BaseModel):
    """Where something is. A docstring the schema must not carry."""

    city: str = Field(description="The city.", examples=["Lisbon"])
    country: str = Field(title="Country name")


class _Trip(BaseModel):
    """A trip, with text at every depth."""

    destination: _Place = Field(description="Where to.")
    stops: list[_Place] = Field(description="On the way.")
    nights: int | None = Field(default=None, description="How long.")


def _walk(schema: object) -> list[dict[str, object]]:
    """Every schema position in ``schema``, descending through every keyword."""
    found: list[dict[str, object]] = []
    if isinstance(schema, dict):
        found.append(schema)
        for keyword, value in schema.items():
            if keyword in {"properties", "$defs"} and isinstance(value, dict):
                for item in value.values():
                    found.extend(_walk(item))
            else:
                found.extend(_walk(value))
    elif isinstance(schema, list):
        for item in schema:
            found.extend(_walk(item))
    return found


def _assert_closed_and_text_free(schema: object) -> None:
    positions = _walk(schema)
    objects = [s for s in positions if s.get("type") == "object"]
    assert len(objects) >= 2, "the shape's nested objects are all in the schema"
    for position in objects:
        assert position.get("additionalProperties") is False, position
    for position in positions:
        assert not {"title", "description", "examples"} & position.keys(), position


async def _sent(profile: ModelProfile, shape: type[BaseModel] = Verdict) -> AgentInfo:
    scripted = _Scripted(response_for(Answer(VALID_REPLY)))
    model = FunctionModel(scripted.respond, model_name=_MODEL_NAME, profile=profile)
    await PydanticAIProvider(model).complete_structured(request(), shape)
    assert len(scripted.infos) == 1
    return scripted.infos[0]


# --- the mode, and what the request asks for (§4:2, §4:3) ------------------------


async def test_a_model_with_native_support_is_sent_the_schema_natively() -> None:
    info = await _sent(_NATIVE)
    parameters = info.model_request_parameters
    assert parameters.output_mode == "native"
    assert parameters.output_object is not None
    assert parameters.output_object.json_schema == reply_schema(Verdict)
    assert parameters.output_tools == []
    assert parameters.function_tools == []
    assert info.instructions is None


async def test_a_model_without_it_is_sent_the_schema_in_its_instructions() -> None:
    info = await _sent(_PROMPTED)
    parameters = info.model_request_parameters
    assert parameters.output_mode == "prompted"
    assert parameters.output_tools == []
    assert parameters.function_tools == []
    assert info.instructions == f"{PROMPTED_INSTRUCTION}\n\n{json.dumps(reply_schema(Verdict))}"


async def test_the_mode_is_resolved_for_the_model_the_call_names() -> None:
    """§4:3: a call's override is sent in the mode its own model takes."""
    native = await PydanticAIProvider(
        FunctionModel(_Scripted(response_for(Answer("{}"))).respond)
    ).complete_structured(request(), Verdict, model="test")
    # pydantic-ai's `TestModel`, which the spec "test" names, has no JSON-schema output.
    assert TestModel().profile.get("supports_json_schema_output", False) is False
    assert native.exchange.mode is ReplyMode.PROMPTED
    assert native.exchange.model == "test:test"


@pytest.mark.parametrize("profile", [_NATIVE, _PROMPTED], ids=["native", "prompted"])
async def test_the_schema_sent_is_closed_at_every_depth_and_carries_no_text(
    profile: ModelProfile,
) -> None:
    info = await _sent(profile, _Trip)
    parameters = info.model_request_parameters
    assert parameters.output_object is not None
    _assert_closed_and_text_free(parameters.output_object.json_schema)
    if profile is _PROMPTED:
        assert info.instructions is not None
        sent = json.loads(info.instructions.removeprefix(f"{PROMPTED_INSTRUCTION}\n\n"))
        _assert_closed_and_text_free(sent)
        assert sent == reply_schema(_Trip)


@pytest.mark.parametrize("profile", [_NATIVE, _PROMPTED], ids=["native", "prompted"])
async def test_a_request_asks_for_no_setting_of_its_own_on_a_model_without_cache_marks(
    profile: ModelProfile,
) -> None:
    """§4:5: no thinking, no output ceiling, and no marks off Anthropic's model."""
    info = await _sent(profile)
    assert info.model_settings is None
    assert info.model_request_parameters.thinking is None


# --- what the reply is (§4:6, §5:2) ----------------------------------------------


async def _answer(
    *parts: TextPart | ThinkingPart | ToolCallPart | NativeToolCallPart,
) -> StructuredReply[Verdict]:
    scripted = _Scripted(ModelResponse(parts=list(parts)))
    reply = await PydanticAIProvider(FunctionModel(scripted.respond)).complete_structured(
        request(), Verdict
    )
    assert len(scripted.infos) == 1
    return reply


async def test_a_thinking_part_is_no_part_of_the_reply() -> None:
    reply = await _answer(
        ThinkingPart(content="The user wants a yes."),
        TextPart(content=VALID_REPLY),
    )
    assert reply.value == VALID_VALUE
    assert reply.exchange.reply == VALID_REPLY


async def test_the_reply_is_the_text_parts_joined_in_order() -> None:
    reply = await _answer(
        TextPart(content='{"answer": "yes", '),
        ThinkingPart(content="and how sure"),
        TextPart(content='"confidence": 4}'),
    )
    assert reply.value == VALID_VALUE


@pytest.mark.parametrize(
    "call",
    [
        ToolCallPart(tool_name="final_result", args={"answer": "yes"}, tool_call_id="c1"),
        NativeToolCallPart(tool_name="web_search", args={"q": "x"}, tool_call_id="c2"),
    ],
    ids=["function-call", "native-call"],
)
async def test_a_response_carrying_a_call_is_invalid(
    call: ToolCallPart | NativeToolCallPart,
) -> None:
    reply = await _answer(TextPart(content=VALID_REPLY), call)
    assert reply.failure is ReplyFailure.INVALID
    assert reply.value is None


async def test_a_call_with_no_text_beside_it_is_empty_first() -> None:
    reply = await _answer(ToolCallPart(tool_name="final_result", args={}, tool_call_id="c1"))
    assert reply.failure is ReplyFailure.EMPTY


async def test_the_exchange_names_the_provider_and_model_the_response_names() -> None:
    response = response_for(Answer(VALID_REPLY))
    response.provider_name = "anthropic"
    scripted = _Scripted(response)
    reply = await PydanticAIProvider(
        FunctionModel(scripted.respond, model_name="claude-sonnet-5-5")
    ).complete_structured(request(), Verdict)
    assert reply.exchange.model == "anthropic:claude-sonnet-5-5"
    assert reply.exchange.shape_version == reply_shape_version(Verdict)


async def test_a_refusals_category_is_carried_where_the_provider_gives_one() -> None:
    response = response_for(Answer("", ending="refused", refusal="No."))
    response.provider_details = {"refusal": "No.", "refusal_category": "cyber"}
    reply = await PydanticAIProvider(
        FunctionModel(_Scripted(response).respond)
    ).complete_structured(request(), Verdict)
    assert reply.failure is ReplyFailure.REFUSED
    assert reply.exchange.refusal == "No."
    assert reply.exchange.refusal_category == "cyber"


async def test_a_refusal_no_record_can_hold_is_still_returned_refused() -> None:
    """§2:5, §5:2: the refusal is read off the response, never off the record of it."""
    response = ModelResponse(
        parts=[TextPart(content=VALID_REPLY)],
        finish_reason="content_filter",
        provider_details={"refusal": "I won't \udc80", "refusal_category": "\ud800"},
    )
    reply = await PydanticAIProvider(
        FunctionModel(_Scripted(response).respond, model_name="claude-\udfff")
    ).complete_structured(request(), Verdict)
    assert reply.failure is ReplyFailure.REFUSED
    assert reply.exchange.refusal == "I won't \ufffd"
    assert reply.exchange.refusal_category == "\ufffd"
    assert reply.exchange.model == "function:claude-\ufffd"


async def test_such_a_refusal_is_not_routed_to_the_next_provider() -> None:
    refused = ModelResponse(
        parts=[], finish_reason="content_filter", provider_details={"refusal": "\ud800"}
    )
    primary, secondary = _Scripted(refused), _Scripted(response_for(Answer(VALID_REPLY)))
    router = RoutingProvider(
        [
            Route(PydanticAIProvider(FunctionModel(primary.respond))),
            Route(PydanticAIProvider(FunctionModel(secondary.respond))),
        ]
    )
    reply = await router.complete_structured(request(), Verdict)
    assert reply.failure is ReplyFailure.REFUSED
    assert len(primary.infos) == 1
    assert secondary.infos == []


# --- what is refused before any request, and what is raised (§2:5, §4:4) ---------


async def test_a_fallback_model_is_refused_before_any_request() -> None:
    first, second = (
        _Scripted(response_for(Answer(VALID_REPLY))),
        _Scripted(response_for(Answer(VALID_REPLY))),
    )
    fallback = FallbackModel(FunctionModel(first.respond), FunctionModel(second.respond))
    with pytest.raises(ModelError) as caught:
        await PydanticAIProvider(fallback).complete_structured(request(), Verdict)
    assert type(caught.value) is ModelError
    assert first.infos == []
    assert second.infos == []


async def test_a_wrapped_fallback_model_is_refused_too() -> None:
    scripted = _Scripted(response_for(Answer(VALID_REPLY)))
    wrapped = WrapperModel(FallbackModel(FunctionModel(scripted.respond)))
    with pytest.raises(ModelError) as caught:
        await PydanticAIProvider(wrapped).complete_structured(request(), Verdict)
    assert type(caught.value) is ModelError
    assert scripted.infos == []


def _failing(exc: Exception) -> Callable[[list[ModelMessage], AgentInfo], Awaitable[ModelResponse]]:
    async def fail(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise exc

    return fail


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (ModelHTTPError(429, "m"), ModelRateLimitError),
        (ModelHTTPError(503, "m"), ModelUnavailableError),
    ],
    ids=["rate-limited", "unavailable"],
)
async def test_a_failure_of_the_exchange_is_classified_as_completes_are(
    raised: Exception, expected: type[ModelError]
) -> None:
    with pytest.raises(expected):
        await PydanticAIProvider(FunctionModel(_failing(raised))).complete_structured(
            request(), Verdict
        )


async def test_the_conversation_reaches_the_model_as_given() -> None:
    scripted = _Scripted(response_for(Answer(VALID_REPLY)))
    await PydanticAIProvider(FunctionModel(scripted.respond)).complete_structured(
        request(), Verdict
    )
    assert [turn[:2] for turn in rendered_turns(scripted.histories[0])] == [
        (message.role, message.content) for message in request()
    ]
