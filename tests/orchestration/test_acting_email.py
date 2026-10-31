"""ADR-0357 §3 and §6:4 for ``email``: what its entry holds, and its repeats.

Over acting, the phases' working set and the canonical plan store, with ``tools``' own
declaration of ``email``: an email acting ran is recorded with what it sent, where and
how (§3:1), and an accidental repeat is refused as *already done* while a deliberate
repeat ADR-0306 §5:9 lets through runs (§6:4).
"""

from __future__ import annotations

from typing import Any, Final

import pytest
from test_acting import _AT, _Invoker, _round, _stage

from ai_assistant.core.types import (
    ActionRequest,
    CallOutcomeKind,
    DeliveryStatus,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    PlanningRound,
    ProposedCall,
    RecordedCall,
    ToolCall,
)
from ai_assistant.orchestration.acting import (
    ActedCall,
    ActedOutcome,
    ActedRound,
    AuthorizedCall,
    AuthorizedRound,
)
from ai_assistant.orchestration.authorizer import CallVerdict, RoundAuthorization, Verdict
from ai_assistant.orchestration.held_results import HeldResults
from ai_assistant.orchestration.phase_path import PhaseWorking
from ai_assistant.orchestration.planning import PlaceWindow, PlannedCall, PlannedRound
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


def _entry_of(
    outcome: ActedOutcome, *, effect: str | None = "e1", reason: str | None = None
) -> RecordedCall:
    """The entry of one email round whose acting came to ``outcome``."""
    call = ProposedCall(call_id="c1", name="email", arguments=_SENT)
    working = PhaseWorking(
        activation_id="activation",
        place=PlaceWindow(takes_message=True),
        conversation_id=None,
        trigger=None,
        owner_records=True,
        round_limit=3,
    )
    working.planned(
        PlannedRound(
            round=PlanningRound(id="round-1", recorded_at=_AT, calls=(call,)),
            labels=(),
            recorded=True,
            calls=(PlannedCall(call),),
        ),
        effects={"email": True},
    )
    working.latest.authorization = RoundAuthorization(
        activation_id="activation",
        round_id="round-1",
        verdicts=(CallVerdict("c1", Verdict.ALLOWED, decision_id="d1", effect_id="e1"),),
    )
    working.latest.acted = ActedRound(
        round_id="round-1",
        calls=(ActedCall(_email("d1", "e1"), outcome, reason=reason, effect_id=effect),),
    )
    (entry,) = working.call_entries(_AT)
    return entry


@pytest.mark.parametrize(
    ("outcome", "status", "reason"),
    [
        pytest.param(ActedOutcome.DONE, DeliveryStatus.SENT, None, id="sent"),
        pytest.param(
            ActedOutcome.UNKNOWN, DeliveryStatus.UNKNOWN, "the server's verdict was lost", id="lost"
        ),
        pytest.param(
            ActedOutcome.NOT_DONE, DeliveryStatus.FAILED, "the server refused it", id="failed"
        ),
    ],
)
def test_an_email_acting_ran_is_recorded_with_what_it_sent_where_and_how(
    outcome: ActedOutcome, status: DeliveryStatus, reason: str | None
) -> None:
    """§3:1-§3:3, §10's tests: the words, the platform and its recipients, and how it
    went with the reason; a lost acknowledgement is unknown, never sent."""
    entry = _entry_of(outcome, reason=reason)

    assert entry.capability == "email"
    assert entry.delivered is not None
    assert entry.delivered.words == "One o'clock?"
    assert (entry.delivered.went.channel_type, entry.delivered.went.instance_id) == (
        "email",
        "anna@example.invalid",
    )
    assert entry.delivered.status is status
    assert entry.delivered.reason == reason


def test_an_email_refused_before_it_was_claimed_holds_no_delivery() -> None:
    """§6:1: an accidental repeat's refusal sent nothing, so it records no delivery."""
    entry = _entry_of(ActedOutcome.NOT_DONE, effect=None, reason="already done")

    assert (entry.outcome, entry.delivered) == (CallOutcomeKind.NOT_DONE, None)
