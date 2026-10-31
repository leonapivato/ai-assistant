"""ADR-0357 §6:4 for ``email``: not safe to repeat, so acting's backstop refuses a repeat.

Over acting and the canonical plan store, with ``tools``' own declaration of ``email``:
an accidental repeat is refused as *already done*, and a deliberate repeat ADR-0306 §5:9
lets through runs.
"""

from __future__ import annotations

from typing import Any, Final

from test_acting import _AT, _Invoker, _round, _stage

from ai_assistant.core.types import (
    ActionRequest,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    ToolCall,
)
from ai_assistant.orchestration.acting import ActedOutcome, AuthorizedCall, AuthorizedRound
from ai_assistant.orchestration.held_results import HeldResults
from ai_assistant.testing import FakePlanStore
from ai_assistant.tools.send_email import EMAIL

_SENT: Final = {
    "to": ["anna@example.invalid"],
    "subject": "Lunch",
    "words": "One o'clock?",
    "from": "user",
}


def _email(decision: str, effect: str, **fields: Any) -> AuthorizedCall:
    request = ActionRequest(tool=EMAIL, parameters=_SENT)
    allowed = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="the user said yes"),
        id=decision,
        decided_at=_AT,
        effect=effect,
    )
    return AuthorizedCall(ToolCall(request=request, decision=allowed), **fields)


async def test_an_accidental_repeat_is_refused_and_a_deliberate_one_runs() -> None:
    """§6:4, §10's test: refused exactly where ADR-0306 §5:9-§5:11 refuse it."""
    plans = FakePlanStore(now=lambda: _AT)
    invoker = _Invoker()
    earlier = AuthorizedRound(activation_id="act-0", round_id="r0", calls=(_email("d0", "e0"),))
    await _stage(plans, invoker).act(held=HeldResults(), authorized=earlier)

    refused = await _stage(plans, invoker).act(
        held=HeldResults(), authorized=_round(_email("d1", "e1"), stories=("act-0",))
    )
    repeated = await _stage(plans, invoker).act(
        held=HeldResults(),
        authorized=_round(_email("d2", "e2", deliberate_repeat=True), stories=("act-0",)),
    )

    (accidental,) = refused.calls
    assert accidental.outcome is ActedOutcome.NOT_DONE
    assert accidental.reason is not None
    assert "already done" in accidental.reason
    (deliberate,) = repeated.calls
    assert deliberate.outcome is ActedOutcome.DONE
    assert len(invoker.calls) == 2
