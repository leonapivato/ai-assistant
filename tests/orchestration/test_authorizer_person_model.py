"""Authorizing the person model's calls: each needs the person's yes, by rule (ADR-0338 §8:5).

``set_profile``, ``pin`` and ``unpin`` are a source of *needs you* beside the policy's
confirm, the stand-in's and a candidate's *confirm*, with the policy's recorded allow as
the deciding decision (ADR-0321 §4:17). A deny still refuses one, and under a yes each
runs as any approved call does (§4).
"""

from __future__ import annotations

from typing import Any

import pytest
import test_authorizer as plain
import test_authorizer_yes as yes

from ai_assistant.core.types import AskedCall, PermissionOutcome, RiskLevel
from ai_assistant.orchestration.authorizer import Verdict
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
    # What a question about it shows and records (ADR-0321 §2:8).
    assert verdict.request is not None
    assert dict(verdict.request.parameters) == arguments


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
async def test_under_a_yes_a_pin_runs_as_any_approved_call(outcome: PermissionOutcome) -> None:
    """§8:5, ADR-0321 §4: the facts hold, the rule is the yes's, and an effect is claimed."""
    confirm_at = RiskLevel.LOW if outcome is PermissionOutcome.CONFIRM else None
    hub = yes._Hub(yes._LOOKUP, PIN, policy=FakeActionPolicy(confirm_at=confirm_at))
    asked = AskedCall(part=1, tool=PIN, values={"memory": "m:diet"})
    await hub.asked(asked)

    decided = await hub.authorize(
        yes._round((yes._call("c1", "pin", memory="m:diet"), yes._PART), yes=yes._yes())
    )

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED
    (allowed,) = decided.allowed
    assert allowed.asked == asked
    decision = allowed.call.decision
    assert decision.approval is not None
    assert decision.approved_part == yes._PART
    assert decision.effect is not None
    assert decision.ruling.outcome is PermissionOutcome.ALLOW


async def test_without_the_yes_the_same_pin_needs_you_again() -> None:
    hub = yes._Hub(yes._LOOKUP, PIN, policy=FakeActionPolicy(confirm_at=None))
    await hub.asked(AskedCall(part=1, tool=PIN, values={"memory": "m:diet"}))

    decided = await hub.authorize(yes._round((yes._call("c1", "pin", memory="m:diet"), None)))

    assert decided.verdicts[0].verdict is Verdict.NEEDS_YOU
    assert decided.allowed == ()
