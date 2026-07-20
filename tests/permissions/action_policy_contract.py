"""Shared conformance suite for the ActionPolicy Protocol (ADR-0021 §5).

Every ``ActionPolicy`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`ActionPolicyContract` and overrides the ``policy`` fixture.

**This suite fixes a shape, not a threshold.** A policy is the *user's*, so the
contract cannot decide "confirm at or above MEDIUM" on their behalf. Within the
floors below a conforming implementation may be arbitrarily permissive — one
returning ``CONFIRM`` for everything and one returning ``ALLOW`` for every
non-disclosing, known-cost tool both pass, and neither is what a user would
want. The suite deliberately cannot tell a good policy from a mediocre one.

What it does guarantee is that the failures which are *not* matters of taste
cannot occur: an inverted comparison, a disclosure auto-granted, a cost nobody
declared treated as free, and a user's refusal converted into an approval.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

from itertools import combinations
from typing import TYPE_CHECKING

import pytest
from permission_builders import action, decision, ruling, tool

from ai_assistant.core.types import (
    CostBasis,
    DataTier,
    PermissionOutcome,
    Reversibility,
    RiskLevel,
    ToolCost,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import ActionPolicy

#: Severity ladders, least severe first. Monotonicity is asserted over every
#: ordered *pair* rather than adjacent rungs only: a policy can be correct
#: between neighbours and still invert across a gap, and the ladders are short
#: enough that the exhaustive check costs nothing.
_RISK_LADDER = (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL)

_REVERSIBILITY_LADDER = (
    Reversibility.REVERSIBLE,
    Reversibility.RECOVERABLE,
    Reversibility.IRREVERSIBLE,
)

#: Widening by inclusion: each rung is a superset of the one before it. The
#: order the tuples are written in does not matter — ``TierReach`` sorts them.
_DISCLOSES_LADDER = (
    (),
    (DataTier.OPERATIONAL,),
    (DataTier.OPERATIONAL, DataTier.PERSONAL),
    (DataTier.OPERATIONAL, DataTier.PERSONAL, DataTier.SECRET),
)

#: Every non-empty reach, including the single-tier ones. The floor is over
#: *non-emptiness*, not over a list of tiers: ``OPERATIONAL`` is the tier a tool
#: assigns to a disclosure it considers unremarkable, so exempting it would let
#: the declaration decide whether it gets gated — the self-certifying fast path
#: ADR-0016 §3 refused.
_DISCLOSING = [
    tiers
    for size in (1, 2, 3)
    for tiers in combinations((DataTier.SECRET, DataTier.PERSONAL, DataTier.OPERATIONAL), size)
]


def _name_tiers(tiers: tuple[DataTier, ...]) -> str:
    """Name a parametrised case after the tiers it discloses."""
    return "+".join(tiers)


class ActionPolicyContract:
    """Behaviour every ``ActionPolicy`` implementation must exhibit."""

    @pytest.fixture
    def policy(self) -> ActionPolicy:
        """Return the policy under test."""
        raise NotImplementedError

    # --- monotonicity in severity ---------------------------------------

    async def test_raising_risk_never_relaxes_the_outcome(self, policy: ActionPolicy) -> None:
        """A policy may not be more permissive about the more dangerous action.

        This is what rules out the whole class of accidents where a threshold
        comparison is written the wrong way round — including, concretely, the
        ``RiskLevel.CRITICAL < RiskLevel.LOW`` inversion ADR-0016 §2 disarmed on
        the type but which a policy could still reproduce in its own arithmetic.
        """
        outcomes = [
            (await policy.decide(action(tool=tool(risk_level=level)))).outcome
            for level in _RISK_LADDER
        ]

        _assert_never_relaxes(outcomes, _RISK_LADDER)

    async def test_raising_irreversibility_never_relaxes_the_outcome(
        self, policy: ActionPolicy
    ) -> None:
        outcomes = [
            (await policy.decide(action(tool=tool(reversibility=level)))).outcome
            for level in _REVERSIBILITY_LADDER
        ]

        _assert_never_relaxes(outcomes, _REVERSIBILITY_LADDER)

    async def test_widening_disclosure_never_relaxes_the_outcome(
        self, policy: ActionPolicy
    ) -> None:
        """Each rung discloses a superset of the one before it."""
        outcomes = [
            (await policy.decide(action(tool=tool(discloses=tiers)))).outcome
            for tiers in _DISCLOSES_LADDER
        ]

        _assert_never_relaxes(outcomes, _DISCLOSES_LADDER)

    async def test_deciding_the_same_request_twice_agrees_with_itself(
        self, policy: ActionPolicy
    ) -> None:
        """``decide`` is a function of its argument.

        Not decoration: monotonicity is a statement about *pairs* of requests,
        so a policy whose answer drifted between two calls on identical input
        would make every comparison above unfalsifiable rather than merely
        flaky. It is also what the ADR buys by keeping the clock and the id
        minting out of the policy — there is nothing left for an answer to
        legitimately depend on but the request.

        The whole ruling is compared, not just the outcome: ``reason`` is shown
        to the user, so a policy deriving it from a clock, a counter or a random
        source is one whose prompts differ between two identical questions, and
        an outcome-only assertion would call that conforming.
        """
        request = action(tool=tool(risk_level=RiskLevel.HIGH))

        first = await policy.decide(request)
        second = await policy.decide(request)

        assert first == second, "the whole ruling, not just the outcome, is the answer"

    # --- the two floors --------------------------------------------------

    @pytest.mark.parametrize("tiers", _DISCLOSING, ids=_name_tiers)
    async def test_off_device_disclosure_is_never_auto_granted(
        self, policy: ActionPolicy, tiers: tuple[DataTier, ...]
    ) -> None:
        """A disclosing tool may not be ``ALLOW``ed by the policy's own reasoning.

        The enforceable form of ADR-0016 §2's two-field rule. It has to be a
        floor rather than something weaker, because nothing weaker is checkable:
        a function that ignores an input is monotone in that input, so no
        monotonicity requirement can ever force ``discloses`` to be read.

        The floor is written against *auto*-granting rather than against the
        outcome, which is what keeps the standing-grant relief valve reachable
        without amending the rule. Today nothing populates ``authorised_by`` on
        a fresh ruling, so in practice this is absolute.
        """
        ruled = await policy.decide(action(tool=tool(discloses=tiers)))

        assert not (ruled.outcome is PermissionOutcome.ALLOW and ruled.authorised_by is None), (
            f"disclosing {tiers} was auto-granted"
        )

    async def test_an_undeclared_cost_is_never_auto_granted(self, policy: ActionPolicy) -> None:
        """ADR-0016 §4 ratified ``UNKNOWN`` as "policy must fail closed"."""
        ruled = await policy.decide(action(tool=tool(cost=ToolCost(basis=CostBasis.UNKNOWN))))

        assert not (ruled.outcome is PermissionOutcome.ALLOW and ruled.authorised_by is None)

    async def test_deciding_a_fresh_request_invents_no_authorisation(
        self, policy: ActionPolicy
    ) -> None:
        """``decide`` may not name an authorisation, so the floor cannot be written around.

        A ``str`` field naming an authorisation is one a policy could fabricate,
        which would make the disclosure floor satisfiable by writing something
        in a box. Standing grants are deferred, so *every* policy today is one
        constructed with no authorisation source — and this is checkable against
        any of them.
        """
        for tiers in ((), (DataTier.PERSONAL,)):
            ruled = await policy.decide(action(tool=tool(discloses=tiers)))

            assert ruled.authorised_by is None

    # --- resolving a confirmation ----------------------------------------

    async def test_a_refusal_is_honoured(self, policy: ActionPolicy) -> None:
        """``approved=False`` must yield ``DENY``, citing no authorisation.

        The single worst failure available to this subsystem is the one it would
        make possible: a user who declines has *decided*, and a policy that could
        turn a refusal into an ``ALLOW`` would make the confirmation prompt
        theatre — at the one moment the user believes they are in control.
        """
        resolved = await policy.resolve(decision(), approved=False)

        assert resolved.outcome is PermissionOutcome.DENY
        assert resolved.authorised_by is None

    async def test_an_approval_yields_allow_or_deny_and_never_another_question(
        self, policy: ActionPolicy
    ) -> None:
        """A policy may refuse a confirmation it no longer accepts, but may not re-ask.

        Refusing is legitimate — a confirmation answered long after it was asked
        need not be rubber-stamped. Returning ``CONFIRM`` is not: a resolving
        decision may not itself be a ``CONFIRM``, so it would be a ruling that
        is conforming and unrecordable.
        """
        resolved = await policy.resolve(decision(), approved=True)

        assert resolved.outcome in (PermissionOutcome.ALLOW, PermissionOutcome.DENY)

    async def test_an_approving_allow_rests_on_the_confirmation_it_answers(
        self, policy: ActionPolicy
    ) -> None:
        """The one path that may set ``authorised_by`` sets it to something verifiable.

        A user answering a confirmation *is* the user decision the disclosure
        floor asks for, and it is already on the record — so the pointer is
        covered by the invariant ``AuditTrail.record`` enforces rather than taken
        on trust. A resolving ``DENY`` leaves it unset, because a refusal rests
        on no authorisation.
        """
        confirmed = decision("d-confirm")

        resolved = await policy.resolve(confirmed, approved=True)

        if resolved.outcome is PermissionOutcome.ALLOW:
            assert resolved.authorised_by == confirmed.id
        else:
            assert resolved.authorised_by is None

    @pytest.mark.parametrize("outcome", [PermissionOutcome.ALLOW, PermissionOutcome.DENY])
    async def test_resolving_a_decision_that_was_never_a_confirmation_grants_nothing(
        self, policy: ActionPolicy, outcome: PermissionOutcome
    ) -> None:
        """``resolve`` cannot mint an authorisation out of a decision nobody was shown.

        Otherwise the method becomes a second, unguarded route to ``ALLOW``:
        hand it any recorded decision, claim the user approved, and receive an
        authorisation for a question that was never asked.
        """
        never_asked = decision("d-1", ruled=ruling(outcome))

        resolved = await policy.resolve(never_asked, approved=True)

        assert resolved.outcome is not PermissionOutcome.ALLOW


def _assert_never_relaxes(outcomes: list[PermissionOutcome], ladder: tuple[object, ...]) -> None:
    """Assert ``outcomes`` never falls as the corresponding ladder rung rises."""
    for (lower, less_severe), (higher, more_severe) in combinations(
        zip(outcomes, ladder, strict=True), 2
    ):
        assert higher >= lower, (
            f"{more_severe} was ruled {higher}, less restrictive than {less_severe}'s {lower}"
        )
