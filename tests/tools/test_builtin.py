"""The local tool and the default-registry factory (ADR-0048, ADR-0208).

Three things are proven here: the tool's callable does what its declaration says;
:func:`build_default_registry` returns a populated one-object registry+invoker
advertising ``current_time`` **and no memory capability** (ADR-0208 §1, §6); and —
end to end — a plan naming an advertised capability drives the real
``StepRunner``/``StepExecutor`` through selection, permission and execution to a
``SUCCEEDED`` step, while a plan naming a *memory lookup* reaches
``NO_CAPABLE_TOOL`` instead (ADR-0208 §3, §6).

The end-to-end tests wire the *real* registry against canonical fakes for the
other subsystems (``ai_assistant.testing``), because the point is to exercise the
tool and the pipeline, not to re-test the fakes.

ADR-0208 §6 asks for the registry assertion "for a call with an egress integration
and for one without". The *without* half is here, where the factory's default is;
the *with* half is in ``test_send_email_registration.py``, which owns the
configured branch and the machinery that builds a real integration.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.clock import ClockReadingError
from ai_assistant.core.types import (
    ActionPlan,
    Disposition,
    ExecutionState,
    FrozenJson,
    Goal,
    MemorySource,
    PlanStep,
    Provenance,
    StepStatus,
    ToolDefinition,
)
from ai_assistant.orchestration import (
    StepExecutor,
    StepRunner,
)
from ai_assistant.orchestration.capability_alias import resolve_capability
from ai_assistant.orchestration.origin import NOTHING_EXTERNAL
from ai_assistant.testing import FakeActionPolicy, FakeAuditTrail, FakePlanStore
from ai_assistant.tools import (
    CURRENT_TIME,
    CurrentTime,
    InMemoryToolRegistry,
    build_default_registry,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

#: The capability names the eight deleted alias rows used to serve (ADR-0208 §2),
#: plus the id and capability the tool itself advertised. A plan may still emit any
#: of them; none of them may reach a tool.
MEMORY_SYNONYMS = (
    "recall",
    "recall_memories",
    "recall_memory",
    "search_memory",
    "search_memories",
    "retrieve_memory",
    "memory_recall",
    "memory_search",
    "lookup_memory",
)

#: A fixed instant, so nothing here depends on how fast the suite runs.
AT = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)

#: Long enough that these instant tools finish inside it anywhere.
PATIENT = timedelta(seconds=30)


def _at() -> datetime:
    return AT


# --- the declarations ---------------------------------------------------


def test_the_local_declaration_is_well_formed_and_local() -> None:
    """The surviving local tool is read-only and discloses nothing (ADR-0048 §2)."""
    assert isinstance(CURRENT_TIME, ToolDefinition)
    assert CURRENT_TIME.side_effecting is False
    assert CURRENT_TIME.discloses == ()  # nothing leaves the device
    assert CURRENT_TIME.writes == ()


async def test_build_default_registry_advertises_no_memory_capability() -> None:
    """The unconfigured registry is ``current_time`` and nothing else (ADR-0208 §1, §6).

    Asserted over the registry's *advertised capabilities and its tool ids*, not by
    the absence of an import: ADR-0208 §6 asks for the property a selection stage
    can observe, and a module that imported nothing could still register a memory
    tool built somewhere else. The exhaustive equalities are the strong half — a
    re-added tool under any id or capability fails them — and the synonym sweep
    below states the same fact in the vocabulary #1715 was filed about.

    The configured half of §6 (a call *with* an egress integration) is
    ``test_send_email_registration.py``'s
    ``test_no_memory_capability_is_advertised_with_an_integration_either``.
    """
    registry = build_default_registry(now=_at, ledger=FakeAuditTrail(), gate=FakeAuditTrail())

    capabilities = await registry.capabilities()
    ids = [definition.id for definition in await registry.all_tools()]

    assert capabilities == ("report_current_time",)
    assert ids == ["current_time"]
    for synonym in MEMORY_SYNONYMS:
        assert synonym not in capabilities
        assert synonym not in ids


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


# --- end to end: a plan drives selection -> permission -> execute --------


def _runner(registry: object, trail: FakeAuditTrail) -> tuple[StepRunner, FakePlanStore]:
    """Wire the real StepRunner/StepExecutor over the real registry and fakes.

    The registry is the *same* object as the invoker (ADR-0029 §8): one binding
    selects and acts, under the default fake policy — which is all these cases
    need, because ``current_time`` is ``LOW`` and the memory-lookup case reaches no
    tool to be ruled on at all.

    ``trail`` is the **same object** the registry claims through (ADR-0192 §9's
    wiring clause), so these cases run the production sequence end to end: the
    runner records the ruling, and the seam then claims the authorisation it just
    recorded. A second trail here would refuse every claim.
    """
    plans = FakePlanStore(now=_at)
    runner = StepRunner(
        plans=plans,
        registry=registry,  # type: ignore[arg-type]  # the real InMemoryToolRegistry
        policy=FakeActionPolicy(),
        trail=trail,
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
    trail = FakeAuditTrail()
    registry = build_default_registry(now=_at, ledger=trail, gate=trail)
    runner, plans = _runner(registry, trail)  # LOW risk: the default policy allows it
    step = PlanStep(id="step-1", intent="what time is it", capability="report_current_time")
    state = await _execution_for(plans, step)

    disposition = await runner.run(state, "step-1", timeout=PATIENT, origin=NOTHING_EXTERNAL)

    assert disposition.disposition is Disposition.EXECUTED
    assert disposition.tool_id == "current_time"
    stored = (await plans.get_execution(state.id)).step("step-1")  # type: ignore[union-attr]
    assert stored is not None
    assert stored.status is StepStatus.SUCCEEDED
    assert stored.output == {"utc": AT.isoformat()}


class _CountingCurrentTime:
    """The real ``current_time`` callable, counting the calls that reach it.

    Structurally a ``ToolImplementation``, delegating everything: the point is to
    prove a call did **not** arrive, and an assertion about the step's stored
    status alone cannot tell "never invoked" from "invoked and rolled back".
    """

    def __init__(self) -> None:
        """Wrap a real :class:`CurrentTime` bound to the suite's fixed clock."""
        self._inner = CurrentTime(now=_at)
        self.calls = 0

    async def __call__(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,
    ) -> FrozenJson:
        """Count the call, then do exactly what the real tool does."""
        self.calls += 1
        return await self._inner(parameters, idempotency_key=idempotency_key)


async def test_an_unexpected_argument_never_reaches_the_tool() -> None:
    """An argument the declared schema rejects is refused before the seam (ADR-0145).

    This used to assert the opposite half of the same event: the call ran, the
    tool's hand-written check raised, and the seam classified it ``INTERNAL``.
    ADR-0145 §3 abolished that outcome — "a parameter-schema mismatch never
    reaches a tool's callable and never produces a ``ToolResult``" — so what is
    pinned here now is the refusal and its position, not the failure kind.

    ``current_time`` declares ``additionalProperties: false`` and takes no
    arguments, so ``{"timezone": "UTC"}`` violates its own declaration. The tool
    is genuinely capable of the step's capability, which is what makes this a
    statement about the arguments rather than about selection.
    """
    spy = _CountingCurrentTime()
    trail = FakeAuditTrail()
    registry = InMemoryToolRegistry([(CURRENT_TIME, spy)], ledger=trail, gate=trail)
    runner, plans = _runner(registry, trail)
    step = PlanStep(
        id="step-1",
        intent="what time is it",
        capability="report_current_time",
        parameters={"timezone": "UTC"},  # the tool takes no arguments
    )
    state = await _execution_for(plans, step)

    # The line this test was written expecting to change, now changed: the
    # selection stage turns the refusal into a disposition rather than letting
    # `ActionRequest`'s validator raise out of `run` (#1115, ADR-0145 §4, §7).
    # Everything below it is the durable fact and held under both.
    result = await runner.run(state, "step-1", timeout=PATIENT, origin=NOTHING_EXTERNAL)

    assert result.disposition is Disposition.INVALID_PARAMETERS
    assert spy.calls == 0  # the callable is never reached (ADR-0145 §3)
    stored = (await plans.get_execution(state.id)).step("step-1")  # type: ignore[union-attr]
    assert stored is not None
    assert stored.status is StepStatus.PENDING  # nothing was claimed (§1, §4)
    assert stored.failure is None
    assert stored.output is None


# --- a memory lookup reaches no tool (ADR-0208 §3, §6) -------------------


@pytest.mark.parametrize("emitted", MEMORY_SYNONYMS)
async def test_a_plan_naming_a_memory_lookup_reaches_no_capable_tool(emitted: str) -> None:
    """A lookup-shaped step is skipped, not selected and not parked (ADR-0208 §3).

    Driven through the **real** selection path — the same ``StepRunner`` the two
    cases above use, which resolves the emitted capability through the alias layer
    before it looks for a tool (ADR-0053). That is what makes this the test ADR-0208
    §6 asks for rather than a restatement of the registry assertion: a lane that
    deleted the eight alias rows but left the tool bound would still select it here,
    where a table-shaped assertion alone would pass.

    ``AWAITING_CONFIRMATION`` is called out because it is the outcome #1715 was
    filed about: the owner asked what they take in their coffee, the step parked at
    ``CONFIRM``, and the turn said nothing. Nothing parks now because nothing is
    selected.
    """
    trail = FakeAuditTrail()
    registry = build_default_registry(now=_at, ledger=trail, gate=trail)
    runner, plans = _runner(registry, trail)
    step = PlanStep(id="step-1", intent="what do i take in my coffee", capability=emitted)
    state = await _execution_for(plans, step)

    disposition = await runner.run(state, "step-1", timeout=PATIENT, origin=NOTHING_EXTERNAL)

    assert disposition.disposition is Disposition.NO_CAPABLE_TOOL
    assert disposition.tool_id is None
    # Nothing was ruled on, so there was nothing to park: the trail holds no
    # decision at all, which is the state #1715's `AWAITING_CONFIRMATION` was the
    # absence of. An enum comparison could not say this — the disposition above
    # already excludes that member — and "no decision recorded" is the fact.
    assert await trail.export() == []
    stored = (await plans.get_execution(state.id)).step("step-1")  # type: ignore[union-attr]
    assert stored is not None
    assert stored.status is StepStatus.SKIPPED
    assert stored.output is None


@pytest.mark.parametrize("emitted", MEMORY_SYNONYMS)
async def test_a_memory_synonym_resolves_to_itself_against_the_live_registry(
    emitted: str,
) -> None:
    """ADR-0053's branch 4, over the capabilities the factory actually advertises.

    This is what makes ADR-0208 §2's deletion honest rather than merely tidy: the
    resolver is handed the **live** advertised set — read off the registry the
    composition root builds, not a literal — and every synonym the deleted rows
    served comes back unchanged, so selection reports ``NO_CAPABLE_TOOL`` about the
    name the planner actually emitted (ADR-0037 §1).
    """
    registry = build_default_registry(now=_at, ledger=FakeAuditTrail(), gate=FakeAuditTrail())

    advertised = await registry.capabilities()

    assert resolve_capability(emitted, advertised) == emitted
