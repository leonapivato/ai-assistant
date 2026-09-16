"""Records ADR-0262's comparison reads, built by hand so each arm varies one fact.

Every value here is one the **record already carries** (§2): a user-confirmed coverage
member, an authorisation that proved a concrete call against it, a tool author's own
declared postconditions, and the steps a walk committed. **Nothing a planner returns is
built at all** — no ``verifies``, no ``intended_action``, no ``serves`` — which is what
makes an arm asserting *"no model authors any operand"* an arm about the operands
rather than about a mock.

The two read seams are the module-private Protocols
:mod:`ai_assistant.orchestration.verification` narrows them to, so the doubles here
carry ``get_execution`` and ``get`` and **nothing else**: a double able to write would
be one an implementation could write through.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import (
    Authorization,
    AuthorizationBasis,
    AuthorizationDisposition,
    AuthorizationOrigin,
    BoundAccount,
    BoundKind,
    CanonicalDestination,
    CostBasis,
    CoverageMember,
    ExecutionState,
    Goal,
    GoalAttempt,
    GoalElement,
    GoalInterpretation,
    GoalStatus,
    Ground,
    Idempotency,
    MemorySource,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Provenance,
    ResolutionRule,
    Reversibility,
    RiskLevel,
    StepExecution,
    StepFailure,
    StepStatus,
    StepVerification,
    ToolCost,
    ToolDefinition,
    ToolFailureKind,
    ValueBound,
    ValueResolution,
    VerificationKind,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.types import EgressBinding, FrozenJson, SkipReason

AT: Final = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)
"""The one instant every record here is stamped at."""

GOAL: Final = "g-1"
"""The goal every arm compares."""

EXECUTION: Final = "e-1"
"""The execution the attempt names, unless an arm names a second."""

ACT: Final = "t-1"
"""The turn the confirmed members were minted from (ADR-0266 §2)."""

ACCOUNT: Final = BoundAccount(identity="bookings@example.com", reference="conn-1")

DESTINATION: Final = CanonicalDestination(account=ACCOUNT)
"""The one canonical destination a recorded act names (ADR-0193 §1, ADR-0148 §2)."""

_SUBJECT: Final = "a" * 64
"""A well-formed ``Sha256Hex``; the recomputed subject digest is ``record``'s check."""

DIGEST: Final = "b" * 64
"""The ``parameters_digest`` one call's steps share (§2's grouping)."""

OTHER_DIGEST: Final = "c" * 64
"""A **second** call — a different concrete request, so a different group."""

RIVERSIDE: Final = "Riverside"
SUNDAY: Final = "Sunday"
UNDER_150: Final = "up to 150 euros"


def field_equals(key: str, value: FrozenJson) -> StepVerification:
    """One declared postcondition: that key of the output equals that literal."""
    return StepVerification(kind=VerificationKind.FIELD_EQUALS, field=key, equals=value)


def field_present(key: str) -> StepVerification:
    """One declared postcondition: that key of the output is present and not null."""
    return StepVerification(kind=VerificationKind.FIELD_PRESENT, field=key)


def a_tool(
    tool_id: str = "bookings",
    *,
    postconditions: Sequence[StepVerification] = (),
    **overrides: object,
) -> ToolDefinition:
    """A declaration, with whatever it declares about its own success.

    The default is ``side_effecting`` and ``REVERSIBLE`` with an empty ``discloses``,
    which is §3's **rung 1** — an act ran that is not rung 2's — so an arm about the
    rung says which field it moved and every other arm is unaffected by it.
    """
    fields: dict[str, object] = {
        "id": tool_id,
        "capability": "book_site",
        "description": "Book a campsite.",
        "risk_level": RiskLevel.LOW,
        "reversibility": Reversibility.REVERSIBLE,
        "side_effecting": True,
        "reads": (),
        "writes": (),
        "discloses": (),
        "cost": ToolCost(basis=CostBasis.FREE),
        "idempotency": Idempotency.NATURAL,
        "postconditions": tuple(postconditions),
    }
    fields.update(overrides)
    return ToolDefinition(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def a_criterion(span: str | None, *, text: str | None = None) -> GoalElement:
    """One criterion of the goal's current interpretation.

    ``span`` ``None`` is a criterion on any ground but ``USER_STATED``, which §2 gives
    **no matching member by construction** — so it is spelled by the ground rather than
    by an absent field, exactly as :class:`~ai_assistant.core.types.GoalElement`
    requires.
    """
    if span is None:
        return GoalElement(text=text or "it is booked", ground=Ground.INFERRED)
    return GoalElement(text=text or span, ground=Ground.USER_STATED, span=span)


def a_goal(
    *criteria: GoalElement,
    status: GoalStatus = GoalStatus.ACTIVE,
    version: int = 3,
) -> Goal:
    """The goal, carrying ``criteria`` on its **current** interpretation (§1)."""
    return Goal(
        id=GOAL,
        interpretation=(
            GoalInterpretation(
                revision=1,
                outcome="book the campsite",
                outcome_ground=Ground.USER_STATED,
                outcome_span="book the campsite",
                criteria=criteria,
                recorded_at=AT,
                raised_by=ACT,
            ),
        ),
        status=status,
        version=version,
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT),
        created_at=AT,
    )


def a_member(span: str, *, kind: BoundKind = BoundKind.TERMS) -> CoverageMember:
    """One member of a confirmed row, resting on **the span the user stated**.

    The span is what §2 matches a criterion against, byte for byte; the value beside it
    is whatever that kind admits (ADR-0266 §3) — a ceiling for ``MONEY``, a date for
    ``PERIOD``, the words themselves for ``TERMS`` — and **no arm here reads it**, which
    is the point: the comparison joins on the span and never on the value.
    """
    basis = AuthorizationBasis(
        act=ACT, span=span, resolution=ValueResolution(rule=ResolutionRule.AS_STATED)
    )
    if kind is BoundKind.MONEY:
        return CoverageMember(
            kind=kind,
            bound=ValueBound(kind=kind, currency="EUR", maximum=Decimal("150.00")),
            basis=basis,
        )
    if kind is BoundKind.PERIOD:
        return CoverageMember(kind=kind, fixed="2026-09-20", basis=basis)
    return CoverageMember(kind=kind, fixed=span, basis=basis)


def a_row(
    authorization_id: str = "auth-1",
    *members: CoverageMember,
    origin: AuthorizationOrigin = AuthorizationOrigin.CONFIRMED,
    goal: str = GOAL,
    disposition: AuthorizationDisposition = AuthorizationDisposition.ESTABLISHED,
    tool_id: str = "bookings",
) -> Authorization:
    """An authorising row of this goal, carrying ``members``."""
    return Authorization(
        id=authorization_id,
        goal=goal,
        tool=a_tool(tool_id=tool_id),
        account=ACCOUNT,
        destinations=(DESTINATION,),
        origin=origin,
        coverage=members,
        proposed_at=AT - timedelta(hours=1),
        expires_at=AT + timedelta(hours=1),
        confirmation="d-0",
        supersedes=None,
        disposition=disposition,
        settled_at=AT - timedelta(hours=1),
    )


def a_ruling(
    *,
    authorised_by: str | None = "auth-1",
    outcome: PermissionOutcome = PermissionOutcome.ALLOW,
    goal: str | None = GOAL,
    subject: str | None = _SUBJECT,
) -> PermissionRuling:
    """A route-(d) ``ALLOW``, or one of the shapes §2 says is not one.

    ADR-0254 §7's discriminator is *"``resolves`` unset, ``authorised_by`` set,
    ``authorised_subject`` set, ``authorised_goal`` **set**"*, so dropping any one of
    the three named here is how an arm spells a route-(a), (b) or (c) ``ALLOW``.
    """
    return PermissionRuling(
        outcome=outcome,
        reason="a standing authorization of this goal covers this call",
        authorised_by=authorised_by,
        # ADR-0193 §6, enforced on the model: a ruling that names no authorisation
        # fingerprints none. So dropping `authorised_by` drops the digest with it, and
        # a route-(a) `ALLOW` is spelled by passing `goal=None` as well.
        authorised_subject=None if authorised_by is None else subject,
        authorised_goal=goal,
    )


def a_decision(
    decision_id: str,
    *,
    definition: ToolDefinition | None = None,
    digest: str = DIGEST,
    ruling: PermissionRuling | None = None,
    egress_binding: EgressBinding | None = None,
) -> PermissionDecision:
    """The ruling a step was claimed under, with the declaration pinned **by value**."""
    return PermissionDecision(
        id=decision_id,
        ruling=ruling if ruling is not None else a_ruling(),
        tool=definition if definition is not None else a_tool(),
        parameters_digest=digest,
        decided_at=AT,
        egress_binding=egress_binding,
    )


def a_step(  # noqa: PLR0913 — one keyword per field of the stored step an arm varies
    step_id: str,
    *,
    status: StepStatus = StepStatus.SUCCEEDED,
    output: Mapping[str, FrozenJson] | None = None,
    approval_ref: str | None = "d-1",
    attempts: int = 1,
    skip_reason: SkipReason | None = None,
    satisfied_by: tuple[str, str] | None = None,
    bound_tool: str | None = "bookings",
) -> StepExecution:
    """One committed step.

    ``attempts`` is what §3 reads as *"reached a committed ``→ RUNNING`` claim"* — the
    store increments it on exactly that transition — so ``attempts=0`` is a step a plan
    declared and no walk claimed. ``satisfied_by`` is ADR-0259 §2's pair, which such a
    step carries **without** a claim of its own.
    """
    ran = attempts > 0 and status in {
        StepStatus.SUCCEEDED,
        StepStatus.FAILED,
        StepStatus.INDETERMINATE,
    }
    return StepExecution(
        step_id=step_id,
        status=status,
        attempts=attempts,
        bound_tool=bound_tool,
        output=output,
        approval_ref=approval_ref,
        skip_reason=skip_reason,
        # The model's own invariants: a step that ran carries both instants, and a
        # `FAILED` or `INDETERMINATE` one carries a failure. They are supplied here
        # rather than asserted away so that every record an arm compares is one the
        # store could have written.
        started_at=AT if ran or (attempts > 0 and status is StepStatus.RUNNING) else None,
        finished_at=AT if ran or (attempts == 0 and satisfied_by is not None) else None,
        failure=(
            StepFailure(kind=ToolFailureKind.UNAVAILABLE, message="the provider was unreachable")
            if status in {StepStatus.FAILED, StepStatus.INDETERMINATE}
            else None
        ),
        satisfied_by_execution=None if satisfied_by is None else satisfied_by[0],
        satisfied_by_step=None if satisfied_by is None else satisfied_by[1],
    )


def an_execution(*steps: StepExecution, execution_id: str = EXECUTION) -> ExecutionState:
    """One execution of the attempt, carrying ``steps``."""
    return ExecutionState(
        id=execution_id, plan_id=f"plan-{execution_id}", steps=steps, updated_at=AT
    )


def an_attempt(*execution_ids: str) -> GoalAttempt:
    """The attempt being compared, naming ``execution_ids``."""
    return GoalAttempt(
        id="attempt-1",
        goal_id=GOAL,
        opened_at=AT,
        execution_ids=execution_ids or (EXECUTION,),
    )


class Executions:
    """The plan store, narrowed to the one read the comparison takes."""

    def __init__(self, *states: ExecutionState, failure: Exception | None = None) -> None:
        """Hold ``states``, or raise ``failure`` from every read."""
        self._by_id = {state.id: state for state in states}
        self._failure = failure
        self.calls: list[str] = []

    async def get_execution(self, execution_id: str) -> ExecutionState | None:
        """The execution, or ``None`` where this double does not hold it."""
        self.calls.append(execution_id)
        if self._failure is not None:
            raise self._failure
        return self._by_id.get(execution_id)


class Decisions:
    """The audit trail, narrowed to the one read the comparison takes."""

    def __init__(self, *decisions: PermissionDecision, failure: Exception | None = None) -> None:
        """Hold ``decisions``, or raise ``failure`` from every read."""
        self._by_id = {decision.id: decision for decision in decisions}
        self._failure = failure
        self.calls: list[str] = []

    async def get(self, decision_id: str) -> PermissionDecision | None:
        """The ruling, or ``None`` where the trail does not hold it."""
        self.calls.append(decision_id)
        if self._failure is not None:
            raise self._failure
        return self._by_id.get(decision_id)


class Rows:
    """``AuthorizationResolution``, which is ``resolve(id)`` and nothing else."""

    def __init__(self, *rows: Authorization, failure: Exception | None = None) -> None:
        """Hold ``rows``, or raise ``failure`` from every read."""
        self._by_id = {row.id: row for row in rows}
        self._failure = failure
        self.calls: list[str] = []

    async def resolve(self, authorization_id: str) -> Authorization | None:
        """The row in **every** disposition, or ``None``."""
        self.calls.append(authorization_id)
        if self._failure is not None:
            raise self._failure
        return self._by_id.get(authorization_id)
