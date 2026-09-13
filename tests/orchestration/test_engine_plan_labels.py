"""ADR-0253 §9's substitution, end to end, on both conforming stores.

**The window §9 closes has two ends and they are checked at two altitudes.** The loop
substitutes each condition label for an element id and refuses a plan on which it could
not; ``PlanStore.save_plan`` refuses a plan on which it has not. Neither half proves the
other: a loop that substituted nothing would fail at the store, and a store check exercised
over a hand-built plan says nothing about the value a turn actually produces. What is
asserted here is the **joint**, over a turn that opens a goal, proposes the condition its
own plan names, and persists the plan through a real ``PlanStore``.

§14 arm 20's paired half rides the same turn — *"the arm that matters"*: a plan whose
interpretation carries a ``record`` the loop **did** pass is saved, through the real
orchestration save path.

**Nothing here evaluates the condition, and that is §12 rather than an omission**: "no
lane of this decision performs an interpretation call, evaluates a condition, resolves a
reference, computes ``GoalRevision.invalidates``, dispatches a step or writes a
``SkipReason``". What these arms read is the value the plan *records*, which is the whole
of what the decision puts in the store for A7 to walk.

Both arms run over ``FakePlanStore`` and over ``SqlitePlanStore``, for
``test_engine_goal_evidence.py``'s reason: "a conformance suite exercising one
implementation would be a suite that lets the other disagree", read one level up at the
consumer that drives them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, cast

import pytest
from test_engine import AT, PATIENT, Harness, NoStepPlanner

from ai_assistant.core.types import (
    EvidenceBasis,
    Ground,
    InterpretationVerdict,
    MemorySource,
    Placement,
    PlanInterpretation,
    PlanStep,
    ProposedElement,
    ProposedUnderstanding,
    Provenance,
    SemanticMemory,
    StepCondition,
)
from ai_assistant.planning.sqlite_store import SqlitePlanStore
from ai_assistant.testing import FakeMemoryStore, FakePlanStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from ai_assistant.core.protocols import PlanStore
    from ai_assistant.core.types import ActionPlan

#: The word the seeded belief and the utterance share, so the turn's retrieval selects
#: it and the plan's interpretation has a durable record of the supply to name.
_TOPIC: Final = "weather"

_BELIEF: Final = "belief-forecast"

#: What the planner proposes the goal now depends on, and what its plan then conditions
#: on — the whole of ADR-0253 §9's first-turn case in one sentence.
_CONDITION: Final = "the forecast over the trip is dry"


def _belief() -> SemanticMemory:
    """One durable record the turn's retrieval puts in the planner's supply."""
    content = f"the {_TOPIC} forecast comes from the met office"
    return SemanticMemory(
        id=_BELIEF,
        content=content,
        fact=content,
        placement=Placement(),
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=AT),
    )


class _Conditioning(NoStepPlanner):
    """A planner that proposes one condition and plans against it in the same call.

    ADR-0249 §7 has a planner decide the understanding and the plan "in one pass", and
    §9 orders the loop's substitution after the recording for exactly this shape: on the
    turn a condition first exists, it exists only in the ``ProposedUnderstanding`` that
    call returned.
    """

    def __init__(self) -> None:
        self.supplied: tuple[str, ...] = ()

    async def plan(self, goal: Any, **kwargs: Any) -> Any:
        """Answer with a plan carrying one conditioned step and one interpretation."""
        self.supplied = tuple(record.id for record in kwargs["memories"])
        produced = await super().plan(
            goal,
            utterance=kwargs["utterance"],
            context=kwargs["context"],
            memories=kwargs["memories"],
            capabilities=kwargs["capabilities"],
        )
        interpretation = PlanInterpretation(
            id="interpretation-1",
            # ADR-0253 §9's condition label, which the loop replaces with the id it
            # minted for the element proposed below. The planner never resolves it.
            settles="D1",
            # Resolved by the seam that rendered the `M` label (ADR-0226 §3), so what
            # crosses here is already an id of a record this call was handed — which is
            # the population §8 has the loop verify it against.
            record=self.supplied[0],
        )
        step = PlanStep(
            id="step-1",
            intent="book it",
            capability="book_campsite",
            when=(
                StepCondition(
                    about="D1",
                    basis=EvidenceBasis.INTERPRETATION,
                    requires=InterpretationVerdict.QUALIFIES,
                ),
            ),
        )
        return produced.model_copy(
            update={
                "plan": produced.plan.model_copy(
                    update={"interpretations": (interpretation,), "steps": (step,)}
                ),
                "understanding": ProposedUnderstanding(
                    retains_outcome=True,
                    conditions=(ProposedElement(text=_CONDITION, ground=Ground.INFERRED),),
                ),
            }
        )


async def _drive(plans: PlanStore) -> tuple[Harness, _Conditioning, ActionPlan]:
    """Run one turn that opens a goal, proposes a condition and plans against it.

    Args:
        plans: The store to wire the engine with.

    Returns:
        The harness, the planner it was wired with, and the plan the turn produced.
    """
    planner = _Conditioning()
    memory = FakeMemoryStore(now=lambda: AT)
    await memory.add(_belief())
    harness = Harness(planner=planner, memory=memory, plans=cast("FakePlanStore", plans))

    outcome = await harness.engine.converse(f"what is the {_TOPIC} doing", timeout=PATIENT)

    assert outcome.turn is not None
    return harness, planner, outcome.turn.plan


@pytest.fixture(name="sqlite_plans")
async def _sqlite_plans(tmp_path: Path) -> AsyncIterator[SqlitePlanStore]:
    """The other conforming ``PlanStore``, over a real file."""
    store = SqlitePlanStore(path=tmp_path / "plans.db", now=lambda: AT)
    try:
        yield store
    finally:
        store.close()


async def _assert_round_trip(plans: PlanStore, planner: _Conditioning, plan: ActionPlan) -> None:
    """The plan the turn produced carries an element id, and reads back carrying it.

    Args:
        plans: The store the engine was wired with.
        planner: The planner the turn was driven with.
        plan: The plan the turn produced.
    """
    goal = await plans.get_goal(plan.goal_id)
    assert goal is not None
    [element] = goal.interpretation[-1].conditions
    assert element.text == _CONDITION
    assert element.id is not None, "ADR-0253 §7: orchestration minted it a moment earlier"

    assert plan.targets_revision == goal.revision == 2, "ADR-0249 §8's stamp, taken first"
    assert plan.interpretations[0].settles == element.id, (
        "ADR-0253 §9: the label is gone and the element's own id stands in its place"
    )
    assert plan.interpretations[0].record == planner.supplied[0], (
        "§9's writer clause: every field but the two it names is exactly as returned"
    )

    stored = await plans.get_plan(plan.id)
    assert stored is not None, "save_plan accepted it: §9's store-side conjunct is satisfied"
    assert stored.interpretations == plan.interpretations, "and it reads back unchanged"
    assert stored.steps[0].when[0].about == element.id, (
        "the same substitution on the step's own condition, through the same write"
    )


async def test_a_turns_substituted_plan_reaches_the_fake_store() -> None:
    """§14 arm 20's paired half and §9's joint, over ``FakePlanStore``."""
    harness, planner, plan = await _drive(FakePlanStore(now=lambda: AT))

    await _assert_round_trip(harness.plans, planner, plan)


async def test_a_turns_substituted_plan_reaches_the_sqlite_store(
    sqlite_plans: SqlitePlanStore,
) -> None:
    """The same turn, the same assertions, over the other conforming implementation."""
    _, planner, plan = await _drive(sqlite_plans)

    await _assert_round_trip(sqlite_plans, planner, plan)
