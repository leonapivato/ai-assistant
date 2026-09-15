"""ADR-0265 §2's minting, end to end, on both conforming stores.

**What a turn *produces* and what a store *holds* are two facts, and neither proves the
other.** ``test_loop_intended_actions.py`` drives the loop and reads the record it built;
what is asserted here is the joint — that the minting reaches a real ``PlanStore``
through the one member §5 adds, that ``save_plan``'s added conjunct is satisfied by the
value a turn actually produces, and that the ``expected_version`` each write is computed
against is the one the write before it returned.

**The opening write is where the two decisions meet.** ``save_goal`` refuses a goal
opened carrying an intended action (§1, §2), so a turn that opens a goal *and* mints on
the same call has to take two writes in one order: the chain, then the actions. A turn
that only ever produced one of the two would never exercise it — which is why every arm
here drives a whole ``converse``.

Both arms run over ``FakePlanStore`` and over ``SqlitePlanStore``, for
``test_engine_plan_labels.py``'s reason: "a conformance suite exercising one
implementation would be a suite that lets the other disagree", read one level up at the
consumer that drives them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, cast

import pytest
from test_engine import AT, PATIENT, Harness, NoStepPlanner

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    AssociationVerdict,
    GoalAssociation,
    Ground,
    IntendedActionMinting,
    PlanStep,
    ProposedAction,
    ProposedElement,
    ProposedUnderstanding,
)
from ai_assistant.planning.sqlite_store import SqlitePlanStore
from ai_assistant.testing import FakeGoalAssociator, FakePlanStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from ai_assistant.core.protocols import PlanStore
    from ai_assistant.core.types import ActionPlan, Goal

#: What the planner proposes the goal now depends on, so a minted action has a live
#: element to serve on the very call that proposes both.
_CONSTRAINT: Final = "both rooms are on the same floor"

_FIRST_ROOM: Final = "book the first room"
_SECOND_ROOM: Final = "book the second room"


def _step(step_id: str, *, action: str | None) -> PlanStep:
    """One step selecting an intended action by ``A`` label (§4).

    The capability and the ``parameters`` are byte-identical across the two steps a case
    builds, which is §6's point: at the argument key nothing distinguishes two rooms
    asked for from one room asked for twice.
    """
    return PlanStep(
        id=step_id,
        intent="book it",
        capability="book_room",
        parameters={"nights": 2},
        intended_action=action,
    )


class _Minting(NoStepPlanner):
    """A planner that proposes an understanding, intended actions and a plan in one call.

    ADR-0249 §7 has a planner decide the understanding and the plan "in one pass", and
    ADR-0265 §2 orders the loop's minting between the two for exactly this shape: on the
    turn an intended action first exists, it exists only in the ``PlannerOutput`` that
    call returned.
    """

    def __init__(
        self,
        *,
        understanding: ProposedUnderstanding | None = None,
        actions: tuple[ProposedAction, ...] = (),
        steps: tuple[PlanStep, ...] = (),
    ) -> None:
        self.understanding = understanding
        self.actions = actions
        self.steps = steps

    async def plan(self, goal: Any, **fields: Any) -> Any:
        """Answer with this planner's current envelope."""
        produced = await super().plan(goal, **fields)
        return produced.model_copy(
            update={
                "understanding": self.understanding,
                "actions": self.actions,
                "plan": produced.plan.model_copy(update={"steps": self.steps}),
            }
        )


class _CountingPlanStore(FakePlanStore):
    """A store that counts the mintings it was handed, one per call."""

    mintings: int = 0

    async def record_intended_actions(self, minting: IntendedActionMinting) -> Goal:
        """Count the call, then append exactly as the canonical fake does."""
        self.mintings += 1
        return await super().record_intended_actions(minting)


def _continuing() -> FakeGoalAssociator:
    """An associator that continues the conversation's focused goal (ADR-0250 §4).

    Scripted at the one seam §4 exposes, so a second turn reaches the goal the first one
    opened without this module reaching past the production association path.
    """
    return FakeGoalAssociator(answer=GoalAssociation(verdict=AssociationVerdict.CONTINUES))


@pytest.fixture(name="sqlite_plans")
async def _sqlite_plans(tmp_path: Path) -> AsyncIterator[SqlitePlanStore]:
    """The other conforming ``PlanStore``, over a real file."""
    store = SqlitePlanStore(path=tmp_path / "plans.db", now=lambda: AT)
    try:
        yield store
    finally:
        store.close()


async def _drive(plans: PlanStore) -> tuple[Harness, ActionPlan]:
    """One turn that opens a goal, proposes a constraint, mints two actions and plans.

    Args:
        plans: The store to wire the engine with.

    Returns:
        The harness, and the plan the turn produced.
    """
    planner = _Minting(
        understanding=ProposedUnderstanding(
            retains_outcome=True,
            constraints=(ProposedElement(text=_CONSTRAINT, ground=Ground.INFERRED),),
        ),
        actions=(
            ProposedAction(intent=_FIRST_ROOM, serves=("C1",)),
            ProposedAction(intent=_SECOND_ROOM, serves=("C1",)),
        ),
        steps=(_step("step-1", action="A1"), _step("step-2", action="A2")),
    )
    harness = Harness(planner=planner, plans=cast("FakePlanStore", plans))

    outcome = await harness.engine.converse("book two rooms for the trip", timeout=PATIENT)

    assert outcome.turn is not None
    return harness, outcome.turn.plan


async def _assert_round_trip(plans: PlanStore, plan: ActionPlan) -> None:
    """Both actions reach the store, and the plan that names them is accepted.

    Args:
        plans: The store the engine was wired with.
        plan: The plan the turn produced.
    """
    goal = await plans.get_goal(plan.goal_id)
    assert goal is not None
    [element] = goal.interpretation[-1].constraints
    assert element.id is not None, "ADR-0253 §7: orchestration minted it a moment earlier"

    first, second = goal.intended_actions
    assert (first.intent, second.intent) == (_FIRST_ROOM, _SECOND_ROOM), "§1: oldest first"
    assert first.id != second.id, "§10 arm 1: two identical rooms are two identities"
    assert (first.serves, second.serves) == ((element.id,), (element.id,)), (
        "§3: the link the same call's revision minted, resolved before the append"
    )
    assert goal.version > 0, "§5's compare-and-swap advanced it; the token is the store's"

    assert plan.steps[0].intended_action == first.id
    assert plan.steps[1].intended_action == second.id
    assert plan.steps[0].parameters == plan.steps[1].parameters, "and the argument key is equal"

    stored = await plans.get_plan(plan.id)
    assert stored is not None, "save_plan accepted it: §4's store-side conjunct is satisfied"
    assert stored.steps == plan.steps, "and it reads back unchanged"


async def test_a_turns_minting_reaches_the_fake_store() -> None:
    """§10 arm 1(b)'s persistence half, over ``FakePlanStore``.

    The opening write and the minting in the one order that works: ``save_goal`` is
    handed the goal **without** its actions, because §2 makes
    ``record_intended_actions`` "the only route to a new ``IntendedAction``" and §1 has
    the opening write mint none. A turn that handed the seeded tuple to ``save_goal``
    would be refused here, on either implementation.
    """
    harness, plan = await _drive(FakePlanStore(now=lambda: AT))

    await _assert_round_trip(harness.plans, plan)


async def test_a_turns_minting_reaches_the_sqlite_store(sqlite_plans: SqlitePlanStore) -> None:
    """The same turn, the same assertions, over the other conforming implementation."""
    _, plan = await _drive(sqlite_plans)

    await _assert_round_trip(sqlite_plans, plan)


async def test_two_actions_minted_on_one_turn_take_one_compare_and_swap() -> None:
    """§5: "two actions minted on one turn are appended in one call".

    "So the two-rooms case takes one compare-and-swap and not two" — which is what makes
    the member's all-or-nothing limb mean anything: split across two writes, a bound or
    a bad ``serves`` could leave *book two identical rooms* holding one intended action,
    "which is the two-rooms defect reached through the capacity path".
    """
    plans = _CountingPlanStore(now=lambda: AT)

    harness, plan = await _drive(plans)

    assert plans.mintings == 1, "one planner call that minted, one write"
    goal = await harness.plans.get_goal(plan.goal_id)
    assert goal is not None
    assert len(goal.intended_actions) == 2


async def test_a_plan_naming_an_action_the_goal_does_not_hold_is_never_persisted() -> None:
    """§4: the refusal reaches the turn, and nothing of that turn is written.

    "The loop **refuses the plan** … it is not passed to ``save_plan``, no step of it is
    dispatched and no interpretation of it is performed." The refusal is taken before
    ADR-0249 §11's persistence site, so the goal row, the plan row and the attempt row
    are all absent — which is the same shape a turn that could not produce a plan at all
    leaves, and what that refusal then causes is A7's and A9's.
    """
    goals = iter([f"goal-{ordinal}" for ordinal in range(1, 40)])
    harness = Harness(
        planner=_Minting(steps=(_step("step-1", action="A1"),)),
        loop_id_factory=lambda: next(goals),
    )

    with pytest.raises(PlanningError, match="A1"):
        await harness.engine.converse("book two rooms for the trip", timeout=PATIENT)

    assert await harness.plans.get_goal("goal-1") is None, "no goal row, no plan row, no attempt"
    assert (await harness.plans.export()).goals == ()


async def test_a_second_turns_minting_follows_the_revision_that_turn_recorded() -> None:
    """§10 arm 1(b)'s version limb, on the route where the two writes are really two.

    A goal the store **already holds** takes ``record_interpretation`` per revision and
    ``record_intended_actions`` per minting, and §2 records a call's actions **after**
    that same call's revision — so "the ``expected_version`` the minting carries is the
    one the revision left and the append is not refused stale". Batching the mintings
    after the revisions would be visible here as nothing at all on a one-call turn, and
    as a refusal on a turn whose revision restated the element its own action serves: the
    member checks each ``serves`` against the **current** interpretation at the append.

    It is also where §1's append-only tuple is read across turns: the action turn 1
    minted is still there, first, with turn 2's appended after it.
    """
    planner = _Minting(actions=(ProposedAction(intent=_FIRST_ROOM),))
    harness = Harness(planner=planner, associator=_continuing())
    conversation = (await harness.conversations.begin(None)).id

    opened = await harness.engine.converse(
        "book a room", timeout=PATIENT, conversation_id=conversation
    )

    assert opened.turn is not None
    goal_id = opened.turn.goal.goal_id
    after_opening = await harness.plans.get_goal(goal_id)
    assert after_opening is not None

    planner.understanding = ProposedUnderstanding(
        retains_outcome=True,
        constraints=(ProposedElement(text=_CONSTRAINT, ground=Ground.INFERRED),),
    )
    planner.actions = (ProposedAction(intent=_SECOND_ROOM, serves=("C1",)),)
    planner.steps = (_step("step-1", action="A2"),)

    continued = await harness.engine.converse(
        "and book a second one", timeout=PATIENT, conversation_id=conversation
    )

    assert continued.turn is not None
    assert continued.turn.goal.goal_id == goal_id, "the same goal, continued"
    stored = await harness.plans.get_goal(goal_id)
    assert stored is not None
    assert len(stored.interpretation) == 2, "the revision this turn recorded"
    [element] = stored.interpretation[-1].constraints
    first, second = stored.intended_actions
    assert (first.intent, second.intent) == (_FIRST_ROOM, _SECOND_ROOM), "§1: append-only"
    assert first.serves == (), "turn 1 proposed no link"
    assert second.serves == (element.id,), "and turn 2's link names the element it just minted"
    assert stored.version > after_opening.version, "each write returned the next one's token"
    assert continued.turn.plan.steps[0].intended_action == second.id, (
        "§4: A2 over the extended tuple — the brief's one action plus this call's own"
    )
