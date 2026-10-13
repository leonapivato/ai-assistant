"""ADR-0250 §20's arms that name §19's M3 — the ``orchestration`` threading.

Every case here drives the **production** path: a wired :class:`Engine` over the
canonical fakes, with the association scripted at the one seam §4 exposes and nothing
reached past. What the arms are about is which calls a turn makes, what it writes, and
what its outcome carries — none of which a loop-level case can see, because the store,
the association and the outcome are all the engine's.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from test_engine import AT, NoStepPlanner

from ai_assistant import orchestration
from ai_assistant.core.types import (
    AssociationVerdict,
    Goal,
    GoalAssociation,
    GoalInterpretation,
    GoalStatus,
    Ground,
    MemorySource,
    ProposedElement,
    ProposedQuestion,
    ProposedUnderstanding,
    Provenance,
)
from ai_assistant.testing import (
    FakeGoalAssociator,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import PlanStore

#: The module ADR-0250 §19's M3 added, which arm 29's absence is stated over.
_GOALS: Final = Path(orchestration.__file__).parent / "goals.py"


def _associating(verdict: AssociationVerdict, *labels: str) -> FakeGoalAssociator:
    """An associator scripted to one verdict, at ADR-0250 §4's own seam."""
    return FakeGoalAssociator(answer=GoalAssociation(verdict=verdict, labels=labels))


def _goal(
    goal_id: str, outcome: str, *, conversation: str, status: GoalStatus | None = None
) -> Goal:
    """A goal an earlier turn opened, as this system stores one."""
    return Goal(
        id=goal_id,
        conversation_id=conversation,
        interpretation=(
            GoalInterpretation(
                revision=1,
                outcome=outcome,
                outcome_ground=Ground.USER_STATED,
                outcome_span=outcome,
                recorded_at=AT,
                raised_by=f"turn-{goal_id}",
            ),
        ),
        status=GoalStatus.ACTIVE if status is None else status,
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT),
        created_at=AT,
    )


async def _seed(plans: PlanStore, goal: Goal, *, engaged_in: str | None = None) -> Goal:
    """Store a goal, engaging it where a case needs it in a candidate set."""
    await plans.save_goal(goal)
    if engaged_in is None:
        return goal
    return await plans.engage_goal(
        goal.id, at=AT, conversation_id=engaged_in, expected_version=goal.version
    )


_SUBJECT = ProposedUnderstanding(
    retains_outcome=True,
    criteria=(ProposedElement(text="a pitch by the river", ground=Ground.INFERRED),),
    questions=(ProposedQuestion(text="Which campsite did you mean?", about="S1"),),
)


class _Asking(NoStepPlanner):
    """A planner whose envelope a case rewrites between turns.

    **One instance across a case's turns**, because ``plan_id`` counts this planner's
    own calls: a second instance would restart the count and mint an id the store
    already holds, which ADR-0014 §2 refuses for the planner's own defect.
    """

    def __init__(self, understanding: ProposedUnderstanding | None = _SUBJECT) -> None:
        self.understanding = understanding

    async def plan(self, goal: Any, **fields: Any) -> Any:
        """Plan no step, proposing this planner's current understanding."""
        produced = await super().plan(goal, **fields)
        return produced.model_copy(update={"understanding": self.understanding})


# --------------------------------------------------------------------------- #
# Arms 14, 15, 18, 20, 22, 24, 25, 29, 32: the rest M3 owes                    #
# --------------------------------------------------------------------------- #


def test_no_notification_producer_is_built_on_any_path_of_this_decision() -> None:
    """§20 arm 29, asserted over the shipped tree rather than as a reading.

    "Raising a question, a question expiring, a question superseded and a goal paused
    each produce **no** ``NotificationCandidate``, no ``NotificationPolicy`` call and no
    ``NotificationStore`` row — asserted over the shipped tree, so that the absence of a
    producer is a fact rather than a reading of this document."

    §10 makes that absence this decision's ruling rather than an oversight: "**this
    decision builds no producer at all** … A producer is a decision with its own ADR,
    its own class, its own reach level and its own budget, and it is not made by
    inference from a deadline this decision added for a different reason."
    """
    named = sorted(
        name
        for name in ("NotificationCandidate", "NotificationPolicy", "NotificationStore")
        if name in _GOALS.read_text(encoding="utf-8")
    )

    assert named == [], f"ADR-0250 §10 builds no notification producer at all (found {named})"
