"""The canonical planning fake passes the shared conformance suite.

This is what lets other subsystems trust ``ai_assistant.testing.FakePlanStore``
as a stand-in: it is held to the same contract as the real implementations. It
matters more here than elsewhere, because ``FakePlanStore`` re-implements the stop
record and acting's effect records independently (it cannot import the subsystem it
stands in for) — this suite is what stops the two copies drifting apart.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from plan_store_contract import PlanRemoval, PlanStoreContract

from ai_assistant.core.types import SightMode
from ai_assistant.testing import FakePlanStore
from ai_assistant.testing.cancellation import SuspendedMidWrite
from sight_equivalence import SIGHTS

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from ai_assistant.core.protocols import PlanStore


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
            arm=lambda _operation: store.suspend_next_operation(),
        )

    @pytest.fixture
    def sight_store_factory(self) -> Callable[[SightMode], PlanStore]:
        return lambda mode: FakePlanStore(now=_fixed_now, sight_mode=mode)

    @pytest.fixture
    def remove_records(self) -> Callable[[PlanStore, PlanRemoval], None]:
        """Pop the records from the fake's own containers; the issuer is untouched."""

        def remove(store: PlanStore, removal: PlanRemoval) -> None:
            assert isinstance(store, FakePlanStore)
            for one in removal.effects:
                del store._activation_effects[one]
            for one in removal.observations:
                del store._observations[one]
            for one in removal.tasks:
                del store._tasks[one]
            for one in removal.requests:
                del store._requests[one]
            store._stopped.clear()

        return remove


class _CountingStops(FakePlanStore):
    """A stand-in of the kind ``tests/orchestration`` builds: one override, by subclassing."""

    def __init__(self) -> None:
        super().__init__(now=_fixed_now, sight_mode=SightMode.WITHHOLD)
        self.stops: list[str] = []

    async def record_stop(self, activation_id: str, /) -> None:
        self.stops.append(activation_id)
        await super().record_stop(activation_id)


async def test_a_binding_of_a_stand_in_runs_its_overrides() -> None:
    """ADR-0383 §7:1: a binding is the stand-in's own class, sharing its state.

    The override runs on the binding, and what it keeps in a mutable container is shared
    with the store it was bound from; an attribute the override would rebind is not, so a
    stand-in that wants its binding's calls seen keeps them in a container.
    """
    store = _CountingStops()
    bound = store.bound(SIGHTS["run-over-the-owners-domain"])
    assert isinstance(bound, _CountingStops)
    await bound.record_stop("act-1")
    assert store.stops == ["act-1"]
    assert await store.stopped_activations(["act-1"]) == ("act-1",)
    assert await bound.stopped_activations(["act-1"]) == ()
