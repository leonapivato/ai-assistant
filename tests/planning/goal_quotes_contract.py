"""Shared conformance suite for the ``GoalQuotes`` Protocol (ADR-0267 §5).

Every :class:`~ai_assistant.core.protocols.GoalQuotes` implementation must pass
:class:`GoalQuotesContract`. A concrete test subclasses it and supplies
:meth:`GoalQuotesContract.holding`, which returns a seam holding the quotes it is
given, **in that order**, for :data:`GOAL`.

**Here rather than under ``tests/core/``.** The corpus puts a suite beside the
subsystem that implements it, and ADR-0267 §11 puts the implementation in
``planning`` — the quotes live inside the ``Goal``, so ``planning``'s store answers
the seam and ``app/`` passes the concrete. The Protocol itself stays in ``core``,
which is what lets ``permissions`` hold the narrow face by injection without
importing ``planning``.

**What the suite is about is the answer and never the selection.** §5 makes the seam
*"keyed and never asked"*: it filters by the goal and the act and evaluates **no**
predicate — it does not select the governing quote, compare a digest, compare an
amount or read a ``CoverageMember``. So every case here is about **what comes back
and in what order**; which member of it governs is ``permissions``' and is
``tests/permissions/test_quote_coverage.py``'s, because *"a store that selected would
be a second place the governing rule lives"*.

**What is deliberately not in here.** The **fault** clause — *"a fault is not an
absence"* — is asserted of each implementation in its own module rather than here: a
fake satisfies it by construction, and what the clause is actually about is the
durable store, over a data directory its read cannot use. ``MAX_ACTION_QUOTES``, the
elision and the compare-and-swap are ``PlanStore``'s, not this seam's, and are in
``tests/planning/plan_store_contract.py``.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.types import ActionQuote, StepOutputRef

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import GoalQuotes

#: The goal every seeded quote of this suite belongs to.
GOAL = "g1"

#: The two acts the suite keys on. **Two rather than one**, because the whole of what
#: the seam does is filter: a suite holding quotes for one act could not tell a
#: conforming filter from a member that returned everything it held.
ACTION = "ia1"
OTHER_ACTION = "ia2"

#: A well-formed arguments digest. The seam compares it against **nothing** (§5), so
#: what matters here is only that a quote is constructible.
DIGEST = "a" * 64

#: When a scripted quote was read. Fixed, and **no case orders by it** (§1): the order
#: this seam answers in is the goal's own tuple order.
READ_AT = datetime(2026, 1, 2, tzinfo=UTC)


def quote(*, action: str = ACTION, amount: str = "120", currency: str = "EUR") -> ActionQuote:
    """One quote for ``action``, at the shape ADR-0267 §1 declares."""
    return ActionQuote(
        intended_action=action,
        arguments_digest=DIGEST,
        amount=Decimal(amount),
        currency=currency,
        plan="p1",
        read_from=StepOutputRef(step="s1", field="price"),
        read_at=READ_AT,
    )


class GoalQuotesContract:
    """``GoalQuotes.for_action``'s clauses (ADR-0267 §5)."""

    async def holding(self, quotes: Sequence[ActionQuote]) -> GoalQuotes:
        """A seam holding ``quotes`` for :data:`GOAL`, **in the order given**.

        Args:
            quotes: The quotes, oldest first — the order ADR-0267 §2 makes the total
                order the governing-quote rule reads.

        Returns:
            The subject under test, at its narrow face.

        Raises:
            NotImplementedError: If a subclass has not supplied one.
        """
        raise NotImplementedError

    async def test_for_action_answers_that_actions_quotes_in_the_goals_own_order(
        self,
    ) -> None:
        """§5: "returning that goal's quotes naming that action **in the order the goal
        holds them**".

        The filter is the two identifiers and nothing else: a quote for another act is
        left out, and nothing is reordered, de-duplicated or collapsed to the last —
        the caller takes the last member, and a seam that returned only it would be
        the second implementation of ADR-0266 §7's governing rule.
        """
        seam = await self.holding(
            [
                quote(amount="120"),
                quote(action=OTHER_ACTION, amount="80"),
                quote(amount="135"),
            ]
        )

        assert [one.amount for one in await seam.for_action(GOAL, ACTION)] == [
            Decimal("120"),
            Decimal("135"),
        ]
        assert [one.amount for one in await seam.for_action(GOAL, OTHER_ACTION)] == [Decimal("80")]

    async def test_for_action_answers_empty_for_an_action_the_goal_has_no_quote_for(
        self,
    ) -> None:
        """§5: "possibly empty", and an empty tuple means exactly that.

        ADR-0266 §7 then leaves the member unmet, the request uncovered and the act
        **asked about** — which is the fail-closed direction, and is a different fact
        from the fault the seam raises on.
        """
        seam = await self.holding([quote()])

        assert await seam.for_action(GOAL, "ia-none") == ()

    async def test_for_action_answers_empty_for_a_goal_the_subject_does_not_hold(
        self,
    ) -> None:
        """§5: a goal with no quotes is an absence and never a fault.

        A goal a store has never seen holds no quote for any act, which is the same
        answer ADR-0266 §7 reads as *"no quote governs"* — the act asks.
        """
        seam = await self.holding([quote()])

        assert await seam.for_action("g-none", ACTION) == ()

    async def test_for_action_answers_every_quote_of_that_action_and_not_the_last(
        self,
    ) -> None:
        """§5: "``permissions`` takes the last member of what comes back".

        So the seam returns **all** of them, including two readings that are equal:
        ADR-0267 §2 makes a refresh a position in the tuple rather than a predicate,
        and a seam that de-duplicated would be evaluating one.
        """
        seam = await self.holding([quote(amount="120"), quote(amount="120")])

        answered = await seam.for_action(GOAL, ACTION)
        assert len(answered) == 2
        assert answered[0] == answered[1]

    async def test_for_action_reads_no_clock_and_refuses_no_quote_for_its_age(
        self,
    ) -> None:
        """§6: "nothing in this decision expires a quote", and this seam least of all.

        A quote governs until a later one for the same action displaces it, however
        long ago it was read — *"no lane refuses a quote for being old, computes a
        validity window from ``read_at``, compares ``read_at`` to the instant of
        dispatch, or adds an expiry field"*. Driven with a ``read_at`` far in the past
        and one far in the future, because a seam applying a window in **either**
        direction would drop one of them.
        """
        old = quote().model_copy(update={"read_at": datetime(2001, 1, 1, tzinfo=UTC)})
        ahead = quote().model_copy(update={"read_at": datetime(2099, 1, 1, tzinfo=UTC)})
        seam = await self.holding([old, ahead])

        assert await seam.for_action(GOAL, ACTION) == (old, ahead)

    async def test_for_action_is_a_read_and_leaves_the_subject_where_it_found_it(
        self,
    ) -> None:
        """§5: the seam answers, and **no lane appends through it**.

        Two calls answer the same tuple: a member that recorded, cached a selection or
        advanced a version would show here, and a policy holding this face has no
        ``record_quote`` to reach for.
        """
        seam = await self.holding([quote(amount="120"), quote(amount="135")])

        first = await seam.for_action(GOAL, ACTION)
        assert await seam.for_action(GOAL, ACTION) == first

    @pytest.mark.parametrize("act", ["ia1 ", " ia1", "IA1", "ia11"])
    async def test_the_key_is_compared_whole_and_never_by_prefix_or_fold(self, act: str) -> None:
        """§5: the filter is equality of the identifier and nothing looser.

        No case folding, no trimming, no prefix match. A looser key would answer a
        quote read for a **different act**, and the whole of ADR-0266 §7's proof is
        that the amount was quoted for *that* act.
        """
        seam = await self.holding([quote()])

        assert await seam.for_action(GOAL, act) == ()
