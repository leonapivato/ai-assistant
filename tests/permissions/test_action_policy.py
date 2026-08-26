"""The default action policy, against its shared conformance suite and beyond it.

The suite fixes a *shape* — monotone, and fail-closed on disclosure and on an
undeclared cost. Everything below the contract line here is about the parts a
shape cannot pin: that the gate actually opens, that each clause bites on its
own, and that the thresholds are the user's while the floors are not.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from action_policy_contract import ActionPolicyContract
from permission_builders import action, decision, ruling, tool
from recipient_builders import ALICE, BOB, NOW, TOOL, binding, member, request

from ai_assistant.core.types import (
    CostBasis,
    DataTier,
    PermissionDecision,
    PermissionOutcome,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.permissions import ThresholdActionPolicy
from ai_assistant.testing import (
    FakeAuditTrail,
    FakeRecipientGrantResolution,
    FakeRecipientGrants,
    recipient_grant,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import ActionPolicy
    from ai_assistant.core.types import RecipientGrant


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


@pytest.mark.parametrize("truthy", ["false", 1, object()], ids=["string", "int", "object"])
async def test_only_true_counts_as_consent(truthy: object) -> None:
    """An unparsed value handed on by an adapter must not read as an approval.

    ``approved`` is annotated ``bool`` and mypy runs strict over ``src`` and
    ``tests``, so this is a type error before it is a runtime one. It is pinned
    anyway because the mistake produces a *truthy* value — a form field's
    ``"false"`` is the sharp case — and the failure it would cause is the one
    failure this subsystem must not have: a decline rendered as an
    authorisation.
    """
    resolved = await ThresholdActionPolicy().resolve(
        decision("d-confirm"),
        approved=truthy,  # type: ignore[arg-type]  # a caller ignoring the annotation is the case
    )

    assert resolved.outcome is PermissionOutcome.DENY
    assert resolved.authorised_by is None


# --- ADR-0193 §3, §7: route (b), where this policy was given a grant seam -----
#
# A policy constructed with no ``RecipientGrants`` is unchanged and every case
# above still binds it. What follows is about the one constructed *with* one, and
# every case here would pass vacuously against a policy that never consulted the
# seam — which is why the call counts are asserted beside the outcomes.


def _sourced(
    *records: RecipientGrant, **thresholds: Any
) -> tuple[ThresholdActionPolicy, FakeRecipientGrants]:
    """A policy over a seam holding ``records``, and the seam, for its call count.

    The call count is what every case below turns on beside its outcome: a policy
    that never consulted the seam would pass the outcome half of most of them, and
    §7's whole discipline is about *when* the read happens rather than about what
    it returns.
    """
    grants = FakeRecipientGrants(records)
    return ThresholdActionPolicy(grants=grants, **thresholds), grants


async def test_a_covering_grant_turns_the_disclosure_floor_into_an_allow() -> None:
    """The successful handoff, end to end (ADR-0193 §14).

    The one case that pins the production path: the ``ALLOW`` names **that
    grant's** id and carries **that grant's recomputed** ``subject_digest``, and
    the decision built from it is then accepted by an ``AuditTrail`` over the
    matching resolution face. A policy stamping a fixed well-formed digest passes
    every origin, error and call-count case below while making every ordinary
    route-(b) decision unrecordable, and every audit-side digest case can be
    satisfied with hand-built rulings that never exercise a policy at all — so
    the two halves are only joined here.

    ADR-0021 §5's floor is **satisfied rather than relaxed**: it forbids an
    ``ALLOW`` with ``authorised_by`` unset for a non-empty ``discloses``, and this
    one sets it. §5's own text already named this mechanism as the relief valve.
    """
    granted = recipient_grant(member(ALICE), grant_id="g-1")
    policy, grants = _sourced(granted)
    subject = request(binding(ALICE))

    ruled = await policy.decide(subject)

    assert ruled.outcome is PermissionOutcome.ALLOW
    assert ruled.authorised_by == "g-1"
    assert ruled.authorised_subject == granted.subject_digest
    assert grants.call_count == 1

    trail = FakeAuditTrail(recipient_grants=FakeRecipientGrantResolution([granted]))
    recorded = PermissionDecision.from_request(subject, ruled, id="d-1", decided_at=NOW)

    assert await trail.record(recorded) == "d-1"


async def test_no_grant_covering_the_request_leaves_the_confirmation_standing() -> None:
    """The seam is consulted, answers ``None``, and the ruling proceeds unchanged."""
    policy, grants = _sourced(recipient_grant(member(BOB), grant_id="g-1"))

    ruled = await policy.decide(request(binding(ALICE)))

    assert ruled.outcome is PermissionOutcome.CONFIRM
    assert ruled.authorised_by is None
    assert ruled.authorised_subject is None
    assert grants.call_count == 1


async def test_a_grant_covers_no_call_planned_over_external_content() -> None:
    """ADR-0098 §3's last clause, answered **no**, and enforced at the ruling.

    With a live grant covering every member of the canonical destination set in
    place. A case asserting only that the grant is consulted does not satisfy
    ADR-0193 §14's clause — and this one asserts the opposite, that the seam is
    not consulted at all, because §7 puts the lookup after every ground the
    request alone settles and a call carrying the fact is one of them.
    """
    policy, grants = _sourced(recipient_grant(member(ALICE), grant_id="g-1"))

    ruled = await policy.decide(request(binding(ALICE, external=True)))

    assert ruled.outcome is PermissionOutcome.CONFIRM
    assert ruled.authorised_by is None
    assert grants.call_count == 0


async def test_a_request_carrying_no_binding_reaches_the_seam_zero_times() -> None:
    """A request with no ``egress_binding`` is not an egress call (ADR-0193 §7).

    Asserted over the recorded count rather than over the outcome, because the
    outcome is the same either way: what this rules out is an implementation that
    consults the store first and then rules on the request's own facts, which
    would let a store failure disturb an answer the request had already given.
    """
    policy, grants = _sourced(recipient_grant(member(ALICE), grant_id="g-1"))

    ruled = await policy.decide(action(tool=tool(discloses=(DataTier.PERSONAL,))))

    assert ruled.outcome is PermissionOutcome.CONFIRM
    assert grants.call_count == 0


@pytest.mark.parametrize(
    ("thresholds", "declared", "expected"),
    [
        pytest.param(
            {},
            {"cost": ToolCost(basis=CostBasis.UNKNOWN)},
            PermissionOutcome.CONFIRM,
            id="an undeclared cost",
        ),
        pytest.param(
            {},
            {"risk_level": RiskLevel.HIGH},
            PermissionOutcome.CONFIRM,
            id="risk at the confirm threshold",
        ),
        pytest.param(
            {"confirm_at_reversibility": Reversibility.RECOVERABLE},
            {"reversibility": Reversibility.RECOVERABLE},
            PermissionOutcome.CONFIRM,
            id="reversibility at the confirm threshold",
        ),
        pytest.param(
            {"deny_at_risk": RiskLevel.LOW},
            {},
            PermissionOutcome.DENY,
            id="a threshold deny",
        ),
    ],
)
async def test_a_grant_discharges_the_disclosure_floor_and_no_other_ground(
    thresholds: dict[str, Any], declared: dict[str, Any], expected: PermissionOutcome
) -> None:
    """§3's *only-effect* clause as a test, and only these four reach it.

    A grant "never converts a ``DENY`` into anything" and satisfies no floor stated
    over any fact but recipient authorisation. Each case has a live grant covering
    every member of the request's canonical destination set in place and still
    draws the outcome it drew without one, and each asserts **zero** ``covering``
    calls beside it: §7 puts those grounds on the far side of the seam, so a
    policy consulting the store first and then ruling on the request's own facts
    lets a store failure disturb an answer that was already given.

    A policy returning ``ALLOW`` the moment ``covering`` succeeds suppresses all
    four while passing the handoff, origin and call-count cases above — and the
    ``ActionPolicy`` suite it also runs does not catch it, because
    ``test_an_undeclared_cost_is_never_auto_granted`` asserts
    ``not (ALLOW and authorised_by is None)`` and a route-(b) ``ALLOW`` sets
    ``authorised_by``.
    """
    declaration = TOOL.model_copy(update=declared)
    granted = recipient_grant(member(ALICE), grant_id="g-1", tool=declaration)
    policy, grants = _sourced(granted, **thresholds)

    ruled = await policy.decide(request(binding(ALICE), tool=declaration))

    assert ruled.outcome is expected
    assert ruled.authorised_by is None
    assert ruled.authorised_subject is None
    assert grants.call_count == 0


async def test_an_unreadable_seam_yields_no_allow_and_no_cached_answer() -> None:
    """A component that cannot get an answer **fails closed** (ADR-0193 §1).

    An implementation that reused the last successful lookup passes every other
    policy case here while authorising sends after its authorisation stopped being
    checkable, so the case is written as a successful ruling followed by a failing
    one against the same policy.
    """
    granted = recipient_grant(member(ALICE), grant_id="g-1")
    grants = FakeRecipientGrants([granted])
    policy = ThresholdActionPolicy(grants=grants)
    subject = request(binding(ALICE))
    assert (await policy.decide(subject)).outcome is PermissionOutcome.ALLOW

    grants.fail_covering()
    ruled = await policy.decide(subject)

    assert ruled.outcome is PermissionOutcome.CONFIRM
    assert ruled.authorised_by is None
    assert ruled.authorised_subject is None


async def test_a_partly_covered_destination_set_draws_one_confirmation_about_all_of_it() -> None:
    """ADR-0193 §8: ``CONFIRM`` rather than ``DENY``, and about the **whole** call.

    ``DENY`` would make a grant over one of two recipients strictly worse than no
    grant at all, which is the shape a user would learn to avoid by never
    granting. And nothing narrows the set: the request the ruling is taken over
    still names both members, so the confirmation built from it names both — a
    card asking about the recipients the user has not blessed, for a message going
    to two, is ADR-0148 §4's silent narrowing arriving at the surface instead of
    at the transport.
    """
    policy, grants = _sourced(recipient_grant(member(ALICE), grant_id="g-1"))
    subject = request(binding(ALICE, BOB))

    ruled = await policy.decide(subject)

    assert ruled.outcome is PermissionOutcome.CONFIRM
    assert ruled.authorised_by is None
    assert grants.call_count == 1
    assert subject.egress_binding is not None
    assert subject.egress_binding.canonical_destination_set == (member(ALICE), member(BOB))


async def test_a_policy_with_no_seam_is_unchanged_by_any_of_this() -> None:
    """ADR-0021 §3's requirement of a policy constructed with no authorisation source.

    The condition that bullet already contemplated, and the one ADR-0193 §12's
    supersession is bounded by: for a policy with none, both purity sentences bind
    as written and ``decide`` is the function of its argument it always was.
    """
    policy = ThresholdActionPolicy()

    ruled = await policy.decide(request(binding(ALICE)))

    assert ruled.outcome is PermissionOutcome.CONFIRM
    assert ruled.authorised_by is None
    assert ruled.authorised_subject is None
