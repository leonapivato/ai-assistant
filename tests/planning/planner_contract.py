"""Shared conformance suite for the Planner Protocol (ADR-0014).

Every ``Planner`` implementation must pass this suite (CONTRIBUTING, "Protocol
conformance suites"). A concrete test subclasses :class:`PlannerContract` and
overrides the ``planner`` fixture.

The contract is deliberately thin: *what* a planner decides is its own business
and cannot be asserted generically. What every planner owes its caller is a plan
that belongs to the goal it was asked about and is safe to treat as an audit
record — which is what this pins down.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    CurrentContext,
    Goal,
    MemorySource,
    Provenance,
    TimeOfDay,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import Planner

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


def _goal(goal_id: str = "g1") -> Goal:
    return Goal(
        id=goal_id,
        statement="relocate to Lisbon",
        provenance=Provenance(
            source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_WHEN
        ),
        created_at=_WHEN,
    )


def _context() -> CurrentContext:
    return CurrentContext(
        now=_WHEN,
        time_of_day=TimeOfDay.MORNING,
        is_weekend=False,
        within_working_hours=True,
    )


class PlannerContract:
    """Behaviour every ``Planner`` implementation must exhibit."""

    @pytest.fixture
    def planner(self) -> Planner:
        """Return the planner under test."""
        raise NotImplementedError

    async def test_plans_for_the_goal_it_was_given(self, planner: Planner) -> None:
        """A plan that does not name its goal cannot be resumed or audited."""
        plan = await planner.plan(_goal(), context=_context())
        assert plan.goal_id == "g1"

    async def test_step_ids_are_unique(self, planner: Planner) -> None:
        plan = await planner.plan(_goal(), context=_context())
        ids = [step.id for step in plan.steps]
        assert len(ids) == len(set(ids))

    async def test_the_returned_plan_is_frozen(self, planner: Planner) -> None:
        """The plan is an audit record, so it must not be editable after the fact."""
        plan = await planner.plan(_goal(), context=_context())
        with pytest.raises((ValidationError, AttributeError, TypeError)):
            plan.goal_id = "tampered"

    async def test_accepts_retrieved_memories(self, planner: Planner) -> None:
        """Memory is passed in, not fetched — it is what makes a plan personal."""
        plan = await planner.plan(_goal(), context=_context(), memories=())
        assert plan.goal_id == "g1"
