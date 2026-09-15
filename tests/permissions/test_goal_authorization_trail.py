"""``AuditTrail.record``'s route-(d) invariant, and the four-route discriminator.

ADR-0254 §7's ten checks, each asserted **independently**: the arm submits a row
with every other check passing and the one under test failing, which is the only
shape that proves the trail refuses on *that* check rather than on a neighbour.

The arm numbers below are ADR-0254 §20's.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from authorization_builders import (
    AT,
    EXPIRES,
    GOAL,
    NOW,
    OTHER_ACCOUNT,
    OTHER_GOAL,
    OTHER_SITE,
    SITE,
    TOOL,
    binding,
    request,
    route_d_decision,
)
from permission_builders import action, decision, ruling
from recipient_builders import binding as smtp_binding
from recipient_builders import route_b_decision

from ai_assistant.core.errors import InvalidAuthorisationError
from ai_assistant.core.types import (
    AuthorizationDisposition,
    AuthorizationSettlement,
    BoundKind,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    SpanCoverage,
)
from ai_assistant.permissions.audit import SqliteAuditTrail
from ai_assistant.testing import (
    FakeAuthorizationResolution,
    FakeRecipientGrantResolution,
    authorization,
    coverage_member,
    money_bound,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.core.types import Authorization


def established(**overrides: object) -> Authorization:
    """A row the trail may resolve a route-(d) pointer to.

    Written ``PROPOSED`` and settled by the seam below, which is ADR-0254 §1's rule
    that a row carrying a ``confirmation`` *"reaches every later disposition through
    ``settle`` alone"*.
    """
    scripted: dict[str, object] = {
        "id": "a1",
        "coverage": (
            # **Two members of two kinds** (ADR-0266 §3), which is what a row may
            # carry: one per kind and no two of one. The fixed one is stated at
            # ``TERMS`` because that is the kind whose reading compares a string.
            coverage_member(BoundKind.TERMS, fixed=SITE),
            coverage_member(BoundKind.MONEY, bound=money_bound("60")),
        ),
    }
    scripted.update(overrides)
    return authorization(**scripted)  # type: ignore[arg-type]  # the builder's own keys


class _Trail:
    """A trail over one authorization seam, so a case can settle the row mid-flight."""

    def __init__(self, path: Path, *rows: Authorization, establish: bool = True) -> None:
        """Build the seam, establish every row, and open the trail over it.

        ``establish=False`` leaves a proposal standing, which is the only way to
        reach the two dispositions §1's graph admits from ``PROPOSED`` alone.
        """
        self.authorizations = FakeAuthorizationResolution(rows)
        for row in rows:
            if establish and row.disposition is AuthorizationDisposition.PROPOSED:
                self.authorizations.settle(
                    row.id, to=AuthorizationDisposition.ESTABLISHED, settled_at=AT
                )
        self.trail = SqliteAuditTrail(
            path=path,
            recipient_grants=FakeRecipientGrantResolution(),
            authorizations=self.authorizations,
        )

    def close(self) -> None:
        """Release the file handle."""
        self.trail.close()


@pytest.fixture
def path(tmp_path: Path) -> Path:
    """Where this case's trail lives."""
    return tmp_path / "trail.sqlite3"


async def _refuses(held: _Trail, submitted: PermissionDecision, because: str) -> None:
    """Assert ``record`` refuses ``submitted``, and that nothing was written.

    A refusal that appended the row and *then* raised would leave the trail holding
    a route-(d) ``ALLOW`` ADR-0254 §7 says is unrecordable, which is exactly the
    state the invariant exists to make unreachable.
    """
    with pytest.raises(InvalidAuthorisationError, match=because):
        await held.trail.record(submitted)
    assert await held.trail.recent() == []


class TestTheFourRouteDiscriminator:
    """Arm 28: *"total, from the row alone, with **no store read**"*."""

    async def test_a_route_d_row_is_accepted_on_all_ten_checks(self, path: Path) -> None:
        """The positive arm, and the baseline every refusal below varies one field of."""
        row = established()
        held = _Trail(path, row)
        try:
            settled = await held.authorizations.resolve("a1")
            assert settled is not None
            await held.trail.record(route_d_decision(settled, binding(SITE)))
            assert [one.id for one in await held.trail.recent()] == ["d-route-d"]
        finally:
            held.close()

    async def test_the_route_b_classification_is_unchanged_from_origin_main(
        self, path: Path
    ) -> None:
        """Arm 28: *"the route-(b) and route-(c) classifications unchanged"*.

        §7 narrows ADR-0247 §2's discriminator *"in its route-(b) limb alone, by one
        conjunct"*: a digest **and** no goal scope. A row carrying a digest and no
        scope is still route (b) and is still held to ADR-0193 §6's eight checks —
        here, refused because this trail's grant seam holds nothing.
        """
        held = _Trail(path)
        try:
            with pytest.raises(InvalidAuthorisationError, match="not an outstanding grant"):
                await held.trail.record(
                    route_b_decision(
                        grant_id="g-1", subject="0" * 64, bound=smtp_binding("alice@example.com")
                    )
                )
        finally:
            held.close()

    async def test_a_route_c_row_is_still_admitted_on_its_own_two_conditions(
        self, path: Path
    ) -> None:
        """Arm 28: route (c)'s digest-free limb is **untouched** (ADR-0247 §2)."""
        held = _Trail(path)
        try:
            bound = binding(SITE, closed_loop=True)
            await held.trail.record(
                decision(
                    "d-route-c",
                    request=request(bound),
                    ruled=ruling(PermissionOutcome.ALLOW, authorised_by=bound.account.reference),
                    decided_at=NOW,
                )
            )
            assert [one.id for one in await held.trail.recent()] == ["d-route-c"]
        finally:
            held.close()

    async def test_a_goal_scope_with_no_digest_is_in_none_of_the_four_routes(
        self, path: Path
    ) -> None:
        """§7's partition admits a goal scope on a **route-(d)** row alone.

        The ordering matters: the digest-free branch runs **after** this one, so such
        a row is refused rather than classified as route (c).
        """
        row = established()
        held = _Trail(path, row)
        try:
            settled = await held.authorizations.resolve("a1")
            assert settled is not None
            scoped = route_d_decision(settled, binding(SITE))
            bare = PermissionDecision.model_construct(
                **{
                    **scoped.model_dump(),
                    "ruling": PermissionRuling.model_construct(
                        outcome=PermissionOutcome.ALLOW,
                        reason=scoped.ruling.reason,
                        authorised_by=scoped.ruling.authorised_by,
                        authorised_subject=None,
                        authorised_goal=scoped.ruling.authorised_goal,
                    ),
                    "tool": scoped.tool,
                    "egress_binding": scoped.egress_binding,
                }
            )
            with pytest.raises(InvalidAuthorisationError, match="fingerprints none"):
                await held.trail.record(bare)
        finally:
            held.close()

    async def test_a_route_a_resolution_carrying_a_goal_scope_is_refused(self, path: Path) -> None:
        """§7: ``authorised_goal`` *"is set **only** on a route-(d) ``ALLOW``"*.

        Route (a) is *"``resolves`` set, ``authorised_by`` equal to it"* in §7's
        partition, and carries no goal scope. The resolving branch returns before
        anything below looks at the scope, and ``_check_authorisation`` checks the
        **pointer** alone — so without a refusal here a durable row would carry a
        goal scope on a route no clause of §7 validates a scope on, and the
        four-route partition would stop being a partition.
        """
        held = _Trail(path)
        try:
            with pytest.raises(
                InvalidAuthorisationError, match="scopes its authorisation to a goal"
            ):
                await held.trail.record(
                    decision(
                        "d-route-a",
                        request=request(binding(SITE)),
                        ruled=ruling(
                            PermissionOutcome.ALLOW, authorised_by="d-0", authorised_goal=GOAL
                        ),
                        resolves="d-0",
                        decided_at=NOW,
                    )
                )
        finally:
            held.close()

    @pytest.mark.parametrize(
        ("named", "subject"),
        [("g-1", "0" * 64), ("g-1", None)],
        ids=["with a digest", "without one"],
    )
    async def test_a_goal_scope_on_a_decision_recording_no_egress_call_is_refused(
        self, path: Path, named: str, subject: str | None
    ) -> None:
        """§7: route (d) is an **egress** route, so a non-egress row is in no route.

        ``_rests_on_a_standing_authorisation`` is deliberately narrow — *"a decision
        with no ``egress_binding`` is not an egress call"* — and returns ``False``
        here, so without a refusal the row would be written carrying a goal scope
        nothing resolved and nothing compared. ``PermissionRuling`` cannot take this
        check: it refuses a scope with no pointer and leaves *"which of the four
        shapes is owed"* to ``record``, *"the only component that can see
        ``resolves`` and ``egress_binding``"*.
        """
        held = _Trail(path)
        try:
            await _refuses(
                held,
                decision(
                    "d-no-egress",
                    request=action(),
                    ruled=ruling(
                        PermissionOutcome.ALLOW,
                        authorised_by=named,
                        authorised_subject=subject,
                        authorised_goal=GOAL,
                    ),
                    decided_at=NOW,
                ),
                "in none of ADR-0254",
            )
        finally:
            held.close()

    async def test_no_row_predating_this_decision_can_be_classified_as_route_d(
        self, path: Path
    ) -> None:
        """§7: ``authorised_goal`` **did not exist to be set**.

        So every stored route-(b) row stays route (b), and ADR-0193 §11's reserved
        digest-free pointer stays where ADR-0247 §2 left it.
        """
        held = _Trail(path)
        try:
            assert (
                route_b_decision(
                    grant_id="g-1", subject="0" * 64, bound=smtp_binding("alice@example.com")
                ).ruling.authorised_goal
                is None
            )
        finally:
            held.close()


class TestTheTenChecks:
    """Arm 29: each of §7's ten, independently."""

    @pytest.fixture
    def held(self, path: Path) -> _Trail:
        """A trail whose seam holds one established row."""
        return _Trail(path, established())

    async def test_a_pointer_resolve_answers_none_for(self, held: _Trail) -> None:
        """The resolution read, which is the first of the eight §7 takes from §6."""
        settled = await held.authorizations.resolve("a1")
        assert settled is not None
        try:
            await _refuses(
                held,
                route_d_decision(settled, binding(SITE), authorised_by="nobody"),
                "which the store does not hold",
            )
        finally:
            held.close()

    @pytest.mark.parametrize(
        "disposition",
        [AuthorizationDisposition.REVOKED, AuthorizationDisposition.SUPERSEDED],
    )
    async def test_a_row_that_left_established_between_the_ruling_and_the_write(
        self, held: _Trail, disposition: AuthorizationDisposition
    ) -> None:
        """§7's first check: *"the existence, the kind, the unrevoked, the
        unsuperseded and the answered check at once"*.

        **This is arm 4 as well** — a revocation taken between ``live_for`` and
        ``record``'s resolution read refuses the write, *"for the row behind
        **every** argument"*. A revocation *"bites twice"* (§13), and this is the
        second bite; the residual window runs from this read to the execution and no
        clause rounds it to zero.
        """
        settled = await held.authorizations.resolve("a1")
        assert settled is not None
        submitted = route_d_decision(settled, binding(SITE))
        try:
            held.authorizations.settle("a1", to=disposition, settled_at=NOW)
            await _refuses(held, submitted, "rather than ESTABLISHED")
        finally:
            held.close()

    @pytest.mark.parametrize(
        "disposition",
        [
            AuthorizationDisposition.PROPOSED,
            AuthorizationDisposition.DECLINED,
            AuthorizationDisposition.EXPIRED,
        ],
    )
    async def test_a_row_the_user_never_answered_or_refused(
        self, path: Path, disposition: AuthorizationDisposition
    ) -> None:
        """§7's first check over the three dispositions a proposal can reach.

        A ``PROPOSED`` row *"authorises nothing whatever else is true of it"*; a
        ``DECLINED`` one is the user's refusal; an ``EXPIRED`` one is the answer a
        question never got. **Every other disposition is retired and none of them is
        live**, which is why one check does the work of five.

        **The arrangement is asserted before the refusal is.** ``EXPIRED`` leaves
        ``PROPOSED`` only *"at or after the row's ``expires_at``"* (ADR-0254 §1,
        §12), so settling it at :data:`AT` is answered ``NOT_AT_SOURCE`` and leaves
        the row ``PROPOSED`` — the parameter above it, refused for its own reason,
        and a case proving nothing about a lapsed row.
        """
        row = established()
        held = _Trail(path, row, establish=False)
        try:
            if disposition is not AuthorizationDisposition.PROPOSED:
                at = EXPIRES if disposition is AuthorizationDisposition.EXPIRED else AT
                assert (
                    held.authorizations.settle("a1", to=disposition, settled_at=at)
                    is AuthorizationSettlement.SETTLED
                )
            stored = await held.authorizations.resolve("a1")
            assert stored is not None
            assert stored.disposition is disposition
            await _refuses(
                held,
                route_d_decision(stored, binding(SITE)),
                "rather than ESTABLISHED",
            )
        finally:
            held.close()

    async def test_a_settled_at_after_the_decisions_decided_at(self, held: _Trail) -> None:
        """§7: the **backdated** case — *"the policy could not have read a record
        that did not exist when it ruled"*."""
        settled = await held.authorizations.resolve("a1")
        assert settled is not None
        try:
            await _refuses(
                held,
                route_d_decision(settled, binding(SITE), at=AT - timedelta(hours=1)),
                "established after the ruling was made",
            )
        finally:
            held.close()

    async def test_equality_at_the_lower_end_is_admitted(self, held: _Trail) -> None:
        """§7: *"a coarse clock stamping a settlement and the ruling that spends it
        alike is an ordinary thing rather than a suspicious one"*."""
        settled = await held.authorizations.resolve("a1")
        assert settled is not None
        try:
            await held.trail.record(route_d_decision(settled, binding(SITE), at=AT))
            assert len(await held.trail.recent()) == 1
        finally:
            held.close()

    async def test_an_expires_at_at_or_before_the_decisions_decided_at(self, held: _Trail) -> None:
        """§7: *"a lapsed authority never sources a new ALLOW"*."""
        settled = await held.authorizations.resolve("a1")
        assert settled is not None
        try:
            await _refuses(
                held,
                route_d_decision(settled, binding(SITE), at=EXPIRES),
                "not live when the ruling was made",
            )
        finally:
            held.close()

    async def test_an_unequal_declaration(self, held: _Trail) -> None:
        """§7, §3's condition 3: *"a declaration edit re-prompts"*."""
        settled = await held.authorizations.resolve("a1")
        assert settled is not None
        try:
            await _refuses(
                held,
                route_d_decision(
                    settled,
                    binding(SITE),
                    tool=TOOL.model_copy(update={"description": "reworded"}),
                ),
                "a different declaration",
            )
        finally:
            held.close()

    async def test_an_unequal_account(self, held: _Trail) -> None:
        """§7: *"an account is two facts, identity and connection reference, and
        never one"*.

        *"A faulty policy citing an established authorization for one recipient while
        ruling on a send to another through the same declaration would otherwise pass
        every other check."*
        """
        settled = await held.authorizations.resolve("a1")
        assert settled is not None
        try:
            await _refuses(
                held,
                route_d_decision(settled, binding(SITE, account=OTHER_ACCOUNT)),
                "a different connected account",
            )
        finally:
            held.close()

    async def test_a_destination_of_the_binding_the_row_does_not_carry(self, held: _Trail) -> None:
        """§7: *"coverage is set membership and nothing looser"*."""
        settled = await held.authorizations.resolve("a1")
        assert settled is not None
        try:
            await _refuses(
                held,
                route_d_decision(settled, binding(OTHER_SITE)),
                "does not name every recipient",
            )
        finally:
            held.close()

    async def test_an_unequal_goal(self, held: _Trail) -> None:
        """§7: *"the scope is read off the record the policy's own read returned and
        is carried from nowhere else"*."""
        settled = await held.authorizations.resolve("a1")
        assert settled is not None
        try:
            await _refuses(
                held,
                route_d_decision(settled, binding(SITE), authorised_goal=OTHER_GOAL),
                "a goal the store's",
            )
        finally:
            held.close()

    async def test_a_digest_recomputed_unequal(self, held: _Trail) -> None:
        """§7: *"never taken on the decision's word"*.

        A pointer whose id was recycled after a ``clear`` resolves to a record that
        fails this comparison, which is the whole of what it is for.
        """
        settled = await held.authorizations.resolve("a1")
        assert settled is not None
        try:
            await _refuses(
                held,
                route_d_decision(settled, binding(SITE), authorised_subject="0" * 64),
                "does not match",
            )
        finally:
            held.close()

    @pytest.mark.parametrize("closed_loop", [False, True])
    async def test_a_binding_whose_coverage_is_not_not_covered(
        self, held: _Trail, closed_loop: bool
    ) -> None:
        """§7's tenth check, *"submitted directly as a ruling a faulty policy could
        have authored"*, with every other check passing.

        Refused **whatever the binding's ``closed_loop`` says** — including ``True``,
        which is route (b)'s ADR-0238 disjunct and route (c)'s eligibility and is
        **neither of them here**. *"A lane that reused route (c)'s eligibility here
        has breached this clause."*
        """
        settled = await held.authorizations.resolve("a1")
        assert settled is not None
        try:
            await _refuses(
                held,
                route_d_decision(
                    settled,
                    binding(
                        SITE,
                        closed_loop=closed_loop,
                        coverage=SpanCoverage.MODEL_ON_EVERY_PATH,
                    ),
                ),
                "over covered content",
            )
        finally:
            held.close()

    async def test_the_eleventh_check_is_asserted_absent(self, held: _Trail) -> None:
        """Arm 29's last limb: a route-(d) row whose binding carries
        ``planned_with_external_content``, every other check passing, is **accepted**.

        §6's discharge turns on coverage the trail cannot see (§7), so *"a lane that
        refused it has restored a check this decision gave up and would refuse every
        fully covered call the policy allowed"*. ADR-0193 §6's origin arm stays
        untouched on every route-(b) row.
        """
        settled = await held.authorizations.resolve("a1")
        assert settled is not None
        try:
            await held.trail.record(route_d_decision(settled, binding(SITE, external=True)))
            assert len(await held.trail.recent()) == 1
        finally:
            held.close()


class TestTheSeamTheTrailIsGivenAndWhatItCannotDo:
    """§7: *"the trail holds a **read and nothing else**"*."""

    async def test_a_trail_wired_with_no_seam_refuses_every_route_d_row(self, path: Path) -> None:
        """``_NoAuthorizations`` on ``_NoRecipientGrants``'s pattern: every pointer
        resolves to ``None`` and the row is refused — the fail-closed direction, and
        the only answer a deployment with no authorization store can give."""
        row = established()
        seam = FakeAuthorizationResolution((row,))
        seam.settle("a1", to=AuthorizationDisposition.ESTABLISHED, settled_at=AT)
        settled = await seam.resolve("a1")
        assert settled is not None
        trail = SqliteAuditTrail(path=path)
        try:
            with pytest.raises(InvalidAuthorisationError, match="does not hold"):
                await trail.record(route_d_decision(settled, binding(SITE)))
        finally:
            trail.close()

    async def test_a_seam_that_could_not_be_read_refuses_the_write(self, path: Path) -> None:
        """§7, §16: *"a component that cannot get an answer from that seam fails
        closed"*, and the fault is **raised** rather than returned — a store fault is
        not something a later duplicate-id refusal should be allowed to mask."""
        row = established()
        held = _Trail(path, row)
        settled = await held.authorizations.resolve("a1")
        assert settled is not None
        held.authorizations.fail_resolve()
        try:
            with pytest.raises(InvalidAuthorisationError, match="could not be read"):
                await held.trail.record(route_d_decision(settled, binding(SITE)))
        finally:
            held.close()

    async def test_a_route_d_row_costs_exactly_one_resolution_read(self, path: Path) -> None:
        """§7: the trail resolves **one** row, and ``authorised_by`` names one row."""
        row = established()
        held = _Trail(path, row)
        settled = await held.authorizations.resolve("a1")
        assert settled is not None
        before = held.authorizations.call_count
        try:
            await held.trail.record(route_d_decision(settled, binding(SITE)))
            assert held.authorizations.call_count == before + 1
        finally:
            held.close()

    async def test_a_row_of_no_route_costs_no_resolution_read_at_all(self, path: Path) -> None:
        """§7's scope is narrow: an ordinary ``CONFIRM`` is outside it entirely."""
        held = _Trail(path, established())
        before = held.authorizations.call_count
        try:
            await held.trail.record(
                decision(
                    "d-confirm",
                    request=request(binding(SITE)),
                    ruled=ruling(PermissionOutcome.CONFIRM),
                    decided_at=NOW,
                )
            )
            assert held.authorizations.call_count == before
        finally:
            held.close()

    async def test_the_trail_revalidates_no_stored_row(self, path: Path) -> None:
        """§7: *"No stored row is revalidated, rewritten or re-derived."*

        ``AuditTrail.record``'s invariants are **write-path** checks: a decision
        written before this decision keeps its ``authorised_by``, its digest and its
        recorded meaning, and no read path applies route (d)'s checks to it.
        """
        row = established()
        held = _Trail(path, row)
        settled = await held.authorizations.resolve("a1")
        assert settled is not None
        try:
            await held.trail.record(route_d_decision(settled, binding(SITE)))
            held.authorizations.settle("a1", to=AuthorizationDisposition.REVOKED, settled_at=NOW)
            recorded = await held.trail.recent()
            assert [one.ruling.authorised_goal for one in recorded] == [GOAL]
            assert [one.ruling.authorised_by for one in recorded] == ["a1"]
        finally:
            held.close()


class TestTheAccountAndDestinationChecksAreNotThePayloadComparison:
    """§7: *"it needs no extra data, no seam and no arguments, only the binding the
    decision already carries"*."""

    async def test_the_trail_reads_no_clock_and_decides_both_ends_against_decided_at(
        self, path: Path
    ) -> None:
        """§7: *"``record`` reads **no clock**"*.

        A row live at the instant the ruling was made is admitted however long after
        that the write happens, and one that had lapsed by then is refused however
        soon — both decided against the decision's own ``decided_at``.
        """
        held = _Trail(path, established())
        settled = await held.authorizations.resolve("a1")
        assert settled is not None
        try:
            await held.trail.record(
                route_d_decision(settled, binding(SITE), at=AT + timedelta(minutes=1))
            )
            with pytest.raises(InvalidAuthorisationError, match="not live when the ruling"):
                await held.trail.record(
                    route_d_decision(
                        settled,
                        binding(SITE),
                        decision_id="d-2",
                        at=EXPIRES + timedelta(days=7),
                    )
                )
        finally:
            held.close()

    async def test_a_route_d_row_over_the_account_member_alone_is_admitted(
        self, path: Path
    ) -> None:
        """§7's destination check is **containment**, so a call reaching only the
        connected account is covered by a row naming it."""
        from authorization_builders import account_member  # noqa: PLC0415 — one case needs it

        row = established(
            id="a3",
            destinations=(account_member(),),
            coverage=(coverage_member(BoundKind.TERMS, fixed="x"),),
        )
        held = _Trail(path, row)
        settled = await held.authorizations.resolve("a3")
        assert settled is not None
        try:
            await held.trail.record(route_d_decision(settled, binding()))
            assert len(await held.trail.recent()) == 1
        finally:
            held.close()
