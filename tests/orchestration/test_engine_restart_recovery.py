"""A durably-parked confirmation survives a process restart, end to end (ADR-0052).

Unlike ``test_engine.py`` — which drives the façade over canonical in-memory fakes
— this module wires the façade over the **real** connection-owning durable stores
(:class:`SqlitePlanStore`, :class:`SqliteAuditTrail`) and reopens them against the
*same database files* to simulate a restart. That is the proof #287/#318 need: a
confirmation parked by one engine, whose process then exits, is recovered and
resolved by a second engine reading the same files, and the resolution is itself
durable.

The model-facing loop is still a fake (no network): what is under test is durable
recovery of a parked step, not planning. Everything below the façade that touches
the databases — the runner, the executor, the audit trail — is real.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING
from uuid import uuid4

import structlog.testing

from ai_assistant.core.types import (
    ActionPlan,
    CostBasis,
    DataTier,
    Disposition,
    Idempotency,
    PlanStep,
    Reversibility,
    RiskLevel,
    SkipReason,
    StepStatus,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.orchestration import (
    ComposingStage,
    ConnectionOperations,
    ConversationLifecycle,
    Engine,
    GrantOperations,
    HeldSource,
    MemoryWriteStage,
    ObservationStage,
    QuestionStage,
    StepExecutor,
    StepRunner,
)
from ai_assistant.orchestration.loop import LearningLoop
from ai_assistant.permissions import SqliteAuditTrail
from ai_assistant.permissions.audit import ORIGIN_UNRECORDED
from ai_assistant.planning import SqlitePlanStore
from ai_assistant.testing import (
    FakeActionPolicy,
    FakeConnectionProvisioner,
    FakeContextProvider,
    FakeConversationStore,
    FakeDeferralStore,
    FakeEgressBinder,
    FakeFeedbackProcessor,
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakeMemoryWriter,
    FakeModelProvider,
    FakeObserver,
    FakeSourceGrantStore,
    FakeSourceReadTrail,
    FakeStreamingCompleter,
    FakeToolInvoker,
    FakeToolRegistry,
    FakeTraceRetention,
    FakeTraceSink,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence
    from pathlib import Path

    from ai_assistant.core.types import CurrentContext, FrozenJson, Goal, MemoryRecord

AT = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)


def _composing() -> ComposingStage:
    """The terminal composing stage every engine now takes (ADR-0170 §2).

    Wired to a cooperating fake provider, which is all these tests need: what the
    composed answer *says*, and what the engine does when composing it fails, are
    pinned in ``tests/orchestration/test_composing.py`` and
    ``tests/orchestration/test_engine_composing.py``.
    """
    return ComposingStage(model=FakeModelProvider(), streaming=FakeStreamingCompleter())


def _grant_ids() -> Callable[[], str]:
    """Ids that differ per call, so a second record is never a duplicate."""
    numbers = count(1)
    return lambda: f"grant-{next(numbers)}"


def _grant_operations(sources: Sequence[HeldSource] = ()) -> GrantOperations:
    """The grant collaborator every ``Engine`` needs (ADR-0102 §7).

    Required rather than optional on the façade, like ``questions`` and
    ``observation``: the four grant methods are on the Protocol, so an engine that
    could be built without them is one whose surface is conditionally present. Empty
    ``sources`` is the ordinary deployment — a reader ships disabled, so nothing is
    grantable until one is configured (ADR-0093 §7).
    """
    return GrantOperations(
        store=FakeSourceGrantStore(),
        sources=sources,
        id_factory=_grant_ids(),
        clock=lambda: AT,
    )


def _connection_operations() -> ConnectionOperations:
    """The connection collaborator every ``Engine`` needs (ADR-0151 §10).

    Required rather than optional on the façade, on ``_grant_operations``' reason
    exactly: the five connection methods are on the Protocol, so an engine that
    could be built without them is one whose surface is conditionally present. The
    canonical fake is the subject, so a case that wants a live record, a pending
    one, or a keyring that raises scripts it through the provisioner's own switches
    rather than through a second double.
    """
    return ConnectionOperations(provisioner=FakeConnectionProvisioner())


PATIENT = timedelta(seconds=30)
CAPABILITY = "send_email"
PARAMETERS = {"to": "someone@example.com"}


def _confirmable_tool() -> ToolDefinition:
    """A declaration ``FakeActionPolicy`` confirms: it discloses off-device."""
    return ToolDefinition(
        id="smtp",
        capability=CAPABILITY,
        description="Send an email.",
        risk_level=RiskLevel.LOW,
        reversibility=Reversibility.REVERSIBLE,
        side_effecting=True,
        reads=(),
        writes=(),
        discloses=(DataTier.PERSONAL,),
        cost=ToolCost(basis=CostBasis.FREE),
        idempotency=Idempotency.NATURAL,
    )


#: ADR-0152 §3's two keywords on the one destination-bearing argument, so a runner
#: holding a binder derives a **real** binding for :data:`PARAMETERS` and the
#: recorded ``CONFIRM`` carries an ``egress_binding`` — which is what a legacy row
#: has to have before it can be missing a field of one.
EGRESS_SCHEMA: Mapping[str, FrozenJson] = {
    "type": "object",
    "properties": {
        "to": {"type": "string", "x-egress-destination": "smtp", "x-egress-tier": "personal"}
    },
    "additionalProperties": False,
}

EGRESS_REFERENCE = "conn-0001"
EGRESS_IDENTITY = "work@example.com"
EGRESS_ENDPOINT = "test://endpoint/one"


def _egress_tool() -> ToolDefinition:
    """The confirmable declaration plus the schema that makes it an egress call."""
    return _confirmable_tool().model_copy(update={"parameters_schema": EGRESS_SCHEMA})


def _egress_binder(tool: ToolDefinition) -> FakeEgressBinder:
    """A binder holding ``tool`` against one active connected account."""
    binder = FakeEgressBinder()
    binder.register_egress(
        tool,
        reference=EGRESS_REFERENCE,
        identity=EGRESS_IDENTITY,
        transport_endpoint=EGRESS_ENDPOINT,
    )
    return binder


class _OneStepPlanner:
    """Plans exactly one confirmable step for the goal it is given."""

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
    ) -> ActionPlan:
        step = PlanStep(
            id="step-1", intent="send the note", capability=CAPABILITY, parameters=PARAMETERS
        )
        return ActionPlan(id=f"{goal.id}-plan", goal_id=goal.id, steps=(step,), created_at=AT)


async def _succeeds(parameters: object, *, idempotency_key: str | None) -> None:
    """A tool that does nothing and succeeds."""


def _aclose(close: Callable[[], None]) -> Callable[[], Awaitable[None]]:
    async def _run() -> None:
        close()

    return _run


def _make_engine(
    plans: SqlitePlanStore,
    trail: SqliteAuditTrail,
    conversations: FakeConversationStore,
    *,
    egress: bool = False,
) -> Engine:
    """Wire a façade over the given *real* durable stores (fake loop, real runner).

    ``conversations`` is passed in rather than built here, because these cases stand
    in for a *restart* over the same durable state: a resumption recovers its
    conversation from the binding the parking turn recorded (ADR-0074 §3), so the
    second process has to be looking at the index the first one wrote.
    """
    memory = FakeMemoryStore(now=lambda: AT)
    writer = FakeMemoryWriter(store=memory, policy=FakeMemoryPolicy(), now=lambda: AT)
    deferrals = FakeDeferralStore(now=lambda: AT)
    writes = MemoryWriteStage(writer=writer, deferrals=deferrals)
    loop = LearningLoop(
        context=FakeContextProvider(),
        memory=memory,
        writes=writes,
        planner=_OneStepPlanner(),
        feedback=FakeFeedbackProcessor(),
        now=lambda: AT,
        id_factory=lambda: "g-1",
        registry=FakeToolRegistry(),
    )
    # ``egress`` wires the binding seam and the schema that reaches it, so the
    # recorded CONFIRM carries an ``egress_binding`` (ADR-0152 §1). Off by default:
    # every case above this one is about the *recovery* path rather than the egress
    # one, and a binder they did not ask for would change what their rows hold.
    tool = _egress_tool() if egress else _confirmable_tool()
    # The seam claims through the **same** trail the runner records rulings into
    # (ADR-0192 §9's wiring clause); a second one would refuse every claim.
    invoker = FakeToolInvoker([(tool, _succeeds)], ledger=trail, gate=trail)
    runner = StepRunner(
        plans=plans,
        registry=invoker,
        policy=FakeActionPolicy(),
        trail=trail,
        binder=_egress_binder(tool) if egress else None,
        executor=StepExecutor(plans=plans, registry=invoker, invoker=invoker, now=lambda: AT),
        now=lambda: AT,
        # Unique decision ids, as production does (uuid): a second process must not
        # re-mint the id the first recorded, or the durable trail rejects the
        # resolving decision as a duplicate.
        id_factory=lambda: uuid4().hex,
    )
    return Engine(
        composing=_composing(),
        grant_operations=_grant_operations(),
        connection_operations=_connection_operations(),
        loop=loop,
        runner=runner,
        plans=plans,
        trail=trail,
        spend=trail,
        # ADR-0186 §10's read trail. A fresh one per engine, like the trace
        # fakes above: this module is about a restarted façade recovering a
        # durable park, and no read attempt crosses that restart.
        reads=FakeSourceReadTrail(),
        memory=memory,
        deferrals=deferrals,
        # The narrow deletion seam and its horizon (ADR-0119 §7, §10). This module
        # is about a *restarted* façade recovering a durable park, and nothing here
        # sweeps; a fresh fake per engine is therefore right — the trace store is
        # not part of the durable state the second process re-reads.
        traces=FakeTraceRetention(),
        trace_sink=FakeTraceSink(),
        trace_retention=timedelta(days=365),
        conversations=ConversationLifecycle(
            conversations=conversations,
            memory=memory,
            retention=timedelta(days=30),
            now=lambda: AT,
        ),
        observation=ObservationStage(
            observer=FakeObserver(),
            conversations=conversations,
            memory=memory,
            writes=writes,
            batch_size=20,
            route="anthropic:claude-opus-4-8",
        ),
        questions=QuestionStage(writer=writer, deferrals=deferrals, memory=memory, now=lambda: AT),
        closers=[_aclose(plans.close), _aclose(trail.close)],
    )


async def test_a_parked_confirmation_survives_a_restart_and_resolves_durably(
    tmp_path: Path,
) -> None:
    """ask → park → exit → restart → resume → executed, all against the same files."""
    plans_path = tmp_path / "plans.db"
    audit_path = tmp_path / "audit.db"
    # One conversation index across both "processes": the resumption finds its
    # conversation through the binding the parking turn wrote there (ADR-0074 §3),
    # so a second engine that could not see it would capture nothing.
    conversations = FakeConversationStore(now=lambda: AT)

    # --- first process: park a confirmation, then "exit" (close the connections) ---
    engine1 = _make_engine(
        SqlitePlanStore(path=plans_path), SqliteAuditTrail(path=audit_path), conversations
    )
    parked = await engine1.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.disposition is Disposition.AWAITING_CONFIRMATION
    execution_id = parked.step.state.id
    await engine1.aclose()  # closes both sqlite connections — the process is gone

    # --- restart: a brand-new engine over the same database files ---
    engine2 = _make_engine(
        SqlitePlanStore(path=plans_path), SqliteAuditTrail(path=audit_path), conversations
    )
    try:
        assert engine2._parked == {}  # nothing carried over in memory
        pending = await engine2.pending_confirmations()
        assert len(pending) == 1
        recovered = pending[0]
        assert recovered.tool_id == "smtp"
        assert dict(recovered.parameters) == PARAMETERS

        resumed = await engine2.resume(recovered.token, approved=True, timeout=PATIENT)
        assert resumed.step is not None
        assert resumed.step.disposition is Disposition.EXECUTED
        assert resumed.turn is None  # recovered resume: no live turn
    finally:
        await engine2.aclose()

    # --- a third reopen proves the resolution was durable, not engine2's memory ---
    plans3 = SqlitePlanStore(path=plans_path)
    try:
        state = await plans3.get_execution(execution_id)
        assert state is not None
        step = state.step("step-1")
        assert step is not None
        assert step.status is StepStatus.SUCCEEDED
        assert await plans3.active_executions() == []  # nothing left parked
    finally:
        plans3.close()


async def test_a_recovered_confirmation_can_be_denied_across_a_restart(tmp_path: Path) -> None:
    """The restart path resolves a refusal too, durably (ADR-0052 §3)."""
    plans_path = tmp_path / "plans.db"
    audit_path = tmp_path / "audit.db"
    # One conversation index across both "processes": the resumption finds its
    # conversation through the binding the parking turn wrote there (ADR-0074 §3),
    # so a second engine that could not see it would capture nothing.
    conversations = FakeConversationStore(now=lambda: AT)

    engine1 = _make_engine(
        SqlitePlanStore(path=plans_path), SqliteAuditTrail(path=audit_path), conversations
    )
    parked = await engine1.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    execution_id = parked.step.state.id
    await engine1.aclose()

    engine2 = _make_engine(
        SqlitePlanStore(path=plans_path), SqliteAuditTrail(path=audit_path), conversations
    )
    try:
        pending = await engine2.pending_confirmations()
        assert len(pending) == 1
        denied = await engine2.resume(pending[0].token, approved=False, timeout=PATIENT)
        assert denied.step is not None
        assert denied.step.disposition is Disposition.DENIED
    finally:
        await engine2.aclose()

    plans3 = SqlitePlanStore(path=plans_path)
    try:
        state = await plans3.get_execution(execution_id)
        assert state is not None
        step = state.step("step-1")
        assert step is not None
        # A refused confirmation resolves the step to SKIPPED/APPROVAL_DENIED.
        assert step.status is StepStatus.SKIPPED
        assert step.skip_reason is SkipReason.APPROVAL_DENIED
    finally:
        plans3.close()


# --- A pre-ADR-0181 row, through the engine that would rebuild its park -------


async def test_a_park_whose_row_predates_the_origin_field_is_not_offered_after_a_restart(
    tmp_path: Path,
) -> None:
    """The pre-ADR-0181 row, end to end over the real durable stores.

    The unit case in ``tests/permissions/test_audit.py`` pins what the trail answers;
    this pins what the **user** can reach, which is the claim that matters. An egress
    confirmation is parked by one process, its audit row is rewritten as a
    pre-ADR-0181 build wrote it — the current encoding minus exactly one key — and a
    second process over the same two database files is asked what is pending.

    **Three things, and they are three different claims.** The enumeration
    *succeeds* rather than raising, which is the damage this branch exists to stop:
    one pre-upgrade row would otherwise make every pending confirmation in the trail
    unanswerable. The park itself is not offered, so no card naming no account and no
    recipient is put to a user — handing the decoded row back would be a *false*
    card, because ADR-0150 §1 rules that an absent binding "means the request is not
    an egress call". And nothing was written: the step is still durably
    ``AWAITING_APPROVAL``, refused rather than resolved and not erased.

    The refusal is *named* rather than an unexplained silence, which the trail's own
    case asserts over the log; here what matters is that a user cannot reach it.

    **Resume is unreachable rather than separately refused**, and that is stronger
    than a refusal at the resume seam. A continuation token exists only where
    ``converse`` minted one in this process or ``pending_confirmations`` minted one
    during recovery; a fresh process has neither, so there is no handle with which to
    ask. Nothing reaches ``resolve``, an ``ALLOW`` or a transmission.
    """
    plans_path = tmp_path / "plans.db"
    audit_path = tmp_path / "audit.db"
    conversations = FakeConversationStore(now=lambda: AT)

    engine1 = _make_engine(
        SqlitePlanStore(path=plans_path),
        SqliteAuditTrail(path=audit_path),
        conversations,
        egress=True,
    )
    parked = await engine1.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.disposition is Disposition.AWAITING_CONFIRMATION
    assert parked.step.confirmation is not None
    assert parked.step.confirmation.egress is not None, "the park really is an egress park"
    execution_id = parked.step.state.id
    await engine1.aclose()

    _downgrade_egress_rows(audit_path)

    engine2 = _make_engine(
        SqlitePlanStore(path=plans_path),
        SqliteAuditTrail(path=audit_path),
        conversations,
        egress=True,
    )
    try:
        with structlog.testing.capture_logs() as captured:
            pending = await engine2.pending_confirmations()

        assert pending == (), "the park is not offered, so no false card reaches a user"
        assert ORIGIN_UNRECORDED in {entry["event"] for entry in captured}, (
            "the refusal is named rather than a silent omission"
        )
    finally:
        await engine2.aclose()

    plans3 = SqlitePlanStore(path=plans_path)
    try:
        state = await plans3.get_execution(execution_id)
        assert state is not None
        step = state.step("step-1")
        assert step is not None
        assert step.status is StepStatus.AWAITING_APPROVAL, "refused, not resolved, not erased"
    finally:
        plans3.close()


def _downgrade_egress_rows(audit_path: Path) -> None:
    """Rewrite every stored egress binding as a pre-ADR-0181 build wrote it.

    Rewritten from what this build actually stored rather than hand-built, so the
    fixture is the current encoding minus exactly one key — a hand-written row could
    drift into a shape no build ever produced, and would then be testing nothing.
    """
    conn = sqlite3.connect(audit_path)
    try:
        rows = conn.execute("SELECT id, data FROM decisions").fetchall()
        for row_id, data in rows:
            stored = json.loads(str(data))
            binding = stored.get("egress_binding")
            if binding is None:
                continue
            del binding["planned_with_external_content"]
            conn.execute("UPDATE decisions SET data = ? WHERE id = ?", (json.dumps(stored), row_id))
        conn.commit()
    finally:
        conn.close()
