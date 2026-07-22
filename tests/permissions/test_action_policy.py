"""The default action policy, against its shared conformance suite and beyond it.

The suite fixes a *shape* — monotone, and fail-closed on disclosure and on an
undeclared cost. Everything below the contract line here is about the parts a
shape cannot pin: that the gate actually opens, that each clause bites on its
own, and that the thresholds are the user's while the floors are not.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from action_policy_contract import ActionPolicyContract
from permission_builders import action, decision, ruling, tool

from ai_assistant.core.types import (
    CostBasis,
    DataTier,
    PermissionOutcome,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.permissions import ThresholdActionPolicy

if TYPE_CHECKING:
    from ai_assistant.core.protocols import ActionPolicy


class TestThresholdActionPolicyContract(ActionPolicyContract):
    """Runs the default policy through the shared ActionPolicy conformance suite."""

    @pytest.fixture
    def policy(self) -> ActionPolicy:
        return ThresholdActionPolicy()


class TestPermissiveThresholdActionPolicyContract(ActionPolicyContract):
    """Every threshold disabled: the floors alone must still carry conformance.

    This is the configuration a careless user reaches for, and the one where a
    floor implemented as "just another threshold" would quietly disappear. If
    the disclosure and cost floors were configurable, this subject would
    auto-grant a disclosing tool and the suite would say so.
    """

    @pytest.fixture
    def policy(self) -> ActionPolicy:
        return ThresholdActionPolicy(confirm_at_risk=None, confirm_at_reversibility=None)


class TestRefusingThresholdActionPolicyContract(ActionPolicyContract):
    """The other extreme — refusing everything — is conforming too.

    A policy configurable into violating its own contract would be a trap for
    every deployment that reached for it, so the knobs are run through the suite
    at both ends rather than at their defaults only.
    """

    @pytest.fixture
    def policy(self) -> ActionPolicy:
        return ThresholdActionPolicy(
            confirm_at_risk=RiskLevel.LOW,
            deny_at_risk=RiskLevel.LOW,
            deny_at_reversibility=Reversibility.REVERSIBLE,
        )


class TestInvertedThresholdActionPolicyContract(ActionPolicyContract):
    """A ``deny`` threshold *below* its ``confirm`` threshold still conforms.

    Accepted rather than rejected at construction: the clauses combine by
    maximum, so the result is a policy that denies where it would otherwise have
    asked — strictly safer. The suite is what says that is true rather than the
    constructor's docstring.
    """

    @pytest.fixture
    def policy(self) -> ActionPolicy:
        return ThresholdActionPolicy(confirm_at_risk=RiskLevel.CRITICAL, deny_at_risk=RiskLevel.LOW)


async def test_a_harmless_tool_is_allowed_outright() -> None:
    """Every floor in the suite is a negative, so the open gate needs its own test.

    A policy returning ``CONFIRM`` for everything passes the whole conformance
    suite while being useless as a gate — the ADR says so in as many words. This
    is what distinguishes the shipped default from that.
    """
    ruled = await ThresholdActionPolicy().decide(action(tool=tool(risk_level=RiskLevel.LOW)))

    assert ruled.outcome is PermissionOutcome.ALLOW
    assert ruled.authorised_by is None


@pytest.mark.parametrize(
    "declared",
    [
        tool(risk_level=RiskLevel.MEDIUM),
        tool(reversibility=Reversibility.IRREVERSIBLE),
        tool(discloses=(DataTier.OPERATIONAL,)),
        tool(cost=ToolCost(basis=CostBasis.UNKNOWN)),
    ],
    ids=["risky", "irreversible", "disclosing", "unpriced"],
)
async def test_each_clause_raises_the_outcome_on_its_own(declared: ToolDefinition) -> None:
    """Each rule bites independently, so the suite's ladders test four rules, not one."""
    ruled = await ThresholdActionPolicy().decide(action(tool=declared))

    assert ruled.outcome is PermissionOutcome.CONFIRM


async def test_the_reason_names_every_clause_that_reached_the_outcome() -> None:
    """The reason is shown to the user at the moment they decide.

    A tool that is both disclosing and unpriced was stopped twice, and a prompt
    citing one of the two reasons describes the gate inaccurately.
    """
    both = tool(discloses=(DataTier.PERSONAL,), cost=ToolCost(basis=CostBasis.UNKNOWN))

    ruled = await ThresholdActionPolicy().decide(action(tool=both))

    assert "personal" in ruled.reason
    assert "cost is undeclared" in ruled.reason


async def test_a_deny_threshold_outranks_a_confirm_one() -> None:
    """The clauses combine by taking the most restrictive result, not the first hit."""
    policy = ThresholdActionPolicy(confirm_at_risk=RiskLevel.LOW, deny_at_risk=RiskLevel.HIGH)

    asked = await policy.decide(action(tool=tool(risk_level=RiskLevel.MEDIUM)))
    refused = await policy.decide(action(tool=tool(risk_level=RiskLevel.CRITICAL)))

    assert asked.outcome is PermissionOutcome.CONFIRM
    assert refused.outcome is PermissionOutcome.DENY


async def test_disabling_every_threshold_does_not_disable_the_floors() -> None:
    """The floors are the contract's; the thresholds are the user's (ADR-0036 §1)."""
    policy = ThresholdActionPolicy(confirm_at_risk=None, confirm_at_reversibility=None)

    disclosing = await policy.decide(action(tool=tool(discloses=(DataTier.OPERATIONAL,))))
    unpriced = await policy.decide(action(tool=tool(cost=ToolCost(basis=CostBasis.UNKNOWN))))
    critical = await policy.decide(action(tool=tool(risk_level=RiskLevel.CRITICAL)))

    assert disclosing.outcome is PermissionOutcome.CONFIRM
    assert unpriced.outcome is PermissionOutcome.CONFIRM
    assert critical.outcome is PermissionOutcome.ALLOW, "risk alone was configured away"


async def test_an_approval_resolves_to_an_allow_that_cites_the_confirmation() -> None:
    """The one path that may set ``authorised_by``, and the flow the floor is for."""
    policy = ThresholdActionPolicy()
    confirmed = decision("d-confirm", request=action(tool=tool(discloses=(DataTier.PERSONAL,))))

    resolved = await policy.resolve(confirmed, approved=True)

    assert resolved.outcome is PermissionOutcome.ALLOW
    assert resolved.authorised_by == "d-confirm"


async def test_an_approval_does_not_stand_where_the_rules_now_deny() -> None:
    """Consent given under the old rules does not resurrect a now-refused action.

    ADR-0021 §3 permits a policy to refuse "one whose request would now be
    ``DENY``". The recorded decision embeds the whole declaration, and every
    clause reads only that, so the policy can ask what it would rule today
    without the request it no longer has.
    """
    policy = ThresholdActionPolicy(deny_at_risk=RiskLevel.HIGH)
    confirmed = decision("d-confirm", request=action(tool=tool(risk_level=RiskLevel.CRITICAL)))

    resolved = await policy.resolve(confirmed, approved=True)

    assert resolved.outcome is PermissionOutcome.DENY
    assert resolved.authorised_by is None


async def test_an_approval_stands_where_the_rules_now_merely_confirm() -> None:
    """Only a ``DENY`` withdraws an approval — a still-confirmable action is confirmed."""
    policy = ThresholdActionPolicy(confirm_at_risk=RiskLevel.LOW)
    confirmed = decision("d-confirm", request=action(tool=tool(risk_level=RiskLevel.HIGH)))

    resolved = await policy.resolve(confirmed, approved=True)

    assert resolved.outcome is PermissionOutcome.ALLOW


async def test_a_refusal_is_honoured_even_where_the_rules_would_allow() -> None:
    """The prompt is not theatre: "no" wins over a policy that would have said yes."""
    policy = ThresholdActionPolicy()

    resolved = await policy.resolve(decision("d-confirm"), approved=False)

    assert resolved.outcome is PermissionOutcome.DENY
    assert resolved.authorised_by is None


async def test_resolving_something_never_shown_grants_nothing() -> None:
    """``resolve`` is not a second, unguarded route to ``ALLOW``."""
    policy = ThresholdActionPolicy()
    never_asked = decision("d-1", ruled=ruling(PermissionOutcome.ALLOW))

    resolved = await policy.resolve(never_asked, approved=True)

    assert resolved.outcome is PermissionOutcome.DENY
    assert resolved.authorised_by is None


async def test_the_configured_rules_are_inspectable_without_deciding() -> None:
    """A caller may render the gate to the user; the floors are always in it."""
    bare = ThresholdActionPolicy(confirm_at_risk=None, confirm_at_reversibility=None)

    assert len(bare.rules) == 2
    assert len(ThresholdActionPolicy().rules) == 4
