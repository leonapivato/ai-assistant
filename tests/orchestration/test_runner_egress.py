"""The runner stage against the egress binding seam (ADR-0152 §10, §13).

ADR-0152 §13 packages the ``orchestration`` consumer into the lane that lands the
Protocol, and these are the obligations it states over *this* side of the seam:
that no non-egress call changed, that the request the policy rules on is built
from what the seam returned rather than from what this stage retained, that a
refusal is ``EGRESS_UNBINDABLE`` and commits nothing, and that a store outage
propagates instead.

Every collaborator is a canonical fake, so nothing here imports `tools/` —
which is the property the subject under test is required to have (golden rule 1).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import ConnectionStoreError
from ai_assistant.core.types import (
    ActionPlan,
    ActionRequest,
    CostBasis,
    DataTier,
    DiscloserProvenance,
    Disposition,
    Goal,
    Idempotency,
    MemorySource,
    PermissionOutcome,
    PlanStep,
    Provenance,
    ProvisioningState,
    Reversibility,
    RiskLevel,
    StepStatus,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.orchestration import StepExecutor, StepRunner
from ai_assistant.testing import (
    FakeActionPolicy,
    FakeAuditTrail,
    FakeEgressBinder,
    FakePlanStore,
    FakeToolInvoker,
)
from ai_assistant.testing.cancellation import held_at_its_first_await

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.protocols import EgressBinder
    from ai_assistant.core.types import (
        BoundEgressCall,
        ExecutionState,
        FrozenJson,
        PermissionRuling,
        StepExecution,
    )

AT = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)
PATIENT = timedelta(seconds=30)
STEP = "step-1"
CAPABILITY = "send_email"
REFERENCE = "conn-0001"
IDENTITY = "work@example.com"
ENDPOINT = "test://endpoint/one"

_SCHEMA: Mapping[str, FrozenJson] = {
    "type": "object",
    "properties": {
        "to": {
            "type": "array",
            "items": {"type": "string"},
            "x-egress-destination": "smtp",
            "x-egress-tier": "personal",
        },
        "body": {"type": "string"},
    },
    "additionalProperties": False,
}


def _tool(
    *, egress: bool, discloses: tuple[DataTier, ...] = (DataTier.PERSONAL,), tool_id: str = "smtp"
) -> ToolDefinition:
    """A declaration with or without an egress schema, disclosing or not.

    ``discloses`` non-empty is what makes ``FakeActionPolicy`` return ``CONFIRM``,
    which is ADR-0148 §8's second clause in miniature — a tool registered at the
    seam must disclose, so no egress send is auto-granted. The ``None`` regression
    pin passes ``()`` instead, because what it compares is an ordinary
    ``EXECUTED`` turn either side of this seam existing.
    """
    return ToolDefinition(
        id=tool_id,
        capability=CAPABILITY,
        description="send a note",
        risk_level=RiskLevel.LOW,
        reversibility=Reversibility.REVERSIBLE,
        side_effecting=True,
        reads=(),
        writes=(),
        discloses=discloses,
        cost=ToolCost(basis=CostBasis.FREE),
        idempotency=Idempotency.NATURAL,
        parameters_schema=_SCHEMA if egress else {"type": "object"},
    )


def _step() -> PlanStep:
    """The one step every case here disposes of."""
    return PlanStep(
        id=STEP,
        intent="send the note",
        capability=CAPABILITY,
        parameters={"to": ["Alice@Example.COM"], "body": "hello"},
    )


async def _succeeds(parameters: object, *, idempotency_key: str | None) -> None:
    """A tool that does nothing and succeeds."""


class _LeakyPlans(FakePlanStore):
    """A store that hands back the plan it holds, so a case can mutate it mid-flight.

    ``PlanStore`` contracts no detached snapshot, so this is a **conforming**
    store: the caller is the one that has to hold its own copy. It is what makes
    ADR-0152 §13's pairing pin reachable — the mutation has to land on the object
    the runner itself retained, not on a copy of it.
    """

    def __init__(self, **kwargs: object) -> None:
        """Remember the plan most recently handed out."""
        super().__init__(**kwargs)  # type: ignore[arg-type]  # passthrough for the fake's kwargs
        self.handed_out: ActionPlan | None = None

    async def get_plan(self, plan_id: str) -> ActionPlan | None:
        """Return the stored plan itself, attached."""
        plan = await super().get_plan(plan_id)
        self.handed_out = plan
        return plan


class _RecordingPolicy(FakeActionPolicy):
    """A policy that keeps every request it was handed, so a case can read it."""

    def __init__(self, **kwargs: object) -> None:
        """Rule as the fake does, remembering what was asked."""
        super().__init__(**kwargs)  # type: ignore[arg-type]  # passthrough for the fake's kwargs
        self.decided: list[ActionRequest] = []
        self.resolved: list[ActionRequest] = []

    async def decide(self, request: ActionRequest) -> PermissionRuling:
        """Keep the request, then rule."""
        self.decided.append(request)
        return await super().decide(request)


class _WatchingBinder:
    """A binder that delegates to a real one and keeps what it handed back.

    Structurally an ``EgressBinder`` and behaviourally the fake it wraps: the
    pairing pin needs the *returned* value to compare the built request against,
    and no seam member reports what it returned twice.
    """

    def __init__(self, inner: FakeEgressBinder) -> None:
        """Wrap ``inner``, recording each answer."""
        self.inner = inner
        self.returned: list[BoundEgressCall | None] = []

    async def bind(self, tool: ToolDefinition, **kwargs: object) -> BoundEgressCall | None:
        """Delegate, keeping the answer."""
        answer = await self.inner.bind(tool, **kwargs)  # type: ignore[arg-type]  # passthrough
        self.returned.append(answer)
        return answer

    async def rebind(self, tool: ToolDefinition, **kwargs: object) -> BoundEgressCall | None:
        """Delegate, keeping the answer."""
        answer = await self.inner.rebind(tool, **kwargs)  # type: ignore[arg-type]  # passthrough
        self.returned.append(answer)
        return answer


class _Harness:
    """A wired ``StepRunner`` and the fakes behind it."""

    def __init__(
        self,
        *,
        tool: ToolDefinition,
        binder: EgressBinder | None,
        plans: FakePlanStore | None = None,
        policy: FakeActionPolicy | None = None,
    ) -> None:
        """Wire the stage over canonical fakes and the binder under test."""
        self.plans = plans if plans is not None else FakePlanStore(now=lambda: AT)
        self.invoker = FakeToolInvoker([(tool, _succeeds)])
        self.policy = policy if policy is not None else _RecordingPolicy()
        self.trail = FakeAuditTrail()
        self.ids = iter(f"d-{n}" for n in range(1, 100))
        self.runner = StepRunner(
            plans=self.plans,
            registry=self.invoker,
            policy=self.policy,
            trail=self.trail,
            executor=StepExecutor(
                plans=self.plans, registry=self.invoker, invoker=self.invoker, now=lambda: AT
            ),
            binder=binder,
            now=lambda: AT,
            id_factory=lambda: next(self.ids),
        )


async def _an_execution(store: FakePlanStore, step: PlanStep) -> ExecutionState:
    """Store a goal, a one-step plan, and open an execution of it."""
    goal = Goal(
        id="g-1",
        statement="send the note",
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT),
        created_at=AT,
    )
    await store.save_goal(goal)
    plan = ActionPlan(id="p-1", goal_id=goal.id, steps=(step,), created_at=AT)
    await store.save_plan(plan)
    return await store.start_execution(plan.id)


async def _stored(store: FakePlanStore, state: ExecutionState) -> StepExecution:
    """The durable record of the one step."""
    reloaded = await store.get_execution(state.id)
    assert reloaded is not None
    found = reloaded.step(STEP)
    assert found is not None
    return found


def _bound_binder(tool: ToolDefinition) -> FakeEgressBinder:
    """A binder holding ``tool`` registered against one active connected account."""
    binder = FakeEgressBinder()
    binder.register_egress(
        tool, reference=REFERENCE, identity=IDENTITY, transport_endpoint=ENDPOINT
    )
    return binder


# --- ADR-0152 §13: the None regression pin -----------------------------------


async def test_a_non_egress_call_produces_the_durable_state_it_did_before_this_seam() -> None:
    """ADR-0152 §8, §13: the ``None`` regression pin, over the durable state itself.

    An existing non-egress call runs the whole runner stage with ``bind``
    returning ``None``, builds a request with ``egress_binding=None``, and
    produces state indistinguishable from the same call **before this seam
    existed** — which the ``binder=None`` runner beside it is. §8's claim that no
    behaviour of any non-egress call changes is demonstrated rather than asserted.
    """
    tool = _tool(egress=False, discloses=())
    binder = FakeEgressBinder()
    binder.register(tool)
    with_seam = _Harness(tool=tool, binder=binder)
    without_seam = _Harness(tool=tool, binder=None)

    outcomes = []
    states = []
    for harness in (with_seam, without_seam):
        state = await _an_execution(harness.plans, _step())
        outcomes.append(await harness.runner.run(state, STEP, timeout=PATIENT))
        states.append(await _stored(harness.plans, state))

    assert [outcome.disposition for outcome in outcomes] == [Disposition.EXECUTED] * 2
    assert states[0].model_dump(mode="json") == states[1].model_dump(mode="json")
    policy = with_seam.policy
    assert isinstance(policy, _RecordingPolicy)
    assert policy.decided[0].egress_binding is None
    assert binder.reads() == ()


# --- ADR-0152 §1, §13: the pairing pin ---------------------------------------


async def test_the_request_is_built_from_what_the_seam_returned_and_not_from_what_was_held() -> (
    None
):
    """ADR-0152 §1, §13: all three fields, with the retained objects diverged.

    The runner's own ``step`` and its selected ``tool`` are rewritten **across the
    seam's awaited connection-record read**, so they are unequal to the copies the
    seam detached before it suspended. Without that divergence the assertion holds
    whichever object the runner used and pins nothing.

    The binding limb is asserted with a **distinguishable** binding, because
    ``egress_binding`` defaults to ``None``: a pin over ``tool`` and ``parameters``
    alone passes a runner that carried the right payload and dropped the binding,
    which would put an apparently non-egress request in front of the policy.
    """
    tool = _tool(egress=True)
    watcher = _WatchingBinder(_bound_binder(tool))
    plans = _LeakyPlans(now=lambda: AT)
    harness = _Harness(tool=tool, binder=watcher, plans=plans)
    state = await _an_execution(harness.plans, _step())
    held = watcher.inner.suspend_next_read()

    async with held_at_its_first_await(
        held, harness.runner.run(state, STEP, timeout=PATIENT)
    ) as task:
        plan = plans.handed_out
        assert plan is not None
        plan.steps[0].__dict__["parameters"] = {"to": ["mallory@example.com"], "body": "swapped"}
    await task

    returned = watcher.returned[0]
    assert returned is not None
    policy = harness.policy
    assert isinstance(policy, _RecordingPolicy)
    request = policy.decided[0]
    assert request.parameters == returned.parameters
    assert request.tool == returned.tool
    assert request.egress_binding == returned.binding
    assert request.egress_binding is not None
    assert request.parameters["body"] == "hello"
    assert [span.destination.canonical for span in request.egress_binding.spans if span.destination]


async def test_the_rebuilt_request_is_built_from_what_rebind_returned() -> None:
    """ADR-0152 §13: the ``rebind`` limb, separately and on the resuming path.

    §7's equality cases do **not** reach this: they compare the derived binding
    against ``approved`` *inside* the seam, and say nothing about which objects the
    request built after the seam returned was built from — so a lane passing every
    one of them can still hand ``ActionPolicy.resolve`` a request the seam never
    described. A pin covering ``bind`` alone leaves the path a second ruling is
    taken on untested.
    """
    tool = _tool(egress=True)
    watcher = _WatchingBinder(_bound_binder(tool))
    plans = _LeakyPlans(now=lambda: AT)
    harness = _Harness(tool=tool, binder=watcher, plans=plans, policy=_RecordingPolicy())
    state = await _an_execution(harness.plans, _step())
    parked = await harness.runner.run(state, STEP, timeout=PATIENT)
    assert parked.disposition is Disposition.AWAITING_CONFIRMATION
    held = watcher.inner.suspend_next_read()

    async with held_at_its_first_await(
        held,
        harness.runner.resume(
            parked.state,
            STEP,
            confirmation_id=str(parked.decision_id),
            approved=True,
            timeout=PATIENT,
        ),
    ) as task:
        plan = plans.handed_out
        assert plan is not None
        plan.steps[0].__dict__["parameters"] = {"to": ["mallory@example.com"], "body": "swapped"}
    resumed = await task

    assert resumed.disposition is Disposition.EXECUTED
    returned = watcher.returned[-1]
    assert returned is not None
    resolved = await harness.trail.get(str(resumed.decision_id))
    assert resolved is not None
    assert resolved.tool == returned.tool
    assert resolved.egress_binding == returned.binding
    assert resolved.egress_binding is not None
    rebuilt = ActionRequest(
        tool=returned.tool,
        parameters=returned.parameters,
        step_id=STEP,
        execution_id=state.id,
        egress_binding=returned.binding,
    )
    assert resolved.authorises(rebuilt)
    assert returned.parameters["body"] == "hello"


# --- ADR-0152 §9, §13: the disposition ---------------------------------------


async def test_a_refused_binding_is_egress_unbindable_and_commits_nothing() -> None:
    """ADR-0152 §9, §13: no ruling, no audit record, no claim, step still ``PENDING``.

    Terminal for the turn that met it and for nothing beyond it, and reported as
    neither ``DENIED`` nor ``INVALID_PARAMETERS`` — ``DENIED`` would be a falsehood
    about the user's own policy, since no decision exists to name.
    """
    tool = _tool(egress=True)
    binder = FakeEgressBinder()
    binder.register_egress(
        tool,
        reference=REFERENCE,
        identity=IDENTITY,
        transport_endpoint=ENDPOINT,
        state=ProvisioningState.PENDING,
    )
    harness = _Harness(tool=tool, binder=binder)
    state = await _an_execution(harness.plans, _step())
    before = await _stored(harness.plans, state)

    result = await harness.runner.run(state, STEP, timeout=PATIENT)

    assert result.disposition is Disposition.EGRESS_UNBINDABLE
    assert result.decision_id is None
    assert await harness.trail.get("d-1") is None
    assert harness.invoker.invocations == []
    after = await _stored(harness.plans, state)
    assert after.status is StepStatus.PENDING
    assert after.model_dump(mode="json") == before.model_dump(mode="json")
    policy = harness.policy
    assert isinstance(policy, _RecordingPolicy)
    assert policy.decided == []


async def test_a_resumed_call_whose_binding_moved_is_refused_before_the_second_ruling() -> None:
    """ADR-0152 §7: refused before ``resolve``, so no resolving decision is recorded.

    ADR-0148 §6's four-way refusal at transmission is unchanged and unrelaxed;
    what changes is that a resumed egress call whose account has moved is refused
    one stage earlier and before a second ruling is recorded.
    """
    tool = _tool(egress=True)
    binder = _bound_binder(tool)
    harness = _Harness(tool=tool, binder=binder)
    state = await _an_execution(harness.plans, _step())
    parked = await harness.runner.run(state, STEP, timeout=PATIENT)
    assert parked.disposition is Disposition.AWAITING_CONFIRMATION
    binder.set_connection(REFERENCE, identity="somebody-else@example.com")

    resumed = await harness.runner.resume(
        parked.state,
        STEP,
        confirmation_id=str(parked.decision_id),
        approved=True,
        timeout=PATIENT,
    )

    assert resumed.disposition is Disposition.EGRESS_UNBINDABLE
    assert await harness.trail.get("d-2") is None
    assert harness.invoker.invocations == []
    stored = await _stored(harness.plans, state)
    assert stored.status is StepStatus.AWAITING_APPROVAL


async def test_a_store_outage_propagates_rather_than_becoming_a_disposition() -> None:
    """ADR-0152 §9, §13: the store-outage case, over the durable state as well.

    A test asserting only that something raised satisfies neither limb, and one
    asserting ``EGRESS_UNBINDABLE`` asserts the behaviour the clause forbids.
    """
    tool = _tool(egress=True)
    binder = _bound_binder(tool)
    harness = _Harness(tool=tool, binder=binder)
    state = await _an_execution(harness.plans, _step())
    before = await _stored(harness.plans, state)
    binder.fail_next_read()

    with pytest.raises(ConnectionStoreError):
        await harness.runner.run(state, STEP, timeout=PATIENT)

    assert await harness.trail.get("d-1") is None
    assert harness.invoker.invocations == []
    after = await _stored(harness.plans, state)
    assert after.status is StepStatus.PENDING
    assert after.model_dump(mode="json") == before.model_dump(mode="json")


async def test_the_recorded_decision_holds_the_binding_the_seam_derived() -> None:
    """ADR-0150 §1 and ADR-0152 §13: what the record holds when the call is *not* refused.

    The counterpart to the refusal cases: a decision embeds the binding verbatim,
    so the destinations and the account the ruling was taken over survive into the
    trail, which is what ADR-0148 §3 binds a standing grant to.
    """
    tool = _tool(egress=True)
    binder = _bound_binder(tool)
    harness = _Harness(tool=tool, binder=binder)
    state = await _an_execution(harness.plans, _step())

    parked = await harness.runner.run(state, STEP, timeout=PATIENT)

    assert parked.decision_id is not None
    recorded = await harness.trail.get(parked.decision_id)
    assert recorded is not None
    assert recorded.ruling.outcome is PermissionOutcome.CONFIRM
    binding = recorded.egress_binding
    assert binding is not None
    assert binding.account.identity == IDENTITY
    assert binding.account.reference == REFERENCE
    assert binding.transport_endpoint == ENDPOINT
    assert [member.canonical for member in binding.canonical_destination_set] == [
        "Alice@example.com"
    ]
    assert {span.provenance for span in binding.spans} == {DiscloserProvenance.SYSTEM_SELECTED}
