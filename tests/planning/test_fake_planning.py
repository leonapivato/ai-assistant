"""The canonical planning fakes pass the shared conformance suites.

This is what lets other subsystems trust ``ai_assistant.testing.FakePlanStore``
and ``FakePlanner`` as stand-ins: they are held to the same contracts as the
real implementations. It matters more here than elsewhere, because
``FakePlanStore`` re-implements the ADR-0014 §4 transition graph independently
(it cannot import the subsystem it stands in for) — this suite is what stops the
two copies drifting apart.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from plan_store_contract import PlanStoreContract
from planner_contract import PlannerContract

from ai_assistant.core.types import (
    CurrentContext,
    Goal,
    MemorySource,
    Provenance,
    TimeOfDay,
)
from ai_assistant.testing import FakePlanner, FakePlanStore
from ai_assistant.testing.cancellation import SuspendedMidWrite

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ai_assistant.core.protocols import Planner, PlanStore


def _fixed_now() -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC)


class TestFakePlanStoreContract(PlanStoreContract):
    """Runs FakePlanStore through the shared PlanStore conformance suite."""

    @pytest.fixture
    def store(self) -> PlanStore:
        return FakePlanStore(now=_fixed_now)

    @contextlib.asynccontextmanager
    async def store_suspended_mid_write(
        self,
    ) -> AsyncIterator[SuspendedMidWrite[PlanStore]]:
        """The fake models the resource it does not really own (ADR-0060 §3).

        Dicts need no serialising, so without this the canonical fake could only
        opt out — and the cancellation case would run solely against the
        ``sqlite3`` store that already holds the invariant. Every write passes
        through the *one* modelled resource, so ``arm`` ignores which operation it
        is handed: the parametrised cases (#370) exercise the same ``held()`` path
        on the fake and earn their keep on the ``sqlite3`` store, where each
        operation is a separate lock site. Nothing to dispose of, hence the bare
        yield.
        """
        store = FakePlanStore(now=_fixed_now)
        yield SuspendedMidWrite(
            store=store,
            log=store.resource_log,
            arm=lambda _operation: store.suspend_next_write(),
        )


class TestFakePlannerContract(PlannerContract):
    """Runs FakePlanner through the shared Planner conformance suite."""

    @pytest.fixture
    def planner(self) -> Planner:
        return FakePlanner(now=_fixed_now)


async def test_a_fresh_fake_does_not_reuse_a_prior_instances_execution_id() -> None:
    """The fake matches ``InMemoryPlanStore``'s cross-restart non-reuse (#280).

    A new instance rewinds the sequence to 0, so without the per-instance
    incarnation nonce it would re-mint a prior instance's id. The fake must keep
    this or it would certify a store that reuses ids across restarts — the exact
    hazard ADR-0044 §1 forbids. Impl-level, like the real store's twin, because
    "restart" for an in-memory double is a new instance.
    """
    from plan_store_contract import _goal, _plan  # noqa: PLC0415

    async def start(store: FakePlanStore) -> str:
        await store.save_goal(_goal())
        await store.save_plan(_plan())
        return (await store.start_execution("p1")).id

    first_id = await start(FakePlanStore(now=_fixed_now))
    second_id = await start(FakePlanStore(now=_fixed_now))
    assert first_id != second_id


async def test_fake_planner_records_what_it_was_asked() -> None:
    """Beyond the contract: the fake exists to let callers assert on the call."""
    planner = FakePlanner(now=_fixed_now)
    goal = Goal(
        id="g1",
        statement="ship it",
        provenance=Provenance(
            source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_fixed_now()
        ),
        created_at=_fixed_now(),
    )
    context = CurrentContext(
        now=_fixed_now(),
        time_of_day=TimeOfDay.MORNING,
        is_weekend=False,
        within_working_hours=True,
    )

    await planner.plan(goal, context=context)

    assert len(planner.calls) == 1
    assert planner.calls[0][0].id == "g1"
