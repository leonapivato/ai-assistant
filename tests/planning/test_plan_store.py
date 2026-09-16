"""InMemoryPlanStore passes the shared PlanStore conformance suite."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from plan_store_contract import PlanStoreContract

from ai_assistant.core.types import StepStatus, StepTransition
from ai_assistant.planning import InMemoryPlanStore
from ai_assistant.planning.execution import PlanExecution

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    from ai_assistant.core.protocols import PlanStore
    from ai_assistant.core.types import GoalAttempt


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

    async def seed_a_second_owner(self, store: PlanStore, attempt: GoalAttempt) -> None:
        """Write the row into the dict, beneath ADR-0255 §3's refusal on both members.

        A store written before that decision could hold it; ``open_attempt`` cannot
        produce it any more, which is the whole of what the arm is about.
        """
        assert isinstance(store, InMemoryPlanStore)
        # A pre-decision row, by construction: the public members refuse it now.
        store._attempts[attempt.id] = attempt

    def store_on(self, now: Callable[[], datetime]) -> AbstractContextManager[PlanStore]:
        """A fresh subject on ``now``; nothing to dispose of, so a null context."""
        return contextlib.nullcontext(InMemoryPlanStore(now=now))


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


async def test_a_satisfaction_stamps_the_stores_clock_and_not_the_trackers() -> None:
    """ADR-0259 §9: the **store** stamps ``finished_at``, whatever the tracker reads.

    This store takes its transition tracker by injection, so the two clocks are
    independently settable — which is the wiring that makes §9's "from its own injected
    clock" a claim with a way to be false. Decided here rather than in the shared suite:
    the ``tracker`` keyword is this class's own affordance, and a contract arm could only
    assert the two agree where the default wiring already makes them one value.
    """
    from plan_store_contract import _KEY, PlanStoreContract  # noqa: PLC0415 — the suite's helpers

    store_at = datetime(2026, 6, 1, tzinfo=UTC)
    tracker_at = datetime(2030, 1, 1, tzinfo=UTC)
    store = InMemoryPlanStore(now=lambda: store_at, tracker=PlanExecution(now=lambda: tracker_at))
    suite = PlanStoreContract()

    holder = await suite._acting(store)
    await store.claim_effect(execution_id=holder.id, step_id="s1", effect_key=_KEY)
    holder = await suite._to_status(store, holder, StepStatus.SUCCEEDED)
    later = await suite._acting(store, plan_id="p2", attempt_id="a2")
    await store.claim_effect(execution_id=later.id, step_id="s1", effect_key=_KEY)

    committed = await store.commit_transition(
        StepTransition(
            execution_id=later.id,
            step_id="s1",
            to_status=StepStatus.SUCCEEDED,
            expected_version=later.version,
            satisfied_by_execution=holder.id,
            satisfied_by_step="s1",
            satisfied_by_key=_KEY,
        )
    )

    step = committed.step("s1")
    assert step is not None
    assert step.finished_at == store_at, "the satisfaction's instant is the store's"
    assert step.finished_at != tracker_at
