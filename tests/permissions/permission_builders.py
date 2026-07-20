"""Builders shared by the two permission conformance suites (ADR-0021).

``ActionPolicy`` and ``AuditTrail`` are separate contracts, but both are stated
in terms of the same three values — a :class:`ToolDefinition`, the
:class:`ActionRequest` wrapping it, and the :class:`PermissionDecision` a ruling
becomes. Building those in one place keeps the two suites arranging *identical*
subjects, which matters most for the fields whose equality the resolution
invariant turns on.

Not a conformance suite itself: nothing here asserts anything.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ai_assistant.core.types import (
    ActionRequest,
    CostBasis,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)

#: A fixed instant, so ordering assertions are about the values under test
#: rather than about how fast the suite runs.
AT = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


def tool(tool_id: str = "smtp", **overrides: object) -> ToolDefinition:
    """Build a valid definition, overriding whichever field a test is about.

    The base is deliberately the *least* severe declaration that is still
    representable: ``LOW`` risk, ``REVERSIBLE``, disclosing nothing, at a known
    (free) cost. Monotonicity tests raise one field at a time from here, so
    "everything else held equal" is true by construction rather than by care.

    ``side_effecting`` is ``True`` even though the base tool writes and discloses
    nothing, because ``ToolDefinition`` refuses a non-side-effecting tool that is
    anything but ``REVERSIBLE`` — a base that flipped it would make the
    reversibility ladder unrepresentable at its first rung.
    """
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
        "idempotency": Idempotency.NONE,
    }
    fields.update(overrides)
    return ToolDefinition(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def action(**overrides: object) -> ActionRequest:
    """Build a request, overriding ``tool``, ``parameters`` or ``step_id``."""
    fields: dict[str, object] = {"tool": tool(), "step_id": "step-1"}
    fields.update(overrides)
    return ActionRequest(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def ruling(
    outcome: PermissionOutcome = PermissionOutcome.CONFIRM,
    **overrides: object,
) -> PermissionRuling:
    """Build a ruling with a visible reason."""
    fields: dict[str, object] = {"outcome": outcome, "reason": f"because it is {outcome}"}
    fields.update(overrides)
    return PermissionRuling(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def decision(
    decision_id: str = "d-1",
    *,
    request: ActionRequest | None = None,
    ruled: PermissionRuling | None = None,
    decided_at: datetime | None = None,
    resolves: str | None = None,
) -> PermissionDecision:
    """Build a decision through ``from_request``, the sanctioned construction path.

    Going through the factory rather than the constructor is deliberate even in
    a builder: it is what the contract asks callers to use, so the suites
    exercise the path implementations will actually be handed. It also means a
    builder cannot arrange a decision whose subject disagrees with its request,
    which is a shape the contract makes unreachable and a suite should not be
    able to fake.
    """
    return PermissionDecision.from_request(
        request if request is not None else action(),
        ruled if ruled is not None else ruling(),
        id=decision_id,
        decided_at=decided_at if decided_at is not None else AT,
        resolves=resolves,
    )
