"""A failed call's result is flagged to the provider as an error (ADR-0364 §6:5-§6:6).

A result planning was shown not done or refused goes back to an Anthropic model with
``is_error`` set, and an unknown, a done and a result with no outcome without it. The
flag carries no wording: each result's text is sent exactly as planning wrote it, with
nothing telling the model to retry. The request is read off the wire of Anthropic's real
SDK over a mock transport, with the network denied.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import httpx
from anthropic import AsyncAnthropic
from network_guard import network_denied
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from vendor_stacks import RequestRecorder, anthropic_success

from ai_assistant.core.types import (
    CallOutcomeKind,
    CallResult,
    ExchangeStep,
    OfferedTool,
    PlanningExchange,
    ProposedCall,
    RoundReport,
    RoundResponse,
)
from ai_assistant.models import PydanticAIToolCallingCompleter

if TYPE_CHECKING:
    from collections.abc import Mapping

_DUMMY_KEY: Final = "sk-ant-test-not-a-key"

#: Each call's id, with the outcome its result was shown under.
_OUTCOMES: Final[Mapping[str, CallOutcomeKind | None]] = {
    "toolu_done": CallOutcomeKind.DONE,
    "toolu_not_done": CallOutcomeKind.NOT_DONE,
    "toolu_unknown": CallOutcomeKind.UNKNOWN,
    "toolu_refused": CallOutcomeKind.REFUSED,
    "toolu_none": None,
}


def _text(call_id: str) -> str:
    return f'{{"outcome": "{call_id}"}}'


def _exchange() -> PlanningExchange:
    calls = tuple(
        ProposedCall(call_id=call_id, name="search_web", arguments={"query": "q"})
        for call_id in _OUTCOMES
    )
    results = tuple(
        CallResult(call_id=call_id, text=_text(call_id), outcome=outcome)
        for call_id, outcome in _OUTCOMES.items()
    )
    return PlanningExchange(
        instruction="Plan.",
        briefing="# The stimulus",
        steps=(
            ExchangeStep(
                response=RoundResponse(calls=calls),
                report=RoundReport(results=results, news="Nothing else has changed."),
            ),
        ),
    )


async def _tool_results() -> dict[str, dict[str, Any]]:
    """The tool results the round put on Anthropic's wire, by their call id."""
    recorder = RequestRecorder(anthropic_success)
    with network_denied():
        async with httpx.AsyncClient(transport=httpx.MockTransport(recorder)) as http_client:
            client = AsyncAnthropic(api_key=_DUMMY_KEY, http_client=http_client, max_retries=0)
            model = AnthropicModel(
                "claude-opus-4-8", provider=AnthropicProvider(anthropic_client=client)
            )
            completer = PydanticAIToolCallingCompleter(model, thinking=False)
            tool = OfferedTool(
                name="search_web", description="Search.", parameters={"type": "object"}
            )
            await completer.respond(_exchange(), [tool])
    body: Any = recorder.only
    found: dict[str, dict[str, Any]] = {}
    for message in body["messages"]:
        content = message["content"]
        if not isinstance(content, list):
            continue
        for block in content:
            if block.get("type") == "tool_result":
                found[block["tool_use_id"]] = block
    return found


async def test_a_not_done_and_a_refused_result_are_flagged_as_errors() -> None:
    """§6:5: not done and refused carry ``is_error``; done, unknown and none do not."""
    results = await _tool_results()

    flagged = {call_id for call_id, block in results.items() if block.get("is_error")}
    assert flagged == {"toolu_not_done", "toolu_refused"}
    assert set(results) == set(_OUTCOMES)


async def test_the_flag_carries_no_retry_wording() -> None:
    """§6:6: each result is sent as planning wrote it, and no text tells it to retry."""
    results = await _tool_results()

    for call_id, block in results.items():
        content = block["content"]
        texts = [content] if isinstance(content, str) else [one["text"] for one in content]
        assert texts == [_text(call_id)]
        assert not any("try again" in one.casefold() for one in texts)
