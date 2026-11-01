"""The approvals panel, in a real browser (ADR-0361 §4:6-§4:9).

The engine behind the page is the canonical fake over the shared suite's stores
(``approvals_panel_contract``), so each answer is the one the engine's contract holds
the fake to, and what is driven here is the page: the requests waiting for an answer,
each as its card shows it with Approve and Deny, and the ones answered recently; a tap
that lands, said in words, the panel read again; a tap after the card's answered with
the request's state; a request too long for a Telegram card read and answered whole;
and the hub's refusal for a device it does not admit, which changes nothing. Both
widths ADR-0233 §15 has the browser lane drive, with no horizontal scroll and an empty
console.

Every read of the page's text is a waiting assertion (``expect``), never a read at an
instant, so no assertion races the render it is about.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Final

import pytest
from approvals_panel_contract import APPROVALS_AT, hold_asking_episode, hold_request
from browser_drive import DESKTOP, PHONE, driving, press
from playwright.async_api import expect

from ai_assistant.core.errors import DeviceRefusal, DeviceRefusedError
from ai_assistant.core.types import (
    APPROVAL_WHY_MAX_CHARS,
    ApprovalGiver,
    ApprovalRequestState,
    ApprovalTap,
)
from ai_assistant.testing import FakeMemoryStore, FakePlanStore

if TYPE_CHECKING:
    from pathlib import Path

    from browser_drive import Drive
    from playwright.async_api import Browser, ConsoleMessage, Page, ViewportSize

    from ai_assistant.core.types import ApprovalChoice, ApprovalPanelTap, Identifier

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
]

_WIDTHS: Final = pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])

#: A ``why`` long enough to need wrapping at a phone's width.
_WHY: Final = (
    "You asked me to book the corner table at the harbour restaurant for your sister's "
    "birthday dinner on Friday, and it needs your yes before I send the booking."
)


def _complaints(page: Page) -> list[str]:
    """Every console error and uncaught exception, but the browser's own favicon probe."""
    heard: list[str] = []

    def note(message: ConsoleMessage) -> None:
        if message.type == "error" and not message.location["url"].endswith("/favicon.ico"):
            heard.append(f"{message.location['url']}: {message.text}")

    page.on("console", note)
    page.on("pageerror", lambda error: heard.append(str(error)))
    return heard


async def _overflow(page: Page) -> int:
    overflow: int = await page.evaluate(
        "() => document.documentElement.scrollWidth - window.innerWidth"
    )
    return overflow


def _stores(drive: Drive) -> FakePlanStore:
    """Clock the drive's fake at the suite's instant, over fresh stores; its plan store."""
    drive.engine.plan_store = FakePlanStore(now=lambda: APPROVALS_AT)
    drive.engine.episode_memory = FakeMemoryStore(now=lambda: APPROVALS_AT)
    drive.engine.approval_clock = lambda: APPROVALS_AT
    return drive.engine.plan_store


async def _open(drive: Drive) -> None:
    async with drive.page.expect_response("**/approvals"):
        await press(drive.page, "#approvals-button")
    await drive.page.wait_for_selector("#approvals:not([hidden])")


@_WIDTHS
async def test_the_panel_shows_what_waits_and_what_was_answered(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """§4:6: pending ones with Approve and Deny, as their cards show them; recent ones
    with their state and where they were answered, and no buttons."""
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        heard = _complaints(drive.page)
        plans = _stores(drive)
        await hold_request(plans, "approval:1", why=_WHY)
        await hold_asking_episode(drive.engine.episode_memory)
        await hold_request(plans, "approval:2", ago=timedelta(hours=4), date="Saturday")
        await plans.answer_approval_request(
            "approval:2",
            ApprovalRequestState.DENIED,
            ApprovalTap(
                who=ApprovalGiver.USER_TAP_ON_TELEGRAM_CARD, at=APPROVALS_AT - timedelta(hours=3)
            ),
        )

        await _open(drive)

        pending = drive.page.locator("#approvals-pending .approval-row")
        recent = drive.page.locator("#approvals-recent .approval-row")
        await expect(pending).to_have_count(1)
        await expect(recent).to_have_count(1)
        await expect(pending.first.locator(".reply")).to_contain_text("Approval needed:")
        await expect(pending.first.locator(".reply")).to_contain_text(f"Why: {_WHY}")
        await expect(pending.first.locator(".reply")).to_contain_text("Asked in the hub chat.")
        await expect(pending.first.locator(".reply")).to_contain_text("Waiting for your answer.")
        await expect(pending.first.locator("button")).to_have_text(["Approve", "Deny"])
        await expect(recent.first.locator(".reply")).to_contain_text("Denied.")
        await expect(recent.first.locator(".hint")).to_contain_text(
            "Answered on its card in Telegram"
        )
        await expect(recent.first.locator("button")).to_have_count(0)
        assert await _overflow(drive.page) <= 0
        assert heard == []


@_WIDTHS
async def test_a_tap_lands_is_said_and_the_panel_is_read_again(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """§4:9: Approve marks the request as the hub page's tap; it moves to the recent
    list, approved, and the other waits on."""
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        heard = _complaints(drive.page)
        plans = _stores(drive)
        await hold_request(plans, "approval:1", ago=timedelta(hours=2), date="Friday")
        await hold_request(plans, "approval:2", ago=timedelta(hours=1), date="Sunday")
        await _open(drive)
        pending = drive.page.locator("#approvals-pending .approval-row")
        await expect(pending).to_have_count(2)

        async with drive.page.expect_response("**/approval/tap"):
            await pending.first.get_by_role("button", name="Approve").click()

        await expect(drive.page.locator("#approvals-outcome")).to_have_text(
            "Approved. I may now do exactly what it shows, once."
        )
        await expect(pending).to_have_count(1)
        await expect(pending.first.locator(".reply")).to_contain_text("Sunday")
        recent = drive.page.locator("#approvals-recent .approval-row")
        await expect(recent).to_have_count(1)
        await expect(recent.first.locator(".reply")).to_contain_text("Approved: not used yet.")
        await expect(recent.first.locator(".hint")).to_contain_text("Answered on this page")
        (held,) = await plans.approval_requests(["approval:1"])
        assert held.state is ApprovalRequestState.APPROVED
        assert held.answer is not None
        assert held.answer.who is ApprovalGiver.USER_TAP_ON_HUB_PANEL
        assert drive.engine.approvals_woken == 1
        assert await _overflow(drive.page) <= 0
        assert heard == []


async def test_a_tap_after_the_cards_is_answered_with_the_requests_state(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§4:9: the card was tapped while the panel was open; the panel's Deny changes
    nothing, and the page says where the request stands."""
    async with driving(gateway_browser, tmp_path, viewport=PHONE) as drive:
        heard = _complaints(drive.page)
        plans = _stores(drive)
        await hold_request(plans, "approval:1")
        await _open(drive)
        pending = drive.page.locator("#approvals-pending .approval-row")
        await expect(pending).to_have_count(1)
        await plans.answer_approval_request(
            "approval:1",
            ApprovalRequestState.APPROVED,
            ApprovalTap(who=ApprovalGiver.USER_TAP_ON_TELEGRAM_CARD, at=APPROVALS_AT),
        )

        async with drive.page.expect_response("**/approval/tap"):
            await pending.first.get_by_role("button", name="Deny").click()

        await expect(drive.page.locator("#approvals-outcome")).to_have_text(
            "That was already answered, so nothing changed. It stands: Approved: not used yet."
        )
        await expect(pending).to_have_count(0)
        await expect(drive.page.locator("#approvals-pending")).to_contain_text(
            "Nothing is waiting for your answer."
        )
        (held,) = await plans.approval_requests(["approval:1"])
        assert held.state is ApprovalRequestState.APPROVED
        assert drive.engine.approvals_woken == 0
        assert heard == []


@_WIDTHS
async def test_a_request_too_long_for_a_card_is_read_and_answered_whole(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """§4:4: the panel shows it whole, wrapping at a phone's width, and takes the tap."""
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        heard = _complaints(drive.page)
        plans = _stores(drive)
        why = ("A long reason. " * (APPROVAL_WHY_MAX_CHARS // 15)).strip()
        await hold_request(plans, "approval:long", why=why, date="d" * 300)
        await _open(drive)
        pending = drive.page.locator("#approvals-pending .approval-row")
        await expect(pending).to_have_count(1)
        await expect(pending.first.locator(".reply")).to_contain_text(f"Why: {why}")
        assert await _overflow(drive.page) <= 0

        async with drive.page.expect_response("**/approval/tap"):
            await pending.first.get_by_role("button", name="Deny").click()

        await expect(drive.page.locator("#approvals-outcome")).to_have_text(
            "Denied. I will not do it."
        )
        (held,) = await plans.approval_requests(["approval:long"])
        assert held.state is ApprovalRequestState.DENIED
        assert heard == []


class _NotAdmitted:
    """The hub's refusal of a device without the commands role (ADR-0298 §5:6)."""

    async def tap_approval(
        self, request_id: Identifier, /, *, choice: ApprovalChoice
    ) -> ApprovalPanelTap:
        msg = "tap_approval needs the commands role, which this device does not hold"
        raise DeviceRefusedError(msg, reason=DeviceRefusal.NOT_ALLOWED)


async def test_a_tap_the_hub_refuses_for_the_device_changes_nothing(
    gateway_browser: Browser, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§4:8: a tap from a device the hub does not admit is refused before anything
    changes; the page says so in the panel, and the request still waits."""
    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        plans = _stores(drive)
        await hold_request(plans, "approval:1")
        await _open(drive)
        pending = drive.page.locator("#approvals-pending .approval-row")
        await expect(pending).to_have_count(1)
        monkeypatch.setattr(drive.engine, "tap_approval", _NotAdmitted().tap_approval)

        async with drive.page.expect_response("**/approval/tap"):
            await pending.first.get_by_role("button", name="Approve").click()

        await expect(drive.page.locator("#approvals > .fault:not([hidden])")).to_have_count(1)
        await expect(pending.first.get_by_role("button", name="Approve")).to_be_enabled()
        (held,) = await plans.approval_requests(["approval:1"])
        assert held.state is ApprovalRequestState.PENDING
        assert held.answer is None


async def test_more_waiting_than_one_read_holds_is_said(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The oldest are shown and the page says how many more wait, past the page's count
    or past what one answer may carry (ADR-0085 §8, §4:4)."""
    async with driving(gateway_browser, tmp_path, viewport=PHONE) as drive:
        heard = _complaints(drive.page)
        plans = _stores(drive)
        for index in range(26):
            await hold_request(
                plans,
                f"approval:{index:02d}",
                ago=timedelta(hours=3, minutes=-index),
                date=f"{index}",
            )

        await _open(drive)

        await expect(drive.page.locator("#approvals-pending .approval-row")).to_have_count(25)
        await expect(drive.page.locator("#approvals-pending > .hint")).to_have_text(
            "1 more request waits after these. Answer these to see the rest."
        )
        assert await _overflow(drive.page) <= 0
        assert heard == []
