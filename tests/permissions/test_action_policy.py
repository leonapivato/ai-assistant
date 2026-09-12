"""The default action policy, against its shared conformance suite and beyond it.

The suite fixes a *shape* — monotone, and fail-closed on disclosure and on an
undeclared cost. Everything below the contract line here is about the parts a
shape cannot pin: that the gate actually opens, that each clause bites on its
own, and that the thresholds are the user's while the floors are not.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, final

import pytest
from action_policy_contract import ActionPolicyContract
from permission_builders import action, decision, ruling, tool
from recipient_builders import (
    ALICE,
    BOB,
    ENDPOINT,
    NOW,
    SEARCH_ACCOUNT,
    SEARCH_CANONICAL,
    SEARCH_ORIGIN,
    SEARCH_TOOL,
    TOOL,
    binding,
    member,
    request,
    search_binding,
    search_member,
)

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import RecipientGrantError
from ai_assistant.core.logging import configure_logging
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
from ai_assistant.permissions import ConfiguredSearchDestination, ThresholdActionPolicy
from ai_assistant.testing import (
    FakeAuditTrail,
    FakeRecipientGrantResolution,
    FakeRecipientGrants,
    recipient_grant,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.protocols import ActionPolicy
    from ai_assistant.core.types import ActionRequest, RecipientGrant


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


async def test_a_seam_fault_is_logged_without_the_request_it_was_ruling_on(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The fault line names the seam and the class, and carries no Tier 1 value.

    Round 1's adversarial finding, and it is about the *renderer* rather than
    about the event dict. ``core.logging`` renders through
    ``structlog.dev.ConsoleRenderer``, whose default exception formatter is
    ``rich``'s with ``show_locals=True``, so an ``exc_info=True`` on this line
    writes the ruling frame's locals into the log — and ``request`` carries the
    recipient addresses, the connected account and the transport endpoint.
    ``redact_sensitive`` cannot reach any of it: it runs **before** the renderer
    and over the event dict's keys, and a rendered traceback is neither
    (ADR-0004 §5).

    Asserted over the **rendered output**, never over
    ``structlog.testing.capture_logs`` — that fixture replaces the processor
    chain, so a "does not leak" test written against it passes while the real
    emission path leaks. ``tests/core/test_logging.py`` pins that trap directly.
    """
    configure_logging(Settings())
    grants = FakeRecipientGrants([recipient_grant(member(ALICE), grant_id="g-1")])
    policy = ThresholdActionPolicy(grants=grants)
    grants.fail_covering()
    capsys.readouterr()

    ruled = await policy.decide(request(binding(ALICE)))

    assert ruled.outcome is PermissionOutcome.CONFIRM
    out = capsys.readouterr().out
    assert "recipient_grant_seam_unreadable" in out
    assert "RecipientGrantError" in out
    assert ALICE not in out
    assert ENDPOINT not in out


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


@final
class _YieldingFaultySeam:
    """A ``RecipientGrants`` that suspends and *then* refuses.

    ``FakeRecipientGrants.fail_covering`` refuses without ever suspending, so a
    policy that read the request inside its failure handler passes every case
    written against it. The interval is the point here: the request is rewritten
    while this seam is out, and the handler must still fail closed.
    """

    def __init__(self, rewrite: Callable[[], None]) -> None:
        """Take the rewrite to perform at the suspension this seam creates."""
        self._rewrite = rewrite

    async def covering(self, request: ActionRequest) -> RecipientGrant | None:
        """Suspend, let the caller's request be rewritten, then refuse."""
        del request
        await asyncio.sleep(0)
        self._rewrite()
        msg = "the recipient-grant store could not be read"
        raise RecipientGrantError(msg)


async def test_a_seam_fault_fails_closed_even_where_the_request_was_rewritten() -> None:
    """ADR-0065 on the failure branch, which is the one that must not raise.

    A seam fault is answered ``CONFIRM`` (ADR-0193 §1's fail-closed clause), and
    the handler that answers it composes a log line. Reading ``request.tool.id``
    there reads the caller's object *after* a suspension — so a caller who
    replaces ``request.tool`` while the seam is out turns the fail-closed branch
    into whatever that read raised, out of the very code that exists to keep the
    ruling safe.
    """
    subject = request(binding(ALICE))

    def _rewrite() -> None:
        subject.__dict__["tool"] = None

    policy = ThresholdActionPolicy(grants=_YieldingFaultySeam(_rewrite))

    ruled = await policy.decide(subject)

    assert ruled.outcome is PermissionOutcome.CONFIRM
    assert ruled.authorised_by is None
    assert ruled.authorised_subject is None


# --- ADR-0247 §2, §3: route (c), the deployment's own configured search provider ---
#
# The ADR writes its primed arm names with a prime and its second C with a
# subscript; both are rendered as a plain apostrophe and a plain digit here,
# because ruff refuses the ambiguous characters in Python source.
#
# ADR-0148 §3's enumeration gains a third route, and §12's arms A, B, B', C, C2, C'
# and C″ are what hold it to its stated extent. Every case here turns on the **seam's
# call count** beside its outcome, for the route-(b) block's reason above and for one
# more of its own: §2 puts route (c) *before* the seam is consulted, so a policy that
# looked first and preferred the configuration afterwards would pass every outcome
# assertion while making a ruling at the configured provider cite a grant.
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


def _at_provider(
    *records: RecipientGrant, **overrides: Any
) -> tuple[ThresholdActionPolicy, FakeRecipientGrants]:
    """A policy configured with the search destination, over a seam holding ``records``.

    The seam is handed over **so its call count can be asserted at zero**: a policy
    built with no seam at all would satisfy "the grant seam is consulted zero times"
    vacuously, and §12's Arm A asks for the assertion "over the seam and not over the
    ruling".
    """
    grants = FakeRecipientGrants(records)
    arguments: dict[str, Any] = {"grants": grants, "configured_search": _configured()}
    arguments.update(overrides)
    return ThresholdActionPolicy(**arguments), grants


async def test_a_search_at_the_configured_provider_is_allowed_with_no_grant_record() -> None:
    """§12's **Arm A**, and the handoff into the trail in one case.

    A turn that has read a local file and then searches: the binding carries
    ``planned_with_external_content``, the grant store is **empty**, and the ruling is
    an ``ALLOW`` on route (c) whose ``authorised_by`` is the binding's own
    ``account.reference`` and whose ``authorised_subject`` is unset. **The grant seam
    is consulted zero times**, asserted over the seam rather than over the ruling.

    The decision built from that ruling is then recorded by an ``AuditTrail`` holding
    **no** grant at all, which is the join ADR-0247 §2 rests on: the policy's pointer
    is a value the trail re-reads off the binding, so the two halves of route (c)
    agree by construction rather than by two lanes each being right on its own.
    """
    policy, grants = _at_provider()
    subject = request(search_binding(external=True), tool=SEARCH_TOOL)

    ruled = await policy.decide(subject)

    assert ruled.outcome is PermissionOutcome.ALLOW
    assert ruled.authorised_by == SEARCH_ACCOUNT.reference
    assert ruled.authorised_subject is None
    assert grants.call_count == 0

    trail = FakeAuditTrail(recipient_grants=FakeRecipientGrantResolution([]))
    recorded = PermissionDecision.from_request(subject, ruled, id="d-1", decided_at=NOW)

    assert await trail.record(recorded) == "d-1"


async def test_a_policy_with_no_grant_seam_at_all_still_reaches_route_c() -> None:
    """§2: "A policy constructed with no ``RecipientGrants`` reaches route (c)".

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

    A query a ``QueryComposer`` composed over a supply carrying any record at all is a
    model-composed span over covered content, so its ``SpanCoverage`` is
    ``MODEL_ON_EVERY_PATH`` whenever the supply carries one. **Arm B' is the row a
    lane that retired only the lineage limb fails**: with
    ``planned_with_external_content`` ``False`` and the coverage limb alone standing,
    the ruling is still the same ``ALLOW``.

    The third row is the converse, for the same reason in the other direction: a lane
    that retired only the coverage limb would still be stopped on every turn that had
    read anything.
    """
    policy, grants = _at_provider()
    bound = search_binding(external=external, coverage=coverage)

    ruled = await policy.decide(request(bound, tool=SEARCH_TOOL))

    assert ruled.outcome is PermissionOutcome.ALLOW
    assert ruled.authorised_by == SEARCH_ACCOUNT.reference
    assert ruled.authorised_subject is None
    assert grants.call_count == 0


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

    **With a grant covering the request in the store**, so the case is not passing on
    the absence of one: the ruling is ``CONFIRM``, the grant seam is consulted
    **zero** times, and no ``ALLOW`` of any route is reached. That is §2's "reaches
    route (b) in no case that route (b) does not already admit" — and it holds only
    because §3's limbs read the derived fact rather than sitting beside route (c),
    which is what these two arms exist to say.
    """
    bound = search_binding(external=external, coverage=coverage, **mismatch)
    covering = recipient_grant(
        search_member(canonical=str(bound.spans[0].destination.canonical)),  # type: ignore[union-attr]  # the span this builder writes carries one
        grant_id="g-1",
        tool=SEARCH_TOOL,
        account=bound.account,
    )
    policy, grants = _at_provider(covering)
    subject = request(bound, tool=SEARCH_TOOL)

    ruled = await policy.decide(subject)

    assert ruled.outcome is PermissionOutcome.CONFIRM
    assert ruled.authorised_by is None
    assert ruled.authorised_subject is None
    assert grants.call_count == 0
    # The premise, over a second seam so the count above stays this ruling's: the
    # store really does hold a grant covering this call, so the ``CONFIRM`` is the
    # floors binding rather than a grant that never matched.
    assert await FakeRecipientGrants([covering]).covering(subject) is not None


async def test_a_policy_with_no_configured_destination_reaches_no_route_c() -> None:
    """§12's **Arm C'**: the predicate is false for every request (ADR-0247 §2).

    The fail-closed direction, and the same shape ADR-0021 §3 gives a policy with no
    authorisation source: an otherwise perfect route-(c) request draws ``CONFIRM``.
    """
    policy, grants = _at_provider(configured_search=None)

    ruled = await policy.decide(request(search_binding(external=True), tool=SEARCH_TOOL))

    assert ruled.outcome is PermissionOutcome.CONFIRM
    assert ruled.authorised_by is None
    assert grants.call_count == 0


async def test_a_route_b_request_on_such_a_policy_rules_exactly_as_it_does_today() -> None:
    """Arm C''s second half, which keeps the first from passing vacuously.

    "A route-(b) request that never carried ``closed_loop`` rules exactly as it does
    at ``origin/main``": the covering grant still discharges the disclosure floor, the
    seam is still read once, and the ``ALLOW`` still names the grant and its digest.
    """
    granted = recipient_grant(member(ALICE), grant_id="g-1")
    policy, grants = _at_provider(granted, configured_search=None)

    ruled = await policy.decide(request(binding(ALICE)))

    assert ruled.outcome is PermissionOutcome.ALLOW
    assert ruled.authorised_by == "g-1"
    assert ruled.authorised_subject == granted.subject_digest
    assert grants.call_count == 1


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
    policy, grants = _at_provider()
    bound = search_binding(external=True, closed_loop=False)

    ruled = await policy.decide(request(bound, tool=TOOL))

    assert ruled.outcome is PermissionOutcome.CONFIRM
    assert ruled.authorised_by is None
    assert grants.call_count == 0


async def test_route_c_answers_before_the_grant_seam_where_both_would_be_reachable() -> None:
    """§2's ordering clause: "no ruling at the configured provider ever cites a grant".

    With a grant in the store that **does** cover the request, so both routes would
    answer it: (c) answers first, ``_covering`` is called zero times, and the recorded
    ``authorised_by`` is the connection reference rather than the grant's id. A policy
    that consulted the seam first and preferred the configuration afterwards passes
    every other case in this block and fails this one.
    """
    covering = recipient_grant(
        search_member(), grant_id="g-1", tool=SEARCH_TOOL, account=SEARCH_ACCOUNT
    )
    policy, grants = _at_provider(covering)

    ruled = await policy.decide(request(search_binding(), tool=SEARCH_TOOL))

    assert ruled.outcome is PermissionOutcome.ALLOW
    assert ruled.authorised_by == SEARCH_ACCOUNT.reference
    assert ruled.authorised_subject is None
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
    policy, grants = _at_provider(**thresholds)

    ruled = await policy.decide(request(search_binding(external=True), tool=declaration))

    assert ruled.outcome is expected
    assert ruled.authorised_by is None
    assert ruled.authorised_subject is None
    assert grants.call_count == 0


async def test_the_route_c_reason_names_the_basis_and_quotes_no_identifier() -> None:
    """§2's last normative clause, and ADR-0148 §6's bar it rests on.

    "The reason text says that this deployment's owner configured this search
    provider, and it names **no origin, no host, no connection reference, no
    credential and no ``Settings`` field**." ``BoundAccount.reference`` is never shown
    to the user, and this decision does not move that: the reference is recorded on
    the decision for an auditor and rendered to nobody.
    """
    policy, _ = _at_provider()

    ruled = await policy.decide(request(search_binding(external=True), tool=SEARCH_TOOL))

    assert "configured this search provider" in ruled.reason
    for quoted in (SEARCH_ACCOUNT.reference, SEARCH_ORIGIN, SEARCH_CANONICAL, "search.example.com"):
        assert quoted not in ruled.reason
    assert "web_search_connection" not in ruled.reason
    assert "web_search_origin" not in ruled.reason
