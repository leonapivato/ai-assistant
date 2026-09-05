"""What the operator's per-call figure does to a search (ADR-0236).

ADR-0236 §8's representative-input tests, less the four whose subject is another
file: items 4, 5 and 6 are load-time refusals and live in
``tests/core/test_config.py``; item 8's and item 12's subject is the canonical fake
and lives in ``tests/tools/test_fake_web_searcher.py``; item 11's is the composition
root and lives in ``tests/app/test_composition_web_search.py``.

**The whole point of this module is that nothing in it is modelled.** Before
ADR-0236 the arm ADR-0231 §18 item 1 asks for — *"the search is ``ALLOW``ed on route
(b)"* — was unreachable in production, because ``WEB_SEARCH`` declared ``UNKNOWN``,
``ThresholdActionPolicy`` fired ``_UNKNOWN_COST_FLOOR`` beside the disclosure floor,
and ``_only_the_disclosure_floor`` therefore required a singleton ``fired`` it could
never have (#2111). ``tests/orchestration/test_loop_search.py`` had to substitute a
declaration it constructed itself to reach it, and pinned the gap. Here the
declaration is the one :func:`~ai_assistant.tools.builtin.build_web_search_integration`
registers, the policy is the production ``ThresholdActionPolicy`` at its shipped
thresholds, and the grants seam is the canonical ``RecipientGrants`` holding one
seeded grant.

**Nothing here opens a socket**, for :mod:`web_search_harness`'s reasons: every far
end is a :class:`~ai_assistant.testing.FakeByteChannel` and every host is
``.invalid`` (RFC 6761 §6.4).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

import pytest
from web_search_harness import (
    ORIGIN,
    answering,
    authorised_search,
    bound,
    built,
    request,
    result,
)

from ai_assistant.core.errors import SpendCeilingError, SpendUndeterminedError
from ai_assistant.core.types import (
    ActionRequest,
    CostBasis,
    PermissionOutcome,
    Reversibility,
    RiskLevel,
    SearchRefusal,
)
from ai_assistant.orchestration.reads import SearchDisposition
from ai_assistant.permissions import ThresholdActionPolicy
from ai_assistant.testing import FakeAuditTrail, FakeRecipientGrants
from ai_assistant.testing.recipient_grants import recipient_grant
from ai_assistant.tools.web_search import WEB_SEARCH, checked_search_cost

if TYPE_CHECKING:
    from web_search_harness import Built

    from ai_assistant.core.types import ToolCost, ToolDefinition

pytestmark = pytest.mark.anyio

#: The instant every grant here is live at. Fixed, because ADR-0193 §6 refuses an
#: ``ALLOW`` sourced from a grant that was not live when the ruling was made.
NOW: Final = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)

#: The operator's figure, and the code it is denominated in. Distinctive enough that
#: an assertion about the declaration is not an assertion about a coincidence.
FIGURE: Final = Decimal("0.005")
CODE: Final = "USD"

#: The id the seeded grant carries, so a route-(b) ``ALLOW`` can be asserted to name
#: **this** grant rather than merely to have set the field.
GRANT_ID: Final = "g-search"


def _at() -> datetime:
    return NOW


async def _granted(subject: Built, *, declaration: ToolDefinition | None = None) -> Any:
    """A standing grant covering the search this ``subject`` would make.

    ADR-0193 §3's route-(b) subject, taken over the destination set the **production**
    ``EgressBinder`` derives rather than a hand-built one: a grant whose declaration,
    account or canonical set differed from the request's by so much as a reworded
    description covers nothing, so deriving both from one binding is what keeps the
    coverage a fact about the mechanism.

    Args:
        subject: The configured integration.
        declaration: The declaration to grant over; defaults to the one the builder
            registered.

    Returns:
        The grant.
    """
    tool = subject.declaration if declaration is None else declaration
    derived = await bound(subject, tool=tool)
    return recipient_grant(
        *derived.binding.canonical_destination_set,
        grant_id=GRANT_ID,
        tool=tool,
        account=derived.binding.account,
        decided_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=30),
    )


async def _ruled(
    subject: Built,
    *,
    grants: FakeRecipientGrants,
    declaration: ToolDefinition | None = None,
    **thresholds: Any,
) -> Any:
    """The production policy's ruling on one search this ``subject`` would make.

    Args:
        subject: The configured integration.
        grants: The seam the policy may consult.
        declaration: The declaration to rule on; defaults to the registered one.
        thresholds: Overrides for ``ThresholdActionPolicy``'s own. **Passing none
            leaves the shipped thresholds**, which is the condition ADR-0236 §4's
            first consequence depends on.

    Returns:
        The ruling.
    """
    tool = subject.declaration if declaration is None else declaration
    derived = await bound(subject, tool=tool)
    policy = ThresholdActionPolicy(grants=grants, **thresholds)
    return await policy.decide(
        ActionRequest(
            tool=derived.tool, parameters=dict(derived.parameters), egress_binding=derived.binding
        )
    )


# --------------------------------------------------------------------------- #
# §8 item 1: the figure reaches the declaration and the floor stops firing      #
# --------------------------------------------------------------------------- #


async def test_a_configured_figure_reaches_an_allow_over_a_covering_grant() -> None:
    """§8 item 1, which is ADR-0231 §18's item 1 made reachable.

    "Over ``build_web_search_integration`` with the pair set: the registered
    declaration's ``cost`` is ``PER_CALL`` with that amount and that code, and
    ``ThresholdActionPolicy(grants=…).decide`` on a request carrying it, over a
    covering grant, returns an ``ALLOW`` whose ``reason`` names the standing grant and
    whose ``authorised_by`` is the grant's id."

    **The policy is constructed at the shipped thresholds and this says so**: ADR-0236
    §4's condition is that no threshold rule fires, and ``WEB_SEARCH`` is ``LOW``
    against a default ``confirm_at_risk`` of ``MEDIUM`` and ``REVERSIBLE`` against a
    default ``confirm_at_reversibility`` of ``IRREVERSIBLE``. The companion arm below
    asserts that condition rather than assuming it.
    """
    subject = await built(cost_per_call=FIGURE, cost_currency=CODE)
    grants = FakeRecipientGrants([await _granted(subject)], now=_at)

    ruled = await _ruled(subject, grants=grants)

    assert subject.declaration.cost.basis is CostBasis.PER_CALL
    assert subject.declaration.cost.amount == FIGURE
    assert subject.declaration.cost.currency == CODE
    assert ruled.outcome is PermissionOutcome.ALLOW
    assert ruled.authorised_by == GRANT_ID, "route (b) names the grant it was reached by"
    assert "standing grant" in ruled.reason
    assert grants.call_count == 1, "the seam was consulted exactly once"


async def test_the_shipped_thresholds_are_the_condition_and_not_an_assumption() -> None:
    """§8 item 1's companion arm: ``confirm_at_risk=LOW`` and the ``ALLOW`` is gone.

    ADR-0236 §4 states the condition in terms — a deployment that set
    ``confirm_at_risk=LOW`` has ``_risk_rule`` in ``fired`` beside the disclosure
    floor, so the seam is consulted **zero** times and the search confirms whatever
    the figure says. "Neither is a defect this ADR fixes and neither is one it may
    fix": those are the user's own thresholds (ADR-0036 §1).
    """
    subject = await built(cost_per_call=FIGURE, cost_currency=CODE)
    grants = FakeRecipientGrants([await _granted(subject)], now=_at)

    ruled = await _ruled(subject, grants=grants, confirm_at_risk=RiskLevel.LOW)

    assert ruled.outcome is PermissionOutcome.CONFIRM
    assert ruled.authorised_by is None
    assert grants.call_count == 0, "a threshold the user set settles it, and asks no seam"


async def test_a_reversibility_threshold_the_user_set_defeats_the_lookup_too() -> None:
    """§4's other half of the same condition, which the risk arm alone would not fail.

    A deployment setting ``confirm_at_reversibility=REVERSIBLE`` puts
    ``_reversibility_rule`` in ``fired``, and ``_only_the_disclosure_floor``'s
    singleton test fails on that exactly as it does on the risk rule. Asserted
    separately because an implementation reading only ``risk_level`` would pass the
    arm above.
    """
    subject = await built(cost_per_call=FIGURE, cost_currency=CODE)
    grants = FakeRecipientGrants([await _granted(subject)], now=_at)

    ruled = await _ruled(subject, grants=grants, confirm_at_reversibility=Reversibility.REVERSIBLE)

    assert ruled.outcome is PermissionOutcome.CONFIRM
    assert grants.call_count == 0


# --------------------------------------------------------------------------- #
# §8 item 2: the absence keeps both floors, and the grant is not consulted      #
# --------------------------------------------------------------------------- #


async def test_an_unconfigured_deployment_keeps_both_floors_and_consults_no_grant() -> None:
    """§8 item 2, and ``_only_the_disclosure_floor``'s zero-consultations property.

    "The same wiring with neither field set: the declaration's ``cost`` is
    ``UNKNOWN``, the ruling is ``CONFIRM``, its reason names both grounds, and the
    ``RecipientGrants`` fake fails the test if ``covering`` is called at all."

    The fake is armed to raise rather than merely counted, so the assertion is that
    the lookup did not happen rather than that its answer was ignored — an
    implementation that consulted the seam and then discarded the grant would pass a
    count-only assertion on a suite that had forgotten to check it.
    """
    subject = await built()
    grants = FakeRecipientGrants([await _granted(subject)], now=_at)
    grants.fail_covering(AssertionError("covering was consulted past the cost floor"))

    ruled = await _ruled(subject, grants=grants)

    assert subject.declaration is WEB_SEARCH, "the template is registered unchanged"
    assert subject.declaration.cost.basis is CostBasis.UNKNOWN
    assert ruled.outcome is PermissionOutcome.CONFIRM
    assert "disclose" in ruled.reason, "the disclosure ground"
    assert "cost is undeclared" in ruled.reason, "and the cost ground, beside it"
    assert ruled.authorised_by is None
    assert grants.call_count == 0


# --------------------------------------------------------------------------- #
# §8 item 3: a zero figure is a figure                                          #
# --------------------------------------------------------------------------- #


async def test_a_zero_figure_is_a_per_call_declaration_and_never_a_free_one() -> None:
    """§8 item 3's first half, and ADR-0236 §3's whole subject.

    "``web_search_cost_per_call = 0`` with a currency yields a ``PER_CALL``
    declaration and, at the shipped thresholds, an ``ALLOW`` on the covering grant.
    Its ``basis`` is asserted **not** to be ``FREE``, which fails an implementation
    that mapped zero onto the other member."
    """
    subject = await built(cost_per_call=Decimal("0"), cost_currency=CODE)
    grants = FakeRecipientGrants([await _granted(subject)], now=_at)

    ruled = await _ruled(subject, grants=grants)

    assert subject.declaration.cost.basis is not CostBasis.FREE, "zero is not FREE"
    assert subject.declaration.cost.basis is CostBasis.PER_CALL
    assert subject.declaration.cost.amount == Decimal("0")
    assert subject.declaration.cost.currency == CODE
    assert ruled.outcome is PermissionOutcome.ALLOW
    assert ruled.authorised_by == GRANT_ID


@pytest.mark.parametrize(
    ("figure", "admitted"),
    [(Decimal("0"), True), (FIGURE, False)],
    ids=["zero-projects-nothing", "a-figure-projects-itself"],
)
async def test_a_zero_figure_projects_zero_at_the_gate(*, figure: Decimal, admitted: bool) -> None:
    """§8 item 3's second half, asserted through behaviour rather than a projection read.

    "With that currency equal to ``world_spend_currency``, its projected contribution
    at the gate is ``Decimal("0")``." A ceiling of zero is the arrangement that makes
    that a *behaviour*: ADR-0194 §4 admits a projection exactly equal to a ceiling and
    refuses one strictly above it, so a zero figure passes a zero ceiling and any
    other figure does not. That is what ADR-0194 §2's *"A ``FREE`` basis contributes
    zero, in both totals"* buys a zero ``PER_CALL`` figure, and it is why §3 can say
    little is lost by making ``FREE`` unreachable.

    **No arm here asserts anything about the accounted total**, which ADR-0236 §3's
    first clause puts beyond a declared figure's reach.
    """
    trail = FakeAuditTrail(currency=CODE, day_ceiling=Decimal("0"))
    subject = await built(
        channels=[answering(result())], trail=trail, cost_per_call=figure, cost_currency=CODE
    )
    call = await authorised_search(
        subject.trail, proposal=await request(subject, tool=subject.declaration)
    )

    outcome = await subject.searcher.search(call)

    assert (outcome.refusal is None) is admitted
    if not admitted:
        assert outcome.refusal is SearchRefusal.SPEND_REFUSED


# --------------------------------------------------------------------------- #
# §8 item 7: the builder refuses the same states the Settings do                #
# --------------------------------------------------------------------------- #

#: Every cost pair ADR-0236 §2 refuses, in the spelling a caller offers it. Shared by
#: the builder cases here and by :func:`checked_search_cost`'s own, so the two
#: statements of one rule are asserted over one list rather than over two that can
#: drift.
REFUSED_PAIRS: Final = [
    pytest.param(FIGURE, None, id="an-amount-with-no-currency"),
    pytest.param(None, CODE, id="a-currency-with-no-amount"),
    pytest.param(Decimal("-0.01"), CODE, id="a-negative-amount"),
    pytest.param(Decimal("Infinity"), CODE, id="a-positive-infinity"),
    pytest.param(Decimal("-Infinity"), CODE, id="a-negative-infinity"),
    pytest.param(Decimal("NaN"), CODE, id="a-nan"),
    pytest.param(Decimal("1E15"), CODE, id="at-the-magnitude-ceiling"),
    pytest.param(Decimal("1E16"), CODE, id="above-the-magnitude-ceiling"),
    pytest.param(Decimal("0.0000000001"), CODE, id="a-tenth-fractional-digit"),
    pytest.param(FIGURE, "usd", id="a-lowercase-code"),
    pytest.param(FIGURE, "USDX", id="a-four-letter-code"),
    pytest.param(FIGURE, "US", id="a-two-letter-code"),
    pytest.param(FIGURE, "US1", id="a-code-carrying-a-digit"),
    pytest.param(FIGURE, "", id="an-empty-code"),
]


@pytest.mark.parametrize(("amount", "code"), REFUSED_PAIRS)
async def test_the_builder_refuses_every_state_settings_refuses(
    amount: Decimal | None, code: str | None
) -> None:
    """§8 item 7, "driven directly, which is what makes the two statements one rule".

    ADR-0236 §2's last clause puts the domain at ``Settings`` **and** at the one place
    a searcher can be built without going through it, and says the two are "of one
    rule". Asserted over the same list ``tests/core/test_config.py`` drives at the
    load side, so a domain that drifted at one site fails at the other.
    """
    with pytest.raises(ValueError, match=r"cost_per_call|cost_currency"):
        await built(cost_per_call=amount, cost_currency=code)


@pytest.mark.parametrize(("amount", "code"), REFUSED_PAIRS)
def test_the_cost_helper_refuses_the_same_states_the_builder_does(
    amount: Decimal | None, code: str | None
) -> None:
    """The same list at the function the builder delegates to, driven synchronously.

    Worth its own parametrisation rather than folded into the builder's: the builder
    also parses an origin and constructs a transport, so a case that reached it could
    fail for a reason that is not the cost — and this one cannot.
    """
    with pytest.raises(ValueError, match=r"cost_per_call|cost_currency"):
        checked_search_cost(amount, code)


@pytest.mark.parametrize(
    "amount",
    [Decimal("0"), Decimal("1.0000000000"), Decimal("999999999999999.999999999")],
    ids=["zero", "a-trailing-zero-representation", "just-under-the-ceiling"],
)
def test_the_cost_helper_admits_what_adr_0194_s1_calls_countable(amount: Decimal) -> None:
    """§8 item 5's admitted case, at the builder's own statement of the domain.

    ``Decimal("1.0000000000")`` is **admitted** "because ADR-0194 §1's predicate is a
    test on the value and not on the representation", and this fails an
    implementation that read ``as_tuple().exponent`` without stripping the trailing
    zeros first. Zero is admitted because ADR-0236 §2's floor is ``>= 0``.
    """
    cost = checked_search_cost(amount, CODE)

    assert cost is not None
    assert cost.basis is CostBasis.PER_CALL
    assert cost.amount == amount


def test_the_cost_helper_answers_absence_with_no_cost_at_all() -> None:
    """The unconfigured pair yields ``None``, so the caller keeps the template.

    ADR-0236 §1's constant clause depends on this: where the pair is unset the
    builder registers :data:`WEB_SEARCH` itself rather than an equal copy of it, so
    a reader comparing against the constant is comparing against the object that was
    registered.
    """
    assert checked_search_cost(None, None) is None


# --------------------------------------------------------------------------- #
# §8 item 9: the module constants do not move                                   #
# --------------------------------------------------------------------------- #


async def test_a_configured_registration_leaves_the_module_constant_alone() -> None:
    """§8 item 9, and ADR-0016 §1's ``frozen=True`` argument behind it.

    "``WEB_SEARCH.cost`` … is ``UNKNOWN`` after a registration built with a figure —
    the §1 clause that keeps a recorded decision's definition from being edited under
    it." A shared constant whose ``cost`` was rewritten at start-up would be exactly
    the back door that clause names: a permission decision is recorded against the
    definition that was in force.

    ``FAKE_WEB_SEARCH``'s half of item 9 is asserted in
    ``tests/tools/test_fake_web_searcher.py``, beside the fake it belongs to.
    """
    subject = await built(cost_per_call=FIGURE, cost_currency=CODE)

    assert subject.declaration.cost.basis is CostBasis.PER_CALL
    assert WEB_SEARCH.cost.basis is CostBasis.UNKNOWN
    assert WEB_SEARCH.cost.amount is None
    assert WEB_SEARCH.cost.currency is None
    assert subject.declaration is not WEB_SEARCH, "a second value, built per registration"
    assert subject.declaration.model_copy(update={"cost": WEB_SEARCH.cost}) == WEB_SEARCH, (
        "and equal to it in every other field"
    )


# --------------------------------------------------------------------------- #
# §8 item 10: the audit is unchanged                                            #
# --------------------------------------------------------------------------- #


def test_the_search_disposition_enumeration_is_still_the_fifteen() -> None:
    """§8 item 10's mechanical half, which is ADR-0236 §5's "no sixteenth member".

    "``SearchDisposition`` has fifteen members. This is §5 asserted, and it fails a
    lane that reached for a sixteenth on the way past." Named one for one rather than
    counted, so a member swapped for another fails as loudly as a member added.
    """
    assert [member.name for member in SearchDisposition] == [
        "NOT_CONFIGURED",
        "NO_BUDGET",
        "COMPOSER_DECLINED",
        "COMPOSER_UNAVAILABLE",
        "COMPOSER_MALFORMED",
        "COMPOSER_TOO_LONG",
        "BINDING_FAILED",
        "RULING_CONFIRM",
        "RULING_DENY",
        "RULING_UNAVAILABLE",
        "SPEND_REFUSED",
        "TRANSPORT_FAILED",
        "PROVIDER_REFUSED",
        "RESPONSE_TOO_LARGE",
        "UNATTESTED",
    ]
    assert not [member for member in SearchDisposition if "COST" in member.name]


async def test_both_cost_configurations_reach_the_same_confirm_and_so_the_same_record() -> None:
    """§8 item 10's behavioural half, at the ruling the disposition is taken from.

    "A ``CONFIRM`` with the pair unset and one with it set but no covering grant are
    both recorded ``RULING_CONFIRM``." What decides that is the *ruling*: the
    servicer maps a ``CONFIRM`` onto ``SearchDisposition.RULING_CONFIRM`` whatever
    grounds produced it, and that mapping is unchanged by this lane and already
    pinned in ``tests/orchestration/test_loop_search.py``. So what is asserted here
    is the fact the mapping reads — that both configurations produce a ``CONFIRM``,
    and that the two differ only in the grounds the reason renders.

    **The grounds are told apart from the deployment's own configuration and never
    from a per-turn record** (ADR-0236 §5): with the pair unset the cost floor fires
    on every search of that deployment, and with it set on none.
    """
    unconfigured = await built()
    configured = await built(cost_per_call=FIGURE, cost_currency=CODE)
    empty = FakeRecipientGrants([], now=_at)

    absent = await _ruled(unconfigured, grants=empty)
    present = await _ruled(configured, grants=FakeRecipientGrants([], now=_at))

    assert absent.outcome is PermissionOutcome.CONFIRM
    assert present.outcome is PermissionOutcome.CONFIRM
    assert "cost is undeclared" in absent.reason, "the ground the unset pair adds"
    assert "cost is undeclared" not in present.reason, "and does not add once it is set"
    assert empty.call_count == 0, "the unset pair reaches no seam at all"


# --------------------------------------------------------------------------- #
# §8 item 13: a configured deny threshold denies, and still consults no grant    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("amount", "code"),
    [(FIGURE, CODE), (None, None)],
    ids=["figure-configured", "figure-unset"],
)
async def test_a_deny_threshold_denies_the_search_in_either_cost_configuration(
    amount: Decimal | None, code: str | None
) -> None:
    """§8 item 13, which is ADR-0236 §4's second clause asserted.

    "With ``deny_at_risk=LOW`` and a covering grant seeded, in both cost
    configurations: the ruling is ``DENY``, its reason names the risk ground, and the
    ``RecipientGrants`` fake fails the test if ``covering`` is called."

    "The ruling is conditional on the thresholds while the zero-lookup guarantee is
    not", and this fails a lane that read §4's "the ruling is ``CONFIRM``" as
    unconditional. A deployment that configured a ``DENY`` threshold reaching this
    declaration has refused the search on its own stated policy, which is ADR-0036
    §1's thresholds working.
    """
    subject = await built(cost_per_call=amount, cost_currency=code)
    grants = FakeRecipientGrants([await _granted(subject)], now=_at)
    grants.fail_covering(AssertionError("a DENY is not something a grant converts"))

    ruled = await _ruled(subject, grants=grants, deny_at_risk=RiskLevel.LOW)

    assert ruled.outcome is PermissionOutcome.DENY
    assert "risk is low" in ruled.reason, "the ground the user's own threshold names"
    assert ruled.authorised_by is None
    assert grants.call_count == 0


# --------------------------------------------------------------------------- #
# §8 item 14: a mismatched currency is refused at the gate, not at load          #
# --------------------------------------------------------------------------- #


async def test_a_figure_in_another_currency_rules_allow_and_is_refused_at_the_gate() -> None:
    """§8 item 14, which is ADR-0236 §3's stated residual and §6's consequence.

    "``web_search_cost_per_call = 0`` with ``EUR``, ``world_spend_currency = "USD"``,
    a ceiling set and no allowance: ``Settings`` loads, the policy rules ``ALLOW`` on
    a covering grant, and the ``SpendGate`` refuses." It fails an implementation that
    coupled the two currencies at load or silently converted between them.

    **The policy still sees a ``PER_CALL`` basis and ``_UNKNOWN_COST_FLOOR`` still
    does not fire**, because that floor reads ``cost.basis`` and nothing else (§6) —
    which is why the two halves of this case disagree, and why they are asserted
    together rather than in two files.

    That ``Settings`` loads is asserted in ``tests/core/test_config.py``, where the
    load-time refusals are; the gate half needs a store and lives here.
    """
    trail = FakeAuditTrail(currency="USD", day_ceiling=Decimal("10"))
    subject = await built(
        channels=[answering(result())],
        trail=trail,
        cost_per_call=Decimal("0"),
        cost_currency="EUR",
    )
    grants = FakeRecipientGrants([await _granted(subject)], now=_at)

    ruled = await _ruled(subject, grants=grants)
    call = await authorised_search(
        subject.trail, proposal=await request(subject, tool=subject.declaration)
    )
    outcome = await subject.searcher.search(call)

    assert ruled.outcome is PermissionOutcome.ALLOW, "the policy reads a PER_CALL basis"
    assert ruled.authorised_by == GRANT_ID
    assert outcome.refusal is SearchRefusal.SPEND_REFUSED, "and the gate refuses it"
    with pytest.raises(SpendUndeterminedError):
        await subject.trail.admit_invocation(estimate=subject.declaration.cost)
    assert subject.keyring.reads == [], "refused before any credential was read"


# --------------------------------------------------------------------------- #
# §8 item 15: what a completed search does to the period                        #
# --------------------------------------------------------------------------- #


async def _searched(subject: Built, *, decision_id: str) -> Any:
    """Drive one whole search through ``subject``, from the request to the outcome.

    Args:
        subject: The configured integration.
        decision_id: The id the authorising decision is recorded under; distinct per
            call, because ADR-0192 §1 has the ledger require the decision it is
            passed to equal the one the store holds under that id.

    Returns:
        The outcome.
    """
    call = await authorised_search(
        subject.trail,
        proposal=await request(subject, tool=subject.declaration),
        decision_id=decision_id,
    )
    return await subject.searcher.search(call)


def _completions(rows: Any) -> list[ToolCost | None]:
    """The declared cost each completion row carries, in order."""
    return [row.invocation.incurred_cost for row in rows if row.invocation.completes is not None]


async def test_a_completed_search_reports_unknown_and_the_period_goes_indeterminate() -> None:
    """§8 item 15's first arm, and the Consequences bullet it pins.

    "The first search is admitted on its declared estimate and runs to completion; the
    completion row's ``incurred_cost`` is asserted to carry an ``UNKNOWN`` basis and
    **not** the declared figure; and a second search in that period is refused at the
    gate with ``SpendUndeterminedError``."

    It "fails an implementation that reached for ``ToolResult.incurred_cost`` and put
    the declared figure there — which ADR-0192 §5 forbids in terms: *'No lane copies
    ``ToolDefinition.cost`` into it, or derives it from the declaration by any other
    route.'*"

    The class is asserted at the gate itself, because
    :meth:`WebSearchEgress.search` converts both spend classes into the one
    ``SearchRefusal.SPEND_REFUSED`` member ADR-0231 §17 gives it — so the outcome
    carries the behaviour and the gate carries the class.
    """
    trail = FakeAuditTrail(currency=CODE, day_ceiling=Decimal("1"))
    subject = await built(
        channels=[answering(result())], trail=trail, cost_per_call=FIGURE, cost_currency=CODE
    )

    first = await _searched(subject, decision_id="d-search-1")
    reported = _completions(await subject.trail.export_invocations())
    second = await _searched(subject, decision_id="d-search-2")

    assert first.refusal is None, "the declared figure fits under the ceiling"
    assert [cost.basis for cost in reported if cost is not None] == [CostBasis.UNKNOWN]
    assert all(cost is None or cost.amount is None for cost in reported), (
        "ADR-0192 §5: the declared figure is not copied onto the completion"
    )
    assert second.refusal is SearchRefusal.SPEND_REFUSED
    with pytest.raises(SpendUndeterminedError):
        await subject.trail.admit_invocation(estimate=subject.declaration.cost)


async def test_an_allowance_makes_the_completed_row_countable_and_the_next_search_admitted() -> (
    None
):
    """§8 item 15's companion arm, with the ceiling it stipulates.

    "A companion arm sets the allowance **and a ceiling that covers the allowance the
    completed row now contributes plus the second call's own declared estimate**, and
    asserts the second search is admitted." The ceiling is stated because "the
    allowance does not make a period unbounded — it makes it **countable**, and a
    countable total is then compared against the ceiling like any other".
    """
    trail = FakeAuditTrail(currency=CODE, day_ceiling=Decimal("1"), allowance=Decimal("0.01"))
    subject = await built(
        channels=[answering(result()), answering(result())],
        trail=trail,
        cost_per_call=FIGURE,
        cost_currency=CODE,
    )

    first = await _searched(subject, decision_id="d-search-1")
    second = await _searched(subject, decision_id="d-search-2")

    assert first.refusal is None
    assert second.refusal is None, "the allowance made the completed row countable"
    assert len(_completions(await subject.trail.export_invocations())) == 2


async def test_an_allowance_under_a_ceiling_that_cannot_cover_it_crosses_rather_than_puzzles() -> (
    None
):
    """§8 item 15's third arm: ``SpendCeilingError`` rather than ``SpendUndeterminedError``.

    "A third arm holds the allowance and shrinks that ceiling below the sum, and
    asserts ``SpendCeilingError`` rather than ``SpendUndeterminedError``. Together
    they make the pair a statement about the allowance rather than about the search."

    The distinction is the whole of what this arm buys: with the allowance set the
    period is **countable**, so what refuses the second call is the ceiling doing the
    job it was set for and not an indeterminacy — and an implementation that ignored
    the allowance would raise the other class here while passing the arm above.
    """
    ceiling = Decimal("0.012")
    trail = FakeAuditTrail(currency=CODE, day_ceiling=ceiling, allowance=Decimal("0.01"))
    subject = await built(
        channels=[answering(result())], trail=trail, cost_per_call=FIGURE, cost_currency=CODE
    )

    first = await _searched(subject, decision_id="d-search-1")
    second = await _searched(subject, decision_id="d-search-2")

    assert first.refusal is None, "0.005 against a ceiling of 0.012, at a zero accounted total"
    assert second.refusal is SearchRefusal.SPEND_REFUSED
    with pytest.raises(SpendCeilingError):
        await subject.trail.admit_invocation(estimate=subject.declaration.cost)


async def test_the_origin_the_grant_covers_is_the_one_the_registration_pins() -> None:
    """A guard on this module's own arrangement, not one of §8's items.

    Every route-(b) case here derives its grant from the binding the production seam
    produced, so a grant that covered some *other* origin would make every ``ALLOW``
    above vacuous. Asserted once, here, rather than in each case: the canonical set
    the binder derives holds exactly the configured origin, at its default port.
    """
    subject = await built(cost_per_call=FIGURE, cost_currency=CODE)

    derived = await bound(subject, tool=subject.declaration)

    assert [member.canonical for member in derived.binding.canonical_destination_set] == [
        f"{ORIGIN}:443"
    ]
