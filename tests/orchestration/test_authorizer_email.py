"""ADR-0364 §9:7-§9:14 in authorizing: ``send_email``'s own checks, and its approval.

Over the stage and the canonical fakes, with ``tools``' own declaration of ``send_email``:
what comes back before any ruling, and that every email needs approval by rule, from
whichever account, whatever the policy says (§9:12). ``from`` reaches authorizing as the
account planning's check mapped its ``L`` label to, the person's own (§9:11).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import pytest
from test_authorizer import _call, _Hub, _round

from ai_assistant.core.types import PermissionOutcome, PermissionRuling
from ai_assistant.orchestration.authorizer import Verdict
from ai_assistant.tools.send_email import EMAIL, FROM_THE_PERSONS_ACCOUNT

if TYPE_CHECKING:
    from ai_assistant.core.types import ActionRequest, PermissionDecision

_ADDRESS: Final = "anna@example.invalid"


class _Allowing:
    """A policy that allows every call: what the rule that every email needs approval beats."""

    async def decide(self, request: ActionRequest) -> PermissionRuling:
        del request
        return PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed")

    async def resolve(self, confirmed: PermissionDecision, *, approved: bool) -> PermissionRuling:
        del confirmed, approved
        return PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed")


def _email(**arguments: Any) -> dict[str, Any]:
    return {
        "from": FROM_THE_PERSONS_ACCOUNT,
        "to": [_ADDRESS],
        "subject": "Lunch",
        "words": "One o'clock?",
        **arguments,
    }


async def _decided(policy: object | None = None, **arguments: Any) -> Any:
    hub = _Hub(EMAIL, policy=policy)  # type: ignore[arg-type]  # a policy of the test's own
    decided = await hub.authorize(_round(_call("c1", "send_email", **_email(**arguments))))
    (verdict,) = decided.verdicts
    return hub, decided, verdict


async def test_every_email_needs_approval_whatever_allows_it() -> None:
    """§9:12, §14:4: whatever allows it, it needs approval by rule, and nothing runs."""
    hub, decided, verdict = await _decided(_Allowing())

    assert verdict.verdict is Verdict.NEEDS_YOU
    assert verdict.reason is not None
    assert "every email needs approval" in verdict.reason
    assert decided.allowed == ()
    # The policy's allow stays the deciding decision, recorded as ruled.
    assert verdict.decision_id is not None
    assert (await hub.trail.get(verdict.decision_id)) is not None


@pytest.mark.parametrize(
    ("recipients", "where"),
    [
        pytest.param({"to": "Anna"}, "'to' recipient 1", id="a-name-in-to"),
        pytest.param({"to": [_ADDRESS, "Anna Rossi"]}, "'to' recipient 2", id="second"),
        pytest.param({"cc": ["the user"]}, "'cc' recipient 1", id="cc"),
        pytest.param({"bcc": "anna at home"}, "'bcc' recipient 1", id="bcc"),
    ],
)
async def test_a_recipient_that_is_not_an_address_comes_back_before_the_ruling(
    recipients: dict[str, Any], where: str
) -> None:
    """§9:13: every recipient is an email address; one that is not comes back not done,
    saying an address is needed, and nothing is guessed."""
    _, decided, verdict = await _decided(_Allowing(), **recipients)

    assert verdict.verdict is Verdict.NOT_DONE
    assert verdict.reason is not None
    assert where in verdict.reason
    assert "address" in verdict.reason
    assert verdict.decision_id is None
    assert decided.allowed == ()


async def test_a_sender_that_is_no_email_account_comes_back() -> None:
    """§9:11: ``from`` names an email account, which planning's check maps; any other is not."""
    _, _, verdict = await _decided(_Allowing(), **{"from": "Anna"})
    assert verdict.verdict is Verdict.NOT_DONE
    assert verdict.reason is not None
    assert "'from'" in verdict.reason


async def test_words_whose_exact_tag_never_closes_come_back_not_done() -> None:
    """§9:8: an unclosed tag comes back not done, before the ruling."""
    _, decided, verdict = await _decided(_Allowing(), words="Say <exact>this exactly")
    assert verdict.verdict is Verdict.NOT_DONE
    assert verdict.reason is not None
    assert "never closed" in verdict.reason
    assert verdict.decision_id is None
    assert decided.allowed == ()


async def test_a_deny_still_refuses_an_email() -> None:
    """§9:12 adds approval; it takes no refusal away (ADR-0321 §2:10)."""

    class _Denying(_Allowing):
        async def decide(self, request: ActionRequest) -> PermissionRuling:
            del request
            return PermissionRuling(outcome=PermissionOutcome.DENY, reason="no")

    _, _, verdict = await _decided(_Denying())
    assert verdict.verdict is Verdict.NOT_DONE
