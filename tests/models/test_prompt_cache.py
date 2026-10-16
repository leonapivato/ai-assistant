"""Which requests are marked for the provider's cache, and where (#3077).

The marks are pydantic-ai's Anthropic settings, so they are given to pydantic-ai's
Anthropic model alone (ADR-0061). The completer's wire-level checks are in
``test_tool_calling.py``; the provider's are here, over the real vendor stacks.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

import pytest
from network_guard import network_denied
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.instrumented import InstrumentedModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider
from vendor_stacks import ANTHROPIC, OPENAI, RequestRecorder

from ai_assistant.core.types import Message, Role
from ai_assistant.models import PydanticAIProvider
from ai_assistant.models.prompt_cache import prompt_cache_settings

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic_ai.models import Model
    from vendor_stacks import VendorStack

_DUMMY_KEY: Final = "test-key-not-a-credential"

_MARKS: Final = {"anthropic_cache_tool_definitions": True, "anthropic_cache_instructions": True}

_FIVE_MINUTES: Final = {"type": "ephemeral", "ttl": "5m"}


def _anthropic(settings: AnthropicModelSettings | None = None) -> AnthropicModel:
    return AnthropicModel(
        "claude-sonnet-5-5", provider=AnthropicProvider(api_key=_DUMMY_KEY), settings=settings
    )


def _answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    del messages, info
    return ModelResponse(parts=[TextPart("ok")])


@pytest.mark.parametrize(
    "model",
    [
        pytest.param(_anthropic, id="bare"),
        pytest.param(lambda: WrapperModel(_anthropic()), id="wrapped"),
        pytest.param(lambda: InstrumentedModel(_anthropic()), id="instrumented"),
    ],
)
def test_anthropics_model_is_given_both_marks(model: Callable[[], Model]) -> None:
    assert dict(prompt_cache_settings(model())) == _MARKS


@pytest.mark.parametrize(
    "model",
    [
        pytest.param(
            lambda: OpenAIChatModel("gpt-5", provider=OpenAIProvider(api_key=_DUMMY_KEY)),
            id="openai",
        ),
        pytest.param(lambda: FunctionModel(_answer), id="function"),
        pytest.param(lambda: FallbackModel(_anthropic()), id="fallback-over-anthropic"),
        pytest.param(lambda: WrapperModel(FallbackModel(_anthropic())), id="wrapped-fallback"),
    ],
)
def test_any_other_model_is_given_none(model: Callable[[], Model]) -> None:
    """ADR-0061: another provider, or a fallback model holding several, is as it was."""
    assert dict(prompt_cache_settings(model())) == {}


def test_a_mark_the_models_own_settings_set_is_left_to_them() -> None:
    model = _anthropic(AnthropicModelSettings(anthropic_cache_instructions="1h"))
    assert dict(prompt_cache_settings(model)) == {"anthropic_cache_tool_definitions": True}


async def _completed(vendor: VendorStack, messages: list[Message]) -> dict[str, Any]:
    """Complete ``messages`` over ``vendor``'s real SDK; the body it put on the wire."""
    recorder = RequestRecorder(vendor.success)
    with network_denied():
        async with vendor.opened(recorder) as model:
            await PydanticAIProvider(model).complete(messages)
    return recorder.only


_INSTRUCTED: Final = [
    Message(role=Role.SYSTEM, content="Read the input."),
    Message(role=Role.USER, content="{}"),
]


async def test_a_completion_on_anthropic_marks_its_instructions() -> None:
    body = await _completed(ANTHROPIC, _INSTRUCTED)
    assert body["system"] == [
        {"type": "text", "text": "Read the input.", "cache_control": _FIVE_MINUTES}
    ]
    assert "cache_control" not in body
    assert all("cache_control" not in block for block in body["messages"][-1]["content"])


async def test_a_completion_on_openai_is_given_no_marks() -> None:
    body = await _completed(OPENAI, _INSTRUCTED)
    sent = json.dumps(body)
    assert "cache_control" not in sent
    assert "prompt_cache" not in sent
