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

#: A vocabulary to drive the contract over — two plausible advertised names.
#:
#: The contents decide nothing, and that is the point: ADR-0211 §9 item 2 forbids
#: this suite asserting *which* envelope an implementation returns for a goal, so
#: nothing below reads these names back. What is pinned is that a conforming
#: planner **accepts** the input the contract now requires.
_VOCABULARY = ("report_current_time", "send_email")


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
        plan = await planner.plan(_goal(), context=_context(), capabilities=_VOCABULARY)
        assert plan.goal_id == "g1"

    async def test_step_ids_are_unique(self, planner: Planner) -> None:
        plan = await planner.plan(_goal(), context=_context(), capabilities=_VOCABULARY)
        ids = [step.id for step in plan.steps]
        assert len(ids) == len(set(ids))

    async def test_the_returned_plan_is_frozen(self, planner: Planner) -> None:
        """The plan is an audit record, so it must not be editable after the fact."""
        plan = await planner.plan(_goal(), context=_context(), capabilities=_VOCABULARY)
        with pytest.raises((ValidationError, AttributeError, TypeError)):
            plan.goal_id = "tampered"

    async def test_accepts_the_memories_the_pipeline_assembled(self, planner: Planner) -> None:
        """Memory is passed in, not fetched — it is what makes a plan personal.

        ``memories`` is **what the pipeline assembled for this turn**, which
        ADR-0074 §5 widened from "records retrieved as relevant, best first": the
        conversation's recent turns come first, in order, then the
        relevance-retrieved records, then — since ADR-0158 §5 — the episodic
        supplement. The signature did not change, so no triad is owed — but this
        suite's expectation moves with the wording, which is the review concern
        ``CONTRIBUTING.md`` names when a Protocol's meaning changes without its
        shape. What a conforming planner may **not** do is read a single relevance
        order across the sequence: for a user who changes the subject
        mid-conversation, the tail is not the most relevant thing the store holds,
        and the retrieved group is composed under the assembling consumer's
        precedence (ADR-0072 §5, ADR-0113 §6), relevance ordering the records only
        within one precedence band.
        """
        plan = await planner.plan(
            _goal(), context=_context(), memories=(), capabilities=_VOCABULARY
        )
        assert plan.goal_id == "g1"

    async def test_accepts_the_advertised_vocabulary(self, planner: Planner) -> None:
        """The vocabulary is pushed in, and a conforming planner takes it.

        ADR-0211 §1 makes ``capabilities`` a required, keyword-only input carrying
        what ``ToolRegistry.capabilities()`` answered for this turn — an open string
        vocabulary of which the registry is the authority (ADR-0016 §5). A planner
        neither re-derives it, nor fetches it, nor holds a registry, for the reason
        ADR-0014 §6 pushes ``context`` and ``memories`` in rather than letting a
        planner reach for them.

        **What is asserted is acceptance, and deliberately nothing more.** ADR-0211
        §9 item 2 forbids this suite asserting which envelope a given implementation
        returns for a given goal: the fake's plan is scripted and a model's is not,
        so an assertion that a vocabulary of two produces a plan would pass on one
        conforming implementation and fail on another. The behavioural question — is
        the goal one this vocabulary can carry? — is a model's judgement, which
        ADR-0211 §6's third clause declines to guarantee of any planner.
        """
        plan = await planner.plan(_goal(), context=_context(), capabilities=_VOCABULARY)
        assert plan.goal_id == "g1"

    async def test_an_empty_vocabulary_raises_nothing(self, planner: Planner) -> None:
        """The empty vocabulary is a legal input, never an error (ADR-0211 §6).

        A deployment with no builtin and no integration reaches it, and every fake
        and every case here exercises it, which is why it is ruled rather than left
        to an implementation's judgement. A conforming planner raises nothing,
        refuses nothing and enters no repair round on account of it: what an empty
        vocabulary means is that no step can be carried, so a decline is the only
        shape available — and *that* is an obligation on what the planner asks for,
        not a guarantee about what comes back, so it is not asserted here.
        """
        plan = await planner.plan(_goal(), context=_context(), capabilities=())
        assert plan.goal_id == "g1"

    async def test_the_vocabulary_need_not_be_a_tuple(self, planner: Planner) -> None:
        """``Sequence[str]`` is the contract, and a list satisfies it.

        ``ToolRegistry.capabilities()`` answers a tuple today, so an implementation
        could pass its whole test suite while quietly requiring one — indexing is
        common to both, and so is iteration, but ``isinstance(value, tuple)`` and
        equality against a tuple literal are not. A caller assembling the vocabulary
        by other means, or a fake handing over a list, would then fail against a
        planner that looked conforming. Pinned here rather than left to a reviewer's
        eye, because the divergence is invisible until the first caller hits it.
        """
        plan = await planner.plan(_goal(), context=_context(), capabilities=list(_VOCABULARY))
        assert plan.goal_id == "g1"
