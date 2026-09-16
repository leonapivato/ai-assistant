"""Shared conformance suites for the three goal-authorization Protocols (ADR-0254 §16).

Every ``GoalAuthorizations`` implementation must pass
:class:`GoalAuthorizationsContract`, every ``AuthorizationResolution`` must pass
:class:`AuthorizationResolutionContract`, and every ``GoalAuthorizationStore`` must
pass :class:`GoalAuthorizationStoreContract` — which inherits both, because a store
**is** the two narrow seams plus the ability to write and settle. A concrete test
subclasses one of them and supplies its subject fixture.

**Here rather than under ``tests/core/``.** The corpus puts a suite beside the
subsystem that implements it, and ADR-0254 §20 puts the implementation in
``permissions/``. The Protocols themselves stay in ``core``, which is what lets a
policy and a trail hold their own narrow faces by injection without either
importing ``permissions``.

**Three suites, and the cost is named rather than discovered.** One Protocol would
have cost one suite; the split costs three, and it buys the property that a policy
**cannot name** ``record`` or ``resolve`` and a trail can name neither ``record``
nor ``live_for`` — ADR-0254 §16's central clause held by ``mypy --strict`` instead
of by review. Part of the cost comes back as evidence: the two narrow suites are
bound against the **store** fake and against the durable store as well as against
their own fakes, so *"three faces, one object"* is a test rather than an assertion.

**And this suite is what holds the two statements of the invariants in step.**
``testing/`` may not import ``permissions/`` (golden rule 1), so
``_AuthorizationLog`` re-implements what ``SqliteGoalAuthorizationStore`` states;
every refusal below is asserted of both.

**What is deliberately not in here**, restated so its absence does not read as
absence from the contract. The test is whether a clause is decidable from the
store's own surface:

* **ADR-0254 §6's route (d), its bar, its ordering and its seam-read counts.**
  Obligations on ``ActionPolicy``, not on a store — no store exhibits how often a
  policy calls it. They are ``tests/permissions/test_goal_authorization_policy.py``'s.
* **§7's ten checks.** Obligations on ``AuditTrail.record``; a store exhibits none
  of them. They are ``tests/permissions/test_goal_authorization_trail.py``'s.
* **§§9 and 10's basis-against-a-recorded-turn rules, §1's three write paths as
  ``orchestration`` walks them, and §12's ladder.** All ``orchestration``'s, which
  ADR-0254 §20 assigns to **Lane 2**. What a store can see is the *shape* a path
  leaves, and that is what is asserted here.
* **ADR-0060's cancellation matrix**, for every member but two. Not among
  ADR-0254's clauses, and the implementations inherit the SQLite family's own
  ``_run_to_completion``; filed rather than half-built here. **The two exceptions
  are ``end_for_goal`` and ``clear_closure``**, where ADR-0268 §9 arm 7 owes the
  shape explicitly and *"at every call of either store member"* — so the harness
  below is built for those two and is not widened to the rest by this lane.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract bases directly.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, cast

import pytest
from authorization_builders import (
    AT,
    EXPIRES,
    GOAL,
    NOW,
    OTHER_GOAL,
    OTHER_SITE,
    SHARED_CLOCK,
    TOOL,
    MovableClock,
    member,
)

from ai_assistant.core.errors import AuthorizationError, InvalidAuthorizationError
from ai_assistant.core.types import (
    AuthorizationDisposition,
    AuthorizationOrigin,
    AuthorizationSettlement,
    BoundKind,
)
from ai_assistant.testing.cancellation import settle as settle_loop
from ai_assistant.testing.goal_authorizations import (
    authorization,
    coverage_member,
    money_bound,
    period_bound,
    terms_bound,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from contextlib import AbstractAsyncContextManager

    from ai_assistant.core.protocols import (
        AuthorizationResolution,
        GoalAuthorizations,
        GoalAuthorizationStore,
    )
    from ai_assistant.core.types import Authorization
    from ai_assistant.testing.cancellation import SuspendedMidWrite


#: What a failed cancellation case says, so a failure reads as the invariant it
#: broke rather than as an assertion number.
_RELEASED_EARLY = (
    "a cancelled call released the store's resource while the work it started was "
    "still using it (ADR-0060 §1, §3)"
)

#: The two members ADR-0268 §9 arm 7 owes the cancellation shape at, each a
#: distinct lock site. **Only these two.** This suite's module docstring records
#: that ADR-0060's matrix is filed rather than half-built here, and that stands for
#: every other member; what this decision adds is an obligation *"owed at every
#: call of either store member"*, which is these.
_ENDING_OPS: Final = ("end_for_goal", "clear_closure")

#: The widest integer SQLite binds as a parameter — the edge a durable store's own
#: storage has to reach **past**, ADR-0268 §1's watermark being an unrestricted
#: ``int``. Named so the domain arms straddle the real edge rather than a round
#: number.
_MAX_INT64: Final = 2**63 - 1

#: A magnitude past **CPython's own** integer-conversion limit — ``str(int)`` and
#: ``int(str)`` refuse anything over ``sys.get_int_max_str_digits()`` decimal digits,
#: 4300 by default. An implementation encoding the watermark in base 10 would have
#: reimposed a ceiling here and leaked a bare ``ValueError`` doing it; the limit is
#: documented as base-10-only, so a base-16 encoding is exact at every magnitude.
#: Adversarial review, round 3, ``blocker``.
_PAST_DECIMAL: Final = 16**4400


class _Deceptive(int):
    """An ``int`` subclass that answers ``<=`` with a lie, and carries its value.

    Not a contrivance for its own sake: it is the value class a denylist naming
    ``bool`` lets through, and the reason the guard it exercises is written as an
    allowlist of the exact ``int``.
    """

    def __le__(self, other: object) -> bool:
        """Answer ``False`` to every ``<=``, which is what carries it past a sign check."""
        return False


#: Every disposition that is **retired**: no edge leaves it (ADR-0254 §1). **Five
#: since ADR-0268 §2**, which makes ``GOAL_CLOSED`` the fifth.
RETIRED = (
    AuthorizationDisposition.DECLINED,
    AuthorizationDisposition.EXPIRED,
    AuthorizationDisposition.REVOKED,
    AuthorizationDisposition.SUPERSEDED,
    AuthorizationDisposition.GOAL_CLOSED,
)

#: ADR-0254 §1's **seven** edges, as ``(source, target)`` pairs — five its own, two
#: ADR-0268 §2's. Stated once so the edge cases and the non-edge cases are derived
#: from one enumeration.
EDGES = (
    (AuthorizationDisposition.PROPOSED, AuthorizationDisposition.ESTABLISHED),
    (AuthorizationDisposition.PROPOSED, AuthorizationDisposition.DECLINED),
    (AuthorizationDisposition.PROPOSED, AuthorizationDisposition.EXPIRED),
    (AuthorizationDisposition.PROPOSED, AuthorizationDisposition.GOAL_CLOSED),
    (AuthorizationDisposition.ESTABLISHED, AuthorizationDisposition.REVOKED),
    (AuthorizationDisposition.ESTABLISHED, AuthorizationDisposition.SUPERSEDED),
    (AuthorizationDisposition.ESTABLISHED, AuthorizationDisposition.GOAL_CLOSED),
)

#: Moves ADR-0254 §1's graph does **not** admit, each named so a failure says which.
NON_EDGES = (
    (AuthorizationDisposition.PROPOSED, AuthorizationDisposition.REVOKED),
    (AuthorizationDisposition.PROPOSED, AuthorizationDisposition.SUPERSEDED),
    (AuthorizationDisposition.ESTABLISHED, AuthorizationDisposition.DECLINED),
    (AuthorizationDisposition.ESTABLISHED, AuthorizationDisposition.EXPIRED),
)

#: A second declaration, so a goal can hold two ``ESTABLISHED`` rows at once —
#: which ADR-0268 §1's *"the ending is stated over the set and never over one
#: row"* is the whole point of: *"an act that ended one would leave the other
#: standing under a closed goal"*.
OTHER_TOOL = TOOL.model_copy(update={"id": "other_tool"})

#: A third and a fourth, for the two proposals arm 1 arranges beside them.
THIRD_TOOL = TOOL.model_copy(update={"id": "third_tool"})
FOURTH_TOOL = TOOL.model_copy(update={"id": "fourth_tool"})


def established(**overrides: object) -> Authorization:
    """A row written already ``ESTABLISHED`` — path (iii)'s shape, or path (ii)'s.

    ``settled_at`` equal to ``proposed_at`` is what ``record`` requires of a row
    carrying no ``confirmation``, so it is supplied here rather than at every call
    site (ADR-0254 §1, §16).
    """
    scripted: dict[str, object] = {
        "confirmation": None,
        "origin": AuthorizationOrigin.OPENING_ACT,
        "disposition": AuthorizationDisposition.ESTABLISHED,
    }
    scripted.update(overrides)
    return authorization(**scripted)  # type: ignore[arg-type]  # the builder's own keys


async def _refuses(
    store: GoalAuthorizationStore,
    rejected: Authorization,
    error: type[AuthorizationError] = InvalidAuthorizationError,
) -> None:
    """Assert ``record`` refuses ``rejected`` **and writes nothing**.

    ADR-0254 §16 makes ``record`` atomic — the duplicate-id check, the path rules,
    the uniqueness refusal, the two-row checks and the append are one operation — so
    a refusal is not a partial write with an exception on top. Asserting only that
    it raised would accept a store that appended a bad row and *then* rejected it,
    leaving a history the contract says is unrecordable.

    The whole store is compared rather than just the rejected id, because a write
    that landed under a different id, or that settled the row it named on its way
    through, is the same failure wearing a disguise.
    """
    before = await store.export()
    with pytest.raises(error):
        await store.record(rejected)
    assert await store.export() == before, "a refused write must leave no trace"


class GoalAuthorizationsContract:
    """``GoalAuthorizations.live_for``'s clauses (ADR-0254 §1, §3, §16)."""

    @pytest.fixture
    def clock(self) -> MovableClock:
        """The shared clock, reset for this case."""
        return SHARED_CLOCK.reset()

    @pytest.fixture
    def authorizations(self) -> GoalAuthorizations:
        """The subject: a seam over an empty history, on the shared clock."""
        raise NotImplementedError

    async def hold(self, authorizations: GoalAuthorizations, *rows: Authorization) -> None:
        """Put ``rows`` into the subject's history, under ``record``'s invariants."""
        raise NotImplementedError

    async def settle(
        self,
        authorizations: GoalAuthorizations,
        authorization_id: str,
        *,
        to: AuthorizationDisposition,
        settled_at: datetime = NOW,
    ) -> AuthorizationSettlement:
        """Move a row along an edge in the subject's history."""
        raise NotImplementedError

    async def test_an_empty_store_answers_none(self, authorizations: GoalAuthorizations) -> None:
        """``None`` means *"the store holds no live record"* and nothing else."""
        assert await authorizations.live_for(GOAL, TOOL.id) is None

    async def test_it_answers_the_live_established_row_of_that_pair(
        self, authorizations: GoalAuthorizations
    ) -> None:
        """§3's conditions 1 and 2 and the **id half** of condition 3."""
        await self.hold(authorizations, established(id="a1"))
        found = await authorizations.live_for(GOAL, TOOL.id)
        assert found is not None
        assert found.id == "a1"

    async def test_a_proposed_row_is_never_live(self, authorizations: GoalAuthorizations) -> None:
        """§1: *"a row the user has not answered authorises nothing"* (arm 37)."""
        await self.hold(authorizations, authorization(id="a1"))
        assert await authorizations.live_for(GOAL, TOOL.id) is None

    @pytest.mark.parametrize("disposition", RETIRED)
    async def test_a_retired_row_is_never_live(
        self, authorizations: GoalAuthorizations, disposition: AuthorizationDisposition
    ) -> None:
        """§1: every retired disposition is never live."""
        await self.hold(authorizations, authorization(id="a1"))
        edge = (
            AuthorizationDisposition.ESTABLISHED
            if disposition
            in (AuthorizationDisposition.REVOKED, AuthorizationDisposition.SUPERSEDED)
            else disposition
        )
        await self.settle(authorizations, "a1", to=edge)
        if edge is AuthorizationDisposition.ESTABLISHED:
            await self.settle(authorizations, "a1", to=disposition)
        assert await authorizations.live_for(GOAL, TOOL.id) is None

    async def test_a_row_of_another_goal_is_not_returned(
        self, authorizations: GoalAuthorizations
    ) -> None:
        """§1: *"The goal is a field and the scope is never the conversation"*."""
        await self.hold(authorizations, established(id="a1", goal=OTHER_GOAL))
        assert await authorizations.live_for(GOAL, TOOL.id) is None

    async def test_a_row_about_another_declaration_id_is_not_returned(
        self, authorizations: GoalAuthorizations
    ) -> None:
        """§16: the seam is **keyed** on the goal and the declaration's id."""
        await self.hold(authorizations, established(id="a1"))
        assert await authorizations.live_for(GOAL, "some_other_tool") is None

    async def test_a_row_about_an_edited_declaration_of_that_id_is_still_found(
        self, authorizations: GoalAuthorizations
    ) -> None:
        """§6: *"What the id buys is that the bar neither appears nor disappears when
        a declaration is edited"* (arm 48).

        The **policy** then takes §3's condition 3 by value and covers nothing — but
        the seam's job is to find the row, and a value key would lose it.
        """
        edited = TOOL.model_copy(update={"description": "Book a pitch — reworded."})
        await self.hold(authorizations, established(id="a1", tool=edited))
        found = await authorizations.live_for(GOAL, TOOL.id)
        assert found is not None
        assert found.tool != TOOL

    async def test_liveness_is_closed_below_and_open_above(
        self, authorizations: GoalAuthorizations, clock: MovableClock
    ) -> None:
        """§1, arm 71: equality at the lower end is live; the upper end is strict."""
        await self.hold(authorizations, established(id="a1"))
        clock.set(AT)
        assert await authorizations.live_for(GOAL, TOOL.id) is not None
        clock.set(EXPIRES - timedelta(microseconds=1))
        assert await authorizations.live_for(GOAL, TOOL.id) is not None
        clock.set(EXPIRES)
        assert await authorizations.live_for(GOAL, TOOL.id) is None

    async def test_a_clock_that_moved_backwards_answers_none_rather_than_disagreeing(
        self, authorizations: GoalAuthorizations, clock: MovableClock
    ) -> None:
        """§1, arm 71: *"the clock can move backwards — an operator correction, an
        NTP step"*.

        A row this seam called live whose ``settled_at`` is after the ruling's
        ``decided_at`` is one §7's trail then refuses as **backdated**, so the policy
        would report an authority the dispatch could not use and the step would die
        at the write rather than at the ruling. The lower end is what stops that.
        """
        await self.hold(authorizations, established(id="a1"))
        clock.set(AT - timedelta(hours=1))
        assert await authorizations.live_for(GOAL, TOOL.id) is None

    async def test_a_lapsed_established_row_is_not_live_and_is_not_settled_expired(
        self, authorizations: GoalAuthorizations, clock: MovableClock
    ) -> None:
        """§1, arm 37: ``EXPIRED`` is *"the answer a question never got"*.

        Re-using it for a lapsed authority would make the two indistinguishable in a
        listing — so a lapsed ``ESTABLISHED`` row stays ``ESTABLISHED``, which is
        also why it is still revocable.
        """
        await self.hold(authorizations, established(id="a1"))
        clock.set(EXPIRES + timedelta(hours=1))
        assert await authorizations.live_for(GOAL, TOOL.id) is None
        assert (
            await self.settle(authorizations, "a1", to=AuthorizationDisposition.REVOKED)
            is AuthorizationSettlement.SETTLED
        )

    async def test_it_reads_the_clock_exactly_once_per_call(
        self, authorizations: GoalAuthorizations, clock: MovableClock
    ) -> None:
        """§16, on ADR-0193 §9: *"a query reading an advancing clock per row could
        answer over a set true at no real instant"*."""
        await self.hold(
            authorizations,
            established(id="a1"),
            established(id="a2", goal=OTHER_GOAL),
            authorization(id="a3"),
        )
        clock.reset()
        clock.advance_by()
        await authorizations.live_for(GOAL, TOOL.id)
        assert clock.readings == 1

    async def test_it_settles_an_expired_proposal_it_reads(
        self, authorizations: GoalAuthorizations, clock: MovableClock
    ) -> None:
        """§1, arm 37: ADR-0244 §10's mechanism — *"an expiry is settled and is never
        inferred"*, by the **first operation that reads it**.

        Asserted through the seam a policy holds, because that is where the rule
        lives; the store suite asserts the row's own disposition afterwards.
        """
        await self.hold(authorizations, authorization(id="a1"))
        clock.set(EXPIRES + timedelta(hours=1))
        assert await authorizations.live_for(GOAL, TOOL.id) is None

    async def test_the_answer_is_a_detached_snapshot(
        self, authorizations: GoalAuthorizations
    ) -> None:
        """ADR-0097 §3: ``frozen=True`` does not close the ``__dict__`` bypass.

        A caller rewriting the answer would otherwise widen what the user
        authorised, **through the gate's own answer**.
        """
        await self.hold(authorizations, established(id="a1"))
        first = await authorizations.live_for(GOAL, TOOL.id)
        assert first is not None
        first.__dict__["expires_at"] = EXPIRES + timedelta(days=365)
        second = await authorizations.live_for(GOAL, TOOL.id)
        assert second is not None
        assert second.expires_at == EXPIRES


class AuthorizationResolutionContract:
    """``AuthorizationResolution.resolve``'s clauses (ADR-0254 §7, §16)."""

    @pytest.fixture
    def resolution(self) -> AuthorizationResolution:
        """The subject: a seam over an empty history."""
        raise NotImplementedError

    async def hold_for_resolution(
        self, resolution: AuthorizationResolution, *rows: Authorization
    ) -> None:
        """Put ``rows`` into the subject's history, under ``record``'s invariants."""
        raise NotImplementedError

    async def settle_for_resolution(
        self,
        resolution: AuthorizationResolution,
        authorization_id: str,
        *,
        to: AuthorizationDisposition,
        settled_at: datetime = NOW,
    ) -> AuthorizationSettlement:
        """Move a row along an edge in the subject's history."""
        raise NotImplementedError

    async def test_an_unknown_id_answers_none(self, resolution: AuthorizationResolution) -> None:
        """``None`` means the store holds no row with that id, and nothing else."""
        assert await resolution.resolve("nobody") is None

    @pytest.mark.parametrize(
        "to",
        [
            AuthorizationDisposition.ESTABLISHED,
            AuthorizationDisposition.DECLINED,
            AuthorizationDisposition.EXPIRED,
        ],
    )
    async def test_it_answers_the_row_whatever_its_disposition(
        self, resolution: AuthorizationResolution, to: AuthorizationDisposition
    ) -> None:
        """§7: the trail's own first check **reads** that field.

        A member that withheld a retired row would move the check inside the seam
        and leave the trail unable to say which of the five it refused on.
        """
        await self.hold_for_resolution(resolution, authorization(id="a1"))
        # §1 states ``PROPOSED → EXPIRED`` as *"the deadline passed before an
        # answer"*, so that one edge is taken at the deadline rather than at ``NOW``.
        at = EXPIRES if to is AuthorizationDisposition.EXPIRED else NOW
        await self.settle_for_resolution(resolution, "a1", to=to, settled_at=at)
        found = await resolution.resolve("a1")
        assert found is not None
        assert found.disposition is to

    async def test_it_answers_a_proposal_the_user_has_not_answered(
        self, resolution: AuthorizationResolution
    ) -> None:
        """§7: the row in every disposition, ``PROPOSED`` included."""
        await self.hold_for_resolution(resolution, authorization(id="a1"))
        found = await resolution.resolve("a1")
        assert found is not None
        assert found.disposition is AuthorizationDisposition.PROPOSED

    async def test_it_reads_no_clock_so_a_lapsed_row_still_resolves(
        self, resolution: AuthorizationResolution
    ) -> None:
        """§16: both ends of liveness are decided by ``AuditTrail.record`` against
        the **decision's own** ``decided_at``, which is what makes that check a
        comparison of two recorded values rather than a reading of the present."""
        await self.hold_for_resolution(
            resolution, established(id="a1", expires_at=AT + timedelta(seconds=1))
        )
        assert await resolution.resolve("a1") is not None

    async def test_a_resolved_row_is_a_detached_snapshot(
        self, resolution: AuthorizationResolution
    ) -> None:
        """ADR-0097 §3, as on the query face.

        Named apart from :meth:`GoalAuthorizationsContract.
        test_the_answer_is_a_detached_snapshot` because a store subclasses both
        suites and one name would be one test.
        """
        await self.hold_for_resolution(resolution, established(id="a1"))
        first = await resolution.resolve("a1")
        assert first is not None
        first.__dict__["goal"] = "somewhere-else"
        second = await resolution.resolve("a1")
        assert second is not None
        assert second.goal == GOAL


class GoalAuthorizationStoreContract(GoalAuthorizationsContract, AuthorizationResolutionContract):
    """The durable face's clauses: ``record``, ``settle``, and the four reads.

    Inherits both narrow suites, because a store **is** the two narrow seams plus
    the ability to write — so an implementation bound here answers every clause of
    all three faces, which is ADR-0254 §16's *"three faces, one object"*.
    """

    @pytest.fixture
    def store(self) -> GoalAuthorizationStore:
        """The subject: a store over an empty history, on the shared clock."""
        raise NotImplementedError

    # --- the two narrow suites, answered by this same object ---------------

    @pytest.fixture
    def authorizations(self, store: GoalAuthorizationStore) -> GoalAuthorizations:
        """The store, as its query face."""
        return store

    @pytest.fixture
    def resolution(self, store: GoalAuthorizationStore) -> AuthorizationResolution:
        """The store, as its resolution face."""
        return store

    async def hold(self, authorizations: GoalAuthorizations, *rows: Authorization) -> None:
        """Record ``rows`` through the store's own write path."""
        subject = cast("GoalAuthorizationStore", authorizations)
        for row in rows:
            await subject.record(row)

    async def settle(
        self,
        authorizations: GoalAuthorizations,
        authorization_id: str,
        *,
        to: AuthorizationDisposition,
        settled_at: datetime = NOW,
    ) -> AuthorizationSettlement:
        """Settle through the store's own write path."""
        subject = cast("GoalAuthorizationStore", authorizations)
        return await subject.settle(authorization_id, to=to, settled_at=settled_at)

    async def hold_for_resolution(
        self, resolution: AuthorizationResolution, *rows: Authorization
    ) -> None:
        """Record ``rows`` through the store's own write path."""
        subject = cast("GoalAuthorizationStore", resolution)
        for row in rows:
            await subject.record(row)

    async def settle_for_resolution(
        self,
        resolution: AuthorizationResolution,
        authorization_id: str,
        *,
        to: AuthorizationDisposition,
        settled_at: datetime = NOW,
    ) -> AuthorizationSettlement:
        """Settle through the store's own write path."""
        subject = cast("GoalAuthorizationStore", resolution)
        return await subject.settle(authorization_id, to=to, settled_at=settled_at)

    # --- record: the write paths (ADR-0254 §1, §16) ------------------------

    async def test_record_returns_the_id_it_wrote(self, store: GoalAuthorizationStore) -> None:
        """§16: ``record(authorization) -> str`` — *"the id it wrote"*."""
        assert await store.record(authorization(id="a1")) == "a1"

    async def test_it_is_write_once(self, store: GoalAuthorizationStore) -> None:
        """§16: *"a store that upserts is one where history can be rewritten by
        replaying a write"*."""
        await store.record(authorization(id="a1"))
        await _refuses(store, authorization(id="a1", goal=OTHER_GOAL))

    async def test_a_confirmation_carrying_row_is_written_proposed_and_no_other(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§16, arm 38: *"the write-path rule the validator deliberately does not
        state"*.

        It is not a model validator because the same row is later persisted
        ``ESTABLISHED`` with that same ``confirmation`` — a validator stating it
        would refuse to decode the row it had just written.
        """
        await store.record(authorization(id="a1"))
        for disposition in AuthorizationDisposition:
            if disposition is AuthorizationDisposition.PROPOSED:
                continue
            await _refuses(
                store,
                authorization(id=f"bad-{disposition.value}", disposition=disposition),
            )

    async def test_a_row_carrying_no_confirmation_is_written_established(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§1: paths (ii) and (iii) write ``ESTABLISHED`` directly."""
        await _refuses(
            store,
            authorization(
                id="a1", confirmation=None, disposition=AuthorizationDisposition.DECLINED
            ),
        )

    async def test_a_row_carrying_no_confirmation_settles_at_the_instant_it_was_written(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§1: ``settled_at`` equal to ``proposed_at`` — the recorded turn's instant."""
        await _refuses(
            store,
            authorization(
                id="a1",
                confirmation=None,
                origin=AuthorizationOrigin.OPENING_ACT,
                disposition=AuthorizationDisposition.ESTABLISHED,
                settled_at=AT + timedelta(minutes=1),
            ),
        )

    async def test_at_most_one_established_row_stands_per_goal_and_declaration_id(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§1, arm 36: the refusal is over the **disposition**, so no clock is read."""
        await store.record(established(id="a1"))
        await _refuses(store, established(id="a2"))

    async def test_the_uniqueness_key_is_the_id_and_not_the_declaration_by_value(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§1, arm 36: *"stricter than a value key"*.

        It additionally refuses a second row about an **edited** declaration of the
        same id, which a value key would admit.
        """
        edited = TOOL.model_copy(update={"description": "Book a pitch — reworded."})
        await store.record(established(id="a1"))
        await _refuses(store, established(id="a2", tool=edited))

    async def test_another_goal_and_another_declaration_are_each_a_different_pair(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§1: uniqueness is per **pair**, so neither axis alone refuses."""
        other_tool = TOOL.model_copy(update={"id": "other_tool"})
        await store.record(established(id="a1"))
        await store.record(established(id="a2", goal=OTHER_GOAL))
        await store.record(established(id="a3", tool=other_tool))
        assert len(await store.export()) == 3

    async def test_two_proposals_of_one_pair_are_both_recorded(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§16, arm 56: *"neither write leaves two rows ``ESTABLISHED``, so neither is
        ``record``'s to refuse"* — it is the **second settlement** that answers."""
        await store.record(authorization(id="a1"))
        await store.record(authorization(id="a2", confirmation="confirm-0002"))
        assert len(await store.export()) == 2

    async def test_a_supersedes_naming_no_established_row_of_that_pair_is_refused(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§16: absent, standing elsewhere, or belonging to another pair."""
        await _refuses(store, established(id="a1", supersedes="nobody"))
        await store.record(authorization(id="p1"))
        await _refuses(store, established(id="a2", supersedes="p1"))
        await store.record(established(id="e1", goal=OTHER_GOAL))
        await _refuses(store, established(id="a3", supersedes="e1"))

    # --- record: what a path-(ii) correction may change (§1, §5, §9) --------

    async def test_a_correction_settles_the_row_it_supersedes_in_the_same_write(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§16: *"in the same indivisible write"* — so uniqueness is never
        momentarily false."""
        await store.record(established(id="a1"))
        await store.record(
            established(
                id="a2",
                supersedes="a1",
                proposed_at=AT + timedelta(minutes=5),
                coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("40")),),
            )
        )
        assert [row.id for row in await store.standing(GOAL)] == ["a2"]
        first = await store.resolve("a1")
        assert first is not None
        assert first.disposition is AuthorizationDisposition.SUPERSEDED

    @pytest.mark.parametrize("field", ["goal", "tool", "account", "destinations", "origin"])
    async def test_a_correction_transcribes_the_five_fields_it_may_not_change(
        self, store: GoalAuthorizationStore, field: str
    ) -> None:
        """§1, arm 17 — and ADR-0256 §9 adds ``origin`` to the four arm 17 names.

        **Transcribing ``origin`` is what keeps §6's recipient recheck alive through
        a correction**: a chain of corrections over an opening act is still an
        authority resting on someone else's grant, and the row says so.
        """
        await store.record(established(id="a1"))
        other_tool = TOOL.model_copy(update={"id": "other_tool"})
        moved: dict[str, object] = {
            "goal": OTHER_GOAL,
            "tool": other_tool,
            "account": authorization().account.model_copy(update={"reference": "conn-0002"}),
            "destinations": (member(OTHER_SITE),),
            "origin": AuthorizationOrigin.CONFIRMED,
        }
        await _refuses(
            store,
            established(
                id="a2",
                supersedes="a1",
                proposed_at=AT + timedelta(minutes=5),
                **{field: moved[field]},
            ),
        )

    async def test_a_correction_may_replace_a_fixed_value_the_row_already_fixed(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§5: the owner's *"make it Sunday"*, and the user is not asked to repeat it.

        **Stated over the ``kind`` the act constrained** (ADR-0266 §3), where it used
        to be stated over an argument key: the member records that the user fixed a
        *date*, and which argument of which declaration carries it is read at the
        comparison. ADR-0254 §20's arm 14 stands exactly as written — *"actually,
        make it Sunday"* is ``DATE_FROM_CONTEXT``'s and ADR-0266 §4 leaves that
        reading untouched.
        """
        await store.record(
            established(
                id="a1",
                coverage=(coverage_member(BoundKind.PERIOD, fixed="2026-09-19"),),
            )
        )
        await store.record(
            established(
                id="a2",
                supersedes="a1",
                proposed_at=AT + timedelta(minutes=5),
                coverage=(coverage_member(BoundKind.PERIOD, fixed="2026-09-20"),),
            )
        )
        assert [row.id for row in await store.standing(GOAL)] == ["a2"]

    async def test_a_correction_may_narrow_a_bound_the_row_already_bounded(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§1: *"narrow a bound for an argument it already bounded"*."""
        await store.record(established(id="a1"))
        await store.record(
            established(
                id="a2",
                supersedes="a1",
                proposed_at=AT + timedelta(minutes=5),
                coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("40")),),
            )
        )
        assert [row.id for row in await store.standing(GOAL)] == ["a2"]

    @pytest.mark.parametrize(
        "widened",
        [
            pytest.param(lambda: money_bound("80"), id="raised-maximum"),
            pytest.param(lambda: money_bound("60", minimum="5"), id="lowered-minimum"),
            pytest.param(lambda: money_bound("60", currency="EUR"), id="changed-currency"),
        ],
    )
    async def test_a_correction_that_would_widen_a_money_bound_is_refused(
        self, store: GoalAuthorizationStore, widened: object
    ) -> None:
        """§5, arm 15: *"A widening of any kind takes path (i) and is confirmed"*.

        A changed currency is neither a narrowing nor a widening — it
        **re-denominates** what the bound is about — and takes path (i) with the
        rest.

        **Two cases this list used to carry have moved rather than gone** (ADR-0266
        §9). A moved ``currency_argument`` is not a widening of anything any more:
        ADR-0266 §3 takes that key off the bound, because which argument carries an
        amount's currency is a fact about a **declaration** and not about an act. And
        a changed **kind** is no longer refused here but one layer earlier — a member
        and its bound now agree by construction (§3) — so the store sees a correction
        of a kind the superseded row carries no member of, which is the addition
        :meth:`test_a_correction_changing_the_kind_of_a_member_is_refused` states.
        """
        assert callable(widened)
        await store.record(
            established(
                id="a1",
                coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("60", minimum="10")),),
            )
        )
        await _refuses(
            store,
            established(
                id="a2",
                supersedes="a1",
                proposed_at=AT + timedelta(minutes=5),
                coverage=(coverage_member(BoundKind.MONEY, bound=widened()),),
            ),
        )

    async def test_a_correction_setting_maximum_exclusive_at_an_equal_ceiling_narrows(
        self, store: GoalAuthorizationStore
    ) -> None:
        """ADR-0266 §3, arm 4(a): *"setting it narrows"*.

        *"at most 100"* corrected to *"under 100"* **withdraws** the endpoint, so
        every amount the correction permits the superseded row permitted too and
        path (ii) writes it.
        """
        await store.record(
            established(
                id="a1", coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("100")),)
            )
        )
        await store.record(
            established(
                id="a2",
                supersedes="a1",
                proposed_at=AT + timedelta(minutes=5),
                coverage=(
                    coverage_member(
                        BoundKind.MONEY, bound=money_bound("100", maximum_exclusive=True)
                    ),
                ),
            )
        )
        assert [row.id for row in await store.standing(GOAL)] == ["a2"]

    async def test_a_correction_clearing_maximum_exclusive_at_an_equal_ceiling_is_refused(
        self, store: GoalAuthorizationStore
    ) -> None:
        """ADR-0266 §3, arm 4(a): *"clearing it widens"* — **no row written and no
        standing route**.

        The reverse of the arm above, and the one a numeric comparison alone cannot
        see: *"under 100"* corrected to *"at most 100"* adds a call at exactly ``100``
        that the live row refused, so it is a widening ADR-0254 §5 refuses and the act
        asks on path (i). **A lane that compared ``maximum`` alone would read it as no
        change** and establish a wider authority with no confirmation, which is the
        permissive direction §2's asymmetry names.
        """
        await store.record(
            established(
                id="a1",
                coverage=(
                    coverage_member(
                        BoundKind.MONEY, bound=money_bound("100", maximum_exclusive=True)
                    ),
                ),
            )
        )
        await _refuses(
            store,
            established(
                id="a2",
                supersedes="a1",
                proposed_at=AT + timedelta(minutes=5),
                coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("100")),),
            ),
        )
        assert [row.id for row in await store.standing(GOAL)] == ["a1"]

    async def test_a_correction_changing_the_kind_of_a_member_is_refused(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§5, arm 15's *"changed kind"* limb, restated where the store can see it.

        *"A change of ``kind`` is not a narrowing, whatever the two bounds permit"* —
        the kinds are compared by different readings (§4) and a claim that one is
        inside another is a comparison this corpus does not establish. Since ADR-0266
        §3 a member and its bound agree by construction, so the correction the store
        is offered is a member of a kind the superseded row carries **none** of: an
        addition, refused, with the ``MONEY`` member it dropped refused beside it.
        """
        await store.record(established(id="a1"))
        await _refuses(
            store,
            established(
                id="a2",
                supersedes="a1",
                proposed_at=AT + timedelta(minutes=5),
                coverage=(coverage_member(BoundKind.PERIOD, bound=period_bound()),),
            ),
        )

    async def test_a_correction_may_drop_a_minimum_neither_way(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§1: a lower bound the correction **drops** widens — every amount below the
        earlier minimum becomes permitted — and one it **adds** narrows."""
        await store.record(
            established(
                id="a1",
                coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("60", minimum="10")),),
            )
        )
        await _refuses(
            store,
            established(
                id="a2",
                supersedes="a1",
                proposed_at=AT + timedelta(minutes=5),
                coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("60")),),
            ),
        )

    async def test_a_correction_that_would_widen_a_terms_bound_is_refused(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§5, arm 15: *"add Bob"* — an added term is a widening."""
        await store.record(
            established(
                id="a1", coverage=(coverage_member(BoundKind.TERMS, bound=terms_bound("flexible")),)
            )
        )
        await store.record(
            established(
                id="a2",
                supersedes="a1",
                proposed_at=AT + timedelta(minutes=5),
                coverage=(coverage_member(BoundKind.TERMS, bound=terms_bound("flexible")),),
            )
        )
        await _refuses(
            store,
            established(
                id="a3",
                supersedes="a2",
                proposed_at=AT + timedelta(minutes=10),
                coverage=(
                    coverage_member(BoundKind.TERMS, bound=terms_bound("flexible", "refundable")),
                ),
            ),
        )

    async def test_a_correction_that_would_lengthen_a_period_bound_is_refused(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§5, arm 15: *"make it next month as well"* — a longer period is a widening."""
        await store.record(
            established(
                id="a1",
                coverage=(
                    coverage_member(
                        BoundKind.PERIOD, bound=period_bound(starts_at=AT, ends_at=EXPIRES)
                    ),
                ),
            )
        )
        await _refuses(
            store,
            established(
                id="a2",
                supersedes="a1",
                proposed_at=AT + timedelta(minutes=5),
                coverage=(
                    coverage_member(
                        BoundKind.PERIOD,
                        bound=period_bound(starts_at=AT, ends_at=EXPIRES + timedelta(days=30)),
                    ),
                ),
            ),
        )

    async def test_a_correction_naming_an_argument_no_member_covers_is_refused(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§5, arm 15, arm 47: *"add insurance"* — path (ii) refuses it at
        construction, and §6's bar is what then refuses the dispatch.

        **Restated as a member of a kind the row carries none of** (ADR-0266 §9's
        mechanism (i)): ADR-0254 §5's *"naming an argument no member covers"* limb is
        read as *an argument the row would not cover under §7's condition 6 once the
        correction is applied*, and a term the superseded row states nothing about is
        exactly that. Its force is unchanged and only its test moved. ADR-0266 §9
        says so of arm 47 by name: *"add insurance"* is a term, and §4 leaves that
        reading untouched.
        """
        await store.record(established(id="a1"))
        await _refuses(
            store,
            established(
                id="a2",
                supersedes="a1",
                proposed_at=AT + timedelta(minutes=5),
                coverage=(
                    coverage_member(BoundKind.MONEY, bound=money_bound()),
                    coverage_member(BoundKind.TERMS, fixed="insurance"),
                ),
            ),
        )

    async def test_a_correction_dropping_a_member_it_does_not_replace_is_refused(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§5: *"every other member is carried forward byte for byte with the basis it
        already had"*."""
        await store.record(
            established(
                id="a1",
                coverage=(
                    coverage_member(BoundKind.MONEY, bound=money_bound()),
                    coverage_member(BoundKind.TERMS, fixed="A"),
                ),
            )
        )
        await _refuses(
            store,
            established(
                id="a2",
                supersedes="a1",
                proposed_at=AT + timedelta(minutes=5),
                coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("40")),),
            ),
        )

    async def test_a_correction_turning_a_fixed_value_into_a_bound_is_refused(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§1: it replaces a fixed value the row **fixed**, or narrows a bound the row
        **bounded**; turning one shape into the other is neither motion.

        **Stated at ``TERMS`` where it used to be stated at a money argument**: a
        ``MONEY`` member fixes nothing at all since ADR-0266 §3 — an amount carries no
        currency on a fixed member, so such a member states an amount nothing can
        denominate — and the property this arm demonstrates is about the two
        **shapes** rather than about which kind holds them.
        """
        await store.record(
            established(id="a1", coverage=(coverage_member(BoundKind.TERMS, fixed="flexible"),))
        )
        await _refuses(
            store,
            established(
                id="a2",
                supersedes="a1",
                proposed_at=AT + timedelta(minutes=5),
                coverage=(coverage_member(BoundKind.TERMS, bound=terms_bound("flexible")),),
            ),
        )

    # --- record: ADR-0256 §5's one narrowing of expires_at -----------------

    async def test_a_correction_stating_an_earlier_admissible_instant_narrows(
        self, store: GoalAuthorizationStore
    ) -> None:
        """ADR-0256 §5, §9's **Lane 1 arm**: *"the store accepts exactly that row"*.

        Strictly after the new row's ``proposed_at`` and strictly before the
        superseded row's ``expires_at`` — where ADR-0254 §20's arm 17 refused every
        altered ``expires_at``.
        """
        await store.record(established(id="a1"))
        narrowed = AT + timedelta(hours=6)
        await store.record(
            established(
                id="a2",
                supersedes="a1",
                proposed_at=AT + timedelta(minutes=5),
                expires_at=narrowed,
                coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("40")),),
            )
        )
        held = await store.resolve("a2")
        assert held is not None
        assert held.expires_at == narrowed

    async def test_a_correction_stating_a_later_instant_does_not_lengthen(
        self, store: GoalAuthorizationStore
    ) -> None:
        """ADR-0256 §5, §9's second **Lane 1 arm**: every other movement is refused.

        *"Nothing lengthens a horizon on any path but (i)"*, so ADR-0254 §12's *"No
        sequence of corrections outlives the confirmation that began it"* holds a
        fortiori.
        """
        await store.record(established(id="a1"))
        await _refuses(
            store,
            established(
                id="a2",
                supersedes="a1",
                proposed_at=AT + timedelta(minutes=5),
                expires_at=EXPIRES + timedelta(hours=1),
                coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("40")),),
            ),
        )

    async def test_a_chain_narrows_against_the_row_it_supersedes_not_against_the_first(
        self, store: GoalAuthorizationStore
    ) -> None:
        """ADR-0256 §9: *"an implementation comparing against the first row's
        ``expires_at`` passes every single-correction arm above and lengthens on the
        second"*."""
        await store.record(established(id="a1"))
        narrowed = AT + timedelta(hours=6)
        await store.record(
            established(
                id="a2",
                supersedes="a1",
                proposed_at=AT + timedelta(minutes=5),
                expires_at=narrowed,
                coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("50")),),
            )
        )
        await _refuses(
            store,
            established(
                id="a3",
                supersedes="a2",
                proposed_at=AT + timedelta(minutes=10),
                expires_at=narrowed + timedelta(hours=1),
                coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("40")),),
            ),
        )

    async def test_a_path_one_proposal_carrying_supersedes_may_carry_a_later_instant(
        self, store: GoalAuthorizationStore
    ) -> None:
        """ADR-0256 §9: *"a path-(i) proposal carrying ``supersedes`` is not this
        arm's subject and is refused by none of it"* — arm 42's renewal.

        *"An implementation that applied the path-(ii) rule to it would break
        renewal."*
        """
        await store.record(established(id="a1"))
        await store.record(
            authorization(
                id="a2",
                supersedes="a1",
                proposed_at=AT + timedelta(minutes=5),
                expires_at=EXPIRES + timedelta(days=1),
            )
        )
        assert (
            await store.settle(
                "a2", to=AuthorizationDisposition.ESTABLISHED, settled_at=AT + timedelta(hours=1)
            )
            is AuthorizationSettlement.SETTLED
        )
        standing = await store.standing(GOAL)
        assert [row.id for row in standing] == ["a2"]
        assert standing[0].expires_at == EXPIRES + timedelta(days=1)

    # --- settle: the graph, and the four outcomes (§1, §16) ----------------

    @pytest.mark.parametrize(("source", "target"), EDGES)
    async def test_each_of_the_seven_edges_succeeds_from_its_own_source(
        self,
        store: GoalAuthorizationStore,
        source: AuthorizationDisposition,
        target: AuthorizationDisposition,
    ) -> None:
        """§1, arm 37 and arm 55: each edge, from its own source."""
        await store.record(authorization(id="a1"))
        if source is AuthorizationDisposition.ESTABLISHED:
            await store.settle("a1", to=AuthorizationDisposition.ESTABLISHED, settled_at=NOW)
        # **The ``EXPIRED`` edge is taken at the deadline**, because §1 states it as
        # *"the deadline passed before an answer"* — so its source is a proposal whose
        # deadline has passed, and the instant is part of what that edge is.
        at = EXPIRES if target is AuthorizationDisposition.EXPIRED else NOW
        assert await store.settle("a1", to=target, settled_at=at) is AuthorizationSettlement.SETTLED
        held = await store.resolve("a1")
        assert held is not None
        assert (held.disposition, held.settled_at) == (target, at)

    @pytest.mark.parametrize(("source", "target"), NON_EDGES)
    async def test_every_move_that_is_not_an_edge_answers_not_at_source(
        self,
        store: GoalAuthorizationStore,
        source: AuthorizationDisposition,
        target: AuthorizationDisposition,
    ) -> None:
        """§1, arm 37 and arm 55: *"no other edge exists"*."""
        await store.record(authorization(id="a1"))
        if source is AuthorizationDisposition.ESTABLISHED:
            await store.settle("a1", to=AuthorizationDisposition.ESTABLISHED, settled_at=NOW)
        assert (
            await store.settle("a1", to=target, settled_at=NOW)
            is AuthorizationSettlement.NOT_AT_SOURCE
        )

    @pytest.mark.parametrize("retired", RETIRED)
    async def test_no_edge_leaves_a_retired_disposition(
        self, store: GoalAuthorizationStore, retired: AuthorizationDisposition
    ) -> None:
        """§1, arm 55: *"a retired row asked for anything"* answers ``NOT_AT_SOURCE``.

        **And a revoked or superseded row cannot be settled again** (arm 3's third
        limb): none of §1's five edges leaves ``REVOKED`` or ``SUPERSEDED``.
        """
        await store.record(authorization(id="a1"))
        if retired in (AuthorizationDisposition.REVOKED, AuthorizationDisposition.SUPERSEDED):
            await store.settle("a1", to=AuthorizationDisposition.ESTABLISHED, settled_at=NOW)
        # The ``EXPIRED`` edge is taken at the deadline (§1's own statement of it).
        at = EXPIRES if retired is AuthorizationDisposition.EXPIRED else NOW
        await store.settle("a1", to=retired, settled_at=at)
        for target in AuthorizationDisposition:
            assert (
                await store.settle("a1", to=target, settled_at=NOW)
                is AuthorizationSettlement.NOT_AT_SOURCE
            )

    async def test_the_same_settlement_repeated_answers_not_at_source(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§16, arm 55: the compare-and-swap's token is the row's own disposition."""
        await store.record(authorization(id="a1"))
        await store.settle("a1", to=AuthorizationDisposition.DECLINED, settled_at=NOW)
        assert (
            await store.settle("a1", to=AuthorizationDisposition.DECLINED, settled_at=NOW)
            is AuthorizationSettlement.NOT_AT_SOURCE
        )

    async def test_an_id_the_store_does_not_hold_answers_no_such_authorization(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§16, arm 55: *"a ``bool`` cannot tell an unknown id from a row that was not
        at the source"*."""
        assert (
            await store.settle("nobody", to=AuthorizationDisposition.REVOKED, settled_at=NOW)
            is AuthorizationSettlement.NO_SUCH_AUTHORIZATION
        )

    async def test_two_racing_settlements_of_one_row_never_both_win(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§1, §16, arm 55: *"the loser of two racing settlements"* is ``NOT_AT_SOURCE``."""
        await store.record(authorization(id="a1"))
        outcomes = await asyncio.gather(
            store.settle("a1", to=AuthorizationDisposition.ESTABLISHED, settled_at=NOW),
            store.settle("a1", to=AuthorizationDisposition.DECLINED, settled_at=NOW),
        )
        assert sorted(outcome.value for outcome in outcomes) == ["not_at_source", "settled"]

    async def test_settling_the_second_proposal_of_one_pair_answers_would_duplicate(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§16, arm 56: *"a settlement is where two rows can meet"*.

        *"A lane that answered ``SETTLED`` here has written the state §1 forbids"*,
        and one that raised has made a refusal an exception.
        """
        await store.record(authorization(id="a1"))
        await store.record(authorization(id="a2", confirmation="confirm-0002"))
        assert (
            await store.settle("a1", to=AuthorizationDisposition.ESTABLISHED, settled_at=NOW)
            is AuthorizationSettlement.SETTLED
        )
        assert (
            await store.settle("a2", to=AuthorizationDisposition.ESTABLISHED, settled_at=NOW)
            is AuthorizationSettlement.WOULD_DUPLICATE
        )
        held = await store.resolve("a2")
        assert held is not None
        assert held.disposition is AuthorizationDisposition.PROPOSED
        assert [row.id for row in await store.standing(GOAL)] == ["a1"]

    async def test_two_racing_establishments_of_one_pair_never_both_win(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§16, arm 56: *"never two winners and never an interleaving that leaves two
        rows ``ESTABLISHED``"*."""
        await store.record(authorization(id="a1"))
        await store.record(authorization(id="a2", confirmation="confirm-0002"))
        outcomes = await asyncio.gather(
            store.settle("a1", to=AuthorizationDisposition.ESTABLISHED, settled_at=NOW),
            store.settle("a2", to=AuthorizationDisposition.ESTABLISHED, settled_at=NOW),
        )
        assert sorted(outcome.value for outcome in outcomes) == ["settled", "would_duplicate"]
        assert len(await store.standing(GOAL)) == 1

    async def test_a_path_one_proposal_retires_nothing_until_it_is_answered(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§16, arm 57: *"a lane whose ``record`` settled the predecessor at the
        proposal fails this arm"*.

        The bar would have had no row to test and the declined widening would have
        dispatched.
        """
        await store.record(established(id="a1"))
        await store.record(
            authorization(id="a2", supersedes="a1", proposed_at=AT + timedelta(minutes=5))
        )
        assert [row.id for row in await store.standing(GOAL)] == ["a1"]
        found = await store.live_for(GOAL, TOOL.id)
        assert found is not None
        assert found.id == "a1"

    async def test_declining_a_widening_leaves_the_row_it_named_exactly_as_it_was(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§5, arm 39: *"a refused widening is not a revocation of what the user
        already authorised"*."""
        await store.record(established(id="a1"))
        await store.record(
            authorization(id="a2", supersedes="a1", proposed_at=AT + timedelta(minutes=5))
        )
        before = await store.resolve("a1")
        assert (
            await store.settle("a2", to=AuthorizationDisposition.DECLINED, settled_at=NOW)
            is AuthorizationSettlement.SETTLED
        )
        assert await store.resolve("a1") == before
        assert [row.id for row in await store.standing(GOAL)] == ["a1"]

    async def test_approving_a_widening_settles_both_rows_in_one_write(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§5, arm 39: *"with no instant at which both are established"*."""
        await store.record(established(id="a1"))
        await store.record(
            authorization(id="a2", supersedes="a1", proposed_at=AT + timedelta(minutes=5))
        )
        assert (
            await store.settle("a2", to=AuthorizationDisposition.ESTABLISHED, settled_at=NOW)
            is AuthorizationSettlement.SETTLED
        )
        assert [row.id for row in await store.standing(GOAL)] == ["a2"]
        first = await store.resolve("a1")
        assert first is not None
        assert first.disposition is AuthorizationDisposition.SUPERSEDED

    async def test_a_predecessor_revoked_while_the_question_stood_is_left_as_it_stands(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§1's conditional-supersession clause, arm 63.

        *"A lane that refused the establishment here fails this arm"*, as does one
        that answered ``SETTLED`` while moving A out of a retired disposition.
        """
        await store.record(established(id="a1"))
        await store.record(
            authorization(id="a2", supersedes="a1", proposed_at=AT + timedelta(minutes=5))
        )
        await store.settle("a1", to=AuthorizationDisposition.REVOKED, settled_at=NOW)
        assert (
            await store.settle("a2", to=AuthorizationDisposition.ESTABLISHED, settled_at=NOW)
            is AuthorizationSettlement.SETTLED
        )
        first = await store.resolve("a1")
        assert first is not None
        assert first.disposition is AuthorizationDisposition.REVOKED
        assert [row.id for row in await store.standing(GOAL)] == ["a2"]

    async def test_a_third_established_row_of_that_pair_answers_would_duplicate(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§1, arm 63: *"a row this write's ``supersedes`` does not name"*.

        *"That is §16's member doing exactly what it exists for, and it is why the
        arm above is stated over *the named row* and never over *the pair*."*
        """
        await store.record(established(id="a1"))
        await store.record(
            authorization(id="a2", supersedes="a1", proposed_at=AT + timedelta(minutes=5))
        )
        await store.record(
            established(
                id="a3",
                supersedes="a1",
                proposed_at=AT + timedelta(minutes=6),
                coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("40")),),
            )
        )
        assert (
            await store.settle("a2", to=AuthorizationDisposition.ESTABLISHED, settled_at=NOW)
            is AuthorizationSettlement.WOULD_DUPLICATE
        )
        held = await store.resolve("a2")
        assert held is not None
        assert held.disposition is AuthorizationDisposition.PROPOSED
        assert [row.id for row in await store.standing(GOAL)] == ["a3"]

    async def test_supersession_is_permanent(self, store: GoalAuthorizationStore) -> None:
        """§1, arm 19: *"nothing un-supersedes one"*.

        Both rows stay in the store, both appear in ``export``, and revoking the
        superseding row leaves **neither** live — the fail-closed direction.
        """
        await store.record(established(id="a1"))
        await store.record(
            established(
                id="a2",
                supersedes="a1",
                proposed_at=AT + timedelta(minutes=5),
                coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("40")),),
            )
        )
        await store.settle("a2", to=AuthorizationDisposition.REVOKED, settled_at=NOW)
        first = await store.resolve("a1")
        assert first is not None
        assert first.disposition is AuthorizationDisposition.SUPERSEDED
        assert await store.live_for(GOAL, TOOL.id) is None
        assert {row.id for row in await store.export()} == {"a1", "a2"}

    async def test_a_lapsed_established_row_is_still_revocable(
        self, store: GoalAuthorizationStore, clock: MovableClock
    ) -> None:
        """§1, arm 43: *"a lapsed row never becomes an obstacle"*.

        It is reachable for the withdrawal because ``standing(goal)`` returns it,
        which is why that member needs no history query.
        """
        await store.record(established(id="a1"))
        clock.set(EXPIRES + timedelta(hours=1))
        assert [row.id for row in await store.standing(GOAL)] == ["a1"]
        assert (
            await store.settle("a1", to=AuthorizationDisposition.REVOKED, settled_at=NOW)
            is AuthorizationSettlement.SETTLED
        )

    async def test_a_proposed_row_is_refused_a_revocation(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§1, arm 43: ``PROPOSED → REVOKED`` is not an edge."""
        await store.record(authorization(id="a1"))
        assert (
            await store.settle("a1", to=AuthorizationDisposition.REVOKED, settled_at=NOW)
            is AuthorizationSettlement.NOT_AT_SOURCE
        )

    async def test_live_for_settles_the_lapsed_proposal_it_reads(
        self, store: GoalAuthorizationStore, clock: MovableClock
    ) -> None:
        """§1, arm 37: settled ``EXPIRED`` by a ``live_for`` read, **and by no other
        operation** — ``standing``, ``resolve``, ``recent`` and ``export`` settle
        nothing."""
        await store.record(authorization(id="a1"))
        clock.set(EXPIRES + timedelta(hours=1))
        await store.resolve("a1")
        await store.recent()
        await store.export()
        await store.standing(GOAL)
        held = await store.resolve("a1")
        assert held is not None
        assert held.disposition is AuthorizationDisposition.PROPOSED
        await store.live_for(GOAL, TOOL.id)
        settled = await store.resolve("a1")
        assert settled is not None
        assert settled.disposition is AuthorizationDisposition.EXPIRED

    # --- the reads (§16) ---------------------------------------------------

    async def test_standing_returns_the_established_rows_of_that_goal_live_and_lapsed(
        self, store: GoalAuthorizationStore, clock: MovableClock
    ) -> None:
        """§16, arm 33: *"never a ``PROPOSED`` one and never another goal's"*, and
        *"the same rows immediately before and immediately after an
        ``expires_at``"* — the difference being the caller's comparison."""
        await store.record(established(id="a1"))
        await store.record(authorization(id="a2", confirmation="confirm-0002"))
        await store.record(established(id="a3", goal=OTHER_GOAL))
        clock.set(EXPIRES - timedelta(microseconds=1))
        assert [row.id for row in await store.standing(GOAL)] == ["a1"]
        clock.set(EXPIRES + timedelta(hours=1))
        assert [row.id for row in await store.standing(GOAL)] == ["a1"]

    @pytest.mark.parametrize(
        "disposition",
        [
            AuthorizationDisposition.DECLINED,
            AuthorizationDisposition.EXPIRED,
            AuthorizationDisposition.REVOKED,
        ],
    )
    async def test_standing_never_returns_a_retired_row(
        self, store: GoalAuthorizationStore, disposition: AuthorizationDisposition
    ) -> None:
        """§16, arm 33: ``recent`` and ``export`` are where those are read.

        **The arrangement is asserted before the read is**, because the three
        settlements do not all succeed at one instant: ``EXPIRED`` leaves
        ``PROPOSED`` only *"at or after the row's ``expires_at``"* (§1, §12), so
        settling it at :data:`NOW` is answered ``NOT_AT_SOURCE`` and leaves a
        ``PROPOSED`` row — which ``standing`` excludes for a different reason
        entirely, and the case would pass while proving nothing about a retired one.
        """
        await store.record(authorization(id="a1"))
        if disposition is AuthorizationDisposition.REVOKED:
            await store.settle("a1", to=AuthorizationDisposition.ESTABLISHED, settled_at=NOW)
        at = EXPIRES if disposition is AuthorizationDisposition.EXPIRED else NOW
        assert (
            await store.settle("a1", to=disposition, settled_at=at)
            is AuthorizationSettlement.SETTLED
        )
        retired = await store.resolve("a1")
        assert retired is not None
        assert retired.disposition is disposition
        assert await store.standing(GOAL) == ()

    async def test_standing_reads_no_clock(
        self, store: GoalAuthorizationStore, clock: MovableClock
    ) -> None:
        """§16: *"it reports no liveness, reports none and reads none"* — the caller
        compares, against one reading of the injected clock."""
        await store.record(established(id="a1"))
        clock.reset()
        clock.advance_by()
        await store.standing(GOAL)
        assert clock.readings == 0

    async def test_recent_is_newest_first_by_proposed_at_with_an_id_tie_break(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§16: ``RecipientGrantStore.recent``'s order one store over.

        *"Newest first"* is ambiguous between insertion order and decision time,
        which disagree whenever rows are appended out of order, and an ``id``
        tie-break makes the order total rather than merely mostly determined.
        """
        await store.record(authorization(id="b", proposed_at=AT + timedelta(minutes=5)))
        await store.record(authorization(id="c", proposed_at=AT, confirmation="c-2"))
        await store.record(authorization(id="a", proposed_at=AT, confirmation="c-3"))
        assert [row.id for row in await store.recent()] == ["b", "a", "c"]

    async def test_recent_is_bounded(self, store: GoalAuthorizationStore) -> None:
        """§16: every read of a Tier 1 store in this corpus is bounded (ADR-0021 §4)."""
        for index in range(4):
            await store.record(
                authorization(
                    id=f"a{index}",
                    proposed_at=AT + timedelta(minutes=index),
                    confirmation=f"c-{index}",
                )
            )
        assert len(await store.recent(limit=2)) == 2

    @pytest.mark.parametrize(
        "limit",
        [None, True, 1.0, "1", _Deceptive(5)],
        ids=["none", "bool", "float", "str", "int-subclass"],
    )
    async def test_recent_refuses_a_limit_that_is_not_a_strictly_positive_int(
        self, store: GoalAuthorizationStore, limit: object
    ) -> None:
        """§16, arm 58: refused **locally and before any I/O**.

        The type is allowlisted rather than a ``bool`` denylisted, for the reasons
        ``SqliteRecipientGrantStore.recent`` states at length: ``True`` is an
        ``int``, passes ``<= 0``, and is silently taken as a bound of one.
        """
        with pytest.raises(ValueError, match="strictly positive int"):
            await store.recent(limit=limit)  # type: ignore[arg-type]  # the refusal is the point

    @pytest.mark.parametrize("limit", [0, -1])
    async def test_recent_refuses_a_non_positive_limit(
        self, store: GoalAuthorizationStore, limit: int
    ) -> None:
        """§16: SQLite reads ``LIMIT -1`` as *no limit at all*, so the one call
        offering a bounded read would become the unbounded read it exists to avoid."""
        with pytest.raises(ValueError, match="strictly positive int"):
            await store.recent(limit=limit)

    async def test_export_carries_every_row_in_every_disposition_with_its_basis_whole(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§16, arm 33: *"act, span and resolution"* — the data right (ADR-0004 §6)."""
        await store.record(authorization(id="a1"))
        await store.settle("a1", to=AuthorizationDisposition.DECLINED, settled_at=NOW)
        await store.record(established(id="a2"))
        exported = await store.export()
        assert {row.id for row in exported} == {"a1", "a2"}
        basis = exported[0].coverage[0].basis
        assert (basis.act, basis.span, basis.resolution.rule.value) == (
            "turn-0001",
            "up to fifty pounds",
            "as_stated",
        )

    async def test_clear_returns_the_count_and_leaves_the_store_empty(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§16, arm 33: the wholesale erase, and the **only** operation that removes a
        row — *"a store from which a row can be removed is one whose history can be
        rewritten"*."""
        await store.record(authorization(id="a1"))
        await store.record(established(id="a2", goal=OTHER_GOAL))
        assert await store.clear() == 2
        assert await store.export() == ()
        assert await store.recent() == ()

    async def test_an_id_held_before_a_clear_may_be_recorded_again_afterwards(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§16: nothing is retained — no id, no tombstone, no derived value."""
        await store.record(authorization(id="a1"))
        await store.clear()
        assert await store.record(authorization(id="a1")) == "a1"

    async def test_the_store_holds_a_detached_validated_snapshot(
        self, store: GoalAuthorizationStore
    ) -> None:
        """ADR-0097 §3: a caller rewriting the row it handed in **after** ``record``
        accepted it must not widen the history the store has already recorded."""
        row = established(id="a1")
        await store.record(row)
        row.coverage[0].__dict__["fixed"] = "tampered"
        held = await store.resolve("a1")
        assert held is not None
        assert held.coverage[0].fixed is None

    async def test_an_invalid_record_is_refused_as_the_callers_error(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§16, arm 58: *"a refusal is the caller's error and a fault is the
        store's"*, and the subclass relation means a caller catching the base class
        still catches both."""
        assert issubclass(InvalidAuthorizationError, AuthorizationError)
        await store.record(established(id="a1"))
        with pytest.raises(AuthorizationError):
            await store.record(established(id="a2"))

    # --- settle: the late answer (ADR-0254 §1, §12) ------------------------

    async def test_an_answer_arriving_at_or_after_expires_at_establishes_nothing(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§12, §1: *"an expired proposal is refused as an establishment at all"*.

        ``settle`` is the second of §1's exactly two settling operations — *"a
        ``live_for`` read, and **the answer that names it**"* (arm 37) — so the
        expiry settlement is taken first and the requested edge is then evaluated
        from where the row stands. A late approval therefore lands the row
        ``EXPIRED`` and is answered ``NOT_AT_SOURCE``, because the row genuinely does
        not stand at ``PROPOSED`` by the time that edge is considered.

        **Answering ``SETTLED`` would tell the caller an authority came into being
        that §12 says did not**, which is the one direction this must not fail in.
        """
        await store.record(authorization(id="a1"))
        assert (
            await store.settle("a1", to=AuthorizationDisposition.ESTABLISHED, settled_at=EXPIRES)
            is AuthorizationSettlement.NOT_AT_SOURCE
        )
        held = await store.resolve("a1")
        assert held is not None
        assert (held.disposition, held.settled_at) == (
            AuthorizationDisposition.EXPIRED,
            EXPIRES,
        )
        assert await store.standing(GOAL) == ()

    async def test_an_answer_strictly_before_expires_at_still_establishes(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§1: the boundary is *at or after*, so the instant before it is an answer.

        Stated beside the arm above because a lane that compared with ``<`` would
        pass that one and refuse every ordinary approval taken at the deadline's own
        microsecond.
        """
        await store.record(authorization(id="a1"))
        assert (
            await store.settle(
                "a1",
                to=AuthorizationDisposition.ESTABLISHED,
                settled_at=EXPIRES - timedelta(microseconds=1),
            )
            is AuthorizationSettlement.SETTLED
        )
        assert [row.id for row in await store.standing(GOAL)] == ["a1"]

    async def test_a_late_refusal_is_also_the_answer_that_names_it(
        self, store: GoalAuthorizationStore
    ) -> None:
        """Arm 37 states the rule over *"the answer that names it"*, not over an
        approval alone: a refusal arriving after the deadline is as much an answer to
        a question that has lapsed."""
        await store.record(authorization(id="a1"))
        assert (
            await store.settle("a1", to=AuthorizationDisposition.DECLINED, settled_at=EXPIRES)
            is AuthorizationSettlement.NOT_AT_SOURCE
        )
        held = await store.resolve("a1")
        assert held is not None
        assert held.disposition is AuthorizationDisposition.EXPIRED

    async def test_a_caller_asking_for_expired_late_is_answered_settled(
        self, store: GoalAuthorizationStore
    ) -> None:
        """Where the expiry settlement and the requested move coincide, the step has
        taken the edge the caller asked for and says so."""
        await store.record(authorization(id="a1"))
        assert (
            await store.settle("a1", to=AuthorizationDisposition.EXPIRED, settled_at=EXPIRES)
            is AuthorizationSettlement.SETTLED
        )

    async def test_the_late_answer_rule_reads_no_clock(
        self, store: GoalAuthorizationStore, clock: MovableClock
    ) -> None:
        """§16, ADR-0021 §3: ``settled_at`` is the caller's instant and ``expires_at``
        is the row's, so this is a comparison of two **recorded values**.

        A clock moved far past the row's expiry changes nothing about a settlement
        taken with an instant inside it.
        """
        await store.record(authorization(id="a1"))
        clock.reset()
        clock.set(EXPIRES + timedelta(days=30))
        clock.advance_by()
        assert (
            await store.settle("a1", to=AuthorizationDisposition.ESTABLISHED, settled_at=NOW)
            is AuthorizationSettlement.SETTLED
        )
        assert clock.readings == 0

    async def test_a_lapsed_established_row_is_untouched_by_this_rule(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§1: an ``ESTABLISHED`` row past its ``expires_at`` is **not** settled
        ``EXPIRED`` — *"that member is the answer a question never got, and re-using
        it for a lapsed authority would make the two indistinguishable in a
        listing"* — and is still ``REVOKED`` by a withdrawal."""
        await store.record(established(id="a1"))
        assert (
            await store.settle(
                "a1", to=AuthorizationDisposition.REVOKED, settled_at=EXPIRES + timedelta(days=1)
            )
            is AuthorizationSettlement.SETTLED
        )
        held = await store.resolve("a1")
        assert held is not None
        assert held.disposition is AuthorizationDisposition.REVOKED

    async def test_a_move_that_is_not_an_answer_leaves_a_lapsed_proposal_untouched(
        self, store: GoalAuthorizationStore
    ) -> None:
        """Arm 37: settled ``EXPIRED`` by those two operations *"and by no other"*.

        ``PROPOSED`` is left by no edge to ``REVOKED`` or ``SUPERSEDED``, so a call
        asking for one is **not an answer** — it is a malformed call — and a refused
        settlement must mutate nothing. **A lane that took the expiry settlement on
        every move fails this arm**: the refusal would still have written to the
        store.
        """
        for target in (AuthorizationDisposition.REVOKED, AuthorizationDisposition.SUPERSEDED):
            await store.record(authorization(id=f"a-{target.value}", confirmation=target.value))
            assert (
                await store.settle(f"a-{target.value}", to=target, settled_at=EXPIRES)
                is AuthorizationSettlement.NOT_AT_SOURCE
            )
            held = await store.resolve(f"a-{target.value}")
            assert held is not None
            assert (held.disposition, held.settled_at) == (
                AuthorizationDisposition.PROPOSED,
                None,
            )

    # --- record: the origin a path determines (ADR-0254 §1, §6) ------------

    async def test_a_row_naming_a_confirmation_is_written_confirmed(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§1's path (i): ``origin`` is ``CONFIRMED`` *"because the destination set is
        named in the question the user answers"*."""
        await _refuses(store, authorization(id="a1", origin=AuthorizationOrigin.OPENING_ACT))

    async def test_a_row_naming_neither_pointer_is_written_opening_act(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§1's path (iii), and it is what keeps §6's recipient recheck reachable.

        ``origin`` is what route (d) reads to decide whether to re-take the recipient
        authority an opening act rested on, *"read off the row, with no store read
        and no walk back through a chain"*. **A path-(iii) row falsely marked
        ``CONFIRMED`` is exactly the row route (d) would carry alone**, with the
        grant seam consulted zero times — which is the failure arm 70 names.
        """
        await _refuses(
            store,
            authorization(
                id="a1",
                confirmation=None,
                supersedes=None,
                origin=AuthorizationOrigin.CONFIRMED,
                disposition=AuthorizationDisposition.ESTABLISHED,
            ),
        )

    async def test_a_correction_transcribes_the_origin_rather_than_determining_it(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§1: a path-(ii) row carries ``supersedes``, so its origin is neither
        determined by its pointers nor free — it is **transcribed**, and the
        non-widening check is what holds it.

        That is why the rule above is stated over a row carrying **neither** pointer
        rather than over ``confirmation`` alone: a correction of a ``CONFIRMED`` row
        is ``CONFIRMED`` and a correction of an opening act is ``OPENING_ACT``, and
        both are correct.
        """
        await store.record(established(id="a1"))
        await store.record(
            established(
                id="a2",
                supersedes="a1",
                proposed_at=AT + timedelta(minutes=5),
                coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("40")),),
            )
        )
        held = await store.resolve("a2")
        assert held is not None
        assert held.origin is AuthorizationOrigin.OPENING_ACT

    @pytest.mark.parametrize(
        "spelled",
        [
            pytest.param("established", id="a-members-own-value"),
            pytest.param("nonsense", id="no-members-value"),
            pytest.param(None, id="none"),
            pytest.param(0, id="an-int"),
        ],
    )
    async def test_a_settlement_target_that_is_not_the_member_is_refused(
        self, store: GoalAuthorizationStore, spelled: object
    ) -> None:
        """§16 signs ``settle`` with ``to: AuthorizationDisposition``, and an
        implementation refuses anything else **before** it branches on it.

        The reason the guard is owed is that the vocabulary is a ``StrEnum``: a
        member's own value is **equal** to it and is not **identical** to it, and a
        settlement asks both questions — *"is this an edge"* against a set of
        members, by equality; *"is this the establishment"* against one member, by
        identity. ``"established"`` passes the first and fails the second, taking the
        direct write and skipping §1's uniqueness check: **two ``ESTABLISHED`` rows
        of one pair**, which is the state §1 forbids and what arm 56 requires
        ``WOULD_DUPLICATE`` for.

        **A lane that coerced instead of refusing widens the ratified signature**,
        which is a change to the contract rather than an implementation of it
        (golden rule 5); one that branched on identity without any guard writes the
        state §1 forbids.
        """
        await store.record(authorization(id="a1"))
        before = await store.export()
        with pytest.raises(ValueError, match="AuthorizationDisposition"):
            await store.settle("a1", to=cast("AuthorizationDisposition", spelled), settled_at=NOW)
        assert await store.export() == before

    async def test_a_spelled_target_reaches_the_same_edge_check_as_the_member(
        self, store: GoalAuthorizationStore
    ) -> None:
        """The guard moves nothing about a **valid** target: a non-edge is still
        refused as a result rather than raised."""
        await store.record(authorization(id="a1"))
        assert (
            await store.settle("a1", to=AuthorizationDisposition.REVOKED, settled_at=NOW)
            is AuthorizationSettlement.NOT_AT_SOURCE
        )

    async def test_a_proposal_whose_deadline_has_not_passed_is_not_settled_expired(
        self, store: GoalAuthorizationStore
    ) -> None:
        """§1's graph states that edge as *"the deadline passed before an answer"*.

        So its source is a proposal **whose deadline has passed**, and a row whose
        deadline has not is not standing at it. Settling one early would record a
        false fact the store can see is false, from two recorded values and no clock:
        a row saying it lapsed at an instant its own ``expires_at`` says it was still
        live at — which ``recent`` and ``export`` would then render as a question that
        expired, the one thing §1 keeps that member apart from every other to say.

        **Nothing is written**, which is what makes this a refusal rather than a
        different settlement.
        """
        await store.record(authorization(id="a1"))
        assert (
            await store.settle(
                "a1",
                to=AuthorizationDisposition.EXPIRED,
                settled_at=EXPIRES - timedelta(microseconds=1),
            )
            is AuthorizationSettlement.NOT_AT_SOURCE
        )
        held = await store.resolve("a1")
        assert held is not None
        assert (held.disposition, held.settled_at) == (AuthorizationDisposition.PROPOSED, None)

    async def test_the_expired_edge_is_taken_at_the_deadline_itself(
        self, store: GoalAuthorizationStore
    ) -> None:
        """The boundary is *at or after*, so the deadline's own instant takes it.

        Stated beside the arm above because a lane that compared with ``>`` would
        pass that one and refuse the settlement §1 says is owed the moment the
        deadline arrives.
        """
        await store.record(authorization(id="a1"))
        assert (
            await store.settle("a1", to=AuthorizationDisposition.EXPIRED, settled_at=EXPIRES)
            is AuthorizationSettlement.SETTLED
        )

    # --- ADR-0268: the ending, the fence and the closure record ---------------
    #
    # §9's arms 1, 2, 3, 8 and 9, plus the two coverage gaps #2427 books to this
    # lane. Arms 4, 5, 6, 7's act half and 10's reopen half are about an **act**
    # and are `tests/orchestration/`'s; arm 10's database half is about bytes on
    # disk and is the durable store's own.

    @staticmethod
    async def _fenced(store: GoalAuthorizationStore, goal: str = GOAL) -> bool:
        """Whether ``goal`` stands fenced, read the only way the surface allows.

        **The closure record is reached by no member of the store** (ADR-0268 §1,
        its scope on ADR-0004 §6), so the fence is not readable and is not meant to
        be: what it *does* is refuse a ``record``, and that is what is observed
        here. A helper rather than the assertion written out each time, because
        every arm below asks the same question and a second spelling of it would be
        a second answer free to drift.
        """
        row = established(goal=goal, tool=FOURTH_TOOL)
        try:
            await store.record(row)
        except InvalidAuthorizationError:
            return True
        # Recorded, so no fence stood — and the probe is undone, because an arm
        # asserting over the store's contents afterwards must not see it.
        assert (await store.resolve(row.id)) is not None
        await store.settle(row.id, to=AuthorizationDisposition.REVOKED, settled_at=NOW)
        return False

    async def test_the_ending_moves_every_standing_row_and_leaves_each_retired_one(
        self, store: GoalAuthorizationStore, clock: MovableClock
    ) -> None:
        """Arm 1's first limb: the ending over the **set**, and what it does not touch.

        A goal holding established rows for two declarations, one live and one
        lapsed; an unexpired ``PROPOSED`` row; **a ``PROPOSED`` row already past its
        ``expires_at`` and unsettled**; and one row at each of the five retired
        dispositions. ``end_for_goal`` answers **4**.

        **The lapsed proposal is settled ``GOAL_CLOSED`` and not ``EXPIRED``**, which
        is this member's *evaluates no liveness* and the limb of ADR-0254's arm 37
        that ADR-0268 §7 retires as false of it. **Each retired row is byte-identical
        to what it was and excluded from the count** — asserted one disposition at a
        time, so an implementation that excludes one retired member and not the rest
        fails here rather than passing on an aggregate.

        **The instant is the call's own**, on every row it moved.
        """
        # **Strictly after ``proposed_at`` and strictly before the store's reading**,
        # so *"a ``PROPOSED`` row already past its ``expires_at`` and unsettled"* is
        # genuinely past it. An instant the clock has not reached would leave this
        # arm asserting nothing about liveness at all.
        lapsed_expiry = AT + timedelta(minutes=30)
        await store.record(established(id="live", tool=TOOL))
        await store.record(established(id="lapsed", tool=OTHER_TOOL, expires_at=lapsed_expiry))
        await store.record(authorization(id="unexpired", tool=THIRD_TOOL))
        await store.record(authorization(id="past", tool=FOURTH_TOOL, expires_at=lapsed_expiry))
        retired_ids = {}
        for index, disposition in enumerate(RETIRED):
            row_id = f"retired-{disposition.value}"
            retired_ids[disposition] = row_id
            tool = TOOL.model_copy(update={"id": f"retired_tool_{index}"})
            await store.record(authorization(id=row_id, tool=tool))
            if disposition in (
                AuthorizationDisposition.REVOKED,
                AuthorizationDisposition.SUPERSEDED,
            ):
                await store.settle(row_id, to=AuthorizationDisposition.ESTABLISHED, settled_at=AT)
            at = EXPIRES if disposition is AuthorizationDisposition.EXPIRED else AT
            assert (
                await store.settle(row_id, to=disposition, settled_at=at)
                is AuthorizationSettlement.SETTLED
            ), disposition
        before = {row.id: row for row in await store.export()}

        # The clock is set past **every** instant in play, so *"it evaluates no
        # liveness"* is asked of a store that could tell the difference on either
        # reading — the two rows whose ``expires_at`` the clock has passed, and the
        # two it has now passed as well. **No read is taken in between**: a
        # ``live_for`` here would settle the lapsed proposal ``EXPIRED`` itself
        # (ADR-0254 §1's two settling operations), which is the state this arm exists
        # to keep it out of.
        clock.set(EXPIRES + timedelta(days=1))
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=4) == 4

        held = {row.id: row for row in await store.export()}
        for row_id in ("live", "lapsed", "unexpired", "past"):
            assert held[row_id].disposition is AuthorizationDisposition.GOAL_CLOSED, row_id
            assert held[row_id].settled_at == NOW, row_id
            assert held[row_id].expires_at == before[row_id].expires_at, row_id
        for disposition, row_id in retired_ids.items():
            assert held[row_id] == before[row_id], disposition

    async def test_a_second_ending_answers_zero_and_leaves_the_fence_standing(
        self, store: GoalAuthorizationStore
    ) -> None:
        """Arm 1: *"A second call answers 0 and leaves the fence set."*

        **And only because the fence stood throughout**, which is what the ``record``
        refusal in between is evidence of: the version governs staleness, never
        emptiness.
        """
        await store.record(established(id="a1"))
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=4) == 1
        assert await self._fenced(store)
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=4) == 0
        assert await self._fenced(store)

    async def test_a_goal_the_store_holds_no_row_of_answers_zero_and_is_fenced(
        self, store: GoalAuthorizationStore
    ) -> None:
        """Arm 1: it *"answers 0, does not raise, **and is fenced all the same**"*.

        The shape ``standing`` already takes for a goal it does not hold — and the
        fence is asserted by a ``record`` refused afterwards, because the record is
        reached by no member of the store.
        """
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=4) == 0
        assert await self._fenced(store)

    async def test_the_record_keeps_the_higher_version_and_a_lower_call_moves_nothing(
        self, store: GoalAuthorizationStore
    ) -> None:
        """Arm 1: *"the record keeps the higher version"*, both ways round.

        A second ``end_for_goal`` at a **higher** version raises it — proved by a
        ``clear_closure`` at the *first* version then answering ``False`` with the
        fence still standing — while one at a **lower** version leaves it where it
        was, and **neither moves a row**.
        """
        await store.record(established(id="a1"))
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=4) == 1
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=9) == 0
        assert await store.clear_closure(GOAL, goal_version=4) is False
        assert await self._fenced(store)
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=2) == 0
        assert await self._fenced(store)
        held = await store.resolve("a1")
        assert held is not None
        assert (held.disposition, held.settled_at) == (AuthorizationDisposition.GOAL_CLOSED, NOW)

    async def test_a_row_admitted_after_a_reopen_is_ended_by_a_call_at_that_same_version(
        self, store: GoalAuthorizationStore
    ) -> None:
        """Arm 1: *"the version governs **staleness, never emptiness**"*.

        ADR-0268 §1 is explicit that a repeated call answers ``0`` *"**but only
        because the fence stood throughout**"* — and that *"where a reopen lifted it
        and a row was admitted since, that call ends the row and counts it"*, raising
        the record and standing the fence as the member's first clause says.

        **This is the arm an implementation testing staleness with ``>=`` slips
        past.** Every other case answers ``0`` at the standing version because there
        is nothing left to move, so the two readings are indistinguishable there; here
        there is something to move, and a store that discarded the call as stale would
        leave a live row standing under a goal that has just closed.
        """
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=4) == 0
        assert await store.clear_closure(GOAL, goal_version=4) is True
        await store.record(established(id="admitted"))

        assert await store.end_for_goal(GOAL, at=NOW, goal_version=4) == 1

        held = await store.resolve("admitted")
        assert held is not None
        assert (held.disposition, held.settled_at) == (
            AuthorizationDisposition.GOAL_CLOSED,
            NOW,
        )
        assert await self._fenced(store), "and the fence stands again"

    async def test_clear_closure_against_a_standing_fence_at_that_version_lifts_it(
        self, store: GoalAuthorizationStore
    ) -> None:
        """Arm 1: ``True``, the fence lifted, **and the record stands at that version**.

        The lift is asserted by a ``record`` for that goal then succeeding, and the
        record's survival by a second ``clear_closure`` at the same version answering
        ``False`` — *"lifts the fence and **removes no record**"*.
        """
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=4) == 0
        assert await store.clear_closure(GOAL, goal_version=4) is True
        assert not await self._fenced(store)
        assert await store.clear_closure(GOAL, goal_version=4) is False

    async def test_clear_closure_against_a_standing_fence_at_a_lower_version_lifts_it(
        self, store: GoalAuthorizationStore
    ) -> None:
        """#2427's first gap, and the arm that closes it.

        ADR-0268 §1 specifies ``clear_closure`` over a record standing **"at or
        below"** ``goal_version``. The ADR's own arm 1 asserts the standing-fence
        path only at the **exact** version, and the lower-version path only where the
        fence is **already lifted** — so an equality-only implementation passes every
        prescribed arm while ``clear_closure(goal_version=6)`` against a fence
        standing at 5 answers ``False`` and **leaves that fence standing**, which is
        a reopen that could not admit a fresh row.

        A fence standing at 5, cleared at 6: ``True``, the fence lifted — a ``record``
        for that goal then succeeding — and the record standing at **6**, which a
        ``clear_closure`` back at 5 shows by answering ``False``.
        """
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=5) == 0
        assert await store.clear_closure(GOAL, goal_version=6) is True
        assert not await self._fenced(store)
        assert await store.clear_closure(GOAL, goal_version=5) is False

    async def test_clear_closure_against_a_lifted_record_answers_false_and_still_raises_it(
        self, store: GoalAuthorizationStore
    ) -> None:
        """Arm 1: ``False`` *"and still raises the watermark to the version passed"*.

        Proved the way the ADR says to prove it — by a **delayed** ``end_for_goal`` at
        that lower version then answering ``0``, moving no row and standing no fence.
        A lane that answered ``False`` by leaving the record alone would let that
        delayed call fence a goal a reopen had just opened for business.
        """
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=4) == 0
        assert await store.clear_closure(GOAL, goal_version=4) is True
        assert await store.clear_closure(GOAL, goal_version=9) is False
        await store.record(established(id="fresh"))
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=4) == 0
        held = await store.resolve("fresh")
        assert held is not None
        assert held.disposition is AuthorizationDisposition.ESTABLISHED
        assert not await self._fenced(store)

    async def test_clear_closure_over_a_goal_with_no_record_writes_none(
        self, store: GoalAuthorizationStore
    ) -> None:
        """Arm 1: ``False``, *"writes none and raises nothing"*.

        The absence of a written record is what the delayed ``end_for_goal`` at a
        **lower** version shows: had this call written one at 9, that call would have
        been discarded as stale and left the row standing.
        """
        assert await store.clear_closure(GOAL, goal_version=9) is False
        await store.record(established(id="a1"))
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=4) == 1

    async def test_a_record_outliving_its_goal_discards_the_new_goals_own_ending(
        self, store: GoalAuthorizationStore
    ) -> None:
        """Arm 1's last limb, and §8's residual this decision **adds**, pinned.

        *"A goal's record standing, that goal deleted from ``PlanStore``, a **new**
        goal saved under the same identifier at a lower version — its
        ``end_for_goal`` answers ``0``, leaving its row ``ESTABLISHED`` under a goal
        that closes."*

        **The ``PlanStore`` half is not a store's to exhibit** — ``delete_goal``
        reaches this store not at all, which is exactly why the residual exists — so
        what is pinned here is the whole of what this store's surface shows: a
        lifted record standing **above** a later goal's version discards that goal's
        own ending, and the row survives. A lane that made either member lower the
        watermark would pass a suite that never asked.
        """
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=9) == 0
        assert await store.clear_closure(GOAL, goal_version=9) is True
        await store.record(established(id="reborn"))
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=2) == 0
        held = await store.resolve("reborn")
        assert held is not None
        assert held.disposition is AuthorizationDisposition.ESTABLISHED

    async def test_neither_member_reads_the_clock(
        self, store: GoalAuthorizationStore, clock: MovableClock
    ) -> None:
        """#2427's second gap, and the arm that closes it.

        ADR-0268 §1 states it of both — ``end_for_goal`` *"reads **no clock**, the
        instant being the caller's"*, and ``clear_closure`` *"settles nothing,
        revives nothing and **reads no clock**"* — and no prescribed arm asserts it.
        An implementation could call the injected clock and discard the value,
        passing every caller-instant assertion.

        **Asserted over the reading count rather than against a clock that raises**,
        which is the same claim in the form this suite can make and is strictly
        stronger: a member that never *calls* the clock cannot be made to fail by
        poisoning it, while one that calls and discards is caught here and would be
        caught there. The subject is built over the shared clock by a fixture the
        triad check must be able to evaluate with no argument, so a poisoned subject
        is not something this suite can hand itself.
        """
        await store.record(established(id="a1"))
        clock.reset()
        before = clock.readings
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=4) == 1
        assert await store.clear_closure(GOAL, goal_version=4) is True
        assert clock.readings == before

    async def test_a_settlement_cannot_enter_the_step_the_ending_is_inside(self) -> None:
        """Arm 2's other half, as an interleaving.

        A settlement to ``ESTABLISHED`` fired into the window the ending holds open
        does not complete while the step is open, and answers ``NOT_AT_SOURCE``
        afterwards **over a row the same step ended** — the store needing no
        conjunct on ``settle`` for it, because the row it names now stands where no
        edge to ``ESTABLISHED`` leaves.
        """
        async with self.store_suspended_mid_write() as harness:
            store = harness.store
            await store.record(authorization(id="a1"))
            suspended = harness.arm("end_for_goal")

            ending = asyncio.ensure_future(store.end_for_goal(GOAL, at=NOW, goal_version=4))
            settling: asyncio.Task[object] | None = None
            try:
                await suspended.reached()
                settling = asyncio.ensure_future(
                    store.settle("a1", to=AuthorizationDisposition.ESTABLISHED, settled_at=NOW)
                )
                await settle_loop()
                assert not settling.done(), _RELEASED_EARLY
            finally:
                suspended.release()

            assert await ending == 1
            assert await settling is AuthorizationSettlement.NOT_AT_SOURCE
            held = await store.resolve("a1")
            assert held is not None
            assert held.disposition is AuthorizationDisposition.GOAL_CLOSED
            assert await store.standing(GOAL) == ()

    async def test_an_ended_row_is_never_live_is_absent_from_standing_and_is_exported(
        self, store: GoalAuthorizationStore, clock: MovableClock
    ) -> None:
        """Arm 3's last limb.

        A ``GOAL_CLOSED`` row is **never live**, is **absent from ``standing``**, and
        is **present in ``recent`` and in ``export``** carrying its coverage, its
        basis and its **unmoved** ``expires_at`` — ADR-0254 §12's no-deletion rule
        binding entire, so a user reading the record of a finished request still
        finds what they authorised and when it ended.
        """
        row = established(id="a1")
        await store.record(row)
        clock.set(EXPIRES - timedelta(hours=1))
        assert await store.live_for(GOAL, TOOL.id) is not None
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=4) == 1

        assert await store.live_for(GOAL, TOOL.id) is None
        assert await store.standing(GOAL) == ()
        exported = await store.export()
        assert [one.id for one in exported] == ["a1"]
        assert [one.id for one in await store.recent()] == ["a1"]
        assert exported[0].coverage == row.coverage
        assert exported[0].expires_at == row.expires_at
        assert exported[0].disposition is AuthorizationDisposition.GOAL_CLOSED

    async def test_a_proposal_across_a_closure_and_a_reopen_settles_nothing(
        self, store: GoalAuthorizationStore
    ) -> None:
        """Arm 8: what the fence is for.

        An unexpired ``PROPOSED`` row exists when the goal closes; it is ended
        ``GOAL_CLOSED``; the goal is reopened and the fence cleared; **an answer
        naming that row then settles nothing**, answering ``NOT_AT_SOURCE`` — so no
        call of the reopened goal is covered by it. A proposal left standing could
        be answered after the reopen and would cover calls of the reopened request
        under a bound the user stated for the request that ended.
        """
        await store.record(authorization(id="a1"))
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=4) == 1
        assert await store.clear_closure(GOAL, goal_version=4) is True
        assert (
            await store.settle("a1", to=AuthorizationDisposition.ESTABLISHED, settled_at=NOW)
            is AuthorizationSettlement.NOT_AT_SOURCE
        )
        assert await store.standing(GOAL) == ()
        assert await store.live_for(GOAL, TOOL.id) is None

    async def test_a_record_across_the_closure_is_refused_until_the_fence_is_cleared(
        self, store: GoalAuthorizationStore
    ) -> None:
        """Arm 8's second half, **and §8's booked residual asserted rather than assumed**.

        Across the closure a ``record`` for that goal is refused — before the
        reopen's ``ACTIVE`` write and after it — and admitted **only** after
        ``clear_closure``. That last admission is the residual ADR-0268 §8 declines
        to close: *"a ``record`` begun before the closure and arriving after the
        clear succeeds"*, carrying an authority the user gave for the request that
        ended. It is pinned here so a later lane cannot mistake it for a defect, and
        closing it would take a retained generation on ``record`` itself, which §8
        refuses to have inferred from silence.
        """
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=4) == 0
        await _refuses(store, established(id="across"))
        # The ``ACTIVE`` write is `orchestration`'s and reaches this store not at
        # all, so what a store can exhibit is that nothing between the ending and
        # the clear lifts the fence.
        await _refuses(store, established(id="across"))
        assert await store.clear_closure(GOAL, goal_version=4) is True
        assert await store.record(established(id="across")) == "across"

    async def test_the_fence_refusal_names_no_new_error_class(
        self, store: GoalAuthorizationStore
    ) -> None:
        """ADR-0268 §1: the class is **reused and none is minted**.

        ``InvalidAuthorizationError`` is what ADR-0254 §16 gives *"a write this store
        does not admit"*, and a caller wanting only *"the store would not accept
        this"* keeps one handler — which ``AuthorizationError`` being its base is
        what provides.
        """
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=4) == 0
        await _refuses(store, established(id="fenced"), AuthorizationError)

    async def test_clear_erases_the_closure_records_with_the_rows(
        self, store: GoalAuthorizationStore, clock: MovableClock
    ) -> None:
        """Arm 9: *"the consequence is asserted rather than avoided"*.

        ``clear`` answers the count of **rows** and the store holds none — a goal
        whose fence a reopen had already lifted included, its record going with the
        rest. A ``record`` for the closed goal afterwards **succeeds**, which is
        ADR-0268 §1's universal holding *absent a ``clear``* and is the stated cost;
        **and that row is reached by no ending and lapses on its own
        ``expires_at``**, which is §3's rule over it and not a case of its own.
        """
        await store.record(established(id="a1"))
        await store.record(established(id="a2", goal=OTHER_GOAL))
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=4) == 1
        assert await store.end_for_goal(OTHER_GOAL, at=NOW, goal_version=4) == 1
        assert await store.clear_closure(OTHER_GOAL, goal_version=4) is True

        assert await store.clear() == 2
        assert await store.export() == ()
        assert not await self._fenced(store)
        assert not await self._fenced(store, OTHER_GOAL)

        after = established(id="after")
        assert await store.record(after) == "after"
        clock.set(after.expires_at - timedelta(microseconds=1))
        assert await store.live_for(GOAL, TOOL.id) is not None
        clock.set(after.expires_at)
        assert await store.live_for(GOAL, TOOL.id) is None

    async def test_a_fenced_goal_the_store_holds_no_row_of_is_carried_by_no_export(
        self, store: GoalAuthorizationStore
    ) -> None:
        """Arm 9's last limbs, which are ADR-0268's **scope on ADR-0004 §6** asserted.

        With a goal the store holds **no** row of fenced, ``export`` answers
        **nothing** and the record is reached by no member of the store — the
        sharpest case in that scope, an identifier retained behind no row at all.
        And an ``export`` taken **before** a ``clear`` carries the ``GOAL_CLOSED``
        rows and **no fence**, §16's snapshot being over rows.

        **That absence is the decision's stated and bounded cost and is not a defect
        to fix here** (#2410): a surface for the record would take a new
        ``core/types.py`` type and a third store member, and is ADR-0004 §6's
        decision rather than this one's.
        """
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=4) == 0
        assert await store.export() == ()
        assert await self._fenced(store)

        await store.record(established(id="a1", goal=OTHER_GOAL))
        assert await store.end_for_goal(OTHER_GOAL, at=NOW, goal_version=4) == 1
        exported = await store.export()
        assert [one.id for one in exported] == ["a1"]
        assert exported[0].disposition is AuthorizationDisposition.GOAL_CLOSED

    @pytest.mark.parametrize(
        "version",
        [0, 1, _MAX_INT64, _MAX_INT64 + 1, 2**70, -1, -(2**70), _PAST_DECIMAL, -_PAST_DECIMAL],
        ids=lambda version: format(version, "x")[:12],
    )
    async def test_the_watermark_holds_any_int_the_goal_domain_admits(
        self, store: GoalAuthorizationStore, version: int
    ) -> None:
        """ADR-0268 §1 states the watermark over an **unrestricted** ``int``.

        ``Goal.version`` carries ``ge=0`` and **no ceiling** (ADR-0249 §1) and
        ``PlanStore`` persists a goal as JSON, which has none either — so a goal can
        stand above any fixed width, and an implementation whose storage is narrower
        **widens the storage** rather than the contract.

        **A ceiling strands the goal rather than reporting anything**, which is why
        an earlier revision's refusal was wrong: such a goal abandons and fences
        successfully, its version advances, and the reopen's ``ACTIVE`` write then
        lands **before** the ending is refused — leaving a live goal fenced against
        every authorization for good. Adversarial and architecture review, round 2,
        ``blocker`` each.

        The watermark is asserted by what it *does*: a call at the version itself
        lifts the fence, and one **below** it is discarded as stale. Negative values
        are in the table because nothing here states a floor — that is
        ``PlanStore``'s to decide — and a store inventing one would be deciding a
        rule ADR-0268 leaves alone.
        """
        await store.record(established(id="a1"))
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=version) == 1
        assert await self._fenced(store)
        assert await store.clear_closure(GOAL, goal_version=version) is True
        assert not await self._fenced(store)
        # Read back exactly: a version one below is stale against what was written.
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=version - 1) == 0

    @pytest.mark.parametrize(
        ("passed", "means"),
        [(True, 1), (False, 0), (1, 1), (0, 0), (7, 7), (_MAX_INT64 + 1, _MAX_INT64 + 1)],
        ids=repr,
    )
    @pytest.mark.parametrize("member_name", _ENDING_OPS)
    async def test_the_version_a_member_stores_is_exactly_the_one_it_was_passed(
        self, store: GoalAuthorizationStore, member_name: str, passed: int, means: int
    ) -> None:
        """The watermark a call writes is pinned **from both sides**, so it is the value.

        **This is the general form of a question four review rounds asked one case
        at a time**, and it is stated once here for the reason the encoding probe
        exists: an arm that pins a *bound* leaves every value above it passing. A
        case asserting only that ``clear_closure(True)`` lifted a fence standing at
        1 admits an implementation mapping ``True`` to **2**; one asserting only that
        a later call was stale admits everything below. Adversarial review, rounds
        10 and 11, ``major`` each.

        So each call's record is squeezed: the version **one below** what was passed
        is **stale** against it, and the version passed **acts**. Nothing between
        them is left free, and ``True``/``False`` ride in the same table as the
        integers they mean — ``operator.index`` normalising them rather than a guard
        refusing them, because ADR-0268 §1 states the member over ``int`` and Python
        says a ``bool`` is one.

        ``_MAX_INT64 + 1`` is in the table because the squeeze has to hold where the
        storage stops being a machine integer, which is where the encoding lives.
        """
        await store.record(established(id="a1"))
        if member_name == "clear_closure":
            # A fence has to stand for a clear to do anything, and it must stand
            # *above* the version under test so the call is not stale against it.
            assert await store.end_for_goal(GOAL, at=NOW, goal_version=means) == 1
            assert await store.clear_closure(GOAL, goal_version=passed) is True
        else:
            assert await store.end_for_goal(GOAL, at=NOW, goal_version=passed) == 1
            assert await self._fenced(store)
            assert await store.clear_closure(GOAL, goal_version=means) is True

        # **Below is stale**: a record standing at ``means`` discards this call.
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=means - 1) == 0
        assert not await self._fenced(store), "a stale ending raises no fence"

        # **At the version, it acts** — which a record standing anywhere *above*
        # ``means`` would refuse, so the two together pin it exactly.
        await store.record(established(id="a2"))
        assert await store.end_for_goal(GOAL, at=NOW, goal_version=means) == 1
        assert await self._fenced(store)

    @pytest.mark.parametrize("member_name", _ENDING_OPS)
    async def test_a_version_that_is_not_an_integer_is_pythons_own_type_error(
        self, store: GoalAuthorizationStore, member_name: str
    ) -> None:
        """A ``float`` is not a version, and truncating one would invent a watermark.

        ``TypeError`` rather than a refusal or a fault: ``mypy --strict`` signs the
        member with ``int`` and holds every caller in this tree, so this is the one
        caller a type cannot reach — and the answer Python itself gives for a value
        that is not an integer. **Both implementations answer identically**, which a
        store coercing where the fake refused (or the reverse) would break (ADR-0084
        §4). **Nothing is written on the way out.**
        """
        await store.record(established(id="a1"))
        before = await store.export()
        with pytest.raises(TypeError):
            await self._ending_call(store, member_name, GOAL, goal_version=4.5)
        assert await store.export() == before
        assert not await self._fenced(store)

    # --- ADR-0268 arm 7's cancellation shape, per member ----------------------

    def store_suspended_mid_write(
        self,
    ) -> AbstractAsyncContextManager[SuspendedMidWrite[GoalAuthorizationStore]]:
        """Supply a store whose named member can be stopped *inside* its resource.

        Overridden by both subjects. ADR-0060 §3 is explicit that propagation alone
        is not the evidence — *"a propagation-only suite would certify exactly the
        bug this ADR exists to catch"* — so the case cancels the call while it is
        suspended and then watches what a **second** caller can reach.

        The returned :class:`SuspendedMidWrite` carries the store, its
        ``ResourceLog``, and an ``arm(member)`` lever the case calls *after* its
        preconditions, so a fake arming one modelled resource suspends the member
        under test rather than a setup write.
        """
        raise NotImplementedError

    @staticmethod
    def _ending_call(
        store: GoalAuthorizationStore,
        member_name: str,
        goal: str,
        *,
        goal_version: Any = 4,
    ) -> Coroutine[object, object, object]:
        """One call of ``member_name`` against ``goal``, as the case drives it.

        ``goal_version`` is typed loosely on purpose: the guard arms drive values
        ``mypy`` would refuse at a call site, which is exactly the caller a type
        cannot reach and the reason the guard exists at all.
        """
        if member_name == "end_for_goal":
            return store.end_for_goal(goal, at=NOW, goal_version=goal_version)
        return store.clear_closure(goal, goal_version=goal_version)

    @pytest.mark.parametrize("member_name", _ENDING_OPS)
    async def test_a_cancelled_ending_call_holds_its_resource_until_the_work_finishes(
        self, member_name: str
    ) -> None:
        """Arm 7's cancellation shape, taken once per member (ADR-0060 §1, §3).

        **ADR-0060 §1's two guarantees are what is asserted**: the
        ``CancelledError`` **arrives** at the caller unabsorbed, and the resource is
        **safe** — a second call of this store reaches the resource only once the
        cancelled call's work has finished, and the store still serves reads after.
        The second call is what makes this a test of the invariant rather than of
        propagation, because a single cancelled call in isolation looks identical
        either way.

        **This store is not among ADR-0060 §3's four** — that scope is its own — but
        §1's rule binds every Protocol in the file, and ADR-0268 §9 arm 7 owes the
        shape at every call of both members.

        **No composition of outcomes is asserted, and none is enumerated.** ADR-0060
        §1 rules a cancelled write's effect *"indeterminate to the caller"* — *"A
        cancelled write may or may not have committed. The caller may assume
        neither"* — so each cancelled write admits **both** of its own outcomes and
        no limb here asserts it left nothing. A cancelled ``clear_closure`` that
        landed leaves the rows ended and the fence **lifted**, which nothing refuses.
        """
        async with self.store_suspended_mid_write() as harness:
            store = harness.store
            await store.record(established(id="seed"))
            suspended = harness.arm(member_name)
            visited_before = harness.log.visits

            first = asyncio.ensure_future(self._ending_call(store, member_name, GOAL))
            second: asyncio.Task[object] | None = None
            try:
                await suspended.reached()
                first.cancel()
                await settle_loop()

                second = asyncio.ensure_future(self._ending_call(store, member_name, OTHER_GOAL))
                await settle_loop()
                assert not second.done(), _RELEASED_EARLY

                # Again, because deferring one cancellation is not the contract: a
                # second delivered while the deferred wait runs must not escape and
                # unwind out of the resource either.
                first.cancel()
                await settle_loop()
                assert not second.done(), _RELEASED_EARLY
            finally:
                suspended.release()

            with pytest.raises(asyncio.CancelledError):
                await first
            assert second is not None
            await second

            # Decisive where the blocked-caller check is not: the two calls were
            # never inside the resource at the same time.
            assert not harness.log.overlapped, _RELEASED_EARLY
            assert harness.log.visits - visited_before == 2, (
                "both calls should have reached the resource by now"
            )
            # The store still serves reads, which is the other half of *safe*.
            assert {one.id for one in await store.export()} == {"seed"}

    async def test_a_record_cannot_enter_the_step_the_ending_is_inside(
        self,
    ) -> None:
        """Arm 2, made an interleaving rather than a scheduling coincidence.

        ``asyncio.gather`` over two coroutines on one loop proves little on its own:
        whichever runs first may run to completion, and the arm above would pass
        against a store whose step was not indivisible at all. Here the ending is
        **held open inside its resource** and a ``record`` of the same goal is fired
        into that window.

        **What no interleaving produces** (arm 2): the ``record`` does not complete
        while the step is open, and once it is released the store is in one of
        exactly two states — the write landed **before** the step and the row is
        ended and counted, or it is **refused**. In neither does a row of that goal
        stand ``PROPOSED`` or ``ESTABLISHED`` afterwards, and in neither is the set
        the step saw partitioned.
        """
        async with self.store_suspended_mid_write() as harness:
            store = harness.store
            await store.record(established(id="seed"))
            suspended = harness.arm("end_for_goal")

            ending = asyncio.ensure_future(store.end_for_goal(GOAL, at=NOW, goal_version=4))
            writing: asyncio.Task[object] | None = None
            try:
                await suspended.reached()
                writing = asyncio.ensure_future(store.record(established(id="racer")))
                await settle_loop()
                assert not writing.done(), _RELEASED_EARLY
            finally:
                suspended.release()

            assert await ending == 1
            refused = None
            try:
                await writing
            except InvalidAuthorizationError as exc:  # the fence was up first
                refused = exc

            held = await store.resolve("racer")
            if refused is not None:
                assert held is None
            else:
                assert held is not None
                assert held.disposition is AuthorizationDisposition.GOAL_CLOSED
            assert await store.standing(GOAL) == ()
            seed = await store.resolve("seed")
            assert seed is not None
            assert seed.disposition is AuthorizationDisposition.GOAL_CLOSED
