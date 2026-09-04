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

from ai_assistant.core.errors import ConnectionStoreError, PermissionDeniedError
from ai_assistant.core.types import (
    ActionPlan,
    ActionRequest,
    CostBasis,
    DataTier,
    DiscloserProvenance,
    Disposition,
    EgressBinding,
    Goal,
    Idempotency,
    MemorySource,
    OriginUnrecordedBinding,
    PermissionOutcome,
    PlanStep,
    Provenance,
    ProvisioningState,
    Reversibility,
    RiskLevel,
    SpanCoverage,
    StepStatus,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.orchestration import StepExecutor, StepRunner
from ai_assistant.orchestration.origin import NOTHING_EXTERNAL, SelectionOrigin
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
        PermissionDecision,
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


def _forged(binding: EgressBinding) -> EgressBinding:
    """``binding`` with one occurrence's canonical form replaced by a lie.

    Built by ``model_validate`` over a dumped copy, so the result is a *valid*
    binding carrying a canonical form no canonicaliser would compute from its
    supplied form — which is what a tampered trail row looks like, and what
    ADR-0150 §3 says `core` cannot detect on its own.
    """
    dumped = binding.model_dump()
    for span in dumped["spans"]:
        if span["destination"] is not None:
            span["destination"]["canonical"] = "mallory@example.com"
            break
    return EgressBinding.model_validate(dumped)


class _LeakyTrail(FakeAuditTrail):
    """A trail that remembers the decision it most recently handed out.

    ``FakeAuditTrail.get`` already returns a detached snapshot, so what this keeps
    **is** the object the runner retained — not the trail's own row. That is what
    ADR-0152 §13's rebind limb needs: the mutation has to land on the confirmation
    the stage is holding, while it is holding it, without disturbing what the trail
    stores or the comparison ``record`` makes against it.
    """

    def __init__(self) -> None:
        """A trail that has handed nothing out yet."""
        super().__init__()
        self.handed_out: PermissionDecision | None = None

    async def get(self, decision_id: str) -> PermissionDecision | None:
        """Answer as the fake does, keeping the snapshot the caller now holds."""
        handed = await super().get(decision_id)
        self.handed_out = handed
        return handed


class _TamperedTrail(FakeAuditTrail):
    """A trail that hands back one named decision with its binding forged.

    ADR-0152 §7 makes the forged-canonical case reachable on exactly this path:
    "a decision read back out of the trail carrying a forged occurrence is compared
    against a freshly derived binding, the two are unequal, and ``rebind`` refuses
    before ``resolve`` is reached." A trail row is where such an occurrence can
    exist, so a double is what puts one there — the shape ``SubstitutingTrail`` and
    ``MislabelledTrail`` already take in ``test_runner.py``.

    Only the named id is forged: the write path reads its own record back
    (``StepRunner._recorded``), and a trail that lied about every row would break
    the parking this case depends on.
    """

    def __init__(self) -> None:
        """A trail forging nothing until told which id to forge."""
        super().__init__()
        self.forge: str | None = None

    async def get(self, decision_id: str) -> PermissionDecision | None:
        """Answer with the stored decision, its binding forged where asked."""
        stored = await super().get(decision_id)
        if stored is None or decision_id != self.forge:
            return stored
        binding = stored.egress_binding
        if not isinstance(binding, EgressBinding):
            # ADR-0184 §2 widened the field to a three-member union. The forged
            # occurrence this double exists to plant is a fact about a *current*
            # binding, and nothing here writes the origin-unrecorded shape, so the
            # other two arms are passed through untouched rather than forged.
            return stored
        return stored.model_copy(update={"egress_binding": _forged(binding)})


class _RecordingPolicy(FakeActionPolicy):
    """A policy that keeps every request it was handed, so a case can read it.

    Only ``decide`` is overridden. **The resolving half needs no override**:
    ``FakeActionPolicy`` already records every ``resolve`` call in
    :attr:`resolutions`, and the cases below assert over *that* rather than over
    what reached the trail — because "no resolving decision was recorded" and
    "``resolve`` was never called" are different claims, and ADR-0152 §7 makes the
    refusal happen **before** the second ruling rather than merely instead of
    recording one.
    """

    def __init__(self, **kwargs: object) -> None:
        """Rule as the fake does, remembering what was asked."""
        super().__init__(**kwargs)  # type: ignore[arg-type]  # passthrough for the fake's kwargs
        self.decided: list[ActionRequest] = []

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
        trail: FakeAuditTrail | None = None,
    ) -> None:
        """Wire the stage over canonical fakes and the binder under test."""
        self.plans = plans if plans is not None else FakePlanStore(now=lambda: AT)
        self.policy = policy if policy is not None else _RecordingPolicy()
        self.trail = trail if trail is not None else FakeAuditTrail()
        # The seam claims through the **same** trail the runner records rulings
        # into (ADR-0192 §9's wiring clause); a second one would refuse every claim.
        self.invoker = FakeToolInvoker([(tool, _succeeds)], ledger=self.trail, gate=self.trail)
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
        outcomes.append(
            await harness.runner.run(state, STEP, timeout=PATIENT, origin=NOTHING_EXTERNAL)
        )
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
        held, harness.runner.run(state, STEP, timeout=PATIENT, origin=NOTHING_EXTERNAL)
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
    trail = _LeakyTrail()
    harness = _Harness(tool=tool, binder=watcher, plans=plans, trail=trail)
    state = await _an_execution(harness.plans, _step())
    parked = await harness.runner.run(state, STEP, timeout=PATIENT, origin=NOTHING_EXTERNAL)
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
        # The retained **confirmation tool**, which §13 names beside the parameters:
        # without it, a stage rebuilding from `confirmed.tool` rather than from
        # `bound.tool` passes, because the two stay equal.
        confirmed = trail.handed_out
        assert confirmed is not None
        object.__setattr__(confirmed.tool, "id", "somebody-else")
    resumed = await task

    assert resumed.disposition is Disposition.EXECUTED
    returned = watcher.returned[-1]
    assert returned is not None
    resolved = await harness.trail.get(str(resumed.decision_id))
    assert resolved is not None
    assert resolved.tool == returned.tool
    assert resolved.tool.id == "smtp"
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

    result = await harness.runner.run(state, STEP, timeout=PATIENT, origin=NOTHING_EXTERNAL)

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
    parked = await harness.runner.run(state, STEP, timeout=PATIENT, origin=NOTHING_EXTERNAL)
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
    # Not the same claim as "no decision was recorded": ADR-0152 §7 refuses
    # **before** the second ruling, so a stage that resolved first and then
    # declined to record would satisfy the line above and breach the clause.
    assert harness.policy.resolutions == []
    stored = await _stored(harness.plans, state)
    assert stored.status is StepStatus.AWAITING_APPROVAL


async def test_a_forged_canonical_form_in_the_parked_row_is_refused_before_resolve() -> None:
    """ADR-0150 §12, ADR-0152 §7, §13: the forged-canonical case, through the runner.

    §13 states it in the terms §7 makes reachable — a parked confirmation whose
    binding carries an occurrence whose canonical form is not what the seam's
    canonicaliser computes is refused **before** ``resolve`` is reached, and no
    resolving decision is recorded. Both halves are asserted, because they are
    different claims: a stage that resolved first and then declined to record
    would satisfy the second and breach the first.

    The suite already holds ``rebind`` itself to this (``EgressBinderContract``);
    what is here is the runner obligation, which needs a trail row an occurrence
    can be forged into.
    """
    tool = _tool(egress=True)
    binder = _bound_binder(tool)
    trail = _TamperedTrail()
    harness = _Harness(tool=tool, binder=binder, trail=trail)
    state = await _an_execution(harness.plans, _step())
    parked = await harness.runner.run(state, STEP, timeout=PATIENT, origin=NOTHING_EXTERNAL)
    assert parked.disposition is Disposition.AWAITING_CONFIRMATION
    trail.forge = str(parked.decision_id)

    resumed = await harness.runner.resume(
        parked.state,
        STEP,
        confirmation_id=str(parked.decision_id),
        approved=True,
        timeout=PATIENT,
    )

    assert resumed.disposition is Disposition.EGRESS_UNBINDABLE
    assert harness.policy.resolutions == []
    assert await harness.trail.get("d-2") is None
    assert harness.invoker.invocations == []
    stored = await _stored(harness.plans, state)
    assert stored.status is StepStatus.AWAITING_APPROVAL


async def test_a_store_outage_on_the_resuming_path_propagates_too() -> None:
    """ADR-0152 §9, §13: the outage clause is stated over ``bind`` **and** ``rebind``.

    A stage catching ``ConnectionStoreError`` on ``resume`` alone would pass the
    first-ruling case below while turning a store fault into a refusal at exactly
    the moment a user is waiting on an answer they have already given — and
    ``EGRESS_UNBINDABLE`` there would assert that the call cannot be completed,
    which a transient read failure establishes nothing about.
    """
    tool = _tool(egress=True)
    binder = _bound_binder(tool)
    harness = _Harness(tool=tool, binder=binder)
    state = await _an_execution(harness.plans, _step())
    parked = await harness.runner.run(state, STEP, timeout=PATIENT, origin=NOTHING_EXTERNAL)
    assert parked.disposition is Disposition.AWAITING_CONFIRMATION
    before = await _stored(harness.plans, state)
    binder.fail_next_read()

    with pytest.raises(ConnectionStoreError):
        await harness.runner.resume(
            parked.state,
            STEP,
            confirmation_id=str(parked.decision_id),
            approved=True,
            timeout=PATIENT,
        )

    assert harness.policy.resolutions == []
    assert await harness.trail.get("d-2") is None
    assert harness.invoker.invocations == []
    after = await _stored(harness.plans, state)
    assert after.status is StepStatus.AWAITING_APPROVAL
    assert after.model_dump(mode="json") == before.model_dump(mode="json")


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
        await harness.runner.run(state, STEP, timeout=PATIENT, origin=NOTHING_EXTERNAL)

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

    parked = await harness.runner.run(state, STEP, timeout=PATIENT, origin=NOTHING_EXTERNAL)

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


# --- ADR-0181 §3, §4, §10: the origin, stamped and transcribed ----------------


@pytest.mark.parametrize("selected_external", [True, False])
async def test_the_request_carries_the_origin_the_runner_was_given(
    *, selected_external: bool
) -> None:
    """ADR-0181 §4, §10's second case: stamped onto the carrier, carried to the ruling.

    The stage's whole obligation on the ``bind`` path, asserted where it can be
    seen: the value the caller states reaches the request the policy rules on,
    unchanged, and reaches the *recorded* decision with it (ADR-0148 §6's
    transcription, which this field rides for free because it is a member of the
    binding).

    Both states, and the arguments are byte-identical across the two runs — which
    is what makes the assertion about the caller's value rather than about
    anything the stage could have recovered from the payload. ADR-0181 §4's second
    clause forbids recovering it from an argument's value, its field or its shape,
    and a stage that did would answer the same on both runs.
    """
    tool = _tool(egress=True)
    harness = _Harness(tool=tool, binder=_bound_binder(tool))
    state = await _an_execution(harness.plans, _step())

    parked = await harness.runner.run(
        state,
        STEP,
        timeout=PATIENT,
        # ``coverage`` is held **fixed** across the parametrisation, which is what
        # makes this a case about the boolean alone: ADR-0233 §4's fifth clause
        # forbids reading either axis off the other, and a stage that did would
        # move this value with the one under test.
        origin=SelectionOrigin(
            planned_with_external_content=selected_external,
            coverage=SpanCoverage.NOT_COVERED,
        ),
    )

    assert parked.disposition is Disposition.AWAITING_CONFIRMATION
    policy = harness.policy
    assert isinstance(policy, _RecordingPolicy)
    ruled = policy.decided[0].egress_binding
    assert ruled is not None
    assert ruled.planned_with_external_content is selected_external
    assert parked.decision_id is not None
    recorded = await harness.trail.get(parked.decision_id)
    assert recorded is not None
    assert isinstance(recorded.egress_binding, EgressBinding)
    assert recorded.egress_binding.planned_with_external_content is selected_external


async def test_a_parked_call_planned_over_external_content_resumes_and_executes() -> None:
    """ADR-0181 §10's sixth case: the resume round-trip, end to end.

    The one case that fails an implementation that **re-derived** the field on the
    resuming path rather than transcribing it from ``approved`` (ADR-0181 §3's
    fifth and sixth clauses). Such an implementation passes every other clause of
    §10 and then refuses exactly the call the user was asked about and approved:
    ``rebind`` holds no selection set, so it would answer ``False``, the re-derived
    binding would compare unequal to the parked one, and ADR-0152 §7's equality
    refusal would fire as ``EGRESS_UNBINDABLE``.

    Three things are asserted rather than one, because they are three claims: that
    ``rebind`` transcribed the field, that the re-derived binding compares **equal**
    to the approved one, and that the call reached execution. The runner is given
    no ``origin`` on the resuming path at all — ``resume`` takes none, which is the
    structural half of "not re-derived, not defaulted, not omitted".
    """
    tool = _tool(egress=True)
    binder = _WatchingBinder(_bound_binder(tool))
    harness = _Harness(tool=tool, binder=binder)
    state = await _an_execution(harness.plans, _step())
    parked = await harness.runner.run(
        state,
        STEP,
        timeout=PATIENT,
        origin=SelectionOrigin(
            planned_with_external_content=True, coverage=SpanCoverage.NOT_COVERED
        ),
    )
    assert parked.disposition is Disposition.AWAITING_CONFIRMATION
    assert parked.decision_id is not None
    approved = await harness.trail.get(parked.decision_id)
    assert approved is not None
    assert isinstance(approved.egress_binding, EgressBinding)
    assert approved.egress_binding.planned_with_external_content is True

    resumed = await harness.runner.resume(
        parked.state,
        STEP,
        confirmation_id=str(parked.decision_id),
        approved=True,
        timeout=PATIENT,
    )

    assert resumed.disposition is Disposition.EXECUTED, (
        "a re-derived field would have made the binding compare unequal and refused this"
    )
    rebound = binder.returned[-1]
    assert rebound is not None
    assert rebound.binding.planned_with_external_content is True
    assert rebound.binding == approved.egress_binding
    assert len(harness.invoker.invocations) == 1


class _DowngradingTrail(FakeAuditTrail):
    """A trail that hands back one named decision as a pre-ADR-0181 row would decode.

    What a real :class:`~ai_assistant.permissions.SqliteAuditTrail` does for a row
    written before ADR-0181 §3's ``planned_with_external_content`` (ADR-0184 §5), put
    on the fake because the fake holds **objects rather than bytes** and so cannot be
    seeded with such a row — and because ``record`` now refuses the shape outright
    (§4), which is exactly why the substitution happens on the read.

    Only the named id is downgraded: the write path reads its own record back
    (``StepRunner._recorded``), and a trail that answered this way for every row
    would break the parking the case depends on.
    """

    def __init__(self) -> None:
        """A trail downgrading nothing until told which id to downgrade."""
        super().__init__()
        self.downgrade: str | None = None

    async def get(self, decision_id: str) -> PermissionDecision | None:
        """Answer with the stored decision, its origin dropped where asked."""
        stored = await super().get(decision_id)
        if stored is None or decision_id != self.downgrade:
            return stored
        binding = stored.egress_binding
        if not isinstance(binding, EgressBinding):
            return stored
        return stored.model_copy(
            update={
                "egress_binding": OriginUnrecordedBinding(
                    spans=binding.spans,
                    account=binding.account,
                    transport_endpoint=binding.transport_endpoint,
                )
            }
        )


async def test_resuming_a_confirmation_whose_origin_was_never_recorded_is_refused() -> None:
    """ADR-0184 §8's fourth clause: narrow the union and refuse, before any ruling.

    ``StepRunner.resume`` reaches the recorded ``CONFIRM`` two ways. The restart path
    goes through ``AuditTrail.pending_confirmation``, which never offers such a row —
    so it cannot arrive that way. The in-process path goes through ``_recorded`` →
    ``AuditTrail.get``, which since ADR-0184 §5 returns the row **as history** rather
    than raising, and that is the route this closes.

    Refused by this seam's own existing name, which is what ADR-0184 §5 means by "the
    two callers refuse by their own existing names". Four things are asserted because
    they are four claims: the refusal happened, ``EgressBinder.rebind`` was never
    handed the shape (§8's third clause), the policy was never asked to resolve it —
    so ADR-0184 §7's floor is a *second* lock rather than the only one — and nothing
    was written, so the step is still durably parked and its ``CONFIRM`` unresolved.
    """
    tool = _tool(egress=True)
    binder = _WatchingBinder(_bound_binder(tool))
    trail = _DowngradingTrail()
    harness = _Harness(tool=tool, binder=binder, trail=trail)
    state = await _an_execution(harness.plans, _step())
    parked = await harness.runner.run(state, STEP, timeout=PATIENT, origin=NOTHING_EXTERNAL)
    assert parked.disposition is Disposition.AWAITING_CONFIRMATION
    assert parked.decision_id is not None
    binder.returned.clear()
    trail.downgrade = str(parked.decision_id)

    with pytest.raises(PermissionDeniedError, match="origin was never recorded"):
        await harness.runner.resume(
            parked.state,
            STEP,
            confirmation_id=str(parked.decision_id),
            approved=True,
            timeout=PATIENT,
        )

    assert binder.returned == [], "rebind never receives a binding recording no origin"
    assert harness.policy.resolutions == []
    assert harness.invoker.invocations == []
    assert await harness.trail.get("d-2") is None
    stored = await _stored(harness.plans, state)
    assert stored.status is StepStatus.AWAITING_APPROVAL
