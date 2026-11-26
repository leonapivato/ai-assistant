"""InMemoryPlanStore passes the shared PlanStore conformance suite."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from plan_store_contract import PlanRemoval, PlanStoreContract

from ai_assistant.planning import InMemoryPlanStore

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.protocols import PlanStore
    from ai_assistant.core.types import SightMode


def _fixed_now() -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC)


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

    @pytest.fixture
    def sight_store_factory(self) -> Callable[[SightMode], PlanStore]:
        return lambda mode: InMemoryPlanStore(now=_fixed_now, sight_mode=mode)

    @pytest.fixture
    def remove_records(self) -> Callable[[PlanStore, PlanRemoval], None]:
        """Pop the records from the store's own containers; the issuer is untouched."""

        def remove(store: PlanStore, removal: PlanRemoval) -> None:
            assert isinstance(store, InMemoryPlanStore)
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
