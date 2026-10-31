"""ADR-0357 §2:5-§2:10 in authorizing: ``email``'s own checks, and its yes.

Over the stage and the canonical fakes, with ``tools``' own declaration of ``email``:
what comes back before any ruling, and that an email from the user's address never
runs without their yes, whatever the policy says.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import pytest
from test_authorizer import _call, _Hub, _round

from ai_assistant.core.types import PermissionOutcome, PermissionRuling
from ai_assistant.orchestration.authorizer import Verdict
from ai_assistant.tools.send_email import EMAIL

if TYPE_CHECKING:
    from ai_assistant.core.types import ActionRequest, PermissionDecision

_ADDRESS: Final = "anna@example.invalid"


class _Allowing:
    """A policy that allows every call: what an email from the user's address beats."""

    async def decide(self, request: ActionRequest) -> PermissionRuling:
        del request
        return PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed")

    async def resolve(self, confirmed: PermissionDecision, *, approved: bool) -> PermissionRuling:
        del confirmed, approved
        return PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed")


def _email(**arguments: Any) -> dict[str, Any]:
    return {"to": [_ADDRESS], "subject": "Lunch", "words": "One o'clock?", **arguments}


async def _decided(policy: object | None = None, **arguments: Any) -> Any:
    hub = _Hub(EMAIL, policy=policy)  # type: ignore[arg-type]  # a policy of the test's own
    decided = await hub.authorize(_round(_call("c1", "email", **_email(**arguments))))
    (verdict,) = decided.verdicts
    return hub, decided, verdict


async def test_an_email_from_the_users_address_never_runs_without_their_yes() -> None:
    """§2:10, §10's test: whatever allows it, it needs the user, and nothing runs."""
    hub, decided, verdict = await _decided(_Allowing(), **{"from": "user"})

    assert verdict.verdict is Verdict.NEEDS_YOU
    assert verdict.reason is not None
    assert "user's own address" in verdict.reason
    assert verdict.request is not None  # a question about it shows the exact call
    assert decided.allowed == ()
    # The policy's allow stays the deciding decision, recorded as ruled.
    assert verdict.decision_id is not None
    assert (await hub.trail.get(verdict.decision_id)) is not None


@pytest.mark.parametrize("sender", [None, "assistant"])
async def test_an_email_from_the_assistants_address_comes_back_unruled(sender: str | None) -> None:
    """§2:9: left out, it is sent from the assistant's address where one is connected; none
    is, so it comes back saying only the user's is available, and no ruling is sought."""
    arguments = {} if sender is None else {"from": sender}
    _, decided, verdict = await _decided(_Allowing(), **arguments)

    assert verdict.verdict is Verdict.NOT_DONE
    assert verdict.reason is not None
    assert "only the user's address is available" in verdict.reason
    assert verdict.decision_id is None
    assert decided.allowed == ()


@pytest.mark.parametrize(
    ("recipients", "where"),
    [
        pytest.param({"to": "Anna"}, "'to' recipient 1", id="a-name-in-to"),
        pytest.param({"to": [_ADDRESS, "Anna Rossi"]}, "'to' recipient 2", id="second"),
        pytest.param({"cc": ["the user"]}, "'cc' recipient 1", id="cc"),
        pytest.param({"bcc": "anna at home"}, "'bcc' recipient 1", id="bcc"),
    ],
)
async def test_a_recipient_with_no_known_address_comes_back_before_the_ruling(
    recipients: dict[str, Any], where: str
) -> None:
    """§2:7: resolved only from an ADR-0148 §5:2 source, before the ruling; none is
    wired, so it comes back saying an address is needed, and nothing is guessed."""
    _, decided, verdict = await _decided(_Allowing(), **{"from": "user", **recipients})

    assert verdict.verdict is Verdict.NOT_DONE
    assert verdict.reason is not None
    assert where in verdict.reason
    assert "address" in verdict.reason
    assert verdict.decision_id is None
    assert decided.allowed == ()


async def test_an_attachment_comes_back_and_sends_nothing() -> None:
    """§2:8: what can be attached is the email tool's, and nothing can be yet."""
    _, decided, verdict = await _decided(
        _Allowing(), **{"from": "user", "attachments": ["the menu"]}
    )

    assert verdict.verdict is Verdict.NOT_DONE
    assert verdict.reason is not None
    assert "attached" in verdict.reason
    assert decided.allowed == ()


async def test_a_sender_that_is_neither_address_comes_back() -> None:
    _, _, verdict = await _decided(_Allowing(), **{"from": "Anna"})
    assert verdict.verdict is Verdict.NOT_DONE
    assert verdict.reason is not None
    assert "'from'" in verdict.reason


async def test_a_deny_still_refuses_an_email_from_the_users_address() -> None:
    """§2:10 adds a yes; it takes no refusal away (ADR-0321 §2:10)."""

    class _Denying(_Allowing):
        async def decide(self, request: ActionRequest) -> PermissionRuling:
            del request
            return PermissionRuling(outcome=PermissionOutcome.DENY, reason="no")

    _, _, verdict = await _decided(_Denying(), **{"from": "user"})
    assert verdict.verdict is Verdict.NOT_DONE
