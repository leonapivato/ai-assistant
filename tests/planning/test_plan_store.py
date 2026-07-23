"""InMemoryPlanStore passes the shared PlanStore conformance suite."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from plan_store_contract import PlanStoreContract

from ai_assistant.planning import InMemoryPlanStore

if TYPE_CHECKING:
    from ai_assistant.core.protocols import PlanStore


def _fixed_now() -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC)


class TestInMemoryPlanStoreContract(PlanStoreContract):
    """Runs InMemoryPlanStore through the shared PlanStore conformance suite."""

    @pytest.fixture
    def store(self) -> PlanStore:
        return InMemoryPlanStore(now=_fixed_now)


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
