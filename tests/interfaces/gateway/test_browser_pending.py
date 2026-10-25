"""The pending candidates in the belief panel, in a real browser (ADR-0329 §18:1).

The engine behind the page answers with its own reading — the fake's
``pending_candidates`` over seeded episodes and effect records, as the shared suite
holds it to — so what is driven here is the page: the panel opened from its menu entry
shows each candidate by its fact, marked pending, with no control on it, and shows no
section at all where the hub's ``remember`` still writes memories (§19:3). Both widths
ADR-0233 §15 has the browser lane drive.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from browser_drive import DESKTOP, PHONE, driving, press
from pending_candidates_contract import PENDING_AT, PendingCandidatesSubject, hold_episode
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import expect
from test_browser_session_loss import _ends_the_session

from ai_assistant.testing import FakeMemoryStore, FakePlanStore

if TYPE_CHECKING:
    from pathlib import Path

    from browser_drive import Drive
    from playwright.async_api import Browser, Request, Route, ViewportSize

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
]

#: A fact long enough to need wrapping at a phone's width, which is where a row that
#: does not wrap would push the page sideways.
_LONG_FACT = (
    "prefers an aisle seat on any flight longer than two hours, and a window seat on "
    "anything shorter, because they like to sleep on the short ones"
)


async def _seed(drive: Drive, *, candidates: bool = True) -> None:
    """Give the drive's engine two episodes with three candidates between them, or none."""
    memory = FakeMemoryStore(now=lambda: PENDING_AT)
    plans = FakePlanStore(now=lambda: PENDING_AT)
    drive.engine.episode_memory = memory
    drive.engine.plan_store = plans
    if not candidates:
        return
    subject = PendingCandidatesSubject(engine=drive.engine, memory=memory, plans=plans)
    await hold_episode(subject, "older", "lives in Lisbon", age=timedelta(days=1))
    await hold_episode(subject, "newer", "has a dog", _LONG_FACT)


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
async def test_the_belief_panel_shows_each_pending_candidate_by_its_fact_marked_pending(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        await _seed(drive, candidates=True)

        async with drive.page.expect_response("**/candidates/pending"):
            await press(drive.page, "#beliefs-button")
        await drive.page.wait_for_selector("#pending-candidates:not([hidden])")

        rows = drive.page.locator("#pending-list > div")
        assert await rows.count() == 3
        texts = [await rows.nth(index).inner_text() for index in range(3)]
        assert [text.splitlines()[-1] for text in texts] == [
            "has a dog",
            _LONG_FACT,
            "lives in Lisbon",
        ]
        assert all(text.splitlines()[0] == "Pending: not remembered yet" for text in texts)
        assert await drive.page.locator("#pending-list button").count() == 0
        assert await drive.page.locator("#beliefs #pending-candidates").count() == 1
        overflow = await drive.page.evaluate(
            "() => document.documentElement.scrollWidth - window.innerWidth"
        )
        assert overflow <= 0


async def test_a_hub_holding_no_pending_candidate_shows_no_pending_section(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§18:1: with none pending, the section is not shown."""
    async with driving(gateway_browser, tmp_path, viewport=PHONE) as drive:
        await _seed(drive, candidates=False)

        async with drive.page.expect_response("**/candidates/pending"):
            await press(drive.page, "#beliefs-button")
        await drive.page.wait_for_selector("#beliefs:not([hidden])")

        assert await drive.page.locator("#pending-candidates").is_hidden()
        assert await drive.page.locator("#pending-list > div").count() == 0


async def test_a_listing_that_outlived_its_session_reads_no_candidates_under_the_next(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The candidates are read for the session that opened the panel, and no other.

    The listing is held while its session ends and the owner starts another; released,
    its answer is the old session's and is retired, and the opening goes no further —
    a candidate read started now would be the new session's, for a panel nobody opened
    in it (adversarial review, round 1).
    """
    loop = asyncio.get_running_loop()
    release: asyncio.Future[None] = loop.create_future()
    asked: list[str] = []

    async def hang(one: Route) -> None:
        await release
        with contextlib.suppress(PlaywrightError):
            await one.fallback()

    def note(request: Request) -> None:
        if request.url.endswith("/candidates/pending"):
            asked.append(request.url)

    async with driving(gateway_browser, tmp_path, viewport=PHONE) as drive:
        await _seed(drive, candidates=True)
        drive.page.on("request", note)
        await drive.page.route("**/beliefs", hang)
        async with drive.page.expect_request("**/beliefs"):
            await press(drive.page, "#beliefs-button")

        await drive.page.route("**/sources", _ends_the_session)
        await press(drive.page, "#sources-button")
        await drive.page.wait_for_selector("#bootstrap:not([hidden])")
        await drive.admit()

        async with drive.page.expect_response("**/beliefs") as stale:
            release.set_result(None)
        await (await stale.value).finished()
        # A whole round trip after the stale answer, so its continuation has run.
        async with drive.page.expect_response("**/conversations"):
            await press(drive.page, "#conversations-button")

        assert asked == []
        await expect(drive.page.locator("#beliefs")).to_be_hidden()
