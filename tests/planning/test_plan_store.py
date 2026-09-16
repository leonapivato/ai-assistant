"""InMemoryPlanStore passes the shared PlanStore conformance suite."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from plan_store_contract import InjectedFaultError, PlanStoreContract

from ai_assistant.planning import InMemoryPlanStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ai_assistant.core.protocols import PlanStore
    from ai_assistant.core.types import GoalAttempt, UtcInstant


def _fixed_now() -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC)


class _FailsMidAbandonment(InMemoryPlanStore):
    """This store with ADR-0261 §14 arm 6's fault in its own per-attempt seam.

    The second ending the act computes raises, which on a goal holding two live
    attempts is part-way through the set. The seam is a method of the store, so the
    dicts beneath it are untouched and the fault lands exactly where the act does its
    fallible per-attempt work.
    """

    _endings = 0

    def _cancelled_attempt(self, attempt: GoalAttempt, /, *, at: UtcInstant) -> GoalAttempt:
        """Raise on the second ending, once, then behave (ADR-0261 §14 arm 6)."""
        self._endings += 1
        if self._endings == 2:
            raise InjectedFaultError("the second attempt's ending")
        return super()._cancelled_attempt(attempt, at=at)


class TestInMemoryPlanStoreContract(PlanStoreContract):
    """Runs InMemoryPlanStore through the shared PlanStore conformance suite."""

    #: Every method mutates dicts and returns without awaiting anything, so no
    #: ``CancelledError`` can arrive while the store holds something — there is no
    #: connection, lock or worker for ADR-0060's clause to bite on. Declared here
    #: rather than left to a silent skip: if this store ever grows a resource, the
    #: line has to be deleted deliberately.
    acquires_no_shared_resource = True

    @pytest.fixture
    def store(self) -> PlanStore:
        return InMemoryPlanStore(now=_fixed_now)

    async def seed_a_second_owner(self, store: PlanStore, attempt: GoalAttempt) -> None:
        """Write the row into the dict, beneath ADR-0255 §3's refusal on both members.

        A store written before that decision could hold it; ``open_attempt`` cannot
        produce it any more, which is the whole of what the arm is about.
        """
        assert isinstance(store, InMemoryPlanStore)
        # A pre-decision row, by construction: the public members refuse it now.
        store._attempts[attempt.id] = attempt

    @contextlib.asynccontextmanager
    async def store_failing_mid_abandonment(self) -> AsyncIterator[PlanStore]:
        """A subclass carrying the fault; nothing to dispose of, hence the bare yield."""
        yield _FailsMidAbandonment(now=_fixed_now)


async def _seed_and_start(store: InMemoryPlanStore) -> str:
    """Save a goal+plan and start one execution, returning its id."""
    from plan_store_contract import _goal, _plan  # noqa: PLC0415

    await store.save_goal(_goal())
    await store.save_plan(_plan())
    return (await store.start_execution("p1")).id


async def test_a_fresh_store_does_not_reuse_a_prior_instances_execution_id() -> None:
    """A restart must not re-mint a prior incarnation's execution id (#280).

    ``InMemoryPlanStore`` is non-persistent, so every process start is a fresh
    instance whose sequence rewinds to 0. Kept in this impl-level file, not the
    shared suite, because "restart" is persistence-model-specific: for an
    in-memory store it is a new instance; a persistent store would reopen the
    same backing file. The per-instance incarnation nonce is what makes the id
    unique across restarts, so a persistent audit trail's stale ``CONFIRM`` bound
    to the old id (ADR-0044 §3) cannot recover onto the new execution.
    """
    first_id = await _seed_and_start(InMemoryPlanStore(now=_fixed_now))
    second_id = await _seed_and_start(InMemoryPlanStore(now=_fixed_now))
    assert first_id != second_id
