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
from plan_store_contract import PlanStoreContract

from ai_assistant.testing import FakePlanStore
from ai_assistant.testing.cancellation import SuspendedMidWrite

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

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
