"""The canonical ``GoalQuotes`` fake and the two stores, bound to the shared suite.

ADR-0267 §5 lands a triad — the Protocol, its shared conformance suite and a canonical
fake — and this is the third artifact: without a binding class the suite collects
nothing and the fake is unverified however many files exist
(``tests/core/test_protocol_triad.py`` makes that mechanical).

**The suite is bound three times**, and the two extra bindings are the point. §11
obliges Q1 to leave a **production** provider — *"``app/`` passes the plan store where
a ``GoalQuotes`` is wanted, and a store without ``for_action`` does not satisfy the
Protocol"* — so both conforming ``PlanStore`` implementations answer the seam here, and
a divergence between the fake and either of them is a failure rather than a latent
surprise. The store bindings also carry the **fault** clause, which the fake can only
satisfy by construction: §5's *"a fault is not an absence"* is about a durable read
failing, and the durable store is where that actually happens.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from goal_quotes_contract import (
    ACTION,
    GOAL,
    HELD,
    OTHER_ACTION,
    READ_AT,
    GoalQuotesContract,
)

from ai_assistant.core.errors import AuthorizationError
from ai_assistant.core.types import (
    ActionQuoteMinting,
    Goal,
    GoalInterpretation,
    Ground,
    IntendedAction,
    IntendedActionMinting,
    MemorySource,
    Provenance,
)
from ai_assistant.planning.sqlite_store import SqlitePlanStore
from ai_assistant.planning.store import InMemoryPlanStore
from ai_assistant.testing import FakeGoalQuotes

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from ai_assistant.core.protocols import GoalQuotes, PlanStore
    from ai_assistant.core.types import ActionQuote


def _goal() -> Goal:
    """A goal holding no quote, which its two acts are then minted onto."""
    return Goal(
        id=GOAL,
        interpretation=(
            GoalInterpretation(
                revision=1,
                outcome="book a room for the trip",
                outcome_ground=Ground.USER_STATED,
                outcome_span="book a room",
                recorded_at=READ_AT,
            ),
        ),
        provenance=Provenance(
            source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=READ_AT
        ),
        created_at=READ_AT,
    )


async def _seeded[S: PlanStore](store: S, quotes: Sequence[ActionQuote]) -> S:
    """Open the goal, mint the suite's two acts, and append ``quotes`` in order.

    **Generic in the store rather than typed at the Protocol**, so the concrete type
    flows through to the fixture's ``GoalQuotes`` annotation: that assignment is the
    static half of ADR-0267 §11's *"a store without ``for_action`` does not satisfy
    the Protocol"*, and a store that stopped satisfying it would be a ``mypy`` error
    here rather than a ``TypeError`` at the composition root.
    """
    await store.save_goal(_goal())
    minted = await store.record_intended_actions(
        IntendedActionMinting(
            goal_id=GOAL,
            actions=(
                IntendedAction(id=ACTION, intent="book the room"),
                IntendedAction(id=OTHER_ACTION, intent="book the second room"),
            ),
            expected_version=0,
        )
    )
    version = minted.version
    for one in quotes:
        version = (
            await store.record_quote(
                ActionQuoteMinting(goal_id=GOAL, quote=one, expected_version=version)
            )
        ).version
    return store


class TestFakeGoalQuotesContract(GoalQuotesContract):
    """Runs :class:`~ai_assistant.testing.FakeGoalQuotes` through the shared suite."""

    @pytest.fixture
    def quotes(self) -> GoalQuotes:
        """The fake, seeded in the order the suite fixes."""
        return FakeGoalQuotes(HELD, goal=GOAL)


class TestInMemoryPlanStoreGoalQuotesContract(GoalQuotesContract):
    """Runs :class:`~ai_assistant.planning.store.InMemoryPlanStore` through the suite.

    **The annotation is half the assertion**: the fixture returns the store where a
    ``GoalQuotes`` is declared, so a store that stopped satisfying the Protocol
    structurally would be a ``mypy`` error here rather than a ``TypeError`` at the
    composition root (ADR-0267 §11).
    """

    @pytest.fixture
    async def quotes(self) -> GoalQuotes:
        """The in-memory store, holding the goal, its two acts and the suite's quotes."""
        return await _seeded(InMemoryPlanStore(), HELD)


class TestSqlitePlanStoreGoalQuotesContract(GoalQuotesContract):
    """Runs :class:`~ai_assistant.planning.sqlite_store.SqlitePlanStore` through it."""

    @pytest.fixture
    async def quotes(self, tmp_path: Path) -> GoalQuotes:
        """The durable store, holding the goal, its two acts and the suite's quotes."""
        return await _seeded(SqlitePlanStore(path=tmp_path / "plans.db"), HELD)


async def test_the_fake_detaches_a_quote_on_the_way_in_as_well_as_out() -> None:
    """§5's detachment, on the **input** side, which the shared suite cannot reach.

    The suite is handed a subject already holding its corpus, so the objects that were
    seeded are not in its hands; here they are. A caller that keeps a reference to a
    quote it seeded — or, as every binding in this module does, seeds from a **module
    constant** — could otherwise rewrite the amount afterwards and move what the seam
    answers, which would make one case's mutation leak into the next.

    Driven through both routes a quote enters by: the constructor and
    :meth:`~ai_assistant.testing.FakeGoalQuotes.hold_for`.
    """
    seeded = HELD[0]
    seam = FakeGoalQuotes([seeded], goal=GOAL)
    later = HELD[2]
    seam.hold_for(GOAL, later)

    seeded.__dict__["amount"] = Decimal("999999")
    later.__dict__["amount"] = Decimal("999999")
    try:
        answered = await seam.for_action(GOAL, ACTION)
        assert [one.amount for one in answered] == [Decimal("120"), Decimal("135")]
    finally:
        # ``HELD`` is this suite's shared corpus; leaving it rewritten would move
        # every other case's expectations.
        seeded.__dict__["amount"] = Decimal("120")
        later.__dict__["amount"] = Decimal("135")


async def test_a_fault_behind_the_fake_is_raised_and_never_an_empty_tuple() -> None:
    """§5's fault clause, over the fake: armed, it raises rather than answering empty.

    "A ``for_action`` that cannot answer raises ``AuthorizationError`` and **no
    implementation converts it into an empty tuple**" — and the two answers are
    different facts about what the user authorised: empty means the goal holds no
    quote, which leaves the act asking, while a fault means the policy could not find
    out, which takes ADR-0254 §6's bar and leaves **no standing route** at all.
    """
    seam = FakeGoalQuotes(HELD, goal=GOAL)
    assert await seam.for_action(GOAL, ACTION) != ()

    seam.fail_for_action()

    with pytest.raises(AuthorizationError):
        await seam.for_action(GOAL, ACTION)


async def test_a_durable_read_that_cannot_be_taken_raises_rather_than_answering_empty(
    tmp_path: Path,
) -> None:
    """§5's fault clause **against the production store**, which is arm 6's own limb.

    "The fault limb is driven against the production store as well as a configured
    fake, because a fake that raises satisfies the limb by construction while the
    durable store is where the failure comes from": ``planning``'s own ``GoalQuotes``
    implementation, over a data directory its read cannot use, raises
    ``AuthorizationError`` — **not** a driver exception, **not** an ``OSError``, and
    **not** an empty tuple.

    The control is the same store answering **empty** for an act it holds no quote
    for, which is uncovered for the other reason.
    """
    store = SqlitePlanStore(path=tmp_path / "plans.db")
    await _seeded(store, HELD)
    assert await store.for_action(GOAL, "ia-none") == (), "the control: an absence"

    store.close()

    with pytest.raises(AuthorizationError):
        await store.for_action(GOAL, ACTION)
