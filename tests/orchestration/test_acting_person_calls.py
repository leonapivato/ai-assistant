"""Acting's part in the person model's calls (ADR-0338 §8:7, §11:2; ADR-0306 §3:3).

A runner on the own-records seam that refuses a call answers ``NotDone`` with its reason,
and acting finishes the call's record not done and reports that reason to planning.
Runners attached beside the composition root's seam reach their own capabilities, and
every other call still reaches the seam the stage was built with.
"""

from __future__ import annotations

import pytest
from test_acting import _approved, _Approving, _authorized, _now, _over, _round

from ai_assistant.core.types import (
    ActionRequest,
    PermissionDecision,
    ToolCall,
    ToolOutcome,
)
from ai_assistant.orchestration.acting import ActedOutcome, AuthorizedCall
from ai_assistant.orchestration.held_results import HeldResults
from ai_assistant.orchestration.person_calls import PIN, NotDone
from ai_assistant.testing import FakePlanStore

pytestmark = pytest.mark.anyio

_REASON = "only a current memory can be pinned"


async def test_a_call_its_runner_refuses_is_not_done_with_the_runners_reason() -> None:
    """§8:7: the reason reaches planning, and the record is finished with it."""
    plans = FakePlanStore(now=_now)

    acted = await _over(plans, _Approving(NotDone(reason=_REASON))).act(
        held=HeldResults(), authorized=_round(_authorized("remember", effect="e1"))
    )

    (one,) = acted.calls
    assert one.outcome is ActedOutcome.NOT_DONE
    assert one.reason == _REASON
    assert (one.effect_id, one.result_id, one.route) == ("e1", None, None)
    (record,) = await plans.activation_effects(["act-1"])
    assert record.outcome is ToolOutcome.FAILED
    assert record.reason == _REASON


def _pin() -> AuthorizedCall:
    """A ``pin`` allowed under the approval ``_approved`` names."""
    request = ActionRequest(tool=PIN, parameters={"memory": "m:diet"})
    template = _approved("remember").call.decision
    decision = PermissionDecision.from_request(
        request,
        template.ruling,
        id="d1",
        decided_at=template.decided_at,
        effect="e1",
        approval=template.approval,
        approved_part=template.approved_part,
    )
    return AuthorizedCall(ToolCall(request=request, decision=decision))


async def test_runners_added_beside_the_seam_reach_their_capabilities_alone() -> None:
    base = _Approving()
    added = _Approving(NotDone(reason=_REASON))
    stage = _over(FakePlanStore(now=_now), base)
    stage.add_own_records({"pin": added})
    remember = _approved("remember", decision="d2", effect="e2", part=2)

    acted = await stage.act(held=HeldResults(), authorized=_round(_pin(), remember))

    pinned, remembered = acted.calls
    assert (pinned.outcome, pinned.reason) == (ActedOutcome.NOT_DONE, _REASON)
    assert remembered.outcome is ActedOutcome.DONE
    assert [str(call.request.tool.capability) for call in added.run_calls] == ["pin"]
    assert [str(call.request.tool.capability) for call in base.run_calls] == ["remember"]


def test_attaching_no_runner_is_refused() -> None:
    stage = _over(FakePlanStore(now=_now), _Approving())

    with pytest.raises(ValueError, match="at least one"):
        stage.add_own_records({})
