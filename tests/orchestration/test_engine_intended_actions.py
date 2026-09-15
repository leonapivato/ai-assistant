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
from test_engine_revision import _ADDRESS, _ASKED, _hop, _store_holding_the_address

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    ActionPlan,
    AssociationVerdict,
    GoalAssociation,
    Ground,
    IntendedActionMinting,
    PlannerOutput,
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
    from ai_assistant.core.types import Goal, MemoryRecord

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


class _TwoCall:
    """A planner that asks for a read, mints on both calls, and plans on the second.

    ADR-0228 §3 bounds a turn at two ``Planner.plan`` calls, and ADR-0265 §2's ordering
    is stated **per call** — "on every ``PlannerOutput`` a planner returns". A turn that
    only ever made one call could not tell a loop that mints once per call from one that
    mints once per turn, which is the gap this class exists to close.

    **It reads the supply and not the iteration** for what it *plans* (ADR-0228 §12), and
    counts its own calls only to vary what it *proposes* — which is a fake's own
    bookkeeping and crosses no seam.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[MemoryRecord, ...]] = []

    async def plan(self, goal: Any, **fields: Any) -> Any:
        """Ask for the hop and mint the first room; on the second call, mint and plan."""
        ordinal = len(self.calls) + 1
        self.calls.append(tuple(fields["memories"]))
        if not any(_ADDRESS in one.content for one in fields["memories"]):
            return PlannerOutput(
                plan=ActionPlan(
                    id=f"{goal.goal_id}-plan-{ordinal}",
                    goal_id=goal.goal_id,
                    steps=(),
                    created_at=AT,
                    rationale="the address is not in front of me",
                    read_request=_hop("M1"),
                ),
                actions=(ProposedAction(intent=_FIRST_ROOM),),
            )
        return PlannerOutput(
            plan=ActionPlan(
                id=f"{goal.goal_id}-plan-{ordinal}",
                goal_id=goal.goal_id,
                steps=(_step("step-1", action="A2"),),
                created_at=AT,
                rationale="now it is",
            ),
            actions=(ProposedAction(intent=_SECOND_ROOM),),
        )


async def test_each_planner_call_of_a_turn_mints_and_each_minting_is_its_own_write() -> None:
    """§2's ordering is per call, and a turn's two calls take two appends.

    "On **every** ``PlannerOutput`` a planner returns, ``orchestration`` … (b) records
    this call's ``actions``" — so a turn that plans twice mints twice, the goal holds
    both in the order the calls proposed them (§1, oldest first and append-only), and
    the second call's ``A2`` indexes "``GoalBrief.actions`` extended by this call's own
    ``PlannerOutput.actions``" — which on this turn is the first call's action plus this
    one's.

    **Two writes and not one** (§5), because each is all-or-nothing over its own call's
    proposal: merging a turn's calls into one command would make a later call's bad
    proposal discard an earlier call's good one.
    """
    plans = _CountingPlanStore(now=lambda: AT)
    planner = _TwoCall()
    harness = Harness(memory=await _store_holding_the_address(), planner=planner, plans=plans)

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert len(planner.calls) == 2, "ADR-0228 §3's second call, which the hop earned"
    assert outcome.turn is not None
    stored = await plans.get_goal(outcome.turn.goal.goal_id)
    assert stored is not None
    first, second = stored.intended_actions
    assert (first.intent, second.intent) == (_FIRST_ROOM, _SECOND_ROOM), "§1: oldest first"
    assert plans.mintings == 2, "§5: one compare-and-swap per call that minted"
    assert outcome.turn.plan.steps[0].intended_action == second.id, (
        "§4: A2 over the tuple this call's own proposal extended"
    )


class _MintingThenRestating(_TwoCall):
    """Call 1 proposes an element and an action serving it; call 2 restates the element.

    The narrowest shape of #2414: the action's link is legitimate on the call that
    minted it, and ADR-0265 §3 makes it "stale, truthful and harmless" the moment call
    2's revision replaces the element it names.
    """

    async def plan(self, goal: Any, **fields: Any) -> Any:
        """Ask for the hop and mint against ``C1``; on the second call, restate ``C1``."""
        produced = await super().plan(goal, **fields)
        stated = "the booking is for Saturday" if len(self.calls) == 1 else "make it Sunday"
        minting = len(self.calls) == 1
        return produced.model_copy(
            update={
                "understanding": ProposedUnderstanding(
                    retains_outcome=True,
                    constraints=(ProposedElement(text=stated, ground=Ground.INFERRED),),
                ),
                "actions": (ProposedAction(intent=_FIRST_ROOM, serves=("C1",)),) if minting else (),
                # Call 2 selects **no** action, so the only thing that can refuse this
                # turn is the write: a step naming `A2` would be refused by §4 at the
                # loop, on a goal whose second call minted none, and would mask the
                # state this arm exists to pin.
                "plan": produced.plan.model_copy(update={"steps": ()}),
            }
        )


async def test_an_opening_turn_that_mints_then_restates_records_the_action() -> None:
    """ADR-0269 §4 arm 1: #2414's case, turned over — the turn completes and records.

    This arm keeps the shape of the test it replaces — the same two-call fake planner —
    "so that what changed is the verdict and not the case". What forced the old refusal
    was four ratified clauses meeting, and ADR-0269 §1 moves exactly one of them:

    - ADR-0265 §2 resolves call 1's ``serves`` against call 1's own sequence and records
      the action there, and §3 then makes the link stale, truthful and harmless once
      call 2 replaces the element.
    - ADR-0249 §11 defers every write to one end-of-turn site, and §12 makes
      ``save_goal`` the opening write **carrying the whole interpretation chain**, so by
      the append the current revision is call 2's. ADR-0269 §2 leaves both standing:
      no write moves, and the interleave an opening turn cannot have is not manufactured.
    - ADR-0265 §1 refuses a ``save_goal`` carrying an intended action, so on an opening
      turn the minting still **follows** that one write.
    - ADR-0265 §5's third conjunct is now a membership test over **every revision the
      goal holds** (ADR-0269 §1), so the link — an element of this goal's own earlier
      reading of itself — is admitted rather than refused.

    The assertions are §4 arm 1's: the turn completes, the goal holds **one**
    ``IntendedAction``, its ``serves`` names the **call-1** element's ``id`` byte for
    byte, the stored ``interpretation`` carries both calls' revisions, and the plan is
    saved.
    """
    planner = _MintingThenRestating()
    goals = iter([f"goal-{ordinal}" for ordinal in range(1, 60)])
    harness = Harness(
        memory=await _store_holding_the_address(),
        planner=planner,
        loop_id_factory=lambda: next(goals),
    )

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert len(planner.calls) == 2, "both calls ran, and the write took neither of them down"
    assert outcome.turn is not None
    stored = await harness.plans.get_goal("goal-1")
    assert stored is not None
    assert len(stored.interpretation) == 3, "carrying both calls' revisions"

    assert len(stored.intended_actions) == 1, "§5 recorded the one action call 1 proposed"
    [action] = stored.intended_actions
    [call_one] = stored.interpretation[1].constraints
    assert call_one.id is not None, "ADR-0253 §7: orchestration minted it on call 1"
    assert action.serves == (call_one.id,), "byte for byte, the element call 1 proposed"

    [current] = stored.interpretation[-1].constraints
    assert current.id != call_one.id, (
        "ADR-0253 §7 minted the restatement a new id, so the link is stale at the "
        "append — which is exactly the value ADR-0269 §1 admits"
    )

    saved = await harness.plans.get_plan(outcome.turn.plan.id)
    assert saved is not None, "and the turn's plan is saved: nothing of it was rolled back"
