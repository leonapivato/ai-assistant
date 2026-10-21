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
from typing import TYPE_CHECKING, Final

import pytest
from browser_drive import DESKTOP, PHONE, driving
from playwright.async_api import expect

from ai_assistant.core.errors import DeviceRefusal, DeviceRefusedError
from ai_assistant.core.types import ChatDevice, DeviceAccess

if TYPE_CHECKING:
    from pathlib import Path

    from browser_drive import Drive
    from playwright.async_api import Browser, Route, ViewportSize

    from ai_assistant.core.types import Identifier

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
]

#: §5:5's bound, in milliseconds: no two signals closer than this.
_EVERY: Final = 1000

#: Where the page's clock is paused from: any instant, so long as it is fixed.
_PAUSED_AT: Final = 1_800_000_000_000

_VIEWPORTS: Final = [DESKTOP, PHONE]


class _Signals:
    """Every composing signal the hub was handed, in order."""

    def __init__(self, drive: Drive) -> None:
        self.arrived: list[str] = []
        self.refuse = False
        #: Set to hold every signal at the hub until it is released, as a slow hub would.
        self.held: asyncio.Event | None = None
        #: How many signals the hub was working on at once, at most.
        self.most_at_once = 0
        self._at_once = 0
        held = drive.engine.composing

        async def composing(conversation_id: Identifier) -> None:
            self.arrived.append(conversation_id)
            self._at_once += 1
            self.most_at_once = max(self.most_at_once, self._at_once)
            try:
                if self.held is not None:
                    await self.held.wait()
            finally:
                self._at_once -= 1
            if self.refuse:
                msg = "composing needs a device that is an end for writing of the conversation"
                raise DeviceRefusedError(msg, reason=DeviceRefusal.NOT_ALLOWED)
            await held(conversation_id)

        drive.engine.composing = composing  # type: ignore[method-assign]

    async def reached(self, count: int) -> None:
        """Wait, bounded, until ``count`` signals have reached the hub."""
        for _ in range(200):
            if len(self.arrived) >= count:
                return
            await asyncio.sleep(0.025)
        msg = f"{count} composing signals never reached the hub"
        raise AssertionError(msg)


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


async def _pause(drive: Drive) -> None:
    """Take the page's clock off the wall, so time moves only when the case moves it."""
    await drive.page.clock.install(time=_PAUSED_AT)
    await drive.page.clock.pause_at(_PAUSED_AT + _EVERY)


async def _quiet(drive: Drive) -> None:
    """Wait, bounded, until the page has no signal out: each it sent has been answered.

    Asked of the page in real time rather than through a wait the page's clock drives,
    because that clock is paused.
    """
    for _ in range(200):
        if await drive.page.evaluate("() => !composingOut"):
            return
        await asyncio.sleep(0.025)
    msg = "a composing signal stayed out"
    raise AssertionError(msg)


async def _key(drive: Drive, key: str = "a") -> None:
    """Press one key in the composer, and wait until what it sent, if anything, landed."""
    await drive.page.locator("#chat-text").press(key)
    await _quiet(drive)


async def _storage(drive: Drive) -> list[list[str]]:
    """Every key and value this page holds in browser storage, of both kinds."""
    held: list[list[str]] = await drive.page.evaluate(
        """() => [window.localStorage, window.sessionStorage].flatMap((store) =>
            Object.keys(store).sort().map((key) => [key, store.getItem(key)]))"""
    )
    return held


@pytest.mark.parametrize("viewport", _VIEWPORTS)
async def test_a_burst_of_keys_inside_a_second_is_one_signal_for_the_open_conversation(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """§5:5: the signal names the conversation typed into, at most once a second.

    Driven at both widths, because the person types on a phone as often as at a desk.
    """
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        conversation = await _open(drive)
        signals = _Signals(drive)
        await _pause(drive)

        for _ in range(5):
            await _key(drive)
            await drive.page.clock.run_for(150)

        assert signals.arrived == [conversation]
        assert await drive.page.evaluate(
            "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )


async def test_the_signal_is_renewed_once_a_second_while_typing_goes_on(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§5:5's cadence, on the boundary: a key a millisecond short of a second sends
    nothing, one at the second sends the renewal, and steady typing renews it every
    second after — inside §6:2's three-second lapse, so the hub never lets it go."""
    async with driving(gateway_browser, tmp_path) as drive:
        conversation = await _open(drive)
        signals = _Signals(drive)
        await _pause(drive)

        await _key(drive)
        assert len(signals.arrived) == 1
        await drive.page.clock.run_for(_EVERY - 1)
        await _key(drive)
        assert len(signals.arrived) == 1
        await drive.page.clock.run_for(1)
        await _key(drive)
        assert len(signals.arrived) == 2

        # Two more seconds of a key every tenth: renewed at the second and the third.
        for _ in range(20):
            await drive.page.clock.run_for(100)
            await _key(drive)

        assert signals.arrived == [conversation] * 4


async def test_nothing_is_sent_once_the_typing_stops(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """No clock sends the signal: once the keys stop, the page says nothing more, and the
    hub lets the last one lapse (§5:6)."""
    async with driving(gateway_browser, tmp_path) as drive:
        await _open(drive)
        signals = _Signals(drive)
        await _pause(drive)

        await _key(drive)
        await drive.page.clock.run_for(10 * _EVERY)
        await _quiet(drive)

        assert len(signals.arrived) == 1


async def test_a_signal_still_out_holds_the_next_back_and_is_never_replaced(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """One signal out at a time, and never a second relay behind it.

    The hub holds the first signal, as a slow hub would, after the gateway has admitted
    it and taken a hub connection for it. Typing on for several seconds sends nothing
    more, so the gateway never holds a second connection for the signal — a page that
    replaced the slow one would take one more for each (ADR-0168 §8). Once the first is
    answered, the next key past the cadence sends again.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        conversation = await _open(drive)
        signals = _Signals(drive)
        signals.held = asyncio.Event()
        await _pause(drive)

        await drive.page.locator("#chat-text").press("a")
        await signals.reached(1)
        for _ in range(10):
            await drive.page.clock.run_for(_EVERY)
            await drive.page.locator("#chat-text").press("a")
        await asyncio.sleep(0.2)
        assert signals.arrived == [conversation]
        assert signals.most_at_once == 1
        assert await drive.page.evaluate("() => composingOut")

        signals.held.set()
        await _quiet(drive)
        await drive.page.clock.run_for(_EVERY)
        await _key(drive)

        assert signals.arrived == [conversation] * 2
        assert signals.most_at_once == 1


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
        await _pause(drive)

        for key in "half a thought":
            await _key(drive, key)
            await drive.page.clock.run_for(300)

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
        await _pause(drive)

        for key in "hello":
            await _key(drive, key)

        assert len(signals.arrived) == 1
        await expect(drive.page.locator("#chat .fault")).to_be_hidden()
        await expect(drive.page.locator("#console")).to_be_visible()
        assert await drive.page.locator("#chat-text").input_value() == "hello"


@pytest.mark.parametrize("viewport", _VIEWPORTS)
async def test_a_signal_lost_at_the_network_holds_nothing_back(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """A lost request is a signal not sent, and the next key past the cadence sends again.

    The refusal case above is answered, so its ``fetch`` resolves; this one rejects. The
    first signal is reset at the network, before the gateway ever sees it, and the page
    still clears its one-out guard: typing on past a second sends the next signal, the
    panel says nothing, and the draft is the person's, untouched. A guard cleared only on
    an answer would leave this tab silent from the first lost request on.
    """
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        conversation = await _open(drive)
        signals = _Signals(drive)
        asked: list[str] = []

        async def lose_the_first(route: Route) -> None:
            asked.append(route.request.url)
            if len(asked) == 1:
                await route.abort("connectionreset")
            else:
                await route.fallback()

        await drive.page.route("**/chat/composing", lose_the_first)
        try:
            await _pause(drive)

            await _key(drive, "h")
            assert len(asked) == 1
            assert signals.arrived == []

            for key in "ello":
                await drive.page.clock.run_for(_EVERY // 5)
                await _key(drive, key)
            await drive.page.clock.run_for(_EVERY)
            await _key(drive, "!")

            assert len(asked) == 2
            assert signals.arrived == [conversation]
            await expect(drive.page.locator("#chat .fault")).to_be_hidden()
            await expect(drive.page.locator("#console")).to_be_visible()
            assert await drive.page.locator("#chat-text").input_value() == "hello!"
        finally:
            await drive.page.unroute("**/chat/composing", lose_the_first)


async def test_sending_the_message_sends_no_signal(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """Emptying the composer once the message is sent is the page's act, not typing."""
    async with driving(gateway_browser, tmp_path) as drive:
        await _open(drive)
        signals = _Signals(drive)
        await drive.page.fill("#chat-text", "Book the usual campsite.")
        await _quiet(drive)
        assert len(signals.arrived) == 1
        # Past the cadence, so a signal the send fired would be sent rather than held.
        await drive.page.evaluate("() => { composingAt = -Infinity; }")

        await drive.page.click("#chat-send")
        await expect(drive.page.locator("#chat-transcript li").last).to_contain_text(
            "Book the usual campsite."
        )
        await _quiet(drive)

        assert len(signals.arrived) == 1
        assert await drive.page.locator("#chat-text").input_value() == ""
