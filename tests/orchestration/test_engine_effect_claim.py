"""ADR-0259 §12's arm 1, at the level the told-once fact lives: a ``TurnOutcome``.

``satisfied_from_earlier`` rides on the turn, so the fold ADR-0242 §9's shape requires —
*"carried by value from what the stage computed and never a second computation"* — is a
property of ``Engine``'s capture point and of nothing ``StepRunner`` returns. This module
drives two whole ``converse`` calls over one goal for that one assertion, and
``test_effect_claim.py`` carries every other half of the arm.

**One turn can satisfy at most one step on this tree**, because ADR-0255's own L2 lands
the walk and until it does ``Engine`` drives ``turn.plan.steps[0]``. So the tuple here is
one element long by construction; that it is a tuple in walk order rather than a folded
scalar is asserted over
:func:`~ai_assistant.orchestration.effects.told_once` in ``test_effect_claim.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from test_engine import PATIENT, Harness, NoStepPlanner

from ai_assistant.core.types import (
    AssociationVerdict,
    CostBasis,
    Disposition,
    GoalAssociation,
    Idempotency,
    PlanStep,
    ProposedAction,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.testing import FakeGoalAssociator

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import FrozenJson

_CAPABILITY: Final = "book_room"
_ACT: Final = "book the room"

#: Byte-identical across both turns, which is what makes the second turn's step carry the
#: **same** ``EffectKey`` as the first one's — the whole premise of a ``COMPLETED`` answer.
_PARAMETERS: Final[dict[str, FrozenJson]] = {"nights": 2}
_OUTPUT: Final[dict[str, FrozenJson]] = {"booking": "bk-9"}


def _tool() -> ToolDefinition:
    """A side-effecting declaration the fake policy allows outright."""
    return ToolDefinition(
        id="rooms",
        capability=_CAPABILITY,
        description="Book a room.",
        risk_level=RiskLevel.LOW,
        reversibility=Reversibility.REVERSIBLE,
        side_effecting=True,
        reads=(),
        writes=(),
        discloses=(),
        cost=ToolCost(basis=CostBasis.FREE),
        idempotency=Idempotency.NATURAL,
    )


async def _books(
    parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
) -> FrozenJson:
    """The callable, which must be reached exactly once across the two turns."""
    return _OUTPUT


class _Booking(NoStepPlanner):
    """A planner that mints the act on its first call and repeats it on its second.

    The ``A`` label indexes ``GoalBrief.actions`` extended by this call's own
    ``PlannerOutput.actions`` (ADR-0265 §4), so the first call proposes the act and names
    ``A1``, and the second finds the very same act already on the brief under that label
    and proposes none of its own — which is what makes the two steps two attempts at
    **one** intended action rather than two acts.
    """

    def __init__(self) -> None:
        self.turns = 0

    async def plan(self, goal: Any, **fields: Any) -> Any:
        """Answer with a one-step plan naming ``A1``, minting it on the first call."""
        produced = await super().plan(goal, **fields)
        self.turns += 1
        step = PlanStep(
            id=f"step-{self.turns}",
            intent="book it",
            capability=_CAPABILITY,
            parameters=_PARAMETERS,
            intended_action="A1",
        )
        return produced.model_copy(
            update={
                "actions": (ProposedAction(intent=_ACT),) if self.turns == 1 else (),
                "plan": produced.plan.model_copy(update={"steps": (step,)}),
            }
        )


async def test_a_turn_that_satisfied_a_step_says_so_and_one_that_did_not_says_nothing() -> None:
    """Arm 1's told-once half: ``None`` on the acting turn, the step's id on the borrowing one."""
    harness = Harness(
        planner=_Booking(),
        associator=FakeGoalAssociator(answer=GoalAssociation(verdict=AssociationVerdict.CONTINUES)),
        tools=(_tool(),),
        tool_handler=_books,
    )

    conversation = (await harness.conversations.begin(None)).id
    acted = await harness.engine.converse(
        "book the room for the trip", timeout=PATIENT, conversation_id=conversation
    )
    borrowed = await harness.engine.converse(
        "book the room for the trip", timeout=PATIENT, conversation_id=conversation
    )

    assert acted.step is not None
    assert acted.step.disposition is Disposition.EXECUTED
    assert acted.satisfied_from_earlier is None, "the acting turn satisfied nothing"
    assert borrowed.step is not None
    assert borrowed.step.disposition is Disposition.EXECUTED, "the walk was not stopped"
    assert borrowed.satisfied_from_earlier == (borrowed.step.step_id,), (
        "the ids of the steps this turn satisfied, in walk order"
    )
    assert borrowed.step.step_id != acted.step.step_id, "its own id, never the holder's"
    record = next(one for one in borrowed.step.state.steps if one.step_id == borrowed.step.step_id)
    assert record.output == _OUTPUT, "the holder's own output, copied by the store"
    assert record.satisfied_by_step == acted.step.step_id
    assert record.attempts == 0, "nothing ran under it"
