"""The layer's harness on the two paths a working browser cannot reach (#1808).

Every case in ``test_browser_page.py`` and ``test_browser_playback.py`` needs a
browser that launched and a context that opened, so two of the harness's own
decisions are unreachable from inside the layer: what a launch refusal *means*
(ADR-0216 §6 — an absent build skips, anything else fails), and what a drive that
never opens leaves behind.

**No browser is taken here, and that is the point rather than a shortcut.** A
module that requested ``gateway_browser`` in order to test what happens when
``gateway_browser`` cannot launch could not be run in the condition it is about;
and a case that drives the page cannot also be the case where opening the page
fails. So the subjects here are the harness's own functions, called directly, over
values a real Playwright hands them.

**This module is deliberately not part of the layer.** It declares neither of
ADR-0216 §3's markers, because it launches nothing and needs no worker of its
own — and ``test_browser_scheduling.py``'s audit, which identifies the layer by
which cases request the browser fixture rather than by which carry its marker,
therefore does not count it. It is beside the layer, not in it.
"""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING, Any, cast

import browser_drive
import pytest
from playwright.async_api import Error as BrowserError

import conftest

if TYPE_CHECKING:
    from pathlib import Path

    from playwright.async_api import Browser

pytestmark = [pytest.mark.usefixtures("hermetic_assistant_env")]

# Playwright's `Browser` is a concrete class rather than a Protocol, so the two
# stand-ins below are cast at the call rather than declared to implement it. What
# `driving()` asks of a browser is one method, and each fake answers exactly that
# one -- a subclass would have to be constructed through a live connection, which
# is the thing these cases exist to do without.


class _RefusingBrowser:
    """A browser that will not open a context at all.

    The realistic failure rather than an invented one: the browser is session-scoped
    and shared by every case in the layer (ADR-0216 §3), so by the time a later case
    asks for a context an earlier one may have crashed it, and Playwright reports
    that with the same ``Error`` class it reports everything with.
    """

    def __init__(self) -> None:
        self.refusal = BrowserError("Target page, context or browser has been closed")

    async def new_context(self, **_: Any) -> Any:
        raise self.refusal


class _UncloseableContext:
    """A context that opens, fails the drive, and then will not close."""

    def __init__(self) -> None:
        self.close_attempted = False

    async def add_init_script(self, script: str) -> None:
        raise BrowserError(f"the frame was detached before {len(script)} bytes ran")

    async def close(self) -> None:
        self.close_attempted = True
        raise BrowserError("the context is already gone")


class _BadlyClosingBrowser:
    """A browser handing out one :class:`_UncloseableContext`."""

    def __init__(self) -> None:
        self.context = _UncloseableContext()

    async def new_context(self, **_: Any) -> Any:
        return self.context


def _is_free(port: int) -> bool:
    """Report whether nothing is listening on ``port`` any more.

    Binding is the question rather than connecting: a listening socket refuses a
    second ``bind`` even with ``SO_REUSEADDR``, so a bind that succeeds is a port the
    gateway really let go of.
    """
    try:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    except OSError:
        return False
    return True


@pytest.mark.integration
async def test_a_drive_whose_context_never_opens_leaves_no_gateway_listening(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refused context does not strand the gateway ``driving()`` has already bound.

    ``gateway.start()`` binds a listening socket before there is anything to drive,
    so every statement after it owes that socket a close. Creating the context
    outside the ``try`` did not: the refusal propagated past a ``finally`` that never
    ran, and because the browser is shared, one crashed browser leaked a gateway per
    remaining case (adversarial review, round 7, ``major``).
    """
    port = browser_drive.free_port()
    monkeypatch.setattr(browser_drive, "free_port", lambda: port)
    browser = _RefusingBrowser()

    with pytest.raises(BrowserError) as raised:
        async with browser_drive.driving(cast("Browser", browser), tmp_path):
            pytest.fail("the drive must not be entered when its context was refused")

    assert raised.value is browser.refusal
    assert _is_free(port), f"the gateway is still listening on {port}"


@pytest.mark.integration
async def test_a_context_that_will_not_close_still_releases_the_gateway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raising ``context.close()`` does not skip the gateway's own teardown.

    The same defect one line over from the one above, and the reason the teardown is
    nested rather than a sequence of statements: ``close()`` was the unguarded first
    thing in the ``finally``, so a context that would not close took ``gateway.close()``
    and ``server.close()`` with it. The close is still attempted first and its failure
    still propagates -- what changed is that it no longer costs the run a live port.
    """
    port = browser_drive.free_port()
    monkeypatch.setattr(browser_drive, "free_port", lambda: port)
    browser = _BadlyClosingBrowser()

    with pytest.raises(BrowserError):
        async with browser_drive.driving(cast("Browser", browser), tmp_path):
            pytest.fail("the drive must not be entered when its probe was refused")

    assert browser.context.close_attempted
    assert _is_free(port), f"the gateway is still listening on {port}"


def test_an_absent_browser_build_skips_naming_the_command_that_installs_it() -> None:
    """ADR-0216 §6's skip, which no clone that can run the layer can reach.

    §6: "Where the browser build the installed ``playwright`` pins is not present, the
    layer skips, with a message naming the command that installs it." Both halves are
    asserted, because a skip that says only "no browser" leaves the reader to find the
    command themselves -- and the message is the whole of what a fresh clone gets.
    """
    refusal = BrowserError(
        "BrowserType.launch: Executable doesn't exist at "
        "/home/dev/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome"
    )

    with pytest.raises(pytest.skip.Exception) as skipped:
        conftest.classify_launch_refusal(refusal)

    assert "uv run playwright install chromium" in str(skipped.value)


def test_a_browser_that_is_present_and_will_not_start_is_a_failure() -> None:
    """Everything but an absent build is reported rather than skipped past.

    The half that makes the skip safe. A missing system library or a refused sandbox
    is a machine that *has* the build and cannot run it, and turning that into a skip
    would let ADR-0216's layer go green having executed nothing -- silently, on
    exactly the runner where it matters. The refusal is re-raised unchanged, so what
    Playwright said is what the report carries.
    """
    refusal = BrowserError(
        "BrowserType.launch: Target page, context or browser has been closed\n"
        "error while loading shared libraries: libnss3.so"
    )

    with pytest.raises(BrowserError) as raised:
        conftest.classify_launch_refusal(refusal)

    assert raised.value is refusal
