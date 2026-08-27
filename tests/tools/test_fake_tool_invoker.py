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

from ai_assistant.core.errors import UnrecordedAuthorisationError
from ai_assistant.core.types import ToolOutcome
from ai_assistant.testing import (
    FakeAuditTrail,
    FakeToolInvoker,
    authorised,
    invoker_over,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from tool_invoker_contract import InvocableToolRegistry

    from ai_assistant.core.protocols import InvocationLedger, SpendGate


class TestFakeToolInvokerContract(ToolInvokerContract):
    """Runs FakeToolInvoker through the shared ToolInvoker conformance suite."""

    @pytest.fixture
    def invoker(self) -> InvocableToolRegistry:
        return FakeToolInvoker(ledger=FakeAuditTrail(), gate=FakeAuditTrail())

    @pytest.fixture
    def consuming(self) -> Callable[[InvocationLedger], InvocableToolRegistry]:
        return lambda ledger: FakeToolInvoker(ledger=ledger, gate=FakeAuditTrail())

    @pytest.fixture
    def admitting(self) -> Callable[[SpendGate], InvocableToolRegistry]:
        return lambda gate: FakeToolInvoker(ledger=FakeAuditTrail(), gate=gate)

    @pytest.fixture
    def accounting(self) -> Callable[[FakeAuditTrail], InvocableToolRegistry]:
        return lambda trail: FakeToolInvoker(ledger=trail, gate=trail)


async def test_fake_records_the_calls_it_accepted() -> None:
    """Beyond the contract: the fake exists to let an executor's test assert on
    what reached the seam, and on nothing having reached it when a call was
    refused.
    """
    invoker, trail = invoker_over([(tool(), Spy())])

    result = await invoker.invoke(await authorised(trail, call_for(tool())), timeout=PATIENT)

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert [each.request.tool.id for each in invoker.invocations] == ["smtp"]


async def test_the_default_implementation_succeeds_with_no_output() -> None:
    """Arranging a binding is one argument when the test is not about the tool."""
    invoker, trail = invoker_over()
    invoker.register(tool())

    result = await invoker.invoke(
        await authorised(trail, call_for(tool())), timeout=timedelta(seconds=5)
    )

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert result.output is None


async def test_the_fake_records_no_call_the_ledger_refused() -> None:
    """``invocations`` is what a consumer reads to prove nothing was accepted.

    A call the ledger refused reached no callable, so recording it would let a
    consumer's test report an execution that never occurred — the same falsehood
    a call refused by the three checks would be (ADR-0192 §1).
    """
    trail = FakeAuditTrail()
    invoker = FakeToolInvoker([(tool(), Spy())], ledger=trail, gate=trail)

    with pytest.raises(UnrecordedAuthorisationError):
        await invoker.invoke(call_for(tool()), timeout=PATIENT)

    assert invoker.invocations == []
