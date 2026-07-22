"""The executor's half of the tool-invocation contract (ADR-0029 §8, §10).

The `tools/` lane pinned everything observable *at the seam*. What is here is
everything that can only be observed through an executor: what reaches durable
state, what does not get re-driven, and what happens when a cancellation lands
between the tool and the commit.

Every collaborator is a canonical fake from ``ai_assistant.testing``, so nothing
here imports `tools/` — which is exactly what the subject under test is required
to do (CLAUDE.md golden rule 1).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

import pytest

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.protocols import ToolInvoker, ToolRegistry
from ai_assistant.core.types import (
    ActionPlan,
    ActionRequest,
    CostBasis,
    Goal,
    Idempotency,
    MemorySource,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    PlanStep,
    Provenance,
    Reversibility,
    RiskLevel,
    StepExecution,
    StepStatus,
    ToolCall,
    ToolCost,
    ToolDefinition,
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
)
from ai_assistant.orchestration import StepExecutor
from ai_assistant.testing import FakePlanStore, FakeToolInvoker

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import ExecutionState, FrozenJson, StepTransition


class InvocableRegistry(ToolRegistry, ToolInvoker, Protocol):
    """Both faces over one binding, as ADR-0029 §8 requires of the wiring."""


#: A fixed instant, so nothing here depends on how fast the suite runs.
AT = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)

#: Long enough that a prompt tool finishes inside it on any machine the gate
#: runs on; short enough that the tests which *want* an expiry are quick.
PATIENT = timedelta(seconds=30)
BRIEF = timedelta(milliseconds=20)

STEP = "step-1"


# --- builders -----------------------------------------------------------


def tool(tool_id: str = "smtp", **overrides: object) -> ToolDefinition:
    """A side-effecting, non-``NATURAL`` declaration: the ``INDETERMINATE`` branch.

    That base is deliberate — a test wanting the ``FAILED`` half of ADR-0029 §4
    has to say so, rather than getting it by forgetting.
    """
    fields: dict[str, object] = {
        "id": tool_id,
        "capability": "send_email",
        "description": "Send an email.",
        "risk_level": RiskLevel.HIGH,
        "reversibility": Reversibility.IRREVERSIBLE,
        "side_effecting": True,
        "reads": (),
        "writes": (),
        "discloses": (),
        "cost": ToolCost(basis=CostBasis.FREE),
        "idempotency": Idempotency.NONE,
    }
    fields.update(overrides)
    return ToolDefinition(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def read_only(tool_id: str = "inbox") -> ToolDefinition:
    """A tool with no side effect: ADR-0029 §4's ``FAILED`` branch."""
    return tool(
        tool_id,
        capability="read_email",
        side_effecting=False,
        reversibility=Reversibility.REVERSIBLE,
    )


def natural(tool_id: str = "upsert") -> ToolDefinition:
    """A side-effecting tool idempotent by nature: also ``FAILED``."""
    return tool(tool_id, idempotency=Idempotency.NATURAL)


def keyed(tool_id: str = "smtp", window: timedelta = timedelta(hours=1)) -> ToolDefinition:
    """A tool whose repeats are deduplicated by key inside ``window``."""
    return tool(tool_id, idempotency=Idempotency.KEYED, idempotency_window=window)


def call_for(definition: ToolDefinition, *, decision_id: str = "d-1") -> ToolCall:
    """Build an authorised call, through the path the contract asks callers to use."""
    request = ActionRequest(tool=definition, parameters={"to": "someone@example.com"}, step_id=STEP)
    decision = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="because the user said so"),
        id=decision_id,
        decided_at=AT,
    )
    return ToolCall(request=request, decision=decision)


async def a_claimed_execution(
    store: FakePlanStore, capability: str = "send_email"
) -> ExecutionState:
    """Store a goal, a one-step plan, and open an execution for it."""
    goal = Goal(
        id="g-1",
        statement="send the note",
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT),
        created_at=AT,
    )
    await store.save_goal(goal)
    plan = ActionPlan(
        id="p-1",
        goal_id=goal.id,
        steps=(PlanStep(id=STEP, intent="send the note", capability=capability),),
        created_at=AT,
    )
    await store.save_plan(plan)
    return await store.start_execution(plan.id)


async def stored_step(store: FakePlanStore, state: ExecutionState) -> StepExecution:
    """Read the one step back out of durable state."""
    reloaded = await store.get_execution(state.id)
    assert reloaded is not None
    step = reloaded.step(STEP)
    assert step is not None
    return step


# --- tool implementations -----------------------------------------------


class Spy:
    """A tool that records what it was handed and returns a configured output."""

    def __init__(self, output: FrozenJson = None) -> None:
        """Return ``output`` on every call."""
        self.calls: list[tuple[dict[str, FrozenJson], str | None]] = []
        self._output = output

    async def __call__(
        self, parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> FrozenJson:
        """Record the arguments and return the configured output."""
        self.calls.append((dict(parameters), idempotency_key))
        return self._output


class Raiser:
    """A tool that raises, which the seam turns into an ``INTERNAL`` result."""

    def __init__(self) -> None:
        """Count the calls, so "never re-driven" is assertable."""
        self.calls = 0

    async def __call__(
        self, parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> FrozenJson:
        """Fail the way a broken integration does."""
        self.calls += 1
        msg = "the integration is broken"
        raise RuntimeError(msg)


class Blocking:
    """A tool that reports it has started and then never finishes."""

    def __init__(self) -> None:
        """Create the event that reports the callable has been entered."""
        self.entered = asyncio.Event()
        self.calls = 0

    async def __call__(
        self, parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> FrozenJson:
        """Signal entry, then wait to be cancelled or to outrun the deadline."""
        self.calls += 1
        self.entered.set()
        await asyncio.Event().wait()
        return None


class Mutating(Blocking):
    """A blocking tool that flips its *caller's* declaration to read-only.

    The mutation ADR-0029 §4 warns about: the seam's checks all ran before the
    callable started, so a declaration edited now is re-examined by nothing. An
    executor classifying from ``call.request.tool`` would record a possible side
    effect as certainly-nothing-happened.
    """

    def __init__(self, call: ToolCall) -> None:
        """Mutate ``call``'s declaration once the tool has been reached."""
        super().__init__()
        self._call = call

    async def __call__(
        self, parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> FrozenJson:
        """Tamper past ``frozen=True``, then block."""
        object.__setattr__(self._call.request.tool, "side_effecting", False)
        object.__setattr__(self._call.request.tool, "idempotency", Idempotency.NATURAL)
        return await super().__call__(parameters, idempotency_key=idempotency_key)


# --- doubles the executor is driven against -----------------------------


class HoldingPlanStore(FakePlanStore):
    """A ``FakePlanStore`` a test can hold mid-commit.

    Only the *terminal* transition is held: the claim has to land, since the
    whole point is what happens to the write that comes after the tool.
    """

    def __init__(self, *, rejects: bool = False, hold_claim: bool = False) -> None:
        """Create a store whose commit waits to be released.

        Args:
            rejects: Whether the released commit then fails, as a stale-version
                rejection would.
            hold_claim: Hold the ``→ RUNNING`` claim instead of the closing
                write. The claim is the write that lands *before* the tool is
                reachable, so it is a different hazard and needs its own arm.
        """
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self._rejects = rejects
        self._hold_claim = hold_claim

    async def commit_transition(self, transition: StepTransition) -> ExecutionState:
        """Hold the transition this store was built to hold."""
        if (transition.to_status is StepStatus.RUNNING) is self._hold_claim:
            self.entered.set()
            await self.release.wait()
            if self._rejects:
                msg = "the store rejected the write"
                raise PlanningError(msg)
        return await super().commit_transition(transition)


class TickingClock:
    """A clock that advances by a fixed step on every reading.

    Advancing rather than frozen, because ADR-0029 §5's window measurement
    treats a zero elapsed duration as lapsed: a frozen clock would decline every
    keyed retry and prove nothing about ordering.
    """

    def __init__(self, tick: timedelta) -> None:
        """Start at :data:`AT` and move ``tick`` per reading."""
        self.now = AT
        self._tick = tick

    def __call__(self) -> datetime:
        """Advance and return the new instant."""
        self.now += self._tick
        return self.now


class SlowClaimPlanStore(FakePlanStore):
    """A store whose ``→ RUNNING`` claim costs measurable time.

    The claim is the one write that happens *before* the first invocation, so a
    slow one is what distinguishes a window measured from the attempt from one
    measured from before the claim.
    """

    def __init__(self, clock: TickingClock, cost: timedelta) -> None:
        """Charge ``cost`` to ``clock`` on each claim."""
        super().__init__()
        # Not `_clock`: `FakePlanStore` already owns that name for its own.
        self._ticking = clock
        self._cost = cost

    async def commit_transition(self, transition: StepTransition) -> ExecutionState:
        """Advance the clock past the claim, then commit it."""
        if transition.to_status is StepStatus.RUNNING:
            self._ticking.now += self._cost
        return await super().commit_transition(transition)


class ScriptedInvoker:
    """A ``ToolRegistry``/``ToolInvoker`` pair returning results a test chose.

    :class:`~ai_assistant.testing.FakeToolInvoker` is the canonical fake and is
    used wherever the seam's own classification is part of what is being
    observed. It cannot, however, produce an arbitrary ``ToolFailureKind``: a
    raising tool is ``INTERNAL`` and an expiry is ``TIMED_OUT``, and for a
    ``KEYED`` side-effecting tool neither reaches ADR-0029 §5's retry algebra —
    ``TIMED_OUT`` on such a tool is ``INDETERMINATE``, which is outside automatic
    retry. So the retry tests script the seam's answers. The executor is the
    subject; the seam's own behaviour is pinned by the shared conformance suite.

    It presents both faces over one declaration, as ADR-0029 §8 requires of the
    composition root.
    """

    def __init__(self, definition: ToolDefinition, results: Sequence[ToolResult]) -> None:
        """Answer with ``results`` in order, repeating the last one."""
        self._definition = definition
        self._results = list(results)
        self.calls = 0

    async def get(self, tool_id: str) -> ToolDefinition | None:
        """Return the declaration, detached, or ``None``."""
        if tool_id != self._definition.id:
            return None
        return self._definition.model_copy(deep=True)

    async def find(self, capability: str) -> list[ToolDefinition]:
        """Return the declaration when it advertises ``capability``."""
        return [self._definition] if self._definition.capability == capability else []

    async def capabilities(self) -> tuple[str, ...]:
        """Return the one advertised capability."""
        return (self._definition.capability,)

    async def all_tools(self) -> list[ToolDefinition]:
        """Return the one declaration."""
        return [self._definition]

    async def invoke(self, call: ToolCall, *, timeout: timedelta) -> ToolResult:  # noqa: ASYNC109 — the seam's signature (ADR-0029 §4)
        """Return the next scripted result."""
        del call, timeout  # scripted: this double neither checks nor waits
        self.calls += 1
        return self._results[min(self.calls - 1, len(self._results) - 1)]


def stepping_clock(readings: Iterable[datetime]) -> Clock:
    """A clock handing out ``readings`` in order, repeating the last one."""
    remaining = list(readings)

    def _read() -> datetime:
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return _read


def executor_over(
    store: FakePlanStore, seam: InvocableRegistry, *, now: Clock | None = None
) -> StepExecutor:
    """Wire an executor over one object playing both registry and invoker.

    One object, not two: no Protocol can enforce it, and injecting a registry
    and an invoker that could be rebound independently is the wiring ADR-0016 §7
    calls unrecoverable.
    """
    if now is None:
        return StepExecutor(plans=store, registry=seam, invoker=seam)
    return StepExecutor(plans=store, registry=seam, invoker=seam, now=now)


def unavailable() -> ToolResult:
    """A retryable failure — ADR-0029 §5's first conjunct satisfied."""
    return ToolResult(
        outcome=ToolOutcome.FAILED,
        failure=ToolFailure(kind=ToolFailureKind.UNAVAILABLE, message="the upstream is down"),
    )


def succeeded() -> ToolResult:
    """An ordinary success."""
    return ToolResult(outcome=ToolOutcome.SUCCEEDED, output="ok")


# --- §8: the claim describes the call that ran --------------------------


async def test_the_claim_names_the_tool_and_the_decision_that_authorised_it() -> None:
    """``bound_tool == call.request.tool.id`` and ``approval_ref == call.decision.id``.

    Both are ids in a durable record whose full values live elsewhere; requiring
    the equality is what makes the record a description of the call that actually
    ran (ADR-0029 §8). Asserted while the step is still ``RUNNING``, so it is the
    *claim* that carries them and not some later write.
    """
    store = FakePlanStore()
    state = await a_claimed_execution(store)
    implementation = Blocking()
    seam = FakeToolInvoker([(tool(), implementation)])
    call = call_for(tool(), decision_id="d-99")
    task = asyncio.create_task(
        executor_over(store, seam).execute(state, step_id=STEP, call=call, timeout=PATIENT)
    )

    await implementation.entered.wait()
    claimed = await stored_step(store, state)

    assert claimed.status is StepStatus.RUNNING
    assert claimed.bound_tool == call.request.tool.id
    assert claimed.approval_ref == call.decision.id == "d-99"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# --- §8: a ToolBindingError is FAILED, and is not re-driven -------------


async def test_a_binding_refusal_is_committed_failed_and_not_re_driven() -> None:
    """The one outcome derived from an exception rather than from a result.

    The claim precedes the call, so a seam rejection arrives after the step is
    durably ``RUNNING``. Letting it propagate uncommitted would strand the step
    until recovery, which would then record ``INDETERMINATE`` — "we cannot tell
    whether it acted" — about a call that provably never reached the callable.

    Asserting only that the tool was never reached would leave the *stranding*
    untested, and ``FAILED`` alone is a status ADR-0014 §4 lets a retry leave. So
    this asserts the executor **does not schedule**: one claim, one attempt, and
    the tool never entered.
    """
    store = FakePlanStore()
    state = await a_claimed_execution(store)
    implementation = Spy()
    # Registered under a different id, so the call names an unbound tool.
    seam = FakeToolInvoker([(tool("other"), implementation)])

    final = await executor_over(store, seam).execute(
        state, step_id=STEP, call=call_for(tool()), timeout=PATIENT
    )

    step = await stored_step(store, state)
    assert step.status is StepStatus.FAILED
    assert step.attempts == 1, "a rejected call is not re-claimed"
    assert step.error is not None
    assert step.finished_at is not None
    assert implementation.calls == [], "the callable was never reached"
    assert final.step(STEP) == step


async def test_a_binding_refusal_records_nothing_the_executor_did_not_author() -> None:
    """``StepExecution.error`` is Tier 2 text bound for a log (ADR-0004 §5)."""
    store = FakePlanStore()
    state = await a_claimed_execution(store)
    seam = FakeToolInvoker([(tool("other"), Spy())])

    await executor_over(store, seam).execute(
        state, step_id=STEP, call=call_for(tool()), timeout=PATIENT
    )

    step = await stored_step(store, state)
    assert "someone@example.com" not in str(step.error)


# --- §8: the result mapping is total ------------------------------------


async def test_a_success_is_committed_with_its_output() -> None:
    """``SUCCEEDED`` → ``output`` and ``finished_at``."""
    store = FakePlanStore()
    state = await a_claimed_execution(store)
    seam = FakeToolInvoker([(tool(), Spy({"message_id": "m-1"}))])

    await executor_over(store, seam).execute(
        state, step_id=STEP, call=call_for(tool()), timeout=PATIENT
    )

    step = await stored_step(store, state)
    assert step.status is StepStatus.SUCCEEDED
    assert step.output == {"message_id": "m-1"}
    assert step.finished_at is not None


async def test_a_failure_is_committed_with_its_message() -> None:
    """``FAILED`` → ``error`` and ``finished_at``.

    A raising tool is ``INTERNAL``, which is not retryable, so this also shows
    the loop stopping on the first conjunct of ADR-0029 §5.
    """
    store = FakePlanStore()
    state = await a_claimed_execution(store)
    implementation = Raiser()
    seam = FakeToolInvoker([(tool(), implementation)])

    await executor_over(store, seam).execute(
        state, step_id=STEP, call=call_for(tool()), timeout=PATIENT
    )

    step = await stored_step(store, state)
    assert step.status is StepStatus.FAILED
    assert step.error is not None
    assert step.finished_at is not None
    assert implementation.calls == 1


async def test_a_live_deadline_expiry_reaches_indeterminate() -> None:
    """``RUNNING → INDETERMINATE``, now reachable from an expiry as well as recovery.

    ADR-0014 §4 reserved that transition for a crash found at startup. This is
    the widening of *when* it fires that ADR-0029 §8 records — a live executor,
    a side-effecting non-``NATURAL`` tool, and a deadline that passed.
    """
    store = FakePlanStore()
    state = await a_claimed_execution(store)
    seam = FakeToolInvoker([(tool(), Blocking())])

    await executor_over(store, seam).execute(
        state, step_id=STEP, call=call_for(tool()), timeout=BRIEF
    )

    step = await stored_step(store, state)
    assert step.status is StepStatus.INDETERMINATE
    assert step.finished_at is not None
    assert step.attempts == 1, "an INDETERMINATE outcome is never auto-retried"


async def test_a_read_only_deadline_expiry_reaches_failed() -> None:
    """The other half of the same rule: a read that timed out changed nothing."""
    store = FakePlanStore()
    state = await a_claimed_execution(store, capability="read_email")
    seam = FakeToolInvoker([(read_only(), Blocking())])

    await executor_over(store, seam).execute(
        state, step_id=STEP, call=call_for(read_only()), timeout=BRIEF
    )

    step = await stored_step(store, state)
    assert step.status is StepStatus.FAILED


# --- §4: external cancellation, committed on both branches --------------


@pytest.mark.parametrize(
    ("definition", "expected"),
    [
        (read_only(), StepStatus.FAILED),
        (natural(), StepStatus.FAILED),
        (tool(), StepStatus.INDETERMINATE),
    ],
    ids=["read-only", "natural", "side-effecting"],
)
async def test_a_cancelled_call_is_committed_and_the_cancellation_re_raised(
    definition: ToolDefinition, expected: StepStatus
) -> None:
    """Committing is not swallowing (ADR-0029 §4).

    The write is the executor's own durable bookkeeping and the cancellation
    still propagates, which is what keeps shutdown working. An executor that
    returned normally from a cancellation is the bug that clause is not
    licensing — hence both halves in one test.
    """
    store = FakePlanStore()
    state = await a_claimed_execution(store, capability=definition.capability)
    implementation = Blocking()
    seam = FakeToolInvoker([(definition, implementation)])
    task = asyncio.create_task(
        executor_over(store, seam).execute(
            state, step_id=STEP, call=call_for(definition), timeout=PATIENT
        )
    )

    await implementation.entered.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    step = await stored_step(store, state)
    assert step.status is expected
    assert step.finished_at is not None


async def test_the_transition_lands_before_a_repeat_cancellation_escapes() -> None:
    """The shield **idiom**, not a bare ``await asyncio.shield(...)``.

    ADR-0029 §4 is explicit that shielding the task without absorbing a repeat
    cancellation "looks correct and is not": ``shield`` protects the inner task,
    not the ``await`` of it, so a second ``cancel()`` raises in the executor
    immediately while the commit is still in flight. An executor that re-raised
    there would re-raise *before* the write landed, leaving the step ``RUNNING``
    with no record of the classification it had just computed.

    The assertion that carries this is ``not task.done()`` after the second
    cancellation: against a bare shield the executor is already finished there,
    with the store still holding an uncommitted transition.
    """
    store = HoldingPlanStore()
    state = await a_claimed_execution(store)
    implementation = Blocking()
    seam = FakeToolInvoker([(tool(), implementation)])
    task = asyncio.create_task(
        executor_over(store, seam).execute(
            state, step_id=STEP, call=call_for(tool()), timeout=PATIENT
        )
    )

    await implementation.entered.wait()
    task.cancel()
    await store.entered.wait()

    task.cancel()
    for _ in range(5):
        await asyncio.sleep(0)

    assert not task.done(), "a bare shield re-raises here, before the write lands"

    store.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    step = await stored_step(store, state)
    assert step.status is StepStatus.INDETERMINATE


async def test_a_known_outcome_is_committed_even_when_the_commit_is_cancelled() -> None:
    """The whole write path is cancellation-aware, not just the handler's.

    By the time a terminal transition is written the tool has been reached and
    its outcome is *known*. A cancellation landing on that ``await`` would
    abandon the write and leave the step ``RUNNING``, and recovery would then
    record ``INDETERMINATE`` — "we cannot tell whether it acted" — over an answer
    the executor was holding, discarding a `SUCCEEDED` result's output with it.
    """
    store = HoldingPlanStore()
    state = await a_claimed_execution(store)
    seam = FakeToolInvoker([(tool(), Spy({"message_id": "m-1"}))])
    task = asyncio.create_task(
        executor_over(store, seam).execute(
            state, step_id=STEP, call=call_for(tool()), timeout=PATIENT
        )
    )

    await store.entered.wait()
    task.cancel()
    for _ in range(5):
        await asyncio.sleep(0)

    assert not task.done(), "an unshielded terminal commit is abandoned here"

    store.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    step = await stored_step(store, state)
    assert step.status is StepStatus.SUCCEEDED, "the known outcome still landed"
    assert step.output == {"message_id": "m-1"}


async def test_a_claim_cancelled_before_the_tool_is_closed_not_left_running() -> None:
    """A claim lands *before* the tool is reachable, so it must not stand.

    A durable ``RUNNING`` there is the worst available record: recovery reads it
    as ``INDETERMINATE`` — "we cannot tell whether it acted" — about a call that
    provably never started, which ADR-0029 §8 names as the one thing that state
    must not be used for. Nothing happened, so ``FAILED`` is the honest close.
    """
    store = HoldingPlanStore(hold_claim=True)
    state = await a_claimed_execution(store)
    implementation = Spy()
    seam = FakeToolInvoker([(tool(), implementation)])
    task = asyncio.create_task(
        executor_over(store, seam).execute(
            state, step_id=STEP, call=call_for(tool()), timeout=PATIENT
        )
    )

    await store.entered.wait()
    task.cancel()
    for _ in range(5):
        await asyncio.sleep(0)

    assert not task.done(), "the claim is still in flight and must be resolved"

    store.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    step = await stored_step(store, state)
    assert step.status is StepStatus.FAILED, "not left RUNNING for recovery to misread"
    assert step.finished_at is not None
    assert implementation.calls == [], "the tool was never reached"


async def test_a_cancellation_requested_after_the_claim_still_reaches_the_tool() -> None:
    """There is no gap between the claim and the callable for one to land in.

    A cancellation requested while the executor is *running* — here by the
    injected clock, the last thing called before ``invoke`` — sets the task's
    pending flag rather than raising, and a directly awaited coroutine does not
    suspend. So ``invoke``'s body runs, the seam reaches the callable without an
    await of its own, and the ``CancelledError`` is delivered at the **tool's**
    first suspension: the callable was entered.

    What the executor then sees is an ordinary result, not a cancellation, and
    that is ADR-0031 §2's provenance rule rather than an accident. The seam reads
    a *delta* on ``Task.cancelling()`` captured across the call, so a cancellation
    requested before it was entered is not this call's; the seam rules the
    absorbed error ``INTERNAL`` and returns. The step is therefore committed
    ``FAILED`` — nothing ambiguous is recorded — and the executor's cancellation
    handler is never reached.

    Both halves are pinned because both are load-bearing: the callable *was*
    reached, so ``INDETERMINATE`` would be honest if the handler had run; and in
    this window it does not run at all, so no side-effecting tool acquires a
    false ambiguity here.
    """
    store = FakePlanStore()
    state = await a_claimed_execution(store)
    implementation = Blocking()
    seam = FakeToolInvoker([(tool(), implementation)])

    def cancelling_clock() -> datetime:
        current = asyncio.current_task()
        assert current is not None
        current.cancel()
        return AT

    await executor_over(store, seam, now=cancelling_clock).execute(
        state, step_id=STEP, call=call_for(tool()), timeout=PATIENT
    )

    assert implementation.calls == 1, "the callable was entered before the error landed"
    step = await stored_step(store, state)
    assert step.status is StepStatus.FAILED, "no false ambiguity is recorded in this window"


async def test_a_clock_that_raises_is_a_wiring_bug_and_is_not_swallowed() -> None:
    """A reading and an invocation are different failures (ADR-0034 §2).

    ADR-0029 §5's fail-closed rule is scoped to a *reading* that is not a
    positive elapsed duration. A clock that raises produced none, and ADR-0026 §2
    keeps the invocation outside the guard for exactly that reason — so it is a
    wiring bug, translated at this boundary per ADR-0026 §4 rather than becoming
    a log line and a retry quietly not taken.

    It still leaves no step ``RUNNING``: the raise lands between the claim and
    the callable, so the step is closed ``FAILED`` before the error propagates.
    """
    store = FakePlanStore()
    state = await a_claimed_execution(store)
    implementation = Spy()
    seam = FakeToolInvoker([(tool(), implementation)])

    def unreadable() -> datetime:
        """A clock whose reading the guard refuses: naive, so not localizable."""
        return datetime(2026, 7, 20, 12, 0)  # noqa: DTZ001 — the defect under test

    with pytest.raises(PlanningError):
        await executor_over(store, seam, now=unreadable).execute(
            state, step_id=STEP, call=call_for(tool()), timeout=PATIENT
        )

    assert implementation.calls == [], "the tool was never reached"
    step = await stored_step(store, state)
    assert step.status is StepStatus.FAILED, "not left RUNNING for recovery to misread"
    assert step.finished_at is not None


async def test_a_cancellation_absorbed_while_closing_unstarted_outranks_the_cause() -> None:
    """Absorbing a cancellation is a promise to re-raise it (ADR-0034 §1).

    The pre-invocation close runs while another exception — here a refused clock
    reading — is already on its way out. A cancellation absorbed by that write
    still wins: a teardown the caller cannot observe is worse than a diagnosis it
    loses, and the step lands either way.
    """
    store = HoldingPlanStore()
    state = await a_claimed_execution(store)
    seam = FakeToolInvoker([(tool(), Spy())])

    def unreadable() -> datetime:
        return datetime(2026, 7, 20, 12, 0)  # noqa: DTZ001 — naive, so the guard refuses it

    task = asyncio.create_task(
        executor_over(store, seam, now=unreadable).execute(
            state, step_id=STEP, call=call_for(tool()), timeout=PATIENT
        )
    )

    await store.entered.wait()
    task.cancel()
    for _ in range(5):
        await asyncio.sleep(0)
    store.release.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    step = await stored_step(store, state)
    assert step.status is StepStatus.FAILED


async def test_a_rejected_unstarted_close_is_raised_not_logged_away() -> None:
    """A step left ``RUNNING`` is the state ADR-0034 exists to prevent.

    When the store refuses the close there is nothing further the executor can
    do about the durable record, so the one thing it must not do is report the
    original fault and let the wrong state pass unmentioned: recovery would read
    that ``RUNNING`` as ``INDETERMINATE`` for a callable never reached. The store
    failure is raised, chained to the reason for closing.
    """
    store = HoldingPlanStore(rejects=True)
    state = await a_claimed_execution(store)
    implementation = Spy()
    seam = FakeToolInvoker([(tool(), implementation)])
    store.release.set()

    def unreadable() -> datetime:
        return datetime(2026, 7, 20, 12, 0)  # noqa: DTZ001 — naive, so the guard refuses it

    with pytest.raises(PlanningError, match="rejected") as caught:
        await executor_over(store, seam, now=unreadable).execute(
            state, step_id=STEP, call=call_for(tool()), timeout=PATIENT
        )

    assert isinstance(caught.value.__context__, PlanningError), "the reason for closing is kept"
    assert implementation.calls == []
    step = await stored_step(store, state)
    assert step.status is StepStatus.RUNNING, (
        "the store refused; the caller is told rather than not"
    )


async def test_a_cancelled_reason_survives_a_rejected_unstarted_close() -> None:
    """Where the reason for closing is itself a cancellation, it wins (ADR-0034 §1).

    The second precedence rule — a rejected close beats the reason for closing —
    is scoped by the first. A store fault must not hide a teardown in progress:
    the caller would handle a ``PlanningError`` while the task it belongs to
    quietly kept going.
    """
    store = HoldingPlanStore(rejects=True)
    state = await a_claimed_execution(store)
    implementation = Spy()
    seam = FakeToolInvoker([(tool(), implementation)])
    store.release.set()

    def cancelled_clock() -> datetime:
        """A clock whose own ``BaseException`` the guard lets through (ADR-0026 §2)."""
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await executor_over(store, seam, now=cancelled_clock).execute(
            state, step_id=STEP, call=call_for(tool()), timeout=PATIENT
        )

    assert implementation.calls == []


async def test_a_clock_callables_own_exception_propagates_unwrapped() -> None:
    """ADR-0026 §2: "an exception raised by the clock callable itself propagates".

    The guard covers the reading, not the invocation, so this is not the seam's
    ``PlanningError`` to compose — it keeps its own type and cause. The claimed
    step is still closed, for the same reason as above.
    """
    store = FakePlanStore()
    state = await a_claimed_execution(store)
    implementation = Spy()
    seam = FakeToolInvoker([(tool(), implementation)])

    def exploding() -> datetime:
        msg = "the clock's provider is unreachable"
        raise OSError(msg)

    with pytest.raises(OSError, match="unreachable"):
        await executor_over(store, seam, now=exploding).execute(
            state, step_id=STEP, call=call_for(tool()), timeout=PATIENT
        )

    assert implementation.calls == []
    step = await stored_step(store, state)
    assert step.status is StepStatus.FAILED


async def test_an_absorbed_cancellation_outranks_the_commits_own_failure() -> None:
    """Absorbing a cancellation is a promise to re-raise it.

    A ``PlanningError`` from the write it was protecting must not be what leaves
    instead: the caller's ``except PlanningError`` would handle a store fault
    while the task it belongs to quietly kept running, having had its teardown
    swallowed. The store fault is logged; the cancellation is what propagates.
    """
    store = HoldingPlanStore(rejects=True)
    state = await a_claimed_execution(store)
    seam = FakeToolInvoker([(tool(), Spy({"message_id": "m-1"}))])
    task = asyncio.create_task(
        executor_over(store, seam).execute(
            state, step_id=STEP, call=call_for(tool()), timeout=PATIENT
        )
    )

    await store.entered.wait()
    task.cancel()
    for _ in range(5):
        await asyncio.sleep(0)
    store.release.set()

    with pytest.raises(asyncio.CancelledError):
        await task


async def test_a_commit_failure_with_nothing_absorbed_is_still_a_planning_error() -> None:
    """The rule above is about a *conflict*, not about hiding store faults."""
    store = HoldingPlanStore(rejects=True)
    state = await a_claimed_execution(store)
    seam = FakeToolInvoker([(tool(), Spy())])
    store.release.set()

    with pytest.raises(PlanningError, match="rejected"):
        await executor_over(store, seam).execute(
            state, step_id=STEP, call=call_for(tool()), timeout=PATIENT
        )


async def test_classification_reads_the_trusted_binding_not_the_callers_object() -> None:
    """A declaration mutated *after* invocation begins changes nothing.

    A side-effecting, non-``NATURAL`` invocation whose definition were flipped to
    read-only mid-flight and then classified from would be recorded ``FAILED`` —
    a possible side effect recorded as certainly-nothing-happened, the one
    direction ADR-0014 §4 refuses to guess in.
    """
    store = FakePlanStore()
    state = await a_claimed_execution(store)
    call = call_for(tool())
    implementation = Mutating(call)
    seam = FakeToolInvoker([(tool(), implementation)])
    task = asyncio.create_task(
        executor_over(store, seam).execute(state, step_id=STEP, call=call, timeout=PATIENT)
    )

    await implementation.entered.wait()
    assert call.request.tool.side_effecting is False, "the mutation landed"
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    step = await stored_step(store, state)
    assert step.status is StepStatus.INDETERMINATE


# --- §4: a deadline the seam would refuse never claims the step ---------


@pytest.mark.parametrize("bad", [timedelta(0), timedelta(seconds=-1), None, 5, "30s"])
async def test_a_timeout_the_seam_would_refuse_leaves_no_claim(bad: object) -> None:
    """Checked before the claim, not after it (ADR-0029 §4, §8).

    ``invoke`` refuses a non-positive or non-``timedelta`` deadline before the
    callable is created. The claim precedes the call, so letting that
    ``ValueError`` surface from inside ``invoke`` would leave the step durably
    ``RUNNING``, and recovery would record ``INDETERMINATE`` — "we cannot tell
    whether it acted" — about a call whose coroutine that same guard guarantees
    never existed. Refusing first means no durable state is touched at all.
    """
    store = FakePlanStore()
    state = await a_claimed_execution(store)
    implementation = Spy()
    seam = FakeToolInvoker([(tool(), implementation)])

    with pytest.raises(ValueError, match="timeout"):
        await executor_over(store, seam).execute(
            state,
            step_id=STEP,
            call=call_for(tool()),
            timeout=bad,  # type: ignore[arg-type]  # the annotation is not the enforcement
        )

    step = await stored_step(store, state)
    assert step.status is StepStatus.PENDING, "the step was never claimed"
    assert step.attempts == 0
    assert implementation.calls == []


# --- §5: the executor's half of the idempotency window ------------------


async def test_the_window_is_measured_from_the_first_attempt_not_the_claim() -> None:
    """ADR-0029 §5 measures "since the first attempt of this call".

    A slow ``commit_transition`` is not part of the window: counting it could
    consume a whole one before ``invoke`` was ever reached, and then decline a
    retry of a tool that had been called moments earlier. Here the claim alone
    costs two hours against a one-hour window, and the retry must still happen.
    """
    clock = TickingClock(timedelta(minutes=1))
    store = SlowClaimPlanStore(clock, timedelta(hours=2))
    state = await a_claimed_execution(store)
    seam = ScriptedInvoker(keyed(window=timedelta(hours=1)), [unavailable(), succeeded()])

    await executor_over(store, seam, now=clock).execute(
        state,
        step_id=STEP,
        call=call_for(keyed(window=timedelta(hours=1))),
        timeout=PATIENT,
    )

    assert seam.calls == 2, "the window is measured from the attempt, not from before the claim"
    step = await stored_step(store, state)
    assert step.status is StepStatus.SUCCEEDED


async def test_a_keyed_tool_is_retried_inside_its_window() -> None:
    """Both of ADR-0029 §5's conjuncts hold, so the retry is scheduled."""
    store = FakePlanStore()
    state = await a_claimed_execution(store)
    seam = ScriptedInvoker(keyed(), [unavailable(), succeeded()])
    clock = stepping_clock([AT, AT + timedelta(minutes=1)])

    await executor_over(store, seam, now=clock).execute(
        state, step_id=STEP, call=call_for(keyed()), timeout=PATIENT
    )

    step = await stored_step(store, state)
    assert seam.calls == 2
    assert step.attempts == 2, "a retry re-claims the step, spending an attempt"
    assert step.status is StepStatus.SUCCEEDED


async def test_retrying_stops_once_the_window_has_elapsed() -> None:
    """Past the window "the tool is free to act again" (ADR-0016 §4).

    The retry stops being a retry, so the executor stops retrying — even though
    the failure kind is retryable and every other condition still holds.
    """
    store = FakePlanStore()
    state = await a_claimed_execution(store)
    seam = ScriptedInvoker(keyed(window=timedelta(hours=1)), [unavailable()])
    clock = stepping_clock([AT, AT + timedelta(hours=2)])

    await executor_over(store, seam, now=clock).execute(
        state, step_id=STEP, call=call_for(keyed(window=timedelta(hours=1))), timeout=PATIENT
    )

    step = await stored_step(store, state)
    assert seam.calls == 1
    assert step.attempts == 1
    assert step.status is StepStatus.FAILED


@pytest.mark.parametrize(
    "second",
    [AT, AT - timedelta(seconds=1)],
    ids=["no-elapsed-time", "clock-went-backwards"],
)
async def test_a_reading_that_is_not_a_positive_elapsed_duration_is_lapsed(
    second: datetime,
) -> None:
    """Fail-closed, because ``Clock`` is a wall clock (ADR-0029 §5, ADR-0026 §7).

    Measuring an elapsed duration across a DST transition or an NTP step is a
    contract ``Clock`` does not provide, so any reading that is not a positive
    elapsed duration is treated as *the window has lapsed*. Declining to retry
    costs a recoverable error surfaced to the user; retrying outside a lapsed
    window costs a duplicated side effect. A monotonic clock seam is #171.
    """
    store = FakePlanStore()
    state = await a_claimed_execution(store)
    seam = ScriptedInvoker(keyed(), [unavailable()])
    clock = stepping_clock([AT, second])

    await executor_over(store, seam, now=clock).execute(
        state, step_id=STEP, call=call_for(keyed()), timeout=PATIENT
    )

    assert seam.calls == 1, "an unusable measurement declines the retry"
    step = await stored_step(store, state)
    assert step.attempts == 1


async def test_a_side_effecting_tool_with_no_guarantee_is_never_auto_retried() -> None:
    """An ``Idempotency.NONE`` side-effecting tool, whatever the failure kind."""
    store = FakePlanStore()
    state = await a_claimed_execution(store)
    seam = ScriptedInvoker(tool(), [unavailable(), succeeded()])

    await executor_over(store, seam).execute(
        state, step_id=STEP, call=call_for(tool()), timeout=PATIENT
    )

    assert seam.calls == 1
    step = await stored_step(store, state)
    assert step.status is StepStatus.FAILED


async def test_a_read_only_tool_is_retried_without_consulting_any_clock() -> None:
    """Repeating is safe because the tool is not ``side_effecting``.

    No window is involved, so the measurement that ADR-0029 §5 makes fail-closed
    is not reached at all — which is why a read-only retry does not depend on a
    clock the system does not have.
    """
    store = FakePlanStore()
    state = await a_claimed_execution(store, capability="read_email")
    seam = ScriptedInvoker(read_only(), [unavailable(), succeeded()])

    await executor_over(store, seam).execute(
        state, step_id=STEP, call=call_for(read_only()), timeout=PATIENT
    )

    assert seam.calls == 2
    step = await stored_step(store, state)
    assert step.status is StepStatus.SUCCEEDED


async def test_retrying_stops_at_the_trackers_ceiling() -> None:
    """The retry budget is ADR-0014 §4's, and running out of it ends the loop.

    A failing read-only tool would otherwise be re-driven forever: both of
    ADR-0029 §5's conjuncts keep holding.
    """
    store = FakePlanStore()
    state = await a_claimed_execution(store, capability="read_email")
    seam = ScriptedInvoker(read_only(), [unavailable()])

    await executor_over(store, seam).execute(
        state, step_id=STEP, call=call_for(read_only()), timeout=PATIENT
    )

    step = await stored_step(store, state)
    assert step.attempts == 3, "the ceiling FakePlanStore enforces"
    assert step.status is StepStatus.FAILED
