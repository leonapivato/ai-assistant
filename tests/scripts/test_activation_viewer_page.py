"""The activation viewer's page, driven in a real browser (ADR-0316 §3, §6:7).

What the server's JSON cannot say: that the page puts an entry's raw text into the
document as text, that a round's calls each show their own verdict, and that a drawer
shows only what the last click asked for, however its loads interleave. The viewer is
bound on loopback over a record written by ADR-0314's store, and driven by the suite's
one shared browser (ADR-0216 §3).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pytest
from playwright.async_api import expect

sys.path.insert(0, str(Path(__file__).parent))
from _activation_record import HOSTILE, serving, write_record

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from playwright.async_api import Browser, Page, Route

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
]

#: Long enough for a poll and a fetch to land.
_SHOWN: Final = 10_000


@pytest.fixture
def record(tmp_path: Path) -> Path:
    """A record written by ADR-0314's store."""
    return write_record(tmp_path)


@pytest.fixture
def server(record: Path) -> Iterator[Any]:
    """The viewer on loopback over ``record``."""
    with serving(record) as bound:
        yield bound


@contextlib.asynccontextmanager
async def _page(browser: Browser) -> AsyncIterator[Page]:
    """A fresh page in its own context, closed when the case is done with it."""
    context = await browser.new_context(viewport={"width": 1280, "height": 860})
    try:
        yield await context.new_page()
    finally:
        await context.close()


async def _open(page: Page, port: int, activation_id: str) -> None:
    await page.goto(f"http://127.0.0.1:{port}/#{activation_id}")
    await expect(page.locator("#detail-body")).to_be_visible(timeout=_SHOWN)


async def test_entry_text_reaches_the_page_as_text(server: Any, gateway_browser: Browser) -> None:
    async with _page(gateway_browser) as page:
        await _open(page, server.port, "act-1")
        await expect(page.locator("#d-input")).to_have_text(HOSTILE, timeout=_SHOWN)
        await page.locator(".tl-lane .bar.call").first.click()
        await expect(page.locator("#drawer-body pre").nth(1)).to_contain_text("<script>")
        assert await page.locator("img").count() == 0
        assert await page.locator("script").count() == 1
        assert await page.title() == "Activation viewer"


async def test_each_call_shows_its_own_verdict(server: Any, gateway_browser: Browser) -> None:
    async with _page(gateway_browser) as page:
        await _open(page, server.port, "act-1")
        chips = page.locator(".round").first.locator(".chip")
        await expect(chips).to_have_text(
            ["web_search · allowed", "web_search · needs you"], timeout=_SHOWN
        )
        await expect(page.locator(".round").first).to_contain_text("marked")


async def test_a_drawer_shows_only_what_the_last_click_asked_for(
    server: Any, gateway_browser: Browser
) -> None:
    requested = asyncio.Event()
    released = asyncio.Event()

    async def hold_act_1(route: Route) -> None:
        if "id=act-1" in route.request.url:
            requested.set()
            await released.wait()
        await route.continue_()

    async with _page(gateway_browser) as page:
        await page.route("**/api/entry?*", hold_act_1)
        await _open(page, server.port, "act-1")
        # Planning's call on act-1, two lines, its first load held.
        await page.locator(".tl-lane").nth(3).locator(".bar.call").first.click()
        await asyncio.wait_for(requested.wait(), timeout=10)
        # Then act-2, and one of its entries, before act-1's load comes back.
        await page.evaluate("location.hash = 'act-2'")
        await expect(page.locator("#d-input")).to_have_text("hello", timeout=_SHOWN)
        await page.locator(".tl-lane .bar.call").first.click()
        headings = page.locator("#drawer-body .sec h3")
        await expect(headings.first).to_have_text("understanding · given", timeout=_SHOWN)
        released.set()
        # Long enough for act-1's two held loads to land, were they drawn.
        await page.wait_for_timeout(500)
        shown = await headings.all_text_contents()
        assert all(not one.startswith("planning") for one in shown), shown
        await expect(page.locator("#drawer-title")).not_to_contain_text("planning")


async def test_a_span_of_a_century_draws_a_handful_of_ticks(
    server: Any, record: Path, gateway_browser: Browser
) -> None:
    lines: list[dict[str, object]] = [
        {
            "activation_id": "wide",
            "source": "planning",
            "kind": "given",
            "recorded_at": when,
            "body": {},
        }
        for when in ("1900-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00")
    ]
    (record / "wide.jsonl").write_text("".join(json.dumps(one) + "\n" for one in lines))
    async with _page(gateway_browser) as page:
        await _open(page, server.port, "wide")
        await expect(page.locator(".tl-lane").first).to_be_visible(timeout=_SHOWN)
        assert 2 <= await page.locator(".tick").count() <= 8
        lanes = await page.locator(".tl-lane").count()
        assert await page.locator(".grid").count() <= 8 * lanes


async def test_a_change_of_activation_takes_the_old_details_down_at_once(
    server: Any, gateway_browser: Browser
) -> None:
    released = asyncio.Event()

    async def hold_act_2(route: Route) -> None:
        if "id=act-2" in route.request.url:
            await released.wait()
        await route.continue_()

    async with _page(gateway_browser) as page:
        await page.route("**/api/activation?*", hold_act_2)
        await _open(page, server.port, "act-1")
        await expect(page.locator(".round")).to_have_count(2, timeout=_SHOWN)
        await page.evaluate("location.hash = 'act-2'")
        # While act-2's details are still loading, nothing of act-1's is on show.
        await expect(page.locator("#detail-body")).to_be_hidden()
        await expect(page.locator("#detail-empty")).to_have_text("Loading…")
        released.set()
        await expect(page.locator("#d-input")).to_have_text("hello", timeout=_SHOWN)
