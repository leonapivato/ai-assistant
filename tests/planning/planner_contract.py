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
    MAX_HOP_LABELS,
    CurrentContext,
    EpisodicMemory,
    Goal,
    MemorySource,
    Provenance,
    ReadKind,
    ReadRequest,
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


def _supply() -> tuple[EpisodicMemory, ...]:
    """A two-record supply, so a call has positions for ADR-0226 §3 to label.

    Episodes rather than beliefs so that the sequence is the shape ADR-0074 §5 puts
    first — a conversation tail — and every planner renders it the same way. What
    it holds decides nothing here: the suite never asserts what a planner asks
    about it, only what the shape of an ask may be.
    """
    return tuple(
        EpisodicMemory(
            id=f"e{ordinal}",
            content=f"Ada: turn {ordinal}.",
            occurred_at=_WHEN,
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=_WHEN),
        )
        for ordinal in (1, 2)
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

    # --- ADR-0226 §4: the widened return -----------------------------------
    # `Planner.plan` may now answer a plan carrying a `read_request`. §10 obliges
    # this suite to cover that widening, "so that every `Planner` implementation is
    # held to it — the model-backed planner and the canonical fake alike".

    @pytest.fixture
    def asking_planner(self) -> Planner | None:
        """The same implementation, arranged to emit a read request — or ``None``.

        **Optional by construction, because ADR-0226 §4 makes the field additive
        and defaulted.** A ``Planner`` that knows nothing of the envelope conforms
        and returns no request on any turn, so a suite that *required* every
        implementation to produce one would refuse a conforming planner. A subclass
        that can arrange an emission overrides this and the arms below bind on it;
        one that cannot leaves it, and they skip.

        Returns:
            A planner of the implementation under test that asks for a read, or
            ``None`` where the implementation never asks.
        """
        return None

    async def test_the_plan_says_whether_a_read_was_asked_for(self, planner: Planner) -> None:
        """The widened return, at its weakest and most total form (ADR-0226 §4).

        Whatever a planner decides, ``read_request`` is either ``None`` — "the
        planner asked for no read", which §4 makes the semantically correct answer
        and never an error — or a validated
        :class:`~ai_assistant.core.types.ReadRequest`. *Which* of the two is a
        judgement this suite may not assert, for ADR-0211 §9 item 2's reason: a
        scripted plan and a model's plan would answer differently for one goal and
        both would conform.
        """
        plan = await planner.plan(
            _goal(), context=_context(), memories=_supply(), capabilities=_VOCABULARY
        )
        assert plan.read_request is None or isinstance(plan.read_request, ReadRequest)

    async def test_a_request_it_returns_is_one_this_contract_admits(
        self, asking_planner: Planner | None
    ) -> None:
        """An emitted request is a *validated* model, arm by arm (ADR-0226 §§1-2, §6).

        Every condition here is one ``ReadRequest`` and ``ReadAsk`` enforce, which
        is the point: a planner can bypass them — ``model_construct`` skips
        validation, and an implementation assembling a request by hand could ship a
        two-ask ``SIGHTED_QUERY`` request or a three-label hop that no ``core`` test
        would ever see. Re-asserted here over what a planner actually returned, the
        conditions bind on the emission rather than only on the type.
        """
        if asking_planner is None:
            pytest.skip("this implementation never asks for a read (ADR-0226 §4)")
        plan = await asking_planner.plan(
            _goal(), context=_context(), memories=_supply(), capabilities=_VOCABULARY
        )
        request = plan.read_request
        assert request is not None, "the fixture promises an implementation that asks"

        kinds = [ask.kind for ask in request.asks]
        assert kinds, "a request carries at least one ask"
        assert len(set(kinds)) == len(kinds), "at most one ask of each kind"
        for ask in request.asks:
            assert ask.kind in set(ReadKind)
            if ask.kind is ReadKind.SIGHTED_QUERY:
                assert ask.query is not None
                assert ask.query.strip()
                assert ask.labels == ()
            else:
                assert ask.query is None
                assert 1 <= len(ask.labels) <= MAX_HOP_LABELS

    async def test_a_request_it_returns_cannot_be_edited(
        self, asking_planner: Planner | None
    ) -> None:
        """ADR-0226 §11 item 15's first arm: a plan carrying a request is still frozen.

        The plan is an audit record (ADR-0014 §2) and the request is now part of
        what it records, so the freeze has to reach all the way down — the field on
        the plan, the request, and each ask. A frozen plan holding a mutable request
        would let a later stage rewrite what the planner asked for, after the
        decision it is a record of.
        """
        if asking_planner is None:
            pytest.skip("this implementation never asks for a read (ADR-0226 §4)")
        plan = await asking_planner.plan(
            _goal(), context=_context(), memories=_supply(), capabilities=_VOCABULARY
        )
        request = plan.read_request
        assert request is not None

        frozen = (ValidationError, AttributeError, TypeError)
        with pytest.raises(frozen):
            plan.read_request = None
        with pytest.raises(frozen):
            request.asks = ()
        with pytest.raises(frozen):
            request.asks[0].kind = ReadKind.SIGHTED_QUERY

    async def test_a_read_it_asks_for_never_becomes_a_step(
        self, asking_planner: Planner | None
    ) -> None:
        """ADR-0226 §11 item 15's second arm, at the seam that emits it (§4).

        "A ``ReadAsk`` is **not** a ``PlanStep``, and nothing drives it": reading
        the owner's own store is not an act in the world, so no ask is selected
        against the vocabulary, resolved to a tool, ruled on by the permission gate,
        or reaches an executor. At *this* seam that means one thing — an emitted ask
        appears in ``read_request`` and never in ``steps``, whatever it says. The
        turn-level half, that no registry, gate or executor sees one, is the loop's
        and is asserted there.
        """
        if asking_planner is None:
            pytest.skip("this implementation never asks for a read (ADR-0226 §4)")
        plan = await asking_planner.plan(
            _goal(), context=_context(), memories=_supply(), capabilities=_VOCABULARY
        )
        request = plan.read_request
        assert request is not None

        asked = {ask.query for ask in request.asks if ask.query is not None}
        asked |= {label for ask in request.asks for label in ask.labels}
        for step in plan.steps:
            assert step.capability not in asked
            assert step.intent not in asked
