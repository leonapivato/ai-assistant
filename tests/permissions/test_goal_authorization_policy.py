"""ADR-0148 §3's route (d), and ADR-0254 §6's argument-authority bar.

`ThresholdActionPolicy`'s half of ADR-0254, which the store's conformance suite
cannot state because no store exhibits how often a policy calls it: the route's
five conditions, the readings §4 fixes over a concrete request, the bar's exact
scope, the total order the four routes answer in, and the **seam-read counts** that
are the whole of what makes "at most one durable read per seam per ruling" a
testable claim.

The arm numbers below are ADR-0254 §20's.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest
from action_policy_contract import ActionPolicyContract
from authorization_builders import (
    ACCOUNT,
    AT,
    DECLARED_TOOL,
    EXPIRES,
    GOAL,
    NOW,
    OTHER_ACCOUNT,
    OTHER_GOAL,
    OTHER_SITE,
    SEARCH_ACCOUNT,
    SEARCH_TOOL,
    SHARED_CLOCK,
    SITE,
    TOOL,
    MovableClock,
    account_member,
    binding,
    member,
    request,
    search_binding,
    search_member,
)

from ai_assistant.core.config import Settings
from ai_assistant.core.logging import configure_logging
from ai_assistant.core.types import (
    AuthorizationDisposition,
    BoundKind,
    CostBasis,
    FrozenDict,
    PermissionOutcome,
    Reversibility,
    RiskLevel,
    SpanCoverage,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.permissions._coverage import (
    CoverageFailure,
    _met_on_argument_route,
    coverage_subject,
    covers_on_argument_route,
    declared_at,
    uncovered,
)
from ai_assistant.permissions.policy import (
    ConfiguredSearchDestination,
    ThresholdActionPolicy,
)
from ai_assistant.testing import (
    FakeGoalAuthorizations,
    FakeRecipientGrants,
    authorization,
    coverage_member,
    money_bound,
    opening_act,
    period_bound,
    recipient_grant,
    terms_bound,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import ActionPolicy
    from ai_assistant.core.types import (
        ActionRequest,
        Authorization,
        CanonicalDestination,
        CoverageMember,
        ValueBound,
    )


def live(
    *, coverage: tuple[CoverageMember, ...] | None = None, site: bool = True, **overrides: object
) -> Authorization:
    """A path-(i) **proposal** the seam below then establishes.

    **The destination-bearing argument is covered too, and that is not a
    convenience.** ADR-0266 §7's condition 6 is over *every* user-facing argument
    of the request, and a booking call carries ``site`` as an ordinary argument as
    well as a destination — so a row carrying no member of its kind covers nothing,
    whatever else holds. Prepending it here is what lets each case below vary the
    member it is actually about. ``site=False`` is the empty-coverage case, where
    the request carries no user-facing argument at all.

    **It is a ``TERMS`` member fixed to the site, and it carries no ``MONEY``
    member** (ADR-0266 §3, §7). A member records what the user stated and never
    which slot it fills, so the site is the *named term* this act fixed, and
    ``AUTHORIZATION_TOOL`` declares ``site`` at ``TERMS`` for the argument route to
    meet it on. A ``MONEY`` member is deliberately **not** here: §7 meets one only
    against a quote for the request's intended action, this tree holds none, so a
    default row carrying one would make every case below draw ``CONFIRM`` for a
    reason none of them is about. The cases that **are** about it are
    :class:`TestAMoneyMemberIsProvedAgainstAQuoteAndNothingElse`.

    The seam seeds through the fake's own write path, which holds a row carrying a
    ``confirmation`` to ``PROPOSED`` — ADR-0254 §1's rule that such a row *"reaches
    every later disposition through ``settle`` alone"*. So a case that wants a live
    record arranges the same two acts production does, rather than writing a state
    the store would refuse.
    """
    members = coverage if coverage is not None else ()
    if site:
        members = (coverage_member(BoundKind.TERMS, fixed=SITE), *members)
    return authorization(coverage=members, **overrides)  # type: ignore[arg-type]  # its own keys


def seam(*rows: Authorization) -> FakeGoalAuthorizations:
    """The policy's query face over ``rows``, on the suite's shared clock.

    Each ``PROPOSED`` row is settled ``ESTABLISHED`` at :data:`AT`, which is the
    answer arriving — the only way a path-(i) row becomes an authority. Rows already
    written ``ESTABLISHED`` (an opening act, a correction) are recorded as they are.
    """
    held = FakeGoalAuthorizations(now=SHARED_CLOCK.reset())
    for row in rows:
        held.hold(row)
        if row.disposition is AuthorizationDisposition.PROPOSED:
            held.settle(row.id, to=AuthorizationDisposition.ESTABLISHED, settled_at=AT)
    return held


def grants(
    *,
    covering: bool = True,
    destinations: tuple[CanonicalDestination, ...] = (),
    expires_at: datetime = EXPIRES + timedelta(days=1),
) -> FakeRecipientGrants:
    """A recipient-grant seam covering the booking request, or holding nothing.

    Present in nearly every case below because ADR-0254 §6's most important claims
    are about what route (b) does **not** get to do: *"``RecipientGrants.covering``
    is called **zero** times"* is only an assertion where a covering grant is
    actually there to be reached.
    """
    held = FakeRecipientGrants(now=SHARED_CLOCK)
    if covering:
        held.hold(
            recipient_grant(
                *(destinations or (member(SITE),)),
                grant_id="g-1",
                tool=TOOL,
                account=ACCOUNT,
                decided_at=AT,
                expires_at=expires_at,
            )
        )
    return held


def policy(
    *rows: Authorization,
    recipients: FakeRecipientGrants | None = None,
    configured: ConfiguredSearchDestination | None = None,
    sourced: bool = True,
) -> tuple[ThresholdActionPolicy, FakeGoalAuthorizations | None, FakeRecipientGrants | None]:
    """The policy, and the two seams, so a case can read their call counts."""
    authorizations = seam(*rows) if sourced else None
    return (
        ThresholdActionPolicy(
            grants=recipients,
            configured_search=configured,
            authorizations=authorizations,
        ),
        authorizations,
        recipients,
    )


def booking(**parameters: object) -> ActionRequest:
    """The concrete call every case rules on: one destination, and its arguments.

    **It carries no price** (ADR-0266 §11). A ``MONEY`` member is met only against a
    quote and this tree holds none, so a default call carrying an amount would be
    uncovered whatever the row said and every case below would be about that. The
    priced call is :func:`priced`, and the cases about it are their own class.
    """
    return request(binding(SITE), **parameters)  # type: ignore[arg-type]


def priced(amount: object = "50", **parameters: object) -> ActionRequest:
    """The booking call **with** a price and the currency it is denominated in.

    ``AUTHORIZATION_TOOL`` declares ``amount`` at ``MONEY`` with ``currency`` as its
    ``currency_argument`` (ADR-0266 §7), so this is the call the argument route's
    ``MONEY`` comparison is taken over — and the call no quote covers.
    """
    return request(binding(SITE), amount=amount, currency="GBP", **parameters)  # type: ignore[arg-type]


def declaring(*, only: bool = False, **kinds: BoundKind) -> ToolDefinition:
    """:data:`TOOL` with these further arguments declared at these kinds (§7).

    **The argument route's only source**, and the reason a case needs it: a member
    names no argument (ADR-0266 §3), so a member of kind *k* is met only against the
    one argument this declaration declares at *k*. A request carrying an argument
    declared at **no** kind is covered only through the evidence route, which no
    quote reaches in this tree — so a case that forgot to declare would be about
    that rather than about what it is about.

    ``site`` stays declared at ``TERMS`` and ``amount`` at ``MONEY`` (the canonical
    fake's own declaration), because every booking carries both keys — unless
    ``only`` is set, which **replaces** them. A case needs that where it is about a
    kind ``site`` already occupies: §7 meets a member of kind *k* only where the
    declaration declares **exactly one** argument at *k*, so declaring a second
    ``TERMS`` argument beside ``site`` would meet no ``TERMS`` member at all and the
    arm would be about that instead.
    """
    return ToolDefinition.model_validate(
        {
            **TOOL.model_dump(),
            "bounded_arguments": (
                *(() if only else TOOL.model_dump()["bounded_arguments"]),
                *(
                    {
                        "argument": argument,
                        "kind": kind,
                        "currency_argument": "currency" if kind is BoundKind.MONEY else None,
                    }
                    for argument, kind in kinds.items()
                ),
            ),
        }
    )


#: :data:`TOOL` declaring ``stay_from`` at ``PERIOD`` beside its own two (§7).
#:
#: **A case carrying a date needs one**: a ``PERIOD`` member is met on the argument
#: route alone (ADR-0266 §7, §4 minting none of that kind), and the route reads the
#: argument the *declaration* names. Without it the date is an argument declared at
#: no kind, and the case would be about condition 6's third conjunct rather than
#: about §4's reading of an instant.
PERIOD_TOOL: ToolDefinition = declaring(stay_from=BoundKind.PERIOD)

#: A declaration whose **only** bounded argument is ``choice``, at ``TERMS`` (§7).
#:
#: The arms about §4's ``TERMS`` reading and about the fixed-value comparison need
#: one: ``site`` is the canonical declaration's own ``TERMS`` argument, and a
#: declaration carrying two at one kind meets **no** member of that kind — so a case
#: adding a second would be about the two-declarations rule rather than about the
#: reading. Here ``site`` is declared at no kind, which leaves it to condition 6's
#: third conjunct; the arms below read the defect for ``choice`` and not the ruling.
TERMS_TOOL: ToolDefinition = declaring(only=True, choice=BoundKind.TERMS)

#: One value per shape the three kinds' readings accept, carried at ``choice``.
#:
#: **``"50"`` deliberately serves two kinds at once**: it is inside the ``MONEY``
#: ceiling below *and* a term of the ``TERMS`` bound below, which is ADR-0266 §7's
#: *"a hotel's star rating has a number in it and would fit a price"* as a value
#: rather than as a sentence. An implementation selecting an argument by what its
#: value looks like meets the wrong member at that cell.
_ROUTE_VALUES: Final[frozenset[str]] = frozenset({"50", "flexible", AT.isoformat()})

#: A well-formed bound of each kind, so the matrix is written over ``BoundKind``.
_ROUTE_BOUNDS: Final[dict[BoundKind, ValueBound]] = {
    BoundKind.MONEY: money_bound("60"),
    BoundKind.PERIOD: period_bound(starts_at=AT, ends_at=AT + timedelta(hours=12)),
    BoundKind.TERMS: terms_bound("50", "flexible"),
}

#: Which of :data:`_ROUTE_VALUES` each bound above accepts on its own reading.
#:
#: **What keeps the matrix's negative cells from passing vacuously**: a cell is
#: expected to be met exactly where the kinds agree *and* the carried value is one
#: this kind's own bound admits, so the diagonal is green and a refusal off it is
#: about the kind rather than about the value.
_ROUTE_ACCEPTS: Final[dict[BoundKind, frozenset[str]]] = {
    BoundKind.MONEY: frozenset({"50"}),
    BoundKind.PERIOD: frozenset({AT.isoformat()}),
    BoundKind.TERMS: frozenset({"50", "flexible"}),
}


def defects(row: Authorization, call: ActionRequest) -> set[tuple[str, CoverageFailure]]:
    """Every way ADR-0266 §7's condition 6 fails over this pair, as a set.

    **The comparison read at the level the arm is about.** §7 meets a ``MONEY``
    member only against a quote, so a case about §4's *reading* of an amount cannot
    be stated through the ruling in this tree — every such call draws ``CONFIRM``
    whatever the amount is, and an assertion on the outcome alone would pass
    vacuously. The **defects** distinguish the two: a value the reading accepts
    leaves only :attr:`CoverageFailure.UNPROVED` for the kind, and a value it
    refuses adds :attr:`CoverageFailure.REFUSED` for the declared argument. That is
    the property arm 3(b) states, kept whole while its covered limb rides with the
    quote decision (ADR-0266 §11).
    """
    return {(one.subject, one.failure) for one in uncovered(row, coverage_subject(call))}


def refuses(row: Authorization, call: ActionRequest, argument: str) -> bool:
    """Whether §4's reading refused ``argument``'s own value over ``row``."""
    return (argument, CoverageFailure.REFUSED) in defects(row, call)


class TestExistingAuthorizationCoversTheConcreteAction:
    """Arm 1: the case the milestone exists for."""

    async def test_route_d_allows_and_names_the_record(self) -> None:
        """*"``authorised_by`` the record's id, ``authorised_subject`` its recomputed
        digest, ``authorised_goal`` its goal, ``RecipientGrants.covering`` called
        **zero** times, and no redundant approval."*"""
        row = live(id="a1")
        gate, authorizations, recipients = policy(row, recipients=grants())
        ruling = await gate.decide(booking())
        assert ruling.outcome is PermissionOutcome.ALLOW
        assert (ruling.authorised_by, ruling.authorised_goal) == ("a1", GOAL)
        assert ruling.authorised_subject == row.subject_digest
        assert authorizations is not None
        assert authorizations.call_count == 1
        assert recipients is not None
        assert recipients.call_count == 0

    async def test_the_row_is_read_exactly_once_per_ruling_and_never_cached(self) -> None:
        """Arm 51: *"no second call, and no cached answer reused across two ``decide``
        calls"*."""
        gate, authorizations, _ = policy(
            live(
                id="a1",
            )
        )
        await gate.decide(booking())
        await gate.decide(booking())
        assert authorizations is not None
        assert authorizations.call_count == 2


class TestPermissionMissingAndPermissionRevoked:
    """Arms 2 and 3."""

    async def test_no_record_of_that_goal_reaches_no_route_d(self) -> None:
        """Arm 2: the request draws the ``CONFIRM`` the table reached."""
        gate, _, _ = policy()
        ruling = await gate.decide(booking())
        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert (ruling.authorised_by, ruling.authorised_goal) == (None, None)

    async def test_a_revoked_row_answers_none_with_no_bar_and_no_route_d(self) -> None:
        """Arm 3: *"``live_for`` answers ``None``, **no bar and no route (d)**"*.

        The **bar** does not fire, because the seam holds no live row for that pair —
        which is the first of §6's exactly two answers on which a standing route may
        be taken.
        """
        row = live(id="a1")
        gate, authorizations, recipients = policy(row, recipients=grants())
        assert authorizations is not None
        authorizations.settle("a1", to=AuthorizationDisposition.REVOKED, settled_at=NOW)
        ruling = await gate.decide(booking())
        assert ruling.outcome is PermissionOutcome.ALLOW
        assert ruling.authorised_by == "g-1"
        assert ruling.authorised_goal is None
        assert recipients is not None
        assert recipients.call_count == 1


class TestSection4sReadings:
    """Arms 5, 6, 7, 10, 11 and 12: every reading is total and fail-closed.

    **The ``MONEY`` arms are stated over the defects and not over the ruling, and
    ADR-0266 §11 is why.** §7 meets a ``MONEY`` member only against a quote for the
    request's intended action; this tree holds none, so **every** priced call draws
    ``CONFIRM`` whatever its amount is, and an arm asserting on the outcome alone
    would pass for a reason that has nothing to do with the reading. :func:`defects`
    keeps each arm's property: a value §4's reading accepts leaves the argument
    unrefused, and one it rejects adds :attr:`CoverageFailure.REFUSED` for it. The
    covered limb — the same amount drawing ``ALLOW`` — rides with the quote decision
    (ADR-0266 §11), and the arm below pins that the price is unproved meanwhile.
    """

    @pytest.mark.parametrize(
        ("amount", "satisfies"),
        [("60", True), ("59", True), ("61", False), ("10", True), ("9", False)],
    )
    async def test_a_money_bound_is_inclusive_at_both_ends(
        self, amount: str, satisfies: bool
    ) -> None:
        """Arm 5: at, below and above ``maximum``; and at and below ``minimum``.

        **Arm 5 stands verbatim under ``maximum_exclusive``**, which the ADR-0266 §9
        sweep records: the flag defaults to ``False``, so an inclusive ceiling reads
        exactly as it did.
        """
        row = live(
            coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("60", minimum="10")),)
        )
        assert refuses(row, priced(amount=amount), "amount") is not satisfies

    @pytest.mark.parametrize(
        ("amount", "satisfies"),
        [("100", False), ("99.99", True)],
    )
    async def test_a_strict_ceiling_withdraws_its_endpoint(
        self, amount: str, satisfies: bool
    ) -> None:
        """Arm 3(b): *"against an exclusive ``maximum`` of 100 a value of exactly
        ``\"100\"`` does **not** satisfy and against an inclusive one it does"*
        (ADR-0266 §3).

        **No reading rounds, quantises, nudges or relaxes an endpoint in either
        direction**: the difference is a cent in the direction that authorises a
        call the user did not authorise.
        """
        strict = live(
            coverage=(
                coverage_member(BoundKind.MONEY, bound=money_bound("100", maximum_exclusive=True)),
            )
        )
        assert refuses(strict, priced(amount=amount), "amount") is not satisfies

    async def test_an_inclusive_ceiling_admits_the_endpoint_the_strict_one_withdraws(
        self,
    ) -> None:
        """Arm 3(b)'s control, against which the arm above is a difference of one
        flag and of nothing else."""
        inclusive = live(coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("100")),))
        assert refuses(inclusive, priced(amount="100"), "amount") is False

    @pytest.mark.parametrize("amount", [50.0, 50.5, 0.0])
    async def test_a_price_as_a_json_float_is_never_covered(self, amount: float) -> None:
        """Arm 6: *"whatever its magnitude"*.

        *"A binary float is not a price, and comparing one against a decimal bound
        is precisely the unproven comparison ADR-0148 §2 refuses by default: the
        answer is not to round, to quantise or to pick a tolerance, it is to refuse
        and ask."*
        """
        row = live(coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("60")),))
        assert refuses(row, priced(amount=amount), "amount") is True

    async def test_a_json_boolean_is_never_covered_by_a_money_bound(self) -> None:
        """§4: ``bool`` is an ``int`` in Python and ``True`` would otherwise read as one."""
        row = live(coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("60")),))
        assert refuses(row, priced(amount=True), "amount") is True

    @pytest.mark.parametrize(
        ("value", "satisfies"),
        [("A", True), ("a", False), ("A ", False), (60, False)],
    )
    async def test_a_fixed_value_is_compared_by_the_canonical_json_encoding(
        self, value: object, satisfies: bool
    ) -> None:
        """Arm 7: *"a fixed value differing by one byte"*, and a number where the
        member holds a string.

        **Stated over the argument the declaration declares at the member's kind**
        (ADR-0266 §7): a member names no argument, so what a fixed value is compared
        against is the value at that argument and nothing else.
        """
        row = live(site=False, coverage=(coverage_member(BoundKind.TERMS, fixed="A"),))
        call = request(binding(SITE), tool=TERMS_TOOL, choice=value)  # type: ignore[arg-type]
        assert refuses(row, call, "choice") is not satisfies

    @pytest.mark.parametrize(
        ("stated", "satisfies"),
        [("GBP", True), ("KWD", False), (60, False)],
    )
    async def test_the_money_bounds_currency_conjunct_is_taken_over_the_request(
        self, stated: object, satisfies: bool
    ) -> None:
        """Arm 10: *"stated over the **concrete request** rather than over the row"*.

        *"A row whose bound says one currency and whose request says another covers
        nothing rather than covering the wrong amount of the wrong money"* —
        whatever the declaration's schema admits, because no schema is consulted.

        **The key is read at the declaration's ``currency_argument`` and no longer
        at the bound's** (ADR-0266 §3, §7): which key carries an amount's currency is
        a fact about a *declaration*, not about an act. ``AUTHORIZATION_TOOL``
        declares it as ``currency``, and the conjunct is taken there.
        """
        row = live(coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("60")),))
        call = request(binding(SITE), amount="50", currency=stated)  # type: ignore[arg-type]
        assert refuses(row, call, "amount") is not satisfies

    async def test_a_request_carrying_no_value_at_the_currency_argument_is_not_covered(
        self,
    ) -> None:
        """Arm 10's first limb: the conjunct is stated over the **request**, so a
        call that names the amount and not its currency is covered by nothing."""
        row = live(coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("60")),))
        assert refuses(row, request(binding(SITE), amount="50"), "amount") is True

    @pytest.mark.parametrize(
        ("stay_from", "covered"),
        [
            ("2026-09-13T09:00:00+00:00", True),
            ("2026-09-13T21:00:00+00:00", False),
            ("2026-09-13T10:00:00", False),
            ("2026-09-13", False),
        ],
    )
    async def test_a_period_bound_is_half_open_and_refuses_a_naive_instant(
        self, stay_from: str, covered: bool
    ) -> None:
        """Arm 11: an instant at ``starts_at`` is covered, one at ``ends_at`` is not,
        and a date-time carrying **no offset** never satisfies a ``PERIOD`` bound.

        The bare calendar date here falls outside because it denotes the start of
        that day **in the bound's own zone**, which is an hour before ``starts_at``.
        """
        gate, _, _ = policy(
            live(
                tool=PERIOD_TOOL,
                coverage=(
                    coverage_member(
                        BoundKind.PERIOD,
                        bound=period_bound(starts_at=AT, ends_at=AT + timedelta(hours=12)),
                    ),
                ),
            )
        )
        ruling = await gate.decide(request(binding(SITE), tool=PERIOD_TOOL, stay_from=stay_from))
        assert (ruling.outcome is PermissionOutcome.ALLOW) is covered

    async def test_a_calendar_date_is_read_in_the_bounds_own_zone(self) -> None:
        """§4: *"A calendar date denotes the **start of that day in the bound's own
        ``timezone``**, and the zone is read off the bound rather than off
        ``Settings``"* — two recorded values, and no configuration at the moment the
        comparison is taken."""
        gate, _, _ = policy(
            live(
                tool=PERIOD_TOOL,
                coverage=(
                    coverage_member(
                        BoundKind.PERIOD,
                        bound=period_bound(
                            starts_at=AT - timedelta(days=1),
                            ends_at=AT + timedelta(days=1),
                            timezone="Europe/London",
                        ),
                    ),
                ),
            )
        )
        ruling = await gate.decide(request(binding(SITE), tool=PERIOD_TOOL, stay_from="2026-09-13"))
        assert ruling.outcome is PermissionOutcome.ALLOW

    @pytest.mark.parametrize(
        ("value", "covered"),
        [("flexible", True), ("Flexible", False), ("flex", False), ("flexible ", False)],
    )
    async def test_a_terms_bound_is_equality_of_the_stored_characters(
        self, value: str, covered: bool
    ) -> None:
        """Arm 12: *"a term differing only by case"* is not covered.

        *"No fold, no strip, no case-insensitive match, no prefix and no substring."*
        """
        row = live(
            site=False, coverage=(coverage_member(BoundKind.TERMS, bound=terms_bound("flexible")),)
        )
        call = request(binding(SITE), tool=TERMS_TOOL, choice=value)
        assert refuses(row, call, "choice") is not covered


class TestSection3sConditionsThreeFourAndFive:
    """Arms 13 and 49: the facts a grant is stated **about**, which the bar never
    fires on."""

    async def test_a_destination_outside_the_rows_set_is_not_covered(self) -> None:
        """Arm 13: coverage is **set membership** and nothing looser."""
        gate, _, recipients = policy(
            live(
                site=False,
                coverage=(coverage_member(BoundKind.TERMS, bound=terms_bound(SITE, OTHER_SITE)),),
            ),
            recipients=grants(covering=False),
        )
        ruling = await gate.decide(request(binding(OTHER_SITE)))
        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert recipients is not None
        assert recipients.call_count == 1

    async def test_the_same_address_through_a_second_connected_account_is_not_covered(
        self,
    ) -> None:
        """Arm 13's second limb: ``BoundAccount``'s **two facts**, never one."""
        gate, _, _ = policy(
            live(),
            recipients=grants(covering=False),
        )
        ruling = await gate.decide(
            request(binding(SITE, account=OTHER_ACCOUNT), amount="50", currency="GBP")
        )
        assert ruling.outcome is PermissionOutcome.CONFIRM

    async def test_a_declaration_differing_by_value_is_not_covered(self) -> None:
        """Arm 49: *"a record established about one declaration authorises nothing
        about an edited one"* — §1's accepted cost in the safe direction."""
        edited = TOOL.model_copy(update={"description": "Book a pitch — reworded."})
        gate, _, _ = policy(live())
        ruling = await gate.decide(request(binding(SITE), tool=edited, amount="50", currency="GBP"))
        assert ruling.outcome is PermissionOutcome.CONFIRM

    @pytest.mark.parametrize("mismatch", ["declaration", "account", "destinations", "lapsed"])
    async def test_the_bar_does_not_fire_on_what_a_grant_is_stated_about(
        self, mismatch: str, clock: MovableClock
    ) -> None:
        """Arm 49: *"ADR-0193 §5 is the ground — a grant is about the declaration, the
        account and the recipient — and the tests are named for it."*

        In each, every user-facing argument is covered, the bar does **not** fire,
        route (d) does not cover, and route (b) rules exactly as it does on
        ``origin/main``.
        """
        row = live()
        bound = binding(SITE)
        if mismatch == "declaration":
            row = live(tool=TOOL.model_copy(update={"description": "reworded"}))
        elif mismatch == "account":
            row = live(account=OTHER_ACCOUNT)
        elif mismatch == "destinations":
            row = live(destinations=(member(OTHER_SITE),))
        gate, _, recipients = policy(row, recipients=grants(expires_at=EXPIRES + timedelta(days=2)))
        if mismatch == "lapsed":
            clock.set(EXPIRES + timedelta(hours=1))
        ruling = await gate.decide(request(bound))
        assert ruling.outcome is PermissionOutcome.ALLOW
        assert ruling.authorised_by == "g-1"
        assert ruling.authorised_goal is None
        assert recipients is not None
        assert recipients.call_count == 1


class TestSection6sBar:
    """Arms 45, 46, 47, 50, 52, 53 and 54: the refusal taken before any route."""

    async def test_the_bar_fires_over_route_b(self) -> None:
        """Arm 45, *"the case it exists for"*.

        A live record bounding ``amount`` at GBP 60 **and** a grant covering the same
        declaration, account and destination set; a GBP 80 request → route (d) does
        not cover, the bar fires, ``covering`` is called **zero** times, the ruling is
        ``CONFIRM``, and the reason names the argument.

        **Arm 45's GBP 50 limb is the one that moves, and it moves lane** (ADR-0266
        §9's mechanism (iv), §11): a ``MONEY`` member is met only against a quote, so
        in this tree GBP 50 draws the same ``CONFIRM`` for a different reason — the
        ceiling is proved against nothing rather than breached. The reason tells them
        apart, which is what this asserts; the ``ALLOW`` rides with the quote
        decision.
        """
        row = live(coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("60")),))
        gate, _, recipients = policy(row, recipients=grants())
        ruling = await gate.decide(priced(amount="80"))
        assert ruling.outcome is PermissionOutcome.CONFIRM
        # **The key is counted rather than quoted**, because this declaration's
        # schema names nothing — ADR-0145 §8's *"a key can be data"* rule, which the
        # rendering arms exercise both halves of over ``DECLARED_TOOL``.
        assert "outside what the user's own recorded act allows" in ruling.reason
        assert ("amount", CoverageFailure.REFUSED) in defects(row, priced(amount="80"))
        assert recipients is not None
        assert recipients.call_count == 0
        gate, _, recipients = policy(row, recipients=grants())
        inside = await gate.decide(priced(amount="50"))
        assert inside.outcome is PermissionOutcome.CONFIRM
        assert "states a limit nothing about this call proves: money" in inside.reason
        assert "outside what the user's own recorded act allows" not in inside.reason

    async def test_the_bar_fires_on_an_argument_the_record_names_in_no_member(self) -> None:
        """Arm 47: *"§5's *reaches no standing route at all* and §9's *an argument no
        member names* made true of route (b) as well as of route (d)."*"""
        gate, _, recipients = policy(
            live(),
            recipients=grants(),
        )
        ruling = await gate.decide(
            request(binding(SITE), amount="50", currency="GBP", insurance=True)
        )
        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert recipients is not None
        assert recipients.call_count == 0

    async def test_removing_an_argument_the_record_fixes_is_a_change_not_a_licence(
        self,
    ) -> None:
        """Arm 53: *"a lane that read condition 6 over the request's keys alone fails
        this arm"*, ``ALLOW``ing a call that drops the term the user fixed.

        **Stated over the member rather than over the key** (ADR-0266 §7's first
        conjunct): a member names no argument, so what a dropped argument breaks is
        the *member* — it is met by no route, because the argument route needs a
        value at the key the declaration declares at its kind. The control beside it
        is the same row and the same call **carrying** that value.
        """
        row = live(
            site=False,
            tool=PERIOD_TOOL,
            coverage=(coverage_member(BoundKind.PERIOD, bound=period_bound()),),
        )
        gate, _, recipients = policy(row, recipients=grants())
        dropped = request(binding(SITE), tool=PERIOD_TOOL)
        ruling = await gate.decide(dropped)
        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert ("stay_from", CoverageFailure.OMITTED) in defects(row, dropped)
        assert recipients is not None
        assert recipients.call_count == 0
        carried = request(binding(SITE), tool=PERIOD_TOOL, stay_from=AT.isoformat())
        assert ("stay_from", CoverageFailure.OMITTED) not in defects(row, carried)

    async def test_an_empty_coverage_is_an_authority_over_an_argument_free_call(
        self,
    ) -> None:
        """Arm 54: *"an empty ``coverage`` is an authority over an argument-free call
        and is a wildcard over nothing"*."""
        empty = live(coverage=(), site=False, destinations=(account_member(),))
        held = grants(destinations=(account_member(),))
        gate, _, recipients = policy(empty, recipients=held)
        allowed = await gate.decide(request(binding()))
        assert allowed.outcome is PermissionOutcome.ALLOW
        assert allowed.authorised_goal == GOAL
        gate, _, recipients = policy(
            live(id="a2", coverage=(), site=False, destinations=(account_member(),)),
            recipients=grants(destinations=(account_member(),)),
        )
        barred = await gate.decide(request(binding(), anything="at all"))
        assert barred.outcome is PermissionOutcome.CONFIRM
        assert recipients is not None
        assert recipients.call_count == 0

    async def test_the_bar_reads_nothing_it_need_not(self) -> None:
        """Arm 50: *"``live_for`` is called **zero** times in each"*.

        A request carrying ``goal`` unset (arm 9); a policy constructed with no
        ``GoalAuthorizations`` (arm 30); and a request on which
        ``_only_the_disclosure_floor`` is false.
        """
        row = live()
        gate, authorizations, _ = policy(row, recipients=grants())
        goalless = await gate.decide(request(binding(SITE), goal=None, amount="50", currency="GBP"))
        assert authorizations is not None
        assert authorizations.call_count == 0
        # The ruling is what `origin/main` produces for this request: route (b),
        # because a covering grant is in the store and the bar never fired.
        assert goalless.outcome is PermissionOutcome.ALLOW
        assert (goalless.authorised_by, goalless.authorised_goal) == ("g-1", None)

        unsourced = ThresholdActionPolicy()
        sourceless = await unsourced.decide(booking())
        assert sourceless.outcome is PermissionOutcome.CONFIRM
        assert (sourceless.authorised_by, sourceless.authorised_goal) == (None, None)

        gate, authorizations, _ = policy(row, recipients=grants())
        dear = TOOL.model_copy(update={"cost": ToolCost(basis=CostBasis.UNKNOWN)})
        floored = await gate.decide(request(binding(SITE), tool=dear, amount="50", currency="GBP"))
        assert floored.outcome is PermissionOutcome.CONFIRM
        assert authorizations is not None
        assert authorizations.call_count == 0

    async def test_a_store_fault_takes_the_bar_and_is_never_read_as_an_absence(
        self,
    ) -> None:
        """Arm 52. **A lane that answered ``None`` on the fault fails this arm**, the
        grant being enough to reach ``ALLOW``.

        *"The same request with the seam working answers ``CONFIRM`` too, so the fault
        never makes a ruling less restrictive."*
        """
        row = live()
        gate, authorizations, recipients = policy(row, recipients=grants())
        assert authorizations is not None
        authorizations.fail_live_for()
        ruling = await gate.decide(request(binding(SITE), amount="80", currency="GBP"))
        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert recipients is not None
        assert recipients.call_count == 0

    async def test_the_log_line_names_the_class_and_no_value(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """§6, §16: *"the log line names the class and no value"*.

        A store fault is an operator's fact and *"not something to put in front of
        someone deciding about a call"*, so the reason the **user** sees is
        unchanged. Asserted over the **rendered output** rather than over
        ``structlog.testing.capture_logs``, which replaces the processor chain — a
        "does not leak" test written against that fixture passes while the real
        emission path leaks.
        """
        configure_logging(Settings())
        gate, authorizations, _ = policy(live(), recipients=grants())
        assert authorizations is not None
        authorizations.fail_live_for()
        capsys.readouterr()

        ruled = await gate.decide(request(binding(SITE), amount="80", currency="GBP"))

        assert ruled.outcome is PermissionOutcome.CONFIRM
        out = capsys.readouterr().out
        assert "authorization_seam_unreadable" in out
        assert SITE not in out
        assert GOAL not in out
        assert "80" not in ruled.reason


class TestTheFloorsRouteDDoesNotRelax:
    """Arms 31, 32 and 67: condition 4 unrelaxed, condition 3 discharged in full."""

    async def test_a_covered_binding_reaches_route_d_in_no_case(self) -> None:
        """Arm 31(a): condition 4 is unrelaxed, and
        ``_only_the_disclosure_floor``'s coverage limb **gains no disjunct**, so
        ``live_for`` is called **zero** times."""
        gate, authorizations, _ = policy(live())
        ruling = await gate.decide(
            request(
                binding(SITE, coverage=SpanCoverage.MODEL_ON_EVERY_PATH),
                amount="50",
                currency="GBP",
            )
        )
        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert authorizations is not None
        assert authorizations.call_count == 0

    async def test_full_coverage_discharges_the_lineage_floor(self) -> None:
        """Arms 31(c) and 67: *"outside content **cannot have steered anything the
        user did not bound**"*.

        Admitted by the lineage limb's **third disjunct**, which *"admits a request
        rather than deciding it"* — so ``RecipientGrants.covering`` is called **zero**
        times whichever way the coverage comes out.

        **Every argument here is covered on the argument route**, which is what
        ADR-0266 §7 now requires of the discharge: a quote's digest proves the call
        is the one *quoted*, not one the user *bounded*, so coverage the evidence
        route supplied does not discharge the floor. The arm for that is beside this
        one.
        """
        gate, _, recipients = policy(live(), recipients=grants())
        allowed = await gate.decide(request(binding(SITE, external=True)))
        assert allowed.outcome is PermissionOutcome.ALLOW
        assert allowed.authorised_goal == GOAL
        assert recipients is not None
        assert recipients.call_count == 0

    async def test_partial_coverage_over_a_tainted_binding_reaches_no_route_at_all(
        self,
    ) -> None:
        """Arms 31(c) and 67: *"the third disjunct admits and never discharges"*.

        Route (c) does not answer — ADR-0247 §3's retirement is for the configured
        provider and nothing else — and route (b) does not, because ADR-0193 §4 is
        unmoved and **no** ``RecipientGrant`` covers a tainted call.
        """
        gate, _, recipients = policy(
            live(),
            recipients=grants(),
        )
        ruling = await gate.decide(
            request(binding(SITE, external=True), amount="80", currency="GBP")
        )
        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert recipients is not None
        assert recipients.call_count == 0

    async def test_route_b_inherits_none_of_the_lineage_discharge(self) -> None:
        """Arm 67's last limb: a grant covering a **tainted** request, with no
        authorization → ``CONFIRM``, ADR-0193 §4 unmoved."""
        gate, _, recipients = policy(recipients=grants())
        ruling = await gate.decide(
            request(binding(SITE, external=True), amount="50", currency="GBP")
        )
        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert recipients is not None
        assert recipients.call_count == 0

    @pytest.mark.parametrize("ground", ["cost", "risk", "reversibility"])
    async def test_every_other_ground_survives_a_covering_record(self, ground: str) -> None:
        """Arm 32: an ``UNKNOWN`` cost, a threshold ``risk_level`` and a threshold
        ``reversibility`` each still draw ``CONFIRM``.

        Each reaches the seam **zero** times rather than reaching it and being
        overruled: §6 puts the lookup after every ground the request alone settles.
        """
        declared: ToolDefinition = {
            "cost": TOOL.model_copy(update={"cost": ToolCost(basis=CostBasis.UNKNOWN)}),
            "risk": TOOL.model_copy(update={"risk_level": RiskLevel.HIGH}),
            "reversibility": TOOL.model_copy(update={"reversibility": Reversibility.IRREVERSIBLE}),
        }[ground]
        gate, authorizations, _ = policy(
            live(
                tool=declared,
            )
        )
        ruling = await gate.decide(
            request(binding(SITE), tool=declared, amount="50", currency="GBP")
        )
        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert authorizations is not None
        assert authorizations.call_count == 0


class TestTheTwoRoutesAndConditionSixsThreeConjuncts:
    """ADR-0266 §7's arms 2(b), 6(a)'s no-quote limbs and 6(b)'s comparison half.

    **Every ``MONEY`` arm here is an uncovered one**, and §11 says why: this
    decision lands no quote carrier, so the evidence route is met by nothing and the
    with-a-quote limbs ride with ADR-0267's Q1.
    """

    async def test_a_money_member_is_met_by_no_route_without_a_quote(self) -> None:
        """Arm 6(a)'s first limb: *"against a declaration declaring ``price``
        ``MONEY`` with ``currency_argument`` ``"currency"``, a request satisfying
        that argument but covered by **no quote** is **not** covered"*.

        **The declared argument never stands in for the quote** (ADR-0266 §7): a
        ``MONEY`` member needs the evidence route in every case, and the argument
        route *as well* where the declaration declares an amount. So an amount
        comfortably inside the ceiling is uncovered, and the reason says the ceiling
        was proved against nothing rather than breached.
        """
        row = live(coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("60")),))
        call = priced(amount="50")
        assert defects(row, call) == {("money", CoverageFailure.UNPROVED)}
        gate, _, _ = policy(row)
        ruling = await gate.decide(call)
        assert ruling.outcome is PermissionOutcome.CONFIRM

    async def test_a_declaration_declaring_two_arguments_at_one_kind_meets_no_member(
        self,
    ) -> None:
        """Arm 6(a): *"A declaration declaring **two** ``MONEY`` arguments meets no
        ``MONEY`` member on that route"*.

        **No precedence rule at the comparison** — which is ADR-0254 §2's own reason
        one field over — so the restrictive direction is taken and the act asks.

        **Stated as *neither* argument being selected, and not as one of them being
        refused.** An implementation taking the last declaration and dropping the
        rule would leave ``amount`` refused all the same — the non-selected argument
        failing its own exactly-one guard — so an assertion naming only ``amount``
        passes while precedence is introduced. :func:`declared_at` answering ``None``
        is the rule itself, and the whole defect set is what it means here: both
        declared amounts refused, the ceiling proved by nothing, and the currency key
        left unexamined because no comparison read it. Adversarial review, round 8,
        ``blocker``.
        """
        two = declaring(fee=BoundKind.MONEY)
        row = live(tool=two, coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("60")),))
        call = request(binding(SITE), tool=two, amount="50", currency="GBP", fee="1")
        assert declared_at(two, BoundKind.MONEY) is None
        assert defects(row, call) == {
            ("amount", CoverageFailure.REFUSED),
            ("fee", CoverageFailure.REFUSED),
            ("currency", CoverageFailure.UNNAMED),
            ("money", CoverageFailure.UNPROVED),
        }

    @pytest.mark.parametrize("carried", sorted(_ROUTE_VALUES))
    @pytest.mark.parametrize("declared_kind", list(BoundKind))
    @pytest.mark.parametrize("member_kind", list(BoundKind))
    def test_the_argument_route_meets_a_member_at_its_own_kind_and_nowhere_else(
        self, member_kind: BoundKind, declared_kind: BoundKind, carried: str
    ) -> None:
        """Arm 2(b): kind agreement and **not numeric fit**, which is the review's
        own case — *"a hotel's star rating has a number in it and would fit a price"*.

        **The route predicate itself, over every cell of the matrix.** Read through
        the defects instead, the reverse half of this arm proves nothing: ``("money",
        UNPROVED)`` is emitted for *every* ``MONEY`` member in this tree whatever the
        argument route does (:func:`_met_through_evidence` lands no quote), so an
        implementation selecting an argument by numeric fit rather than by declared
        kind would leave that assertion green. Adversarial review, round 8,
        ``blocker``.

        **The matrix is over ``BoundKind`` itself rather than over the two cells the
        arm names**, so a fourth kind widens it without anyone remembering to. The
        three carried values are each accepted by at least one kind's own bound and
        :data:`_ROUTE_ACCEPTS` says which, so the diagonal is met and the negative
        cells are not vacuous: ``"50"`` fits the ``MONEY`` ceiling **and** sits in the
        ``TERMS`` bound, which is the star rating and the price in one value.
        """
        tool = declaring(only=True, choice=declared_kind)
        declared = tool.bounded_arguments[0]
        call = request(binding(SITE), tool=tool, choice=carried, currency="GBP")
        member = coverage_member(member_kind, bound=_ROUTE_BOUNDS[member_kind])
        met = _met_on_argument_route(member, declared, coverage_subject(call))
        assert met is (member_kind is declared_kind and carried in _ROUTE_ACCEPTS[member_kind])

    async def test_an_undeclared_argument_needs_a_member_met_through_the_evidence_route(
        self,
    ) -> None:
        """Condition 6's **third conjunct**, and the ``send_message`` case.

        *"A row whose every member is met on the **argument** route does not cover a
        request carrying a user-facing argument the declaration declares at no
        kind"* — without it a row fixing ``subject`` to *"urgent"* would cover a
        later ``send_message`` carrying a different ``body``.
        """
        row = live()
        assert defects(row, booking()) == set()
        with_undeclared = booking(body="anything at all")
        assert ("body", CoverageFailure.UNNAMED) in defects(row, with_undeclared)

    async def test_a_call_dropping_the_declared_amount_is_told_so_as_well(self) -> None:
        """ADR-0254 §4's *"the three failures are told apart"*, over §7's two routes.

        **Neither route's failure hides the other.** A call that omits the declared
        amount while carrying its currency fails the evidence route — the price is
        proved by nothing — **and** the argument route, because an act that bounded
        an amount authorised a call *carrying* one. An implementation answering at
        the first failure told the user only the former, which is the wrong one of
        *"different facts about what the user authorised"*: they would read that the
        price could not be proved, and never that their call had dropped the
        argument their own act covers. Adversarial review, round 4, ``blocker``.
        """
        row = live(coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("60")),))
        dropped = request(binding(SITE), currency="GBP")
        assert defects(row, dropped) == {
            ("amount", CoverageFailure.OMITTED),
            ("currency", CoverageFailure.UNNAMED),
            ("money", CoverageFailure.UNPROVED),
        }
        gate, _, _ = policy(
            live(site=False, tool=DECLARED_TOOL, coverage=row.coverage), recipients=grants()
        )
        ruling = await gate.decide(request(binding(SITE), tool=DECLARED_TOOL, currency="GBP"))
        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert "omits an argument the user's own recorded act covers: 'amount'" in ruling.reason
        assert "states a limit nothing about this call proves: money" in ruling.reason

    async def test_a_call_carrying_the_declared_amount_reports_no_omission(self) -> None:
        """The control beside the arm above: with the amount carried, the only
        failure left is the one this tree always has — nothing proves the price."""
        row = live(coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("60")),))
        assert defects(row, priced(amount="50")) == {("money", CoverageFailure.UNPROVED)}

    async def test_the_currency_keys_exemption_is_conditional_and_not_unconditional(
        self,
    ) -> None:
        """Arm 6(a): *"The ``currency_argument`` exemption is conditional and is
        demonstrated so"*.

        A request carrying ``currency`` and **no** ``amount`` is not exempt, nor is
        one whose row holds no ``MONEY`` member — *"an unconditional exemption would
        let ``{"currency": "EUR"}`` and ``{"currency": "USD"}`` both pass an empty
        row"*. Both spellings are uncovered, and by the same defect.
        """
        no_money = live()
        for stated in ("GBP", "USD"):
            call = request(binding(SITE), currency=stated)
            assert ("currency", CoverageFailure.UNNAMED) in defects(no_money, call)
        priced_row = live(coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("60")),))
        no_amount = request(binding(SITE), currency="GBP")
        assert ("currency", CoverageFailure.UNNAMED) in defects(priced_row, no_amount)
        # **And exempt where the comparison that consumes it was actually taken**:
        # the argument route's own §4 reading reads the currency there.
        assert ("currency", CoverageFailure.UNNAMED) not in defects(priced_row, priced(amount="50"))

    async def test_a_tainted_request_the_evidence_route_would_cover_keeps_the_floor(
        self,
    ) -> None:
        """ADR-0266 §7's narrowing of ADR-0254 §6, in the narrowing direction alone.

        *"A digest proves the call is the one quoted, not one the user bounded"*, so
        the lineage discharge is available **only** where every user-facing argument
        is covered by a member on the argument route. Here one is declared at no
        kind, so the floor binds unrelaxed and the ruling is the ``CONFIRM`` the
        table reached — §6's own *"Partial coverage still asks"*, reached by one
        further case.
        """
        row = live()
        undeclared = request(binding(SITE, external=True), body="chosen by a plan")
        assert not covers_on_argument_route(row, coverage_subject(undeclared))
        gate, _, _ = policy(row, recipients=grants())
        ruling = await gate.decide(undeclared)
        assert ruling.outcome is PermissionOutcome.CONFIRM


class TestSystemSuppliedArguments:
    """Arm 68's policy half: neither covered nor asked about."""

    async def test_a_system_supplied_argument_is_covered_by_nothing_and_bars_nothing(
        self,
    ) -> None:
        """§3: condition 6 holds over the **user-facing** arguments alone."""
        declared = TOOL.model_copy(update={"system_supplied": ("idempotency_key", "locale")})
        gate, _, recipients = policy(live(tool=declared), recipients=grants())
        ruling = await gate.decide(
            request(
                binding(SITE),
                tool=declared,
                idempotency_key="k-1",
                locale="en-GB",
            )
        )
        assert ruling.outcome is PermissionOutcome.ALLOW
        assert ruling.authorised_goal == GOAL
        assert recipients is not None
        assert recipients.call_count == 0

    async def test_a_declaration_classifying_none_behaves_exactly_as_before(self) -> None:
        """Arm 68's last limb, over arm 1's record."""
        assert TOOL.system_supplied == ()
        gate, _, _ = policy(live())
        ruling = await gate.decide(booking())
        assert ruling.outcome is PermissionOutcome.ALLOW


class TestTheRecipientAuthorityAnOpeningActRestedOn:
    """Arm 70: it must still stand at every dispatch, and route (d) re-takes it."""

    def _row(self) -> Authorization:
        return opening_act(coverage=(coverage_member(BoundKind.TERMS, fixed=SITE),))

    async def test_route_d_covers_an_opening_act_row_over_a_live_grant(self) -> None:
        """§6: the seam is consulted **once, before route (d) may answer**."""
        gate, _, recipients = policy(self._row(), recipients=grants())
        ruling = await gate.decide(booking())
        assert ruling.outcome is PermissionOutcome.ALLOW
        assert ruling.authorised_goal == GOAL
        assert recipients is not None
        assert recipients.call_count == 1

    async def test_withdrawing_the_grant_ends_the_authority_at_the_next_dispatch(
        self,
    ) -> None:
        """Arm 70: *"route (d) does not cover because the grant condition fails, route
        (b) does not cover because there is no grant, and the bar does not fire
        because the row covers"*.

        **A lane that wrote an opening-act row and then let route (d) carry it alone
        fails this arm.**
        """
        gate, _, recipients = policy(self._row(), recipients=grants(covering=False))
        ruling = await gate.decide(booking())
        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert recipients is not None
        assert recipients.call_count == 1

    async def test_a_confirmed_row_consults_the_grant_seam_zero_times(self) -> None:
        """Arm 70: *"the seam is read over ``origin`` and never over the pointer
        shape"*, and a path-(i) supersession **discharges** the dependency."""
        gate, _, recipients = policy(
            live(
                supersedes=None,
            ),
            recipients=grants(covering=False),
        )
        ruling = await gate.decide(booking())
        assert ruling.outcome is PermissionOutcome.ALLOW
        assert recipients is not None
        assert recipients.call_count == 0

    async def test_a_policy_holding_no_grant_seam_covers_no_opening_act_row(self) -> None:
        """§6, §1: an opening act supplies no recipient authority of its own, so a
        policy that cannot check the grant reaches no route (d) over one."""
        gate, _, _ = policy(self._row())
        ruling = await gate.decide(booking())
        assert ruling.outcome is PermissionOutcome.CONFIRM


class TestAClockThatMovedBackwards:
    """Arm 71: the policy and the trail agree, rather than disagreeing."""

    async def test_a_reading_before_settled_at_answers_none_and_draws_confirm(
        self, clock: MovableClock
    ) -> None:
        """*"Where a liveness stated over the upper end alone would have produced a
        route-(d) ``ALLOW`` the trail then refused as backdated."*"""
        gate, _, _ = policy(live())
        clock.set(AT - timedelta(hours=1))
        ruling = await gate.decide(booking())
        assert ruling.outcome is PermissionOutcome.CONFIRM

    async def test_equality_at_the_lower_end_is_live(self, clock: MovableClock) -> None:
        """Arm 71's second limb."""
        gate, _, _ = policy(live())
        clock.set(AT)
        ruling = await gate.decide(booking())
        assert ruling.outcome is PermissionOutcome.ALLOW


@pytest.fixture
def clock() -> MovableClock:
    """The shared clock, reset for this case."""
    return SHARED_CLOCK.reset()


class TestASourcedPolicyStaysMonotone(ActionPolicyContract):
    """Arm 44: ADR-0193 §12's accommodation, one seam over.

    The suite stands up a fake ``GoalAuthorizations`` and holds its records equal,
    which is what makes ADR-0021 §5's *"equal in every other respect"* stateable at
    all for a policy whose answer depends on a store.
    """

    @pytest.fixture
    def policy(self) -> ActionPolicy:
        """The default policy, sourced, over one record held fixed."""
        return ThresholdActionPolicy(
            authorizations=FakeGoalAuthorizations(
                (live(id="held-equal"),), now=SHARED_CLOCK.reset()
            )
        )


class TestThePeriodReadingsGrammarIsRfc3339AndNoWider:
    """§4 admits *"an RFC 3339 date-time carrying an offset, **or** a calendar date"*.

    ``datetime.fromisoformat`` implements **ISO 8601** and is strictly wider, and
    every form it admits beyond §4's grammar would be an argument satisfying a bound
    in the **permissive** direction — the one direction §4 refuses: *"the answer is
    not to round, to quantise or to pick a tolerance, it is to refuse and ask."*
    """

    @staticmethod
    def _gate() -> ThresholdActionPolicy:
        return policy(
            live(
                tool=PERIOD_TOOL,
                coverage=(
                    coverage_member(
                        BoundKind.PERIOD,
                        bound=period_bound(starts_at=AT, ends_at=AT + timedelta(hours=12)),
                    ),
                ),
            )
        )[0]

    @pytest.mark.parametrize(
        "stay_from",
        [
            pytest.param("2026-09-13 09:00:00+00:00", id="space-separator"),
            pytest.param("2026-09-13X09:00:00+00:00", id="arbitrary-separator"),
            pytest.param("2026-09-13T09:00:00+0000", id="colon-free-offset"),
            pytest.param("2026-09-13T09:00:00,5+00:00", id="comma-fraction"),
            pytest.param("20260913T090000+0000", id="compact"),
            pytest.param("2026-09-13T09:00+00:00", id="no-seconds"),
        ],
    )
    async def test_a_date_time_outside_rfc_3339s_grammar_is_not_covered(
        self, stay_from: str
    ) -> None:
        """Each of these denotes an instant **inside** the bound, so a reading that
        parsed it would ``ALLOW``. *"A lane that delegated the grammar to
        ``datetime.fromisoformat`` fails here."*"""
        ruling = await self._gate().decide(
            request(binding(SITE), tool=PERIOD_TOOL, stay_from=stay_from)
        )
        assert ruling.outcome is PermissionOutcome.CONFIRM

    @pytest.mark.parametrize(
        "stay_from",
        [
            pytest.param("2026-09-13T09:00:00+00:00", id="offset"),
            pytest.param("2026-09-13T09:00:00Z", id="zulu"),
            pytest.param("2026-09-13t09:00:00z", id="lower-case"),
            pytest.param("2026-09-13T09:00:00.500+00:00", id="fraction"),
            pytest.param("2026-09-13T10:00:00+01:00", id="non-utc-offset"),
        ],
    )
    async def test_every_form_rfc_3339_admits_is_read(self, stay_from: str) -> None:
        """The grammar is exactly as wide as §4 states it, and no narrower: a reading
        that refused a ``Z`` or a fraction would ask about calls the user's own act
        covers."""
        ruling = await self._gate().decide(
            request(binding(SITE), tool=PERIOD_TOOL, stay_from=stay_from)
        )
        assert ruling.outcome is PermissionOutcome.ALLOW

    @pytest.mark.parametrize(
        "stay_from",
        [pytest.param("20260913", id="compact"), pytest.param("2026-W37-7", id="week-date")],
    )
    async def test_a_calendar_date_outside_the_full_date_grammar_is_not_covered(
        self, stay_from: str
    ) -> None:
        """``date.fromisoformat`` admits both of these and §4's *"calendar date"*
        does not: they are the same widening one arm over."""
        gate = policy(
            live(
                tool=PERIOD_TOOL,
                coverage=(
                    coverage_member(
                        BoundKind.PERIOD,
                        bound=period_bound(
                            starts_at=AT - timedelta(days=1), ends_at=AT + timedelta(days=1)
                        ),
                    ),
                ),
            )
        )[0]
        ruling = await gate.decide(request(binding(SITE), tool=PERIOD_TOOL, stay_from=stay_from))
        assert ruling.outcome is PermissionOutcome.CONFIRM


class TestWhatTheRulingsReasonSaysWhenCoverageFails:
    """§4's reason clause, and arms 8, 45, 47 and 53.

    *"The three failures are told apart, whichever way the key is rendered"*, and
    the reason **never** reproduces an argument's value, the bound, the record's id
    or its digest: a reason is carried on a durable ``PermissionDecision`` that holds
    ``parameters_digest`` and not ``parameters``, and quoting a value would put into
    the trail exactly what that omission keeps out.
    """

    @staticmethod
    def _covered() -> tuple[CoverageMember, ...]:
        """The site the act fixed and the ceiling it stated.

        **The ``MONEY`` member is met by nothing here** (ADR-0266 §11), so every
        ruling below carries ``UNPROVED`` for it beside whatever the arm is about.
        That is what the arms assert **around**: each names the clause it is about
        and, where it matters, that the other clauses are absent.
        """
        return (
            coverage_member(BoundKind.TERMS, fixed=SITE),
            coverage_member(BoundKind.MONEY, bound=money_bound("60")),
        )

    async def test_an_argument_the_record_names_in_no_member(self) -> None:
        """Arm 47: *"the reason says the record names that argument in no member
        rather than that a comparison failed"*."""
        gate, _, _ = policy(
            live(site=False, coverage=self._covered(), tool=DECLARED_TOOL),
            recipients=grants(),
        )
        ruling = await gate.decide(
            request(
                binding(SITE),
                tool=DECLARED_TOOL,
                amount="50",
                currency="GBP",
                refundable_only=True,
            )
        )
        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert "covers no such argument" in ruling.reason
        assert "'refundable_only'" in ruling.reason

    async def test_an_argument_a_member_names_that_the_request_omits(self) -> None:
        """Arm 53: *"the reason says a member names an argument the request omits"*.

        *"There is no default, no wildcard, no 'not sent therefore unconstrained'
        and no omission that reads as consent."*

        **Stated over the argument the declaration declares at the member's kind**
        (ADR-0266 §7): a member names no argument, so what the request omits is the
        key ``DECLARED_TOOL`` declares at ``PERIOD``, and the omission is why the
        member is met by no route.
        """
        gate, _, _ = policy(
            live(
                site=False,
                coverage=(
                    *self._covered(),
                    coverage_member(BoundKind.PERIOD, bound=period_bound()),
                ),
                tool=DECLARED_TOOL,
            ),
            recipients=grants(),
        )
        ruling = await gate.decide(
            request(binding(SITE), tool=DECLARED_TOOL, amount="50", currency="GBP")
        )
        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert "omits an argument" in ruling.reason
        assert "'stay_from'" in ruling.reason

    async def test_an_argument_whose_value_the_comparison_refused(self) -> None:
        """Arm 45's uncovered limb: *"the reason names the argument"*, and says the
        value is outside what the act allows rather than that a member is missing.

        **And the currency key is reached by condition 6's third conjunct here,
        which is ADR-0266 §7's conditional exemption working rather than a second
        defect.** The key is exempt only *"where the comparison that consumes it was
        actually taken"* — the ``MONEY`` member is not met on the argument route
        against an amount above the ceiling, so nothing read the currency, and an
        unconditional exemption would let ``"EUR"`` and ``"USD"`` both pass.

        Arm 45's **covered** limb — the same declaration at GBP 50 drawing ``ALLOW``
        — rides with the quote decision (ADR-0266 §11), no ``MONEY`` member being
        met in this tree.
        """
        gate, _, _ = policy(
            live(site=False, coverage=self._covered(), tool=DECLARED_TOOL),
            recipients=grants(),
        )
        call = request(binding(SITE), tool=DECLARED_TOOL, amount="80", currency="GBP")
        ruling = await gate.decide(call)
        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert "outside what the user's own recorded act allows: 'amount'" in ruling.reason
        row = live(site=False, coverage=self._covered(), tool=DECLARED_TOOL)
        assert ("amount", CoverageFailure.REFUSED) in defects(row, call)
        assert ("currency", CoverageFailure.UNNAMED) in defects(row, call)

    async def test_the_failures_are_told_apart_on_one_ruling(self) -> None:
        """§4: different facts about what the user authorised, so a ruling meeting
        all of them says all of them.

        **Four and no longer three** (ADR-0266 §7). A member proved by no route is a
        failure §4's three cannot express, and folding it into *"outside what the
        act allows"* would tell the user their ceiling was **breached** when it was
        compared against nothing.
        """
        gate, _, _ = policy(
            live(
                site=False,
                coverage=(
                    *self._covered(),
                    coverage_member(BoundKind.PERIOD, bound=period_bound()),
                ),
                tool=DECLARED_TOOL,
            ),
            recipients=grants(),
        )
        ruling = await gate.decide(
            request(binding(SITE), tool=DECLARED_TOOL, amount="80", currency="GBP", extras="two")
        )
        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert "covers no such argument" in ruling.reason
        assert "omits an argument" in ruling.reason
        assert "outside what the user's own recorded act allows" in ruling.reason
        # **And the fourth, which ADR-0266 §7 creates**: the ceiling is proved
        # against nothing, which is a different fact from a ceiling breached.
        assert "states a limit nothing about this call proves" in ruling.reason

    async def test_a_key_the_schema_does_not_name_is_counted_and_never_quoted(
        self,
    ) -> None:
        """Arm 8's second test, over *"a declaration admitting additional properties
        and a request carrying a data-bearing key such as an address"*.

        ADR-0145 §8's ground is that *"a key can be data"* — a mapping the schema
        does not describe can be keyed by an address or an identifier — so an
        undeclared key is **counted** rather than listed, which is that section's
        *"by keyword and location rather than by key"* read onto this message.
        """
        gate, _, _ = policy(
            live(site=False, coverage=self._covered(), tool=DECLARED_TOOL),
            recipients=grants(),
        )
        ruling = await gate.decide(
            request(
                binding(SITE),
                tool=DECLARED_TOOL,
                amount="50",
                currency="GBP",
                **{"alice@example.com": "yes", "bob@example.com": "no"},
            )
        )
        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert "alice@example.com" not in ruling.reason
        assert "bob@example.com" not in ruling.reason
        assert "2 further arguments" in ruling.reason

    async def test_the_reason_reproduces_no_value_no_bound_and_no_record_id(self) -> None:
        """§4: the three things a reason may never carry, asserted together.

        The record's **id** is the one an auditor reads off ``authorised_by``; a
        ``CONFIRM`` names no authorisation at all, and the reason must not
        reintroduce one.
        """
        row = live(site=False, coverage=self._covered(), tool=DECLARED_TOOL, id="a-secret")
        gate, _, _ = policy(row, recipients=grants())
        ruling = await gate.decide(
            request(binding(SITE), tool=DECLARED_TOOL, amount="80", currency="GBP")
        )
        assert "80" not in ruling.reason
        assert "60" not in ruling.reason
        assert "a-secret" not in ruling.reason
        assert row.subject_digest not in ruling.reason

    async def test_a_store_fault_adds_no_account_to_the_reason(self) -> None:
        """§16: *"a store fault is an operator's fact and not something to put in
        front of someone deciding about a call"*, so the reason the user sees is
        unchanged and describes no coverage failure that did not happen."""
        gate, authorizations, _ = policy(
            live(site=False, coverage=self._covered(), tool=DECLARED_TOOL),
            recipients=grants(),
        )
        assert authorizations is not None
        authorizations.fail_live_for()
        ruling = await gate.decide(
            request(binding(SITE), tool=DECLARED_TOOL, amount="80", currency="GBP")
        )
        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert ruling.reason == "it may disclose personal data off-device"

    async def test_a_request_with_no_record_of_that_goal_gets_no_account_either(
        self,
    ) -> None:
        """There is no coverage failure to describe where the seam holds no live row
        — the first of §6's exactly two answers a standing route may be taken on."""
        gate, _, _ = policy(recipients=grants(covering=False))
        ruling = await gate.decide(
            request(binding(SITE), tool=DECLARED_TOOL, amount="50", currency="GBP")
        )
        assert ruling.reason == "it may disclose personal data off-device"


class TestTheBarAndTheConfiguredProvider:
    """Arms 31(b), 46 and 48: the bar precedes route (c), and is monotone."""

    @staticmethod
    def _configured() -> ConfiguredSearchDestination:
        return ConfiguredSearchDestination(
            reference=SEARCH_ACCOUNT.reference, destinations=frozenset({search_member()})
        )

    @staticmethod
    def _searching(*members: CoverageMember, tool: ToolDefinition = SEARCH_TOOL) -> Authorization:
        """A record of the goal about the **search** declaration.

        **No ``origin`` member, and the declaration is why** (ADR-0266 §7). A member
        names no argument and one kind admits one member, so a row cannot bound both
        the origin and the query; ``SEARCH_TOOL`` therefore declares ``query`` at
        ``TERMS`` and classifies ``origin`` **system-supplied** — which it is, the
        configured provider's origin coming from ``Settings`` — so condition 6 is
        over the query alone and *"a user is never asked to approve"* the origin.
        """
        return live(
            site=False,
            tool=tool,
            account=SEARCH_ACCOUNT,
            destinations=(search_member(),),
            coverage=members,
        )

    async def test_the_bar_fires_over_route_c(self) -> None:
        """Arm 46: a record of the goal fixing an argument of a ``WEB_SEARCH``
        declaration, and a request whose argument fails that member → **``CONFIRM``**,
        no route-(c) ``ALLOW``, and ``authorised_by`` unset."""
        gate, _, _ = policy(
            self._searching(coverage_member(BoundKind.TERMS, bound=terms_bound("campsites"))),
            configured=self._configured(),
        )
        ruling = await gate.decide(
            request(search_binding(), tool=SEARCH_TOOL, query="something else")
        )
        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert ruling.authorised_by is None

    async def test_a_goal_holding_no_such_record_still_reaches_route_c(self) -> None:
        """Arm 46's second half: *"route (c) ``ALLOW`` on the binding's
        ``account.reference``, unchanged from ``origin/main``"*."""
        gate, _, _ = policy(configured=self._configured())
        ruling = await gate.decide(request(search_binding(), tool=SEARCH_TOOL, query="campsites"))
        assert ruling.outcome is PermissionOutcome.ALLOW
        assert ruling.authorised_by == SEARCH_ACCOUNT.reference
        assert ruling.authorised_goal is None

    async def test_route_c_answers_before_route_d_where_both_would(self) -> None:
        """§6's total order: the bar, then route (c), then route (d), then route (b).

        *"Where route (c) answers, ``RecipientGrants.covering`` is called **zero**
        times and no ruling at the configured provider cites a grant"* — and it
        carries no goal scope, which is the discriminator from the row alone.
        """
        gate, _, recipients = policy(
            self._searching(coverage_member(BoundKind.TERMS, fixed="campsites")),
            configured=self._configured(),
            recipients=grants(covering=False),
        )
        ruling = await gate.decide(request(search_binding(), tool=SEARCH_TOOL, query="campsites"))
        assert ruling.outcome is PermissionOutcome.ALLOW
        assert (ruling.authorised_by, ruling.authorised_goal) == (
            SEARCH_ACCOUNT.reference,
            None,
        )
        assert ruling.authorised_subject is None
        assert recipients is not None
        assert recipients.call_count == 0

    async def test_covered_content_at_the_configured_provider_reaches_no_route_d(
        self,
    ) -> None:
        """Arm 31(b). **A lane that read route (d)'s fourth condition off
        ``_only_the_disclosure_floor``'s answer fails this**: that predicate carries
        ADR-0247 §3's disjunct, so it holds here, and route (d) must re-take condition
        4 over the binding in its **strict** form.

        The ruling is route (c)'s ``ALLOW`` — which is what tells the two apart: a
        lane that let route (d) answer would set ``authorised_goal``.
        """
        gate, _, _ = policy(
            self._searching(coverage_member(BoundKind.TERMS, fixed="campsites")),
            configured=self._configured(),
        )
        ruling = await gate.decide(
            request(
                search_binding(coverage=SpanCoverage.MODEL_ON_EVERY_PATH),
                tool=SEARCH_TOOL,
                query="campsites",
            )
        )
        assert ruling.outcome is PermissionOutcome.ALLOW
        assert ruling.authorised_goal is None
        assert ruling.authorised_by == SEARCH_ACCOUNT.reference

    async def test_the_bar_fires_at_the_configured_provider_over_covered_content_too(
        self,
    ) -> None:
        """Arm 31(b)'s *"unless §6's bar fires"*: the bar is taken **before** route
        (c), so it refuses a request route (c) would otherwise have allowed."""
        gate, _, _ = policy(
            self._searching(coverage_member(BoundKind.TERMS, bound=terms_bound("campsites"))),
            configured=self._configured(),
        )
        ruling = await gate.decide(
            request(
                search_binding(coverage=SpanCoverage.MODEL_ON_EVERY_PATH),
                tool=SEARCH_TOOL,
                query="something else",
            )
        )
        assert ruling.outcome is PermissionOutcome.CONFIRM

    @pytest.mark.parametrize(
        ("stored_risk", "request_risk"),
        [(RiskLevel.LOW, RiskLevel.MEDIUM), (RiskLevel.LOW, RiskLevel.LOW)],
    )
    async def test_the_bars_answer_does_not_move_with_severity_out_of_equality(
        self, stored_risk: RiskLevel, request_risk: RiskLevel
    ) -> None:
        """Arm 48(a), *moving out of equality*. **A lane that keyed the lookup by
        value fails here**: the row would match nothing and route (c) would answer
        ``ALLOW``.

        Taken over route (c) because route (b) compares the declaration itself and
        falls away with it. The confirmation threshold is ``HIGH`` throughout, so
        ``fired == [_DISCLOSURE_FLOOR]`` everywhere and the records are held equal.
        """
        stored = SEARCH_TOOL.model_copy(update={"risk_level": stored_risk})
        asked = SEARCH_TOOL.model_copy(update={"risk_level": request_risk})
        gate = ThresholdActionPolicy(
            confirm_at_risk=RiskLevel.HIGH,
            configured_search=self._configured(),
            authorizations=seam(
                self._searching(coverage_member(BoundKind.TERMS, fixed="campsites"), tool=stored)
            ),
        )
        ruling = await gate.decide(request(search_binding(), tool=asked, query="something else"))
        assert ruling.outcome is PermissionOutcome.CONFIRM

    @pytest.mark.parametrize("request_risk", [RiskLevel.LOW, RiskLevel.MEDIUM])
    async def test_the_bars_answer_does_not_move_with_severity_into_equality(
        self, request_risk: RiskLevel
    ) -> None:
        """Arm 48(b), *moving into equality*. **A lane that put §3's condition 3
        inside the bar fails here**: the ``LOW`` request would have drawn ``CONFIRM``
        and the ``MEDIUM`` one ``ALLOW``, which is the same violation from the other
        side."""
        stored = SEARCH_TOOL.model_copy(update={"risk_level": RiskLevel.MEDIUM})
        asked = SEARCH_TOOL.model_copy(update={"risk_level": request_risk})
        gate = ThresholdActionPolicy(
            confirm_at_risk=RiskLevel.HIGH,
            configured_search=self._configured(),
            authorizations=seam(
                self._searching(coverage_member(BoundKind.TERMS, fixed="campsites"), tool=stored)
            ),
        )
        ruling = await gate.decide(request(search_binding(), tool=asked, query="campsites"))
        assert ruling.outcome is PermissionOutcome.ALLOW


class TestACivilDateThatHasNoStartInTheBoundsZone:
    """§4: *"A calendar date denotes the **start of that day in the bound's own
    ``timezone``**"* — and a day that has no start denotes no instant.

    A zone can skip a whole calendar day: Samoa skipped **30 December 2011** when it
    crossed the date line, so no instant exists whose local date in
    ``Pacific/Apia`` is that day. ``datetime.combine`` answers such a date with an
    instant all the same, resolving the gap by PEP 495's rule — and that instant
    belongs to a **different** local day, so a bound containing it would cover a
    request whose date the user could not have meant. §4's reading is total and
    *"every failure of it is a refusal to cover"*.
    """

    @staticmethod
    def _gate(*, starts_at: datetime, ends_at: datetime) -> ThresholdActionPolicy:
        """A policy over a record whose ``PERIOD`` bound spans the 2011 dates.

        The **row's** own instants stay at this module's defaults: a bound's
        interval is what a *date argument* is read against and has nothing to do
        with the record's own liveness, so moving the row into 2011 would have
        tested the clock rather than the reading.
        """
        return policy(
            live(
                tool=PERIOD_TOOL,
                coverage=(
                    coverage_member(
                        BoundKind.PERIOD,
                        bound=period_bound(
                            starts_at=starts_at, ends_at=ends_at, timezone="Pacific/Apia"
                        ),
                    ),
                ),
            )
        )[0]

    async def test_a_skipped_civil_date_is_not_covered(self) -> None:
        """The fabricated instant — ``2011-12-30T00:00-10:00`` — falls inside a bound
        spanning that day in UTC, so a reading that kept it would ``ALLOW``."""
        gate = self._gate(
            starts_at=datetime(2011, 12, 30, tzinfo=UTC),
            ends_at=datetime(2011, 12, 31, tzinfo=UTC),
        )
        ruling = await gate.decide(request(binding(SITE), tool=PERIOD_TOOL, stay_from="2011-12-30"))
        assert ruling.outcome is PermissionOutcome.CONFIRM

    @pytest.mark.parametrize("stay_from", ["2011-12-29", "2011-12-31"])
    async def test_the_days_either_side_are_read_exactly_as_before(self, stay_from: str) -> None:
        """The round trip is the whole test, so an ordinary date is untouched by it.

        Stated beside the arm above because a lane that refused every date in a zone
        with any transition would have made the calendar-date arm unusable rather
        than fail-closed.
        """
        gate = self._gate(
            starts_at=datetime(2011, 12, 28, tzinfo=UTC),
            ends_at=datetime(2012, 1, 2, tzinfo=UTC),
        )
        ruling = await gate.decide(request(binding(SITE), tool=PERIOD_TOOL, stay_from=stay_from))
        assert ruling.outcome is PermissionOutcome.ALLOW


class TestTheReadingIsTotalAtTheRepresentableBoundary:
    """§4: *"every failure of it is a refusal to cover, **never an exception out of
    ``decide``**"*.

    A reading that raised would take down a ruling that owed a ``CONFIRM`` — and
    ``OverflowError`` is neither a ``ValueError`` nor an ``AssistantError``, so it
    would leave the policy's own error boundary through a hole rather than reaching
    a caller's fail-closed branch.
    """

    @staticmethod
    def _gate(zone: str) -> ThresholdActionPolicy:
        return policy(
            live(
                tool=PERIOD_TOOL,
                coverage=(
                    coverage_member(
                        BoundKind.PERIOD,
                        bound=period_bound(
                            starts_at=AT - timedelta(days=1),
                            ends_at=AT + timedelta(days=1),
                            timezone=zone,
                        ),
                    ),
                ),
            )
        )[0]

    @pytest.mark.parametrize(
        ("stay_from", "zone"),
        [
            pytest.param("0001-01-01", "Etc/GMT-14", id="year-one-ahead-of-utc"),
            pytest.param("9999-12-31", "Etc/GMT+12", id="year-nine-thousand-behind-utc"),
        ],
    )
    async def test_a_date_at_the_representable_boundary_is_a_refusal_and_not_a_raise(
        self, stay_from: str, zone: str
    ) -> None:
        """``0001-01-01`` in a zone ahead of UTC converts to a **year-0** instant,
        which ``datetime`` cannot hold; the far end is the mirror of it."""
        ruling = await self._gate(zone).decide(
            request(binding(SITE), tool=PERIOD_TOOL, stay_from=stay_from)
        )
        assert ruling.outcome is PermissionOutcome.CONFIRM


class TestALeapSecondIsRefusedRatherThanNormalised:
    """RFC 3339 §5.6's ``time-second`` admits ``60``; ``datetime`` cannot hold it.

    So the reading ADR-0254 §4 states over *"the instant it denotes"* cannot be
    taken, and §4's own totality clause is the answer: *"every failure of it is a
    refusal to cover"*. The refusal costs a question rather than authorising
    anything.

    **What is refused with it is normalising the value onto the subset.** ADR-0140
    ruled this exact question for a delivery header, and its reasoning is the
    corpus's: a lane *"does not roll a leap second to the following instant"* or
    clamp it to ``:59``, because *"three incompatible outcomes, each claiming
    compliance"* is what delegating the decision produces.
    """

    async def test_a_leap_second_inside_the_bound_is_not_covered(self) -> None:
        """Both the instant before it and the instant after it **are** covered, so a
        reading that rolled or clamped would have covered this too."""
        gate, _, _ = policy(
            live(
                tool=PERIOD_TOOL,
                coverage=(
                    coverage_member(
                        BoundKind.PERIOD,
                        bound=period_bound(
                            starts_at=datetime(2016, 12, 31, tzinfo=UTC),
                            ends_at=datetime(2017, 1, 2, tzinfo=UTC),
                        ),
                    ),
                ),
            )
        )
        ruling = await gate.decide(
            request(binding(SITE), tool=PERIOD_TOOL, stay_from="2016-12-31T23:59:60Z")
        )
        assert ruling.outcome is PermissionOutcome.CONFIRM

    @pytest.mark.parametrize("stay_from", ["2016-12-31T23:59:59Z", "2017-01-01T00:00:00Z"])
    async def test_the_instants_either_side_of_it_are_covered(self, stay_from: str) -> None:
        """The narrowing is the leap second and nothing else."""
        gate, _, _ = policy(
            live(
                tool=PERIOD_TOOL,
                coverage=(
                    coverage_member(
                        BoundKind.PERIOD,
                        bound=period_bound(
                            starts_at=datetime(2016, 12, 31, tzinfo=UTC),
                            ends_at=datetime(2017, 1, 2, tzinfo=UTC),
                        ),
                    ),
                ),
            )
        )
        ruling = await gate.decide(request(binding(SITE), tool=PERIOD_TOOL, stay_from=stay_from))
        assert ruling.outcome is PermissionOutcome.ALLOW


class TestRfc3339sUnknownLocalOffsetSpelling:
    """``-00:00`` denotes the same **instant** as ``+00:00``, and §4 compares instants.

    RFC 3339 §4.3 is explicit about what that spelling means: *"If the time in UTC
    is known, but the offset to local time is unknown, this can be represented with
    an offset of '-00:00'."* What is unknown is the **local offset**, not the
    instant — and ADR-0254 §4's ``PERIOD`` reading is stated over *"the instant it
    denotes"*, with the zone reaching only the **calendar-date** arm.

    So a value spelled this way is not the unproven comparison §4 refuses; it is an
    RFC 3339 date-time carrying an offset whose instant is determinate. Pinned
    rather than left implicit, because an adversarial round read it the other way
    and the reading is worth being deliberate about.
    """

    async def test_an_unknown_local_offset_is_read_as_the_instant_it_denotes(
        self,
    ) -> None:
        """Inside the bound → covered; outside it → not, on the instant alone."""
        gate, _, _ = policy(
            live(
                tool=PERIOD_TOOL,
                coverage=(
                    coverage_member(
                        BoundKind.PERIOD,
                        bound=period_bound(starts_at=AT, ends_at=AT + timedelta(hours=1)),
                    ),
                ),
            )
        )
        inside = await gate.decide(
            request(binding(SITE), tool=PERIOD_TOOL, stay_from="2026-09-13T09:30:00-00:00")
        )
        assert inside.outcome is PermissionOutcome.ALLOW
        gate, _, _ = policy(
            live(
                tool=PERIOD_TOOL,
                coverage=(
                    coverage_member(
                        BoundKind.PERIOD,
                        bound=period_bound(starts_at=AT, ends_at=AT + timedelta(hours=1)),
                    ),
                ),
            )
        )
        outside = await gate.decide(
            request(binding(SITE), tool=PERIOD_TOOL, stay_from="2026-09-13T11:30:00-00:00")
        )
        assert outside.outcome is PermissionOutcome.CONFIRM


class TestARulingIsDecidedOverOneObservationOfItsRequest:
    """ADR-0065, over the suspension ADR-0254 §6's seam read introduces.

    ``decide`` awaits ``live_for``, and a frozen model is rewritable through
    ``__dict__`` — so a caller holding the request can replace its goal, its
    arguments or its binding while the seam is out. The corpus already answers this
    one seam over: ``permissions/recipient_grants.py::covering`` *"reads every value
    the comparison is decided over before the first await"* and compares the
    detached capture afterwards. These arms hold the seam open and rewrite the
    request inside it.

    **Every one of them asserts the ruling the request *as presented* earns.** A
    torn ruling is not merely the wrong answer for one of the two requests; it is an
    answer to a third request that was never made, and the fail-closed direction is
    the one the user was going to be asked about anyway.
    """

    async def test_a_goal_and_arguments_rewritten_mid_ruling_earn_no_route_d(self) -> None:
        """The row is selected for the goal read on the way in; the arguments must
        not be the ones read on the way out.

        The row covers ``amount`` up to 60. The request as presented asks for 80
        under that goal, which §3's condition 6 does not cover, so the bar fires and
        the ruling is ``CONFIRM``. Rewriting the goal to one with no row at all and
        the amount to one inside the bound, while ``live_for`` is suspended, must not
        turn that into an ``ALLOW`` citing a record about **neither** request.
        """
        gate, authorizations, _ = policy(live(id="a1"))
        assert authorizations is not None
        action = request(binding(SITE), amount="80", currency="GBP")
        held = authorizations.suspend_next_operation()
        ruling = asyncio.ensure_future(gate.decide(action))
        await held.reached()
        action.__dict__["goal"] = OTHER_GOAL
        action.__dict__["parameters"] = {**action.parameters, "amount": "50"}
        held.release()
        decided = await ruling
        assert decided.outcome is PermissionOutcome.CONFIRM
        assert (decided.authorised_by, decided.authorised_goal) == (None, None)

    async def test_the_request_as_presented_and_as_rewritten_both_draw_confirm(self) -> None:
        """Neither of the two requests is covered, which is what makes the arm above
        a tear rather than a disagreement about which answer is right."""
        gate, _, _ = policy(live(id="a1"))
        presented = await gate.decide(request(binding(SITE), amount="80", currency="GBP"))
        assert presented.outcome is PermissionOutcome.CONFIRM
        gate, _, _ = policy(live(id="a1"))
        rewritten = await gate.decide(
            request(binding(SITE), goal=OTHER_GOAL, amount="50", currency="GBP")
        )
        assert rewritten.outcome is PermissionOutcome.CONFIRM

    async def test_a_nested_argument_rewritten_mid_ruling_earns_no_route_d(self) -> None:
        """The capture is detached **all the way down**, not only at the top.

        `FrozenDict` holds its pairs in one ``__slots__`` attribute and refuses
        assignment, which ``object.__setattr__(nested, "_items", …)`` goes straight
        past. A ``dict(request.parameters)`` would leave that nested mapping shared
        with the caller, so every comparison taken after the authorization seam
        suspended would read the value as **rewritten** rather than as presented.

        **Stated over the capture rather than over the ruling, and ADR-0266 §3 is
        why.** A ``fixed`` value is now validated against its member's kind — a
        ``TERMS`` one is a JSON string and a ``PERIOD`` one a date — so no member
        can hold a nested mapping and no comparison of *this* tree reads one. The
        property the capture carries is unchanged and is what every later comparison
        rests on, so it is asserted where it still lives: the captured value does not
        move when the caller's does.
        """
        action = request(binding(SITE), prefs=FrozenDict({"x": "bad"}))
        captured = coverage_subject(action)
        object.__setattr__(action.parameters["prefs"], "_items", (("x", "ok"),))
        presented = action.parameters["prefs"]
        held = captured.parameters["prefs"]
        assert isinstance(presented, FrozenDict)
        assert isinstance(held, FrozenDict)
        assert dict(presented) == {"x": "ok"}
        assert dict(held) == {"x": "bad"}

    async def test_a_binding_rewritten_mid_ruling_earns_no_route_b(self) -> None:
        """The grant seam takes its own subject at its own first executed line, which
        since §6 is **after** this suspension — so the request handed to it is checked
        against the observation this ruling was decided over first.

        The grant covers :data:`SITE`. The request as presented discloses to
        :data:`OTHER_SITE`, which no grant covers, and the ruling is the ``CONFIRM``
        the disclosure floor reached. Swapping the binding for one at ``SITE`` while
        ``live_for`` is suspended must not buy the grant.
        """
        gate, authorizations, recipients = policy(recipients=grants())
        assert authorizations is not None
        assert recipients is not None
        action = request(binding(OTHER_SITE), amount="50", currency="GBP")
        held = authorizations.suspend_next_operation()
        ruling = asyncio.ensure_future(gate.decide(action))
        await held.reached()
        action.__dict__["egress_binding"] = binding(SITE)
        held.release()
        decided = await ruling
        assert decided.outcome is PermissionOutcome.CONFIRM
        assert decided.authorised_by is None

    async def test_the_grant_that_arm_refuses_is_reachable_when_it_is_presented(self) -> None:
        """The control: the same policy, the same grant, the binding presented rather
        than substituted — ``ALLOW`` on route (b)."""
        gate, _, recipients = policy(recipients=grants())
        assert recipients is not None
        decided = await gate.decide(booking())
        assert decided.outcome is PermissionOutcome.ALLOW
        assert decided.authorised_by == "g-1"
        assert recipients.call_count == 1

    async def test_a_request_torn_past_reading_mid_ruling_earns_no_grant(self) -> None:
        """A request that cannot be re-read at all is answered the way a seam fault
        is — no grant, and the ``CONFIRM`` the table already reached.

        ``request.__dict__.pop("egress_binding")`` leaves a frozen model with no such
        attribute, which is ``_coverage_subject``'s own case one seam over: *"a
        request that cannot be read as one at all is answered the same way, which is
        the fail-closed direction"*.

        **What this arm proves is that a ruling comes back at all.** The check above
        it re-reads the request, and an unguarded re-read would replace this
        ``CONFIRM`` with an ``AttributeError`` leaving ``decide`` — a builtin out of
        the policy's own error boundary, on the path that exists to make a mid-flight
        rewrite fail closed.
        """
        gate, authorizations, recipients = policy(recipients=grants())
        assert authorizations is not None
        assert recipients is not None
        action = booking()
        held = authorizations.suspend_next_operation()
        ruling = asyncio.ensure_future(gate.decide(action))
        await held.reached()
        action.__dict__.pop("egress_binding")
        held.release()
        decided = await ruling
        assert decided.outcome is PermissionOutcome.CONFIRM
        assert decided.authorised_by is None
