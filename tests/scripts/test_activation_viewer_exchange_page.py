"""The activation viewer's page over a work's exchange, in a real browser (ADR-0356 §14:9).

What the server's JSON cannot say: that a walked round since ADR-0356 shows its text as
its notes and its message calls as its messages, what came of each call from the next
round's report, and that the last round's calls say the record holds none; at a desktop
width and at a phone's, with no sideways scroll.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pytest
from playwright.async_api import expect

sys.path.insert(0, str(Path(__file__).parent))
from _activation_record import serving, viewer
from test_activation_viewer_exchange import (
    _ID,
    _NEWS,
    _NOTES_1,
    _NOTES_2,
    _RESULT,
    _SAID_1,
    _SAID_2,
    _write,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from playwright.async_api import Browser, Page

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
]

_SHOWN: Final = 10_000


@pytest.fixture
def exchanged(tmp_path: Path) -> Iterator[Any]:
    directory = tmp_path / "data" / "diagnostics"
    directory.mkdir(parents=True)
    asyncio.run(_write(directory))
    with serving(directory) as bound:
        yield bound


@contextlib.asynccontextmanager
async def _page(browser: Browser, width: int) -> AsyncIterator[Page]:
    context = await browser.new_context(viewport={"width": width, "height": 860})
    try:
        yield await context.new_page()
    finally:
        await context.close()


async def _sideways(page: Page) -> float:
    return float(
        await page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
    )


@pytest.mark.parametrize("width", [1280, 390], ids=["desktop", "phone"])
async def test_a_walked_exchange_round_shows_its_notes_messages_and_what_came_of_them(
    exchanged: Any, gateway_browser: Browser, width: int
) -> None:
    async with _page(gateway_browser, width) as page:
        await page.goto(f"http://127.0.0.1:{exchanged.port}/#{_ID}/walk/2")
        step = page.locator("#walk-step")
        title = step.locator(".walk-head h2")
        await expect(title).to_have_text("Planning · round 1", timeout=_SHOWN)
        await expect(step).to_contain_text("Its notes (its text)")
        await expect(step).to_contain_text(_NOTES_1)
        await expect(step).to_contain_text("Its messages")
        await expect(step).to_contain_text(_SAID_1)
        await expect(step).to_contain_text("what came of it, as the next round was told")
        await expect(step).to_contain_text(_RESULT)
        # A round since writes no message of its own (§7:3): there is no such section.
        await expect(step.get_by_role("heading", name="Its message", exact=True)).to_have_count(0)
        assert await _sideways(page) <= 0

        await page.goto(f"http://127.0.0.1:{exchanged.port}/#{_ID}/walk/4")
        await expect(title).to_have_text("Planning · round 2", timeout=_SHOWN)
        await expect(step).to_contain_text("What came back from round 1")
        await expect(step).to_contain_text(_NOTES_1)
        await expect(step).to_contain_text(_NEWS)
        await expect(step).to_contain_text(_SAID_2)
        await expect(step).to_contain_text(_NOTES_2)
        await expect(step).to_contain_text(viewer.NO_CALL_ENTRY)
        assert await _sideways(page) <= 0


async def test_the_rounds_panel_labels_an_exchange_rounds_text_as_its_notes(
    exchanged: Any, gateway_browser: Browser
) -> None:
    async with _page(gateway_browser, 1280) as page:
        await page.goto(f"http://127.0.0.1:{exchanged.port}/#{_ID}")
        first = page.locator(".round").first
        await expect(first).to_contain_text("notes: " + _NOTES_1, timeout=_SHOWN)
        await expect(first).to_contain_text("message call: " + _SAID_1)
