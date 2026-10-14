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

**Constructed with a ``RecipientGrants``, it awaits one durable read per ruling**
(ADR-0193 §7), and ADR-0021 §3's two purity sentences are partially superseded in
exactly that condition (ADR-0193 §12): a sourced policy's answer depends on the
store as well as on its argument, and its monotonicity suite stands up a fake
store. What does **not** move is the removal those sentences were drawn from —
``decide`` still mints no ``id`` and reads no clock, the clock lives in the store
— and monotonicity stays checkable, because ADR-0021 §5 compares requests "equal
in every other respect" and that now reads "with the grants in the store held
equal". Constructed with **no** source, both sentences bind as written and every
ruling is the pure function it always was.

**A ``ConfiguredSearchDestination`` moves neither sentence** (ADR-0247 §2). It is
two recorded values compared against the request's own binding — no store, no
seam, no clock and no await — so a policy holding one and no ``RecipientGrants``
is exactly as pure as a policy holding neither, and its monotonicity is checkable
without standing anything up.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from ai_assistant.core.errors import RecipientGrantError
from ai_assistant.core.types import (
    CostBasis,
    CoverageUnrecordedBinding,
    OriginUnrecordedBinding,
    PermissionOutcome,
    PermissionRuling,
    Reversibility,
    RiskLevel,
    SpanCoverage,
)
from ai_assistant.permissions._coverage import coverage_subject

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.protocols import RecipientGrants
    from ai_assistant.core.types import (
        ActionRequest,
        CanonicalDestination,
        EgressBinding,
        PermissionDecision,
        RecipientGrant,
        ToolDefinition,
    )
    from ai_assistant.permissions._coverage import CoverageSubject

_log = structlog.get_logger(__name__)

#: Reported when ``resolve`` is handed a decision the user was never shown.
_NOT_A_CONFIRMATION = "the decision resolved was not a CONFIRM, so it authorises nothing"

#: Reported when the request changed under a ruling that had already begun
#: (ADR-0065). An operator's fact and never the user's: nothing is added to the
#: reason the table reached, and the ruling is the ``CONFIRM`` it already held.
_REQUEST_CHANGED_MID_RULING = (
    "the request changed while a seam was out, so no standing grant is taken over it"
)

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
#: **A ``RecipientGrants`` does not reach them either**, and route (b) is not an
#: exception to that sentence (ADR-0193 §3). What a covering grant discharges is
#: the *ground* :data:`_DISCLOSURE_FLOOR` stands on, not the constant: ADR-0021
#: §5's floor forbids an ``ALLOW`` with ``authorised_by`` **unset** for a
#: non-empty ``discloses``, and a route-(b) ``ALLOW`` sets it. The floor is
#: therefore satisfied rather than relaxed (ADR-0193 §15), which is what ADR-0021
#: §5 already said would happen — "the relief valve is deliberately **not** a
#: policy quietly deciding on the user's behalf: it is the standing grant (§6)".
#: :data:`_UNKNOWN_COST_FLOOR` is untouched by any of that and keeps firing, which
#: is why the two are named separately below rather than tested as a pair.
_FLOORS = (_DISCLOSURE_FLOOR, _UNKNOWN_COST_FLOOR)

#: The ground a route-(b) ``ALLOW`` is rendered with. It names the **basis** —
#: that the user made these recipients standing on this declaration and this
#: account — and quotes no address, no payload and no grant id: ADR-0193 §11 lets
#: a surface say that a decision *names* a standing authorisation and no more, and
#: a reason repeating the recipients would be putting the confirmation's own
#: content into a row the user was deliberately not shown.
_STANDING_GRANT = (
    "the user has a standing grant covering every recipient of this call, for this "
    "declaration and this connected account"
)

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


@dataclass(frozen=True, slots=True)
class _ConfiguredAuthority:
    """Route (c)'s authority, **read before the ruling's first suspension** (ADR-0065).

    Both values are read off :class:`_ConfiguredProviderMatch` while :meth:`decide`
    is still inside its one pre-suspension observation of the request. A frozen
    pydantic model is rewritable through ``__dict__``, so reading
    ``binding.account.reference`` after the seam has had a turn would put into the
    ``ALLOW`` a reference this ruling never compared.
    """

    reference: str
    """The binding's ``account.reference``, which the ``ALLOW`` names."""

    ground: str
    """The sentence the ``ALLOW`` is rendered with."""


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
      closed-loop request** (ADR-0238 §5, §6): what ADR-0238 moves is whether route
      (b) is *reachable* for such a request, not whether this row applies, so the
      outcome is still a ``CONFIRM`` in the absence of a covering grant.
    * nothing applies — ``ALLOW``.

    **The thresholds cannot configure it out of conformance.** Each clause is a
    monotone step function of one field and the combination is a maximum, so every
    setting of the four knobs yields a monotone policy; the floors are module
    constants no argument reaches. A policy configurable into violating its own
    conformance suite would be a trap for the user it is meant to protect, and
    ADR-0036 §1 records the shape as the reason it is not one.

    **The egress clause is a floor and reaches ADR-0181 §5's ceiling rather than
    stating a preference, and it now has a live subject.** It was written when it
    could never decide an outcome — every egress call at the designated seam
    already reached ``_DISCLOSURE_FLOOR``, and ADR-0154 §4 closed standing
    authorisation for all of them — on the ground that "an actuator rule is free
    now and expensive later, and the lane that opens standing authorisation for
    egress will be doing it at the moment nobody wants to carve an exception back
    out". ADR-0193 is that lane, and the exception was not carved: a call carrying
    ``planned_with_external_content`` is the one case route (b) is unavailable on,
    whatever grants exist, so this clause is what keeps such a call's confirmation
    in place. It still refuses nothing that would otherwise run: the call is put to
    the user, with the fact in front of them (ADR-0181 §6).

    **A ``RecipientGrants`` changes exactly one row of the table above**
    (ADR-0193 §3, §7). Where it is the *only* clause standing between the request
    and an ``ALLOW``, ``_DISCLOSURE_FLOOR`` is discharged by a covering standing
    grant — which is ADR-0021 §5's floor **satisfied**, not relaxed, because that
    floor bars an ``ALLOW`` with ``authorised_by`` unset and a route-(b) ``ALLOW``
    sets it. Every other row is untouched: an ``UNKNOWN`` cost still confirms, both
    thresholds still fire, a ``DENY`` still stands, and the egress clause above
    still confirms. A policy constructed with no seam behaves exactly as it did.

    **A ``ConfiguredSearchDestination`` or a ``ConfiguredForecastDestination``
    changes the same one row, by a second route that consults no seam at all**
    (ADR-0247 §2, §3; ADR-0260 §6). Where the request is a ``WEB_SEARCH`` at the
    search destination this deployment is configured with, **or a forecast read at
    the forecast destination it is configured with** — its binding carrying that
    kind's own fact, ``closed_loop`` or ``forecast_reach``, and its account's
    connection reference and canonical destination set equal to **that kind's**
    configured ones — ADR-0148 §3's route (c) answers it: an ``ALLOW`` naming that
    reference, fingerprinting nothing, and taken **before** the grant seam is
    reached, so ``covering`` is called zero times. ADR-0260 §6 widens that route's
    population to a **closed two-member set** and adds no fourth route, and a
    request of one kind bound to the other kind's configured pair takes no route at
    all. The two limbs ADR-0238 opened over ``closed_loop`` are restated over that
    whole fact rather than over either carried fact alone, which is what keeps both
    floors on a binding whose account or origin is not its kind's configured pair:
    such a request reaches no ``ALLOW`` of either route, however many grants the
    store holds. Every other row is untouched here too, and a policy constructed
    with no configured destination for a kind behaves, on that kind, exactly as it
    did.

    The defaults are deliberately unremarkable and are **not** a decision the
    contract makes for the user (ADR-0021 §5): confirm at or above ``MEDIUM``
    risk, confirm on an ``IRREVERSIBLE`` effect, deny nothing outright. A
    deployment wanting something stricter passes it in.
    """

    def __init__(  # noqa: PLR0913 — four thresholds the user sets, and the seams and configured values the composition root supplies; each is one thing a deployment decides on its own
        self,
        *,
        confirm_at_risk: RiskLevel | None = RiskLevel.MEDIUM,
        confirm_at_reversibility: Reversibility | None = Reversibility.IRREVERSIBLE,
        deny_at_risk: RiskLevel | None = None,
        deny_at_reversibility: Reversibility | None = None,
        grants: RecipientGrants | None = None,
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
            grants: The standing recipient grants this policy may consult
                (ADR-0193 §7). **The query face and never the store**: a policy
                handed the whole store is one ``record`` call away from
                authorising the send it is ruling on, and the annotation is what
                removes the capability rather than a rule this class is trusted
                to keep. ``None`` — the default — is a conforming policy that
                reaches no route-(b) ``ALLOW`` at all and leaves both
                ``authorised_by`` and ``authorised_subject`` unset on every
                ruling, exactly as ADR-0021 §3 requires of a policy constructed
                with no authorisation source. **It is not what route (c) rests
                on**, and a policy given none still reaches route (c)
                (ADR-0247 §2).
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
        self._grants = grants
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
        answer was: route (b) is available only where
        :data:`_DISCLOSURE_FLOOR` is the whole of what stands in the way
        (ADR-0193 §3, §7).
        """
        return [rule for rule in self._rules if rule.applies(tool)]

    def _grounds(self, tool: ToolDefinition) -> list[tuple[PermissionOutcome, str]]:
        """Every firing clause's outcome and reason, in table order."""
        return [(rule.outcome, rule.because(tool)) for rule in self._fired(tool)]

    def _outcome_for(self, tool: ToolDefinition) -> PermissionOutcome:
        """The most restrictive outcome this policy's rules reach for ``tool``."""
        grounds = self._grounds(tool)
        return max((outcome for outcome, _ in grounds), default=PermissionOutcome.ALLOW)

    async def _covering(
        self, request: ActionRequest, subject: CoverageSubject
    ) -> RecipientGrant | None:
        """The standing grant covering ``request``, or ``None`` — **failing closed**.

        The one durable read a sourced policy performs, at most once per ruling
        and never cached between them (ADR-0193 §7). Its answer is used or
        discarded within this ruling; no result is carried forward, because an
        implementation reusing the last successful lookup would go on authorising
        sends after its authorisation stopped being checkable.

        A :class:`~ai_assistant.core.errors.RecipientGrantError` is **not a
        grant** (ADR-0193 §1's last clause). It is logged and answered ``None``,
        so the ruling proceeds to the ``CONFIRM`` the request would have drawn
        without a store at all — the fail-closed direction, and the reason the
        user sees is unchanged: a store fault is an operator's fact and not
        something to put in front of someone deciding about a call.

        **The traceback is deliberately not logged, and the class name is.**
        ``core.logging`` renders through ``structlog.dev.ConsoleRenderer``, whose
        default exception formatter is ``rich``'s with ``show_locals=True`` — so
        ``exc_info=True`` here would write this frame's locals into the log, and
        ``request`` carries the recipient addresses, the account identity and the
        payload description. ``redact_sensitive`` cannot reach it either: it runs
        **before** the renderer and over the event dict's keys, and a rendered
        traceback is neither. What an operator needs from this line is that the
        seam could not be read and what refused; ``tool_id`` is Tier 2 and the
        class name names no value (ADR-0004 §5).

        **And the id is read before the await, not inside the handler** (ADR-0065).
        A lookup suspends, and a frozen model is rewritable through ``__dict__``, so
        a caller can replace ``request.tool`` while the seam is out — and a handler
        composing its line from ``request.tool.id`` at that point leaves as whatever
        that read raised, from inside the branch that exists to make this failure
        fail *closed*. ``decide`` reads the declaration once for the same reason and
        rules on that value throughout.

        **The request handed on is checked against this ruling's own observation of
        it first, and a drifted one buys no grant** (ADR-0065, ADR-0193 §1's
        fail-closed clause). ``RecipientGrants.covering`` takes its subject at *its*
        first executed line, which is later than this ruling's observation — so a
        seam read ever placed between the two would otherwise let the grant
        returned be one covering the request as rewritten mid-flight, cited in an
        ``ALLOW`` whose every other ground was reached about the request as
        presented. The check is
        sound where it stands because **nothing suspends between it and that line**:
        awaiting a coroutine runs it to its own first await. Rebuilding the subject
        is three validations rather than a whole
        :class:`~ai_assistant.core.types.ActionRequest`, and a request too broken to
        read is answered the same way a fault is — no grant.
        """
        if self._grants is None:  # pragma: no cover — the caller has already checked
            return None
        tool_id = subject.tool.id
        try:
            if coverage_subject(request) != subject:
                _log.warning(
                    "recipient_grant_request_changed_mid_ruling",
                    tool_id=tool_id,
                    outcome="confirm",
                    reason=_REQUEST_CHANGED_MID_RULING,
                )
                return None
        except Exception:  # a request this ruling cannot re-read buys no grant
            _log.warning(
                "recipient_grant_request_unreadable",
                tool_id=tool_id,
                outcome="confirm",
                reason=_REQUEST_CHANGED_MID_RULING,
            )
            return None
        try:
            return await self._grants.covering(request)
        except RecipientGrantError as exc:
            _log.warning(
                "recipient_grant_seam_unreadable",
                tool_id=tool_id,
                outcome="confirm",
                refused_by=type(exc).__name__,
                reason="a policy that cannot check a standing grant asks the user instead",
            )
            return None

    async def decide(self, request: ActionRequest) -> PermissionRuling:
        """Rule on ``request`` by the table in the class docstring.

        Reads ``request.tool`` and — for ADR-0181 §5's clause alone —
        ``request.egress_binding.planned_with_external_content``. ``parameters`` is
        carried on the request for the invocation contract's future per-call gating
        (ADR-0021 §3) and no rule here consults it, so nothing derived from a
        payload reaches the ``reason`` a user is shown. Neither does the egress
        clause: its ground names the selection this system made and quotes nothing
        of the call.

        **It returns no ``ALLOW`` on a request whose binding carries
        ``planned_with_external_content``** (ADR-0181 §5's third clause). ADR-0148
        §3's route (a) is unavailable to this member by construction — it holds no
        ``AuditTrail`` and no resolution about the request exists yet — so the
        obligation is discharged by returning ``CONFIRM``. Nothing is acquired to
        look for a route (a): no trail read, no store handle, no *source*-grant
        seam, the last of which ADR-0097 §7 forbids outright. The recipient-grant
        seam is not acquired for it either — a binding carrying the fact is one of
        the paths :meth:`_only_the_disclosure_floor` excludes, so ``covering`` is
        called **zero** times on it (ADR-0193 §4, §7). A request whose binding
        carries ``False``, or which carries none, is judged on the ordinary path.

        **Route (b), where this policy was given a ``RecipientGrants``**
        (ADR-0193 §3, §7). A standing recipient grant discharges exactly one
        thing: the recipient-authorisation ground ADR-0148 §8's third clause and
        ADR-0021 §5's disclosure floor rest on. So the seam is consulted **only**
        where :data:`_DISCLOSURE_FLOOR` is the entire reason this request is not
        already an ``ALLOW`` — see :meth:`_only_the_disclosure_floor` — and a
        covering grant then yields an ``ALLOW`` naming the grant's ``id`` and its
        recomputed ``subject_digest``.

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
        account or origin, or the reverse, takes no route at all. It is reachable
        **exactly where route (b) is reachable and on the same five conditions**,
        with two of them restated over that fact and one — a grant seam at all — no
        longer required; and where both would answer one request, **(c) answers it
        first** and ``covering`` is called zero times. The ``ALLOW`` names the
        binding's ``account.reference`` and fingerprints nothing, which is what tells
        the two standing routes apart from the row alone. **No confirmation is sought
        and no grant seam is consulted on either kind** (ADR-0260 §6's no-new-question
        clause).

        **A request carrying its kind's fact that is not at that kind's configured
        provider keeps every floor** (ADR-0247 §2, ADR-0260 §6). Because the two
        limbs read the derived fact rather than ``closed_loop`` or ``forecast_reach``,
        such a request planned over external content, or carrying covered content,
        fails :meth:`_only_the_disclosure_floor` outright: the grant seam is consulted
        **zero** times, no ``ALLOW`` of either route is reachable however many
        grants the store holds, and the ruling is the ``CONFIRM`` ADR-0181 §5 and
        ADR-0233 §9 require. That is the case a reading which put the configuration
        check only on route (c) would leave open.

        **Every other ground is independent and survives a grant.** An
        ``UNKNOWN`` cost still draws ``CONFIRM``; a ``risk_level`` or a
        ``reversibility`` at this policy's own threshold still draws ``CONFIRM``;
        a threshold ``DENY`` still stands. A grant "never converts a ``DENY`` into
        anything" and satisfies no floor stated over any fact but recipient
        authorisation (ADR-0193 §3), and each of those cases reaches the seam
        **zero** times rather than reaching it and being overruled — §7 puts the
        lookup after every ground the request alone settles, so a store failure
        cannot disturb an answer the request had already given.

        **It does not discharge ADR-0148 §8's third clause's other limb** — no
        ``ALLOW`` where the request carries no canonical destination set, no
        payload description, or a description that is not the deterministic
        derivation §6 requires. This policy adds no check for that limb and takes
        none away; a grant is not offered as satisfying it (ADR-0193 §3).

        Returns:
            The ruling. A route-(b) ``ALLOW`` sets ``authorised_by`` and
            ``authorised_subject`` together, and only from the record its own
            ``covering`` read returned; a route-(c) one sets ``authorised_by`` to
            the binding's own ``account.reference`` and leaves
            ``authorised_subject`` unset, on either kind (ADR-0247 §2, ADR-0260 §6).
            A policy constructed with **neither** a ``RecipientGrants`` nor a
            configured destination of either kind leaves both unset on every ruling,
            which is ADR-0021 §3's requirement of a policy with no authorisation
            source; ADR-0247 §2 supersedes that requirement in the limb reaching a
            request at the configured provider, and in no other.
        """
        subject = coverage_subject(request)
        tool = subject.tool
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
        if self._only_the_disclosure_floor(
            request, fired, outcome=outcome, external=external, at_configured=at_configured
        ):
            # **Route (c)'s pointer is read here, before the first suspension**, and
            # not off the binding afterwards (ADR-0065). Every line above this one is
            # part of a single observation of the request — nothing else runs on the
            # loop between two statements that do not await — and this is the last of
            # them: past the grant seam's read the caller has had a turn, and a
            # rewritten ``egress_binding.account`` would otherwise put a reference
            # this ruling never checked into the ``ALLOW`` the trail then compares.
            configured = (
                None
                if at_configured is None
                else _ConfiguredAuthority(
                    reference=at_configured.binding.account.reference,
                    ground=at_configured.ground,
                )
            )
            standing = await self._standing_allow(request, subject=subject, configured=configured)
            if standing is not None:
                return standing
        reasons = [reason for ruled, reason in grounds if ruled is outcome]
        return PermissionRuling(outcome=outcome, reason="; ".join(reasons))

    async def _standing_allow(
        self,
        request: ActionRequest,
        *,
        subject: CoverageSubject,
        configured: _ConfiguredAuthority | None,
    ) -> PermissionRuling | None:
        """The standing ``ALLOW`` this request earns, or ``None`` for none.

        **Route (c) first, then route (b)** (ADR-0247 §2's ordering before the grant
        seam). Where route (c) answers, ``RecipientGrants.covering`` is called
        **zero** times; otherwise it is called **once**, and never cached (ADR-0193
        §7).

        Args:
            request: The action being ruled on, already past
                :meth:`_only_the_disclosure_floor`. **Handed to the grant seam and
                read for nothing else.**
            subject: The one pre-suspension observation of the request, which the
                grant seam's drift check compares against.
            configured: Route (c)'s authority where ADR-0247 §2's derived fact
                holds of the request, as ADR-0260 §6 widens it — the binding's
                ``account.reference`` and the matched kind's own ground, both read
                before the suspension — and ``None`` otherwise.

        Returns:
            The ``ALLOW`` a standing route earned, or ``None`` where none did.
        """
        if configured is not None:
            # **Route (c), taken before the grant seam is consulted** (ADR-0247
            # §2, ADR-0260 §6): where both routes would be reachable for one
            # request this answers it, ``_covering`` is called **zero** times, and
            # no ruling at either configured provider ever cites a grant again.
            #
            # **The ground is the matched kind's own** and is carried here rather
            # than chosen here: ``_at_configured_provider`` is where the kind was
            # decided, and a second reading of the binding at this site would be
            # one rule stated twice — and would be read *after* the suspension,
            # which is exactly what the pointer below is pre-read to avoid.
            #
            # ``authorised_by`` is **owed** rather than a matter of taste
            # (ADR-0021 §5, ADR-0247 §2): §5's disclosure floor forbids an
            # ``ALLOW`` with the field unset for a non-empty ``discloses``. The
            # pointer is not a string this policy invented — it is a value
            # carried on the binding the seam derived and **read off it before
            # this ruling suspended** (ADR-0065), and the trail's own check
            # compares it against exactly that. ``authorised_subject`` stays
            # unset, and its absence is the discriminator that tells the two
            # standing routes apart from the row alone.
            return PermissionRuling(
                outcome=PermissionOutcome.ALLOW,
                reason=configured.ground,
                authorised_by=configured.reference,
            )
        recipient = await self._covering(request, subject)
        if recipient is not None:
            return PermissionRuling(
                outcome=PermissionOutcome.ALLOW,
                reason=_STANDING_GRANT,
                authorised_by=recipient.id,
                authorised_subject=recipient.subject_digest,
            )
        return None

    def _only_the_disclosure_floor(
        self,
        request: ActionRequest,
        fired: list[_Rule],
        *,
        outcome: PermissionOutcome,
        external: bool,
        at_configured: _ConfiguredProviderMatch | None,
    ) -> bool:
        """Whether a standing route is reachable at all for this request.

        Five conditions (ADR-0193 §7), **two of them restated over ADR-0247 §2's
        derived fact as ADR-0260 §6 generalises it** and a third widened by it.
        Each is a path on which the grant seam must be consulted **zero** times
        rather than consulted and ignored:

        * this policy has a source at all, **or the request is at its kind's
          configured provider** — with neither it reaches no standing ``ALLOW`` and
          asks about no grant (ADR-0021 §3). ADR-0247 §2 supersedes that clause "in
          the limb that reaches a request carrying ``closed_loop``, and in no
          other", and ADR-0260 §6 carries the supersession to a forecast read at the
          configured forecast provider and to no further kind: the authority route
          (c) cites is the deployment's own configuration, which this policy is
          handed no seam for and needs none, so **a policy constructed with no
          ``RecipientGrants`` reaches route (c)** on either kind. On every other
          request a sourceless policy still sets neither field;
        * the request is an egress call, so its ``egress_binding`` is not
          ``None``. A request carrying none names no account and no destination
          set, and no grant can cover it;
        * its binding does not carry ``planned_with_external_content``, **or the
          request is at its kind's configured provider** (ADR-0247 §3 as ADR-0260
          §6 restates it, superseding ADR-0238 §6's first clause). §4's bar is the
          ``ActionPolicy`` contract's and is applied **here** rather than on the
          seam, so ``covering`` never has to read the fact and the two statements
          cannot drift apart. A call carrying the taint keeps its confirmation
          whatever grants exist — **unless** it is a ``WEB_SEARCH`` at the search
          destination the owner configured or a forecast read at the forecast
          destination they configured, which is the whole of the exception this
          corpus admits and which ADR-0247 §1 and ADR-0260 §6 each state over two
          recorded comparisons taken per request. **The limb is stated over the
          derived fact and never over ``closed_loop`` or ``forecast_reach`` alone**
          (ADR-0247 §2): a binding carrying its kind's fact whose account or origin
          is not **that kind's** configured pair fails this limb, so the seam is
          consulted zero times and no ``ALLOW`` is reachable for it however many
          grants the store holds. **This policy re-derives none of the facts behind
          that** (ADR-0238 §5): "no ``ActionPolicy`` acquires a store handle, a trail
          read, a grant seam or a conversation identity", and it compares two
          configured values against what ``orchestration`` wrote onto the binding —
          the same trust boundary this corpus already accepts for
          ``planned_with_external_content`` itself;
        * its binding carries no covered content, **or the request is at its
          kind's configured provider** (ADR-0233 §9, ADR-0238 §7, ADR-0247 §3,
          ADR-0260 §6). ADR-0233
          §9's second clause is absolute about the class: "**no** standing
          authorisation, standing policy, standing recipient grant, configuration,
          connected account, tool declaration or approved payload description covers
          such a call, **ever**" — its four conditions are what makes a
          model-composed span approvable *by confirmation*, and neither standing
          route is a confirmation. ADR-0238 §7 opened the one exception this corpus
          admits and ADR-0247 §3 restates it over the configured provider, **in one
          act with the limb above**: a query a ``QueryComposer`` composed over a
          supply carrying any record at all is a model-composed span over covered
          content, so a deployment that retired the lineage floor alone would still
          be stopped here on every query the milestone exists to compose. "Where any
          of the three fails, the clause forbids the span exactly as written".
          **ADR-0260 §6 retires both limbs at the forecast kind for ADR-0247 §3's
          reason and not a new one**: "both limbs are satisfied by one fact and are
          not two decisions";
        * the outcome is ``CONFIRM``. A ``DENY`` is not something a grant or a
          configuration converts, and an ``ALLOW`` needs neither;
        * and the **only** clause that fired is :data:`_DISCLOSURE_FLOOR`. That
          is the ground a grant discharges and the ground route (c) rests on;
          every other firing clause is an independent floor or a threshold the
          user configured, so a request that tripped one of those is settled by
          its own facts and reaches no route. An ``UNKNOWN`` cost still draws
          ``CONFIRM`` at either configured provider, and so does a ``risk_level``
          or a ``reversibility`` at this policy's own threshold (ADR-0247 §2, and
          ADR-0260 §11 leaving the unknown-cost floor untouched at this kind).

        Args:
            request: The action being ruled on.
            fired: Every clause of the table that applies to its declaration.
            outcome: The most restrictive outcome those clauses reach.
            external: Whether the binding records that the call was planned over
                external content. Read beside ``at_configured``, because ADR-0247
                §3 supersedes ADR-0181 §5's second clause and ADR-0193 §4's first
                clause **for a request at its kind's configured provider alone**,
                and for no other request of any kind: an email, a fetch, a tool
                call, a search bound anywhere else **and a forecast read bound
                anywhere else** in the very same conversation each keep the floor
                exactly as written (ADR-0238 §5's last clause, ADR-0247 §3's last,
                ADR-0260 §6's last).
            at_configured: The match where ADR-0247 §2's derived fact holds of the
                request, as ADR-0260 §6 widens it, and ``None`` otherwise. Passed in
                rather than recomputed here, so the fact the ruling is taken over and
                the fact the limbs read are one value.

        Returns:
            Whether a standing route is reachable — route (c) where
            ``at_configured`` is not ``None``, and otherwise the one grant lookup.
        """
        binding = request.egress_binding
        configured = at_configured is not None
        return (
            (self._grants is not None or configured)
            and binding is not None
            and (not external or configured)
            and (binding.coverage is SpanCoverage.NOT_COVERED or configured)
            and outcome is PermissionOutcome.CONFIRM
            and fired == [_DISCLOSURE_FLOOR]
        )

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
        ``isinstance``. Both are a **floor rather than a route that exists**:
        ``AuditTrail.pending_confirmation`` refuses to offer either park and
        ``StepRunner.resume`` refuses each again before any ruling is sought, so
        nothing in the tree reaches these branches — which is exactly ADR-0021 §5's
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
