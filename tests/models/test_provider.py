"""Tests for the pydantic-ai-backed ModelProvider.

The real :class:`PydanticAIProvider` is exercised end to end by injecting
pydantic-ai's ``TestModel``/``FunctionModel`` as the default model, so these
tests are deterministic and never touch the network.
"""

from __future__ import annotations

import pytest
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

from ai_assistant.core.errors import ModelError
from ai_assistant.core.protocols import ModelProvider
from ai_assistant.core.types import Message, Role
from ai_assistant.models import PydanticAIProvider
from ai_assistant.models.provider import (
    _to_model_messages,  # pyright: ignore[reportPrivateUsage]
)


def test_provider_conforms_to_protocol() -> None:
    provider = PydanticAIProvider(default_model=TestModel())
    assert isinstance(provider, ModelProvider)


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


async def test_provider_failure_is_wrapped() -> None:
    def boom(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        error_message = "provider exploded"
        raise RuntimeError(error_message)

    provider = PydanticAIProvider(default_model=FunctionModel(boom))

    with pytest.raises(ModelError, match="model completion failed"):
        await provider.complete([Message(role=Role.USER, content="hi")])
