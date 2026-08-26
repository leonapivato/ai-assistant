"""The composition root's half of ADR-0192 §9's recovery wiring.

§9 makes two claims about this seam, and they fail apart. **One object under two
faces**: the recovery scan is handed the very audit store the runner records into,
as an ``AuditTrail`` for the one query it owes and as an ``InvocationCompleter``
for the write — two stores here would complete claims nobody appended while
leaving the real ones open. And **not the third face**: ``claim_invocation`` is
the seam's act, so the scan is given a dependency that cannot express it, which is
what makes "the scan never claims" a type rather than a promise this root is
trusted to keep (ADR-0029 §1).

Real stores in a temp directory, as everything in ``tests/app`` is: the wiring is
the subject, and a fake wired correctly proves nothing about the production one.
"""

from __future__ import annotations

import ast
import inspect
import typing
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.protocols import AuditTrail, InvocationCompleter, PlanStore
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
    ToolOutcome,
)
from ai_assistant.orchestration import RecoveryScan
from ai_assistant.orchestration import recovery as recovery_module

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.orchestration import Engine

AT = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)

STEP = "step-1"
DECISION = "d-1"

SEND_MAIL = ToolDefinition(
    id="smtp",
    capability="send_email",
    description="Send an email.",
    risk_level=RiskLevel.HIGH,
    reversibility=Reversibility.IRREVERSIBLE,
    side_effecting=True,
    reads=(),
    writes=(),
    discloses=(),
    cost=ToolCost(basis=CostBasis.FREE),
    idempotency=Idempotency.NONE,
)


def _scan_of(engine: Engine) -> RecoveryScan:
    """The scan the root built, read off the engine it was handed to."""
    scan = engine._recovery
    assert isinstance(scan, RecoveryScan)
    return scan


async def _a_crash_left_a_claim_open(engine: Engine) -> tuple[str, str]:
    """Seed the durable state a process that died mid-call leaves behind.

    A recorded ``ALLOW``, a claim under it with no completion beside it, and a step
    durably ``RUNNING`` naming that decision as its ``approval_ref`` — which is
    every fact ADR-0192 §3's recovery rule is written against, and nothing more.

    Returns:
        The execution's id and the open claim's id.
    """
    plans, trail = engine._plans, engine._trail
    await plans.save_goal(
        Goal(
            id="g-1",
            statement="send the note",
            provenance=Provenance(
                source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT
            ),
            created_at=AT,
        )
    )
    await plans.save_plan(
        ActionPlan(
            id="p-1",
            goal_id="g-1",
            steps=(PlanStep(id=STEP, intent="send the note", capability="send_email"),),
            created_at=AT,
        )
    )
    state = await plans.start_execution("p-1")
    request = ActionRequest(
        tool=SEND_MAIL,
        parameters={"to": "someone@example.com"},
        step_id=STEP,
        execution_id=state.id,
    )
    decision = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="because the user said so"),
        id=DECISION,
        decided_at=AT,
    )
    await trail.record(decision)
    claim = await trail.claim_invocation(decision=decision)  # type: ignore[attr-defined]  # one store, three faces
    await plans.commit_transition(
        StepTransition(
            execution_id=state.id,
            step_id=STEP,
            to_status=StepStatus.RUNNING,
            expected_version=state.version,
            bound_tool=SEND_MAIL.id,
            approval_ref=DECISION,
        )
    )
    return state.id, str(claim.id)


async def test_the_root_hands_the_scan_one_store_under_two_faces(tmp_path: Path) -> None:
    """The very object the runner records into, passed twice (ADR-0192 §9).

    Not two objects that happen to agree: an ``AuditTrail`` and an
    ``InvocationCompleter`` over separate stores would each work, and disagree — the
    failure that looks like nothing at all. Structural typing is what lets one
    object serve both seams, and the narrowing is the annotation on the scan's own
    constructor rather than anything this root does.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        scan = _scan_of(engine)
        # Collected as ``object`` so the identity is asserted rather than argued
        # about: the two faces are unrelated Protocols, and one object satisfying
        # both is precisely the claim under test.
        faces: list[object] = [scan._trail, scan._completer]
        assert all(face is engine._trail for face in faces)
        assert scan._plans is engine._plans
    finally:
        await engine.aclose()


def test_the_scan_is_typed_to_the_narrow_face_and_never_claims() -> None:
    """The dependency cannot express the call, and the code does not attempt it.

    Two halves, because they fail apart. The **annotation** is what ADR-0192 §9
    means by making the distinction a type: an earlier draft of that clause injected
    the ledger and defended it with a wiring test, and ADR-0029 §1's rule against
    widening a surface past its consumers' concern decided it the other way. The
    **AST walk** is the second half: a parameter typed to the narrow face still
    receives an object that satisfies the wide one, so a call to
    ``claim_invocation`` would type-check against ``Any`` and run.

    Walked rather than searched as text, because this module's own docstrings say
    ``claim_invocation`` in so many words — naming what the scan may not do is how
    the reason survives, and a substring guard would forbid saying it.
    """
    # The three Protocols are ``TYPE_CHECKING``-only imports in the module under
    # test — `orchestration` consumes contracts and imports no implementation — so
    # the namespace they resolve in has to be supplied here.
    hints = typing.get_type_hints(
        RecoveryScan.__init__,
        localns={
            "AuditTrail": AuditTrail,
            "InvocationCompleter": InvocationCompleter,
            "PlanStore": PlanStore,
        },
    )
    assert hints["completer"] is InvocationCompleter
    assert hints["trail"] is AuditTrail

    tree = ast.parse(inspect.getsource(recovery_module))
    named = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)} | {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    }
    assert "claim_invocation" not in named
    assert "complete_invocation" in named, "the guard is watching the right module"


async def test_a_started_engine_completes_the_claim_a_crash_left_open(tmp_path: Path) -> None:
    """End to end through the real composition: ``start`` resolves what a crash left.

    ADR-0014 §4 puts the scan "at startup"; the hub calls ``Engine.start`` at step 4
    of its own startup and begins accepting at step 6, which is what makes §4's
    precondition — no executor is live for those states — a fact about the listener.
    Driving ``start`` rather than the scan directly is what proves the two are
    joined: a scan the root built and nothing ever called would pass every identity
    assertion above and recover nothing.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        execution_id, claim_id = await _a_crash_left_a_claim_open(engine)

        await engine.start()

        rows = await engine._trail.export_invocations()
        completions = [row.invocation for row in rows if row.invocation.completes is not None]
        assert [row.completes for row in completions] == [claim_id]
        assert completions[0].outcome is ToolOutcome.INDETERMINATE
        assert completions[0].failure_kind is None
        assert completions[0].incurred_cost is not None
        assert completions[0].incurred_cost.basis is CostBasis.UNKNOWN
        assert await engine._trail.open_invocations(decision_id=DECISION) == []

        recovered = await engine._plans.get_execution(execution_id)
        assert recovered is not None
        step = recovered.step(STEP)
        assert step is not None
        assert step.status is StepStatus.INDETERMINATE
        assert step.failure is not None
        assert step.failure.kind is None, "recovery had no ToolResult to classify from"
    finally:
        await engine.aclose()
