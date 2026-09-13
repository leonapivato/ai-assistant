"""The canonical goal-authorization fakes, bound to the three shared suites.

ADR-0254 §16 lands a triad per Protocol, and this is the third artifact of each:
without a binding class the suites collect nothing and the fakes are unverified
however many files exist (``tests/core/test_protocol_triad.py`` makes that
mechanical).

**Each narrow suite is bound twice** — once against its own narrow fake and once
against
:class:`~ai_assistant.testing.goal_authorizations.FakeGoalAuthorizationStore` —
which is ADR-0254 §16's *"three faces, one object"* turned from an assertion into a
test. It also means a divergence between a narrow fake and the store fake is a
failure rather than a latent surprise, which matters here because all three answer
from one shared log and a future lane could easily give one of them its own.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from authorization_builders import AT, EXPIRES, GOAL, NOW, SHARED_CLOCK, TOOL
from goal_authorization_contract import (
    AuthorizationResolutionContract,
    GoalAuthorizationsContract,
    GoalAuthorizationStoreContract,
    established,
)

from ai_assistant.core.errors import AuthorizationError
from ai_assistant.core.types import AuthorizationDisposition, AuthorizationSettlement
from ai_assistant.testing import (
    FakeAuthorizationResolution,
    FakeGoalAuthorizations,
    FakeGoalAuthorizationStore,
    authorization,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ai_assistant.core.protocols import (
        AuthorizationResolution,
        GoalAuthorizations,
        GoalAuthorizationStore,
    )
    from ai_assistant.core.types import Authorization


class TestFakeGoalAuthorizationsContract(GoalAuthorizationsContract):
    """``FakeGoalAuthorizations`` against the query seam's clauses."""

    @pytest.fixture
    def authorizations(self) -> GoalAuthorizations:
        """The fake, over the suite's shared clock."""
        return FakeGoalAuthorizations(now=SHARED_CLOCK.reset())

    async def hold(self, authorizations: GoalAuthorizations, *rows: Authorization) -> None:
        """Append through the fake's own test-only seeding hook."""
        assert isinstance(authorizations, FakeGoalAuthorizations)
        authorizations.hold(*rows)

    async def settle(
        self,
        authorizations: GoalAuthorizations,
        authorization_id: str,
        *,
        to: AuthorizationDisposition,
        settled_at: datetime = NOW,
    ) -> AuthorizationSettlement:
        """Settle through the fake's own test-only hook."""
        assert isinstance(authorizations, FakeGoalAuthorizations)
        return authorizations.settle(authorization_id, to=to, settled_at=settled_at)


class TestFakeGoalAuthorizationStoreAsGrantsContract(GoalAuthorizationsContract):
    """The **store** fake against the query seam's clauses.

    ADR-0254 §16's *"three faces, one object"*: the store satisfies this narrow
    Protocol structurally, so the same suite must pass against it.
    """

    @pytest.fixture
    def authorizations(self) -> GoalAuthorizations:
        """The store fake, over the suite's shared clock."""
        return FakeGoalAuthorizationStore(now=SHARED_CLOCK.reset())

    async def hold(self, authorizations: GoalAuthorizations, *rows: Authorization) -> None:
        """Record through the store fake's own write path."""
        assert isinstance(authorizations, FakeGoalAuthorizationStore)
        for row in rows:
            await authorizations.record(row)

    async def settle(
        self,
        authorizations: GoalAuthorizations,
        authorization_id: str,
        *,
        to: AuthorizationDisposition,
        settled_at: datetime = NOW,
    ) -> AuthorizationSettlement:
        """Settle through the store fake's own write path."""
        assert isinstance(authorizations, FakeGoalAuthorizationStore)
        return await authorizations.settle(authorization_id, to=to, settled_at=settled_at)


class TestFakeAuthorizationResolutionContract(AuthorizationResolutionContract):
    """``FakeAuthorizationResolution`` against the resolution seam's clauses."""

    @pytest.fixture
    def resolution(self) -> AuthorizationResolution:
        """The fake."""
        return FakeAuthorizationResolution()

    async def hold_for_resolution(
        self, resolution: AuthorizationResolution, *rows: Authorization
    ) -> None:
        """Append through the fake's own test-only seeding hook."""
        assert isinstance(resolution, FakeAuthorizationResolution)
        resolution.hold(*rows)

    async def settle_for_resolution(
        self,
        resolution: AuthorizationResolution,
        authorization_id: str,
        *,
        to: AuthorizationDisposition,
    ) -> AuthorizationSettlement:
        """Settle through the fake's own test-only hook."""
        assert isinstance(resolution, FakeAuthorizationResolution)
        return resolution.settle(authorization_id, to=to, settled_at=NOW)


class TestFakeGoalAuthorizationStoreContract(GoalAuthorizationStoreContract):
    """``FakeGoalAuthorizationStore`` against all three suites."""

    @pytest.fixture
    def store(self) -> GoalAuthorizationStore:
        """The store fake, over the suite's shared clock."""
        return FakeGoalAuthorizationStore(now=SHARED_CLOCK.reset())


class TestTheFakesOwnScriptedFaults:
    """The fault branches only a double can arrange, and the contract requires.

    ADR-0254 §6's fault clause is stated over ``ActionPolicy``, and §7's over
    ``AuditTrail.record`` — but **neither is reachable at all** unless the seam a
    conforming implementation is compared against can be made to fail. These pin
    that the fakes offer that branch, and that they raise the class the two
    consumers' fail-closed branches are written against.
    """

    async def test_live_for_raises_the_seams_own_error_when_armed(self) -> None:
        """§6: a fault **takes the bar** and is never read as an absence."""
        seam = FakeGoalAuthorizations(now=SHARED_CLOCK.reset())
        seam.fail_live_for()
        with pytest.raises(AuthorizationError):
            await seam.live_for(GOAL, TOOL.id)

    async def test_resolve_raises_the_seams_own_error_when_armed(self) -> None:
        """§7: the trail refuses the write rather than proceeding."""
        seam = FakeAuthorizationResolution()
        seam.fail_resolve()
        with pytest.raises(AuthorizationError):
            await seam.resolve("a1")

    async def test_the_store_fakes_reads_and_writes_each_fault_apart(self) -> None:
        """§16: a **store fault** is the base class and a refusal is the subclass.

        ``settle``'s refusals are **results** rather than exceptions, so a scripted
        write fault is the only way to reach that member's fault branch at all.
        """
        store = FakeGoalAuthorizationStore(now=SHARED_CLOCK.reset())
        await store.record(authorization(id="a1"))
        store.fail_reads()
        with pytest.raises(AuthorizationError):
            await store.live_for(GOAL, TOOL.id)
        with pytest.raises(AuthorizationError):
            await store.resolve("a1")
        with pytest.raises(AuthorizationError):
            await store.standing(GOAL)
        store.fail_writes()
        with pytest.raises(AuthorizationError):
            await store.settle("a1", to=AuthorizationDisposition.DECLINED, settled_at=EXPIRES)
        with pytest.raises(AuthorizationError):
            await store.clear()


class TestTwoLiveRowsPlantedBehindTheStoresBack:
    """ADR-0254 §1, §16, arm 36: ``live_for`` **raises** rather than answering ``None``.

    *"A query that chose between two would be the composition §5 declines"*, and
    ``None`` is this seam's word for *"the store holds no live record"* — two rows
    are not none of them. §16's fault clause then takes §6's bar, so an integrity
    failure **asks** rather than authorising a request neither row covers.

    **A lane that answered ``None`` fails this arm.**

    Reachable only by reaching past ``record``'s uniqueness refusal, which is what
    *"put there behind the store's back"* means: the fake's own log is the thing a
    test can reach here, and ``tests/permissions/test_goal_authorizations.py``
    reaches the durable store's rows the equivalent way, with raw SQL.
    """

    async def test_live_for_raises_where_two_live_rows_would_answer(self) -> None:
        """Two ``ESTABLISHED`` rows of one pair, planted past the write path."""
        store = FakeGoalAuthorizationStore(now=SHARED_CLOCK.reset())
        await store.record(established(id="a1"))
        planted = established(id="a2", expires_at=EXPIRES + timedelta(hours=1))
        store._log._records.append(planted)  # reaching past `record` is the point
        with pytest.raises(AuthorizationError, match="live rows"):
            await store.live_for(GOAL, TOOL.id)

    async def test_the_planted_state_is_left_exactly_as_it_was_found(self) -> None:
        """The integrity refusal is taken **before** any lapsed proposal is settled."""
        store = FakeGoalAuthorizationStore(now=SHARED_CLOCK.reset())
        await store.record(established(id="a1", expires_at=EXPIRES + timedelta(hours=2)))
        await store.record(authorization(id="p1", expires_at=AT + timedelta(minutes=30)))
        store._log._records.append(  # reaching past `record` is the point
            established(id="a2", expires_at=EXPIRES + timedelta(hours=2))
        )
        SHARED_CLOCK.set(AT + timedelta(hours=1))
        with pytest.raises(AuthorizationError):
            await store.live_for(GOAL, TOOL.id)
        held = await store.resolve("p1")
        assert held is not None
        assert held.disposition is AuthorizationDisposition.PROPOSED
