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
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    ToolCall,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
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


class _Runner:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    async def run(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        return ToolResult(outcome=ToolOutcome.SUCCEEDED)


async def test_each_call_reaches_its_capabilitys_runner_and_no_other() -> None:
    runner = _Runner()
    runners = {"remember_fact": runner}
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
