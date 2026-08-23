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

from dataclasses import dataclass
from itertools import combinations, permutations
from typing import TYPE_CHECKING

import pytest
from permission_builders import action, decision, ruling, tool

from ai_assistant.core.types import (
    BoundAccount,
    CostBasis,
    DataTier,
    EgressBinding,
    OriginUnrecordedBinding,
    PermissionOutcome,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import ActionPolicy
    from ai_assistant.core.types import ActionRequest, PermissionDecision, PermissionRuling

#: Severity ladders, least severe first.
_RISK_LADDER = (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL)

_REVERSIBILITY_LADDER = (
    Reversibility.REVERSIBLE,
    Reversibility.RECOVERABLE,
    Reversibility.IRREVERSIBLE,
)

#: Every reach a tool can declare — all eight subsets of the three tiers.
#: "Widening ``discloses``" is inclusion, which is a *partial* order rather than
#: a chain, so a single ladder would visit three of the nineteen strict-superset
#: pairs and accept a policy that relaxed on any of the other sixteen.
_REACHES = [
    tiers
    for size in range(4)
    for tiers in combinations((DataTier.SECRET, DataTier.PERSONAL, DataTier.OPERATIONAL), size)
]

#: Every non-empty reach. The floor is over *non-emptiness*, not over a list of
#: tiers: ``OPERATIONAL`` is the tier a tool assigns to a disclosure it
#: considers unremarkable, so exempting it would let the declaration decide
#: whether it gets gated — the self-certifying fast path ADR-0016 §3 refused.
_DISCLOSING = [tiers for tiers in _REACHES if tiers]

#: Cost is carried as a *context* the comparisons hold fixed, not as a severity
#: axis. ADR-0021 §5 states monotonicity over risk, reversibility and
#: disclosure only; ``UNKNOWN`` is an absence of information the policy must
#: fail closed on, which is a floor rather than a rung.
_COST_BASES = (CostBasis.FREE, CostBasis.UNKNOWN)


def _name_tiers(tiers: tuple[DataTier, ...]) -> str:
    """Name a parametrised case after the tiers it discloses."""
    return "+".join(tiers) or "nothing"


#: The three members both binding classes carry, so every subject below differs from
#: its twin in exactly one thing. The least that makes a well-formed binding — no
#: described span, one account, one endpoint — which keeps it constructible over
#: ``action()``'s empty ``parameters``. An empty description is not a non-egress
#: marker: the binding still names an account and still derives a non-empty canonical
#: set (ADR-0148 §2's third clause), and ``egress_binding is None`` is the
#: discriminator (ADR-0178 §4).
_SHARED_MEMBERS: dict[str, object] = {
    "spans": (),
    "account": BoundAccount(identity="work@example.com", reference="conn-0001"),
    "transport_endpoint": "test://endpoint/one",
}


def _planned_over_external(*, marked: bool) -> EgressBinding:
    """A whole binding differing from its twin in ``planned_with_external_content`` alone.

    Built here rather than in ``permission_builders`` because only this suite rules
    over it: ADR-0181 §5's obligation is the ``ActionPolicy`` contract's, and the
    trail's suite has no clause that reads the field. Everything else is
    :data:`_SHARED_MEMBERS`, which leaves nothing but this field for a refusal to be
    about.
    """
    return EgressBinding(**_SHARED_MEMBERS, planned_with_external_content=marked)  # type: ignore[arg-type]  # heterogeneous shared members


def _origin_unrecorded() -> OriginUnrecordedBinding:
    """The pre-ADR-0181 binding, over the exact members its twin above carries.

    Built directly, because ADR-0184 §4 leaves no producer that can make one: a
    request cannot carry the shape, ``from_request`` has no route to it, and
    ``AuditTrail.record`` refuses it outright. What a suite may do is what a **store
    decoding a row** does, which is this.

    Sharing ``_SHARED_MEMBERS`` with :func:`_planned_over_external` is what makes the
    boundary case sharp: the two subjects differ in their *class* and in nothing
    else, so a policy refusing the legacy one on some unrelated ground would fail
    the pair rather than pass the clause.
    """
    return OriginUnrecordedBinding(**_SHARED_MEMBERS)  # type: ignore[arg-type]  # heterogeneous shared members


def _confirmed_with(binding: EgressBinding | OriginUnrecordedBinding) -> PermissionDecision:
    """A recorded ``CONFIRM`` carrying ``binding``, whichever class it is.

    ``model_copy`` rather than the builder for the legacy arm, and deliberately: the
    builder goes through ``from_request``, which ADR-0184 §4 gives no route to the
    shape. Substituting the field afterwards is precisely the caller ADR-0184 §7's
    floor is written against — one that reached ``resolve`` holding a decision no
    sanctioned path could have produced.
    """
    return decision(
        "d-binding",
        request=action(egress_binding=_planned_over_external(marked=False)),
        ruled=ruling(PermissionOutcome.CONFIRM),
    ).model_copy(update={"egress_binding": binding})


@dataclass(frozen=True)
class _Declaration:
    """One point in the declaration cross-product the monotonicity tests range over."""

    risk: RiskLevel
    reversibility: Reversibility
    discloses: tuple[DataTier, ...]
    cost: CostBasis

    def tool(self) -> ToolDefinition:
        """Build the definition this point describes."""
        return tool(
            risk_level=self.risk,
            reversibility=self.reversibility,
            discloses=self.discloses,
            cost=ToolCost(basis=self.cost),
        )

    def held_equal_to(self, other: _Declaration, *, except_for: str) -> bool:
        """Whether every field but ``except_for`` matches ``other``'s."""
        fields = {"risk", "reversibility", "discloses", "cost"} - {except_for}
        return all(getattr(self, name) == getattr(other, name) for name in fields)

    def outranks(self, other: _Declaration, *, on: str) -> bool:
        """Whether this declaration is strictly more severe than ``other`` on ``on``."""
        if on == "discloses":
            return set(self.discloses) > set(other.discloses)
        mine, theirs = getattr(self, on), getattr(other, on)
        return bool(mine > theirs)

    def __str__(self) -> str:
        """Describe the point in the terms the ADR uses."""
        return (
            f"{self.risk}/{self.reversibility}/discloses {_name_tiers(self.discloses)}"
            f"/{self.cost} cost"
        )


#: The full cross-product: 4 risk levels x 3 reversibility levels x 8 reaches x
#: 2 cost bases. Every combination is representable, because the builder
#: declares every tool side-effecting.
_DECLARATIONS = [
    _Declaration(risk, reversibility, tiers, cost)
    for risk in _RISK_LADDER
    for reversibility in _REVERSIBILITY_LADDER
    for tiers in _REACHES
    for cost in _COST_BASES
]


def _assert_monotone(outcomes: dict[_Declaration, PermissionOutcome], *, axis: str) -> None:
    """Assert no pair differing only on ``axis`` relaxes as that axis rises."""
    for lower, higher in permutations(_DECLARATIONS, 2):
        if not higher.held_equal_to(lower, except_for=axis) or not higher.outranks(lower, on=axis):
            continue
        assert outcomes[higher] >= outcomes[lower], (
            f"raising {axis}: {higher} was ruled {outcomes[higher]}, less restrictive "
            f"than {lower}'s {outcomes[lower]}"
        )


async def _ruling_for(policy: ActionPolicy, request: ActionRequest) -> PermissionRuling:
    """Rule on ``request``, checking the invariants **every** ruling must satisfy.

    Three obligations hold for every call rather than for a representative one,
    and sampling them is how a policy conforms in the cases a suite happens to
    look at and not in the ones it does not:

    * ``decide`` is a function of its argument, so a second call on the same
      request must produce an identical ruling — including ``reason``, which is
      what the user is shown.
    * a fresh ruling may not name an authorisation. ``authorised_by`` is a
      ``str`` a policy could fabricate, and the disclosure floor is written as
      "``ALLOW`` **with ``authorised_by`` unset**" — so a policy inventing a
      pointer for exactly the requests the floor covers would auto-grant a
      disclosure while passing a floor test that only ever saw unauthorised
      rulings.
    * **``decide`` does not mutate the request it is given.** ADR-0021 §3 takes
      away the policy's ability to substitute a subject through its *return
      value* — a ruling has no field naming a tool. The request it was handed is
      the other end of the same concern: ``frozen=True`` refuses
      ``request.parameters = ...`` and not
      ``object.__setattr__(request, "parameters", ...)``, so a policy could rule
      on a benign payload and hand back a request describing a different one,
      which ``from_request`` would then transcribe faithfully.

      Stated as a contract obligation because that is the level it can be held
      at. Nothing *prevents* in-process code from mutating an object it
      legitimately holds — the same limit ADR-0018 §3 accepts when it says
      detachment isolates store state rather than making a caller's copy
      tamper-proof — but a policy that does it is not conforming, and an
      accidental one is caught here rather than in an audit record.

    Routing every ``decide`` in the suite through here is what makes all three
    universal instead of a spot check, at no cost in test bulk.
    """
    untouched = request.model_dump(mode="json")

    ruled = await policy.decide(request)
    again = await policy.decide(request)

    assert ruled == again, f"decide is not a function of its argument: {ruled} then {again}"
    assert ruled.authorised_by is None, (
        f"decide invented an authorisation ({ruled.authorised_by!r}); standing grants are "
        f"deferred, so no policy today has a source for one"
    )
    assert request.model_dump(mode="json") == untouched, (
        "decide mutated the request it was given; the decision would then be "
        "transcribed from an action the policy never ruled on"
    )
    return ruled


class ActionPolicyContract:
    """Behaviour every ``ActionPolicy`` implementation must exhibit."""

    @pytest.fixture
    def policy(self) -> ActionPolicy:
        """Return the policy under test."""
        raise NotImplementedError

    # --- monotonicity in severity ---------------------------------------

    @pytest.fixture
    async def outcomes(self, policy: ActionPolicy) -> dict[_Declaration, PermissionOutcome]:
        """Rule on every declaration in the cross-product, once.

        The three obligations below are each about one axis, and "everything
        else held equal" has to range over more than the benign defaults a
        builder starts from — a policy can be monotone in risk for a harmless
        tool and inverted for a disclosing one. Deciding the product up front is
        what lets each test assert its own axis across the others without three
        separate sweeps.

        **The product covers the four fields the obligations are stated over**
        — risk, reversibility, disclosure reach, and cost as a held-fixed
        context — not every field of a ``ToolDefinition``. A policy keying on
        ``writes``, on ``reads``, or on a ``PER_CALL`` price could still invert
        somewhere this never looks. That is a real limit and it is written down
        rather than papered over: the alternative is a product that multiplies
        with every field the type grows, and ADR-0021 §5 states monotonicity
        over risk, reversibility and disclosure specifically. Widening this is
        cheap if a policy ever keys on more.
        """
        return {
            declared: (await _ruling_for(policy, action(tool=declared.tool()))).outcome
            for declared in _DECLARATIONS
        }

    async def test_raising_risk_never_relaxes_the_outcome(
        self, outcomes: dict[_Declaration, PermissionOutcome]
    ) -> None:
        """A policy may not be more permissive about the more dangerous action.

        This is what rules out the whole class of accidents where a threshold
        comparison is written the wrong way round — including, concretely, the
        ``RiskLevel.CRITICAL < RiskLevel.LOW`` inversion ADR-0016 §2 disarmed on
        the type but which a policy could still reproduce in its own arithmetic.

        Checked across every combination of the other three fields in the
        product (see the ``outcomes`` fixture for what that does and does not
        span), because a policy can be monotone in risk for a benign tool and
        inverted for a disclosing one — and it is the disclosing one that
        matters.
        """
        _assert_monotone(outcomes, axis="risk")

    async def test_raising_irreversibility_never_relaxes_the_outcome(
        self, outcomes: dict[_Declaration, PermissionOutcome]
    ) -> None:
        """The same, over the reversibility scale, across the rest of the product."""
        _assert_monotone(outcomes, axis="reversibility")

    async def test_widening_disclosure_never_relaxes_the_outcome(
        self, outcomes: dict[_Declaration, PermissionOutcome]
    ) -> None:
        """Over the whole inclusion lattice, not one chain through it.

        "Widening ``discloses``" is a *partial* order. A single ladder from
        ``()`` to all three tiers visits three of the nineteen strict-superset
        pairs, so a policy that ruled ``DENY`` for ``(SECRET,)`` and ``CONFIRM``
        for ``(SECRET, PERSONAL)`` — relaxing as disclosure widened — would pass
        it while violating the obligation outright.
        """
        _assert_monotone(outcomes, axis="discloses")

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

        Named here because it is an obligation in its own right, but not *only*
        checked here: ``_ruling_for`` re-decides every request the rest of the
        suite builds, so a policy that varied its answer for low-risk or
        disclosing requests only has nowhere left to hide.
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
        ruled = await _ruling_for(policy, action(tool=tool(discloses=tiers)))

        assert not (ruled.outcome is PermissionOutcome.ALLOW and ruled.authorised_by is None), (
            f"disclosing {tiers} was auto-granted"
        )

    async def test_an_undeclared_cost_is_never_auto_granted(self, policy: ActionPolicy) -> None:
        """ADR-0016 §4 ratified ``UNKNOWN`` as "policy must fail closed"."""
        ruled = await _ruling_for(policy, action(tool=tool(cost=ToolCost(basis=CostBasis.UNKNOWN))))

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

        Checked over every axis the contract varies rather than a sample,
        because the failure it guards against is *selective*: a policy that
        invented a pointer only for ``CRITICAL`` risk, an ``UNKNOWN`` cost or a
        ``SECRET`` disclosure would auto-grant exactly the actions the floors
        exist to catch, while a spot check on a benign request saw nothing.
        (``_ruling_for`` asserts the same thing on every other request the suite
        builds; this test is what states the obligation.)
        """
        varied = (
            [action(tool=tool(risk_level=level)) for level in _RISK_LADDER]
            + [action(tool=tool(reversibility=level)) for level in _REVERSIBILITY_LADDER]
            + [action(tool=tool(discloses=tiers)) for tiers in _REACHES]
            + [
                action(tool=tool(cost=ToolCost(basis=basis)))
                for basis in (CostBasis.FREE, CostBasis.UNKNOWN)
            ]
        )

        for request in varied:
            ruled = await policy.decide(request)

            assert ruled.authorised_by is None, f"invented an authorisation for {request.tool}"

    # --- resolving a confirmation ----------------------------------------

    @pytest.mark.parametrize("outcome", list(PermissionOutcome))
    async def test_a_refusal_is_honoured(
        self, policy: ActionPolicy, outcome: PermissionOutcome
    ) -> None:
        """``approved=False`` must yield ``DENY``, citing no authorisation.

        The single worst failure available to this subsystem is the one it would
        make possible: a user who declines has *decided*, and a policy that could
        turn a refusal into an ``ALLOW`` would make the confirmation prompt
        theatre — at the one moment the user believes they are in control.

        The obligation is *unconditional*, so it is checked against every
        outcome a recorded decision can carry rather than only the ``CONFIRM``
        the flow normally supplies. A policy that honoured "no" for a
        confirmation but returned ``ALLOW`` when handed a prior ``ALLOW`` would
        otherwise conform.
        """
        confirmed = decision("d-1", ruled=ruling(outcome))

        resolved = await policy.resolve(confirmed, approved=False)

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

    # --- ADR-0181 §5: the lineage gate, on each member separately --------------

    async def test_decide_returns_no_allow_on_a_call_planned_over_external_content(
        self, policy: ActionPolicy
    ) -> None:
        """ADR-0181 §5's second and third clauses, §10's fifth: ``decide``'s half.

        The declaration is the *least* severe one this suite can build — ``LOW``
        risk, ``REVERSIBLE``, disclosing nothing, at a known cost — so every other
        clause of every policy here reaches ``ALLOW`` on it. Nothing but the
        binding's ``planned_with_external_content`` can produce the refusal, which
        is what makes this a test of the clause rather than of a threshold.

        ``decide`` holds an ``ActionRequest`` and no ``AuditTrail``, so ADR-0148
        §3's route (a) — a decision of the user about *this* request — is
        unavailable to it by construction, and the obligation is discharged by
        returning no ``ALLOW`` at all. It is **not** a refusal to perform the call:
        ``CONFIRM`` satisfies the clause, and ADR-0181's Alternatives refuse an
        outright ``DENY`` on the ground that a silently declined call teaches the
        user nothing.
        """
        ruled = await policy.decide(action(egress_binding=_planned_over_external(marked=True)))

        assert ruled.outcome is not PermissionOutcome.ALLOW
        assert ruled.authorised_by is None

    async def test_decide_judges_a_call_planned_over_nothing_external_on_the_ordinary_path(
        self, policy: ActionPolicy
    ) -> None:
        """ADR-0181 §10's second clause: the boundary, asserted as well as the subject.

        A request whose binding carries ``False`` is not refused by §5's clause. It
        may still be confirmed or denied by a policy's own rules — the suite fixes a
        shape, not a threshold — so what is asserted is that the *reason* is not this
        one: the same declaration, ruled with the marker set and unset, must not
        produce the same answer for a policy that would otherwise allow it.

        Without this half, a policy returning ``CONFIRM`` for every request would
        pass the case above while reading nothing at all.
        """
        clean = await policy.decide(action(egress_binding=_planned_over_external(marked=False)))
        marked = await policy.decide(action(egress_binding=_planned_over_external(marked=True)))
        unbound = await policy.decide(action())

        assert clean.outcome == unbound.outcome, (
            "a binding carrying False is judged exactly as a call with no binding is"
        )
        if clean.outcome is PermissionOutcome.ALLOW:
            assert marked.outcome is not PermissionOutcome.ALLOW

    async def test_resolve_returns_no_allow_when_a_marked_confirmation_was_declined(
        self, policy: ActionPolicy
    ) -> None:
        """ADR-0181 §5's fourth clause, §10's fifth: ``resolve``'s half.

        Stated over exactly the two facts this member receives — the recorded
        decision and the user's answer — because it holds **no request**. Where
        ``confirmed.egress_binding`` carries the marker, an ``ALLOW`` requires
        ``approved`` to be true; ``approved`` being false yields ``DENY`` as
        ADR-0021 already requires, and this is that obligation asserted on the path
        where the marker is present.

        A suite exercising ``decide`` alone would pass an implementation that
        relaxed the rule here — the path where an approval exists is exactly the one
        route (a) leaves open, and it is the one an implementation is most likely to
        widen by accident.
        """
        marked = decision(
            "d-marked",
            request=action(egress_binding=_planned_over_external(marked=True)),
            ruled=ruling(PermissionOutcome.CONFIRM),
        )

        resolved = await policy.resolve(marked, approved=False)

        assert resolved.outcome is PermissionOutcome.DENY
        assert resolved.authorised_by is None

    async def test_resolve_still_honours_an_approval_of_a_marked_confirmation(
        self, policy: ActionPolicy
    ) -> None:
        """The boundary on ``resolve``, and the failure ADR-0181 §5's sixth clause names.

        The user's answer about *this* call **is** ADR-0148 §3's route (a), the one
        route §5's second clause leaves open, so approving a marked confirmation is
        not refused by anything this ADR adds. An implementation that re-applied
        ``decide``'s clause here would refuse every approval of exactly the calls §6
        exists to put to the user — "the fix a lane would otherwise reach for is to
        stop comparing".

        A policy may still refuse on rules of its own, so what is asserted is that
        the marker alone does not change the answer.
        """
        marked = decision(
            "d-marked",
            request=action(egress_binding=_planned_over_external(marked=True)),
            ruled=ruling(PermissionOutcome.CONFIRM),
        )
        clean = decision(
            "d-clean",
            request=action(egress_binding=_planned_over_external(marked=False)),
            ruled=ruling(PermissionOutcome.CONFIRM),
        )

        answered = await policy.resolve(marked, approved=True)
        baseline = await policy.resolve(clean, approved=True)

        assert answered.outcome is baseline.outcome

    # --- ADR-0184 §7: the floor on a confirmation whose origin was never recorded

    @pytest.mark.parametrize("approved", [True, False])
    async def test_resolve_returns_no_allow_on_a_binding_recording_no_origin(
        self, policy: ActionPolicy, *, approved: bool
    ) -> None:
        """ADR-0184 §7's first clause, §10's eleventh: no ``ALLOW``, whatever was answered.

        Such a decision records a call made before ADR-0181 §3's
        ``planned_with_external_content`` existed, so its origin cannot be
        established at all — §3 forbids a default and §4's second clause forbids a
        seam inventing one, which rules out ``False`` and ``True`` alike — and
        ADR-0181 §5's second clause then leaves no route by which any authorisation
        covers it, the user's own answer included.

        **Parametrised over both answers because that is the whole of the clause.**
        The declining arm is already required by ADR-0021 §3 and would pass on its
        own; it is the approving arm that separates a policy honouring the floor from
        one that treats consent as sufficient. Asserting both is what stops the case
        being satisfied by the pre-existing obligation.

        A **floor rather than a route that exists**: ``AuditTrail.pending_confirmation``
        never offers such a park and ``StepRunner.resume`` refuses one before any
        ruling is sought, so no conforming caller reaches this today. ADR-0021 §5's
        "fail-closed twice over" is why it is stated anyway — a floor is worth having
        because it holds when a route appears, and this one is checkable on any
        implementation without knowing its rules.
        """
        unrecorded = _confirmed_with(_origin_unrecorded())

        resolved = await policy.resolve(unrecorded, approved=approved)

        assert resolved.outcome is not PermissionOutcome.ALLOW
        assert resolved.authorised_by is None

    async def test_resolve_judges_a_whole_binding_on_the_ordinary_path(
        self, policy: ActionPolicy
    ) -> None:
        """ADR-0184 §10's eleventh clause: the boundary, so the floor is not a blanket.

        The two subjects carry the **same** spans, account and transport endpoint and
        differ only in their class, so a policy that refused every egress
        confirmation would pass the case above and fail this one. Without it, "return
        no ``ALLOW`` on a legacy binding" is satisfied by an implementation that
        stopped approving anything with a binding at all — which would refuse exactly
        the calls ADR-0181 §6 exists to put to the user.

        A policy may still decline on rules of its own, so what is asserted is that
        the answer to an ordinary approved confirmation is the answer it gives to any
        approved confirmation, and that the legacy one does not get it.
        """
        whole = _confirmed_with(_planned_over_external(marked=False))
        unrecorded = _confirmed_with(_origin_unrecorded())
        unbound = decision("d-plain", ruled=ruling(PermissionOutcome.CONFIRM))

        ordinary = await policy.resolve(whole, approved=True)
        baseline = await policy.resolve(unbound, approved=True)
        refused = await policy.resolve(unrecorded, approved=True)

        assert ordinary.outcome is baseline.outcome, (
            "a binding whose origin was recorded is judged as any confirmation is"
        )
        if baseline.outcome is PermissionOutcome.ALLOW:
            assert refused.outcome is not PermissionOutcome.ALLOW
