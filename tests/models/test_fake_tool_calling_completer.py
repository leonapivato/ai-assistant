"""``FakeToolCallingCompleter`` through the shared ``ToolCallingCompleter`` suite.

The canonical fake's binding, and the one the Protocol-triad check
(``tests/core/test_protocol_triad.py``) reads: without a ``Test…Contract`` subclass
whose subject fixture supplies the fake and whose inherited obligations actually ran,
the fake is unverified however many files exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from tool_calling_completer_contract import (
    SeenTool,
    ToolCallingCompleterContract,
    Turn,
    exchange_turns,
)

from ai_assistant.core.errors import ModelError
from ai_assistant.core.types import OfferedTool, PlanningExchange, RoundResponse
from ai_assistant.testing import DEFAULT_ROUND_TEXT, FakeToolCallingCompleter

if TYPE_CHECKING:
    from ai_assistant.core.protocols import ToolCallingCompleter


@dataclass(frozen=True)
class _FakeWorld:
    """The suite's world over a :class:`FakeToolCallingCompleter`: it is its own model."""

    subject: FakeToolCallingCompleter

    @property
    def completer(self) -> ToolCallingCompleter:
        return self.subject

    @property
    def attempts(self) -> int:
        return self.subject.call_count

    @property
    def observed(self) -> tuple[tuple[Turn, ...], ...]:
        return tuple(exchange_turns(call.exchange) for call in self.subject.calls)

    @property
    def offered(self) -> tuple[tuple[SeenTool, ...], ...]:
        return tuple(
            tuple(
                (tool.name, tool.description, tool.model_dump()["parameters"])
                for tool in call.tools
            )
            for call in self.subject.calls
        )


class TestFakeToolCallingCompleterContract(ToolCallingCompleterContract):
    """``FakeToolCallingCompleter`` passes the shared ``ToolCallingCompleter`` contract."""

    @pytest.fixture
    def completer(self) -> ToolCallingCompleter:
        return FakeToolCallingCompleter()

    def world(self, response: RoundResponse) -> _FakeWorld:
        return _FakeWorld(subject=FakeToolCallingCompleter(response))


def _hi() -> PlanningExchange:
    return PlanningExchange(instruction="Plan.", briefing="hi")


class TestTheFakeBeyondTheContract:
    """What the fake promises its own users, over and above the shared contract."""

    async def test_an_unscripted_fake_writes_its_default_round(self) -> None:
        response = await FakeToolCallingCompleter().respond(_hi(), [])
        assert response == RoundResponse(text=DEFAULT_ROUND_TEXT)

    async def test_scripted_returns_each_round_in_turn_then_raises(self) -> None:
        fake = FakeToolCallingCompleter.scripted(
            RoundResponse(text="one"), RoundResponse(text="two")
        )
        assert (await fake.respond(_hi(), [])).text == "one"
        assert (await fake.respond(_hi(), [])).text == "two"
        with pytest.raises(AssertionError):
            await fake.respond(_hi(), [])

    async def test_a_refused_call_consumes_no_scripted_round(self) -> None:
        fake = FakeToolCallingCompleter.scripted(RoundResponse(text="the only round"))
        tool = OfferedTool(name="t", description="d", parameters={"type": "object"})
        with pytest.raises(ModelError):
            await fake.respond(_hi(), [tool, tool])
        assert (await fake.respond(_hi(), [])).text == "the only round"
        assert fake.call_count == 1

    async def test_a_callable_sees_the_request_and_its_failure_is_a_model_error(self) -> None:
        def answer(exchange: object, tools: object) -> RoundResponse:
            del exchange, tools
            msg = "boom"
            raise RuntimeError(msg)

        with pytest.raises(ModelError):
            await FakeToolCallingCompleter(answer).respond(_hi(), [])

    async def test_records_the_model_override_and_the_tools(self) -> None:
        fake = FakeToolCallingCompleter()
        tool = OfferedTool(name="t", description="d", parameters={"type": "object"})
        await fake.respond(_hi(), [tool], model="test:model")
        assert fake.last_call.model == "test:model"
        assert fake.last_call.tools == (tool,)
        assert fake.last_call.exchange == _hi()
