"""Inputs the path-(i) proposal is taken over (ADR-0254 §1), shared by two modules.

``test_authorizing.py`` runs the four conditions and the ladder directly;
``test_runner_authorizations.py`` drives the same shapes through a whole
``StepRunner``. One set of builders keeps the two talking about the same call.
"""

from __future__ import annotations

from collections.abc import Mapping  # noqa: TC003 — used at runtime by the span derivation
from datetime import UTC, datetime, timedelta
from typing import Final

from ai_assistant.core.types import (
    ActionRequest,
    BoundAccount,
    CostBasis,
    DiscloserProvenance,
    EgressBinding,
    EgressSpan,
    FrozenJson,
    Goal,
    GoalInterpretation,
    Ground,
    Idempotency,
    MemorySource,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Provenance,
    Reversibility,
    RiskLevel,
    SpanCoverage,
    ToolCost,
    ToolDefinition,
)

#: A fixed instant, so every horizon here is arithmetic a reader can check.
AT: Final = datetime(2026, 9, 13, 9, 0, tzinfo=UTC)

#: The goal every request here belongs to.
GOAL: Final = "g-1"

#: A finite ``Settings.episode_retention``, which ADR-0256 §1's rung 3 reads.
RETENTION: Final = timedelta(days=30)

#: The connected account an argument-free egress call is bound to, and therefore
#: the one member of its canonical destination set (ADR-0148 §2's third clause).
ACCOUNT: Final = BoundAccount(identity="work@example.com", reference="conn-1")


def a_tool(tool_id: str = "smtp", **overrides: object) -> ToolDefinition:
    """An egress declaration a policy can rule on."""
    fields: dict[str, object] = {
        "id": tool_id,
        "capability": "send_email",
        "description": "Send an email.",
        "risk_level": RiskLevel.LOW,
        "reversibility": Reversibility.REVERSIBLE,
        "side_effecting": True,
        "reads": (),
        "writes": (),
        "discloses": (),
        "cost": ToolCost(basis=CostBasis.FREE),
        "idempotency": Idempotency.NATURAL,
    }
    fields.update(overrides)
    return ToolDefinition(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def a_binding(**overrides: object) -> EgressBinding:
    """A binding whose spans carry no destination, so the account is the set.

    ADR-0148 §2's third clause, and the shape ADR-0254 §20's arm 54 is stated
    over: *"An egress declaration whose call carries ``parameters={}``"*.
    """
    fields: dict[str, object] = {
        "spans": (),
        "account": ACCOUNT,
        "transport_endpoint": "smtp://mail.example.com",
        "coverage": SpanCoverage.NOT_COVERED,
        "closed_loop": False,
        "planned_with_external_content": False,
    }
    fields.update(overrides)
    return EgressBinding(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def a_described_binding(parameters: Mapping[str, FrozenJson], **overrides: object) -> EgressBinding:
    """A binding whose spans describe ``parameters``, carrying no destination.

    ``ActionRequest`` refuses a call carrying an argument no span describes, and
    refuses a span whose ``extent`` is not its value's code-point count, so the
    spans are derived from the values themselves. They are ordered by argument
    as ``EgressBinding`` requires.

    The spans carry no ``destination``, so the canonical destination set is still
    the connected account (ADR-0148 §2's third clause) — which keeps the
    destination set one fact across every test here and leaves the *arguments*
    the only thing that varies.
    """
    spans = tuple(
        EgressSpan(
            argument=argument,
            provenance=DiscloserProvenance.USER_AUTHORED,
            extent=len(str(parameters[argument])),
        )
        for argument in sorted(parameters)
    )
    return a_binding(spans=spans, **overrides)


def a_goal(*, deadline: datetime | None) -> Goal:
    """A goal carrying ``deadline``, for the ladder's rung 2."""
    return Goal(
        id=GOAL,
        interpretation=(
            GoalInterpretation(
                revision=1,
                outcome="send the note",
                outcome_ground=Ground.USER_STATED,
                outcome_span="send the note",
                recorded_at=AT,
                raised_by="t-1",
            ),
        ),
        deadline=deadline,
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT),
        created_at=AT,
    )


#: The binding every request here carries unless a test names another, or names
#: ``None`` for a call that is not an egress call at all.
DEFAULT_BINDING: Final = a_binding()


def a_request(
    *,
    tool: ToolDefinition | None = None,
    parameters: Mapping[str, FrozenJson] | None = None,
    goal: str | None = GOAL,
    binding: EgressBinding | None = DEFAULT_BINDING,
    intended_action: str | None = None,
) -> ActionRequest:
    """The concrete request a `CONFIRM` was ruled over.

    ``binding=None`` is a request that is **not** an egress call, which is
    ADR-0254 §1's second proposal condition failing.

    ``intended_action`` is the act the step is an attempt at (ADR-0265 §1), which
    ADR-0266 §7's evidence route selects the governing quote by. ``None`` — the
    default — is met by that route in no case, so a ``MONEY`` member over such a
    request is unmet whatever the goal holds (ADR-0267 §7).
    """
    carried: Mapping[str, FrozenJson] = {} if parameters is None else parameters
    if binding is DEFAULT_BINDING and carried:
        # The default binding describes no argument, and a call carrying one it
        # does not describe is unconstructible, so the default derives spans.
        binding = a_described_binding(carried)
    return ActionRequest(
        tool=tool if tool is not None else a_tool(),
        parameters=carried,
        goal=goal,
        intended_action=intended_action,
        step_id="step-1",
        execution_id="e-1",
        egress_binding=binding,
    )


def a_decision(
    *, ruling: PermissionRuling | None = None, decided_at: datetime = AT
) -> PermissionDecision:
    """The recorded `CONFIRM` a proposal rides."""
    request = a_request()
    return PermissionDecision.from_request(
        request,
        ruling
        if ruling is not None
        else PermissionRuling(
            outcome=PermissionOutcome.CONFIRM, reason="this call transmits off-device"
        ),
        id="d-1",
        decided_at=decided_at,
    )
