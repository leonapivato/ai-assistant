"""ADR-0014 §4's startup scan, carrying ADR-0192 §3's completions.

The scan is the only consumer of ``AuditTrail.open_invocations`` (ADR-0192 §2) and
the only writer of a recovery completion. What is pinned here is everything a
single-claim happy path leaves free: the **ordering** against the step's
transition, the **fields** every completion carries, what a scan interrupted
partway leaves behind, and what an erasure landing under it does.

Every collaborator is a canonical fake from ``ai_assistant.testing`` except where a
case is written **against a persisted payload** — the reservation the paired lane
put inside ``open_invocations``' own store operation — which a fake holding objects
can model but cannot prove. Those cases run over both.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

import pytest
from test_engine import Harness
from test_engine import _composing as composing
from test_engine import _connection_operations as connection_operations
from test_engine import _grant_operations as grant_operations

from ai_assistant.core.errors import AuditError, InvalidCompletionError
from ai_assistant.core.protocols import AuditTrail, InvocationLedger
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
    StepStatus,
    StepTransition,
    ToolCost,
    ToolDefinition,
    ToolFailureKind,
    ToolOutcome,
)
from ai_assistant.orchestration import Engine, RecoveryScan
from ai_assistant.permissions import SqliteAuditTrail
from ai_assistant.planning import SqlitePlanStore
from ai_assistant.testing import FakeAuditTrail, FakeIdentifiers, FakeIdentifierSpace, FakePlanStore

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

    from ai_assistant.core.protocols import InvocationCompleter, PlanStore
    from ai_assistant.core.types import ExecutionState, StepExecution, ToolInvocation


class LedgerTrail(AuditTrail, InvocationLedger, Protocol):
    """Both faces over one object, which is how the composition root wires it.

    ADR-0192 §2 has one store satisfy ``AuditTrail``, ``InvocationLedger`` and
    ``InvocationCompleter``; the canonical fake and the durable store are each that
    one object. A helper here that seeds a claim and then reads it back needs both
    faces, and naming the pair is what keeps the seeding honest rather than
    silenced.
    """


#: A fixed instant, so nothing here depends on how fast the suite runs.
AT = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)

STEP = "step-1"
OTHER_STEP = "step-2"
DECISION = "d-1"

#: The id the claim a dead process left open holds, and the one a new
#: process's factory is scripted to draw next (ADR-0192 §2).
RESERVED = "inv-stale-1"


# --- builders -----------------------------------------------------------


def tool(tool_id: str = "smtp", **overrides: object) -> ToolDefinition:
    """A side-effecting, non-``NATURAL`` declaration: a **spendable** authorisation.

    ADR-0192 §1 refuses a second claim under one of these while a claim is open, so
    a case wanting two open claims has to ask for the read-only one below — which
    is exactly the scoping §9 puts on that case.
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
        "cost": ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("0.01"), currency="USD"),
        "idempotency": Idempotency.NONE,
    }
    fields.update(overrides)
    return ToolDefinition(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def read_only(tool_id: str = "inbox") -> ToolDefinition:
    """A tool with no side effect: the **non-spendable** authorisation of §1."""
    return tool(
        tool_id,
        capability="read_email",
        side_effecting=False,
        reversibility=Reversibility.REVERSIBLE,
    )


def decision_for(
    definition: ToolDefinition,
    *,
    decision_id: str = DECISION,
    step_id: str = STEP,
    execution_id: str,
) -> PermissionDecision:
    """An ``ALLOW`` recorded for one step of one execution."""
    request = ActionRequest(
        tool=definition,
        parameters={"to": "someone@example.com"},
        step_id=step_id,
        execution_id=execution_id,
    )
    return PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="because the user said so"),
        id=decision_id,
        decided_at=AT,
    )


async def an_execution(
    plans: PlanStore, *, capability: str = "send_email", steps: Sequence[str] = (STEP,)
) -> ExecutionState:
    """Store a goal, a plan of ``steps``, and open an execution for it."""
    goal = Goal(
        id="g-1",
        statement="send the note",
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT),
        created_at=AT,
    )
    await plans.save_goal(goal)
    plan = ActionPlan(
        id="p-1",
        goal_id=goal.id,
        steps=tuple(
            PlanStep(id=step_id, intent="send the note", capability=capability) for step_id in steps
        ),
        created_at=AT,
    )
    await plans.save_plan(plan)
    return await plans.start_execution(plan.id)


async def claimed(
    plans: PlanStore,
    state: ExecutionState,
    *,
    step_id: str = STEP,
    decision_id: str = DECISION,
    tool_id: str = "smtp",
) -> ExecutionState:
    """Commit the ``→ RUNNING`` claim an executor would have, and return the state."""
    return await plans.commit_transition(
        StepTransition(
            execution_id=state.id,
            step_id=step_id,
            to_status=StepStatus.RUNNING,
            expected_version=state.version,
            bound_tool=tool_id,
            approval_ref=decision_id,
        )
    )


async def a_running_step(
    plans: PlanStore, trail: LedgerTrail, definition: ToolDefinition, *, claims: int = 1
) -> ExecutionState:
    """One execution, one ``RUNNING`` step, and ``claims`` open claims under it.

    The step is left exactly as a process that died mid-call would have left it: a
    durable ``RUNNING`` naming the decision that authorised it, and a claim in the
    trail with no completion beside it.
    """
    state = await an_execution(plans, capability=definition.capability)
    decision = decision_for(definition, execution_id=state.id)
    await trail.record(decision)
    for _ in range(claims):
        await trail.claim_invocation(decision=decision)
    return await claimed(plans, state, tool_id=definition.id)


async def stored_step(
    plans: PlanStore, state: ExecutionState, step_id: str = STEP
) -> StepExecution:
    """Read one step back out of durable state."""
    reloaded = await plans.get_execution(state.id)
    assert reloaded is not None
    step = reloaded.step(step_id)
    assert step is not None
    return step


def completions(rows: Iterable[ToolInvocation]) -> list[ToolInvocation]:
    """The completion rows among ``rows``, in the order given."""
    return [row for row in rows if row.completes is not None]


async def every_row(trail: AuditTrail) -> list[ToolInvocation]:
    """Every invocation row the trail holds, in the ledger's append order.

    ``export_invocations`` answers newest-first, so this reverses it — which is the
    append order only because every trail here is built over :class:`Ticking`. A
    frozen clock would leave every row at one instant and the tie broken by ``id``,
    and the fake's counter is not lexicographically ordered past nine.
    """
    return [recorded.invocation for recorded in reversed(await trail.export_invocations())]


class Ticking:
    """A clock advancing one second per reading, so append order is readable.

    Advancing rather than frozen because two assertions here are about **order**,
    and ADR-0192 §2 is explicit that the durable append order — not ``recorded_at``
    — is what every rule is decided on. What the tick buys is a *readable* order at
    the export seam, not a rule measured on an instant.
    """

    def __init__(self) -> None:
        """Start one tick before :data:`AT`."""
        self.now = AT - timedelta(seconds=1)

    def __call__(self) -> datetime:
        """Advance and return the new instant."""
        self.now += timedelta(seconds=1)
        return self.now


def assert_recovery_shaped(row: ToolInvocation, *, claim: str, decision_id: str = DECISION) -> None:
    """Assert one recovery completion field by field (ADR-0192 §9).

    Not merely counted. The scan derives its rows from **no ``ToolResult`` at
    all**, and the fields are exactly where that shows: a scan that closed every
    claim with ``failure_kind=TIMED_OUT`` and the declaration's price would pass
    every ordering, rerun and erasure case here and corrupt the spend total §5 is
    built on — a kind the tool never reported, at a number nobody measured.
    """
    assert row.completes == claim
    assert row.decision_id == decision_id
    assert row.outcome is ToolOutcome.INDETERMINATE
    assert row.failure_kind is None, "§2 forbids synthesising a kind; there was none to transcribe"
    assert row.incurred_cost is not None
    assert row.incurred_cost.basis is CostBasis.UNKNOWN, "never a figure, never the declaration's"
    assert row.incurred_cost.amount is None
    assert row.incurred_cost.currency is None
    assert row.recorded_at.tzinfo is not None, "stamped by the ledger from its guarded clock"


# --- doubles -------------------------------------------------------------


class ScriptedIdentifiers:
    """A factory returning ids a test chose, and honouring every reservation.

    Conforming in the one respect the reservation cases turn on — it returns none
    it was given to reserve — and scripted in the one respect a conforming factory
    cannot be asked for: **which** id it draws next. A case resting on a factory
    left to its own sequence reproduces the restart collision only by coincidence,
    and a test resting on a coincidence asserts nothing (ADR-0192 §9).
    """

    def __init__(self, scripted: Sequence[str]) -> None:
        """Draw ``scripted`` in order, then fall back to a fresh sequence."""
        self._scripted = list(scripted)
        self._fallback = FakeIdentifiers(space=FakeIdentifierSpace())
        self._reserved: set[str] = set()
        self.refused: list[str] = []

    def __call__(self) -> str:
        """Return the next scripted id the reservation still permits."""
        while self._scripted:
            candidate = self._scripted.pop(0)
            if candidate not in self._reserved:
                return candidate
            self.refused.append(candidate)
        return self._fallback()

    def reserve(self, ids: Iterable[str]) -> None:
        """Take ``ids`` out of this factory for good."""
        self._reserved.update(ids)


class WatchingPlanStore(FakePlanStore):
    """A plan store that reads the trail at the moment each transition commits.

    The ordering ADR-0192 §3 states is not observable from the end state — a scan
    that transitioned first and completed afterwards leaves exactly the same rows.
    So this snapshots what was open at the instant of the commit, which is the only
    place the two orders differ.
    """

    def __init__(self, trail: AuditTrail, decision_id: str = DECISION) -> None:
        """Watch ``decision_id``'s open claims across every commit."""
        super().__init__()
        self._trail = trail
        self._decision_id = decision_id
        self.open_at_commit: list[tuple[StepStatus, tuple[str, ...]]] = []

    async def commit_transition(self, transition: StepTransition) -> ExecutionState:
        """Record what was open, then commit."""
        claims = await self._trail.open_invocations(decision_id=self._decision_id)
        self.open_at_commit.append((transition.to_status, tuple(claim.id for claim in claims)))
        return await super().commit_transition(transition)


class CountingCompleter:
    """An :class:`InvocationCompleter` that counts, and may fail on a chosen call."""

    def __init__(self, trail: FakeAuditTrail, *, fails_on: int | None = None) -> None:
        """Delegate to ``trail``, raising instead on the ``fails_on``-th call."""
        self._trail = trail
        self._fails_on = fails_on
        self.calls = 0

    async def complete_invocation(
        self,
        *,
        claim_id: str,
        outcome: ToolOutcome,
        incurred_cost: ToolCost,
        failure_kind: ToolFailureKind | None = None,
    ) -> ToolInvocation:
        """Count the call, then either fail it or pass it on."""
        self.calls += 1
        if self.calls == self._fails_on:
            msg = "the trail could not be written"
            raise AuditError(msg)
        return await self._trail.complete_invocation(
            claim_id=claim_id,
            outcome=outcome,
            incurred_cost=incurred_cost,
            failure_kind=failure_kind,
        )


class ErasingCompleter:
    """A completer that lets ``clear()`` land between the enumeration and the write.

    The one interleaving that makes ADR-0192 §2's ``InvalidCompletionError``
    reachable at this seam (§3): the scan enumerated an open claim, and by the time
    it writes, the user has erased it.
    """

    def __init__(self, trail: FakeAuditTrail) -> None:
        """Erase the trail on the first completion, then delegate."""
        self._trail = trail
        self.erased = 0

    async def complete_invocation(
        self,
        *,
        claim_id: str,
        outcome: ToolOutcome,
        incurred_cost: ToolCost,
        failure_kind: ToolFailureKind | None = None,
    ) -> ToolInvocation:
        """Erase once, then complete whatever is left."""
        if not self.erased:
            self.erased = await self._trail.clear()
        return await self._trail.complete_invocation(
            claim_id=claim_id,
            outcome=outcome,
            incurred_cost=incurred_cost,
            failure_kind=failure_kind,
        )


class RecordingTrail:
    """Records which trail members a recovery pass reached."""

    def __init__(self, trail: FakeAuditTrail) -> None:
        """Delegate every call to ``trail``, naming it first."""
        self._trail = trail
        self.reached: list[str] = []

    def __getattr__(self, name: str) -> object:
        """Name the member, then hand back the trail's own."""
        self.reached.append(name)
        return getattr(self._trail, name)


def scan_over(
    plans: PlanStore, trail: LedgerTrail, completer: InvocationCompleter | None = None
) -> RecoveryScan:
    """Wire a scan the way the composition root does: one store behind two faces."""
    return RecoveryScan(
        plans=plans,
        trail=trail,
        completer=completer if completer is not None else trail,
    )


# --- §3: the completion's fields ----------------------------------------


async def test_the_scan_completes_the_open_claim_indeterminate_field_by_field() -> None:
    """The happy path, asserted where a scan deriving rows from nothing goes wrong.

    ``INDETERMINATE`` is not a value minted to fill a field but ADR-0014 §4's
    durable ignorance, which is exactly what the record holds about this claim: the
    process died with the call in flight, and nothing established what it did.
    """
    trail = FakeAuditTrail(now=Ticking())
    plans = FakePlanStore()
    state = await a_running_step(plans, trail, tool())
    claim = (await trail.open_invocations(decision_id=DECISION))[0]

    await scan_over(plans, trail).recover()

    appended = completions(await every_row(trail))
    assert len(appended) == 1
    assert_recovery_shaped(appended[0], claim=claim.id)
    assert appended[0].recorded_at > claim.recorded_at, (
        "the completion's own reading, taken by the ledger at its append (ADR-0192 §2)"
    )
    assert (await stored_step(plans, state)).status is StepStatus.INDETERMINATE


async def test_the_declarations_price_reaches_no_row() -> None:
    """``ToolDefinition.cost`` appears on **no** row of the trail (ADR-0192 §5).

    The declaration here is ``PER_CALL`` at a real figure, so an implementation
    reading a price off the decision it already holds would produce a row that
    passes every count and ordering case and puts a number nobody measured into the
    spend total §5 exists to keep honest.
    """
    trail = FakeAuditTrail(now=Ticking())
    plans = FakePlanStore()
    await a_running_step(plans, trail, tool())

    await scan_over(plans, trail).recover()

    for row in completions(await every_row(trail)):
        assert row.incurred_cost is not None
        assert row.incurred_cost.basis is CostBasis.UNKNOWN


# --- §3: completions first, transition second ---------------------------


async def test_the_transition_commits_only_once_no_claim_is_still_open() -> None:
    """The order is the whole of the crash protocol (ADR-0192 §3).

    Committing the transition first loses every claim still open at that moment,
    **permanently**: the step stops being ``RUNNING``, no later scan returns for it,
    and nothing else knows to look — a ``ToolInvocation`` names no step and is
    reachable from that step's ``approval_ref`` and from nowhere else.

    Not observable from the end state, which is why this reads the trail from
    inside the commit: both orders leave one completion and one ``INDETERMINATE``
    step.
    """
    trail = FakeAuditTrail(now=Ticking())
    plans = WatchingPlanStore(trail)
    await a_running_step(plans, trail, read_only(), claims=2)

    await scan_over(plans, trail).recover()

    resolving = [
        open_claims
        for status, open_claims in plans.open_at_commit
        if status is StepStatus.INDETERMINATE
    ]
    assert resolving == [()], "no claim under that decision was still open at the transition"


async def test_two_open_claims_under_one_decision_are_both_completed() -> None:
    """ "Every open claim", and not one selected among them (ADR-0192 §3, §9).

    Pinned on the **non-spendable** authorisation, because that is the only kind §1
    admits a second claim under: a first attempt whose completion write failed
    leaves its claim open with the call's own result standing, ADR-0029 §5's first
    two arms admit the retry, and the process dies with the retry's claim open too.

    An implementation completing "the" open claim passes every single-claim case
    here and strands the other permanently. Both are completed in the ledger's
    append order, and no correlation is asserted between a completion and an
    attempt — §3 mints none.
    """
    trail = FakeAuditTrail(now=Ticking())
    plans = FakePlanStore()
    await a_running_step(plans, trail, read_only(), claims=2)
    open_ids = [claim.id for claim in await trail.open_invocations(decision_id=DECISION)]
    assert len(open_ids) == 2

    await scan_over(plans, trail).recover()

    appended = completions(await every_row(trail))
    assert [row.completes for row in appended] == open_ids, "both, in append order"
    for row, claim in zip(appended, open_ids, strict=True):
        assert_recovery_shaped(row, claim=claim)


# --- §3: the crash protocol, re-run ------------------------------------


async def test_a_scan_interrupted_between_two_completions_leaves_the_step_recoverable() -> None:
    """A crash partway through costs a scan, never a stranded claim (ADR-0192 §3, §9).

    The ordering makes the act **idempotent with no marker, generation or resume
    point**: the interrupted scan leaves the step ``RUNNING``, so the next one finds
    the same step and completes whatever is still open; a claim already completed is
    no longer *open*, so no rerun ever attempts a second completion of one; and a
    third scan, over a step now out of ``RUNNING``, appends nothing at all.
    """
    trail = FakeAuditTrail(now=Ticking())
    plans = FakePlanStore()
    state = await a_running_step(plans, trail, read_only(), claims=2)
    open_ids = [claim.id for claim in await trail.open_invocations(decision_id=DECISION)]

    with pytest.raises(AuditError):
        await scan_over(plans, trail, CountingCompleter(trail, fails_on=2)).recover()

    assert (await stored_step(plans, state)).status is StepStatus.RUNNING, "still recoverable"
    assert [row.completes for row in completions(await every_row(trail))] == open_ids[:1]

    second = CountingCompleter(trail)
    await scan_over(plans, trail, second).recover()

    assert second.calls == 1, "only the claim still open; the completed one is not re-completed"
    assert [row.completes for row in completions(await every_row(trail))] == open_ids
    assert (await stored_step(plans, state)).status is StepStatus.INDETERMINATE

    third = CountingCompleter(trail)
    await scan_over(plans, trail, third).recover()

    assert third.calls == 0, "a step out of RUNNING is not returned for"
    assert len(completions(await every_row(trail))) == 2


async def test_a_crash_after_the_last_completion_appends_nothing() -> None:
    """The other half of the window, and the divergence §3 states rather than repairs.

    A crash after the last completion and before the step's transition leaves a
    **completed** claim under a ``RUNNING`` step. The next scan appends nothing and
    records the step ``INDETERMINATE`` — so the ledger can read ``SUCCEEDED`` while
    the step reads ``INDETERMINATE`` for one attempt, and neither record is inferred
    from the other's absence or rewritten to match it.
    """
    trail = FakeAuditTrail(now=Ticking())
    plans = FakePlanStore()
    state = await a_running_step(plans, trail, tool())
    claim = (await trail.open_invocations(decision_id=DECISION))[0]
    await trail.complete_invocation(
        claim_id=claim.id,
        outcome=ToolOutcome.SUCCEEDED,
        incurred_cost=ToolCost(basis=CostBasis.FREE),
    )
    before = await every_row(trail)

    await scan_over(plans, trail).recover()

    assert await every_row(trail) == before, "nothing appended, and nothing rewritten"
    assert (await stored_step(plans, state)).status is StepStatus.INDETERMINATE
    assert completions(before)[0].outcome is ToolOutcome.SUCCEEDED, "the row stands as written"


async def test_a_running_step_with_no_claim_transitions_and_appends_nothing() -> None:
    """No open claim means no call was in flight, so there is nothing to complete.

    The step is still resolved: ADR-0014 §4's transition is owed whatever the trail
    holds, and ADR-0192 §3 adds an act to that occasion rather than a condition on
    it.
    """
    trail = FakeAuditTrail(now=Ticking())
    plans = FakePlanStore()
    state = await an_execution(plans)
    await trail.record(decision_for(tool(), execution_id=state.id))
    await claimed(plans, state)

    await scan_over(plans, trail).recover()

    assert await every_row(trail) == []
    assert (await stored_step(plans, state)).status is StepStatus.INDETERMINATE


# --- §3, §6: the erasure that lands under the scan ----------------------


async def test_an_erasure_under_the_scan_is_absorbed_and_recreates_nothing() -> None:
    """``clear()`` wins here as everywhere (ADR-0192 §3, §6).

    Between enumerating an open claim and completing it, an erasure can remove that
    claim; the completion then refuses exactly as it does for any completion naming
    no claim. That refusal is neither a fault to repair nor a reason to abandon the
    transition — the claim it named no longer exists, so there is nothing left to
    complete. The scan re-reads, finds none open, and commits.

    **Nothing is recreated.** Putting a claim back would be the store recreating a
    row the user destroyed on purpose, which §6 names as the one answer no store may
    give.
    """
    trail = FakeAuditTrail(now=Ticking())
    plans = WatchingPlanStore(trail)
    state = await a_running_step(plans, trail, tool())
    erasing = ErasingCompleter(trail)

    await scan_over(plans, trail, erasing).recover()

    assert erasing.erased, "the erasure landed under the scan"
    assert await every_row(trail) == [], "no claim, no completion, nothing recreated"
    assert (await stored_step(plans, state)).status is StepStatus.INDETERMINATE, (
        "the transition is committed, never abandoned in RUNNING"
    )
    resolving = [
        open_claims
        for status, open_claims in plans.open_at_commit
        if status is StepStatus.INDETERMINATE
    ]
    assert resolving == [()]


async def test_a_completion_refused_for_any_other_reason_is_not_absorbed() -> None:
    """Only ``InvalidCompletionError`` is the erasure's refusal (ADR-0192 §3).

    A store that cannot be written is a startup fault and not something to press on
    past: absorbing it would commit the step's transition over a claim that is still
    open, which is the one order §3 forbids. The narrow ``except`` is what makes the
    difference, so it is asserted rather than assumed.
    """
    trail = FakeAuditTrail(now=Ticking())
    plans = FakePlanStore()
    state = await a_running_step(plans, trail, tool())

    with pytest.raises(AuditError) as caught:
        await scan_over(plans, trail, CountingCompleter(trail, fails_on=1)).recover()

    assert not isinstance(caught.value, InvalidCompletionError)
    assert (await stored_step(plans, state)).status is StepStatus.RUNNING


# --- §9: the faces the scan holds ---------------------------------------


async def test_a_recovery_pass_reaches_open_invocations_and_nothing_else() -> None:
    """The scan reads one member of the trail and writes one of the completer.

    ADR-0192 §2 makes this scan ``open_invocations``' only consumer, and §9 gives it
    the **narrow** face for the write. The claim is checkable rather than trusted
    because the dependency cannot express a claim at all — but the trail it holds
    still carries ``record``, ``export`` and ``clear``, and that posture is a
    residue ADR-0192 §9 inherits rather than a licence, so the pass is watched.
    """
    trail = FakeAuditTrail(now=Ticking())
    plans = FakePlanStore()
    await a_running_step(plans, trail, tool())
    watched = RecordingTrail(trail)
    completer = CountingCompleter(trail)

    await RecoveryScan(plans=plans, trail=watched, completer=completer).recover()  # type: ignore[arg-type]  # a recording proxy over the fake

    assert set(watched.reached) == {"open_invocations"}
    assert completer.calls == 1


async def test_the_scan_leaves_every_step_that_is_not_running_alone() -> None:
    """Only ``RUNNING`` is recovery's occasion (ADR-0014 §4, ADR-0192 §10).

    A step ``AWAITING_APPROVAL`` at a restart is ADR-0052 §1's to recover, not this
    scan's, and ADR-0014 §4's transition graph is untouched by ADR-0192 (§10). A
    scan reaching a second status would be minting a mechanism neither ADR has.
    """
    trail = FakeAuditTrail(now=Ticking())
    plans = FakePlanStore()
    state = await an_execution(plans, steps=(STEP, OTHER_STEP))
    await trail.record(decision_for(tool(), execution_id=state.id))
    await plans.commit_transition(
        StepTransition(
            execution_id=state.id,
            step_id=STEP,
            to_status=StepStatus.AWAITING_APPROVAL,
            expected_version=state.version,
            bound_tool="smtp",
        )
    )

    await scan_over(plans, trail).recover()

    assert (await stored_step(plans, state)).status is StepStatus.AWAITING_APPROVAL
    assert (await stored_step(plans, state, OTHER_STEP)).status is StepStatus.PENDING


async def test_every_running_step_of_one_execution_is_resolved() -> None:
    """Each transition is computed against the state the last one returned.

    The store's write is compare-and-swap on ``expected_version`` and every commit
    moves the version on, so a scan iterating the snapshot ``active_executions``
    handed back would be refused ``StaleExecutionError`` on the second step —
    stranding it, and every claim under it, for good.
    """
    trail = FakeAuditTrail(now=Ticking())
    plans = FakePlanStore()
    state = await an_execution(plans, steps=(STEP, OTHER_STEP))
    for step_id, decision_id in ((STEP, "d-1"), (OTHER_STEP, "d-2")):
        decision = decision_for(
            tool(), decision_id=decision_id, step_id=step_id, execution_id=state.id
        )
        await trail.record(decision)
        await trail.claim_invocation(decision=decision)
        state = await claimed(plans, state, step_id=step_id, decision_id=decision_id)

    await scan_over(plans, trail).recover()

    assert (await stored_step(plans, state)).status is StepStatus.INDETERMINATE
    assert (await stored_step(plans, state, OTHER_STEP)).status is StepStatus.INDETERMINATE
    assert len(completions(await every_row(trail))) == 2


# --- §2, §3: the reservation, and the completion that outlives a restart --


class ClaimingCompleter:
    """A completer that lets a **fresh claim** land between the read and the write.

    The restart hazard in one object: the scan is holding a claim id it read out of
    a store no live process minted from, and something claims again before it
    writes. Without ``open_invocations``' reservation the fresh claim can receive
    that very id, and the scan's completion — one call's outcome and cost — lands on
    a **different** call's claim, silently.
    """

    def __init__(self, trail: LedgerTrail, decision: PermissionDecision) -> None:
        """Claim once under ``decision``, on the first completion, then delegate."""
        self._trail = trail
        self._decision = decision
        self.claimed: ToolInvocation | None = None

    async def complete_invocation(
        self,
        *,
        claim_id: str,
        outcome: ToolOutcome,
        incurred_cost: ToolCost,
        failure_kind: ToolFailureKind | None = None,
    ) -> ToolInvocation:
        """Mint a fresh claim once, then write the completion the scan asked for."""
        if self.claimed is None:
            self.claimed = await self._trail.claim_invocation(decision=self._decision)
        return await self._trail.complete_invocation(
            claim_id=claim_id,
            outcome=outcome,
            incurred_cost=incurred_cost,
            failure_kind=failure_kind,
        )


@pytest.fixture(params=["fake", "sqlite"])
def restarted(request: pytest.FixtureRequest) -> Iterator[tuple[PlanStore, LedgerTrail]]:
    """A plan store and a trail whose factory's first draw is ``RESERVED``.

    Both implementations, because the reservation ADR-0192 §2 puts **inside**
    ``open_invocations``' own store operation is a property of a store that
    serialises its reads and writes; a fake holding objects can model it, and only
    the durable one proves it over a transaction boundary.

    ``RESERVED`` is scripted twice: once for the claim that is already open when the
    scan starts, and once for the draw the scan's own writes take next — which a
    conforming, process-scoped factory in a *new* process may legally return, and
    which the reservation is the only thing standing between and a reissue.
    """
    identifiers = ScriptedIdentifiers([RESERVED, RESERVED])
    if request.param == "fake":
        yield FakePlanStore(), FakeAuditTrail(now=Ticking(), identifiers=identifiers)
        return
    trail = SqliteAuditTrail(path=":memory:", now=Ticking(), identifiers=identifiers)
    try:
        yield SqlitePlanStore(path=":memory:"), trail
    finally:
        trail.close()


async def test_the_completion_of_a_reserved_claim_lands_over_a_fresh_one(
    restarted: tuple[PlanStore, LedgerTrail],
) -> None:
    """The scan completes the claim it read, never the claim minted under it.

    ``open_invocations`` "reserves every claim id it returns", and this is the case
    the reservation exists for (ADR-0192 §2): a claim appended by one process is
    read back by a **new** one whose factory may legally mint that same id, and the
    completion the scan is still holding must not attach to a later call's claim.

    Driven so the factory **would** have reissued it — the scripted draw is refused
    by the reservation and not by luck, which a factory left to its own sequence
    reproduces only by coincidence.
    """
    plans, trail = restarted
    definition = read_only()
    state = await an_execution(plans, capability=definition.capability)
    decision = decision_for(definition, execution_id=state.id)
    await trail.record(decision)
    stale = await trail.claim_invocation(decision=decision)
    assert stale.id == RESERVED
    await claimed(plans, state, tool_id=definition.id)
    interleaving = ClaimingCompleter(trail, decision)

    await scan_over(plans, trail, interleaving).recover()

    assert interleaving.claimed is not None
    assert interleaving.claimed.id != RESERVED, "the reservation outlived the process that minted"
    settled = {row.completes: row for row in completions(await every_row(trail))}
    assert_recovery_shaped(settled[RESERVED], claim=RESERVED)
    assert settled[RESERVED].id != RESERVED, "a completion mints its own id"
    assert interleaving.claimed.id in settled, "the fresh claim is completed too, on the re-read"
    assert (await stored_step(plans, state)).status is StepStatus.INDETERMINATE


# --- ADR-0014 §4: the scan runs at startup, and startup happens once ------


class CountingScan(RecoveryScan):
    """A scan that counts its passes and suspends inside each one.

    The suspension is the point rather than a detail: a guard written as a bare
    flag is not a guard across an ``await``, and only a scan that yields lets two
    overlapping calls both observe it unset.
    """

    def __init__(self) -> None:
        """Count only; every collaborator is unreached because ``recover`` is not."""
        self.calls = 0

    async def recover(self) -> None:
        """Count the pass, and give the loop somewhere to interleave."""
        self.calls += 1
        await asyncio.sleep(0)


def engine_with(scan: RecoveryScan | None) -> Engine:
    """A façade over a harness's durable state, holding ``scan``."""
    harness = Harness()
    return Engine(
        composing=composing(),
        grant_operations=grant_operations(),
        connection_operations=connection_operations(),
        loop=harness.engine._loop,
        runner=harness.engine._runner,
        plans=harness.plans,
        trail=harness.trail,
        spend=harness.trail,
        reads=harness.reads,
        memory=harness.memory,
        deferrals=harness.deferrals,
        traces=harness.traces,
        trace_sink=harness.trace_sink,
        trace_retention=harness.trace_retention,
        conversations=harness.conversations,
        observation=harness.observation,
        questions=harness.questions,
        recovery=scan,
    )


async def test_a_second_start_does_not_scan_again() -> None:
    """``start`` is *also* the scheduler's recurring conversation sweep.

    ``service/scheduler.py``'s job table wires ``engine.start`` as the sweep, so a
    scan on every call would run on a timer inside a hub that is serving turns —
    and ADR-0014 §4 authorises the scan only because it "presumes no executor is
    live for those states". True of a step the *previous* process left ``RUNNING``,
    false of one this process claimed a moment ago. An unguarded scan would
    complete a live invocation's claim ``INDETERMINATE`` and commit its step out of
    ``RUNNING``, after which the tool's real completion is refused and its
    executor's terminal write is refused stale.

    The sweeps beside it stay repeatable, which is what makes this a guard on one
    step rather than on the method.
    """
    scan = CountingScan()
    engine = engine_with(scan)

    await engine.start()
    await engine.start()

    assert scan.calls == 1


async def test_two_overlapping_starts_scan_once_between_them() -> None:
    """A bare flag is not a guard across an ``await``.

    Both calls read it unset; the first scans and returns, an executor then claims
    a step, and the second resumes its already-started scan over that live claim —
    the very state the guard exists to prevent, reached *through* the guard.
    ``start`` is public and documents only that it is safe to call more than once,
    so nothing in this class excludes the overlap: the hub's step 4 / step 6
    ordering is a fact about ``service/hub.py`` and not a property callers of this
    method inherit. The same finding adversarial review made against the lease
    guard, one collaborator over.
    """
    scan = CountingScan()
    engine = engine_with(scan)

    await asyncio.gather(engine.start(), engine.start())

    assert scan.calls == 1


async def test_an_engine_wired_with_no_scan_still_starts() -> None:
    """``recovery`` is optional, and its absence is not an error.

    The CLI's in-process engine and every test façade compose none, exactly as they
    compose no delivery outbox. A guard that dereferenced an absent scan would turn
    an unwired deployment into a startup crash.
    """
    await engine_with(None).start()  # must not raise
