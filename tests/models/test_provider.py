"""Tests for the pydantic-ai-backed ModelProvider.

The real :class:`PydanticAIProvider` is exercised end to end by injecting
pydantic-ai's ``TestModel``/``FunctionModel`` as the default model, so these
tests are deterministic and never touch the network.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from model_provider_contract import ModelProviderContract
from pydantic_ai.exceptions import (
    ContentFilterError,
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
)
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from ai_assistant.core.errors import (
    ModelAuthError,
    ModelContentFilterError,
    ModelError,
    ModelRateLimitError,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from ai_assistant.core.types import Message, Role
from ai_assistant.models import PydanticAIProvider
from ai_assistant.models.provider import (
    _to_model_messages,  # pyright: ignore[reportPrivateUsage]
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import ModelProvider


class TestPydanticAIProviderContract(ModelProviderContract):
    """Runs PydanticAIProvider through the shared ModelProvider conformance suite.

    ``TestModel`` supplies a deterministic, offline default model so the contract
    never touches the network.
    """

    @pytest.fixture
    def provider(self) -> ModelProvider:
        return PydanticAIProvider(default_model=TestModel())


async def test_complete_returns_assistant_message() -> None:
    provider = PydanticAIProvider(default_model=TestModel(custom_output_text="hi there"))

    reply = await provider.complete([Message(role=Role.USER, content="hello")])

    assert reply.role is Role.ASSISTANT
    assert reply.content == "hi there"


async def test_conversation_is_forwarded_to_the_model() -> None:
    captured: list[ModelMessage] = []

    def capture(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        captured.extend(messages)
        return ModelResponse(parts=[TextPart(content="ok")])

    provider = PydanticAIProvider(default_model=FunctionModel(capture))

    reply = await provider.complete(
        [
            Message(role=Role.SYSTEM, content="be terse"),
            Message(role=Role.USER, content="hi"),
            Message(role=Role.ASSISTANT, content="hello"),
            Message(role=Role.USER, content="how are you?"),
        ]
    )

    assert reply.content == "ok"
    # system + first user collapse into one request, then the assistant
    # response, then the trailing user turn as a second request.
    assert [type(m) for m in captured] == [ModelRequest, ModelResponse, ModelRequest]
    first_request = captured[0]
    assert isinstance(first_request, ModelRequest)
    assert [type(p) for p in first_request.parts] == [SystemPromptPart, UserPromptPart]


def test_to_model_messages_groups_request_parts() -> None:
    history = _to_model_messages(
        [
            Message(role=Role.SYSTEM, content="sys"),
            Message(role=Role.USER, content="u1"),
            Message(role=Role.ASSISTANT, content="a1"),
            Message(role=Role.USER, content="u2"),
        ]
    )

    assert [type(m) for m in history] == [ModelRequest, ModelResponse, ModelRequest]


def test_tool_role_is_rejected() -> None:
    with pytest.raises(ModelError, match="tool-role"):
        _to_model_messages([Message(role=Role.TOOL, content="result")])


async def test_empty_messages_raise() -> None:
    provider = PydanticAIProvider(default_model=TestModel())

    with pytest.raises(ModelError, match="at least one message"):
        await provider.complete([])


async def test_model_override_is_forwarded_to_the_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A non-None ``"provider:model"`` override cannot be resolved offline, so the
    # shared contract only checks the keyword is accepted. Here we prove the
    # override is actually threaded to the underlying agent by capturing what
    # ``run`` receives — closing the gap the contract cannot cover universally.
    provider = PydanticAIProvider(default_model=TestModel())
    captured: dict[str, object] = {}

    async def fake_run(**kwargs: object) -> SimpleNamespace:
        captured["model"] = kwargs.get("model")
        return SimpleNamespace(output="routed")

    monkeypatch.setattr(provider._agent, "run", fake_run)  # pyright: ignore[reportPrivateUsage]

    reply = await provider.complete([Message(role=Role.USER, content="hi")], model="prov:model")

    assert reply.content == "routed"
    assert captured["model"] == "prov:model"


async def test_provider_failure_is_wrapped() -> None:
    def boom(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        error_message = "provider exploded"
        raise RuntimeError(error_message)

    provider = PydanticAIProvider(default_model=FunctionModel(boom))

    with pytest.raises(ModelError, match="model completion failed"):
        await provider.complete([Message(role=Role.USER, content="hi")])


async def _complete_raising(exc: Exception) -> ModelError:
    """Drive a completion whose model raises ``exc``, returning what surfaced."""

    def boom(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise exc

    provider = PydanticAIProvider(default_model=FunctionModel(boom))

    with pytest.raises(ModelError) as caught:
        await provider.complete([Message(role=Role.USER, content="hi")])
    return caught.value


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (401, ModelAuthError),
        (403, ModelAuthError),
        (408, ModelTimeoutError),
        (429, ModelRateLimitError),
        (500, ModelUnavailableError),
        (503, ModelUnavailableError),
    ],
)
async def test_http_status_is_classified(status_code: int, expected: type[ModelError]) -> None:
    error = await _complete_raising(ModelHTTPError(status_code=status_code, model_name="fake"))

    assert type(error) is expected


async def test_other_4xx_stays_a_bare_model_error() -> None:
    # A malformed request is our bug, not a transient fault — retrying it would
    # fail identically, so it must not land on a retryable subclass.
    error = await _complete_raising(ModelHTTPError(status_code=400, model_name="fake"))

    assert type(error) is ModelError
    assert not error.retryable


async def test_content_filter_is_classified_before_its_base_class() -> None:
    # ContentFilterError subclasses UnexpectedModelBehavior; the more specific
    # pattern has to win.
    error = await _complete_raising(ContentFilterError("refused"))

    assert type(error) is ModelContentFilterError


async def test_unexpected_behaviour_is_a_response_error() -> None:
    error = await _complete_raising(UnexpectedModelBehavior("garbled"))

    assert type(error) is ModelResponseError


async def test_connection_failure_is_unavailable() -> None:
    error = await _complete_raising(ModelAPIError(model_name="fake", message="connection reset"))

    assert type(error) is ModelUnavailableError


async def test_timeout_is_classified() -> None:
    error = await _complete_raising(TimeoutError("deadline exceeded"))

    assert type(error) is ModelTimeoutError


async def test_unknown_failure_is_not_retryable() -> None:
    error = await _complete_raising(RuntimeError("something new"))

    assert type(error) is ModelError
    assert not error.retryable


@pytest.mark.parametrize(
    ("error_type", "retryable"),
    [
        (ModelError, False),
        (ModelAuthError, False),
        (ModelContentFilterError, False),
        (ModelResponseError, False),
        (ModelRateLimitError, True),
        (ModelTimeoutError, True),
        (ModelUnavailableError, True),
    ],
)
def test_retryable_flags(error_type: type[ModelError], retryable: bool) -> None:
    assert error_type.retryable is retryable
    assert issubclass(error_type, ModelError)


async def test_classified_error_preserves_the_cause() -> None:
    cause = ModelHTTPError(status_code=429, model_name="fake")

    error = await _complete_raising(cause)

    # The original provider exception stays reachable for logging/debugging.
    assert error.__cause__ is not None
