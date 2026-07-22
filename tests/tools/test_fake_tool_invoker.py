"""The canonical invoker fake passes the shared conformance suite.

This is what lets other subsystems trust ``ai_assistant.testing.FakeToolInvoker``
as a stand-in for the seam: it is held to the same contract as the real one. It
matters here more than for most fakes, because the fake re-implements the
deadline and the classification independently — it cannot import the subsystem
it stands in for — and this suite is what stops the two copies drifting.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from tool_invoker_contract import PATIENT, Spy, ToolInvokerContract, call_for, tool

from ai_assistant.core.types import ToolOutcome
from ai_assistant.testing import FakeToolInvoker

if TYPE_CHECKING:
    from tool_invoker_contract import InvocableToolRegistry


class TestFakeToolInvokerContract(ToolInvokerContract):
    """Runs FakeToolInvoker through the shared ToolInvoker conformance suite."""

    @pytest.fixture
    def invoker(self) -> InvocableToolRegistry:
        return FakeToolInvoker()


async def test_fake_records_the_calls_it_accepted() -> None:
    """Beyond the contract: the fake exists to let an executor's test assert on
    what reached the seam, and on nothing having reached it when a call was
    refused.
    """
    invoker = FakeToolInvoker([(tool(), Spy())])

    result = await invoker.invoke(call_for(tool()), timeout=PATIENT)

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert [each.request.tool.id for each in invoker.invocations] == ["smtp"]


async def test_the_default_implementation_succeeds_with_no_output() -> None:
    """Arranging a binding is one argument when the test is not about the tool."""
    invoker = FakeToolInvoker()
    invoker.register(tool())

    result = await invoker.invoke(call_for(tool()), timeout=timedelta(seconds=5))

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert result.output is None
