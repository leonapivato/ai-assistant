"""The shipped page, loaded and run by a real browser (ADR-0216 §1).

Nothing in this repository executed a line of ``app.js`` before this module
existed. ``test_bundle.py`` reads the same file as text and is the better
instrument for what a reading decides — an enumeration agreeing with
``core/types.py``, a must-not-contain over the whole artifact — and ADR-0216 §2
keeps it for exactly that. What it cannot decide is whether the 8,000 lines it
reads *run*: a substring assertion is as green over a file with a syntax error in
it, an undefined identifier on the start-up path, or a listener that throws the
first time a browser reaches it.

So the cases here are the ones only loading the page answers, and they are
deliberately the cheapest of the layer: the bundle parses and runs, and everything
it asks for comes from the gateway and from nowhere else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from browser_drive import driving

if TYPE_CHECKING:
    from pathlib import Path

    from playwright.async_api import Browser, ConsoleMessage

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
]

#: The one console error a correct page produces, and it is the browser's rather
#: than the page's: a browser asks for a favicon on its own, and admission is
#: decided before routing (ADR-0168 §3), so a session-less request to any path
#: answers 401. It is filtered by the URL that produced it, so a 401 logged
#: against anything the page itself asked for is still a failure. An *admitted*
#: request to an unserved path answers 404, which ``test_gateway.py`` pins.
_BROWSERS_OWN_PROBE = "/favicon.ico"


async def test_the_shipped_bundle_parses_and_runs_in_a_real_browser(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The page loads, runs, and reaches its own bootstrap state without throwing.

    ADR-0216 §1: "The suite loads the shipped ``index.html``, ``app.js`` and
    ``app.css`` into a real browser and asserts on what the page does." This is the
    floor of that. An uncaught exception anywhere on the start-up path fails it,
    and no assertion over the same bytes as text can.
    """
    thrown: list[str] = []
    complaints: list[str] = []
    async with driving(gateway_browser, tmp_path, admitted=False) as drive:
        drive.page.on("pageerror", lambda error: thrown.append(str(error)))
        drive.page.on("console", lambda message: _note(message, complaints))
        await drive.page.reload()
        await drive.page.wait_for_selector("#bootstrap-form")
        await drive.admit()

        assert thrown == []
        assert complaints == []


async def test_the_page_asks_the_gateway_for_everything_and_no_other_origin_for_anything(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0168 §10's origin clause, observed rather than inferred.

    "The page it serves loads no asset, font, style, script or datum from any
    origin but the gateway's own." ``test_bundle.py`` can say the shipped bytes
    hold no foreign URL, which is a strong claim about the artifact and not this
    one: a URL the page *builds* at run time is absent from the text and present in
    the network log. ADR-0216 §4 makes this layer the place that reads the log —
    "the browser loads the bundle from that gateway and from no other origin".
    """
    asked: list[str] = []
    async with driving(gateway_browser, tmp_path, admitted=False) as drive:
        drive.page.on("request", lambda request: asked.append(request.url))
        await drive.page.reload()
        await drive.page.wait_for_selector("#bootstrap-form")
        await drive.admit()
        await drive.page.fill("#utterance", "what is on today")
        await drive.page.click("#ask-form button[type=submit]")
        await drive.page.wait_for_selector("#answer:not([hidden])")

        assert asked != []
        assert [url for url in asked if not url.startswith(f"{drive.origin}/")] == []


def _note(message: ConsoleMessage, complaints: list[str]) -> None:
    """Keep every console error but the one the browser makes on its own."""
    if message.type == "error" and not message.location["url"].endswith(_BROWSERS_OWN_PROBE):
        complaints.append(f"{message.location['url']}: {message.text}")
