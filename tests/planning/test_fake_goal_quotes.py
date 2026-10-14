"""The canonical ``GoalQuotes`` fake, bound to the shared suite.

ADR-0267 §5 lands a triad — the Protocol, its shared conformance suite and a canonical
fake — and this is the third artifact: without a binding class the suite collects
nothing and the fake is unverified however many files exist
(``tests/core/test_protocol_triad.py`` makes that mechanical).

**The suite is bound once, to the fake.** The two plan stores no longer answer the
seam: ADR-0309 §5 retires ``PlanStore``'s quote members, so neither production store
holds a quote to answer ``for_action`` with, and their bindings left with them. The
Protocol and its fake stay until the lane that retires ``GoalQuotes`` itself.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from goal_quotes_contract import (
    ACTION,
    GOAL,
    HELD,
    GoalQuotesContract,
)

from ai_assistant.core.errors import AuthorizationError
from ai_assistant.testing import FakeGoalQuotes

if TYPE_CHECKING:
    from ai_assistant.core.protocols import GoalQuotes


class TestFakeGoalQuotesContract(GoalQuotesContract):
    """Runs :class:`~ai_assistant.testing.FakeGoalQuotes` through the shared suite."""

    @pytest.fixture
    def quotes(self) -> GoalQuotes:
        """The fake, seeded in the order the suite fixes."""
        return FakeGoalQuotes(HELD, goal=GOAL)


async def test_the_fake_detaches_a_quote_on_the_way_in_as_well_as_out() -> None:
    """§5's detachment, on the **input** side, which the shared suite cannot reach.

    The suite is handed a subject already holding its corpus, so the objects that were
    seeded are not in its hands; here they are. A caller that keeps a reference to a
    quote it seeded — or, as the binding in this module does, seeds from a **module
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
