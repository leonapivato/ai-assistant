"""Canonical test doubles for the permission contracts (ADR-0021).

The shared fakes for :class:`~ai_assistant.core.protocols.ActionPolicy` and
:class:`~ai_assistant.core.protocols.AuditTrail`, so a subsystem that gates or
records actions (`orchestration`, and the invocation path when it lands) can
test against real, contract-correct implementations *without importing the
permissions subsystem's internals* (CLAUDE.md golden rule 1).

Both are held to their Protocol's shared conformance suite, which is what stops
a fake drifting from the contract it stands in for.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_assistant.core.errors import DuplicateDecisionError, InvalidResolutionError
from ai_assistant.core.types import (
    CostBasis,
    PermissionOutcome,
    PermissionRuling,
    Reversibility,
    RiskLevel,
)

if TYPE_CHECKING:
    from ai_assistant.core.types import ActionRequest, PermissionDecision

#: Reported when a policy is asked to resolve something nobody was ever shown.
_NOT_A_CONFIRMATION = "fake: the decision resolved was not a CONFIRM, so it authorises nothing"


class FakeActionPolicy:
    """A conservative, monotone ``ActionPolicy`` test double.

    Structurally implements :class:`~ai_assistant.core.protocols.ActionPolicy`.
    Unlike :class:`~ai_assistant.testing.policy.FakeMemoryPolicy` this is not a
    constant-answer fake: a policy that returned a configured outcome regardless
    of the request would satisfy the monotonicity obligation *vacuously* — a
    constant function is monotone — leaving the conformance suite's central
    check with nothing to bite on. So the rules are real, and the two knobs move
    the thresholds rather than replacing the reasoning.

    The rules, combined by taking the **most restrictive** result:

    * ``risk_level`` at or above ``confirm_at`` — ``CONFIRM``.
    * ``IRREVERSIBLE`` — ``CONFIRM``, whatever the risk level says.
    * a non-empty ``discloses`` — ``CONFIRM``. The ADR-0021 §5 floor, over
      *any* tier rather than a list of them.
    * an ``UNKNOWN`` cost — ``CONFIRM``. ADR-0016 §4's fail-closed clause.
    * ``risk_level`` at or above ``deny_at``, when one is configured — ``DENY``.

    Each clause is a monotone step function of one declared field, and the
    maximum of monotone functions is monotone, so no configuration of the knobs
    can produce a non-conforming policy. That is deliberate: a fake configurable
    into violating its own conformance suite is a trap.

    Beyond the contract it records every call to :attr:`requests` and
    :attr:`resolutions`, so a consumer's test can assert *that* the gate was
    consulted and with what.
    """

    def __init__(
        self,
        *,
        confirm_at: RiskLevel | None = RiskLevel.MEDIUM,
        deny_at: RiskLevel | None = None,
    ) -> None:
        """Create the fake policy.

        Args:
            confirm_at: Risk level at or above which an action needs the user's
                confirmation; ``None`` never confirms on risk alone (the floors
                still apply).
            deny_at: Risk level at or above which an action is refused outright;
                ``None`` never denies on risk. Set it to ``RiskLevel.LOW`` for a
                policy that refuses everything.
        """
        self.confirm_at = confirm_at
        self.deny_at = deny_at
        self.requests: list[ActionRequest] = []
        self.resolutions: list[tuple[PermissionDecision, bool]] = []

    async def decide(self, request: ActionRequest) -> PermissionRuling:
        """Rule on ``request`` by the thresholds and floors in the class docstring."""
        self.requests.append(request.model_copy(deep=True))
        tool = request.tool

        grounds: list[tuple[PermissionOutcome, str]] = [
            (PermissionOutcome.ALLOW, f"{tool.risk_level} risk, nothing disclosed off-device")
        ]
        if self.confirm_at is not None and tool.risk_level >= self.confirm_at:
            grounds.append((PermissionOutcome.CONFIRM, f"risk is {tool.risk_level}"))
        if tool.reversibility is Reversibility.IRREVERSIBLE:
            grounds.append((PermissionOutcome.CONFIRM, "the effect cannot be undone"))
        if tool.discloses:
            tiers = ", ".join(tier.value for tier in tool.discloses)
            grounds.append((PermissionOutcome.CONFIRM, f"it may disclose {tiers} data off-device"))
        if tool.cost.basis is CostBasis.UNKNOWN:
            grounds.append((PermissionOutcome.CONFIRM, "its cost is undeclared"))
        if self.deny_at is not None and tool.risk_level >= self.deny_at:
            grounds.append((PermissionOutcome.DENY, f"risk is {tool.risk_level}"))

        outcome = max(outcome for outcome, _ in grounds)
        reasons = [reason for ruled, reason in grounds if ruled is outcome]
        return PermissionRuling(outcome=outcome, reason=f"fake: {'; '.join(reasons)}")

    async def resolve(self, confirmed: PermissionDecision, *, approved: bool) -> PermissionRuling:
        """Turn the user's answer to ``confirmed`` into the ruling that resolves it.

        A refusal is honoured unconditionally, and a ``confirmed`` that was never
        a ``CONFIRM`` cannot mint an authorisation — both obligations of
        ADR-0021 §3 rather than choices this fake makes.
        """
        self.resolutions.append((confirmed.model_copy(deep=True), approved))

        if not approved:
            return PermissionRuling(
                outcome=PermissionOutcome.DENY, reason="fake: the user declined"
            )
        if confirmed.ruling.outcome is not PermissionOutcome.CONFIRM:
            return PermissionRuling(outcome=PermissionOutcome.DENY, reason=_NOT_A_CONFIRMATION)
        return PermissionRuling(
            outcome=PermissionOutcome.ALLOW,
            reason="fake: the user approved the confirmation",
            authorised_by=confirmed.id,
        )


class FakeAuditTrail:
    """A non-persistent, append-only ``AuditTrail`` test double backed by a dict.

    Structurally implements :class:`~ai_assistant.core.protocols.AuditTrail`,
    including the parts that make the trail an *active* participant: write-once
    ids, the resolution invariant, and detachment on both the write and the read
    path.

    :meth:`record` performs no ``await``, which is how the atomicity ADR-0021 §4
    requires is obtained on a single event loop: there is no interleaving point
    between the checks and the append, so two concurrent resolutions of one
    ``CONFIRM`` cannot both observe an unresolved question.
    """

    def __init__(self) -> None:
        """Create an empty trail."""
        self._decisions: dict[str, PermissionDecision] = {}

    async def record(self, decision: PermissionDecision) -> str:
        """Append ``decision`` and return its id.

        Raises:
            DuplicateDecisionError: If the id is already recorded.
            InvalidResolutionError: If ``resolves`` fails the invariant.
        """
        if decision.id in self._decisions:
            msg = (
                f"decision {decision.id!r} is already recorded; the trail is "
                f"append-only, so history cannot be rewritten by replaying a write"
            )
            raise DuplicateDecisionError(msg)
        if decision.resolves is not None:
            self._check_resolution(decision)
        self._decisions[decision.id] = decision.model_copy(deep=True)
        return decision.id

    def _check_resolution(self, decision: PermissionDecision) -> None:
        """Enforce ADR-0021 §1's invariant on a resolving decision.

        Raises:
            InvalidResolutionError: If the referenced decision is absent, was not
                a ``CONFIRM``, is already resolved, describes a different
                subject, postdates the answer, or if the authorisation pointer
                does not match.
        """
        confirmed = self._decisions.get(str(decision.resolves))
        if confirmed is None:
            msg = f"decision {decision.resolves!r} is not recorded, so nothing resolves it"
            raise InvalidResolutionError(msg)
        if confirmed.ruling.outcome is not PermissionOutcome.CONFIRM:
            msg = (
                f"decision {confirmed.id!r} ruled {confirmed.ruling.outcome}, not CONFIRM: "
                f"only a question the user was asked can be answered"
            )
            raise InvalidResolutionError(msg)
        if any(other.resolves == decision.resolves for other in self._decisions.values()):
            msg = (
                f"decision {confirmed.id!r} is already resolved; a confirmation answered "
                f"repeatedly is one where a 'no' can be followed by a 'yes' until one sticks"
            )
            raise InvalidResolutionError(msg)
        if (
            confirmed.tool != decision.tool
            or confirmed.parameters_digest != decision.parameters_digest
            or confirmed.step_id != decision.step_id
        ):
            msg = (
                f"decision {decision.id!r} resolves {confirmed.id!r} but rules on a "
                f"different action; a confirmation must answer the question that was asked"
            )
            raise InvalidResolutionError(msg)
        if decision.decided_at < confirmed.decided_at:
            msg = (
                f"decision {decision.id!r} is timestamped before the confirmation "
                f"{confirmed.id!r} it answers"
            )
            raise InvalidResolutionError(msg)
        self._check_authorisation(decision)

    @staticmethod
    def _check_authorisation(decision: PermissionDecision) -> None:
        """Require a resolving ALLOW to cite its own ``resolves``, and a DENY none.

        Without this the pointer is a string a policy could invent, and ADR-0021
        §5's disclosure floor would be satisfiable by fabrication.

        Raises:
            InvalidResolutionError: If the pointer does not match the outcome.
        """
        authorised_by = decision.ruling.authorised_by
        if decision.ruling.outcome is PermissionOutcome.ALLOW:
            if authorised_by != decision.resolves:
                msg = (
                    f"a resolving ALLOW must rest on the confirmation it answers: "
                    f"authorised_by={authorised_by!r}, resolves={decision.resolves!r}"
                )
                raise InvalidResolutionError(msg)
        elif authorised_by is not None:
            # Unreachable through validated construction — PermissionRuling
            # permits the field only on an ALLOW — and exercised past that guard
            # in tests/permissions/test_fake_audit_trail.py rather than in the
            # shared suite, which should not oblige every implementation to
            # defend against models built outside the type's contract. Kept
            # because the trail must not depend on another type's invariant to
            # hold a safety rule of its own.
            msg = f"a resolving {decision.ruling.outcome} rests on no authorisation"
            raise InvalidResolutionError(msg)

    async def get(self, decision_id: str) -> PermissionDecision | None:
        """Return the decision with ``decision_id`` as a detached snapshot, or ``None``."""
        stored = self._decisions.get(decision_id)
        return None if stored is None else stored.model_copy(deep=True)

    async def recent(self, *, limit: int = 50) -> list[PermissionDecision]:
        """Return up to ``limit`` decisions, newest first, ties broken by id.

        Raises:
            ValueError: If ``limit`` is not strictly positive.
        """
        if limit <= 0:
            msg = f"limit must be strictly positive, got {limit}"
            raise ValueError(msg)
        return [decision.model_copy(deep=True) for decision in self._ordered()[:limit]]

    async def export(self) -> list[PermissionDecision]:
        """Return every recorded decision, in the same order as :meth:`recent`."""
        return [decision.model_copy(deep=True) for decision in self._ordered()]

    async def clear(self) -> int:
        """Delete every decision, returning the number removed."""
        removed = len(self._decisions)
        self._decisions.clear()
        return removed

    def _ordered(self) -> list[PermissionDecision]:
        """Return the stored decisions by ``decided_at`` descending, ``id`` ascending.

        Two passes over a stable sort rather than one composite key, because the
        two halves run in opposite directions and ``datetime`` has no negation.
        """
        by_id = sorted(self._decisions.values(), key=lambda decision: decision.id)
        return sorted(by_id, key=lambda decision: decision.decided_at, reverse=True)


__all__ = ["FakeActionPolicy", "FakeAuditTrail"]
