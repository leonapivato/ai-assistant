"""ADR-0249 §5, §6, §11 and §12 at the engine: the attempt is opened, stamped and ended.

The attempt-shaped half of §16's L3 arms. Every one of them is engine-level by
construction: ``LearningLoop`` holds no ``PlanStore`` and gains none (ADR-0228 §5), so
the attempt is opened **in memory** by the loop and every write of it is this
component's, at the one site that persists a plan today (§11).

What lives here is §16 item 1's attempt half (S1's six phase stamps, its stored row and
the goal's status), item 14's second clause (a turn that reaches the site records what it
actually finished on), item 19 within a turn, and §12's two-route persistence — a goal
this turn opened through ``save_goal``, a goal the store already holds through
``record_interpretation`` under the compare-and-swap.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from test_engine import (
    AT,
    Harness,
    NoStepPlanner,
)

from ai_assistant.core.types import (
    AttemptEffort,
    AttemptPhase,
    Goal,
    GoalAttempt,
)
from ai_assistant.orchestration.loop import OpenedAttempt
from ai_assistant.testing import (
    FakePlanStore,
)

if TYPE_CHECKING:
    from ai_assistant.core.types import AttemptTransition, GoalRevision


class _Recording(FakePlanStore):
    """The canonical store, recording the attempt writes it was asked for.

    §6 makes the six phases "six responsibilities and **six observable transitions**",
    and three of a turn's six happen before any row exists to observe them on — so what
    a case can see at the store is the phase the row was **opened** at and each
    ``to_phase`` after it. Together they are the sequence the attempt occupied.
    """

    def __init__(self) -> None:
        super().__init__(now=lambda: AT)
        self.opened: list[GoalAttempt] = []
        self.moves: list[AttemptTransition] = []
        self.appended: list[GoalRevision] = []

    async def open_attempt(self, attempt: GoalAttempt) -> str:
        """Record and delegate."""
        self.opened.append(attempt)
        return await super().open_attempt(attempt)

    async def commit_attempt(self, transition: AttemptTransition) -> GoalAttempt:
        """Record and delegate."""
        self.moves.append(transition)
        return await super().commit_attempt(transition)

    async def record_interpretation(self, revision: GoalRevision) -> Goal:
        """Record and delegate."""
        self.appended.append(revision)
        return await super().record_interpretation(revision)

    @property
    def phases(self) -> list[AttemptPhase]:
        """Every phase the attempt was stamped with at this store, in order."""
        return [one.phase for one in self.opened] + [
            move.to_phase for move in self.moves if move.to_phase is not None
        ]


# --------------------------------------------------------------------------- #
# §16 item 1 — S1, end to end                                                  #
# --------------------------------------------------------------------------- #


def test_the_ledger_never_decreases_when_the_clock_goes_backwards() -> None:
    """§5: "monotonically non-decreasing … and no implementation subtracts from one".

    The injected clock supplies wall-clock instants and guarantees no monotonicity
    (ADR-0009), so an adjustment backwards would otherwise make the interval negative —
    which :class:`~ai_assistant.core.types.AttemptEffort` refuses at construction and
    ``commit_attempt`` refuses as a reduction. A backward reading contributes nothing
    rather than failing a turn that has already answered.
    """
    harness = Harness(planner=NoStepPlanner())
    held = OpenedAttempt(
        attempt=GoalAttempt(
            id="a-1",
            goal_id="g-1",
            opened_at=AT,
            effort=AttemptEffort(working=timedelta(seconds=5)),
        )
    )

    backwards = harness.engine._worked(held, AT + timedelta(minutes=1))
    forwards = harness.engine._worked(held, AT - timedelta(seconds=30))

    assert backwards == timedelta(seconds=5), "unchanged, and never negative"
    assert forwards == timedelta(seconds=35), "and it does accumulate the other way"
