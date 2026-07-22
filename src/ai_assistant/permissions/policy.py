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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai_assistant.core.types import (
    CostBasis,
    PermissionOutcome,
    PermissionRuling,
    Reversibility,
    RiskLevel,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.types import ActionRequest, PermissionDecision, ToolDefinition

#: Reported when ``resolve`` is handed a decision the user was never shown.
_NOT_A_CONFIRMATION = "the decision resolved was not a CONFIRM, so it authorises nothing"


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
_FLOORS = (_DISCLOSURE_FLOOR, _UNKNOWN_COST_FLOOR)


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
    * nothing applies — ``ALLOW``.

    **The thresholds cannot configure it out of conformance.** Each clause is a
    monotone step function of one declared field and the combination is a
    maximum, so every setting of the four knobs yields a monotone policy; the
    two floors are module constants no argument reaches. A policy configurable
    into violating its own conformance suite would be a trap for the user it is
    meant to protect, and ADR-0036 §1 records the shape as the reason it is not
    one.

    The defaults are deliberately unremarkable and are **not** a decision the
    contract makes for the user (ADR-0021 §5): confirm at or above ``MEDIUM``
    risk, confirm on an ``IRREVERSIBLE`` effect, deny nothing outright. A
    deployment wanting something stricter passes it in.
    """

    def __init__(
        self,
        *,
        confirm_at_risk: RiskLevel | None = RiskLevel.MEDIUM,
        confirm_at_reversibility: Reversibility | None = Reversibility.IRREVERSIBLE,
        deny_at_risk: RiskLevel | None = None,
        deny_at_reversibility: Reversibility | None = None,
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

        A ``deny`` threshold below its matching ``confirm`` threshold is
        accepted rather than rejected: the combination is still a maximum, so
        the result is a policy that denies where it would otherwise have asked —
        strictly safer, and refusing it would be this contract deciding how
        cautious its user is allowed to be.
        """
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

    def _grounds(self, tool: ToolDefinition) -> list[tuple[PermissionOutcome, str]]:
        """Every clause that fires for ``tool``, in table order."""
        return [(rule.outcome, rule.because(tool)) for rule in self._rules if rule.applies(tool)]

    def _outcome_for(self, tool: ToolDefinition) -> PermissionOutcome:
        """The most restrictive outcome this policy's rules reach for ``tool``."""
        grounds = self._grounds(tool)
        return max((outcome for outcome, _ in grounds), default=PermissionOutcome.ALLOW)

    async def decide(self, request: ActionRequest) -> PermissionRuling:
        """Rule on ``request`` by the table in the class docstring.

        Reads only ``request.tool``. ``parameters`` is carried on the request
        for the invocation contract's future per-call gating (ADR-0021 §3) and
        no rule here consults it, so nothing derived from a payload reaches the
        ``reason`` a user is shown.

        Returns:
            The ruling. ``authorised_by`` is always unset: standing grants are
            deferred (ADR-0021 §6), so this policy has no authorisation source
            and may not invent one.
        """
        tool = request.tool
        grounds = self._grounds(tool)
        if not grounds:
            return PermissionRuling(
                outcome=PermissionOutcome.ALLOW,
                reason=(
                    f"no rule applies: {tool.risk_level} risk, {tool.reversibility}, "
                    f"discloses nothing off-device, at a {tool.cost.basis} cost"
                ),
            )
        outcome = max(ruled for ruled, _ in grounds)
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
