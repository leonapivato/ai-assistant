"""The first local tools and the default-registry factory (ADR-0048).

Three things are proven here: each tool's callable does what its declaration
says; :func:`build_default_registry` returns a populated one-object
registry+invoker; and — end to end — a plan naming a tool's advertised capability
drives the real ``StepRunner``/``StepExecutor`` through selection, permission and
execution to a ``SUCCEEDED`` step.

The end-to-end test wires the *real* registry against canonical fakes for the
other subsystems (``ai_assistant.testing``), because the point is to exercise the
tool and the pipeline, not to re-test the fakes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ai_assistant.core.types import (
    ActionPlan,
    ExecutionState,
    Goal,
    MemorySource,
    PlanStep,
    Provenance,
    SemanticMemory,
    StepStatus,
    ToolDefinition,
)
from ai_assistant.orchestration import Disposition, StepExecutor, StepRunner
from ai_assistant.testing import FakeActionPolicy, FakeAuditTrail, FakeMemoryStore, FakePlanStore
from ai_assistant.tools import (
    CURRENT_TIME,
    RECALL_MEMORY,
    CurrentTime,
    RecallMemory,
    build_default_registry,
)

#: A fixed instant, so nothing here depends on how fast the suite runs.
AT = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)

#: Long enough that these instant tools finish inside it anywhere.
PATIENT = timedelta(seconds=30)


def _at() -> datetime:
    return AT


# --- the declarations ---------------------------------------------------


def test_the_two_declarations_are_well_formed_and_local() -> None:
    """Both tools are read-only and disclose nothing off-device (ADR-0048 §2)."""
    for definition in (CURRENT_TIME, RECALL_MEMORY):
        assert isinstance(definition, ToolDefinition)
        assert definition.side_effecting is False
        assert definition.discloses == ()  # nothing leaves the device
        assert definition.writes == ()


async def test_build_default_registry_advertises_both_capabilities() -> None:
    """Selection can find each tool by the capability it advertises."""
    registry = build_default_registry(memory=FakeMemoryStore(now=_at), now=_at)

    assert await registry.capabilities() == ("recall_memory", "report_current_time")
    ids = [definition.id for definition in await registry.all_tools()]
    assert ids == ["current_time", "recall_memory"]


# --- current_time -------------------------------------------------------


async def test_current_time_reports_the_injected_clock() -> None:
    """The pure-compute tool returns the clock's instant, ISO-8601, under `utc`."""
    output = await CurrentTime(now=_at)({}, idempotency_key=None)

    assert output == {"utc": AT.isoformat()}


# --- recall_memory ------------------------------------------------------


async def test_recall_memory_returns_matching_records() -> None:
    """The memory-backed tool reads its injected store and returns records as JSON."""
    store = FakeMemoryStore(now=_at)
    await store.add(
        SemanticMemory(
            id="m-1",
            content="the wifi password is on the fridge",
            fact="wifi password location",
            provenance=Provenance(
                source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT
            ),
        )
    )

    output = await RecallMemory(store)({"query": "wifi"}, idempotency_key=None)

    assert isinstance(output, list)
    assert len(output) == 1
    assert output[0]["id"] == "m-1"
    assert output[0]["content"] == "the wifi password is on the fridge"


async def test_recall_memory_returns_nothing_for_an_unmatched_query() -> None:
    """A query nothing matches is an empty list, not an error."""
    output = await RecallMemory(FakeMemoryStore(now=_at))(
        {"query": "nothing here"}, idempotency_key=None
    )

    assert output == []


async def test_recall_memory_rejects_a_missing_query() -> None:
    """A bad argument raises, which the seam classifies INTERNAL (ADR-0029 §3)."""
    with pytest.raises(ValueError, match="query"):
        await RecallMemory(FakeMemoryStore(now=_at))({}, idempotency_key=None)


async def test_recall_memory_rejects_a_non_positive_limit() -> None:
    """`limit` must be a positive integer; a bool is not a count."""
    tool = RecallMemory(FakeMemoryStore(now=_at))
    with pytest.raises(ValueError, match="limit"):
        await tool({"query": "x", "limit": 0}, idempotency_key=None)
    with pytest.raises(ValueError, match="limit"):
        await tool({"query": "x", "limit": True}, idempotency_key=None)


# --- end to end: a plan drives selection -> permission -> execute --------


def _runner(
    registry: object, *, allow_everything: bool = False
) -> tuple[StepRunner, FakePlanStore]:
    """Wire the real StepRunner/StepExecutor over the real registry and fakes.

    The registry is the *same* object as the invoker (ADR-0029 §8): one binding
    selects and acts. The policy allows the tool under test — the default fake
    confirms at ``MEDIUM``, so ``recall_memory`` needs ``confirm_at=None``.
    """
    plans = FakePlanStore(now=_at)
    policy = FakeActionPolicy(confirm_at=None) if allow_everything else FakeActionPolicy()
    runner = StepRunner(
        plans=plans,
        registry=registry,  # type: ignore[arg-type]  # the real InMemoryToolRegistry
        policy=policy,
        trail=FakeAuditTrail(),
        executor=StepExecutor(plans=plans, registry=registry, invoker=registry, now=_at),  # type: ignore[arg-type]
        now=_at,
        id_factory=iter(f"d-{n}" for n in range(1, 100)).__next__,
    )
    return runner, plans


async def _execution_for(plans: FakePlanStore, step: PlanStep) -> ExecutionState:
    """Store a goal and a one-step plan, and open an execution for it."""
    goal = Goal(
        id="g-1",
        statement="do the thing",
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT),
        created_at=AT,
    )
    await plans.save_goal(goal)
    plan = ActionPlan(id="p-1", goal_id=goal.id, steps=(step,), created_at=AT)
    await plans.save_plan(plan)
    return await plans.start_execution(plan.id)


async def test_a_plan_naming_report_current_time_executes_end_to_end() -> None:
    """The capability the tool advertises drives selection -> execute (ADR-0048)."""
    registry = build_default_registry(memory=FakeMemoryStore(now=_at), now=_at)
    runner, plans = _runner(registry)  # LOW risk: the default policy allows it
    step = PlanStep(id="step-1", intent="what time is it", capability="report_current_time")
    state = await _execution_for(plans, step)

    disposition = await runner.run(state, "step-1", timeout=PATIENT)

    assert disposition.disposition is Disposition.EXECUTED
    assert disposition.tool_id == "current_time"
    stored = (await plans.get_execution(state.id)).step("step-1")  # type: ignore[union-attr]
    assert stored is not None
    assert stored.status is StepStatus.SUCCEEDED
    assert stored.output == {"utc": AT.isoformat()}


async def test_a_plan_naming_recall_memory_executes_end_to_end() -> None:
    """The injected-dependency tool runs through the pipeline against its store."""
    store = FakeMemoryStore(now=_at)
    await store.add(
        SemanticMemory(
            id="m-1",
            content="the meeting is on tuesday",
            fact="meeting day",
            provenance=Provenance(
                source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT
            ),
        )
    )
    registry = build_default_registry(memory=store, now=_at)
    # MEDIUM risk, so the default fake would confirm; allow it to prove execution.
    runner, plans = _runner(registry, allow_everything=True)
    step = PlanStep(
        id="step-1",
        intent="when is the meeting",
        capability="recall_memory",
        parameters={"query": "meeting"},
    )
    state = await _execution_for(plans, step)

    disposition = await runner.run(state, "step-1", timeout=PATIENT)

    assert disposition.disposition is Disposition.EXECUTED
    assert disposition.tool_id == "recall_memory"
    stored = (await plans.get_execution(state.id)).step("step-1")  # type: ignore[union-attr]
    assert stored is not None
    assert stored.status is StepStatus.SUCCEEDED
    # The seam freezes JSON, so the recorded output is a tuple of frozen mappings.
    assert isinstance(stored.output, tuple)
    assert stored.output[0]["id"] == "m-1"
