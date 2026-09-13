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
from typing import TYPE_CHECKING, NamedTuple

import structlog

from ai_assistant.core.errors import AuthorizationError, RecipientGrantError
from ai_assistant.core.types import (
    AuthorizationOrigin,
    CostBasis,
    CoverageUnrecordedBinding,
    OriginUnrecordedBinding,
    PermissionOutcome,
    PermissionRuling,
    Reversibility,
    RiskLevel,
    SpanCoverage,
)
from ai_assistant.permissions._coverage import account_of, covers, uncovered

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.protocols import GoalAuthorizations, RecipientGrants
    from ai_assistant.core.types import (
        ActionRequest,
        Authorization,
        CanonicalDestination,
        EgressBinding,
        PermissionDecision,
        RecipientGrant,
        ToolDefinition,
    )

_log = structlog.get_logger(__name__)

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

#: The ground a route-(d) ``ALLOW`` is rendered with (ADR-0254 §6). It names the
#: **basis** — that a recorded act of the user about this goal fixed or bounded
#: every user-facing argument of this call — and quotes **no argument key, no
#: value, no bound, no record id and no digest**. ADR-0254 §4 is explicit that a
#: reason never reproduces an argument's value, the bound, the record's id or its
#: digest: the reason is carried on a durable ``PermissionDecision`` that holds
#: ``parameters_digest`` and not ``parameters``, and quoting a value would put into
#: the trail exactly what that omission keeps out.
_GOAL_AUTHORIZATION = (
    "the user's own recorded act for this goal fixed or bounded every argument of "
    "this call, and this call is inside it"
)

#: Reported to an operator when the authorization seam could not answer. **A fault
#: takes ADR-0254 §6's bar and is never read as an absence**: this seam discovers
#: restrictions as well as permissions, so a fault answered ``None`` would turn a
#: ``CONFIRM`` the user's own act earned into a route-(b) or route-(c) ``ALLOW`` —
#: a transient store fault making a call *more* authorised, which is the one
#: direction nothing in this corpus may fail in.
_AUTHORIZATION_SEAM_UNREADABLE = (
    "a policy that cannot check a standing authorization takes no standing route at all"
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


class _Authority(NamedTuple):
    """What the one ``live_for`` read settled about ADR-0254 §6's bar.

    Three values because §6 asks three questions of one read and a ``bool`` answers
    only the first: whether a standing route may be taken at all, which row route
    (d) would then be decided from, and — where the bar fired on **coverage** rather
    than on a fault — §4's account of which of its three failures it was.
    """

    barred: bool
    """Whether ADR-0254 §6's bar fires, so no standing route is taken at all."""

    record: Authorization | None
    """The live row the seam returned, or ``None``.

    ``None`` covers three different facts and route (d) treats them alike: the seam
    was not read (no goal, or no seam), it answered ``None``, or it faulted."""

    account: str | None
    """§4's account of the coverage failure, where the bar fired on one.

    ``None`` on a **fault**, because there is no coverage failure to describe and
    *"a store fault is an operator's fact and not something to put in front of
    someone deciding about a call"*."""


@dataclass(frozen=True, slots=True)
class ConfiguredSearchDestination:
    """The search destination this deployment is configured with (ADR-0247 §1, §2).

    The two values ``Settings.web_search_connection`` and
    ``Settings.web_search_origin`` amount to, as the one argument §2 gives
    :class:`ThresholdActionPolicy`: the connection reference the search is
    registered against, and the canonical destination set that origin canonicalises
    to. **Not a store handle, a trail read, a grant seam or a conversation
    identity**, so ADR-0238 §5's clause forbidding a policy any of those is
    untouched and its trust boundary is unmoved.

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


def _at_configured_provider(
    binding: EgressBinding | None, configured: ConfiguredSearchDestination | None
) -> EgressBinding | None:
    """``binding`` where the request is *at the configured provider*, else ``None``.

    ADR-0247 §2's one derived fact, over which every relaxation of §3 is stated. It
    is three conjuncts and no more: the binding carries ``closed_loop``, its
    ``account.reference`` equals the configured connection reference, and its
    canonical destination set equals the configured one.

    **``closed_loop`` alone is never the condition of any relaxation** (§2). §4
    writes that fact before the binding exists, so it asserts *"this deployment's
    own search"* and cannot assert which account and origin the binding carries; a
    lane reading it alone reopens the hole §3's limbs are stated to close.

    **Both comparisons are over recorded values** (§1): ``DurableIdentifier``
    equality and ``CanonicalDestination`` equality, every field and never across
    protocols. Neither side is inferred, folded, matched by domain or
    re-canonicalised here — the canonical forms were computed once, by one
    canonicaliser, before either reached this function.

    **A policy constructed with no configured destination takes the fact as false
    for every request** (§2), which is the fail-closed direction and the same shape
    ADR-0021 §3 gives a policy with no authorisation source.

    Args:
        binding: The request's own binding, or ``None`` where it carries none — a
            request that is not an egress call, and so at no provider.
        configured: What this deployment is configured with, or ``None``.

    Returns:
        The binding itself where the request is at the configured provider, so a
        caller that then needs its ``account.reference`` reads it off the value the
        comparison was taken over rather than off a second lookup; ``None``
        otherwise.
    """
    if binding is None or configured is None or not binding.closed_loop:
        return None
    if binding.account.reference != configured.reference:
        return None
    if frozenset(binding.canonical_destination_set) != configured.destinations:
        return None
    return binding


class ThresholdActionPolicy:
    """An ``ActionPolicy`` combining user thresholds with the contract's floors.

    Structurally implements :class:`~ai_assistant.core.protocols.ActionPolicy`.

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

    **A ``ConfiguredSearchDestination`` changes the same one row, by a second
    route that consults no seam at all** (ADR-0247 §2, §3). Where the request is a
    ``WEB_SEARCH`` at the destination this deployment is configured with — its
    binding carrying ``closed_loop``, its account's connection reference and its
    canonical destination set equal to the configured ones — ADR-0148 §3's route
    (c) answers it: an ``ALLOW`` naming that reference, fingerprinting nothing, and
    taken **before** the grant seam is reached, so ``covering`` is called zero
    times. The two limbs ADR-0238 opened over ``closed_loop`` are restated over
    that whole fact rather than over ``closed_loop`` alone, which is what keeps
    both floors on a binding whose account or origin is not the configured one:
    such a request reaches no ``ALLOW`` of either route, however many grants the
    store holds. Every other row is untouched here too, and a policy constructed
    with no configured destination behaves exactly as it did.

    The defaults are deliberately unremarkable and are **not** a decision the
    contract makes for the user (ADR-0021 §5): confirm at or above ``MEDIUM``
    risk, confirm on an ``IRREVERSIBLE`` effect, deny nothing outright. A
    deployment wanting something stricter passes it in.
    """

    def __init__(  # noqa: PLR0913 — four thresholds the user sets, and one seam and one configured value the composition root supplies; each is one thing a deployment decides on its own
        self,
        *,
        confirm_at_risk: RiskLevel | None = RiskLevel.MEDIUM,
        confirm_at_reversibility: Reversibility | None = Reversibility.IRREVERSIBLE,
        deny_at_risk: RiskLevel | None = None,
        deny_at_reversibility: Reversibility | None = None,
        grants: RecipientGrants | None = None,
        configured_search: ConfiguredSearchDestination | None = None,
        authorizations: GoalAuthorizations | None = None,
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
                provider* fact false for every request, which is the fail-closed
                direction: such a policy reaches no route-(c) ``ALLOW``, and a
                request that would have taken one draws the ``CONFIRM`` it draws
                at ``origin/main``.
            authorizations: The goal authorizations this policy may consult
                (ADR-0254 §6, §16). **The query face and never the store**: a
                policy handed the whole store is one ``record`` call away from
                authorising the call it is ruling on, and the annotation is what
                removes the capability rather than a rule this class is trusted to
                keep. ``None`` — the default — takes **route (d) as unreachable for
                every request** and leaves ``authorised_by``, ``authorised_subject``
                and ``authorised_goal`` unset on every ruling it would have set
                them on, which is ADR-0021 §3's rule unamended in this limb;
                ADR-0247 §2's supersession of that rule is **not inherited**, being
                stated *"in the limb that reaches a request carrying
                ``closed_loop``, and in no other"*. Such a policy also **never
                fires ADR-0254 §6's bar** and reads this seam **zero** times, on
                every request.

        A ``deny`` threshold below its matching ``confirm`` threshold is
        accepted rather than rejected: the combination is still a maximum, so
        the result is a policy that denies where it would otherwise have asked —
        strictly safer, and refusing it would be this contract deciding how
        cautious its user is allowed to be.
        """
        self._grants = grants
        self._configured_search = configured_search
        self._authorizations = authorizations
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

    async def _covering(self, request: ActionRequest) -> RecipientGrant | None:
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
        """
        if self._grants is None:  # pragma: no cover — the caller has already checked
            return None
        tool_id = request.tool.id
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

        **Route (c), where this policy was given a configured search destination**
        (ADR-0247 §2, §3). ADR-0148 §3's enumeration of what an ``ALLOW`` on an
        egress request may rest on gains a third route: the request is a
        ``WEB_SEARCH`` at the destination this deployment's owner configured, which
        is §1's two recorded comparisons taken over the binding beside the
        ``closed_loop`` ``orchestration`` wrote. It is reachable **exactly where
        route (b) is reachable and on the same five conditions**, with two of them
        restated over that fact and one — a grant seam at all — no longer required;
        and where both would answer one request, **(c) answers it first** and
        ``covering`` is called zero times. The ``ALLOW`` names the binding's
        ``account.reference`` and fingerprints nothing, which is what tells the two
        standing routes apart from the row alone.

        **A request carrying ``closed_loop`` that is not at the configured provider
        keeps every floor** (ADR-0247 §2). Because the two limbs read the derived
        fact rather than ``closed_loop``, such a request planned over external
        content, or carrying covered content, fails
        :meth:`_only_the_disclosure_floor` outright: the grant seam is consulted
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
            ``authorised_subject`` unset (ADR-0247 §2). A policy constructed with
            **neither** a ``RecipientGrants`` nor a
            :class:`ConfiguredSearchDestination` leaves both unset on every ruling,
            which is ADR-0021 §3's requirement of a policy with no authorisation
            source; ADR-0247 §2 supersedes that requirement in the limb reaching a
            request at the configured provider, and in no other.
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
        at_configured = _at_configured_provider(request.egress_binding, self._configured_search)
        if self._only_the_disclosure_floor(
            request, fired, outcome=outcome, external=external, at_configured=at_configured
        ):
            barred, record, account = await self._authority(request)
            if not barred:
                standing = await self._standing_allow(
                    request, record, at_configured=at_configured, external=external
                )
                if standing is not None:
                    return standing
            elif account is not None:
                # **ADR-0254 §4's account of why coverage failed**, added to the
                # grounds the table already reached rather than replacing them: the
                # disclosure floor is still what stands in the way, and the bar is
                # why no standing route relieved it. The outcome is already
                # ``CONFIRM`` — ``_only_the_disclosure_floor`` is what admitted this
                # branch — so appending a ``CONFIRM`` ground moves nothing but the
                # sentence the user reads. **It quotes no value, no bound, no record
                # id and no digest**, and names a key only where the declaration's
                # own schema names it (:func:`~ai_assistant.permissions._coverage.
                # account_of`).
                grounds.append((PermissionOutcome.CONFIRM, account))
        reasons = [reason for ruled, reason in grounds if ruled is outcome]
        return PermissionRuling(outcome=outcome, reason="; ".join(reasons))

    async def _standing_allow(
        self,
        request: ActionRequest,
        record: Authorization | None,
        *,
        at_configured: EgressBinding | None,
        external: bool,
    ) -> PermissionRuling | None:
        """The standing ``ALLOW`` this request earns, or ``None`` for none.

        **ADR-0254 §6's total order, and each step answers before the next seam is
        consulted**: the **bar** first, on the one ``live_for`` read; then **route
        (c)** (ADR-0247 §2's ordering before the grant seam, kept); then **route
        (d)**, decided from the row that same read returned; then **route (b)**.

        **Where the bar fires, no route answers** and ``RecipientGrants.covering``
        is called **zero** times. Where route (c) answers, it is called **zero**
        times. Where route (d) answers, it is called **zero** times — **except on
        an opening-act row**, where it is consulted **once, before route (d) may
        answer**, because such a row carries no recipient authority of its own and
        the one it rested on must still stand. **At most one durable read per seam
        per ruling and never a cached answer** (ADR-0193 §7's rule read onto the
        second seam, and it holds on both).

        **Why (d) precedes (b), stated so it is a decision and not an accident**
        (ADR-0254 §6). A record covering a request under both routes is one the user
        made about *this goal*, with a basis naming the turn and the span, an expiry
        measured in hours and a coverage that names the arguments; the grant that
        would also cover it is a standing preference about a destination set, made
        about something else, with no basis and a longer life. Citing the narrower
        and better-evidenced authority records more and asserts less. **Neither
        route is made reachable or unreachable by the order.**

        **It is reached only where the bar did not fire.** *"Where the bar fires, no
        route answers"* and the recipient-grant seam is consulted **zero** times,
        which :meth:`decide` keeps by not calling this at all — the ruling there is
        the one the table reached with no standing route, which is what §13 and §14
        require of a changed argument outside coverage, what §5 promises of a
        widening the store refused, and what §9's third clause promises of *"an
        argument no member names"*.

        Args:
            request: The action being ruled on, already past
                :meth:`_only_the_disclosure_floor`.
            record: The row the one ``live_for`` read returned, or ``None``.
            at_configured: The binding where ADR-0247 §2's derived fact holds of it,
                and ``None`` otherwise.
            external: Whether the binding records that the call was planned over
                external content.

        Returns:
            The ``ALLOW`` a standing route earned, or ``None`` where none did.
        """
        if at_configured is not None:
            # **Route (c), taken before the grant seam is consulted** (ADR-0247
            # §2): where both routes would be reachable for one request this
            # answers it, ``_covering`` is called **zero** times, and no ruling
            # at the configured provider ever cites a grant again.
            #
            # ``authorised_by`` is **owed** rather than a matter of taste
            # (ADR-0021 §5, ADR-0247 §2): §5's disclosure floor forbids an
            # ``ALLOW`` with the field unset for a non-empty ``discloses``. The
            # pointer is not a string this policy invented — it is a value
            # carried on the binding the seam derived, and the trail's own
            # check compares it against exactly that. ``authorised_subject``
            # stays unset, and its absence is the discriminator that tells the
            # two standing routes apart from the row alone.
            return PermissionRuling(
                outcome=PermissionOutcome.ALLOW,
                reason=_CONFIGURED_SEARCH_PROVIDER,
                authorised_by=at_configured.account.reference,
            )
        recipient: RecipientGrant | None = None
        consulted = False
        if self._covers_in_full(request, record):
            assert record is not None  # noqa: S101 — narrowing; the test is stated over it
            if record.origin is AuthorizationOrigin.OPENING_ACT:
                # **The one exception to "route (d) answers with the grant seam
                # consulted zero times"** (ADR-0254 §6): an opening-act row carries
                # no recipient authority of its own, so the one it rested on is
                # re-taken here, **once, before route (d) may answer**. Where it no
                # longer stands, route (b) does not cover either — it needs the same
                # grant — so the answer is carried rather than the seam re-read,
                # which is what keeps "at most one durable read per seam per ruling"
                # true on this path as on every other.
                recipient = await self._covering(request)
                consulted = True
            if consulted is False or recipient is not None:
                return PermissionRuling(
                    outcome=PermissionOutcome.ALLOW,
                    reason=_GOAL_AUTHORIZATION,
                    authorised_by=record.id,
                    authorised_subject=record.subject_digest,
                    authorised_goal=record.goal,
                )
        if external:
            # **The third disjunct is what admitted this request** (ADR-0254 §6):
            # ``_only_the_disclosure_floor``'s lineage limb now reads "…, **or** the
            # request carries a ``goal`` and the policy holds a
            # ``GoalAuthorizations``", and that disjunct **admits a request rather
            # than deciding it**. Route (c) does not answer on it, because ADR-0247
            # §3's retirement is for a ``WEB_SEARCH`` at the configured provider and
            # for nothing else; route (b) does not, because ADR-0193 §4 is unmoved
            # and **no** ``RecipientGrant`` covers a tainted call. So a request the
            # goal's record does not cover in full reaches **no** route at all and
            # ``_covering`` is called **zero** times.
            return None
        if not consulted:
            recipient = await self._covering(request)
        if recipient is not None:
            return PermissionRuling(
                outcome=PermissionOutcome.ALLOW,
                reason=_STANDING_GRANT,
                authorised_by=recipient.id,
                authorised_subject=recipient.subject_digest,
            )
        return None

    async def _authority(self, request: ActionRequest) -> _Authority:
        """The one ``live_for`` read, and whether ADR-0254 §6's bar fires on it.

        **Where the bar reads, and it is the same read route (d) takes** (§6). The
        policy calls ``live_for`` **at most once per ruling**, and both the bar and
        route (d) are decided from the row it returns: there is no second seam read,
        no second clock reading and no cached answer. It is called **only** where
        ``request.goal`` is set, so a request carrying none reads the seam **zero**
        times and the bar never fires on one; and **only** where the policy holds a
        ``GoalAuthorizations``, a policy constructed without one taking the bar as
        never firing exactly as it takes route (d) as unreachable. Those two
        exclusions are what bound the fault clause below.

        **A standing route is taken only on one of exactly two answers** (§6): *no
        record* — the seam read the store and holds no live row for that goal and
        that declaration id — or *a record every user-facing argument of the request
        is covered by*, which is §3's **condition 6 and that condition alone**. On
        every other answer no standing route is taken at all: a record some argument
        of the request is not covered by, whether it names that argument in a member
        the value fails **or names it in no member at all**; and an answer the seam
        could not give.

        **The bar is stated over the arguments and over nothing else, and the line
        is ADR-0193 §5's.** It does not fire on the declaration, on an account the
        record does not carry, or on a destination outside the record's set: those
        are facts a grant is stated *about*, so a request whose only mismatch is one
        of them fails route (d) on §3's conditions 3, 4 and 5 and still reaches
        route (c) or route (b), exactly as it does today. **A record's arguments are
        the one thing nothing else in this corpus speaks for**, and that is the
        whole of what the bar refuses on.

        **The bar reads no field of the declaration, and that is what makes it
        monotone** (ADR-0021 §5). It is keyed on the declaration's ``id``, which no
        severity edit moves, and its test is condition 6 over the arguments, which
        no severity edit moves either — so raising ``risk_level``,
        ``reversibility`` or ``discloses`` cannot change its answer in **either**
        direction.

        **A seam the policy could not read takes the bar, and that is the one place
        this seam departs from** :meth:`_covering`'s **discipline.** That method
        answers ``None`` on a fault because the grant seam discovers *permissions*
        only, and losing a permission can only make a ruling more restrictive. This
        seam discovers **restrictions** as well, so a fault that read as absence
        would turn a ``CONFIRM`` the bar owes into a route-(b) or route-(c)
        ``ALLOW``. So the fault is logged and **takes the bar**.

        **The log line names the class and no value, and the declaration's id is
        read before the await** — both :meth:`_covering`'s existing discipline,
        adopted rather than reinvented (ADR-0065: a frozen model is rewritable
        through ``__dict__``, so a handler composing its line from
        ``request.tool.id`` after the seam suspended leaves as whatever that read
        raised).

        Args:
            request: The action being ruled on.

        **A fault carries no account** (§4, §16). *"A store fault is an operator's
        fact and not something to put in front of someone deciding about a call"*,
        so the reason the user sees is the one the table reached and nothing is
        added to it — there is no coverage failure to describe, and describing the
        fault would put an operator's fact in the prompt.

        Returns:
            Whether the bar fires; the live row the seam returned — ``None`` where
            the seam was not read at all, where it answered ``None``, or where it
            faulted; and ADR-0254 §4's account of the coverage failure where the bar
            fired on one.
        """
        goal = request.goal
        if goal is None or self._authorizations is None:
            return _Authority(barred=False, record=None, account=None)
        tool_id = request.tool.id
        try:
            record = await self._authorizations.live_for(goal, tool_id)
        except AuthorizationError as exc:
            _log.warning(
                "authorization_seam_unreadable",
                tool_id=tool_id,
                outcome="confirm",
                refused_by=type(exc).__name__,
                reason=_AUTHORIZATION_SEAM_UNREADABLE,
            )
            return _Authority(barred=True, record=None, account=None)
        if record is None:
            return _Authority(barred=False, record=None, account=None)
        defects = uncovered(record, request)
        if defects:
            return _Authority(barred=True, record=record, account=account_of(defects, request.tool))
        return _Authority(barred=False, record=record, account=None)

    @staticmethod
    def _covers_in_full(request: ActionRequest, record: Authorization | None) -> bool:
        """Whether route (d) covers this request but for the opening-act recheck.

        **Route (d) is reachable on** :meth:`_only_the_disclosure_floor`'s **five
        conditions and relaxes none of them** (ADR-0254 §6). Two of them are
        re-taken **over the binding** here rather than read off that predicate's
        answer, because that predicate carries ADR-0247 §3's disjunct and a lane
        reusing its answer would relax on route (d) something §6 relaxes only on its
        own terms:

        * **condition 4** — the binding's ``coverage`` is
          ``SpanCoverage.NOT_COVERED``, **in its strict form**. ADR-0233 §9's second
          clause is absolute about its class — *"**no** standing authorisation,
          standing policy, standing recipient grant, configuration, connected
          account, tool declaration or approved payload description covers such a
          call, **ever**"* — and route (d) inherits none of ADR-0247 §3's
          retirement, because **route (d) is not route (c)**. A request at the
          configured provider carrying covered content therefore reaches route (d)
          in no case.
        * **condition 3** — the binding does not carry
          ``planned_with_external_content``, **or** the row covers the request under
          §3 **in full**. That second limb is ADR-0181 §5's floor **discharged**, and
          it is subsumed by the coverage test rather than stated twice: route (d)
          answers only where the row covers in full, so a tainted request the row
          does not cover in full reaches no route at all. **Partial coverage still
          asks.**

        The remaining condition — the recipient authority an **opening-act** row
        rested on, re-taken at every dispatch — is :meth:`_standing_allow`'s,
        because it is the one that spends a seam read and the read has to be shared
        with route (b).

        Args:
            request: The action being ruled on.
            record: The row the one ``live_for`` read returned, or ``None``.

        Returns:
            Whether §3's six conditions hold over that pair and condition 4 holds
            over the binding.
        """
        binding = request.egress_binding
        if record is None or binding is None or binding.coverage is not SpanCoverage.NOT_COVERED:
            return False
        return covers(record, request)

    def _only_the_disclosure_floor(
        self,
        request: ActionRequest,
        fired: list[_Rule],
        *,
        outcome: PermissionOutcome,
        external: bool,
        at_configured: EgressBinding | None,
    ) -> bool:
        """Whether a standing route is reachable at all for this request.

        Five conditions (ADR-0193 §7), **two of them restated over ADR-0247 §2's
        derived fact** and a third widened by it. Each is a path on which the grant
        seam must be consulted **zero** times rather than consulted and ignored:

        * this policy has a source at all, **or the request is at the configured
          provider** — with neither it reaches no standing ``ALLOW`` and asks about
          no grant (ADR-0021 §3). ADR-0247 §2 supersedes that clause "in the limb
          that reaches a request carrying ``closed_loop``, and in no other": the
          authority route (c) cites is the deployment's own configuration, which
          this policy is handed no seam for and needs none, so **a policy
          constructed with no ``RecipientGrants`` reaches route (c)**. On every
          other request a sourceless policy still sets neither field;
        * the request is an egress call, so its ``egress_binding`` is not
          ``None``. A request carrying none names no account and no destination
          set, and no grant can cover it;
        * its binding does not carry ``planned_with_external_content``, **or the
          request is at the configured provider** (ADR-0247 §3, superseding
          ADR-0238 §6's first clause). §4's bar is the ``ActionPolicy`` contract's
          and is applied **here** rather than on the seam, so ``covering`` never has
          to read the fact and the two statements cannot drift apart. A call
          carrying the taint keeps its confirmation whatever grants exist —
          **unless** it is a ``WEB_SEARCH`` at the destination the owner configured,
          which is the one exception this corpus admits and which ADR-0247 §1 states
          over two recorded comparisons taken per request. **The limb is stated over
          the derived fact and never over ``closed_loop`` alone** (§2): a binding
          carrying ``closed_loop`` whose account or origin is not the configured one
          fails this limb, so the seam is consulted zero times and no ``ALLOW`` is
          reachable for it however many grants the store holds. **This policy
          re-derives none of the facts behind that** (ADR-0238 §5): "no
          ``ActionPolicy`` acquires a store handle, a trail read, a grant seam or a
          conversation identity", and it compares two configured values against what
          ``orchestration`` wrote onto the binding — the same trust boundary this
          corpus already accepts for ``planned_with_external_content`` itself;
        * its binding carries no covered content, **or the request is at the
          configured provider** (ADR-0233 §9, ADR-0238 §7, ADR-0247 §3). ADR-0233
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
          of the three fails, the clause forbids the span exactly as written";
        * the outcome is ``CONFIRM``. A ``DENY`` is not something a grant or a
          configuration converts, and an ``ALLOW`` needs neither;
        * and the **only** clause that fired is :data:`_DISCLOSURE_FLOOR`. That
          is the ground a grant discharges and the ground route (c) rests on;
          every other firing clause is an independent floor or a threshold the
          user configured, so a request that tripped one of those is settled by
          its own facts and reaches no route. An ``UNKNOWN`` cost still draws
          ``CONFIRM`` at the configured provider, and so does a ``risk_level`` or
          a ``reversibility`` at this policy's own threshold (ADR-0247 §2).

        Args:
            request: The action being ruled on.
            fired: Every clause of the table that applies to its declaration.
            outcome: The most restrictive outcome those clauses reach.
            external: Whether the binding records that the call was planned over
                external content. Read beside ``at_configured``, because ADR-0247
                §3 supersedes ADR-0181 §5's second clause and ADR-0193 §4's first
                clause **for a request at the configured provider alone**, and for
                no other request of any kind: an email, a fetch, a tool call and a
                search bound anywhere else in the very same conversation each keep
                the floor exactly as written (ADR-0238 §5's last clause, ADR-0247
                §3's last).
            at_configured: The binding where ADR-0247 §2's derived fact holds of
                it, and ``None`` otherwise. Passed in rather than recomputed here,
                so the fact the ruling is taken over and the fact the limbs read
                are one value.

        Returns:
            Whether a standing route is reachable — route (c) where
            ``at_configured`` is not ``None``, and otherwise the one grant lookup.
        """
        binding = request.egress_binding
        configured = at_configured is not None
        return (
            (self._grants is not None or configured or self._authorizations is not None)
            and binding is not None
            and (not external or configured or self._sourced(request))
            and (binding.coverage is SpanCoverage.NOT_COVERED or configured)
            and outcome is PermissionOutcome.CONFIRM
            and fired == [_DISCLOSURE_FLOOR]
        )

    def _sourced(self, request: ActionRequest) -> bool:
        """ADR-0254 §6's third disjunct on the lineage limb, and it **admits** only.

        *"``_only_the_disclosure_floor``'s lineage limb gains a third disjunct, and
        that disjunct admits a request rather than deciding it."* It becomes *"the
        binding does not carry ``planned_with_external_content``, **or** the request
        is at the configured provider, **or** the request carries a ``goal`` and the
        policy holds a ``GoalAuthorizations``"*.

        **Where this disjunct is what admitted the request, route (d) is the only
        route that may answer**: route (c) does not, because ADR-0247 §3's
        retirement is for a ``WEB_SEARCH`` at the configured provider and for
        nothing else; route (b) does not, because ADR-0193 §4 is unmoved and **no**
        ``RecipientGrant`` covers a tainted call. :meth:`_standing_allow` is where
        that is kept.

        **The coverage limb gains no disjunct**, and the predicate is not made to
        depend on a seam read: this admits, and ADR-0254 §3's six conditions decide.

        Args:
            request: The action being ruled on.

        Returns:
            Whether the request carries a goal and this policy holds the seam.
        """
        return request.goal is not None and self._authorizations is not None

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
