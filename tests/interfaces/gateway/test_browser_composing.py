"""The chat page's composing signal, driven (ADR-0332 §5:5 to §5:8).

What the page does while the person types, which the bundle's text cannot say: it sends
*composing* for the open conversation, renewed while the typing goes on and never more
often than once a second (§5:5), and nothing of it is kept — no message, no transcript
entry, nothing in browser storage (§5:8). A signal the hub refuses says nothing on the
page, because the person asked for nothing. The engine is the canonical fake, its
``composing`` wrapped to record when each signal arrived, so the page is driven against
the gateway's real relay.
"""

from __future__ import annotations

import asyncio
import time
from itertools import pairwise
from typing import TYPE_CHECKING, Final

import pytest
from browser_drive import DESKTOP, PHONE, driving
from playwright.async_api import expect

from ai_assistant.core.errors import DeviceRefusal, DeviceRefusedError
from ai_assistant.core.types import ChatDevice, DeviceAccess

if TYPE_CHECKING:
    from pathlib import Path

    from browser_drive import Drive
    from playwright.async_api import Browser, ViewportSize

    from ai_assistant.core.types import Identifier

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
]

#: §5:5's bound, in seconds: no two signals closer than this.
_EVERY: Final = 1.0

#: What a gap between two arrivals may lose to the page's own scheduling and the relay,
#: below §5:5's second. The page counts from when it *sent*, the record from when the
#: hub was reached, so two arrivals can sit a little closer than two sends did.
_JITTER: Final = 0.15

_VIEWPORTS: Final = [DESKTOP, PHONE]


class _Signals:
    """Every composing signal the hub was handed, with when it arrived."""

    def __init__(self, drive: Drive) -> None:
        self.arrived: list[tuple[float, str]] = []
        self.refuse = False
        held = drive.engine.composing

        async def composing(conversation_id: Identifier) -> None:
            self.arrived.append((time.monotonic(), conversation_id))
            if self.refuse:
                msg = "composing needs a device that is an end for writing of the conversation"
                raise DeviceRefusedError(msg, reason=DeviceRefusal.NOT_ALLOWED)
            await held(conversation_id)

        drive.engine.composing = composing  # type: ignore[method-assign]

    async def settled(self, count: int) -> None:
        """Wait, bounded, until ``count`` signals have arrived; the case asserts after."""
        for _ in range(100):
            if len(self.arrived) >= count:
                return
            await asyncio.sleep(0.05)


async def _open(drive: Drive) -> str:
    """Start a conversation this machine writes, and open it in the chat."""
    drive.engine.chat_reader = False  # nothing here is answered
    await drive.engine.set_my_devices([ChatDevice(device_id="hub", access=DeviceAccess.READ_WRITE)])
    started = await drive.engine.start_conversation()
    await drive.page.click("#chat-button")
    await expect(drive.page.locator("#chat-follow")).to_contain_text("Following this chat")
    await drive.page.wait_for_function("() => chat.stream !== null && chat.stream.headed")
    await drive.page.locator("#chat-conversations button.chat-open:not([aria-current])").click()
    await drive.page.wait_for_function("(id) => chat.selected === id", arg=started.id)
    await drive.page.wait_for_function("() => chat.state !== null")
    return started.id


async def _storage(drive: Drive) -> list[list[str]]:
    """Every key and value this page holds in browser storage, of both kinds."""
    held: list[list[str]] = await drive.page.evaluate(
        """() => [window.localStorage, window.sessionStorage].flatMap((store) =>
            Object.keys(store).sort().map((key) => [key, store.getItem(key)]))"""
    )
    return held


@pytest.mark.parametrize("viewport", _VIEWPORTS)
async def test_typing_sends_the_signal_for_the_open_conversation(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """§5:5: a burst of keys inside one second is one signal, naming the conversation.

    Driven at both widths, because the person types on a phone as often as at a desk.
    """
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        conversation = await _open(drive)
        signals = _Signals(drive)

        await drive.page.locator("#chat-text").press_sequentially("on my", delay=20)
        await signals.settled(1)
        await asyncio.sleep(0.3)

        assert [named for _, named in signals.arrived] == [conversation]
        assert await drive.page.evaluate(
            "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )


async def test_the_signal_is_renewed_while_typing_goes_on_and_never_more_than_once_a_second(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§5:5's cadence: renewed while the person keeps typing, never closer than a second.

    About three and a half seconds of steady typing, a key every tenth of a second, so
    the hub is told again before §6:2's three-second lapse could run out — and every two
    signals stand at least a second apart.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        conversation = await _open(drive)
        signals = _Signals(drive)
        box = drive.page.locator("#chat-text")

        started = time.monotonic()
        while time.monotonic() - started < 3.5:
            await box.press("a")
            await asyncio.sleep(0.1)
        await asyncio.sleep(0.3)

        times = [at for at, _ in signals.arrived]
        assert len(times) >= 3, times
        assert len(times) <= 4, times
        gaps = [later - earlier for earlier, later in pairwise(times)]
        assert all(gap >= _EVERY - _JITTER for gap in gaps), gaps
        # Renewed: no gap a lapse of three seconds would have run out in.
        assert all(gap < 3.0 for gap in gaps), gaps
        assert {named for _, named in signals.arrived} == {conversation}


async def test_the_signal_stops_when_the_typing_does(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """Nothing is sent on a clock: once the keys stop, the page says nothing more, and the
    hub lets the last signal lapse (§5:6)."""
    async with driving(gateway_browser, tmp_path) as drive:
        await _open(drive)
        signals = _Signals(drive)

        await drive.page.locator("#chat-text").press_sequentially("hi", delay=20)
        await signals.settled(1)
        await asyncio.sleep(2.5)

        assert len(signals.arrived) == 1


async def test_the_signal_is_never_stored(gateway_browser: Browser, tmp_path: Path) -> None:
    """§5:8: "never written into the transcript, any store or any episode".

    Asserted at both ends: the hub holds no message and was asked to write none, and the
    page put nothing in the transcript on screen, nothing in its pending sends, and
    nothing in browser storage that was not there before the typing.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        conversation = await _open(drive)
        signals = _Signals(drive)
        before = await _storage(drive)
        shown = await drive.page.locator("#chat-transcript").inner_text()

        await drive.page.locator("#chat-text").press_sequentially("half a thought", delay=30)
        await signals.settled(1)
        await asyncio.sleep(1.1)
        await drive.page.locator("#chat-text").press_sequentially(" more", delay=30)
        await signals.settled(2)

        assert len(signals.arrived) >= 2
        assert await _storage(drive) == before
        assert await drive.page.evaluate("() => chat.pending.length") == 0
        assert await drive.page.locator("#chat-transcript").inner_text() == shown
        assert [name for name, _ in drive.engine.calls if name == "write_message"] == []
        page = await drive.engine.transcript(conversation)
        assert page is not None
        assert page.entries == ()


async def test_a_refused_signal_says_nothing_on_the_page(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A device that only reads the conversation is refused by the hub (ADR-0298 §5's
    Writing row, ADR-0332 §5:11), and the page says nothing: the person asked for
    nothing, and the message they send next is answered in full."""
    async with driving(gateway_browser, tmp_path) as drive:
        await _open(drive)
        signals = _Signals(drive)
        signals.refuse = True

        await drive.page.locator("#chat-text").press_sequentially("hello", delay=20)
        await signals.settled(1)
        await asyncio.sleep(0.3)

        assert len(signals.arrived) == 1
        await expect(drive.page.locator("#chat .fault")).to_be_hidden()
        await expect(drive.page.locator("#console")).to_be_visible()
        assert await drive.page.locator("#chat-text").input_value() == "hello"


async def test_sending_the_message_sends_no_signal(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """Emptying the composer once the message is sent is the page's act, not typing."""
    async with driving(gateway_browser, tmp_path) as drive:
        await _open(drive)
        await drive.page.fill("#chat-text", "Book the usual campsite.")
        await drive.page.wait_for_function(
            "() => !composingOut"
        )  # the one signal the fill sent has been answered
        signals = _Signals(drive)
        await asyncio.sleep(_EVERY + 0.1)

        await drive.page.click("#chat-send")
        await expect(drive.page.locator("#chat-transcript li").last).to_contain_text(
            "Book the usual campsite."
        )
        await asyncio.sleep(0.3)

        assert signals.arrived == []
        assert await drive.page.locator("#chat-text").input_value() == ""
