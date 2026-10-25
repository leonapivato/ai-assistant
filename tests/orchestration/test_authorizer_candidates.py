"""Authorizing a ``remember`` that records a candidate (ADR-0329 §5:2-§5:4, §5:6).

No ``MemoryPolicy``, which the stage no longer holds: *confirm* needs you by rule, and
under a yes the call runs as any approved call does. ADR-0328 §13's interim, under which
remembering passed ``MemoryPolicy`` here, is retired with the composition root's switch.
"""

from __future__ import annotations

from typing import Any

import pytest
import test_authorizer as plain
import test_authorizer_yes as yes

from ai_assistant.core.types import AskedCall, PermissionOutcome, RiskLevel
from ai_assistant.orchestration.authorizer import Verdict
from ai_assistant.orchestration.remembering import (
    EPISODE_ARGUMENT,
    OUTSIDE_CONTENT_ARGUMENT,
    REMEMBER_CANDIDATE,
)
from ai_assistant.testing import FakeActionPolicy


def _candidate(**fields: Any) -> dict[str, Any]:
    return {"fact": "likes window seats", "why": "travel", "rests_on_input": True, **fields}


def _hub(**knobs: Any) -> plain._Hub:
    return plain._Hub(REMEMBER_CANDIDATE, **knobs)


async def test_a_candidate_is_filled_by_the_hub() -> None:
    """§3:4: the hub fills the episode and the mark; §5:6: no MemoryPolicy rules on it."""
    hub = _hub()

    decided = await hub.authorize(plain._round(plain._call("c1", "remember", **_candidate())))

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED
    assert verdict.effect_id == "effect:1"
    (allowed,) = decided.allowed
    assert dict(allowed.call.request.parameters) == {
        **_candidate(),
        EPISODE_ARGUMENT: plain._EPISODE,
        OUTSIDE_CONTENT_ARGUMENT: False,
    }


async def test_a_candidate_with_confirm_set_needs_you_by_rule() -> None:
    """§5:2: by rule, with no model, and the policy's allow does not let it run."""
    hub = _hub()

    decided = await hub.authorize(
        plain._round(plain._call("c1", "remember", **_candidate(confirm=True)))
    )

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.NEEDS_YOU
    assert verdict.reason == "the user is asked to confirm this wording before it is kept"
    assert decided.allowed == ()
    # What a question about it shows and records: confirm among the values (§5:1).
    assert verdict.request is not None
    assert verdict.request.parameters["confirm"] is True


async def test_a_candidate_with_confirm_unset_runs() -> None:
    hub = _hub()

    decided = await hub.authorize(
        plain._round(plain._call("c1", "remember", **_candidate(confirm=False)))
    )

    assert decided.verdicts[0].verdict is Verdict.ALLOWED


async def test_a_deny_still_refuses_a_candidate() -> None:
    """The policy is asked first, as for every call (ADR-0306 §4:1)."""
    hub = _hub(policy=FakeActionPolicy(deny_at=RiskLevel.LOW))

    decided = await hub.authorize(
        plain._round(plain._call("c1", "remember", **_candidate(confirm=True)))
    )

    assert decided.verdicts[0].verdict is Verdict.NOT_DONE


async def test_a_candidate_resting_on_nothing_is_not_done() -> None:
    """§3:1: what it rests on is one or more of its parts."""
    hub = _hub()

    decided = await hub.authorize(
        plain._round(plain._call("c1", "remember", fact="likes window seats", why="travel"))
    )

    assert decided.verdicts[0].verdict is Verdict.NOT_DONE
    assert decided.allowed == ()


# --- under a yes (§5:3) ------------------------------------------------------------------


def _asked_candidate(**fields: Any) -> AskedCall:
    return AskedCall(
        part=1,
        tool=REMEMBER_CANDIDATE,
        values={
            **_candidate(confirm=True, **fields),
            EPISODE_ARGUMENT: f"activation:{yes._ASKING}",
            OUTSIDE_CONTENT_ARGUMENT: False,
        },
    )


def _yes_hub(policy: FakeActionPolicy | None = None) -> yes._Hub:
    return yes._Hub(yes._LOOKUP, yes._BOOK, REMEMBER_CANDIDATE, policy=policy)


@pytest.mark.parametrize(
    "outcome", [PermissionOutcome.ALLOW, PermissionOutcome.CONFIRM], ids=["allow", "confirm"]
)
async def test_a_confirmed_candidate_runs_under_the_yes(
    outcome: PermissionOutcome,
) -> None:
    """§5:3: confirm is a source of *needs you* the yes answers; the policy's allow decides.

    An allow is recorded naming the approval, and a confirm is resolved on route (a)
    (ADR-0321 §4:7, §4:17); either way an effect record is claimed, which the
    candidate is joined to (§3:3).
    """
    hub = _yes_hub(
        FakeActionPolicy(confirm_at=RiskLevel.LOW if outcome is PermissionOutcome.CONFIRM else None)
    )
    asked = _asked_candidate()
    await hub.asked(asked)

    decided = await hub.authorize(
        yes._round(
            (yes._call("c1", "remember", **_candidate(confirm=True)), yes._PART), yes=yes._yes()
        )
    )

    (verdict,) = decided.verdicts
    assert verdict.verdict is Verdict.ALLOWED
    (allowed,) = decided.allowed
    assert allowed.asked == asked
    assert dict(allowed.call.request.parameters) == dict(asked.values)
    decision = allowed.call.decision
    assert decision.approval is not None
    assert decision.effect is not None
    assert decision.ruling.outcome is PermissionOutcome.ALLOW


async def test_without_the_yes_the_same_candidate_needs_you_again() -> None:
    """§5:4: a no, a change or an unanswered question records nothing."""
    hub = _yes_hub()
    await hub.asked(_asked_candidate())

    decided = await hub.authorize(
        yes._round((yes._call("c1", "remember", **_candidate(confirm=True)), None))
    )

    assert decided.verdicts[0].verdict is not Verdict.ALLOWED
    assert decided.allowed == ()
