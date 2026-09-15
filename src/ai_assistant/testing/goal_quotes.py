"""The canonical fake for :class:`~ai_assistant.core.protocols.GoalQuotes` (ADR-0267 §5).

**The policy's face onto the price a ``MONEY`` ceiling is proved against**, and the
narrow one: one member, no way to append a quote, and no way to reach ``PlanStore``. A
policy handed this cannot name ``record_quote``, which is the static guarantee ADR-0097
§3's split buys and which ``mypy --strict`` is what enforces.

**It holds records and evaluates no predicate** (§5). It filters by the two identifiers
and returns that action's quotes **in the order it was given them**; it does not select
the governing quote, compare a digest, compare an amount or read a ``CoverageMember``.
``permissions`` takes the last member of what comes back, and a fake that selected would
be a second place the governing rule lives.

**The fault limb is armable, because "a fault is not an absence" is a rule about this
seam** (§5) — but arming it here satisfies the limb by construction, so the shared
conformance suite drives it against ``planning``'s durable store as well, which is where
the failure actually comes from.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from ai_assistant.core.errors import AuthorizationError
from ai_assistant.testing.cancellation import SuspendableResource

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import ActionQuote
    from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog


@final
class FakeGoalQuotes:
    """A non-persistent ``GoalQuotes`` test double (ADR-0267 §5).

    **Keyed on the goal and the intended action alone**, exactly as the Protocol is: it
    is handed quotes, it filters, and it answers in the order it holds them.
    """

    def __init__(self, quotes: Sequence[ActionQuote] = (), *, goal: str = "g1") -> None:
        """Create the seam.

        Args:
            quotes: The quotes it starts with, **in the order the goal holds them** —
                oldest first, which is the order ADR-0267 §2 makes the total order the
                governing-quote rule reads. Nothing here sorts them.
            goal: The goal every quote it holds belongs to. A seam keyed on one goal is
                enough for a policy's question, which is about the one request it is
                ruling on; :meth:`hold_for` adds a second where a suite needs one.
        """
        self._quotes: dict[str, list[ActionQuote]] = {goal: list(quotes)}
        self._resource = SuspendableResource()
        self._failure: Exception | None = None
        self._calls = 0

    @property
    def call_count(self) -> int:
        """How many times :meth:`for_action` has been called.

        ADR-0254 §6's *"at most once per ruling"* discipline is a rule about the policy,
        and a seam that cannot be counted cannot falsify it.
        """
        return self._calls

    def hold_for(self, goal: str, *quotes: ActionQuote) -> None:
        """Append quotes to a goal after construction, in the order given.

        Args:
            goal: The goal to append to.
            quotes: The quotes, oldest first. **Appended and never sorted**: the order
                this seam answers in is the order it was given, because the store's
                order is the record's own.
        """
        self._quotes.setdefault(goal, []).extend(quotes)

    def fail_for_action(self, error: Exception | None = None) -> None:
        """Arm every subsequent :meth:`for_action` to raise a store fault.

        **The branch ADR-0267 §5's fault clause is stated over.** A fault is **not** an
        absence: no implementation converts it into an empty tuple, the request is then
        not covered, ADR-0254 §6's bar is taken, and no standing route is taken at all.

        Args:
            error: The underlying fault, preserved as ``__cause__``.
        """
        self._failure = (
            error if error is not None else RuntimeError("fake: the plan store is unreadable")
        )

    async def for_action(self, goal: str, intended_action: str) -> tuple[ActionQuote, ...]:
        """That goal's quotes naming that action, in the order it holds them.

        Returns:
            The quotes, oldest first, possibly empty. **Empty means the goal holds none
            for that action** and never that the store could not be read.

        Raises:
            AuthorizationError: If a fault is armed (:meth:`fail_for_action`).
        """
        self._calls += 1
        if self._failure is not None:
            msg = "fake: the goal's quotes could not be read"
            raise AuthorizationError(msg) from self._failure
        async with self._resource.held():
            return tuple(
                quote
                for quote in self._quotes.get(goal, ())
                if quote.intended_action == intended_action
            )

    def suspend_next_operation(self) -> LoopSuspension:
        """Hold the next call that enters the modelled resource open inside it."""
        return self._resource.suspend_next()

    @property
    def resource_log(self) -> ResourceLog:
        """When each call was inside the modelled resource (ADR-0060's case reads it)."""
        return self._resource.log


__all__ = ["FakeGoalQuotes"]
