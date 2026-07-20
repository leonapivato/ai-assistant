"""The canonical action-policy fake passes the shared conformance suite.

This is what lets other subsystems trust ``ai_assistant.testing.FakeActionPolicy``
as a stand-in for the permission gate: it is held to the same contract a real
policy is, floors included.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from action_policy_contract import ActionPolicyContract
from permission_builders import action, decision, tool

from ai_assistant.core.types import (
    DataTier,
    PermissionOutcome,
    Reversibility,
    RiskLevel,
    ToolDefinition,
)
from ai_assistant.testing import FakeActionPolicy

if TYPE_CHECKING:
    from ai_assistant.core.protocols import ActionPolicy


class TestFakeActionPolicyContract(ActionPolicyContract):
    """Runs FakeActionPolicy through the shared ActionPolicy conformance suite."""

    @pytest.fixture
    def policy(self) -> ActionPolicy:
        return FakeActionPolicy()


class TestConfiguredFakeActionPolicyContract(ActionPolicyContract):
    """The knobs cannot configure the fake out of conformance.

    A fake that could be set up to violate its own contract would be a trap for
    every consumer that reached for it, so the thresholds are run through the
    suite at their extremes too — here, refusing everything.
    """

    @pytest.fixture
    def policy(self) -> ActionPolicy:
        return FakeActionPolicy(confirm_at=RiskLevel.LOW, deny_at=RiskLevel.HIGH)


async def test_a_harmless_tool_is_allowed_outright() -> None:
    """Beyond the contract: the default thresholds do reach ALLOW.

    Worth pinning because every floor in the suite is a *negative* — a policy
    that returned ``CONFIRM`` for everything would pass all of them while being
    useless as a stand-in for a gate consumers need to see open.
    """
    ruled = await FakeActionPolicy().decide(action(tool=tool(risk_level=RiskLevel.LOW)))

    assert ruled.outcome is PermissionOutcome.ALLOW


@pytest.mark.parametrize(
    "declared",
    [
        tool(risk_level=RiskLevel.HIGH),
        tool(reversibility=Reversibility.IRREVERSIBLE),
        tool(discloses=(DataTier.OPERATIONAL,)),
    ],
    ids=["risky", "irreversible", "disclosing"],
)
async def test_each_rule_can_raise_the_outcome_on_its_own(declared: ToolDefinition) -> None:
    """Each clause bites independently, so the suite's ladders are not testing one rule."""
    ruled = await FakeActionPolicy().decide(action(tool=declared))

    assert ruled.outcome is PermissionOutcome.CONFIRM


async def test_the_fake_records_what_it_was_asked() -> None:
    """Beyond the contract: the fake exists to let callers assert the gate was consulted."""
    policy = FakeActionPolicy()
    request = action()
    confirmed = decision("d-1")

    await policy.decide(request)
    await policy.resolve(confirmed, approved=False)

    assert policy.requests == [request]
    assert policy.resolutions == [(confirmed, False)]
