"""Authorizing the person model's calls: each needs the person's yes, by rule (ADR-0338 §8:5).

``set_profile``, ``pin`` and ``unpin`` are a source of *needs you* beside the policy's
confirm, the stand-in's and a candidate's *confirm*, with the policy's recorded allow as
the deciding decision (ADR-0321 §4:17). A deny still refuses one, and under a ticket each
runs as any approved call does (ADR-0361 §5:4).
"""

from __future__ import annotations

from typing import Any

import pytest
import test_authorizer as plain
import test_authorizer_approvals as cards

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    PermissionOutcome,
    RequestedCall,
    RiskLevel,
    TapOnCard,
)
from ai_assistant.orchestration.authorizer import CallToAuthorize, Verdict
from ai_assistant.orchestration.person_calls import PIN, SET_PROFILE, UNPIN
from ai_assistant.testing import FakeActionPolicy

#: Each call, with arguments it is proposed with.
_CALLS: list[tuple[str, dict[str, Any]]] = [
    ("set_profile", {"field": "address", "value": "Robin"}),
    ("pin", {"memory": "m:diet"}),
    ("unpin", {"memory": "m:diet"}),
]


@pytest.mark.parametrize(("name", "arguments"), _CALLS, ids=[name for name, _ in _CALLS])
async def test_each_call_needs_the_persons_yes_by_rule(
    name: str, arguments: dict[str, Any]
) -> None:
    """§8:5: the policy allows, and the call still needs you; nothing runs."""
    hub = plain._Hub(SET_PROFILE, PIN, UNPIN)

    decided = await hub.authorize(plain._round(plain._call("c1", name, **arguments)))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NEEDS_YOU
    assert verdict.reason == "a change to the person's profile or pins runs only on their yes"
    assert decided.allowed == ()
    # ADR-0321 §4:17: the policy's recorded allow is the deciding decision.
    deciding = await plain._recorded(hub.trail, verdict.decision_id)
    assert deciding.ruling.outcome is PermissionOutcome.ALLOW


async def test_a_deny_still_refuses_one() -> None:
    """ADR-0306 §4:1: the policy is asked first, as for every call."""
    hub = plain._Hub(SET_PROFILE, PIN, UNPIN, policy=FakeActionPolicy(deny_at=RiskLevel.LOW))

    decided = await hub.authorize(plain._round(plain._call("c1", "pin", memory="m:diet")))

    assert decided.verdicts[0].verdict is Verdict.NOT_DONE


async def test_where_none_is_offered_a_call_names_no_tool_and_is_not_done() -> None:
    """§11:2: with no store wired no declaration is advertised, so selection finds none."""
    hub = plain._Hub()

    decided = await hub.authorize(plain._round(plain._call("c1", "pin", memory="m:diet")))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NOT_DONE
    assert verdict.reason == "no tool satisfies this capability"


@pytest.mark.parametrize(
    "outcome", [PermissionOutcome.ALLOW, PermissionOutcome.CONFIRM], ids=["allow", "confirm"]
)
async def test_under_a_ticket_a_pin_runs_as_any_approved_call(outcome: PermissionOutcome) -> None:
    """§8:5, ADR-0361 §5:4: the ticket's checks hold, the rule is the yes's, an effect claimed."""
    confirm_at = RiskLevel.LOW if outcome is PermissionOutcome.CONFIRM else None
    hub = cards._Hub(tools=(PIN,), policy=FakeActionPolicy(confirm_at=confirm_at))
    request = await cards._approved(
        hub.plans, call=RequestedCall(tool=PIN, values={"memory": "m:diet"})
    )

    decided = await hub.stage.authorize(
        cards._ticket_round(hub, request, tickets=frozenset({str(request.id)}))
    )

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED, verdict.reason
    (allowed,) = decided.allowed
    decision = allowed.call.decision
    assert decision.approval is not None
    assert isinstance(decision.approval.how, TapOnCard)
    assert decision.approved_part is None
    assert decision.effect is not None
    assert decision.ruling.outcome is PermissionOutcome.ALLOW


async def test_without_the_ticket_the_same_pin_needs_you_again() -> None:
    hub = cards._Hub(tools=(PIN,), policy=FakeActionPolicy(confirm_at=None))
    await cards._approved(hub.plans, call=RequestedCall(tool=PIN, values={"memory": "m:diet"}))

    decided = await hub.authorize(
        CallToAuthorize(plain._call("c1", "pin", memory="m:diet")), person=OWNER_PERSON_ID
    )

    assert decided.verdicts[0].verdict is Verdict.NEEDS_YOU
    assert decided.allowed == ()
