"""Shared conformance suite for the ``GoalQuotes`` Protocol (ADR-0267 §5).

Every :class:`~ai_assistant.core.protocols.GoalQuotes` implementation must pass
:class:`GoalQuotesContract`. A concrete test subclasses it and supplies the
``quotes`` fixture: the subject, **holding :data:`HELD` in that order** for
:data:`GOAL`.

**One fixed corpus rather than a seeding hook per case.** The seam does one thing —
filter by two identifiers and answer in the order it holds them — so every question
this suite asks can be asked of one history, and a subject that has to be rebuilt per
case is a subject a binding class cannot supply as a plain fixture. ``HELD`` is
deliberately awkward: two acts, a re-quote, two **equal** readings, and ``read_at``
values decades apart in both directions.

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
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.types import ActionQuote, StepOutputRef

if TYPE_CHECKING:
    from ai_assistant.core.protocols import GoalQuotes

#: The goal every quote of this suite belongs to.
GOAL: Final = "g1"

#: The two acts the suite keys on. **Two rather than one**, because the whole of what
#: the seam does is filter: a suite holding quotes for one act could not tell a
#: conforming filter from a member that returned everything it held.
ACTION: Final = "ia1"
OTHER_ACTION: Final = "ia2"

#: A well-formed arguments digest. The seam compares it against **nothing** (§5), so
#: what matters here is only that a quote is constructible.
DIGEST: Final = "a" * 64

#: When a scripted quote was read. **No case orders by it** (§1): the order this seam
#: answers in is the goal's own tuple order, and §6 refuses every reading of age.
READ_AT: Final = datetime(2026, 1, 2, tzinfo=UTC)

#: A reading far in the past, and one far in the future. Both are in :data:`HELD`
#: because §6's refusal runs in **both** directions: a seam applying a validity window
#: either way would drop one of them.
LONG_AGO: Final = datetime(2001, 1, 1, tzinfo=UTC)
FAR_AHEAD: Final = datetime(2099, 1, 1, tzinfo=UTC)


def quote(
    *,
    action: str = ACTION,
    amount: str = "120",
    currency: str = "EUR",
    read_at: datetime = READ_AT,
) -> ActionQuote:
    """One quote for ``action``, at the shape ADR-0267 §1 declares."""
    return ActionQuote(
        intended_action=action,
        arguments_digest=DIGEST,
        amount=Decimal(amount),
        currency=currency,
        plan="p1",
        read_from=StepOutputRef(step="s1", field="price"),
        read_at=read_at,
    )


#: The history every subject of this suite holds, **oldest first**.
#:
#: A re-quote for one act, a quote for another interleaved with it, a **second equal
#: reading** — because ADR-0267 §2 makes a refresh a position in the tuple rather than
#: a predicate, so a seam that de-duplicated would be evaluating one — and two
#: ``read_at`` values decades apart, because §6 expires nothing.
HELD: Final[tuple[ActionQuote, ...]] = (
    quote(amount="120", read_at=LONG_AGO),
    quote(action=OTHER_ACTION, amount="80"),
    quote(amount="135"),
    quote(amount="135"),
    quote(amount="200", read_at=FAR_AHEAD),
)

#: :data:`HELD`'s members naming :data:`ACTION`, in the order the goal holds them.
FOR_ACTION: Final[tuple[ActionQuote, ...]] = tuple(
    one for one in HELD if one.intended_action == ACTION
)


class GoalQuotesContract:
    """``GoalQuotes.for_action``'s clauses (ADR-0267 §5)."""

    @pytest.fixture
    def quotes(self) -> GoalQuotes:
        """The subject, holding :data:`HELD` in that order for :data:`GOAL`.

        Returns:
            The implementation under test, at its narrow face.

        Raises:
            NotImplementedError: If a subclass has not supplied one.
        """
        raise NotImplementedError

    async def test_for_action_answers_that_actions_quotes_in_the_goals_own_order(
        self, quotes: GoalQuotes
    ) -> None:
        """§5: "returning that goal's quotes naming that action **in the order the goal
        holds them**".

        The filter is the two identifiers and nothing else: a quote for another act is
        left out, and nothing is reordered, de-duplicated or collapsed to the last —
        the caller takes the last member, and a seam that returned only it would be
        the second implementation of ADR-0266 §7's governing rule.
        """
        assert await quotes.for_action(GOAL, ACTION) == FOR_ACTION
        assert await quotes.for_action(GOAL, OTHER_ACTION) == (
            quote(action=OTHER_ACTION, amount="80"),
        )

    async def test_two_equal_readings_both_come_back(self, quotes: GoalQuotes) -> None:
        """§2: a refresh is **position in the tuple** and not a predicate.

        There is nothing here for an implementation to evaluate, so a seam that
        collapsed two equal readings into one would be evaluating a rule the store is
        expressly forbidden to have — and would move ``quotes_elided``'s arithmetic
        out from under the caller.
        """
        answered = await quotes.for_action(GOAL, ACTION)
        assert answered.count(quote(amount="135")) == 2

    async def test_for_action_answers_empty_for_an_action_the_goal_has_no_quote_for(
        self, quotes: GoalQuotes
    ) -> None:
        """§5: "possibly empty", and an empty tuple means exactly that.

        ADR-0266 §7 then leaves the member unmet, the request uncovered and the act
        **asked about** — which is the fail-closed direction, and is a different fact
        from the fault the seam raises on.
        """
        assert await quotes.for_action(GOAL, "ia-none") == ()

    async def test_for_action_answers_empty_for_a_goal_the_subject_does_not_hold(
        self, quotes: GoalQuotes
    ) -> None:
        """§5: a goal with no quotes is an absence and never a fault.

        A goal a store has never seen holds no quote for any act, which is the same
        answer ADR-0266 §7 reads as *"no quote governs"* — the act asks.
        """
        assert await quotes.for_action("g-none", ACTION) == ()

    async def test_for_action_reads_no_clock_and_refuses_no_quote_for_its_age(
        self, quotes: GoalQuotes
    ) -> None:
        """§6: "nothing in this decision expires a quote", and this seam least of all.

        A quote governs until a later one for the same action displaces it, however
        long ago it was read — *"no lane refuses a quote for being old, computes a
        validity window from ``read_at``, compares ``read_at`` to the instant of
        dispatch, or adds an expiry field"*. :data:`HELD` carries a reading from 2001
        and one from 2099, because a seam applying a window in **either** direction
        would drop one of them.
        """
        answered = await quotes.for_action(GOAL, ACTION)
        assert [one.read_at for one in answered] == [one.read_at for one in FOR_ACTION], (
            "no reading is dropped, reordered or preferred for its age"
        )

    async def test_for_action_is_a_read_and_leaves_the_subject_where_it_found_it(
        self, quotes: GoalQuotes
    ) -> None:
        """§5: the seam answers, and **no lane appends through it**.

        Two calls answer the same tuple: a member that recorded, cached a selection or
        advanced a version would show here, and a policy holding this face has no
        ``record_quote`` to reach for.
        """
        first = await quotes.for_action(GOAL, ACTION)
        assert await quotes.for_action(GOAL, ACTION) == first

    async def test_the_answer_is_a_detached_snapshot_a_caller_cannot_rewrite(
        self, quotes: GoalQuotes
    ) -> None:
        """§5 takes ``GoalAuthorizations.live_for``'s direction, detachment included.

        *"``frozen=True`` does not close the bypass: a caller could rewrite …
        through ``__dict__`` on a shared object, which is a widening of what the user
        authorised, reached through the gate's own answer."* One record over that is an
        **amount**: a caller holding this seam's answer could raise the figure a
        ``MONEY`` ceiling is proved against to one no provider ever quoted, and
        ADR-0266 §7 would compare against it.

        **Asserted by rewriting a returned quote and reading again** — not by comparing
        two consecutive answers, which an implementation handing back the *same*
        aliased objects passes trivially. ``__dict__`` rather than assignment, because
        the model is frozen and assignment is not the bypass this is about.
        """
        answered = await quotes.for_action(GOAL, ACTION)
        before = answered[0].amount
        answered[0].__dict__["amount"] = before + Decimal("1000")

        again = await quotes.for_action(GOAL, ACTION)
        assert again[0].amount == before, "a rewritten answer moved what the seam holds"
        assert [one.amount for one in again] == [one.amount for one in FOR_ACTION]

    @pytest.mark.parametrize("act", ["ia1 ", " ia1", "IA1", "ia11", "ia"])
    async def test_the_key_is_compared_whole_and_never_by_prefix_or_fold(
        self, quotes: GoalQuotes, act: str
    ) -> None:
        """§5: the filter is equality of the identifier and nothing looser.

        No case folding, no trimming, no prefix match. A looser key would answer a
        quote read for a **different act**, and the whole of ADR-0266 §7's proof is
        that the amount was quoted for *that* act.
        """
        assert await quotes.for_action(GOAL, act) == ()
