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

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

import pytest

from ai_assistant.core.clock import ClockReadingError
from ai_assistant.core.types import (
    ActionPlan,
    ExecutionState,
    Goal,
    MemoryKind,
    MemoryRecord,
    MemorySource,
    PlanStep,
    Provenance,
    SemanticMemory,
    StepStatus,
    ToolDefinition,
    ToolFailureKind,
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
from ai_assistant.tools.builtin import _MAX_RECALL_LIMIT

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


async def test_current_time_rejects_any_argument() -> None:
    """It takes none; its schema declares additionalProperties: false (ADR-0048 §2)."""
    with pytest.raises(ValueError, match="unexpected argument"):
        await CurrentTime(now=_at)({"timezone": "UTC"}, idempotency_key=None)


async def test_current_time_rejects_a_non_conforming_clock() -> None:
    """A naive reading raises rather than emitting a misleading timestamp (ADR-0026 §2)."""
    naive = CurrentTime(now=lambda: datetime(2026, 7, 23, 12, 0))  # noqa: DTZ001 — the bug under test
    with pytest.raises(ClockReadingError):
        await naive({}, idempotency_key=None)


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


class _SearchRecordingStore(FakeMemoryStore):
    """A store that records every `search` limit, to prove validation runs first.

    The over-cap rejection's whole point is that an out-of-range `limit` never
    reaches the store (#298): a bare `FakeMemoryStore` accepts the huge value
    harmlessly, so a `pytest.raises(ValueError)` alone cannot tell "rejected
    before search" from "searched, then raised". This records the `limit` of
    every `search` call so a test can assert the store was never touched.
    """

    def __init__(self) -> None:
        super().__init__(now=_at)
        self.search_limits: list[int] = []

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
    ) -> list[MemoryRecord]:
        self.search_limits.append(limit)
        return await super().search(query, limit=limit, kinds=kinds)


@pytest.mark.parametrize("over_cap", [_MAX_RECALL_LIMIT + 1, 2_500_000_000_000_000_000])
async def test_recall_memory_rejects_an_over_cap_limit_before_any_search(over_cap: int) -> None:
    """A `limit` above the cap is refused before the store is ever searched (#298)."""
    store = _SearchRecordingStore()
    tool = RecallMemory(store)

    with pytest.raises(ValueError, match="limit"):
        await tool({"query": "x", "limit": over_cap}, idempotency_key=None)

    # The unbounded value from the issue never reaches the store's integer bind:
    # validation raised before any search ran.
    assert store.search_limits == []


async def test_recall_memory_accepts_the_cap_boundary() -> None:
    """`limit` exactly at the cap is in bounds and drives a real search."""
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

    output = await RecallMemory(store)(
        {"query": "wifi", "limit": _MAX_RECALL_LIMIT}, idempotency_key=None
    )

    assert isinstance(output, list)
    assert len(output) == 1
    assert output[0]["id"] == "m-1"


def test_recall_memory_schema_advertises_the_cap() -> None:
    """The advertised schema declares the same maximum the callable enforces."""
    schema = RECALL_MEMORY.parameters_schema
    assert isinstance(schema, Mapping)
    properties = schema["properties"]
    assert isinstance(properties, Mapping)
    limit_schema = properties["limit"]
    assert isinstance(limit_schema, Mapping)

    assert limit_schema["maximum"] == _MAX_RECALL_LIMIT
    assert limit_schema["minimum"] == 1


async def test_recall_memory_rejects_an_unexpected_argument() -> None:
    """A key outside {query, limit} is refused (additionalProperties: false)."""
    tool = RecallMemory(FakeMemoryStore(now=_at))
    with pytest.raises(ValueError, match="unexpected argument"):
        await tool({"query": "x", "surprise": 1}, idempotency_key=None)


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


async def test_an_unexpected_argument_fails_the_step_internally_end_to_end() -> None:
    """A bad argument reaches the seam as INTERNAL, not a silently-ignored success."""
    registry = build_default_registry(memory=FakeMemoryStore(now=_at), now=_at)
    runner, plans = _runner(registry)
    step = PlanStep(
        id="step-1",
        intent="what time is it",
        capability="report_current_time",
        parameters={"timezone": "UTC"},  # the tool takes no arguments
    )
    state = await _execution_for(plans, step)

    disposition = await runner.run(state, "step-1", timeout=PATIENT)

    # The runner did execute; the tool's own outcome is a FAILED/INTERNAL step.
    assert disposition.disposition is Disposition.EXECUTED
    stored = (await plans.get_execution(state.id)).step("step-1")  # type: ignore[union-attr]
    assert stored is not None
    assert stored.status is StepStatus.FAILED
    assert stored.failure is not None
    assert stored.failure.kind is ToolFailureKind.INTERNAL


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
