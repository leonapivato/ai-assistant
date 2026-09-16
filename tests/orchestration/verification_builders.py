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
    CostBasis,
    CoverageMember,
    EgressBinding,
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
    SpanCoverage,
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

    from ai_assistant.core.types import FrozenJson, SkipReason


class _Derive:
    """The sentinel meaning *"derive this from the ruling"* (:func:`a_decision`)."""


_DERIVE: Final = _Derive()

AT: Final = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)
"""The one instant every record here is stamped at."""

GOAL: Final = "g-1"
"""The goal every arm compares."""

EXECUTION: Final = "e-1"
"""The execution the attempt names, unless an arm names a second."""

ACT: Final = "t-1"
"""The turn the confirmed members were minted from (ADR-0266 §2)."""

ACCOUNT: Final = BoundAccount(identity="bookings@example.com", reference="conn-1")

BINDING: Final = EgressBinding(
    spans=(),
    account=ACCOUNT,
    transport_endpoint="https://bookings.example.com",
    coverage=SpanCoverage.NOT_COVERED,
    closed_loop=False,
    planned_with_external_content=False,
)
"""The binding a route-(d) decision carries.

**A route-(d) ``ALLOW`` is an egress decision**: ADR-0254 §7's partition is over a
decision that *"rests on a standing authorisation"*, which the trail's own shape test
requires to carry an ``egress_binding``, so a ruling with ``authorised_goal`` set beside
no binding is outside the four routes and ``AuditTrail.record`` refuses it. Carrying one
here — over the **same** account the row names — is what makes these fixtures records the
trail could have stored. Adversarial review, round 6, ``blocker``.
"""

DESTINATION: Final = BINDING.canonical_destination_set
"""The row's destination set, taken from the binding rather than written twice."""

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


def a_row(  # noqa: PLR0913 — one keyword per field of the stored row an arm varies
    authorization_id: str = "auth-1",
    *members: CoverageMember,
    origin: AuthorizationOrigin = AuthorizationOrigin.CONFIRMED,
    goal: str = GOAL,
    disposition: AuthorizationDisposition = AuthorizationDisposition.ESTABLISHED,
    tool_id: str = "bookings",
    tool: ToolDefinition | None = None,
) -> Authorization:
    """An authorising row of this goal, carrying ``members``.

    ``tool`` is the declaration the row was established over. ADR-0254 §7 compares it
    with the request's **by value**, so a row and the decision that names it carry the
    same one or ``AuditTrail.record`` would have refused that decision — which is why
    :func:`paired` exists rather than each arm being trusted to keep them together.
    """
    return Authorization(
        id=authorization_id,
        goal=goal,
        tool=tool if tool is not None else a_tool(tool_id=tool_id),
        account=ACCOUNT,
        destinations=DESTINATION,
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


def a_decision(  # noqa: PLR0913 — one keyword per field of the stored decision an arm varies
    decision_id: str,
    *,
    definition: ToolDefinition | None = None,
    digest: str = DIGEST,
    ruling: PermissionRuling | None = None,
    egress_binding: EgressBinding | None | _Derive = _DERIVE,
    resolves: str | None = None,
) -> PermissionDecision:
    """The ruling a step was claimed under, with the declaration pinned **by value**.

    ``egress_binding`` is **derived from the ruling** unless an arm names one: a ruling
    that names an authorisation is a standing-route decision and carries
    :data:`BINDING`, because the trail's own shape test refuses one that does not; a
    ruling that names none is the policy's own rules and carries nothing. That coupling
    is §7's, and deriving it here is what keeps an arm from having to remember it.

    **It is also why a route-(d) act is rung 2 wherever its tool is side-effecting**
    (§3's third limb reads the decision's binding). A rung-1 act that still establishes a
    criterion is therefore a **read** authorised against a row — ``side_effecting``
    ``False`` — and the arms that want one say so.

    ``resolves`` is ADR-0254 §7's route-(a) conjunct — *"``resolves`` set,
    ``authorised_by`` equal to it"* — and it is the one limb of that partition no ruling
    can spell on its own, because the field is the **decision's** rather than the
    ruling's.
    """
    decided = ruling if ruling is not None else a_ruling()
    return PermissionDecision(
        id=decision_id,
        ruling=decided,
        tool=definition if definition is not None else a_tool(),
        parameters_digest=digest,
        decided_at=AT,
        resolves=resolves,
        egress_binding=(
            (BINDING if decided.authorised_by is not None else None)
            if isinstance(egress_binding, _Derive)
            else egress_binding
        ),
    )


def an_unbound_ruling() -> PermissionRuling:
    """An ``ALLOW`` that names **no** authorisation — the policy's own rules.

    ADR-0193 §11's third state, and §2's *"a step whose decision … carries no
    ``authorised_by`` at all contributes no row"*. It is what an **unrelated** step's
    ruling looks like: a step about something else did not run under the row this
    criterion rests on, and giving it that row's pointer beside a different declaration
    would be a pair ADR-0254 §7 refuses.
    """
    return PermissionRuling(
        outcome=PermissionOutcome.ALLOW, reason="the deployment's own rules allow this call"
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


def paired(
    rows: Sequence[Authorization], decisions: Sequence[PermissionDecision]
) -> tuple[tuple[Authorization, ...], tuple[PermissionDecision, ...]]:
    """Make every row and the decision that names it a pair the trail could have stored.

    ADR-0254 §7 makes ``AuditTrail.record`` **refuse** a route-(d) decision unless ten
    conditions hold over the row the store returned, two of which are facts about the
    *pair* rather than about either side: the row's ``tool`` equals the request's
    declaration **by value**, and the ruling's ``authorised_subject`` is the row's own
    **recomputed** digest. A fixture that broke either would be testing §2's comparison
    over a record the system could not have written — the arms would still pass, because
    §2 reads neither field, and they would be passing over an impossible state.

    So the reconciliation is done here, once, rather than left to fifty arms: each row is
    rebuilt carrying the declaration of the decision that names it — which is the
    declaration the arm is actually about, the one whose ``postconditions`` §2 compares —
    and each ruling is rebuilt carrying that row's ``subject_digest``. A decision naming
    no row, or naming one these rows do not hold, is returned untouched: that is exactly
    the shape the fail-closed arms are about. Adversarial review, round 5, ``blocker``.

    Args:
        rows: The rows the resolution would answer with.
        decisions: The rulings the trail holds.

    Returns:
        The rows and the decisions, made consistent with each other.
    """
    named: dict[str, PermissionDecision] = {}
    for decision in decisions:
        pointer = decision.ruling.authorised_by
        if pointer is None:
            continue
        held = named.setdefault(pointer, decision)
        if held.tool != decision.tool:
            # ADR-0254 §7 compares the row's declaration with the request's by value, so
            # **one row cannot have admitted two different declarations**. A fixture
            # pairing them is not a record the trail could hold, and silently keeping
            # one of the two would leave the other mismatched — which is the shape this
            # helper exists to remove. An unrelated step takes `an_unbound_ruling`, or
            # its own row.
            msg = (
                f"decisions {held.id!r} and {decision.id!r} both name authorization "
                f"{pointer!r} under different declarations: ADR-0254 §7 compares the "
                f"row's tool with the request's by value, so no trail could hold both"
            )
            raise AssertionError(msg)
    rebuilt = tuple(
        row if row.id not in named else row.model_copy(update={"tool": named[row.id].tool})
        for row in rows
    )
    digests = {row.id: row.subject_digest for row in rebuilt}
    return rebuilt, tuple(
        decision
        if decision.ruling.authorised_by not in digests
        else decision.model_copy(
            update={
                "ruling": decision.ruling.model_copy(
                    update={"authorised_subject": digests[decision.ruling.authorised_by]}
                )
            }
        )
        for decision in decisions
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
        self.failure = failure
        self.calls: list[str] = []

    async def resolve(self, authorization_id: str) -> Authorization | None:
        """The row in **every** disposition, or ``None``."""
        self.calls.append(authorization_id)
        if self.failure is not None:
            raise self.failure
        return self._by_id.get(authorization_id)

    @property
    def held(self) -> tuple[Authorization, ...]:
        """The rows this double holds, in the order it was given them."""
        return tuple(self._by_id.values())

    def reconcile(self, rows: Sequence[Authorization]) -> None:
        """Replace what this double holds, **in place**, with ``rows``.

        In place rather than by building a second double, so that an arm reading
        :attr:`calls` reads the calls the comparison actually made — there is one
        resolution per comparison and the arm holds it.
        """
        self._by_id = {row.id: row for row in rows}
