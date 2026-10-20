"""The hosted page, driven through a fake sign-in edge in a real browser (ADR-0327 §11).

**The edge is a route on the browser's context.** The page is opened at the door's own
origin, ``https://door.example.test``, and every request the browser makes to it is
forwarded by the route to the gateway's hosted listener on the box's loopback — with
the door's `Host` and an ``Edge-Assertion`` the fake edge (:mod:`gateway_edge`) signs
for that request, exactly what the real edge adds (§2:1, §6:1). The browser never sees
an assertion, as it never does through the real door (§9:2).

**Streams are held, not forwarded.** A route answers a request whole, so a delivery
stream or the chat's following cannot be carried through one; they are held open
unanswered, which is a stream that has not yet said anything. Nothing here is about
either, and the page's exchange is what every case observes.

**Every case counts the exchanges the page made**, because §11:2 and §11:3 are rules
about how many: at most one per event, and none after a failure until the owner acts.

**Nothing sleeps** (ADR-0216 §7): each case waits on a state the page reaches.

**The edge stops before its context closes** (issue #3168). A case ends on the state it
asserted, not on the page having nothing more to ask for — a web font the browser
fetches for the panel it has just drawn is commonly still being forwarded. A route
callback that raises is not raised in its case: Playwright keeps the error and raises it
from the connection's *next* call, which is the next case's ``browser.new_context``. And
closing the context makes the forward raise: ``context.close()`` disposes the context's
request client first, which disposes every response it fetched, so a ``route.fulfill``
of one fetched just before is refused — "Fetch response has been disposed" — while the
page is still open to receive it. So the door unroutes with ``behavior="ignoreErrors"``
first, Playwright's own remedy, under which what a callback still running raises after
the unroute is swallowed rather than kept — and answers the streams it held once the
context is closed, so none of their handling is left pending.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import gateway_ports
import pytest
from browser_drive import DESKTOP, PHONE, SESSION_IDLE_MARGIN, DriveEngine, press
from gateway_edge import DOOR, DOOR_ORIGIN, HOSTED_DEVICE, FakeEdge
from gateway_timing import Clock, Timers
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import expect

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import DeviceRefusal, DeviceRefusedError
from ai_assistant.core.types import ChatDevice, DeviceAccess
from ai_assistant.interfaces.gateway.server import Gateway, packaged_bundle

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from playwright.async_api import Browser, BrowserContext, Page, Route, ViewportSize

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
]

#: The paths whose response is a stream, which a route cannot carry (module docstring).
_STREAMED = ("/deliveries", "/chat/follow")


@dataclass
class Door:
    """The fake edge in front of one gateway's hosted listener, and the page behind it.

    Attributes:
        page: The page, opened at the door's origin.
        gateway: The gateway.
        engine: The engine behind it.
        edge: The fake edge, whose key the gateway is configured with.
        clock: The gateway's clock.
        timers: Everything the gateway deferred.
        exchanges: How many exchanges the page has made through the door.
        signing: Whether the edge signs requests — a person whose sign-in has ended is
            one it stops forwarding with an assertion for.
        refuse_exchange: Whether the edge signs the exchange for another account, so
            the gateway refuses it at the door (§7:6).
        drop_exchange: Whether the exchange is lost on its way, as a gateway that is
            not answering loses it.
        swap_cookie: A cookie half to forward in place of the browser's own, on the next
            conversations listing alone.
        hold_exchange: Set, an exchange waits on it before it is forwarded, so a case
            can make a second refusal arrive while one is out.
        held: The stream requests held open.
        forwards: Every forward's task, so a case can wait out one that its door was
            closed under.
    """

    page: Page
    gateway: Gateway
    engine: DriveEngine
    edge: FakeEdge
    clock: Clock
    timers: Timers
    port: int
    exchanges: int = 0
    signing: bool = True
    refuse_exchange: bool = False
    drop_exchange: bool = False
    swap_cookie: str | None = None
    hold_exchange: asyncio.Event | None = None
    held: list[Route] = field(default_factory=list)
    forwards: list[asyncio.Task[Any]] = field(default_factory=list)

    async def forward(self, route: Route) -> None:
        """Forward one request to the hosted listener, as the edge does."""
        # Playwright runs each callback as a task of its own (`RouteHandler`), so the
        # current one is this forward and nothing wider.
        task = asyncio.current_task()
        assert task is not None
        self.forwards.append(task)
        request = route.request
        path = request.url.removeprefix(DOOR_ORIGIN).split("?")[0]
        if path in _STREAMED:
            self.held.append(route)
            return
        headers = dict(request.headers)
        headers["host"] = DOOR
        if path == "/session/edge":
            self.exchanges += 1
            if self.hold_exchange is not None:
                await self.hold_exchange.wait()
            if self.drop_exchange:
                await route.abort("connectionreset")
                return
        if self.signing:
            subject: dict[str, Any] = (
                {"sub": "someone-else"} if path == "/session/edge" and self.refuse_exchange else {}
            )
            headers["edge-assertion"] = self.edge.sign(self.clock(), **subject)
        if self.swap_cookie is not None and path == "/conversations":
            headers["cookie"] = f"__Host-assistant_session={self.swap_cookie}"
            self.swap_cookie = None
        response = await route.fetch(
            url=f"http://127.0.0.1:{self.port}{path}", headers=headers, max_redirects=0
        )
        await route.fulfill(response=response)

    def expire_sessions(self) -> None:
        """Move past every session's idle bound and fire what that armed."""
        self.clock.advance(SESSION_IDLE_MARGIN)
        self.timers.fire_all()


@contextlib.asynccontextmanager
async def through_the_door(
    browser: Browser,
    tmp_path: Path,
    *,
    viewport: ViewportSize | None = None,
    open_page: bool = True,
    **overrides: Any,
) -> AsyncIterator[Door]:
    """Bind a gateway with its hosted listener, and open the page through the fake edge.

    Args:
        browser: The one browser this run launched.
        tmp_path: The case's data directory (ADR-0216 §4).
        viewport: The window, or ``None`` for :data:`DESKTOP`.
        open_page: Whether to open the page; ``False`` for a case that sets the door
            up first.
        **overrides: Any setting to replace.

    Yields:
        The door.
    """
    edge = FakeEdge()
    settings = Settings(
        gateway_port=gateway_ports.free_port(),
        data_dir=tmp_path,
        **edge.settings(gateway_hosted_port=gateway_ports.free_port(), **overrides),
    )
    clock, timers = Clock(reading=datetime.now(UTC).replace(microsecond=0)), Timers()
    engine = DriveEngine()
    gateway = Gateway(
        settings=settings,
        engine=engine,
        now=clock,
        defer=timers,
        bundle=packaged_bundle(),
        hosted_bundle=packaged_bundle(hosted=True),
    )
    servers = [await gateway.start()]
    hosted = await gateway.start_hosted()
    assert hosted is not None
    servers.append(hosted)
    context: BrowserContext | None = None
    held: list[Route] = []
    try:
        context = await browser.new_context(viewport=viewport or DESKTOP)
        page = await context.new_page()
        door = Door(
            page=page,
            gateway=gateway,
            engine=engine,
            edge=edge,
            clock=clock,
            timers=timers,
            port=settings.gateway_hosted_port,
            held=held,
        )
        await context.route(f"{DOOR_ORIGIN}/**", door.forward)
        if open_page:
            await page.goto(f"{DOOR_ORIGIN}/")
        yield door
    finally:
        try:
            if context is not None:
                # The edge first, so a forward still out when the case ended raises at
                # nobody (module docstring). Nested, so a callback's error from inside
                # the case — which this unroute is the connection's next call for, and
                # so raises — is the case's failure without leaving the context open.
                try:
                    await context.unroute_all(behavior="ignoreErrors")
                finally:
                    await context.close()
                    # A held stream's callback has returned, but Playwright's handling
                    # of its request still waits on the answer it never got. Answered
                    # here, into the closed context, where nothing receives it — so no
                    # handling is left pending for the run's loop to cancel at its
                    # close, where, with the route above gone, Playwright's clean-up
                    # of it raises into the connection's kept error.
                    for route in held:
                        with contextlib.suppress(PlaywrightError):
                            await route.abort()
        finally:
            gateway.close()
            for server in servers:
                server.close()
                server.close_clients()
                with contextlib.suppress(Exception):
                    await server.wait_closed()


async def _settled(door: Door) -> None:
    """Wait for the page to finish whatever exchange it started: the console is up, or
    the hosted panel offers the owner's act."""
    await expect(
        door.page.locator("#console:not([hidden]), #hosted-again:not([hidden])")
    ).to_be_visible()


# --- §11:1, §11:7: no bootstrap entry, and what the page says it lasts for -------------


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
async def test_the_page_starts_its_own_session_through_the_door(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """§11:1: "the page shows no bootstrap entry. It mints its session by §8's
    exchange, with nothing typed" — one exchange, on the load that held no half."""
    async with through_the_door(gateway_browser, tmp_path, viewport=viewport) as door:
        await expect(door.page.locator("#console")).to_be_visible()

        assert door.exchanges == 1
        await expect(door.page.locator("#bootstrap")).to_be_hidden()
        await expect(door.page.locator("#bootstrap-value")).to_be_hidden()
        await expect(door.page.locator("#hosted")).to_be_hidden()


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
async def test_the_page_says_it_stays_signed_in_as_long_as_the_sign_in(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """§11:7: stated "without requiring an interaction to reveal it" — and the three
    conditions whose remedy is a bootstrap value are not, on this door."""
    async with through_the_door(gateway_browser, tmp_path, viewport=viewport) as door:
        await _settled(door)

        terms = door.page.locator("#hosted-terms")
        await expect(terms).to_be_visible()
        await expect(terms).to_contain_text("stays signed in for as long as your sign-in lasts")
        await expect(terms).to_contain_text("sign in again at the sign-in page")
        await expect(door.page.locator("#session-terms")).to_be_hidden()


async def test_a_page_holding_a_live_session_makes_no_exchange(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§11:2: the load event is a load "holding no header half". A reload inside the
    session carries on in it."""
    async with through_the_door(gateway_browser, tmp_path) as door:
        await expect(door.page.locator("#console")).to_be_visible()
        await door.page.reload()
        await expect(door.page.locator("#console")).to_be_visible()
        await press(door.page, "#conversations-button")
        await expect(door.page.locator("#conversations")).to_be_visible()

        assert door.exchanges == 1


# --- §11's three outcomes of an exchange, and §11:3's one attempt ---------------------


async def test_a_door_refusal_of_the_exchange_says_where_signing_in_happens(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§11:6: shown "as the door refusing the request, with the statement that signing
    in again happens at the sign-in page, and the page makes no exchange for it"."""
    async with through_the_door(gateway_browser, tmp_path, open_page=False) as door:
        door.refuse_exchange = True
        await door.page.goto(f"{DOOR_ORIGIN}/")
        await _settled(door)

        state = door.page.locator("#hosted-state")
        await expect(state).to_contain_text("The sign-in door refused this request")
        await expect(state).to_contain_text("sign in again at the sign-in page")
        await expect(door.page.locator("#hosted-again")).to_be_visible()
        await expect(door.page.locator("#console")).to_be_hidden()
        assert door.exchanges == 1


async def test_a_failed_exchange_says_only_that_it_failed(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§8:2: "a failed exchange discloses only that it failed" — here, the ceiling held
    by sessions another listener minted, which a hosted exchange never ends (§8:6)."""
    async with through_the_door(
        gateway_browser, tmp_path, open_page=False, gateway_max_sessions=1
    ) as door:
        assert door.gateway._sessions.mint() is not None
        await door.page.goto(f"{DOOR_ORIGIN}/")
        await _settled(door)

        state = door.page.locator("#hosted-state")
        await expect(state).to_contain_text("That did not start a session.")
        await expect(state).to_contain_text("Nothing more is tried until you try again.")
        await expect(door.page.locator("#hosted-again")).to_be_visible()
        assert door.exchanges == 1


async def test_a_gateway_that_does_not_answer_is_said_as_one(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0168 §9's distinction, through the door: an exchange that got no answer is
    the gateway not answering, said beside the panel that is up, with the hosted
    remedy rather than a bootstrap value's."""
    async with through_the_door(gateway_browser, tmp_path, open_page=False) as door:
        door.drop_exchange = True
        await door.page.goto(f"{DOOR_ORIGIN}/")
        await _settled(door)

        slot = door.page.locator("#hosted .fault")
        await expect(slot).to_contain_text("The gateway did not answer")
        await expect(slot).to_contain_text("starts a new session through your sign-in")
        await expect(slot).not_to_contain_text("the value it prints")
        assert door.exchanges == 1


async def test_after_a_failure_the_next_exchange_is_the_owners_to_make(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§11:3: "After a failed exchange the page makes no further one until the owner
    acts, a reload included. A page may not turn the exchange into a retry loop."

    The page is left alone, then shown again — the events a page could mistake for a
    reason to try — and makes nothing; then the owner tries again, and that is one."""
    async with through_the_door(gateway_browser, tmp_path, open_page=False) as door:
        door.refuse_exchange = True
        await door.page.goto(f"{DOOR_ORIGIN}/")
        await _settled(door)
        await door.page.evaluate("window.dispatchEvent(new Event('online'))")
        await door.page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        # A round trip through the door after both events, so anything they started
        # has had the time to be counted.
        await door.page.evaluate("fetch('/door.js').then(() => null)")
        assert door.exchanges == 1

        door.refuse_exchange = False
        await door.page.click("#hosted-again")
        await expect(door.page.locator("#console")).to_be_visible()
        assert door.exchanges == 2


# --- §11:2, §11:4: a session that ended is replaced once, and nothing is re-sent -------


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
async def test_a_session_that_ended_is_replaced_by_one_exchange_and_nothing_is_resent(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """§11:2's second event: the gateway refusing the half the page holds as no live
    session. One exchange, the console back, and the refused request not re-issued
    (§11:4) — the page says so where the owner reads what it is watching."""
    async with through_the_door(gateway_browser, tmp_path, viewport=viewport) as door:
        await expect(door.page.locator("#console")).to_be_visible()
        door.expire_sessions()
        await press(door.page, "#conversations-button")

        await expect(door.page.locator("#delivery-state")).to_contain_text(
            "started a new one through your sign-in"
        )
        await expect(door.page.locator("#console")).to_be_visible()
        await expect(door.page.locator("#conversations")).to_be_hidden()
        await expect(door.page.locator("#watch-button")).to_be_visible()
        assert door.exchanges == 2

        # The new session admits: the owner's next act is served.
        await press(door.page, "#conversations-button")
        await expect(door.page.locator("#conversations")).to_be_visible()
        assert door.exchanges == 2


async def test_two_refusals_at_once_start_one_session(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§11:2: "at most one exchange for each such event" — and an exchange in flight is
    the one for every refusal that arrives while it is."""
    async with through_the_door(gateway_browser, tmp_path) as door:
        await expect(door.page.locator("#console")).to_be_visible()
        door.expire_sessions()
        door.hold_exchange = asyncio.Event()
        # Two of the page's own reads, out at once under the session that has ended:
        # the first refusal starts the exchange, which the edge holds, and the second
        # arrives while it is out.
        await door.page.evaluate("() => { void listConversations(); void listSources(); }")
        await expect(door.page.locator("#hosted-state")).to_contain_text("Starting a session")
        await door.page.evaluate("fetch('/door.js').then(() => null)")
        await door.page.evaluate("fetch('/door.js').then(() => null)")
        door.hold_exchange.set()
        await expect(door.page.locator("#delivery-state")).to_contain_text(
            "started a new one through your sign-in"
        )

        assert door.exchanges == 2


# --- §11:5, §11:6: the two refusals that are shown and not exchanged for ---------------


async def test_a_cookie_half_mismatch_is_shown_as_itself_and_exchanged_for_by_nobody(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§11:5: "a refusal that ADR-0168 §6:4 reports as its own fault is shown as that
    fault, and the page makes no exchange for it"."""
    async with through_the_door(gateway_browser, tmp_path) as door:
        await expect(door.page.locator("#console")).to_be_visible()
        door.swap_cookie = "not-this-sessions-cookie-half"
        await press(door.page, "#conversations-button")

        state = door.page.locator("#hosted-state")
        await expect(state).to_contain_text(
            "The two halves of this browser's session no longer match."
        )
        await expect(door.page.locator("#hosted-again")).to_be_visible()
        await expect(door.page.locator("#console")).to_be_hidden()
        assert door.exchanges == 1


async def test_a_door_refusal_mid_session_says_where_signing_in_happens(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§11:6, on a page already in use: the person's sign-in ends, the edge stops
    signing, and the page says the door refused and makes no exchange."""
    async with through_the_door(gateway_browser, tmp_path) as door:
        await expect(door.page.locator("#console")).to_be_visible()
        door.signing = False
        await press(door.page, "#conversations-button")

        state = door.page.locator("#hosted-state")
        await expect(state).to_contain_text("The sign-in door refused this request")
        await expect(door.page.locator("#hosted-again")).to_be_visible()
        assert door.exchanges == 1


# --- What the hub refuses, said to the person on the door (ADR-0327 §10) --------------

#: What nothing the page says through the door names: the commands, the machine, the
#: device id. The person there can run none of them and has never heard of the id.
_OPERATOR_WORDS = ("ai-assistant-device", "my-devices", "hub's machine", HOSTED_DEVICE)


@pytest.mark.parametrize("reason", list(DeviceRefusal))
async def test_a_refused_first_conversation_says_who_can_turn_it_on(
    gateway_browser: Browser, tmp_path: Path, reason: DeviceRefusal
) -> None:
    """The owner's first message through the door was refused with an operator's command
    line. Each of ADR-0298 §6's reasons is now said as what is not set up, and who can set
    it up — and still as its own sentence."""
    async with through_the_door(gateway_browser, tmp_path, viewport=PHONE) as door:

        async def refused() -> Any:
            msg = "refused for the device"
            raise DeviceRefusedError(msg, reason=reason)

        door.engine.start_conversation = refused  # type: ignore[method-assign]
        await expect(door.page.locator("#console")).to_be_visible()
        await door.page.click("#chat-button")
        await door.page.click("#chat-start")

        slot = door.page.locator("#chat .fault")
        await expect(slot).to_contain_text("That didn't go through, so nothing was done.")
        await expect(slot).to_contain_text("The person who set it up for you")
        said = await slot.inner_text()
        for word in _OPERATOR_WORDS:
            assert word not in said


async def test_the_devices_note_names_no_command_through_the_door(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ "My devices" is changed at the command line, which the person on the door has no
    way to run: the note says who can add this page instead."""
    async with through_the_door(gateway_browser, tmp_path) as door:
        await expect(door.page.locator("#console")).to_be_visible()
        await door.page.click("#chat-button")

        note = door.page.locator("#chat-this-device")
        await expect(note).to_contain_text("This page is not one of your devices yet")
        await expect(note).to_contain_text("The person who set up your assistant can add it.")
        said = await note.inner_text()
        for word in _OPERATOR_WORDS:
            assert word not in said


# --- The phone: the box to write in stays on screen, and nothing scrolls sideways ------

#: What is left of a 390x844 screen with a phone's keyboard up.
_KEYBOARD_UP = 508

#: A message a phone has to wrap somewhere other than at a space.
_UNBROKEN = "https://example.com/" + "a-path-with-no-place-to-break-" * 6


async def test_on_a_phone_the_box_to_write_in_is_on_screen_and_nothing_scrolls_sideways(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """At 390px the open conversation's send control is inside the first screen, a long
    unbroken message wraps rather than widening the page, and with the keyboard up a
    message of many lines grows the box to a share of the screen and no further, the
    send control still on it."""
    async with through_the_door(gateway_browser, tmp_path, viewport=PHONE) as door:
        await door.engine.set_my_devices(
            [ChatDevice(device_id=HOSTED_DEVICE, access=DeviceAccess.READ_WRITE)]
        )
        await door.engine.start_conversation()
        await expect(door.page.locator("#console")).to_be_visible()
        await door.page.click("#chat-button")
        await door.page.locator("#chat-conversations button.chat-open").click()
        await expect(door.page.locator("#chat-thread")).to_be_visible()

        await door.page.fill("#chat-text", _UNBROKEN)
        await door.page.click("#chat-send")
        await expect(door.page.locator("#chat-transcript li").last).to_contain_text(
            "a-path-with-no-place"
        )
        page_width = await door.page.evaluate("document.documentElement.scrollWidth")
        assert page_width <= PHONE["width"]

        send = await door.page.locator("#chat-send").bounding_box()
        assert send is not None
        assert send["y"] + send["height"] <= PHONE["height"]

        # The keyboard up, where the browser shrinks the page for it: the box grows to a
        # share of what is left of the screen and no further.
        await door.page.set_viewport_size({"width": PHONE["width"], "height": _KEYBOARD_UP})
        await door.page.fill("#chat-text", "\n".join(f"line {n}" for n in range(12)))
        box = await door.page.locator("#chat-text").bounding_box()
        send = await door.page.locator("#chat-send").bounding_box()
        assert box is not None
        assert send is not None
        assert box["height"] <= _KEYBOARD_UP * 0.2 + 1
        assert send["y"] + send["height"] <= _KEYBOARD_UP


async def test_the_page_asks_a_phone_to_make_room_for_its_keyboard(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The chat is sized to the screen, so the keyboard must shrink the screen rather
    than cover the box being typed in, where the browser offers the choice."""
    async with through_the_door(gateway_browser, tmp_path, viewport=PHONE) as door:
        viewport = await door.page.get_attribute("meta[name=viewport]", "content")

    assert viewport is not None
    assert "interactive-widget=resizes-content" in viewport


# --- The harness: a forward the door was closed under -----------------------------------


async def test_a_forward_still_out_when_the_door_closes_fails_no_later_case(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """Issue #3168: a request the edge was still forwarding when its case ended raises
    into nothing after the door is gone — not into the next case's first call.

    The exchange is held at the edge across the door's whole teardown and let go once
    the context is closed, so its ``route.fetch`` runs against a request client that
    ``close()`` disposed. That is one window of the two this guards; the other, a
    fetched response fulfilled between the disposal and the close, is as narrow as a
    single message and cannot be held open from outside Playwright. The two meet the
    same mechanism — a callback's error kept for the connection's next call — and the
    one unroute closes both.

    **The error is kept for the next call and raised at its start**, so the case makes
    two once the forward has ended: the first may begin before the error is kept, and
    the round trip it waits on means the second cannot.
    """
    release = asyncio.Event()
    async with through_the_door(gateway_browser, tmp_path, open_page=False) as door:
        door.hold_exchange = release
        await door.page.goto(f"{DOOR_ORIGIN}/")
        await expect(door.page.locator("#hosted-state")).to_contain_text("Starting a session")
        assert door.exchanges == 1
    release.set()
    await asyncio.wait(door.forwards)

    after = await gateway_browser.new_context()
    await after.close()


async def test_the_page_never_holds_an_assertion(gateway_browser: Browser, tmp_path: Path) -> None:
    """§9:2, §9:4: "the browser never holds one" — it is added on the box, after the
    browser's request has left it, and nothing the gateway answers carries one."""
    async with through_the_door(gateway_browser, tmp_path) as door:
        await expect(door.page.locator("#console")).to_be_visible()

        held = await door.page.evaluate(
            "() => JSON.stringify({...window.localStorage}) + document.cookie"
        )
        assert "eyJ" not in held
