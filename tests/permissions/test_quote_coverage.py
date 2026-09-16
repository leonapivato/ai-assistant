"""ADR-0266 §7's evidence route, over the quotes ADR-0267 supplies (§11 arms 5, 6).

The half of condition 6 that had no operand until now. ADR-0266 §11 landed the route
with its last two conjuncts unreachable — *"this tree holds no quotes"* — and assigned
the carrier, the producer and the read to ADR-0267; this module is the read's own
arms, driven over quotes **constructed** on a goal, no mint existing in this lane's
base (ADR-0267 §11), which is why it does not wait on Q2.

**What is here.** Arm 5 whole — the comparison end to end, the digest, the Sunday
re-quote, and the quote bound to the **act** and never to the declaration — and arm
6's policy limbs: the seam answers in the goal's order, an empty tuple is an absence,
and **a fault is not an absence**. Arm 6's conformance and durable-store limbs are
``tests/planning/test_fake_goal_quotes.py``'s, because their subject is the seam.

**What is deliberately not here.** The **mint** (arm 4) is Q2's, in ``orchestration``.
The row's record of the figure and its projection (arm 7) ride ADR-0254 §20's Lane 2
with the population — at every tree ADR-0267's own lanes leave, ``Authorization.quoted``
is ``None`` on every row, so an arm over one would assert against a builder that
returns none.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final

import pytest
from authorization_builders import (
    AT,
    GOAL,
    SITE,
    TOOL,
    binding,
    request,
)
from test_goal_authorization_policy import defects, grants, live, seam

from ai_assistant.core.types import (
    ActionQuote,
    BoundKind,
    PermissionOutcome,
    StepOutputRef,
    ToolDefinition,
)
from ai_assistant.permissions._coverage import (
    CoverageFailure,
    _met_through_evidence,
    coverage_subject,
    covers_arguments,
)
from ai_assistant.permissions.policy import ThresholdActionPolicy
from ai_assistant.testing import (
    FakeGoalQuotes,
    coverage_member,
    money_bound,
    period_bound,
    terms_bound,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import ActionRequest, Authorization

#: The act every priced call below is an attempt at (ADR-0265 §1).
ACT: Final = "ia1"

#: When a scripted quote was read. **No comparison reads it** (ADR-0267 §1): it is
#: provenance, and §6 is explicit that nothing computes a validity window from it.
READ_AT: Final = datetime(2026, 9, 13, 8, 0, tzinfo=UTC)


def quote_for(
    call: ActionRequest, *, amount: str = "120", currency: str = "EUR", act: str = ACT
) -> ActionQuote:
    """A quote for ``act`` taken over **this call's own arguments**.

    ``arguments_digest`` is ``call.parameters_digest`` — the request's own property,
    *"never a value computed a second way"* (ADR-0267 §1). Taking it from the call
    rather than writing a literal is what makes the negative cases below real: a case
    that varies an argument gets a different digest for free, rather than needing a
    second canonicalisation written in test code.
    """
    return ActionQuote(
        intended_action=act,
        arguments_digest=call.parameters_digest,
        amount=Decimal(amount),
        currency=currency,
        plan="p1",
        read_from=StepOutputRef(step="s1", field="price"),
        read_at=READ_AT,
    )


def ceiling(amount: str = "150", *, currency: str = "EUR") -> Authorization:
    """A live row bounding this goal's spend at ``amount`` in ``currency``.

    ``live()``'s ``TERMS`` member for the site rides with it, because condition 6 is
    over **every** user-facing argument and a booking call carries ``site`` as an
    ordinary argument as well as a destination.
    """
    return live(
        tool=UNPRICED_TOOL,
        coverage=(coverage_member(BoundKind.MONEY, bound=money_bound(amount, currency=currency)),),
    )


def priced(**parameters: object) -> ActionRequest:
    """The booking call, carrying the act it is an attempt at and no price argument.

    **It carries no ``amount``**, and that is the case this decision is actually
    about: ADR-0266 §7 makes the quote the *primary* proof, the argument route an
    additional safeguard, and *"a declaration declaring no amount keeps its ceiling
    proved against the quote"*. So the price here is the provider's own output,
    reached through the quote, and not a number the plan wrote into the call.
    """
    return request(binding(SITE), act=ACT, tool=UNPRICED_TOOL, **parameters)  # type: ignore[arg-type]


#: :data:`TOOL` with **no** bounded argument at ``MONEY``.
#:
#: ADR-0266 §7: *"Declaring a money argument is a safeguard and not a requirement …
#: so a declaration omitting one keeps its ceiling proved against the quote and
#: forgoes only the second comparison"*. Every case below is about the evidence route,
#: and leaving the canonical declaration's ``amount`` in would make each of them also
#: about the argument route's ``OMITTED`` defect.
UNPRICED_TOOL: Final[ToolDefinition] = ToolDefinition.model_validate(
    {
        **TOOL.model_dump(),
        "bounded_arguments": tuple(
            one
            for one in TOOL.model_dump()["bounded_arguments"]
            if one["kind"] is not BoundKind.MONEY
        ),
    }
)

#: A second declaration, differing from :data:`UNPRICED_TOOL` in its ``id`` alone.
#:
#: ADR-0267 §1: *"a quote is bound to the act and to the arguments, and never to the
#: declaration that produced it"* — the owner's own case reads a price from an
#: availability tool and performs the act at a **booking** tool.
OTHER_TOOL: Final[ToolDefinition] = ToolDefinition.model_validate(
    {**UNPRICED_TOOL.model_dump(), "id": "availability"}
)


def covered(row: Authorization, call: ActionRequest, quotes: Sequence[ActionQuote]) -> bool:
    """Whether condition 6 holds over this pair and these quotes (ADR-0266 §7)."""
    return covers_arguments(row.coverage, coverage_subject(call), quotes)


def policy_with(
    row: Authorization, quotes: FakeGoalQuotes | None
) -> tuple[ThresholdActionPolicy, FakeGoalQuotes | None]:
    """The policy over ``row``, holding ``quotes`` as its ``GoalQuotes`` (§5)."""
    return (
        ThresholdActionPolicy(
            grants=grants(),
            authorizations=seam(row),
            quotes=quotes,
        ),
        quotes,
    )


# --- arm 5: the comparison, end to end ----------------------------------------


class TestTheGoverningQuoteIsComparedAgainstTheMember:
    """ADR-0267 §11 arm 5, and ADR-0266 §7's last two conjuncts given their operand."""

    def test_a_quote_inside_the_ceiling_covers_the_request(self) -> None:
        """§7: the governing quote's amount satisfies the member, and the request is
        covered — the first arm in this corpus where a ``MONEY`` member is met at all."""
        call = priced()
        assert covered(ceiling("150"), call, [quote_for(call, amount="120")])

    def test_zero_is_a_price_and_covers_under_any_ceiling_of_its_currency(self) -> None:
        """§11 arm 1: *"``Decimal("0")`` constructs, covers under any ceiling of its
        currency, and is no absence"*.

        The arm most likely to regress silently, and the reason it is stated: a
        reading written as ``if amount:`` or ``if not quote.amount:`` treats a free act
        as *no quote at all*, which is the fail-**closed** direction and so would never
        show up as a call that was wrongly authorised — only as one that asks forever
        for a reason nobody can find. Driven at two ceilings, because *"any ceiling of
        its currency"* includes the degenerate one.
        """
        call = priced()
        free = quote_for(call, amount="0")
        assert free.amount == Decimal("0")
        assert covered(ceiling("150"), call, [free])
        assert covered(ceiling("0"), call, [free]), "a zero ceiling admits a zero charge"
        assert not covered(ceiling("150", currency="USD"), call, [free]), (
            "and zero is still denominated: a free act in one currency proves nothing "
            "about a ceiling in another"
        )

    def test_a_quote_above_the_ceiling_does_not(self) -> None:
        """§7 and ADR-0254 §4: *at most* the maximum, and ``170`` is not."""
        call = priced()
        assert not covered(ceiling("150"), call, [quote_for(call, amount="170")])
        assert defects(ceiling("150"), call, [quote_for(call, amount="170")]) == {
            ("money", CoverageFailure.UNPROVED)
        }

    def test_a_quote_in_another_currency_does_not(self) -> None:
        """§7: the currency conjunct is taken **at the quote's own currency**.

        And it is compared **byte for byte** (ADR-0254 §4), which is why
        :class:`~ai_assistant.core.types.ActionQuote` shape-checks the code: a quote
        minted at ``"usd"`` would match no bound's ``"USD"`` ever, so it would cover
        nothing while looking like a price that had been read.
        """
        call = priced()
        assert not covered(ceiling("150"), call, [quote_for(call, currency="USD")])

    def test_no_quote_for_that_action_covers_nothing_however_small_the_arguments(
        self,
    ) -> None:
        """§7: *"Where no quote governs … the member is not met"* — and the act asks.

        Driven over a call whose declared arguments are as modest as they come, so
        the refusal is about the absence of a proof and never about a value.
        """
        call = priced(nights=1)
        assert not covered(ceiling("150"), call, [])

    def test_a_request_carrying_no_intended_action_is_covered_by_no_quote(self) -> None:
        """§7: *"A request carrying ``None`` is met by the evidence route in no case"*.

        Asserted with a quote **present and well inside the ceiling**, so the refusal
        is the missing act and not a missing operand.
        """
        actless = request(binding(SITE), tool=UNPRICED_TOOL)
        assert actless.intended_action is None
        assert not covered(ceiling("150"), actless, [quote_for(actless, amount="1")])

    def test_a_quote_for_another_action_is_not_this_requests(self) -> None:
        """§5: the seam is keyed on the act, and §7 selects among *that* act's quotes.

        A quote read for a different act covers this one through no route: the whole
        of the proof is that the amount was quoted **for that act**. Asserted as a
        property of the **reading** rather than of the seam's filter alone, because
        §7's selection is over the quotes *"that name that action"* and a reading
        resting entirely on a caller having keyed correctly would cover this.
        """
        call = priced()
        assert not covered(ceiling("150"), call, [quote_for(call, act="ia2")])

    @pytest.mark.parametrize("kind", [BoundKind.PERIOD, BoundKind.TERMS])
    def test_a_member_of_any_other_kind_is_met_by_this_route_in_no_case(
        self, kind: BoundKind
    ) -> None:
        """§7: *"No member of any other kind is met by this route in any case"*.

        A quote states a price and carries no other value, so there is nothing for a
        ``PERIOD`` or a ``TERMS`` member to be compared against. **Asserted of the
        route predicate itself** rather than through the defects: a member of either
        kind is unmet in this tree for its own reasons too, so a reading through the
        ruling would pass however the evidence route behaved.
        """
        call = priced()
        member = coverage_member(
            kind,
            bound=(
                terms_bound("flexible")
                if kind is BoundKind.TERMS
                else period_bound(starts_at=AT, ends_at=AT + timedelta(hours=12))
            ),
        )
        assert not _met_through_evidence(member, coverage_subject(call), [quote_for(call)])


class TestTheArgumentsAreTheOnesQuoted:
    """Arm 5's digest half: *"The arguments are the ones quoted"*."""

    @pytest.mark.parametrize(
        ("label", "acting"),
        [
            ("one extra", {"nights": 1, "breakfast": True}),
            ("one missing", {}),
            ("one different", {"nights": 2}),
        ],
    )
    def test_a_call_differing_in_any_argument_is_covered_by_no_quote(
        self, label: str, acting: dict[str, object]
    ) -> None:
        """§1: *"a quoting call and an acting call differing in **any** key … are
        covered by no quote, and ask"* — though the price is unchanged.

        That is the owner's *"re-quote or ask"* read at the one place it can be
        enforced mechanically, and it is enforced by comparing two values of one
        property rather than by a second canonicalisation: the quote carries the
        quoting request's ``parameters_digest`` and the subject carries this one's.
        """
        quoting = priced(nights=1)
        quote = quote_for(quoting, amount="120")
        assert covered(ceiling("150"), quoting, [quote]), "the control: the quoted call"

        call = priced(**acting)
        assert call.parameters_digest != quoting.parameters_digest, label
        assert not covered(ceiling("150"), call, [quote]), label


class TestTheSundayRequoteGoverns:
    """Arm 5: *"The Sunday re-quote governs"*, and the earlier quote never revives."""

    def test_the_later_quote_governs_and_the_earlier_one_never_revives(self) -> None:
        """§2's order and §7's *"An earlier quote is consulted in no case"*.

        A Saturday reading at ``120`` and a Sunday one at ``135`` for one act: the
        **Sunday** arguments are covered, and a request returning to the **Saturday**
        arguments is **not** — rather than reviving a reading the re-quote displaced.
        The ceiling admits both amounts, so what refuses the Saturday call is the
        position of its quote in the tuple and nothing about the number.
        """
        saturday = priced(nights=1)
        sunday = priced(nights=2)
        held = [quote_for(saturday, amount="120"), quote_for(sunday, amount="135")]

        assert covered(ceiling("150"), sunday, held)
        assert not covered(ceiling("150"), saturday, held)

    def test_the_last_member_is_taken_and_not_a_scan_for_a_matching_digest(self) -> None:
        """§5: *"``permissions`` takes the last member of what comes back"*.

        The sharpest statement of the same rule: with the Saturday reading **last**,
        the Saturday call is covered and the Sunday one is not — so an implementation
        that scanned the tuple for a quote whose digest matched would cover both, and
        this pair of arms is what tells the two apart.
        """
        saturday = priced(nights=1)
        sunday = priced(nights=2)
        held = [quote_for(sunday, amount="135"), quote_for(saturday, amount="120")]

        assert covered(ceiling("150"), saturday, held)
        assert not covered(ceiling("150"), sunday, held)


class TestAQuoteIsBoundToTheActAndNotToTheDeclaration:
    """Arm 5's last limb, and §1's *"never to the declaration that produced it"*."""

    def test_a_quote_read_at_one_declaration_covers_the_act_at_another(self) -> None:
        """§1: the owner's **check-then-book** case, asserted rather than left to chance.

        A price is read from an *availability* tool's output and the act is performed
        at a **booking** tool; a same-declaration rule would refuse every act this
        mechanism exists to authorise. What binds the number to the act is the
        totality obligation on the declaration together with the digest, which pins
        the arguments — and §10 books the residual that leaves.

        The two declarations differ in their ``id`` alone, because ADR-0254 §3's
        condition 3 compares the request's declaration against the **row's** by value:
        a case varying anything else would fail that condition instead and prove
        nothing about this one.
        """
        checking = request(binding(SITE), act=ACT, tool=OTHER_TOOL, nights=1)
        booking_call = request(binding(SITE), act=ACT, tool=UNPRICED_TOOL, nights=1)
        assert checking.tool.id != booking_call.tool.id
        assert checking.parameters_digest == booking_call.parameters_digest

        read_at_the_other = quote_for(checking, amount="120")
        assert covered(ceiling("150"), booking_call, [read_at_the_other])


# --- arm 6: the seam, and a fault is not an absence ---------------------------


class TestTheSeamAndTheFaultClause:
    """Arm 6's policy limbs (ADR-0267 §5, ADR-0266 §7)."""

    async def test_a_quote_inside_the_ceiling_reaches_a_standing_allow(self) -> None:
        """§7 end to end through :meth:`ThresholdActionPolicy.decide`.

        The route-(d) ``ALLOW`` a stated ceiling could not reach before this lane:
        with the goal holding a quote for the request's act, over the request's own
        arguments and inside the bound, the ceiling is proved and the standing route
        answers. **The seam is read exactly once.**
        """
        call = priced()
        held = FakeGoalQuotes([quote_for(call, amount="120")], goal=GOAL)
        gate, quotes = policy_with(ceiling("150"), held)

        ruling = await gate.decide(call)

        assert ruling.outcome is PermissionOutcome.ALLOW
        assert ruling.authorised_goal == GOAL
        assert quotes is not None
        assert quotes.call_count == 1, "at most one durable read per seam per ruling"

    async def test_a_zero_quote_reaches_a_standing_allow(self) -> None:
        """Arm 1's covering limb, through the policy rather than the comparison.

        *"Zero is a price … and is no absence"*: a free act proved against a stated
        ceiling reaches route (d) exactly as a priced one does, and an implementation
        reading ``Decimal("0")`` as *no quote* would ask here instead — a defect that
        fails safe and therefore hides.
        """
        call = priced()
        held = FakeGoalQuotes([quote_for(call, amount="0")], goal=GOAL)
        gate, _ = policy_with(ceiling("150"), held)

        ruling = await gate.decide(call)

        assert ruling.outcome is PermissionOutcome.ALLOW

    async def test_a_quote_above_the_ceiling_asks(self) -> None:
        """The control beside it: the same wiring, a price the act did not bound."""
        call = priced()
        held = FakeGoalQuotes([quote_for(call, amount="170")], goal=GOAL)
        gate, _ = policy_with(ceiling("150"), held)

        ruling = await gate.decide(call)

        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert "states a limit nothing about this call proves: money" in ruling.reason

    async def test_a_fault_leaves_the_request_uncovered_with_the_fault_reported(
        self,
    ) -> None:
        """§5: *"A fault is never an absence"*, against a control returning empty.

        A ``for_action`` that raises leaves the request **not covered**: ADR-0254 §6's
        bar is taken, **no standing route is taken at all**, and the ruling is the
        ``CONFIRM`` the request would have drawn had the user authorised nothing. The
        control — a seam answering **empty** — is uncovered too, but for the *other*
        reason, and the ruling says so: it carries §4's account of the coverage
        failure, while the fault carries none, because *"a store fault is an
        operator's fact and not something to put in front of someone deciding about a
        call"*.
        """
        call = priced()
        empty = FakeGoalQuotes([], goal=GOAL)
        gate, _ = policy_with(ceiling("150"), empty)
        absent = await gate.decide(call)
        assert absent.outcome is PermissionOutcome.CONFIRM
        assert "states a limit nothing about this call proves: money" in absent.reason

        faulting = FakeGoalQuotes([quote_for(call, amount="120")], goal=GOAL)
        faulting.fail_for_action()
        gate, _ = policy_with(ceiling("150"), faulting)

        ruling = await gate.decide(call)

        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert "states a limit nothing about this call proves" not in ruling.reason, (
            "a fault carries no account of a coverage failure"
        )

    async def test_a_fault_never_falls_through_to_the_argument_route(self) -> None:
        """§5: *"no lane falls through to the argument route"* on a fault.

        Driven at the declaration that **does** declare an amount, and over a call
        carrying one comfortably inside the ceiling — which is exactly the shape an
        implementation reading a fault as an empty tuple would let through, because
        the argument route would then meet the member on its own. *"A filter is not a
        charge"* (ADR-0266 §7).
        """
        call = request(binding(SITE), act=ACT, amount="50", currency="GBP")
        faulting = FakeGoalQuotes([], goal=GOAL)
        faulting.fail_for_action()
        row = live(coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("60")),))
        gate, _ = policy_with(row, faulting)

        ruling = await gate.decide(call)

        assert ruling.outcome is PermissionOutcome.CONFIRM

    async def test_a_policy_holding_no_quote_seam_leaves_every_money_member_unmet(
        self,
    ) -> None:
        """§11: every tree either lane leaves is conforming and **fail-closed**.

        A policy constructed with no ``GoalQuotes`` is exactly the tree ADR-0266 §11
        described — every ``MONEY`` member unmet, every act carrying a stated ceiling
        asking — and it reads this seam zero times, there being none to read.
        """
        call = priced()
        gate, quotes = policy_with(ceiling("150"), None)
        assert quotes is None

        ruling = await gate.decide(call)

        assert ruling.outcome is PermissionOutcome.CONFIRM

    async def test_the_seam_is_read_zero_times_where_no_money_member_could_need_it(
        self,
    ) -> None:
        """§5: the evidence route meets a member of no other kind, so a row carrying
        no ``MONEY`` member spends no read at all.

        ``_DISCLOSURE_FLOOR``'s *"at most one durable read per seam per ruling and
        never a cached answer"* read onto the seam this decision adds: a read that
        could change no answer is one this policy does not take.
        """
        call = priced()
        held = FakeGoalQuotes([quote_for(call, amount="120")], goal=GOAL)
        gate, quotes = policy_with(live(tool=UNPRICED_TOOL), held)

        ruling = await gate.decide(call)

        assert ruling.outcome is PermissionOutcome.ALLOW
        assert quotes is not None
        assert quotes.call_count == 0

    async def test_the_seam_is_read_zero_times_for_a_request_carrying_no_act(
        self,
    ) -> None:
        """§7: a request carrying no ``intended_action`` is met by this route in no
        case, so the policy asks the seam nothing about it."""
        actless = request(binding(SITE), tool=UNPRICED_TOOL)
        held = FakeGoalQuotes([quote_for(actless, amount="120")], goal=GOAL)
        gate, quotes = policy_with(ceiling("150"), held)

        ruling = await gate.decide(actless)

        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert quotes is not None
        assert quotes.call_count == 0

    async def test_the_seam_is_asked_about_this_requests_own_goal_and_act(self) -> None:
        """§5: it is **keyed**, and the two keys are the request's own.

        A seam holding the quote under a **different** goal answers empty, which
        leaves the ceiling proved by nothing — the assertion that the policy passes
        ``request.goal`` rather than something it reconstructed.
        """
        call = priced()
        elsewhere = FakeGoalQuotes([quote_for(call, amount="120")], goal="another-goal")
        gate, _ = policy_with(ceiling("150"), elsewhere)

        ruling = await gate.decide(call)

        assert ruling.outcome is PermissionOutcome.CONFIRM
