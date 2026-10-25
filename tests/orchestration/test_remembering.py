"""Acting's own-records seam, filled with ``remember``'s runner (ADR-0306 §3:3).

``remember`` records a candidate (ADR-0329 §§3-5), and its declaration, its runner and
its lookup are ``test_remembering_candidates``'s. ADR-0328 §13's interim, under which a
call wrote a memory, is retired with the composition root's switch, and with it the
runner, the proposal and the write-time question this file held.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

from ai_assistant.core.types import (
    ActionRequest,
    Approval,
    ApprovalEnd,
    ApprovalGiven,
    ApprovalGiver,
    AskedCall,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    QuestionPart,
    ToolCall,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
    YesToQuestion,
)
from ai_assistant.orchestration.acting import OwnRecordsByCapability
from ai_assistant.orchestration.remembering import (
    EPISODE_ARGUMENT,
    FACT_ARGUMENT,
    INPUT_ARGUMENT,
    OUTSIDE_CONTENT_ARGUMENT,
    REMEMBER_CANDIDATE,
    WHY_ARGUMENT,
)

_AT: Final = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
_YES_AT: Final = datetime(2026, 10, 12, 14, 15, tzinfo=UTC)
_QUESTION: Final = QuestionPart(round="round:asked", part=1)


def _arguments() -> dict[str, Any]:
    return {
        FACT_ARGUMENT: "The user likes green tea.",
        WHY_ARGUMENT: "a standing preference",
        INPUT_ARGUMENT: True,
        EPISODE_ARGUMENT: "activation:act-1",
        OUTSIDE_CONTENT_ARGUMENT: False,
    }


def _call(*, tool: Any = REMEMBER_CANDIDATE) -> ToolCall:
    request = ActionRequest(tool=tool, parameters=_arguments())
    ruling = PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed")
    decision = PermissionDecision.from_request(
        request, ruling, id="decision:1", decided_at=_AT, effect="effect:1"
    )
    return ToolCall(request=request, decision=decision)


def _approved_call() -> ToolCall:
    """A remember allowed under a yes: its decision names the approval and its part."""
    request = ActionRequest(tool=REMEMBER_CANDIDATE, parameters=_arguments())
    ruling = PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed")
    decision = PermissionDecision.from_request(
        request,
        ruling,
        id="decision:1",
        decided_at=_AT,
        effect="effect:1",
        approval=Approval(
            who=ApprovalGiver.USER_THROUGH_HUB_CHAT,
            how=YesToQuestion(activation_id="act-0", round=_QUESTION.round),
            covers=(_QUESTION,),
            given=ApprovalGiven(activation_id="act-1", at=_YES_AT),
            ends=ApprovalEnd.WHEN_USED,
        ),
        approved_part=_QUESTION,
    )
    return ToolCall(request=request, decision=decision)


class _Runner:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    async def run(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        return ToolResult(outcome=ToolOutcome.SUCCEEDED)


async def test_each_call_reaches_its_capabilitys_runner_and_no_other() -> None:
    runner = _Runner()
    runners = {"remember": runner}
    seam = OwnRecordsByCapability(runners)
    runners.clear()

    held = await seam.run(_call())
    other = REMEMBER_CANDIDATE.model_copy(update={"id": "other", "capability": "other"})
    unheld = await seam.run(_call(tool=other))

    assert isinstance(held, ToolResult)
    assert isinstance(unheld, ToolResult)
    assert held.outcome is ToolOutcome.SUCCEEDED
    assert len(runner.calls) == 1
    assert unheld.outcome is ToolOutcome.FAILED
    assert unheld.failure is not None
    assert unheld.failure.kind is ToolFailureKind.INVALID_REQUEST


class _Approving:
    """An own-records runner that takes the asked call a yes approved."""

    def __init__(self) -> None:
        self.approved: list[tuple[ToolCall, AskedCall]] = []

    async def run(self, call: ToolCall) -> ToolResult:
        del call
        return ToolResult(outcome=ToolOutcome.FAILED)

    async def run_approved(self, call: ToolCall, asked: AskedCall) -> ToolResult:
        self.approved.append((call, asked))
        return ToolResult(outcome=ToolOutcome.SUCCEEDED)


async def test_an_approved_call_reaches_a_runner_that_takes_its_asked_call() -> None:
    """ADR-0329 §5:3: the asked call reaches the runner that takes one, and no other."""
    approving = _Approving()
    plain = _Runner()
    other = REMEMBER_CANDIDATE.model_copy(update={"id": "other", "capability": "other"})
    seam = OwnRecordsByCapability({"remember": approving, "other": plain})
    asked = AskedCall(part=1, tool=REMEMBER_CANDIDATE, values=_arguments())

    taken = await seam.run_approved(_approved_call(), asked)
    run = await seam.run_approved(_call(tool=other), asked)

    assert isinstance(taken, ToolResult)
    assert taken.outcome is ToolOutcome.SUCCEEDED
    assert [one for _, one in approving.approved] == [asked]
    assert isinstance(run, ToolResult)
    assert run.outcome is ToolOutcome.SUCCEEDED
    assert len(plain.calls) == 1
