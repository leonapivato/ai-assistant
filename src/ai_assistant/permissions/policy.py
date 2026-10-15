"""A rule-table :class:`~ai_assistant.core.protocols.ActionPolicy` (ADR-0036 §1).

The default gate in front of every side-effecting tool call (ADR-0004 §7). It is
a **pure function of its argument**: no clock, no id minting, no store — ADR-0021
§3 puts all three in the caller so ``decide`` stays checkable against the
monotonicity obligations its conformance suite asserts.

The rules are a table of independent clauses, each a monotone step function of
one declared field, combined by taking the **most restrictive** result. That is
the shape ADR-0036 §1 chose, and it is load-bearing rather than tidy: the
maximum of monotone functions is monotone, so no threshold a user configures can
produce a policy that violates ADR-0021 §5's central obligation.

**It holds no grant seam and awaits nothing.** ADR-0193 §7 once let a policy be
constructed with a ``RecipientGrants`` and await one durable read per ruling;
recipient grants retired (ADR-0321 §7:1), and with them that seam and the
supersession of ADR-0021 §3's purity sentences it carried, so every ruling is the
pure function those sentences describe.

**A ``ConfiguredSearchDestination`` moves neither sentence** (ADR-0247 §2). It is
two recorded values compared against the request's own binding — no store, no
seam, no clock and no await — so a policy holding one is exactly as pure as a
policy holding none, and its monotonicity is checkable without standing anything
up.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai_assistant.core.types import (
    CostBasis,
    CoverageUnrecordedBinding,
    OriginUnrecordedBinding,
    PermissionOutcome,
    PermissionRuling,
    Reversibility,
    RiskLevel,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.types import (
        ActionRequest,
        CanonicalDestination,
        EgressBinding,
        PermissionDecision,
        ToolDefinition,
    )

#: Reported when ``resolve`` is handed a decision the user was never shown.
_NOT_A_CONFIRMATION = "the decision resolved was not a CONFIRM, so it authorises nothing"

#: ADR-0184 §7's floor, worded as a statement about the **record** rather than about
#: the call: what is missing is the fact the trail never wrote down, and no reading
#: of the user's answer supplies it.
_ORIGIN_UNRECORDED = (
    "the user approved, but this decision records an egress call whose origin was never "
    "recorded, and no answer can establish it"
)

#: ADR-0184 §7's floor extended by cause (ADR-0233 §14), worded the same way and for
#: the same reason: a statement about the **record**, naming the fact the trail never
#: wrote down rather than anything about what the call would carry.
_COVERAGE_UNRECORDED = (
    "the user approved, but this decision records an egress call whose coverage was "
    "never recorded, and no answer can establish it"
)


@dataclass(frozen=True, slots=True)
class _Rule:
    """One clause of the rule table: a condition, an outcome, and a reason.

    ``applies`` must be **monotone** in the field it reads — once it fires for a
    declaration it must keep firing as that field rises — because the policy
    combines clauses by taking the maximum, and the maximum of monotone
    functions is monotone. Every rule below is a threshold comparison or a
    non-emptiness test, both of which have that property by construction.
    """

    outcome: PermissionOutcome
    applies: Callable[[ToolDefinition], bool]
    because: Callable[[ToolDefinition], str]


def _risk_rule(at: RiskLevel, outcome: PermissionOutcome) -> _Rule:
    """A clause firing at or above ``at`` on the risk scale."""
    return _Rule(
        outcome=outcome,
        applies=lambda tool: tool.risk_level >= at,
        because=lambda tool: f"its risk is {tool.risk_level}",
    )


def _reversibility_rule(at: Reversibility, outcome: PermissionOutcome) -> _Rule:
    """A clause firing at or above ``at`` on the reversibility scale."""
    return _Rule(
        outcome=outcome,
        applies=lambda tool: tool.reversibility >= at,
        because=lambda tool: f"its effect is {tool.reversibility}",
    )


#: Off-device disclosure is never auto-granted (ADR-0021 §5). Over *any*
#: non-empty ``discloses`` rather than a list of tiers: ``OPERATIONAL`` is the
#: tier a tool assigns to a disclosure it considers unremarkable, so exempting
#: it would let the declaration decide whether it gets gated.
_DISCLOSURE_FLOOR = _Rule(
    outcome=PermissionOutcome.CONFIRM,
    applies=lambda tool: bool(tool.discloses),
    because=lambda tool: (
        f"it may disclose {', '.join(tier.value for tier in tool.discloses)} data off-device"
    ),
)

#: An ``UNKNOWN`` cost is never auto-granted — ADR-0016 §4's "the author does
#: not know, so policy must fail closed", acquiring an enforcer.
_UNKNOWN_COST_FLOOR = _Rule(
    outcome=PermissionOutcome.CONFIRM,
    applies=lambda tool: tool.cost.basis is CostBasis.UNKNOWN,
    because=lambda _tool: "its cost is undeclared",
)

#: The two ADR-0021 §5 floors, in the order their reasons are rendered. They
#: are module-level constants and no constructor argument reaches them: a
#: threshold is the user's, a floor is the contract's (ADR-0036 §1).
#:
#: **A configured provider does not reach them either.** What route (c) discharges
#: is the *ground* :data:`_DISCLOSURE_FLOOR` stands on, not the constant: ADR-0021
#: §5's floor forbids an ``ALLOW`` with ``authorised_by`` **unset** for a
#: non-empty ``discloses``, and a route-(c) ``ALLOW`` sets it (ADR-0247 §2).
#: :data:`_UNKNOWN_COST_FLOOR` is untouched by that and keeps firing, which is why
#: the two are named separately below rather than tested as a pair.
_FLOORS = (_DISCLOSURE_FLOOR, _UNKNOWN_COST_FLOOR)

#: The ground a route-(c) ``ALLOW`` is rendered with (ADR-0247 §2's last normative
#: clause). It names the **basis** — that this deployment's owner configured the
#: search provider this call is going to — and quotes **no origin, no host, no
#: connection reference, no credential and no ``Settings`` field**. The reference is
#: recorded on the decision for an auditor and is rendered to nobody (ADR-0148 §6,
#: §8's fourth clause), so a reason repeating it would put in front of the user the
#: one value that clause keeps from them.
_CONFIGURED_SEARCH_PROVIDER = (
    "this deployment's owner configured this search provider, so searching it is "
    "the destination they chose and the recipient they granted"
)

#: The ground a route-(c) ``ALLOW`` **at the configured forecast provider** is
#: rendered with (ADR-0260 §6). Its sibling above, one kind along, and stated
#: separately rather than generalised into one sentence for both: the ruling's
#: ``reason`` is what a surface renders and what the decision carries, so a single
#: sentence covering both kinds would change the text of every search ruling this
#: deployment already makes — and ADR-0260 §12 gives this lane "no live behaviour on
#: its own". It names the same **basis** — that this deployment's owner configured
#: the provider this read is going to, which §6 carries to this kind in ADR-0247
#: §1's own words: the destination is the one the owner chose, and the configured
#: provider is also the granted recipient — and quotes no origin, no host, no
#: connection reference, no coordinate, no credential and no ``Settings`` field.
_CONFIGURED_FORECAST_PROVIDER = (
    "this deployment's owner configured this forecast provider, so reading it is "
    "the destination they chose and the recipient they granted"
)

#: ADR-0181 §5's ground, worded at the strength the recorded predicate carries
#: (§2's second clause, §6's second and sixth): a statement about the **selection
#: this system made**, naming no source and no kind of source, and never a
#: detection, a score, a risk level or a claim that the call is malicious.
_PLANNED_OVER_EXTERNAL = (
    "the material selected into the model call that produced this request included "
    "a record resting on recorded external content"
)


def _planned_with_external_content(request: ActionRequest) -> bool:
    """ADR-0181 §5's antecedent, read off the request's own binding.

    **Not a** :class:`_Rule`, and the difference is the whole reason it is a
    function here. Every rule in the table is a monotone step function of one field
    of the *declaration*, which is what lets the table be combined by maximum and
    checked without knowing an implementation's thresholds; this reads a fact about
    the **request**, which no ``ToolDefinition`` carries and no declaration can
    claim (ADR-0181 §4's first clause). Folding it into ``_Rule`` would widen every
    clause's input for one clause's benefit and put a request-level fact where a
    reviewer reads only declaration-level ones.

    It is monotone all the same, in the only sense that matters here: it is a step
    function of one field, it is combined into the same maximum, and it can only
    make the outcome more restrictive — so the class docstring's guarantee that no
    setting of the knobs produces a non-conforming policy is untouched by it.

    Args:
        request: The action being ruled on.

    Returns:
        Whether its binding records that the call was planned over material
        including a record resting on recorded external content. ``False`` for a
        call carrying no binding at all, which is not an egress call.
    """
    binding = request.egress_binding
    return binding is not None and binding.planned_with_external_content


@dataclass(frozen=True, slots=True)
class ConfiguredSearchDestination:
    """The search destination this deployment is configured with (ADR-0247 §1, §2).

    The two values ``Settings.web_search_connection`` and
    ``Settings.web_search_origin`` amount to, as the argument §2 gives
    :class:`ThresholdActionPolicy` for this kind: the connection reference the
    search is registered against, and the canonical destination set that origin
    canonicalises to. **It is the search pair and only ever the search pair** —
    ADR-0260 §6 widens route (c) to a closed two-member set in which each kind is
    compared against its own configured pair, and the forecast kind's is
    :class:`ConfiguredForecastDestination`. **Not a store handle, a trail read, a
    grant seam or a conversation identity**, so ADR-0238 §5's clause forbidding a
    policy any of those is untouched and its trust boundary is unmoved.

    **Neither value is derived here.** The composition root builds both — the
    reference is the configured string, and the set comes from the *same*
    canonicaliser ``EgressBindingSeam`` derives a span's occurrence with — because
    a second derivation would be the second shape that must agree ADR-0150 is named
    after. This type holds what it was handed and compares it.

    **No ``Settings`` object reaches the policy**, which is why this is a pair of
    values rather than the settings themselves: a policy holding the settings could
    read any field of them, and the authority §1 states is exactly two.

    Attributes:
        reference: ``Settings.web_search_connection`` — the connection record the
            search is registered against (ADR-0149 §3). Compared against a
            binding's ``account.reference`` as a recorded value, never inferred,
            folded or matched by domain.
        destinations: The canonical destination set ``Settings.web_search_origin``
            canonicalises to. A ``frozenset`` because §1 compares *sets*: a
            binding's own set is deduplicated and totally ordered, so the two
            agree on membership or not at all, and nothing here depends on an
            order either side chose.
    """

    reference: str
    destinations: frozenset[CanonicalDestination]


@dataclass(frozen=True, slots=True)
class ConfiguredForecastDestination:
    """The forecast destination this deployment is configured with (ADR-0260 §6, §11).

    :class:`ConfiguredSearchDestination` one kind along, and **its own type rather
    than that one reused**. ADR-0260 §6 compares *"each kind against its own
    configured pair"* and takes **no** route at all for *"a forecast request bound
    to the search provider's account or origin, or the reverse"*; two types make the
    crosswise wiring a type error at the composition root — the one site that could
    make it — where one type shared by both pairs would leave it a runtime mismatch
    that only a test can catch. The shape is deliberately identical because §11
    gives the forecast settings ``web_search_*``'s *"own shape field for field"*.

    Everything :class:`ConfiguredSearchDestination` says about what this is **not**
    holds here word for word: not a store handle, not a trail read, not a grant
    seam, not a conversation identity and never a ``Settings`` object, so ADR-0238
    §5's clause forbidding a policy any of those is untouched at this kind too.

    Attributes:
        reference: ``Settings.forecast_connection`` — the connection record the
            forecast integration is registered against (ADR-0149 §4, ADR-0260 §6).
            Compared against a binding's ``account.reference`` as a recorded value,
            never inferred, folded or matched by domain.
        destinations: The canonical destination set ``Settings.forecast_origin``
            canonicalises to, a ``frozenset`` for :class:`ConfiguredSearchDestination`'s
            own reason. **Neither coordinate is here**: ADR-0260 §6's comparison is
            over the account and the origin, and a policy holding a place would be
            holding a value no clause of this corpus lets it rule on.
    """

    reference: str
    destinations: frozenset[CanonicalDestination]


#: Either kind's configured pair, where a step is stated over both alike. The union
#: rather than a shared base class, so that neither pair is ever a subtype of the
#: other and the crosswise wiring :class:`ConfiguredForecastDestination` describes
#: stays a type error at the one site that could commit it.
_ConfiguredPair = ConfiguredSearchDestination | ConfiguredForecastDestination


@dataclass(frozen=True, slots=True)
class _ConfiguredProviderMatch:
    """A request found to be *at its kind's configured provider* (ADR-0260 §6).

    The binding the comparison was taken over, and the ground the ``ALLOW`` route
    (c) reaches is rendered with — carried together because §6 widens route (c) to a
    **closed two-member set** and the kind that matched is what decides both which
    pair was compared and which sentence the user reads. A second derivation of the
    kind at the rendering site would be the second shape ADR-0150 is named after.
    """

    binding: EgressBinding
    """The request's own binding, where the three comparisons held of it."""

    ground: str
    """The reason a route-(c) ``ALLOW`` on this kind is rendered with."""


def _at_configured_provider(
    binding: EgressBinding | None,
    configured_search: ConfiguredSearchDestination | None,
    configured_forecast: ConfiguredForecastDestination | None,
) -> _ConfiguredProviderMatch | None:
    """The match where the request is *at its kind's configured provider*, else ``None``.

    ADR-0247 §2's one derived fact, **widened by ADR-0260 §6 to a closed two-member
    set** and to nothing else. Per kind it is three conjuncts and no more: the
    binding carries that kind's own carried fact — ``closed_loop`` for a
    ``WEB_SEARCH``, ``forecast_reach`` for a forecast read — its
    ``account.reference`` equals that kind's configured connection reference, and
    its canonical destination set equals that kind's configured one.

    **Each kind is compared against its own configured pair** (ADR-0260 §6): "a
    forecast request bound to the search provider's account or origin, or the
    reverse, takes no route at all". The pair is selected by the carried fact and
    never by which pair happens to match, so a deployment that configured both
    providers cannot have one kind's authority answer for the other's.

    **A binding carrying both facts is at no configured provider.** ADR-0260 §11
    writes ``forecast_reach`` *"exactly where the request's kind is a forecast
    read"* and leaves ``closed_loop`` meaning *"this deployment's own search and
    nothing else"*, so the two are one kind each and a binding asserting both
    asserts a kind route (c)'s closed set does not contain. Selecting either pair
    for it would authorise a forecast read from the search configuration or the
    reverse, which is the one thing §6 states route (c) must not do — so the
    ambiguity fails closed and is the whole of what this branch decides.

    **The carried fact alone is never the condition of any relaxation** (ADR-0247
    §2). Both facts are written before the binding exists, so each asserts *which
    act this is* and neither *"can assert which account and origin the binding
    carries"*; a lane reading one alone reopens the hole ADR-0247 §3's limbs are
    stated to close, at whichever kind it read it on.

    **Both comparisons are over recorded values** (ADR-0247 §1, ADR-0260 §6):
    ``DurableIdentifier`` equality and ``CanonicalDestination`` equality, every
    field and never across protocols. Neither side is inferred, folded, matched by
    domain or re-canonicalised here — the canonical forms were computed once, by one
    canonicaliser, before either reached this function.

    **A policy constructed with no configured destination for a kind takes the fact
    as false for every request of it** (ADR-0247 §2), which is the fail-closed
    direction and the same shape ADR-0021 §3 gives a policy with no authorisation
    source. The two pairs are independent: a deployment configured for search alone
    reaches route (c) on a search and on no forecast read, and the reverse.

    Args:
        binding: The request's own binding, or ``None`` where it carries none — a
            request that is not an egress call, and so at no provider.
        configured_search: The search pair this deployment holds, or ``None``.
        configured_forecast: The forecast pair this deployment holds, or ``None``.

    Returns:
        The match where the request is at its kind's configured provider — carrying
        the binding itself, so a caller that then needs its ``account.reference``
        reads it off the value the comparison was taken over rather than off a second
        lookup, and carrying that kind's ground; ``None`` otherwise.
    """
    if binding is None:
        return None
    configured: _ConfiguredPair | None
    if binding.closed_loop and binding.forecast_reach:
        return None
    if binding.closed_loop:
        configured, ground = configured_search, _CONFIGURED_SEARCH_PROVIDER
    elif binding.forecast_reach:
        configured, ground = configured_forecast, _CONFIGURED_FORECAST_PROVIDER
    else:
        return None
    if configured is None:
        return None
    # The two comparisons in one statement rather than two, which changes nothing
    # about either: both are still taken over recorded values and `or` still stops
    # at the first that fails, so neither is ever inferred from the other.
    if (
        binding.account.reference != configured.reference
        or frozenset(binding.canonical_destination_set) != configured.destinations
    ):
        return None
    return _ConfiguredProviderMatch(binding=binding, ground=ground)


def _only_the_disclosure_floor(fired: list[_Rule], *, outcome: PermissionOutcome) -> bool:
    """Whether route (c) may answer a request already at its kind's configured provider.

    Two conditions, each a path on which no ``ALLOW`` is reachable however the
    deployment is configured:

    * the outcome is ``CONFIRM``. A ``DENY`` is not something a configuration
      converts, and an ``ALLOW`` needs none;
    * and the **only** clause of the table that fired is :data:`_DISCLOSURE_FLOOR`.
      That is the ground route (c) rests on; every other firing clause is an
      independent floor or a threshold the user configured, so a request that
      tripped one of those is settled by its own facts. An ``UNKNOWN`` cost still
      draws ``CONFIRM`` at either configured provider, and so does a ``risk_level``
      or a ``reversibility`` at this policy's own threshold (ADR-0247 §2, and
      ADR-0260 §11 leaving the unknown-cost floor untouched at this kind).

    **Neither the origin floor nor the covered-content bar is read here, and that
    is the exception and not an omission** (ADR-0247 §3 as ADR-0260 §6 restates it,
    superseding ADR-0238 §6's first clause, and ADR-0233 §9 as ADR-0238 §7 and
    ADR-0247 §3 open it): at the configured provider both limbs are satisfied by one
    fact. The caller reaches this only with that fact in hand, so for every other
    request — an email, a fetch, a search or a forecast read bound anywhere else —
    both floors keep the ``CONFIRM`` they reach (ADR-0238 §5's last clause, ADR-0247
    §3's last, ADR-0260 §6's last). **This policy re-derives none of the facts
    behind that** (ADR-0238 §5): it compares two configured values against what
    ``orchestration`` wrote onto the binding.

    Args:
        fired: Every clause of the table that applies to the request's declaration.
        outcome: The most restrictive outcome the request's grounds reach.

    Returns:
        Whether route (c) answers the request.
    """
    return outcome is PermissionOutcome.CONFIRM and fired == [_DISCLOSURE_FLOOR]


class ThresholdActionPolicy:
    """An ``ActionPolicy`` combining user thresholds with the contract's floors.

    Structurally implements :class:`~ai_assistant.core.protocols.ActionPolicy`. It
    holds no goal authorizations and no goal quotes: ADR-0309 §5 retires them with
    the old path, and with them ADR-0254 §6's route (d), ADR-0267 §5's quote read and
    ADR-0270 §1's ``coverage_met`` face. The authority milestone redoes them.

    The rule table, combined by taking the **most restrictive** result:

    * a non-empty ``discloses`` — ``CONFIRM``. Not configurable.
    * an ``UNKNOWN`` cost — ``CONFIRM``. Not configurable.
    * ``risk_level`` at or above ``confirm_at_risk`` — ``CONFIRM``.
    * ``reversibility`` at or above ``confirm_at_reversibility`` — ``CONFIRM``.
    * ``risk_level`` at or above ``deny_at_risk`` — ``DENY``.
    * ``reversibility`` at or above ``deny_at_reversibility`` — ``DENY``.
    * an ``egress_binding`` carrying ``planned_with_external_content`` —
      ``CONFIRM``. Not configurable, and the one clause reading the *request*
      rather than the declaration (ADR-0181 §5). **The clause still fires on a
      request at its kind's configured provider** (ADR-0247 §3): what that moves is
      whether route (c) is *reachable* for such a request, not whether this row
      applies.
    * nothing applies — ``ALLOW``.

    **The thresholds cannot configure it out of conformance.** Each clause is a
    monotone step function of one field and the combination is a maximum, so every
    setting of the four knobs yields a monotone policy; the floors are module
    constants no argument reaches. A policy configurable into violating its own
    conformance suite would be a trap for the user it is meant to protect, and
    ADR-0036 §1 records the shape as the reason it is not one.

    **The egress clause is a floor and reaches ADR-0181 §5's ceiling rather than
    stating a preference.** A call carrying ``planned_with_external_content`` keeps
    its confirmation wherever it is not at its kind's configured provider, so this
    clause is what keeps such a call's confirmation in place. It still refuses
    nothing that would otherwise run: the call is put to the user, with the fact in
    front of them (ADR-0181 §6).

    **A ``ConfiguredSearchDestination`` or a ``ConfiguredForecastDestination``
    changes exactly one row of the table above, by a route that consults no seam at
    all** (ADR-0247 §2, §3; ADR-0260 §6). Where the request is a ``WEB_SEARCH`` at
    the search destination this deployment is configured with, **or a forecast read
    at the forecast destination it is configured with** — its binding carrying that
    kind's own fact, ``closed_loop`` or ``forecast_reach``, and its account's
    connection reference and canonical destination set equal to **that kind's**
    configured ones — ADR-0148 §3's route (c) answers it: an ``ALLOW`` naming that
    reference and fingerprinting nothing. That is ADR-0021 §5's disclosure floor
    **satisfied**, not relaxed, because the floor bars an ``ALLOW`` with
    ``authorised_by`` unset and a route-(c) ``ALLOW`` sets it. ADR-0260 §6 widens
    that route's population to a **closed two-member set** and adds no fourth
    route, and a request of one kind bound to the other kind's configured pair
    takes no route at all. The two limbs ADR-0238 opened over ``closed_loop`` are
    restated over that whole fact rather than over either carried fact alone, which
    is what keeps both floors on a binding whose account or origin is not its kind's
    configured pair: such a request reaches no ``ALLOW``. Every other row is
    untouched: an ``UNKNOWN`` cost still confirms, both thresholds still fire, a
    ``DENY`` still stands, and a policy constructed with no configured destination
    for a kind behaves, on that kind, exactly as it did.

    **There is no route (b).** ADR-0193's standing recipient grant retired
    (ADR-0321 §7:1), so this policy holds no grant seam, sets no
    ``authorised_subject`` (§7:7), and answers every other ``CONFIRM`` by asking.

    The defaults are deliberately unremarkable and are **not** a decision the
    contract makes for the user (ADR-0021 §5): confirm at or above ``MEDIUM``
    risk, confirm on an ``IRREVERSIBLE`` effect, deny nothing outright. A
    deployment wanting something stricter passes it in.
    """

    def __init__(  # noqa: PLR0913 — four thresholds the user sets, and the configured values the composition root supplies; each is one thing a deployment decides on its own
        self,
        *,
        confirm_at_risk: RiskLevel | None = RiskLevel.MEDIUM,
        confirm_at_reversibility: Reversibility | None = Reversibility.IRREVERSIBLE,
        deny_at_risk: RiskLevel | None = None,
        deny_at_reversibility: Reversibility | None = None,
        configured_search: ConfiguredSearchDestination | None = None,
        configured_forecast: ConfiguredForecastDestination | None = None,
    ) -> None:
        """Create the policy.

        Args:
            confirm_at_risk: Risk level at or above which an action needs the
                user's confirmation; ``None`` never confirms on risk alone.
            confirm_at_reversibility: Reversibility at or above which an action
                needs confirmation; ``None`` never confirms on reversibility
                alone.
            deny_at_risk: Risk level at or above which an action is refused
                outright; ``None`` never denies on risk. ``RiskLevel.LOW``
                refuses every action.
            deny_at_reversibility: Reversibility at or above which an action is
                refused outright; ``None`` never denies on reversibility.
            configured_search: The search destination this deployment is
                configured with (ADR-0247 §1, §2) — the connection reference and
                the canonical destination set, and never a ``Settings`` object,
                a store handle, a trail read, a grant seam or a conversation
                identity. ``None`` — the default — makes the *at the configured
                provider* fact false for every ``WEB_SEARCH``, which is the
                fail-closed direction: such a policy reaches no route-(c) ``ALLOW``
                on that kind, and a request that would have taken one draws the
                ``CONFIRM`` it draws at ``origin/main``.
            configured_forecast: The forecast destination this deployment is
                configured with (ADR-0260 §6, §11) — the connection reference and
                the canonical destination set, in ``configured_search``'s own shape
                and subject to every word of its description. **It is a second
                argument rather than a widening of the first** because §6 compares
                each kind against its own configured pair and gives a forecast read
                bound to the search provider's account or origin, or the reverse,
                **no** route at all. ``None`` — the default — makes the *at the
                configured provider* fact false for every forecast read, and a
                deployment configured for one kind and not the other reaches route
                (c) on the kind it configured and on no other.
        A ``deny`` threshold below its matching ``confirm`` threshold is
        accepted rather than rejected: the combination is still a maximum, so
        the result is a policy that denies where it would otherwise have asked —
        strictly safer, and refusing it would be this contract deciding how
        cautious its user is allowed to be.
        """
        self._configured_search = configured_search
        self._configured_forecast = configured_forecast
        rules = list(_FLOORS)
        if confirm_at_risk is not None:
            rules.append(_risk_rule(confirm_at_risk, PermissionOutcome.CONFIRM))
        if confirm_at_reversibility is not None:
            rules.append(_reversibility_rule(confirm_at_reversibility, PermissionOutcome.CONFIRM))
        if deny_at_risk is not None:
            rules.append(_risk_rule(deny_at_risk, PermissionOutcome.DENY))
        if deny_at_reversibility is not None:
            rules.append(_reversibility_rule(deny_at_reversibility, PermissionOutcome.DENY))
        self._rules: tuple[_Rule, ...] = tuple(rules)

    # The rule table stays private. Rendering a configured gate to the user is
    # a plausible want and is not on `ActionPolicy`, so a public accessor would
    # invite a consumer to depend on this class and on `_Rule` — the
    # implementation coupling golden rule 1 forbids. If it is ever needed it
    # goes through the Protocol, as a contract.

    def _fired(self, tool: ToolDefinition) -> list[_Rule]:
        """Every clause that fires for ``tool``, in table order.

        The **rules** rather than their outcomes, because ``decide`` has to ask a
        question about *which* clause fired and not merely how restrictive the
        answer was: route (c) is available only where :data:`_DISCLOSURE_FLOOR` is
        the whole of what stands in the way (ADR-0247 §2).
        """
        return [rule for rule in self._rules if rule.applies(tool)]

    def _grounds(self, tool: ToolDefinition) -> list[tuple[PermissionOutcome, str]]:
        """Every firing clause's outcome and reason, in table order."""
        return [(rule.outcome, rule.because(tool)) for rule in self._fired(tool)]

    def _outcome_for(self, tool: ToolDefinition) -> PermissionOutcome:
        """The most restrictive outcome this policy's rules reach for ``tool``."""
        grounds = self._grounds(tool)
        return max((outcome for outcome, _ in grounds), default=PermissionOutcome.ALLOW)

    async def decide(self, request: ActionRequest) -> PermissionRuling:
        """Rule on ``request`` by the table in the class docstring.

        Reads ``request.tool`` and — for ADR-0181 §5's clause and route (c) alone —
        ``request.egress_binding``. ``parameters`` is carried on the request for the
        invocation contract's future per-call gating (ADR-0021 §3) and no rule here
        consults it, so nothing derived from a payload reaches the ``reason`` a user
        is shown. Neither does the egress clause: its ground names the selection this
        system made and quotes nothing of the call.

        **It awaits nothing**, so the whole ruling is one observation of the
        request (ADR-0065): with no grant seam left (ADR-0321 §7:1) there is no
        suspension at which a caller could rewrite the request between two reads of
        it, and ``request.tool`` is read once and ruled on throughout.

        **It returns no ``ALLOW`` on a request whose binding carries
        ``planned_with_external_content``** (ADR-0181 §5's third clause), unless the
        request is at its kind's configured provider (ADR-0247 §3, ADR-0260 §6).
        ADR-0148 §3's route (a) is unavailable to this member by construction — it
        holds no ``AuditTrail`` and no resolution about the request exists yet — so
        the obligation is discharged by returning ``CONFIRM``. Nothing is acquired to
        look for a route (a): no trail read, no store handle, no *source*-grant seam,
        the last of which ADR-0097 §7 forbids outright. A request whose binding
        carries ``False``, or which carries none, is judged on the ordinary path.

        **Route (c), where this policy was given a configured destination for the
        request's kind** (ADR-0247 §2, §3; ADR-0260 §6). ADR-0148 §3's enumeration
        of what an ``ALLOW`` on an egress request may rest on gains a third route,
        and ADR-0260 §6 widens that route's population to a **closed two-member
        set** while adding no fourth route: the request is a ``WEB_SEARCH`` at the
        search destination this deployment's owner configured, **or a forecast read
        at the forecast destination they configured**, which is ADR-0247 §1's two
        recorded comparisons taken over the binding beside the carried fact
        ``orchestration`` wrote for that kind — ``closed_loop`` for a search,
        ``forecast_reach`` for a forecast read. **Each kind is compared against its
        own configured pair**, so a forecast read bound to the search provider's
        account or origin, or the reverse, takes no route at all. The ``ALLOW``
        names the binding's ``account.reference`` and fingerprints nothing, which is
        what tells it apart from route (a) on the row. **No confirmation is sought
        on either kind** (ADR-0260 §6's no-new-question clause).

        **A request carrying its kind's fact that is not at that kind's configured
        provider keeps every floor** (ADR-0247 §2, ADR-0260 §6). Because the two
        limbs read the derived fact rather than ``closed_loop`` or
        ``forecast_reach``, such a request planned over external content, or
        carrying covered content, reaches no ``ALLOW`` and the ruling is the
        ``CONFIRM`` ADR-0181 §5 and ADR-0233 §9 require.

        **Every other ground is independent and survives the configuration.** An
        ``UNKNOWN`` cost still draws ``CONFIRM``; a ``risk_level`` or a
        ``reversibility`` at this policy's own threshold still draws ``CONFIRM``; a
        threshold ``DENY`` still stands.

        **It does not discharge ADR-0148 §8's third clause's other limb** — no
        ``ALLOW`` where the request carries no canonical destination set, no
        payload description, or a description that is not the deterministic
        derivation §6 requires. This policy adds no check for that limb and takes
        none away.

        Returns:
            The ruling. A route-(c) ``ALLOW`` sets ``authorised_by`` to the
            binding's own ``account.reference`` and leaves ``authorised_subject``
            unset, on either kind (ADR-0247 §2, ADR-0260 §6). Every other ruling
            leaves both unset, which is ADR-0021 §3's requirement of a policy with no
            authorisation source; ADR-0247 §2 supersedes that requirement in the limb
            reaching a request at the configured provider, and in no other. **No
            ruling sets** ``authorised_subject`` (ADR-0321 §7:7).
        """
        tool = request.tool
        fired = self._fired(tool)
        grounds = [(rule.outcome, rule.because(tool)) for rule in fired]
        external = _planned_with_external_content(request)
        if external:
            grounds.append((PermissionOutcome.CONFIRM, _PLANNED_OVER_EXTERNAL))
        if not grounds:
            return PermissionRuling(
                outcome=PermissionOutcome.ALLOW,
                reason=(
                    f"no rule applies: {tool.risk_level} risk, {tool.reversibility}, "
                    f"discloses nothing off-device, at a {tool.cost.basis} cost"
                ),
            )
        outcome = max(ruled for ruled, _ in grounds)
        at_configured = _at_configured_provider(
            request.egress_binding, self._configured_search, self._configured_forecast
        )
        if at_configured is not None and _only_the_disclosure_floor(fired, outcome=outcome):
            # **Route (c)** (ADR-0247 §2, ADR-0260 §6). ``authorised_by`` is
            # **owed** rather than a matter of taste (ADR-0021 §5): the disclosure
            # floor forbids an ``ALLOW`` with the field unset for a non-empty
            # ``discloses``. The pointer is not a string this policy invented — it
            # is the value carried on the binding the seam derived, and the trail's
            # own check compares it against exactly that. ``authorised_subject``
            # stays unset, and its absence is what the trail reads the route by.
            return PermissionRuling(
                outcome=PermissionOutcome.ALLOW,
                reason=at_configured.ground,
                authorised_by=at_configured.binding.account.reference,
            )
        reasons = [reason for ruled, reason in grounds if ruled is outcome]
        return PermissionRuling(outcome=outcome, reason="; ".join(reasons))

    async def resolve(self, confirmed: PermissionDecision, *, approved: bool) -> PermissionRuling:
        """Turn the user's answer to ``confirmed`` into the ruling that resolves it.

        A refusal is honoured unconditionally, and a ``confirmed`` that was never
        a ``CONFIRM`` cannot mint an authorisation — both ADR-0021 §3
        obligations rather than choices made here.

        **An approval is re-checked against the rules as they now stand.** The
        recorded decision embeds the whole ``ToolDefinition`` it was made about
        (ADR-0021 §1), and every clause reads only that, so the policy can ask
        what it would rule today. If the answer is now ``DENY`` the approval does
        not resurrect the action: ADR-0021 §3 permits refusing "one whose request
        would now be ``DENY``", and consent to an action the policy has since
        refused outright is consent the user gave under the old rules.

        The complementary staleness check — refusing a confirmation answered
        long after it was asked — is deliberately absent, because it needs a
        clock the policy is contracted not to have (ADR-0036 §1).

        **ADR-0181 §5's fourth clause is discharged by the unconditional refusal
        above and adds no branch here.** Where ``confirmed.egress_binding`` carries
        ``planned_with_external_content``, an ``ALLOW`` requires ``approved`` to be
        true — and ``approved`` being anything but ``True`` already yields ``DENY``
        for every ``confirmed``, egress or not. The approving case gains nothing,
        because the user's answer about that call **is** ADR-0148 §3's route (a),
        the one route §5's second clause leaves open. Re-applying the ``decide``
        clause here would refuse every approval of exactly the calls §6 exists to
        put to the user, which is the failure §5's sixth clause names.

        **ADR-0184 §7's floor *does* add a branch, and ADR-0233 §14 extends it by
        cause to a second: these are the two cases where an approval is not
        enough.** Where ``confirmed.egress_binding`` records no origin — an
        :class:`~ai_assistant.core.types.OriginUnrecordedBinding`, which only a row
        written before ADR-0181 can carry — or records no coverage — a
        :class:`~ai_assistant.core.types.CoverageUnrecordedBinding`, which only a
        row written before ADR-0233 can carry — no ``ALLOW`` is returned whatever
        ``approved`` says. The missing fact cannot be established at all, and
        ADR-0181 §5's second clause leaves no route by which any authorisation
        covers such a call; the user's answer is route (a) for a call whose facts
        are known, and here one of them never was. **The second branch is written
        rather than inherited**, because a coverage-unrecorded row *has*
        ``planned_with_external_content`` and so falls straight past the first
        ``isinstance``. Both are a **floor rather than a route that exists**: the
        old path's park and resume that re-presented a recorded ``CONFIRM`` retired
        under ADR-0309 §5, so nothing in the tree reaches these branches — which is
        exactly ADR-0021 §5's
        "fail-closed twice over" and why they are written anyway. ``decide`` gains no
        counterpart: :attr:`ActionRequest.egress_binding` stays narrow, so both cases
        are unconstructable at that member.

        **Only ``True`` is consent.** ``approved`` is annotated ``bool`` and
        mypy runs strict over `src` and `tests`, so a caller passing anything
        else is a type error before it is a runtime one. The test is written as
        an identity against ``True`` anyway: it is identical for every value the
        annotation admits, and for one it does not — an adapter handing on an
        unparsed ``"false"``, which is truthy — it fails closed rather than
        converting a decline into an authorisation.

        Returns:
            The ruling that resolves ``confirmed``. A resolving ``ALLOW`` cites
            ``confirmed.id``, which is the pointer ``AuditTrail.record``
            verifies.
        """
        if approved is not True:
            return PermissionRuling(outcome=PermissionOutcome.DENY, reason="the user declined")
        if confirmed.ruling.outcome is not PermissionOutcome.CONFIRM:
            return PermissionRuling(outcome=PermissionOutcome.DENY, reason=_NOT_A_CONFIRMATION)
        if isinstance(confirmed.egress_binding, OriginUnrecordedBinding):
            return PermissionRuling(outcome=PermissionOutcome.DENY, reason=_ORIGIN_UNRECORDED)
        if isinstance(confirmed.egress_binding, CoverageUnrecordedBinding):
            return PermissionRuling(outcome=PermissionOutcome.DENY, reason=_COVERAGE_UNRECORDED)
        if self._outcome_for(confirmed.tool) is PermissionOutcome.DENY:
            return PermissionRuling(
                outcome=PermissionOutcome.DENY,
                reason=(
                    "the user approved, but this policy now refuses the declaration "
                    "outright, so the approval does not stand"
                ),
            )
        return PermissionRuling(
            outcome=PermissionOutcome.ALLOW,
            reason="the user approved the confirmation",
            authorised_by=confirmed.id,
        )


__all__ = ["ThresholdActionPolicy"]
