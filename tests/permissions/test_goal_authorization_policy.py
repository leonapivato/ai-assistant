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

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from action_policy_contract import ActionPolicyContract
from authorization_builders import (
    ACCOUNT,
    AT,
    EXPIRES,
    GOAL,
    NOW,
    OTHER_ACCOUNT,
    OTHER_SITE,
    SHARED_CLOCK,
    SITE,
    TOOL,
    MovableClock,
    account_member,
    binding,
    member,
    request,
)

from ai_assistant.core.config import Settings
from ai_assistant.core.logging import configure_logging
from ai_assistant.core.types import (
    AuthorizationDisposition,
    CostBasis,
    PermissionOutcome,
    Reversibility,
    RiskLevel,
    SpanCoverage,
    ToolCost,
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
        ToolDefinition,
    )


def live(
    *, coverage: tuple[CoverageMember, ...] | None = None, site: bool = True, **overrides: object
) -> Authorization:
    """A path-(i) **proposal** the seam below then establishes.

    **The destination-bearing argument is covered too, and that is not a
    convenience.** ADR-0254 §3's condition 6 is over *every* user-facing argument
    of the request, and a booking call carries ``site`` as an ordinary argument as
    well as a destination — so a row naming only ``amount`` and ``currency`` covers
    nothing, whatever else holds. Prepending it here is what lets each case below
    vary the member it is actually about. ``site=False`` is the empty-coverage case,
    where the request carries no user-facing argument at all.

    The seam seeds through the fake's own write path, which holds a row carrying a
    ``confirmation`` to ``PROPOSED`` — ADR-0254 §1's rule that such a row *"reaches
    every later disposition through ``settle`` alone"*. So a case that wants a live
    record arranges the same two acts production does, rather than writing a state
    the store would refuse.
    """
    members = coverage if coverage is not None else _BOOKING_COVERAGE
    if site:
        members = (coverage_member("site", fixed=SITE), *members)
    return authorization(coverage=members, **overrides)  # type: ignore[arg-type]  # its own keys


#: What a booking act bounds unless a case says otherwise: the price and its
#: currency, which is the pair §2's ``MONEY`` rule and §4's currency conjunct are
#: both stated over.
_BOOKING_COVERAGE: tuple[CoverageMember, ...] = (
    coverage_member("amount", bound=money_bound("60")),
    coverage_member("currency", fixed="GBP"),
)


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
    """The concrete call every case rules on: one destination, and its arguments."""
    return request(binding(SITE), amount="50", currency="GBP", **parameters)  # type: ignore[arg-type]


class TestExistingAuthorizationCoversTheConcreteAction:
    """Arm 1: the case the milestone exists for."""

    async def test_route_d_allows_and_names_the_record(self) -> None:
        """*"``authorised_by`` the record's id, ``authorised_subject`` its recomputed
        digest, ``authorised_goal`` its goal, ``RecipientGrants.covering`` called
        **zero** times, and no redundant approval."*"""
        row = live(
            id="a1",
            coverage=(
                coverage_member("amount", bound=money_bound("60")),
                coverage_member("currency", fixed="GBP"),
            ),
        )
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
                coverage=(
                    coverage_member("amount", bound=money_bound("60")),
                    coverage_member("currency", fixed="GBP"),
                ),
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
        row = live(
            id="a1",
            coverage=(
                coverage_member("amount", bound=money_bound("60")),
                coverage_member("currency", fixed="GBP"),
            ),
        )
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
    """Arms 5, 6, 7, 10, 11 and 12: every reading is total and fail-closed."""

    @pytest.mark.parametrize(
        ("amount", "covered"),
        [("60", True), ("59", True), ("61", False), ("10", True)],
    )
    async def test_a_money_bound_is_inclusive_at_both_ends(
        self, amount: str, covered: bool
    ) -> None:
        """Arm 5: at, below and above ``maximum``; and at ``minimum``."""
        gate, _, _ = policy(
            live(
                coverage=(
                    coverage_member("amount", bound=money_bound("60", minimum="10")),
                    coverage_member("currency", fixed="GBP"),
                )
            )
        )
        ruling = await gate.decide(request(binding(SITE), amount=amount, currency="GBP"))
        assert (ruling.outcome is PermissionOutcome.ALLOW) is covered

    @pytest.mark.parametrize("amount", [50.0, 50.5, 0.0])
    async def test_a_price_as_a_json_float_is_never_covered(self, amount: float) -> None:
        """Arm 6: *"whatever its magnitude"*.

        *"A binary float is not a price, and comparing one against a decimal bound
        is precisely the unproven comparison ADR-0148 §2 refuses by default: the
        answer is not to round, to quantise or to pick a tolerance, it is to refuse
        and ask."*
        """
        gate, _, _ = policy(
            live(
                coverage=(
                    coverage_member("amount", bound=money_bound("60")),
                    coverage_member("currency", fixed="GBP"),
                )
            )
        )
        ruling = await gate.decide(request(binding(SITE), amount=amount, currency="GBP"))
        assert ruling.outcome is PermissionOutcome.CONFIRM

    async def test_a_json_boolean_is_never_covered_by_a_money_bound(self) -> None:
        """§4: ``bool`` is an ``int`` in Python and ``True`` would otherwise read as one."""
        gate, _, _ = policy(
            live(
                coverage=(
                    coverage_member("amount", bound=money_bound("60")),
                    coverage_member("currency", fixed="GBP"),
                )
            )
        )
        ruling = await gate.decide(request(binding(SITE), amount=True, currency="GBP"))
        assert ruling.outcome is PermissionOutcome.CONFIRM

    @pytest.mark.parametrize(
        ("value", "covered"),
        [("A", True), ("a", False), ("A ", False), (60, False), ("60", True)],
    )
    async def test_a_fixed_value_is_compared_by_the_canonical_json_encoding(
        self, value: object, covered: bool
    ) -> None:
        """Arm 7: *"a fixed value differing by one byte"*, and a number rendered as a
        string where the member holds a number."""
        fixed: object = "A" if isinstance(value, str) and not value.isdigit() else "60"
        gate, _, _ = policy(
            live(coverage=(coverage_member("site_code", fixed=fixed),))  # type: ignore[arg-type]
        )
        ruling = await gate.decide(request(binding(SITE), site_code=value))  # type: ignore[arg-type]
        assert (ruling.outcome is PermissionOutcome.ALLOW) is covered

    @pytest.mark.parametrize(
        ("stated", "covered"),
        [("GBP", True), ("KWD", False), (60, False)],
    )
    async def test_the_money_bounds_currency_conjunct_is_taken_over_the_request(
        self, stated: object, covered: bool
    ) -> None:
        """Arm 10, arm 18's second half: *"stated over the **concrete request**
        rather than over the row"*.

        *"A row whose currency member says one thing and whose request says another
        covers nothing rather than covering the wrong amount of the wrong money"* —
        whatever the declaration's schema admits, because no schema is consulted.

        The row bounds the currency argument by a ``TERMS`` member naming **both**
        codes, so condition 6 holds over it and the only thing left to fail is §4's
        conjunct. A row that merely *fixed* ``"GBP"`` would fail the fixed-value
        comparison instead, and the arm would be testing the wrong rule.
        """
        gate, _, _ = policy(
            live(
                coverage=(
                    coverage_member("amount", bound=money_bound("60", currency_argument="ccy")),
                    coverage_member("ccy", bound=terms_bound("GBP", "KWD")),
                )
            )
        )
        ruling = await gate.decide(request(binding(SITE), amount="50", ccy=stated))  # type: ignore[arg-type]
        assert (ruling.outcome is PermissionOutcome.ALLOW) is covered

    async def test_a_request_carrying_no_value_at_the_currency_argument_is_not_covered(
        self,
    ) -> None:
        """Arm 10's first limb: the conjunct is stated over the **request**, so a
        call that names the amount and not its currency is covered by nothing.

        The bound's ``currency_argument`` names a key the row's coverage does not,
        so condition 6's key sets agree and what fails is §4's reading alone.
        """
        gate, _, _ = policy(
            live(
                coverage=(
                    coverage_member("amount", bound=money_bound("60", currency_argument="ccy")),
                )
            )
        )
        ruling = await gate.decide(request(binding(SITE), amount="50"))
        assert ruling.outcome is PermissionOutcome.CONFIRM

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
                coverage=(
                    coverage_member(
                        "stay_from",
                        bound=period_bound(starts_at=AT, ends_at=AT + timedelta(hours=12)),
                    ),
                )
            )
        )
        ruling = await gate.decide(request(binding(SITE), stay_from=stay_from))
        assert (ruling.outcome is PermissionOutcome.ALLOW) is covered

    async def test_a_calendar_date_is_read_in_the_bounds_own_zone(self) -> None:
        """§4: *"A calendar date denotes the **start of that day in the bound's own
        ``timezone``**, and the zone is read off the bound rather than off
        ``Settings``"* — two recorded values, and no configuration at the moment the
        comparison is taken."""
        gate, _, _ = policy(
            live(
                coverage=(
                    coverage_member(
                        "stay_from",
                        bound=period_bound(
                            starts_at=AT - timedelta(days=1),
                            ends_at=AT + timedelta(days=1),
                            timezone="Europe/London",
                        ),
                    ),
                )
            )
        )
        ruling = await gate.decide(request(binding(SITE), stay_from="2026-09-13"))
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
        gate, _, _ = policy(
            live(coverage=(coverage_member("terms", bound=terms_bound("flexible")),))
        )
        ruling = await gate.decide(request(binding(SITE), terms=value))
        assert (ruling.outcome is PermissionOutcome.ALLOW) is covered


class TestSection3sConditionsThreeFourAndFive:
    """Arms 13 and 49: the facts a grant is stated **about**, which the bar never
    fires on."""

    async def test_a_destination_outside_the_rows_set_is_not_covered(self) -> None:
        """Arm 13: coverage is **set membership** and nothing looser."""
        gate, _, recipients = policy(
            live(
                site=False,
                coverage=(
                    coverage_member("site", bound=terms_bound(SITE, OTHER_SITE)),
                    *_BOOKING_COVERAGE,
                ),
            ),
            recipients=grants(covering=False),
        )
        ruling = await gate.decide(request(binding(OTHER_SITE), amount="50", currency="GBP"))
        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert recipients is not None
        assert recipients.call_count == 1

    async def test_the_same_address_through_a_second_connected_account_is_not_covered(
        self,
    ) -> None:
        """Arm 13's second limb: ``BoundAccount``'s **two facts**, never one."""
        gate, _, _ = policy(
            live(
                coverage=(
                    coverage_member("amount", bound=money_bound("60")),
                    coverage_member("currency", fixed="GBP"),
                )
            ),
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
        gate, _, _ = policy(
            live(
                coverage=(
                    coverage_member("amount", bound=money_bound("60")),
                    coverage_member("currency", fixed="GBP"),
                )
            )
        )
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
        covered = (
            coverage_member("amount", bound=money_bound("60")),
            coverage_member("currency", fixed="GBP"),
        )
        row = live(coverage=covered)
        bound = binding(SITE)
        if mismatch == "declaration":
            row = live(
                coverage=covered,
                tool=TOOL.model_copy(update={"description": "reworded"}),
            )
        elif mismatch == "account":
            row = live(coverage=covered, account=OTHER_ACCOUNT)
        elif mismatch == "destinations":
            row = live(coverage=covered, destinations=(member(OTHER_SITE),))
        gate, _, recipients = policy(row, recipients=grants(expires_at=EXPIRES + timedelta(days=2)))
        if mismatch == "lapsed":
            clock.set(EXPIRES + timedelta(hours=1))
        ruling = await gate.decide(request(bound, amount="50", currency="GBP"))
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
        """
        row = live(
            coverage=(
                coverage_member("amount", bound=money_bound("60")),
                coverage_member("currency", fixed="GBP"),
            )
        )
        gate, _, recipients = policy(row, recipients=grants())
        ruling = await gate.decide(request(binding(SITE), amount="80", currency="GBP"))
        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert recipients is not None
        assert recipients.call_count == 0
        gate, _, recipients = policy(row, recipients=grants())
        allowed = await gate.decide(request(binding(SITE), amount="50", currency="GBP"))
        assert allowed.outcome is PermissionOutcome.ALLOW
        assert allowed.authorised_goal == GOAL

    async def test_the_bar_fires_on_an_argument_the_record_names_in_no_member(self) -> None:
        """Arm 47: *"§5's *reaches no standing route at all* and §9's *an argument no
        member names* made true of route (b) as well as of route (d)."*"""
        gate, _, recipients = policy(
            live(
                coverage=(
                    coverage_member("amount", bound=money_bound("60")),
                    coverage_member("currency", fixed="GBP"),
                )
            ),
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
        this arm"*, ``ALLOW``ing a call that drops the term the user fixed."""
        gate, _, recipients = policy(
            live(
                coverage=(
                    coverage_member("site_code", fixed="A"),
                    coverage_member("refundable_only", fixed=True),
                )
            ),
            recipients=grants(),
        )
        ruling = await gate.decide(request(binding(SITE), site_code="A"))
        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert recipients is not None
        assert recipients.call_count == 0

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
        row = live(
            coverage=(
                coverage_member("amount", bound=money_bound("60")),
                coverage_member("currency", fixed="GBP"),
            )
        )
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
        row = live(
            coverage=(
                coverage_member("amount", bound=money_bound("60")),
                coverage_member("currency", fixed="GBP"),
            )
        )
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
        gate, authorizations, _ = policy(
            live(
                coverage=(
                    coverage_member("amount", bound=money_bound("60")),
                    coverage_member("currency", fixed="GBP"),
                )
            )
        )
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
        """
        covered = (
            coverage_member("amount", bound=money_bound("60")),
            coverage_member("currency", fixed="GBP"),
        )
        gate, _, recipients = policy(live(coverage=covered), recipients=grants())
        allowed = await gate.decide(
            request(binding(SITE, external=True), amount="50", currency="GBP")
        )
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
            live(
                coverage=(
                    coverage_member("amount", bound=money_bound("60")),
                    coverage_member("currency", fixed="GBP"),
                )
            ),
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
                coverage=(
                    coverage_member("amount", bound=money_bound("60")),
                    coverage_member("currency", fixed="GBP"),
                ),
            )
        )
        ruling = await gate.decide(
            request(binding(SITE), tool=declared, amount="50", currency="GBP")
        )
        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert authorizations is not None
        assert authorizations.call_count == 0


class TestSystemSuppliedArguments:
    """Arm 68's policy half: neither covered nor asked about."""

    async def test_a_system_supplied_argument_is_covered_by_nothing_and_bars_nothing(
        self,
    ) -> None:
        """§3: condition 6 holds over the **user-facing** arguments alone."""
        declared = TOOL.model_copy(update={"system_supplied": ("idempotency_key", "locale")})
        gate, _, recipients = policy(
            live(
                tool=declared,
                coverage=(
                    coverage_member("amount", bound=money_bound("60")),
                    coverage_member("currency", fixed="GBP"),
                ),
            ),
            recipients=grants(),
        )
        ruling = await gate.decide(
            request(
                binding(SITE),
                tool=declared,
                amount="50",
                currency="GBP",
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
        gate, _, _ = policy(
            live(
                coverage=(
                    coverage_member("amount", bound=money_bound("60")),
                    coverage_member("currency", fixed="GBP"),
                )
            )
        )
        ruling = await gate.decide(booking())
        assert ruling.outcome is PermissionOutcome.ALLOW


class TestTheRecipientAuthorityAnOpeningActRestedOn:
    """Arm 70: it must still stand at every dispatch, and route (d) re-takes it."""

    def _row(self) -> Authorization:
        return opening_act(coverage=(coverage_member("site", fixed=SITE), *_BOOKING_COVERAGE))

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
                coverage=(
                    coverage_member("amount", bound=money_bound("60")),
                    coverage_member("currency", fixed="GBP"),
                ),
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
        gate, _, _ = policy(
            live(
                coverage=(
                    coverage_member("amount", bound=money_bound("60")),
                    coverage_member("currency", fixed="GBP"),
                )
            )
        )
        clock.set(AT - timedelta(hours=1))
        ruling = await gate.decide(booking())
        assert ruling.outcome is PermissionOutcome.CONFIRM

    async def test_equality_at_the_lower_end_is_live(self, clock: MovableClock) -> None:
        """Arm 71's second limb."""
        gate, _, _ = policy(
            live(
                coverage=(
                    coverage_member("amount", bound=money_bound("60")),
                    coverage_member("currency", fixed="GBP"),
                )
            )
        )
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
