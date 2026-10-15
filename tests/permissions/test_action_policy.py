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
from recipient_builders import (
    ALICE,
    FORECAST_ACCOUNT,
    FORECAST_CANONICAL,
    FORECAST_ORIGIN,
    FORECAST_TOOL,
    NOW,
    SEARCH_ACCOUNT,
    SEARCH_CANONICAL,
    SEARCH_ORIGIN,
    SEARCH_TOOL,
    TOOL,
    binding,
    forecast_binding,
    forecast_member,
    request,
    search_binding,
    search_member,
)

from ai_assistant.core.types import (
    CostBasis,
    DataTier,
    PermissionDecision,
    PermissionOutcome,
    Reversibility,
    RiskLevel,
    SpanCoverage,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.permissions import (
    ConfiguredForecastDestination,
    ConfiguredSearchDestination,
    ThresholdActionPolicy,
)
from ai_assistant.testing import FakeAuditTrail

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


# --- ADR-0247 §2, §3: route (c), the deployment's own configured search provider ---
#
# The ADR writes its primed arm names with a prime and its second C with a
# subscript; both are rendered as a plain apostrophe and a plain digit here,
# because ruff refuses the ambiguous characters in Python source.
#
# ADR-0148 §3's enumeration gains a third route, and §12's arms A, B, B', C, C2, C'
# and C″ are what hold it to its stated extent. The policy holds no grant seam: route
# (b) retired with recipient grants (ADR-0321 §7:1), so route (c) is the one standing
# route, and it reads the binding alone.
#
# The **binding** is the search-shaped one `recipient_builders` builds — one HTTPS
# span over the `origin` argument, `closed_loop` `True` — because §1's predicate is
# stated over a binding's own account and canonical destination set, and an arm
# arranged over a send's binding would be asserting about a shape no search produces.


def _configured(
    *, reference: str = SEARCH_ACCOUNT.reference, canonical: str = SEARCH_CANONICAL
) -> ConfiguredSearchDestination:
    """The pair a composition root hands the policy (ADR-0247 §2).

    Defaulted to what :func:`search_binding` derives, so a case that wants a
    **mismatch** states the one character it changes and nothing else — which is the
    shape §12's Arms C and C2 are written over.
    """
    return ConfiguredSearchDestination(
        reference=reference, destinations=frozenset({search_member(canonical)})
    )


def _at_provider(**overrides: Any) -> ThresholdActionPolicy:
    """A policy configured with the search destination.

    It holds no grant seam, because none is left to hold (ADR-0321 §7:1): route (c)
    is the only standing route, and it reads the binding alone.
    """
    arguments: dict[str, Any] = {"configured_search": _configured()}
    arguments.update(overrides)
    return ThresholdActionPolicy(**arguments)


async def test_a_search_at_the_configured_provider_is_allowed_with_no_grant_record() -> None:
    """§12's **Arm A**, and the handoff into the trail in one case.

    A turn that has read a local file and then searches: the binding carries
    ``planned_with_external_content``, and the ruling is an ``ALLOW`` on route (c)
    whose ``authorised_by`` is the binding's own ``account.reference`` and whose
    ``authorised_subject`` is unset.

    The decision built from that ruling is then recorded by an ``AuditTrail``, which
    is the join ADR-0247 §2 rests on: the policy's pointer
    is a value the trail re-reads off the binding, so the two halves of route (c)
    agree by construction rather than by two lanes each being right on its own.
    """
    policy = _at_provider()
    subject = request(search_binding(external=True), tool=SEARCH_TOOL)

    ruled = await policy.decide(subject)

    assert ruled.outcome is PermissionOutcome.ALLOW
    assert ruled.authorised_by == SEARCH_ACCOUNT.reference
    assert ruled.authorised_subject is None

    trail = FakeAuditTrail()
    recorded = PermissionDecision.from_request(subject, ruled, id="d-1", decided_at=NOW)

    assert await trail.record(recorded) == "d-1"


async def test_a_policy_with_no_grant_seam_at_all_still_reaches_route_c() -> None:
    """§2: a policy constructed with no grant seam reaches route (c).

    The one way route (c)'s reachability differs from route (b)'s, and the decision
    rather than an oversight: the authority it cites is the deployment's own
    configuration, which the policy is handed no seam for and needs none. ADR-0021
    §3's "a policy with no authorisation source leaves ``authorised_by`` unset" is
    superseded in that limb and in no other — which the case below holds it to.
    """
    policy = ThresholdActionPolicy(configured_search=_configured())

    ruled = await policy.decide(request(search_binding(external=True), tool=SEARCH_TOOL))

    assert ruled.outcome is PermissionOutcome.ALLOW
    assert ruled.authorised_by == SEARCH_ACCOUNT.reference
    assert ruled.authorised_subject is None


async def test_a_sourceless_policy_still_sets_neither_field_on_every_other_request() -> None:
    """The other limb of that supersession, which bounds it (ADR-0247 §2).

    "On every other request a sourceless policy still sets neither field." Without
    this row a policy that set ``authorised_by`` from any binding's account would pass
    the case above while authorising every egress call on the strength of its own
    connection reference.
    """
    policy = ThresholdActionPolicy(configured_search=_configured())

    ruled = await policy.decide(request(binding(ALICE)))

    assert ruled.outcome is PermissionOutcome.CONFIRM
    assert ruled.authorised_by is None
    assert ruled.authorised_subject is None


@pytest.mark.parametrize(
    ("external", "coverage"),
    [
        pytest.param(True, SpanCoverage.MODEL_ON_EVERY_PATH, id="Arm B: both limbs at once"),
        pytest.param(False, SpanCoverage.MODEL_ON_EVERY_PATH, id="Arm B': coverage alone"),
        pytest.param(True, SpanCoverage.NOT_COVERED, id="Arm A's limb: lineage alone"),
    ],
)
async def test_both_floors_retire_at_the_configured_provider_and_retire_together(
    *, external: bool, coverage: SpanCoverage
) -> None:
    """§12's **Arms B and B'**, and §3's "both limbs are satisfied by one fact".

    A query the retired ``QueryComposer`` composed over a supply carrying any record at
    all was a model-composed span over covered content, so its ``SpanCoverage`` was
    ``MODEL_ON_EVERY_PATH`` whenever the supply carried one. **Arm B' is the row a
    lane that retired only the lineage limb fails**: with
    ``planned_with_external_content`` ``False`` and the coverage limb alone standing,
    the ruling is still the same ``ALLOW``.

    The third row is the converse, for the same reason in the other direction: a lane
    that retired only the coverage limb would still be stopped on every turn that had
    read anything.
    """
    policy = _at_provider()
    bound = search_binding(external=external, coverage=coverage)

    ruled = await policy.decide(request(bound, tool=SEARCH_TOOL))

    assert ruled.outcome is PermissionOutcome.ALLOW
    assert ruled.authorised_by == SEARCH_ACCOUNT.reference
    assert ruled.authorised_subject is None


@pytest.mark.parametrize(
    "mismatch",
    [
        pytest.param({"account": SEARCH_ACCOUNT.model_copy(update={"reference": "conn-searcH"})}),
        pytest.param({"canonical": "https://search.example.com:444"}),
    ],
    ids=["the connection reference", "the canonical destination"],
)
@pytest.mark.parametrize(
    ("external", "coverage"),
    [
        pytest.param(True, SpanCoverage.NOT_COVERED, id="Arm C: over external content"),
        pytest.param(False, SpanCoverage.MODEL_ON_EVERY_PATH, id="Arm C2: over covered content"),
    ],
)
async def test_a_closed_loop_binding_elsewhere_keeps_every_floor(
    mismatch: dict[str, Any], *, external: bool, coverage: SpanCoverage
) -> None:
    """§12's **Arms C and C2** — the two that fail a check put beside the route.

    The binding carries ``closed_loop`` **``True``**, which §4 makes the value a
    mismatched ``WEB_SEARCH`` proposal still produces, and differs from the configured
    destination **by one character** — in the connection reference or in the canonical
    form, each on its own, because §1 compares both and either alone would leave the
    other unchecked.

    The ruling is ``CONFIRM`` and no ``ALLOW`` is reached — which holds only because
    §3's limbs read the derived fact rather than sitting beside route (c), which is
    what these two arms exist to say.
    """
    bound = search_binding(external=external, coverage=coverage, **mismatch)
    policy = _at_provider()
    subject = request(bound, tool=SEARCH_TOOL)

    ruled = await policy.decide(subject)

    assert ruled.outcome is PermissionOutcome.CONFIRM
    assert ruled.authorised_by is None
    assert ruled.authorised_subject is None


async def test_a_policy_with_no_configured_destination_reaches_no_route_c() -> None:
    """§12's **Arm C'**: the predicate is false for every request (ADR-0247 §2).

    The fail-closed direction, and the same shape ADR-0021 §3 gives a policy with no
    authorisation source: an otherwise perfect route-(c) request draws ``CONFIRM``.
    """
    policy = _at_provider(configured_search=None)

    ruled = await policy.decide(request(search_binding(external=True), tool=SEARCH_TOOL))

    assert ruled.outcome is PermissionOutcome.CONFIRM
    assert ruled.authorised_by is None


async def test_a_call_of_another_kind_through_the_same_account_confirms_as_today() -> None:
    """§12's **Arm C″**, the cross-kind arm, at the half a policy can state.

    A ``send_email`` and every other non-``WEB_SEARCH`` egress call bind ``closed_loop``
    ``False`` (§4), so the derived fact is false for them whatever this deployment is
    configured with — asserted here through the **same connected account and the same
    destination** as the configured search, which is the sharpest form of it: nothing
    rides this that is not a ``WEB_SEARCH`` at the configured provider, "in the very
    same conversation and the very same turn" (§3's last clause).

    ``orchestration`` writing that ``False`` is lane 3's half of the arm; what is
    asserted here is that the policy rules on the fact rather than on the account.
    """
    policy = _at_provider()
    bound = search_binding(external=True, closed_loop=False)

    ruled = await policy.decide(request(bound, tool=TOOL))

    assert ruled.outcome is PermissionOutcome.CONFIRM
    assert ruled.authorised_by is None


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
            {"deny_at_risk": RiskLevel.LOW},
            {},
            PermissionOutcome.DENY,
            id="a threshold deny",
        ),
    ],
)
async def test_the_configuration_discharges_the_disclosure_floor_and_no_other_ground(
    thresholds: dict[str, Any], declared: dict[str, Any], expected: PermissionOutcome
) -> None:
    """§2: "Every other ground survives exactly as ADR-0193 §3 requires of a grant".

    An ``UNKNOWN`` cost still draws ``CONFIRM`` at the configured provider, a
    ``risk_level`` or a ``reversibility`` at this policy's own threshold still draws
    ``CONFIRM``, and a threshold ``DENY`` still stands — and each reaches no route at
    all, because ``fired == [_DISCLOSURE_FLOOR]`` is false for it. ADR-0247 §9 names
    the unknown-cost floor and the two thresholds as untouched by every clause of that
    decision; this is where the naming becomes a check.

    A policy returning ``ALLOW`` the moment the configuration matches suppresses all
    three while passing every case above.
    """
    declaration = SEARCH_TOOL.model_copy(update=declared)
    policy = _at_provider(**thresholds)

    ruled = await policy.decide(request(search_binding(external=True), tool=declaration))

    assert ruled.outcome is expected
    assert ruled.authorised_by is None
    assert ruled.authorised_subject is None


async def test_the_route_c_reason_names_the_basis_and_quotes_no_identifier() -> None:
    """§2's last normative clause, and ADR-0148 §6's bar it rests on.

    "The reason text says that this deployment's owner configured this search
    provider, and it names **no origin, no host, no connection reference, no
    credential and no ``Settings`` field**." ``BoundAccount.reference`` is never shown
    to the user, and this decision does not move that: the reference is recorded on
    the decision for an auditor and rendered to nobody.
    """
    policy = _at_provider()

    ruled = await policy.decide(request(search_binding(external=True), tool=SEARCH_TOOL))

    assert "configured this search provider" in ruled.reason
    for quoted in (SEARCH_ACCOUNT.reference, SEARCH_ORIGIN, SEARCH_CANONICAL, "search.example.com"):
        assert quoted not in ruled.reason
    assert "web_search_connection" not in ruled.reason
    assert "web_search_origin" not in ruled.reason


# --- ADR-0260 §6, §13: route (c) widened to the configured forecast provider ---
#
# §6 widens ADR-0247 §2's route (c) to a **closed two-member set** and adds no fourth
# route, with each kind compared against **its own** configured pair: a read at the
# configured forecast provider is `ALLOW` "with no confirmation sought".
#
# The **binding** is `forecast_binding`, the forecast-shaped one — one HTTPS span over
# the `origin` argument, `forecast_reach` `True`, `closed_loop` `False` — because §6's
# predicate is stated over a binding's own account and canonical destination set, and
# the two configured pairs in this block deliberately differ in both, so a crosswise
# case has a subject.


def _configured_forecast(
    *, reference: str = FORECAST_ACCOUNT.reference, canonical: str = FORECAST_CANONICAL
) -> ConfiguredForecastDestination:
    """The forecast pair a composition root hands the policy (ADR-0260 §6, §12's L2).

    :func:`_configured`'s twin, defaulted to what :func:`forecast_binding` derives, so
    a case that wants a **mismatch** states the one character it changes and nothing
    else — the shape §13's Arm (d) is written over.
    """
    return ConfiguredForecastDestination(
        reference=reference, destinations=frozenset({forecast_member(canonical)})
    )


def _at_both(**overrides: Any) -> ThresholdActionPolicy:
    """A policy configured with **both** pairs.

    Both, because §6's crosswise clause has no subject on a policy that holds only
    one: "a forecast request bound to the search provider's account or origin, or the
    reverse, takes no route at all" is a statement about a deployment that configured
    two providers, and a policy holding one pair would refuse the crosswise request on
    the missing pair instead of on the mismatch.
    """
    arguments: dict[str, Any] = {
        "configured_search": _configured(),
        "configured_forecast": _configured_forecast(),
    }
    arguments.update(overrides)
    return ThresholdActionPolicy(**arguments)


async def test_a_forecast_read_at_the_configured_provider_is_allowed_with_no_grant_record() -> None:
    """§13's **Arm (d)** in the affirmative, over all three of §6's conjuncts at once.

    A turn that has read a local file and then reads the forecast: the binding carries
    ``planned_with_external_content``, carries ``forecast_reach``, matches the
    configured forecast pair in both recorded comparisons. The ruling is an ``ALLOW``
    on route (c) whose ``authorised_by`` is the binding's own ``account.reference``
    and whose ``authorised_subject`` is unset.

    **Nothing is asserted here about the audit trail**, which is the one half of
    ADR-0247 §2 this decision does not carry to this kind: that section's trail check
    admits a digest-free standing row "only where its binding's ``closed_loop`` is
    ``True``", and ADR-0260's own header lists "§2's route (c) and its trail check"
    among what "binds entire". So a forecast route-(c) row is refused by
    ``AuditTrail.record`` as the corpus stands — a gap filed as an issue and reported
    to the dispatcher, and **not** something this lane may close: §12's L2 enumerates
    what it owes and the trail is not in it, and widening the check would contradict a
    sentence of a ratified ADR.
    """
    policy = _at_both()
    subject = request(forecast_binding(external=True), tool=FORECAST_TOOL)

    ruled = await policy.decide(subject)

    assert ruled.outcome is PermissionOutcome.ALLOW
    assert ruled.authorised_by == FORECAST_ACCOUNT.reference
    assert ruled.authorised_subject is None


@pytest.mark.parametrize(
    ("external", "coverage"),
    [
        pytest.param(True, SpanCoverage.MODEL_ON_EVERY_PATH, id="both limbs at once"),
        pytest.param(False, SpanCoverage.MODEL_ON_EVERY_PATH, id="coverage alone"),
        pytest.param(True, SpanCoverage.NOT_COVERED, id="lineage alone"),
    ],
)
async def test_both_floors_retire_at_the_configured_forecast_provider_and_retire_together(
    *, external: bool, coverage: SpanCoverage
) -> None:
    """§6's restatement of ``_only_the_disclosure_floor``'s two limbs, at this kind.

    "Both limbs are satisfied by one fact and are not two decisions", and the reason
    is ADR-0247 §3's rather than a new one: a deployment retiring the lineage floor
    alone would still be stopped by the coverage limb on every turn that had read
    anything, and one retiring the coverage exception alone by the lineage floor.
    The middle row is the one a lane that restated only the lineage limb fails, and
    the last is its converse.
    """
    policy = _at_both()
    bound = forecast_binding(external=external, coverage=coverage)

    ruled = await policy.decide(request(bound, tool=FORECAST_TOOL))

    assert ruled.outcome is PermissionOutcome.ALLOW
    assert ruled.authorised_by == FORECAST_ACCOUNT.reference
    assert ruled.authorised_subject is None


@pytest.mark.parametrize(
    "mismatch",
    [
        pytest.param(
            {"account": FORECAST_ACCOUNT.model_copy(update={"reference": "conn-forecasT"})},
            id="the connection reference",
        ),
        pytest.param({"canonical": "https://forecast.example.com:444"}, id="the canonical form"),
        pytest.param({"forecast_reach": False}, id="the carried fact"),
    ],
)
@pytest.mark.parametrize(
    ("external", "coverage"),
    [
        pytest.param(True, SpanCoverage.NOT_COVERED, id="over external content"),
        pytest.param(False, SpanCoverage.MODEL_ON_EVERY_PATH, id="over covered content"),
    ],
)
async def test_a_forecast_read_failing_any_conjunct_keeps_every_floor(
    mismatch: dict[str, Any], *, external: bool, coverage: SpanCoverage
) -> None:
    """§13's **Arm (d)**, over each of §6's three conjuncts on its own.

    "A forecast request whose account or origin is not the configured pair … and a
    forecast request whose kind, account and origin all match and whose
    ``forecast_reach`` is ``False`` — each takes **no** route (c), both
    ``_only_the_disclosure_floor`` limbs bind in full and the ruling is what it is
    today." The two recorded comparisons differ **by one character** each, because §6
    compares both and either alone would leave the other unchecked; and the third row
    is owed in its own right because ``forecast_reach`` is §6's *first* conjunct — a
    policy reading only the kind and the pair passes the other two shapes while
    granting route (c) where §6 refuses it, and ``False`` "is also the value a
    composition site that never computed the fact leaves behind".

    The ruling is ``CONFIRM`` and no ``ALLOW`` is reached.
    """
    bound = forecast_binding(external=external, coverage=coverage, **mismatch)
    policy = _at_both()
    subject = request(bound, tool=FORECAST_TOOL)

    ruled = await policy.decide(subject)

    assert ruled.outcome is PermissionOutcome.CONFIRM
    assert ruled.authorised_by is None
    assert ruled.authorised_subject is None


@pytest.mark.parametrize(
    ("bound", "tool"),
    [
        pytest.param(
            forecast_binding(
                account=SEARCH_ACCOUNT,
                origin=SEARCH_ORIGIN,
                canonical=SEARCH_CANONICAL,
                external=True,
            ),
            FORECAST_TOOL,
            id="a forecast read at the search provider's pair",
        ),
        pytest.param(
            search_binding(
                account=FORECAST_ACCOUNT,
                origin=FORECAST_ORIGIN,
                canonical=FORECAST_CANONICAL,
                external=True,
            ),
            SEARCH_TOOL,
            id="a search at the forecast provider's pair",
        ),
    ],
)
async def test_neither_kind_is_authorised_by_the_other_kinds_configured_pair(
    bound: Any, tool: ToolDefinition
) -> None:
    """§6's crosswise clause, in both directions and on a policy holding both pairs.

    "**Each kind is compared against its own configured pair**; a forecast request
    bound to the search provider's account or origin, or the reverse, takes no route
    at all." Each binding here carries its own kind's fact and matches the **other**
    kind's configured pair exactly — both recorded comparisons, not one — so an
    implementation comparing against whichever pair happens to match, or against the
    two as one set, passes every arm above and fails both rows here.
    """
    policy = _at_both()

    ruled = await policy.decide(request(bound, tool=tool))

    assert ruled.outcome is PermissionOutcome.CONFIRM
    assert ruled.authorised_by is None


async def test_a_binding_asserting_both_kinds_is_at_no_configured_provider() -> None:
    """§6's closed set, on the one shape neither member of it describes.

    ADR-0260 §11 writes ``forecast_reach`` "exactly where the request's kind is a
    forecast read" and leaves ``closed_loop`` meaning "this deployment's own search
    and nothing else, and a forecast read never sets it", so a binding carrying both
    asserts a kind route (c)'s two-member set does not contain. Selecting either pair
    for it would let one kind's configuration authorise the other's, which §6 forbids
    in terms — so the ambiguity fails closed.

    Arranged at the **forecast** pair, which is the sharper half: an implementation
    testing ``closed_loop`` first and falling through would rule this an ``ALLOW``
    the moment the forecast pair matched.

    §13's own preamble is the authority for the arm: the enumeration there "is a
    floor and not a ceiling", and "every normative clause of this decision that an
    implementation can fail is owed an arm".
    """
    policy = _at_both()
    bound = forecast_binding(external=True, closed_loop=True)

    ruled = await policy.decide(request(bound, tool=FORECAST_TOOL))

    assert ruled.outcome is PermissionOutcome.CONFIRM
    assert ruled.authorised_by is None


async def test_a_forecast_only_policy_reaches_route_c_with_no_seam_and_no_search_pair() -> None:
    """ADR-0247 §2's sourceless clause carried to this kind by ADR-0260 §6.

    "A policy constructed with no ``RecipientGrants`` reaches route (c)" — the one way
    route (c)'s reachability differs from route (b)'s — and §6 carries the supersession
    of ADR-0021 §3 "to a forecast read at the configured forecast provider and to no
    further kind". Asserted on a policy holding **nothing else**: no grant seam, no
    goal-authorization seam, and no search pair either, because a deployment that
    configured a forecast provider and connected no search account is an ordinary one
    and an implementation requiring either before honouring the forecast pair would
    make every such deployment ask.
    """
    policy = ThresholdActionPolicy(configured_forecast=_configured_forecast())

    ruled = await policy.decide(request(forecast_binding(external=True), tool=FORECAST_TOOL))

    assert ruled.outcome is PermissionOutcome.ALLOW
    assert ruled.authorised_by == FORECAST_ACCOUNT.reference
    assert ruled.authorised_subject is None


async def test_a_policy_with_no_configured_forecast_reaches_no_route_c_on_a_forecast_read() -> None:
    """The fail-closed direction at this kind, and the two pairs' independence.

    ADR-0260 §6 read through ADR-0247 §2: an otherwise perfect route-(c) forecast read
    draws ``CONFIRM`` where the deployment configured no forecast provider — which is
    also what ``forecast_reach``'s restrictive default gives a site that never computed
    the fact. The **same policy still reaches route (c) on a search**, which is what
    keeps the first half from passing on a policy that had simply stopped working.
    """
    policy = _at_both(configured_forecast=None)

    forecast = await policy.decide(request(forecast_binding(external=True), tool=FORECAST_TOOL))

    assert forecast.outcome is PermissionOutcome.CONFIRM
    assert forecast.authorised_by is None

    searched = await policy.decide(request(search_binding(external=True), tool=SEARCH_TOOL))

    assert searched.outcome is PermissionOutcome.ALLOW
    assert searched.authorised_by == SEARCH_ACCOUNT.reference


async def test_the_forecast_read_asks_nothing_and_the_turns_other_send_is_unaffected() -> None:
    """§13's **Arm (e)**: no new question, and nothing rides it that is not this read.

    "A turn on a goal whose supply already carries an external record asks for a
    forecast at the configured provider and is ruled ``ALLOW`` with **no** ``CONFIRM``,
    **no** grant seam read and ``authorised_subject`` unset — and the same turn's
    search at an unconfigured destination is unaffected."

    The ``ALLOW`` names the connection reference and carries no goal scope: route (c)
    answers it. The second ruling is
    the same policy in the same turn on a search bound elsewhere —
    ADR-0260 §6's last normative clause, "nothing rides this that is not a forecast
    read at the configured forecast provider".
    """
    policy = _at_both()

    forecast = await policy.decide(
        request(
            forecast_binding(external=True, coverage=SpanCoverage.MODEL_ON_EVERY_PATH),
            tool=FORECAST_TOOL,
        )
    )

    assert forecast.outcome is PermissionOutcome.ALLOW
    assert forecast.authorised_by == FORECAST_ACCOUNT.reference
    assert forecast.authorised_subject is None

    elsewhere = await policy.decide(
        request(
            search_binding(external=True, canonical="https://elsewhere.example.com:443"),
            tool=SEARCH_TOOL,
        )
    )

    assert elsewhere.outcome is PermissionOutcome.CONFIRM
    assert elsewhere.authorised_by is None


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
            {"deny_at_risk": RiskLevel.LOW},
            {},
            PermissionOutcome.DENY,
            id="a threshold deny",
        ),
    ],
)
async def test_the_forecast_configuration_discharges_the_disclosure_floor_and_no_other_ground(
    thresholds: dict[str, Any], declared: dict[str, Any], expected: PermissionOutcome
) -> None:
    """ADR-0260 §11 leaves the unknown-cost floor and the thresholds standing here too.

    "Where the cost pair is unset the unknown-cost floor binds unchanged", and §6
    retires the two disclosure limbs and nothing else. Each row reaches no route at
    all, because ``fired == [_DISCLOSURE_FLOOR]`` is false for it — a policy returning
    ``ALLOW`` the moment the forecast configuration matched suppresses both while
    passing every case above.
    """
    declaration = FORECAST_TOOL.model_copy(update=declared)
    policy = _at_both(**thresholds)

    ruled = await policy.decide(request(forecast_binding(external=True), tool=declaration))

    assert ruled.outcome is expected
    assert ruled.authorised_by is None


async def test_the_forecast_route_c_reason_names_the_basis_and_quotes_no_identifier() -> None:
    """The route-(c) ground at this kind, held to ADR-0247 §2's last clause.

    The sentence says that this deployment's owner configured this **forecast**
    provider — its own text rather than the search one, so a surface cannot report a
    forecast read as a search — and it names no origin, no host, no connection
    reference, no coordinate, no credential and no ``Settings`` field.
    """
    policy = _at_both()

    ruled = await policy.decide(request(forecast_binding(external=True), tool=FORECAST_TOOL))

    assert "configured this forecast provider" in ruled.reason
    assert "search" not in ruled.reason
    for quoted in (
        FORECAST_ACCOUNT.reference,
        FORECAST_ORIGIN,
        FORECAST_CANONICAL,
        "forecast.example.com",
    ):
        assert quoted not in ruled.reason
    assert "forecast_connection" not in ruled.reason
    assert "forecast_origin" not in ruled.reason


async def test_a_search_at_the_configured_provider_rules_exactly_as_it_did() -> None:
    """The regression pin: widening route (c) moves **no** search ruling.

    ADR-0260 §12 gives this lane "no live behaviour on its own", and a search is the
    only behaviour it could have moved. The whole ruling is compared — outcome,
    pointer, subject **and the reason text** — because the ground is what a surface
    renders, and generalising one sentence over both kinds would have changed it on
    every search this deployment already makes while passing every other arm here.
    """
    policy = _at_both()

    ruled = await policy.decide(request(search_binding(external=True), tool=SEARCH_TOOL))

    assert ruled.outcome is PermissionOutcome.ALLOW
    assert ruled.authorised_by == SEARCH_ACCOUNT.reference
    assert ruled.authorised_subject is None
    assert ruled.reason == (
        "this deployment's owner configured this search provider, so searching it is "
        "the destination they chose and the recipient they granted"
    )
