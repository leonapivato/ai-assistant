"""ADR-0228 at the engine: what a revising turn persists, drives and composes.

The engine-shaped half of §13's eighteen — everything decided *above*
:class:`~ai_assistant.orchestration.loop.LearningLoop`: which plan the turn drives,
that every plan it produced is persisted before anything is, that a superseded plan
reaches no machinery at all, and that a persistence failure mid-sequence loses the
turn rather than an act. The loop-shaped half is ``test_loop_revision.py``.

The harness is ``test_engine``'s, because what these cases are about is the real
pipeline: a plan store that refuses an unresolvable ``supersedes``, a step runner
that would run a side effect, and a capacity ceiling that would be spent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import pytest
import structlog
from test_engine import AT, CAPABILITY, PATIENT, Harness, confirmable
from test_engine_read_envelope import _recorder
from test_loop_reads import _record

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    ActionPlan,
    EpisodicMemory,
    MemorySource,
    Placement,
    PlacementReach,
    PlacementSetter,
    PlanStep,
    Provenance,
    ReadAsk,
    ReadKind,
    ReadRequest,
    Role,
    SemanticMemory,
)
from ai_assistant.orchestration.reads import StopReason
from ai_assistant.testing import FakeMemoryStore

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import CurrentContext, Goal, MemoryRecord, ShownFile

#: What the user asks on every case here: a question whose act needs a value only
#: memory holds. One distinctive term, so the turn's own blind belief read reaches
#: the record that *cites* the answer and not the answer itself.
_ASKED: Final = "surveyor"

#: The value the first plan cannot name and the second must carry.
_ADDRESS: Final = "14 Rua da Boavista"


class _DependentPlanner:
    """A planner whose step's parameters are filled from what the read returned.

    ADR-0228's own justification, made mechanical: "a plan whose **step's
    parameters** cannot be filled until something has been read". The first call
    cannot see the address, so it plans **no step** and emits a ``CITATION_HOP``; the
    second call is handed the record the servicing fetched, finds the address in it,
    and plans the step that carries it.

    **It reads the supply and not the iteration** (ADR-0228 §12). What decides its
    behaviour is whether the value is in front of it, which is exactly the judgement
    a real planner makes — not a call ordinal, which no lane may put in a planner's
    input and which this class is never given.
    """

    def __init__(self, *, request: ReadRequest | None = None) -> None:
        self._request = _hop("M1") if request is None else request
        self.calls: list[tuple[MemoryRecord, ...]] = []

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
        files: Sequence[ShownFile] = (),
    ) -> ActionPlan:
        """Plan the step where the supply carries the address, and ask for it where not."""
        ordinal = len(self.calls) + 1
        self.calls.append(tuple(memories))
        seen = next((one for one in memories if _ADDRESS in one.content), None)
        if seen is None:
            return ActionPlan(
                id=f"{goal.id}-plan-{ordinal}",
                goal_id=goal.id,
                steps=(),
                created_at=AT,
                rationale="the address is not in front of me",
                read_request=self._request,
            )
        return ActionPlan(
            id=f"{goal.id}-plan-{ordinal}",
            goal_id=goal.id,
            steps=(
                PlanStep(
                    id="step-1",
                    intent="tell the surveyor where to go",
                    capability=CAPABILITY,
                    parameters={"address": _ADDRESS},
                ),
            ),
            created_at=AT,
            rationale="the address arrived with the read",
        )


class _AlwaysAsking:
    """A planner emitting a request on **every** call, with a step on each plan.

    §13 item 2's subject, and item 12's: the bound stops it at two, and the plan it
    replaced must drive nothing even though that plan names a side-effecting
    capability.
    """

    def __init__(self, *, capability: str = CAPABILITY) -> None:
        self._capability = capability
        self.calls: list[tuple[MemoryRecord, ...]] = []

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
        files: Sequence[ShownFile] = (),
    ) -> ActionPlan:
        """Plan one step and ask for one more read, on every call."""
        ordinal = len(self.calls) + 1
        self.calls.append(tuple(memories))
        return ActionPlan(
            id=f"{goal.id}-plan-{ordinal}",
            goal_id=goal.id,
            steps=(
                PlanStep(
                    id=f"step-{ordinal}",
                    intent=f"act on call {ordinal}",
                    capability=self._capability,
                    parameters={"ordinal": ordinal},
                ),
            ),
            created_at=AT,
            rationale=f"call {ordinal}",
            read_request=_hop("M1"),
        )


def _hop(*labels: str) -> ReadRequest:
    return ReadRequest(asks=(ReadAsk(kind=ReadKind.CITATION_HOP, labels=labels),))


def _belief(record_id: str, content: str, *, evidence: tuple[str, ...] = ()) -> SemanticMemory:
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        provenance=Provenance(
            source=MemorySource.OBSERVED, confidence=0.6, last_updated=AT, evidence=evidence
        ),
    )


def _episode(record_id: str, content: str) -> EpisodicMemory:
    return EpisodicMemory(
        id=record_id,
        content=content,
        occurred_at=AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
    )


async def _store_holding_the_address() -> FakeMemoryStore:
    """A store whose retrieved belief cites the episode carrying the address.

    The belief carries the asked term and the episode does not, so the turn's own
    blind read reaches the citation and only a hop reaches the value — which is what
    makes the second plan's step the *mechanism* rather than a coincidence of
    retrieval.
    """
    memory = FakeMemoryStore(now=lambda: AT)
    await memory.add(
        _belief("belief-1", "the surveyor asked where the flat is", evidence=("episode-1",))
    )
    await memory.add(_episode("episode-1", f"Ada: the flat is at {_ADDRESS}."))
    return memory


def _plans_of(harness: Harness) -> list[ActionPlan]:
    """Every plan the harness's store holds, oldest first by the chain."""
    return list(harness.plans._plans.values())


# --------------------------------------------------------------------------- #
# §13 item 1: a step's parameters are filled from what the read returned       #
# --------------------------------------------------------------------------- #


async def test_a_steps_parameters_are_filled_from_what_the_read_returned() -> None:
    """The milestone's exit shape, and the one test that fails if revision is merely wired.

    ADR-0228's justification is a task-capability claim rather than a retrieval one:
    "a plan whose **step's parameters** cannot be filled until something has been
    read. Today those parameters are fixed before the first read fires, so a turn
    that needs to look something up in order to know *what to do* cannot do it."

    The first plan cannot name the address and emits a request; the servicing returns
    the record; the **second** plan's step carries the value; and that step is the
    one the engine drives. Asserted over the driven step and over the persisted
    plans, because either alone would pass on an implementation that planned twice
    and drove the wrong one.
    """
    planner = _DependentPlanner()
    harness = Harness(memory=await _store_holding_the_address(), planner=planner)

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert len(planner.calls) == 2
    assert not any(_ADDRESS in one.content for one in planner.calls[0]), "not on the first call"
    assert any(_ADDRESS in one.content for one in planner.calls[1]), "and on the second"
    assert outcome.turn is not None
    driven = outcome.turn.plan.steps[0]
    assert driven.parameters["address"] == _ADDRESS
    assert outcome.step is not None
    assert outcome.step.step_id == driven.id, "and it is the step the engine drove"

    first, revision = _plans_of(harness)
    assert revision.supersedes == first.id
    assert first.steps == (), "the plan that could not name the value drove nothing"
    assert revision.steps == outcome.turn.plan.steps


# --------------------------------------------------------------------------- #
# §13 item 2: the bound is reached and the reply says so                      #
# --------------------------------------------------------------------------- #


async def test_the_bound_is_reached_and_the_reply_says_so() -> None:
    """§3's bound at the engine, with §10's fact in the assembled prompt.

    A planner that emits a request on every call: exactly two planner calls, both
    emissions serviced, the **second** plan driven, the audit recording **bound
    reached**, and the composing stage given §10's fact — asserted through the
    production renderer over the assembled prompt, per ADR-0227 §7's fidelity rule,
    and not through a fake that cannot fail to carry it.
    """
    composing, model = _recorder()
    planner = _AlwaysAsking()
    harness = Harness(
        memory=await _store_holding_the_address(), planner=planner, composing=composing
    )

    with structlog.testing.capture_logs() as captured:
        outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert len(planner.calls) == 2, "and no third"
    record = _record(captured)
    assert len(record["servicings"]) == 2, "both emissions serviced"
    assert record["stop"] == StopReason.BOUND_REACHED.value
    assert outcome.turn is not None
    assert outcome.turn.plan.steps[0].id == "step-2", "the second plan is the one driven"

    [call] = model.calls
    system = next(one.content for one in call.messages if one.role is Role.SYSTEM)
    assert "stopped before you could" in system
    # §10: the fact carries no label and no query. What it carries *instead* of a
    # count, a duration and a guard name is asserted over the added text itself, at
    # the loop, where the prompt with the fact and the prompt without it can be
    # differenced (``test_loop_revision``).
    assert "M1" not in system, "no label the planner named"


# --------------------------------------------------------------------------- #
# §13 item 9: every plan is persisted and the chain is legible                #
# --------------------------------------------------------------------------- #


async def test_every_plan_is_persisted_and_the_chain_is_legible() -> None:
    """§5, at the site that persists a plan.

    A revising turn persists **two** plans under one ``goal_id``; the second's
    ``supersedes`` is the first's ``id``; the first still carries the
    ``read_request`` that was serviced — which is what keeps ADR-0226 §9's
    minimisation argument true, since "the ask stays durable on the frozen
    ``ActionPlan``" and under iteration the ask that was actually serviced is on the
    plan the turn replaced.

    And the export carries both, at ``schema_version`` 4.
    """
    planner = _DependentPlanner()
    harness = Harness(memory=await _store_holding_the_address(), planner=planner)

    await harness.engine.converse(_ASKED, timeout=PATIENT)

    first, revision = _plans_of(harness)
    assert first.goal_id == revision.goal_id, "one turn, one goal"
    assert first.supersedes is None
    assert revision.supersedes == first.id
    assert first.read_request is not None, "the ask that was serviced stays durable"
    assert revision.id != first.id

    export = await harness.plans.export()
    assert export.schema_version == 5
    assert {plan.id for plan in export.plans} == {first.id, revision.id}


# --------------------------------------------------------------------------- #
# §13 item 12: the superseded plan drives nothing                             #
# --------------------------------------------------------------------------- #


async def test_the_superseded_plan_drives_nothing() -> None:
    """§5's clause, stated because the tempting implementation is a loop.

    "A superseded plan **drives nothing**. It starts no execution, reaches no
    ``StepRunner``, no ``ActionPolicy`` and no ``StepExecutor``, takes no
    step-execution capacity slot, and its steps are never selected, ruled on or run.
    Exactly one plan of a turn is driven and it is the last."

    ADR-0226 §4 states the sibling rule for its own addition for the same reason: a
    new object on the plan path attracts machinery, and here the object *is* a plan,
    so an implementation that iterates will be tempted to drive each plan's first
    step as it goes. That is the plan-driving stage, it is §14's, and it is not
    reached by accident.

    Both plans here name a **side-effecting** capability, so an implementation that
    drove the superseded one would have reached the tool.
    """
    planner = _AlwaysAsking()
    harness = Harness(
        memory=await _store_holding_the_address(),
        planner=planner,
        tools=(confirmable(CAPABILITY),),
    )

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert len(planner.calls) == 2
    executions = await harness.plans.active_executions()
    assert len(executions) <= 1, "one execution at most, and never the superseded plan's"
    first, revision = _plans_of(harness)
    for execution in await harness.plans.active_executions():
        assert execution.plan_id != first.id
    assert outcome.turn is not None
    assert outcome.turn.plan.id == revision.id
    # Keyed on the step id rather than on the tool, because what §5 forbids is the
    # *superseded plan's own step* reaching anything: both plans here name the same
    # side-effecting capability, and only their step ids tell them apart.
    assert all(call.request.step_id != "step-1" for call in harness.invoker.invocations), (
        "the superseded plan's step reached no executor"
    )
    assert all(call.request.parameters.get("ordinal") != 1 for call in harness.invoker.invocations)


# --------------------------------------------------------------------------- #
# §13 item 13: the evaluation and the stamp are taken once over the final supply #
# --------------------------------------------------------------------------- #


async def test_the_externality_stamp_is_taken_once_over_the_turns_final_supply() -> None:
    """§7 and §11, over a turn with two servicings.

    A record carrying the mark that arrives in the **first** servicing sets the value
    the capture records: under §7's monotonicity nothing leaves the supply, so the
    union the last iteration holds is a superset of every earlier one and a stamp
    taken over the final supply covers everything any iteration saw. "**No lane
    recomputes either from an intermediate supply**, and no implementation clears,
    narrows or re-derives a stamp because a later plan was made over different
    material."

    This is the failure ADR-0223's own docstring for ``SelectionOrigin.over`` names
    and this design forecloses: "plan a step over tainted material, re-plan over
    clean material, stamp the binding from the last selection, and watch the fact
    clear." It fails on any implementation that evaluates between iterations.

    **Asserted at capture, and the egress binding carries the same boolean by
    construction** (§11). ADR-0223 §2 has ``Engine._run_turn`` compute the value once,
    above the branch, and hand it to both consumers — the episode's stamp and the
    ``SelectionOrigin`` the runner is given — which "makes them the same boolean
    rather than two that agree", and ADR-0223's own suite is where that division is
    pinned. What iteration changes is *which supply* the one computation runs over,
    and that is what this case is about.
    """
    memory = FakeMemoryStore(now=lambda: AT)
    await memory.add(
        _belief("belief-1", "the surveyor asked where the flat is", evidence=("episode-1",))
    )
    await memory.add(
        EpisodicMemory(
            id="episode-1",
            content=f"Ada: the flat is at {_ADDRESS}.",
            occurred_at=AT,
            provenance=Provenance(
                source=MemorySource.OBSERVED,
                confidence=0.9,
                last_updated=AT,
                derived_from_external=True,
            ),
        )
    )
    planner = _DependentPlanner()
    harness = Harness(memory=memory, planner=planner)

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert len(planner.calls) == 2
    assert outcome.turn is not None
    marked = [
        one.id for one in outcome.turn.memories if one.provenance.derived_from_external is True
    ]
    assert marked == ["episode-1"], "the mark arrived with the first servicing"
    captured = [
        record
        for record in (await memory.list_beliefs(bands=None, kinds=None, limit=50, offset=0))
        if record.id not in {"belief-1", "episode-1"}
    ]
    assert captured, "the turn captured an episode"
    assert all(record.provenance.derived_from_external is True for record in captured), (
        "the stamp is computed once over the final supply, which holds the marked record"
    )


# --------------------------------------------------------------------------- #
# §13 item 18: a save_plan that raises mid-sequence loses the turn, not an act #
# --------------------------------------------------------------------------- #


class _FailingSecondSave:
    """A ``PlanStore`` façade whose **second** ``save_plan`` of a turn raises.

    Wrapped rather than subclassed so every other method is the canonical fake's, and
    keyed on the call count rather than on the plan's contents so the arm is about
    the *order* of persistence against driving rather than about which plan failed.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.saved: list[str] = []

    async def save_plan(self, plan: ActionPlan) -> str:
        """Persist the first plan of the turn and raise on the second."""
        self.saved.append(plan.id)
        if len(self.saved) >= 2:
            msg = "the plan store is down"
            raise PlanningError(msg)
        saved: str = await self._inner.save_plan(plan)
        return saved

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


async def test_a_save_plan_that_raises_mid_sequence_loses_the_turn_and_not_an_act() -> None:
    """§5's ordering clause, asserted at the engine rather than at the store.

    "The whole sequence of ``save_plan`` calls precedes ``start_execution``, so a turn
    whose second ``save_plan`` raises has driven nothing: no execution is open, no
    capacity slot is spent on a step and no side effect has been reached."

    What this is about is the **order** of persistence against driving: "an
    implementation that wrote each plan as it was produced and drove between them
    would pass §13's eleventh test and fail this one". The naive extension writes
    each plan as it is produced, which would put a ``save_plan`` failure *after* a
    step had run — and the failure a persistence error should produce is a turn that
    decided and recorded nothing, not one that acted and then lost the record of why.

    And §9's record is still emitted exactly once: it comes from ``respond``'s
    ``finally`` and is conditioned on nothing.
    """
    planner = _AlwaysAsking()
    harness = Harness(
        memory=await _store_holding_the_address(),
        planner=planner,
        tools=(confirmable(CAPABILITY),),
    )
    failing = _FailingSecondSave(harness.plans)
    harness.engine._plans = failing

    with (
        structlog.testing.capture_logs() as captured,
        pytest.raises(PlanningError, match="the plan store is down"),
    ):
        await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert len(failing.saved) == 2, "the second save was attempted"
    assert len(_plans_of(harness)) == 1, "the store holds the predecessor and no successor"
    assert await harness.plans.active_executions() == [], "no execution was opened"
    assert harness.invoker.invocations == [], "no step ran"
    assert len(harness.engine._reserved) == 0, "no capacity slot is still spent"
    assert _record(captured)["stop"] == StopReason.BOUND_REACHED.value, "one record, emitted once"


async def test_a_withheld_record_arriving_in_the_first_servicing_sets_the_captured_value() -> None:
    """§13 item 13's first half: ADR-0204 §2's evaluation over the **final** supply.

    On a bounded-audience operation the filter subtracts nothing (ADR-0204 §4) but the
    evaluation is still made, once, and the boolean it records travels to capture. §7
    moves *which* servicing "after servicing" names: a record ADR-0199 §3 would
    withhold that arrives in the **first** servicing is in the turn's final supply, so
    the value the capture records is ``True``.

    "This fails on any implementation that evaluates between iterations" — one that
    took the evaluation after the first servicing and then re-took it, or took it
    before the second, would record a value about a supply the turn did not compose
    over.
    """
    memory = FakeMemoryStore(now=lambda: AT)
    await memory.add(
        _belief("belief-1", "the surveyor asked where the flat is", evidence=("episode-1",))
    )
    await memory.add(
        EpisodicMemory(
            id="episode-1",
            content=f"Ada: the flat is at {_ADDRESS}.",
            occurred_at=AT,
            # ADR-0199 §3 withholds an owner-only record from a channel of unbounded
            # audience; on this operation nothing is subtracted, and the evaluation
            # is what capture stamps (ADR-0204 §2, §4).
            placement=Placement(
                reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=AT
            ),
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
        )
    )
    planner = _DependentPlanner()
    harness = Harness(memory=memory, planner=planner)

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert len(planner.calls) == 2, "the withheld record arrived with the first servicing"
    assert outcome.turn is not None
    assert "episode-1" in {one.id for one in outcome.turn.memories}, "and nothing was subtracted"
    captured = [
        record
        for record in await memory.list_beliefs(bands=None, kinds=None, limit=50, offset=0)
        if record.id not in {"belief-1", "episode-1"}
    ]
    assert captured, "the turn captured an episode"
    # ADR-0217 §1 moved the mark onto `placement`: capture writes reach OWNER, set by
    # DERIVED, exactly where ADR-0204 §2's evaluation came back true.
    assert all(record.placement.reach is PlacementReach.OWNER for record in captured), (
        "the evaluation is taken once, over the final supply"
    )
