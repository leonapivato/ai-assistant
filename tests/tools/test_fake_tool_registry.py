"""The canonical tool-registry fake passes the shared conformance suite.

This is what lets other subsystems trust ``ai_assistant.testing.FakeToolRegistry``
as a stand-in: it is held to the same contract as the real registry. It matters
here for the reason it matters in planning — the fake re-implements the
registration rules independently, because it cannot import the subsystem it
stands in for, and this suite is what stops the two copies drifting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tool_registry_contract import ToolRegistryContract, tool

from ai_assistant.testing import FakeToolRegistry

if TYPE_CHECKING:
    from tool_registry_contract import PopulatableToolRegistry


class TestFakeToolRegistryContract(ToolRegistryContract):
    """Runs FakeToolRegistry through the shared ToolRegistry conformance suite."""

    @pytest.fixture
    def registry(self) -> PopulatableToolRegistry:
        return FakeToolRegistry()


async def test_fake_records_what_it_was_asked() -> None:
    """Beyond the contract: the fake exists to let callers assert on the lookup."""
    registry = FakeToolRegistry([tool("smtp")])

    await registry.get("smtp")
    await registry.find("send_email")

    assert registry.lookups == ["smtp", "send_email"]
