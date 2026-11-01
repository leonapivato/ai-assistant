"""The approvals panel's query and tap, reached from a browser (ADR-0361 §4:6-§4:9).

Driven through a real socket for ``test_gateway.py``'s reason: what is under test is a
request the browser makes and the body it renders, and the router, the door and the
admission all sit between the two. The engine behind it is the canonical fake over the
shared suite's stores (``approvals_panel_contract``), so each answer here is the one the
engine's contract holds the fake to.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from approvals_panel_contract import APPROVALS_AT, hold_asking_episode, hold_request
from test_gateway_streams import _harness

from ai_assistant.core.errors import DeviceRefusal, DeviceRefusedError
from ai_assistant.core.types import (
    ApprovalGiver,
    ApprovalRequestState,
    ApprovalTap,
)
from ai_assistant.interfaces.gateway.http import Request
from ai_assistant.interfaces.gateway.records import RequestClass
from ai_assistant.interfaces.gateway.server import _ASSISTANT_PATHS
from ai_assistant.testing import FakeAssistantEngine, FakeMemoryStore, FakePlanStore

if TYPE_CHECKING:
    from ai_assistant.core.types import ApprovalChoice, ApprovalPanel, ApprovalPanelTap, Identifier

pytestmark = pytest.mark.integration

#: Every path this lane adds, with the member of ADR-0361 §8:4 it reaches.
_ADDED: Final[dict[str, str]] = {"/approvals": "approvals", "/approval/tap": "tap_approval"}

#: One well-formed body per path, every value the browser's own (ADR-0177 §1).
_WELL_FORMED: Final[dict[str, dict[str, Any]]] = {
    "/approvals": {},
    "/approval/tap": {"request_id": "approval:1", "choice": "approve"},
}


def _engine() -> FakeAssistantEngine:
    engine = FakeAssistantEngine()
    engine.plan_store = FakePlanStore(now=lambda: APPROVALS_AT)
    engine.episode_memory = FakeMemoryStore(now=lambda: APPROVALS_AT)
    engine.approval_clock = lambda: APPROVALS_AT
    return engine


def _request(path: str) -> Request:
    return Request(method="POST", path=path, headers=(), body=b"{}")


def test_every_path_names_the_member_adr_0361_s8_4_adds() -> None:
    """One path per member, joined against the router rather than a copy of it."""
    for path, operation in _ADDED.items():
        assert _ASSISTANT_PATHS[("POST", path)] == operation, path
        assert ("GET", path) not in _ASSISTANT_PATHS, path


@pytest.mark.parametrize("path", sorted(_ADDED))
async def test_each_path_asks_the_assistant_and_is_refused_without_a_session(path: str) -> None:
    """ADR-0177 §2 and ADR-0168 §1: an assistant request, refused before any session."""
    async with _harness(_engine()) as one:
        assert one.gateway._classify(_request(path)) is RequestClass.ASSISTANT
        status, body = await one.whole("POST", path, _WELL_FORMED[path], admitted=False)

        assert status == 401
        assert body["fault"] == "no-live-session"
        assert one.engine.calls == []


async def test_the_read_carries_each_request_as_its_card_shows_it() -> None:
    """§4:6: the pending ones and the recent ones, each its card's text and its state."""
    engine = _engine()
    await hold_request(engine.plan_store, "approval:1")
    await hold_asking_episode(engine.episode_memory)
    await hold_request(engine.plan_store, "approval:2", ago=timedelta(hours=3), date="Sat")
    await engine.plan_store.answer_approval_request(
        "approval:2",
        ApprovalRequestState.DENIED,
        ApprovalTap(who=ApprovalGiver.USER_TAP_ON_TELEGRAM_CARD, at=APPROVALS_AT),
    )

    async with _harness(engine) as one:
        status, body = await one.whole("POST", "/approvals", {})

    assert status == 200
    (pending,) = body["approvals"]["pending"]
    assert pending["request_id"] == "approval:1"
    assert pending["state"] == "pending"
    assert pending["text"].startswith("Approval needed:")
    assert "Asked in the hub chat." in pending["text"]
    assert pending["answered_by"] is None
    assert pending["answered_at"] is None
    assert pending["expires_at"] == (APPROVALS_AT + timedelta(hours=23)).isoformat()
    (recent,) = body["approvals"]["recent"]
    assert (recent["request_id"], recent["state"]) == ("approval:2", "denied")
    assert recent["answered_by"] == "user_tap_on_telegram_card"
    assert recent["answered_at"] == APPROVALS_AT.isoformat()
    assert set(pending) == {
        "request_id",
        "text",
        "state",
        "written_at",
        "expires_at",
        "answered_by",
        "answered_at",
    }


async def test_the_read_relays_the_browsers_limit() -> None:
    engine = _engine()
    async with _harness(engine) as one:
        status, _ = await one.whole("POST", "/approvals", {"limit": 3})
        _, _ = await one.whole("POST", "/approvals", {})

    assert status == 200
    asked = [arguments for name, arguments in engine.calls if name == "approvals"]
    assert [one["limit"] for one in asked] == [3, 50]


@pytest.mark.parametrize("limit", [True, -1, "3"])
async def test_a_malformed_limit_is_refused_before_the_hub(limit: object) -> None:
    async with _harness(_engine()) as one:
        status, body = await one.whole("POST", "/approvals", {"limit": limit})

        assert (status, body["fault"]) == (400, "malformed-request")
        assert one.engine.calls == []


async def test_a_tap_answers_the_request_as_the_hub_pages_giver() -> None:
    """§4:9: approved by the panel's tap; a second tap answered with the state."""
    engine = _engine()
    await hold_request(engine.plan_store, "approval:1")

    async with _harness(engine) as one:
        status, body = await one.whole(
            "POST", "/approval/tap", {"request_id": "approval:1", "choice": "approve"}
        )
        _, again = await one.whole(
            "POST", "/approval/tap", {"request_id": "approval:1", "choice": "deny"}
        )

    assert status == 200
    assert body["tap"]["answer"] == "answered"
    assert body["tap"]["entry"]["state"] == "approved"
    assert body["tap"]["entry"]["answered_by"] == "user_tap_on_hub_panel"
    assert again["tap"]["answer"] == "already_answered"
    assert again["tap"]["entry"]["state"] == "approved"
    (held,) = await engine.plan_store.approval_requests(["approval:1"])
    assert held.state is ApprovalRequestState.APPROVED


async def test_a_tap_on_no_request_of_the_persons_is_unknown() -> None:
    async with _harness(_engine()) as one:
        status, body = await one.whole(
            "POST", "/approval/tap", {"request_id": "approval:none", "choice": "deny"}
        )

    assert (status, body) == (200, {"tap": {"answer": "unknown", "entry": None}})


@pytest.mark.parametrize(
    "payload",
    [
        {"choice": "approve"},
        {"request_id": "approval:1"},
        {"request_id": "approval:1", "choice": "yes"},
        {"request_id": 1, "choice": "approve"},
    ],
)
async def test_a_malformed_tap_is_refused_before_the_hub(payload: dict[str, Any]) -> None:
    """Both arguments are the browser's own and required; nothing is defaulted here."""
    engine = _engine()
    await hold_request(engine.plan_store, "approval:1")
    async with _harness(engine) as one:
        status, body = await one.whole("POST", "/approval/tap", payload)

        assert (status, body["fault"]) == (400, "malformed-request")
        assert one.engine.calls == []
    (held,) = await engine.plan_store.approval_requests(["approval:1"])
    assert held.state is ApprovalRequestState.PENDING


class _RefusingDevice(FakeAssistantEngine):
    """A hub refusing this browser's device, as its route table refuses one without the
    command role (ADR-0298 §5:6)."""

    async def approvals(self, *, limit: int = 50) -> ApprovalPanel:
        msg = "the approvals panel needs the commands role"
        raise DeviceRefusedError(msg, reason=DeviceRefusal.NOT_ALLOWED)

    async def tap_approval(
        self, request_id: Identifier, /, *, choice: ApprovalChoice
    ) -> ApprovalPanelTap:
        msg = "the approvals panel needs the commands role"
        raise DeviceRefusedError(msg, reason=DeviceRefusal.NOT_ALLOWED)


@pytest.mark.parametrize("path", sorted(_ADDED))
async def test_the_hubs_refusal_for_the_device_is_relayed_as_every_other(path: str) -> None:
    """§4:8 is the hub's route table's; the gateway adds no rule and relays its answer."""
    async with _harness(_RefusingDevice()) as one:
        status, body = await one.whole("POST", path, _WELL_FORMED[path])

    assert (status, body["fault"]) == (422, "device-not-allowed")
