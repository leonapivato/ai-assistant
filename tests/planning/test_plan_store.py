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

    #: Every method mutates dicts and returns without awaiting anything, so no
    #: ``CancelledError`` can arrive while the store holds something — there is no
    #: connection, lock or worker for ADR-0060's clause to bite on. Declared here
    #: rather than left to a silent skip: if this store ever grows a resource, the
    #: line has to be deleted deliberately.
    acquires_no_shared_resource = True

    @pytest.fixture
    def store(self) -> PlanStore:
        return InMemoryPlanStore(now=_fixed_now)
