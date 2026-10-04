"""What one drive leaves in a reused browser context never reaches the next one.

``browser_drive.driving()`` opens a page per case in a context the layer reuses,
rather than a context per case, because the context's opening and closing was a
fixed cost every case paid before it did anything (``browser_drive._Shelf``). That
is only a saving if the cases cannot tell, and these are the cases that would.

Each one holds two drives in sequence, so that the second is lent whatever the
first handed back: cookies, origin-scoped storage on a port that repeats, a route
and a listener on the page, a second page the case opened, and a case that ended by
raising. The last case pins the other half — that a context really is lent again —
because a shelf that silently stopped reusing anything would pass every isolation
case here and cost the layer the time it exists to save.

These are cases about the harness rather than about the page, and they are in the
layer rather than beside it (``test_browser_harness.py`` launches nothing) because
the property is the real browser's: what Chromium keeps per host, per origin and per
context is the subject, and a fake browser would answer with what its author
believed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import gateway_ports
import pytest
from browser_drive import DESKTOP, driving
from playwright.async_api import Error as BrowserError

if TYPE_CHECKING:
    from pathlib import Path

    from playwright.async_api import Browser, BrowserContext, Dialog, Route

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
]

#: The key the cases write under, named for this module so that nothing the page
#: itself stores could be mistaken for it.
_CANARY = "browser-isolation-canary"


async def test_the_next_drive_at_a_viewport_is_lent_the_same_context_without_its_cookie(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A context is reused, and the session cookie the last gateway set is gone.

    The cookie is the one piece of a context's state that a different port does not
    keep apart: cookies are scoped to a host, so a session minted by one gateway on
    ``127.0.0.1`` would be offered to the next. The reuse half is pinned beside it
    because a shelf that stopped lending would pass every other case in this module.
    """
    async with driving(gateway_browser, tmp_path / "first", viewport=DESKTOP) as first:
        assert await first.page.context.cookies() != [], "the admitted drive set no cookie"
        context = first.page.context

    async with driving(
        gateway_browser, tmp_path / "second", viewport=DESKTOP, admitted=False
    ) as second:
        assert second.page.context is context
        assert await second.page.context.cookies() == []
        assert await second.page.is_visible("#bootstrap-form")
        assert not await second.page.is_visible("#console")


async def test_storage_a_case_wrote_is_not_read_by_a_later_case_on_the_same_port(
    gateway_browser: Browser, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``localStorage`` and ``sessionStorage`` do not survive into a repeated origin.

    Ports repeat — ``gateway_ports`` hands them out of a block of 64, round-robin —
    and a repeated port is a repeated origin, which is where the browser keeps a
    page's storage, half of its session header included. So this pins the port, as
    the cycle eventually would, and writes to both stores before the first drive
    ends.
    """
    port = gateway_ports.free_port()
    monkeypatch.setattr(gateway_ports, "free_port", lambda: port)

    async with driving(gateway_browser, tmp_path / "first", viewport=DESKTOP) as first:
        await first.page.evaluate(
            "key => { localStorage.setItem(key, 'left'); sessionStorage.setItem(key, 'left'); }",
            _CANARY,
        )

    async with driving(gateway_browser, tmp_path / "second", viewport=DESKTOP) as second:
        assert second.origin == first.origin
        left = await second.page.evaluate(
            "key => [localStorage.getItem(key), sessionStorage.getItem(key)]", _CANARY
        )
        assert left == [None, None]


async def test_a_route_a_listener_and_a_second_page_end_with_the_case_that_made_them(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """Nothing a case attached to its page, or opened beside it, is lent on.

    A route that refuses the bundle would leave the next page unable to load at all,
    and a ``dialog`` listener that never answers would leave the next page's first
    ``confirm()`` open for good, where an unlistened dialog is dismissed. The page is
    opened fresh for every case, so neither can reach the next one; the second page
    is closed with the case that opened it, because the context it lives in is not.
    """
    unanswered: list[Dialog] = []

    def hold(dialog: Dialog) -> None:
        unanswered.append(dialog)

    async with driving(gateway_browser, tmp_path / "first", viewport=DESKTOP) as first:
        await first.page.route("**/app.js", _refuse)
        first.page.on("dialog", hold)
        beside = await first.page.context.new_page()
        await beside.goto(f"{first.origin}/")
        context = first.page.context

    async with driving(gateway_browser, tmp_path / "second", viewport=DESKTOP) as second:
        assert second.page.context is context
        assert context.pages == [second.page]
        assert await second.page.evaluate("() => confirm('dismissed?')") is False
        assert unanswered == []


async def test_a_context_whose_case_raised_is_closed_and_not_lent_again(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A case that ended by raising hands back a context nothing vouches for.

    So it is closed rather than shelved, and the next drive at that viewport is
    opened in a context of its own.
    """
    lent: list[BrowserContext] = []
    with pytest.raises(RuntimeError, match="the case failed"):
        await _fail_inside_a_drive(gateway_browser, tmp_path / "first", lent)
    [context] = lent

    with pytest.raises(BrowserError):
        await context.new_page()
    async with driving(gateway_browser, tmp_path / "second", viewport=DESKTOP) as second:
        assert second.page.context is not context


async def _refuse(route: Route) -> None:
    """Refuse whatever the route caught."""
    await route.abort()


async def _fail_inside_a_drive(
    browser: Browser, tmp_path: Path, lent: list[BrowserContext]
) -> None:
    """Open a drive, note the context it was lent, and end it by raising.

    Raises:
        RuntimeError: Always, from inside the drive.
    """
    async with driving(browser, tmp_path, viewport=DESKTOP) as drive:
        lent.append(drive.page.context)
        raise RuntimeError("the case failed")
