"""Tests for the pydantic-ai-backed ModelProvider.

The real :class:`PydanticAIProvider` is exercised end to end by injecting
pydantic-ai's ``TestModel``/``FunctionModel`` as the default model, so these
tests are deterministic and never touch the network.
"""

from __future__ import annotations

import json
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


@pytest.mark.parametrize(
    ("history", "match"),
    [
        pytest.param([], "at least one message", id="empty"),
        pytest.param(
            [Message(role=Role.USER, content="u"), Message(role=Role.ASSISTANT, content="cached")],
            "already ends with an assistant turn",
            id="ends-on-assistant",
        ),
        pytest.param(
            [Message(role=Role.ASSISTANT, content="lone")],
            "already ends with an assistant turn",
            id="lone-assistant",
        ),
    ],
)
async def test_a_malformed_conversation_is_refused_as_a_bare_model_error(
    history: list[Message], match: str
) -> None:
    # The shared suite pins the *disposition* these carry, which is what the
    # contract requires of any implementation (ADR-0066 §6). What is asserted
    # here is narrower and belongs to this implementation alone: that it raises
    # the base class, chosen to match the empty check the trailing-assistant
    # shapes now sit beside. Nothing else pins that — the flag-only shared
    # assertions are equally satisfied by ModelContentFilterError, which is also
    # non-retryable and non-routable and would mislabel a caller-shape mistake as
    # a content-policy refusal.
    provider = PydanticAIProvider(default_model=TestModel())

    with pytest.raises(ModelError, match=match) as caught:
        await provider.complete(history)

    assert type(caught.value) is ModelError


async def test_a_trailing_assistant_turn_is_refused_before_the_agent_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The ordering ADR-0066 §6 obligation 2 requires, and the one obligation that
    # costs a reach into a private. An implementation that called ``Agent.run``,
    # got the echo back and *then* raised would satisfy every other assertion in
    # this change: today's short-circuit means the reject-after ordering also
    # issues no request and never reaches the model, so neither the vendor
    # recorder nor a FunctionModel spy can tell the two apart. A spy on the
    # agent can. Worth pinning because it is what keeps the refusal free of a
    # vendor round trip if pydantic-ai ever stops short-circuiting.
    provider = PydanticAIProvider(default_model=TestModel(custom_output_text="MODEL WAS CALLED"))
    ran = False

    async def spy(**_kwargs: object) -> SimpleNamespace:
        nonlocal ran
        ran = True
        return SimpleNamespace(output="unreached")

    monkeypatch.setattr(provider._agent, "run", spy)  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(ModelError):
        await provider.complete(
            [
                Message(role=Role.USER, content="u"),
                Message(role=Role.ASSISTANT, content="cached reply"),
            ]
        )

    assert not ran


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


async def test_an_undecodable_response_body_is_unavailable() -> None:
    # ADR-0063: the one exception admitted from outside pydantic-ai's hierarchy.
    # A body that will not decode says nothing about the request — it says the
    # path substituted something for the answer — so it is retryable *and*
    # routable, where before it was neither. `tests/models/test_provider_vendors.py`
    # pins that both real vendor SDKs actually raise this; here the arm itself.
    error = await _complete_raising(json.JSONDecodeError("Expecting value", "<html>", 0))

    assert type(error) is ModelUnavailableError
    assert error.retryable
    assert error.routable


async def test_a_plain_value_error_stays_permanent() -> None:
    # The boundary the arm above must not cross. `json.JSONDecodeError` subclasses
    # `ValueError`, and pydantic-ai raises a plain `ValueError` for a model spec
    # naming a provider it does not know ("Unknown provider: ..."). Matching the
    # base would make a typo in configuration retryable on every route.
    error = await _complete_raising(ValueError("Unknown provider: nope"))

    assert type(error) is ModelError
    assert not error.retryable
    assert not error.routable


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
