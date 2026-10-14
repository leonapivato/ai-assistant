"""Driving the shipped page in a real browser (ADR-0216).

A plain module beside ``gateway_mint`` and ``gateway_timing``, and for the same
reason: ``mypy`` refuses a second ``conftest.py`` where the test tree carries no
packages. The one fixture that *has* to be shared across modules — the browser
itself, which ADR-0216 §3 says is "started once and shared by every case in the
layer" — therefore lives in the corpus's single ``tests/conftest.py``, because a
session-scoped fixture imported into two test modules is two fixture definitions
and would be two browsers.

**What this module is for.** ADR-0216 §1 makes the front end executed rather than
only read: the browser loads the shipped ``index.html``, ``app.js`` and
``app.css`` from a real :class:`Gateway` and the cases assert on what the page
*does*. Everything here is the harness for that — the gateway, the session
handshake a browser really performs, and the engine behind it.

**The gateway is the one `test_gateway.py` binds**, over ``ai_assistant.testing``'s
``FakeAssistantEngine``, on a free loopback port, under
``hermetic_assistant_env`` (ADR-0216 §4). The one difference is the bundle: that
module serves three stub bytestrings because its subject is HTTP, and this one
serves :func:`packaged_bundle`, because its subject is the page those bytes are.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final

import gateway_ports
from gateway_mint import bootstrap_value
from gateway_timing import Clock, Timers

from ai_assistant.core.config import Settings
from ai_assistant.core.device_context import serving_device
from ai_assistant.core.errors import DeviceRefusal, DeviceRefusedError
from ai_assistant.core.types import (
    ChatStreamChunk,
    ConversationState,
    CurrentState,
    DeviceRole,
    RequestingDevice,
)
from ai_assistant.interfaces.gateway.server import Gateway, packaged_bundle
from ai_assistant.testing import FakeAssistantEngine

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from playwright.async_api import Browser, BrowserContext, Page, ViewportSize

    from ai_assistant.core.types import ChatStreamEnd

#: The window a case gets when it asks for none: Playwright's own default, stated
#: here rather than left implicit because the parameter that overrides it takes
#: ``None`` to mean *no fixed viewport at all* — which is a third state, and not one
#: any case in this layer wants.
_DEFAULT: ViewportSize = {"width": 1280, "height": 720}

#: The two widths ADR-0233 §15 obliges the browser lane to drive its floor at. The
#: desktop one is PR #1385's, and the phone is the iPhone 13 Pro's viewport — the same
#: 390x844 #1429's layout lane drove, so a rendering assertion here and a layout one
#: there are about the same screen.
DESKTOP: ViewportSize = {"width": 1100, "height": 900}
PHONE: ViewportSize = {"width": 390, "height": 844}

#: How far :meth:`Drive.expire_sessions` moves the clock: past ``Settings``' default
#: ``gateway_session_idle_timeout`` of an hour and well short of its
#: ``gateway_session_ttl`` of twelve, so the bound that ends the session is the *idle*
#: one — which is the bound ADR-0175 §7's fifth clause is about and the only one the
#: page has a sentence for. Stated as a margin rather than read back from the settings
#: so that a drive fails rather than quietly stops expiring anything if either default
#: moves, which is the direction a harness should fail in.
SESSION_IDLE_MARGIN: Final = timedelta(hours=2)


class DriveEngine(FakeAssistantEngine):
    """A ``FakeAssistantEngine`` whose change stream a case can push onto.

    ADR-0216 §4 admits "``FakeAssistantEngine`` or a subclass of it", and this is
    the whole of the subclass: every scripted answer is the fake's own, and what is
    added is the change stream followed as a device of the case's choosing, with
    :meth:`push` merged into it.
    """

    def __init__(self) -> None:
        """Start following as the hub's own machine, with no stream open."""
        super().__init__()
        #: The device the change stream is followed as (ADR-0298 §2), or ``None`` for
        #: the hub's own machine — which is what an engine followed in-process is
        #: otherwise asked as, and which is sent every change and no snapshot.
        self.follow_as: RequestingDevice | None = None
        #: The reason the change stream's first step refuses the device for, or
        #: ``None`` (ADR-0298 §5's "Reading many").
        self.refuse_following: DeviceRefusal | None = None
        self._pushes: set[asyncio.Queue[ChatStreamChunk | ChatStreamEnd | Exception]] = set()

    @property
    def open_streams(self) -> int:
        """How many change streams are open on this engine now."""
        return len(self._pushes)

    def push(self, chunk: ChatStreamChunk | ChatStreamEnd | Exception) -> None:
        """Put one chunk, or a failure, on every open change stream.

        What the engine does when a conversation's activity changes (ADR-0296 §4:9),
        put in the case's hands: an engine followed in-process pushes a state only
        when something it runs starts or ends, which a drive cannot hold still.
        """
        for queue in tuple(self._pushes):
            queue.put_nowait(chunk)

    def push_state(self, conversation_id: str, state: ConversationState) -> None:
        """Push one conversation's current state on every open change stream."""
        self.push(ChatStreamChunk(state=CurrentState(conversation_id=conversation_id, state=state)))

    def follow_chat(self, *, after: int) -> AsyncIterator[ChatStreamChunk | ChatStreamEnd]:
        """The fake's own change stream, as :attr:`follow_as`, with :meth:`push` merged in.

        Args:
            after: The cursor.

        Returns:
            The stream.
        """
        if self.follow_as is None:
            inner = super().follow_chat(after=after)
        else:
            with serving_device(self.follow_as):
                inner = super().follow_chat(after=after)
        return self._following(inner)

    async def _following(
        self, inner: AsyncIterator[ChatStreamChunk | ChatStreamEnd]
    ) -> AsyncIterator[ChatStreamChunk | ChatStreamEnd]:
        if self.refuse_following is not None:
            await inner.aclose()  # type: ignore[attr-defined]  # an async generator
            msg = "reading many needs a role"
            raise DeviceRefusedError(msg, reason=self.refuse_following)
        queue: asyncio.Queue[ChatStreamChunk | ChatStreamEnd | Exception] = asyncio.Queue()
        self._pushes.add(queue)

        async def pump() -> None:
            async for chunk in inner:
                queue.put_nowait(chunk)

        pumping = asyncio.ensure_future(pump())
        try:
            while True:
                item = await queue.get()
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            self._pushes.discard(queue)
            pumping.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await pumping
            await inner.aclose()  # type: ignore[attr-defined]  # an async generator


class _OwnNode:
    """The overlay agent of a gateway whose hub is on another machine, naming this one.

    All a loopback drive asks of it: which node this machine is (ADR-0296 §1:7), so
    the page is a device other than the hub's own machine.
    """

    def __init__(self, node: str) -> None:
        self.node = node

    async def identify(self, host: str, port: int) -> str:  # pragma: no cover — no remote door
        """Never asked: a drive binds no remote listener."""
        msg = f"no peer is identified in a drive ({host}:{port})"
        raise AssertionError(msg)

    async def own_identity(self) -> str:
        """This machine's node."""
        return self.node


@dataclass
class Drive:
    """One gateway, the engine behind it, and the page a browser is driving it from.

    Attributes:
        page: The browser page, already holding an admitted session.
        gateway: The gateway serving the shipped bundle.
        engine: The engine behind it.
        origin: The one origin this page may load anything from (ADR-0168 §10).
        clock: The gateway's clock, which a case moves rather than waits out.
        timers: Everything the gateway deferred, which a case fires.
    """

    page: Page
    gateway: Gateway
    engine: DriveEngine
    origin: str
    clock: Clock
    timers: Timers

    def expire_sessions(self) -> None:
        """Move past every session's idle bound and fire what that armed.

        The gateway is built with a clock and a timer table a test drives by hand
        (``gateway_timing``), for ADR-0168 §4's reason: expired sessions are
        "destroyed continuously rather than at a checkpoint or on the next request
        that happens to arrive", so the death is a *scheduled* act and a case that
        waited it out would wait an hour. Moving the clock and firing is the same
        act the harness cases make (``test_gateway_streams.py``), reached from a
        drive — and it is ADR-0216 §7's own requirement, a state the page reaches
        rather than a duration it is raced against.

        It is every session rather than one because the table announces each ending
        through the same callback and a drive holds one session anyway; naming which
        would be a discrimination neither this harness nor the gateway makes.
        """
        self.clock.advance(SESSION_IDLE_MARGIN)
        self.timers.fire_all()

    async def admit(self) -> None:
        """Exchange a freshly minted bootstrap value through the page's own form.

        The handshake a browser really performs, rather than a cookie planted from
        outside: the value is minted through ``gateway_mint``, which is what makes
        ADR-0182 §1's ordered act — mint, disclose, promote — the one this drive
        exercises, and it is typed into the page's field and submitted through the
        page's form. So every case starts from a state the page put itself in.
        """
        await self.page.fill("#bootstrap-value", bootstrap_value(self.gateway))
        await self.page.click("#bootstrap-form button[type=submit]")
        await self.page.wait_for_selector("#console:not([hidden])")


@contextlib.asynccontextmanager
async def driving(
    browser: Browser,
    tmp_path: Path,
    *,
    admitted: bool = True,
    viewport: ViewportSize | None = None,
    device: str | None = None,
) -> AsyncIterator[Drive]:
    """Bind a gateway, open a page on it, and exchange a session (ADR-0216 §4).

    The handshake is the one a browser really performs — a value minted through
    ``gateway_mint`` and typed into the page's own bootstrap field, submitted
    through the page's own form — rather than a cookie planted from outside, so
    the drive starts from a state the page put itself in.

    Args:
        browser: The one browser this run launched.
        tmp_path: The case's temporary directory, which is the whole of the data
            directory this drive is allowed (ADR-0216 §4).
        admitted: Whether to perform the handshake. ``False`` leaves the page on
            its bootstrap panel, which is where a case about *loading* the bundle
            wants it.
        viewport: The window this page is driven at, or ``None`` for the browser's
            own default. A case about what is on screen *before a control* is a
            case about a width — ADR-0233 §15 obliges the browser lane to drive
            the page "at a desktop width and at a phone-class viewport" — and the
            context is where a viewport is set, because this layer shares one
            browser (ADR-0216 §3).
        device: The node this machine is, for a page that is a device of its own
            rather than the hub's machine: the gateway is told its hub is elsewhere,
            names this browser ``device``, and the engine's change stream is followed
            as that device holding the commands role. ``None`` for the hub's machine.

    Yields:
        The page, the gateway and the engine behind it.
    """
    settings = Settings(
        gateway_port=gateway_ports.free_port(),
        data_dir=tmp_path,
        remote_hub_address=None if device is None else "100.64.0.1",
    )
    engine = DriveEngine()
    if device is not None:
        engine.follow_as = RequestingDevice(
            device_id=device, roles=frozenset({DeviceRole.COMMANDS})
        )
    clock, timers = Clock(), Timers()
    gateway = Gateway(
        settings=settings,
        engine=engine,
        now=clock,
        defer=timers,
        bundle=packaged_bundle(),
        agent=None if device is None else _OwnNode(device),
    )
    server: asyncio.Server = await gateway.start()
    origin = f"http://127.0.0.1:{settings.gateway_port}"
    # A context per case rather than a browser per case: it is milliseconds where a
    # launch is a quarter of a second, and it is what keeps one case's session,
    # storage and permissions out of the next one's.
    # Created *inside* the cleanup-protected region, and closed only if it exists.
    # `gateway.start()` above has already bound a listening socket, so a refusal from
    # `new_context()` would otherwise leave the gateway and its server running for the
    # rest of the run -- and that refusal is the realistic one, because the browser is
    # session-scoped and shared, so an earlier case may have crashed or closed it
    # (adversarial review, round 7, `major`).
    context: BrowserContext | None = None
    try:
        context = await browser.new_context(viewport=viewport if viewport is not None else _DEFAULT)
        page = await context.new_page()
        drive = Drive(
            page=page,
            gateway=gateway,
            engine=engine,
            origin=origin,
            clock=clock,
            timers=timers,
        )
        await page.goto(f"{origin}/")
        await page.wait_for_selector("#bootstrap-form")
        if admitted:
            await drive.admit()
        yield drive
    finally:
        # Nested rather than sequential, which is the same defect one line over: the
        # browser is still torn down first, but a raising `close()` must not take the
        # gateway's teardown with it. It still propagates -- a context that will not
        # close is a fact about the run worth failing on -- it just no longer costs
        # every later case a live port.
        try:
            if context is not None:
                await context.close()
        finally:
            gateway.close()
            server.close()
            # Close the connections the context did not own, or the wait below is the
            # gateway's read deadline. `wait_closed()` waits for every accepted
            # connection to end, and closing the context ends only the browser's: a
            # `route.fetch()` goes out through Playwright's own HTTP client, in the
            # driver process, whose keep-alive socket outlives the context. Its
            # handler then sits in its read until `gateway_read_timeout` (thirty
            # seconds) and the case spends them in this `finally` -- every case that
            # fetched, once each. After `close()`, so no connection can be accepted
            # after the sweep.
            server.close_clients()
            with contextlib.suppress(Exception):
                await server.wait_closed()
