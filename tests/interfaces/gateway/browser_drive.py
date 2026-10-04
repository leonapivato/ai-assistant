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
handshake a browser really performs, the press a thumb really performs, and the
Web Audio probe that counts what the browser scheduled.

**The gateway is the one `test_gateway.py` binds**, over ``ai_assistant.testing``'s
``FakeAssistantEngine``, on a free loopback port, under
``hermetic_assistant_env`` (ADR-0216 §4). The one difference is the bundle: that
module serves three stub bytestrings because its subject is HTTP, and this one
serves :func:`packaged_bundle`, because its subject is the page those bytes are.

**Why the probe wraps Web Audio rather than replacing it.** ADR-0216 §1 rejected a
jsdom runner precisely because "a fake of it is a restatement of the author's
belief about the browser, checked against itself". Nothing here fakes a decoder or
a source: :data:`PROBE` counts real ``AudioBufferSourceNode.start``/``stop`` calls
and can make one real ``decodeAudioData`` resolve late, then delegates to the
browser's own. What is asserted is still what Chromium did.
"""

from __future__ import annotations

import contextlib
import functools
from base64 import b64encode
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final
from weakref import WeakKeyDictionary

import gateway_ports
import numpy as np
from gateway_mint import bootstrap_value
from gateway_timing import Clock, Timers
from playwright.async_api import Error as BrowserError

from ai_assistant.core.config import Settings
from ai_assistant.core.types import SpokenAudio, SpokenAudioFormat
from ai_assistant.interfaces.gateway.server import Gateway, packaged_bundle
from ai_assistant.models.speech_container import encode_mono
from ai_assistant.testing import FakeAssistantEngine

if TYPE_CHECKING:
    import asyncio
    from collections.abc import AsyncIterator
    from pathlib import Path

    from playwright.async_api import Browser, BrowserContext, Page, ViewportSize

    from ai_assistant.core.types import Identifier, SpokenDeliveryReport, SpokenTurn
    from ai_assistant.core.types import SpokenAudio as SpokenAudioType

#: The rate the renderings below are synthesised at. Any rate the encoder accepts
#: would do — what the cases read off a decoded buffer is its *duration*, and the
#: rate only has to be one ``libopus`` will take.
_SAMPLE_RATE = 48_000

#: The tone the pseudo-renderings carry. Nothing decodes it for its content: it is
#: here because a container of silence is a container a decoder may legitimately
#: shorten, and a case that reads a buffer's duration wants samples in it.
_TONE_HERTZ = 440.0

#: How long a press keeps **recording**, once there is a recorder recording.
#:
#: It is a duration of the recording and not a synchronisation device, which is a
#: distinction :meth:`Drive.press` has to earn rather than assert: it waits for
#: ``MediaRecorder.start`` to have been called before this elapses at all.
#: Adversarial review, round 1, ``major``, found the version that did not — a press
#: released 400 ms after ``pointerdown`` is released *before the recorder exists*
#: wherever ``getUserMedia`` takes longer than that, and ``startTalking`` then finds
#: its press already let go, hands the microphone back and sends nothing. Every wait
#: after that would time out, on a loaded CI runner and nowhere else, which is
#: exactly the flake ADR-0216 §7 forbids this layer.
#:
#: Long enough that the recorder's final block carries audio — a blob of no bytes is
#: a press the page answers with "nothing was recorded" and sends nowhere — and short
#: enough that it costs the layer nothing.
PRESS_MILLISECONDS = 400

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

#: The one probe the pages carry, installed before any of the bundle runs.
#:
#: It does three things and nothing else. It counts every
#: ``AudioBufferSourceNode.start`` with the offset it was given and the duration of
#: the buffer behind it, so a case can say *which* rendering sounded rather than
#: only that one did. It counts every ``stop``. And it can hold exactly one
#: ``decodeAudioData`` open — the next one — which is #1707's own instrument:
#: "a fake ``AudioContext`` whose decode promise resolves after
#: ``interruptPlayback()`` would reveal whether no source starts".
#:
#: ``settled`` counts decodes that have *finished*, which is what lets a case wait
#: for a released decode to have had its chance to start a source rather than
#: sleeping and hoping (ADR-0216 §7). ``recordings`` counts recorders the page has
#: actually started, which is what :meth:`Drive.press` waits on before it begins to
#: measure a recording's length — see :data:`PRESS_MILLISECONDS`.
PROBE = """
window.__drive = {
  starts: [],
  stops: 0,
  decodes: 0,
  settled: 0,
  recordings: 0,
  hold: null,
  release: null,
};

const recorderProto = MediaRecorder.prototype;
const realRecord = recorderProto.start;
recorderProto.start = function (...args) {
  const answer = realRecord.apply(this, args);
  window.__drive.recordings += 1;
  return answer;
};

const sourceProto = AudioBufferSourceNode.prototype;
const realStart = sourceProto.start;
const realStop = sourceProto.stop;
sourceProto.start = function (...args) {
  window.__drive.starts.push({
    offset: args[1] === undefined ? 0 : args[1],
    duration: this.buffer === null ? null : this.buffer.duration,
  });
  return realStart.apply(this, args);
};
sourceProto.stop = function (...args) {
  window.__drive.stops += 1;
  return realStop.apply(this, args);
};

const audioProto = Object.getPrototypeOf(AudioContext.prototype);
const realDecode = audioProto.decodeAudioData;
audioProto.decodeAudioData = async function (...args) {
  window.__drive.decodes += 1;
  const held = window.__drive.hold;
  if (held !== null) {
    window.__drive.hold = null;
    await held;
  }
  try {
    return await realDecode.apply(this, args);
  } finally {
    window.__drive.settled += 1;
  }
};

window.__holdNextDecode = () => {
  window.__drive.hold = new Promise((resolve) => {
    window.__drive.release = resolve;
  });
};
window.__releaseHeldDecode = () => {
  window.__drive.release();
};
"""


@functools.cache
def rendering_of(seconds: float) -> str:
    """One playable ``audio/webm;codecs=opus`` rendering, base64 as the wire wants it.

    **Real, decodable audio rather than the canonical fake's octets.**
    ``FakeAssistantEngine`` renders a hash — deterministic, opaque, and explicitly
    "nothing about them is audio" — which is exactly right for every consumer that
    must not decode a rendering, and useless to a browser that must. So this
    encodes a tone through the same seam the hub's own synthesizer's output goes
    through, and :class:`SpeakingEngine` hands it back in the fake's place.

    **Encoded once per duration and then handed out again.** Encoding is the
    costliest thing a drive does before it reaches the browser — tens of
    milliseconds, and about a tenth of a second on a loaded machine, for the
    eight-second default every drive that names no rendering is given — and the
    audio depends on nothing but ``seconds``. The container is not byte-identical
    from one encoding to the next (two eight-byte header fields differ), so caching
    does change one thing: two calls for one duration now return the same string.
    Nothing tells two renderings apart by anything but their duration —
    :class:`SpeakingEngine` repeats its last one, and the cases read the decoded
    buffer's length — so that is a difference no case can see. The value is an
    immutable ``str``, so no caller can change what the next one is handed.

    Args:
        seconds: How long the rendering plays for. Cases read this back off the
            decoded buffer to say which rendering sounded.

    Returns:
        The container's octets, base64-encoded as ``SpokenAudio.content`` requires.
    """
    frames = np.arange(int(_SAMPLE_RATE * seconds), dtype=np.float32) / _SAMPLE_RATE
    samples = (0.2 * np.sin(2 * np.pi * _TONE_HERTZ * frames)).astype(np.float32)
    octets = encode_mono(samples, sample_rate=_SAMPLE_RATE, media_type=SpokenAudioFormat.WEBM_OPUS)
    return b64encode(octets).decode("ascii")


class SpeakingEngine(FakeAssistantEngine):
    """A ``FakeAssistantEngine`` whose spoken answers a browser can actually play.

    ADR-0216 §4 admits "``FakeAssistantEngine`` or a subclass of it", and this is
    the whole of the subclass: every scripted turn is the fake's own, and only the
    rendering's octets are replaced — with the next entry of :attr:`renderings`,
    so two turns of one case can be told apart by the duration that reaches the
    browser's decoder.
    """

    def __init__(self, renderings: tuple[str, ...]) -> None:
        """Start with the renderings this engine will hand out, in order.

        Args:
            renderings: Base64 containers, one per spoken turn. The last is
                repeated once they run out, so a case that does not care how many
                turns it takes passes one.
        """
        super().__init__()
        self.renderings = renderings
        self.rendered = 0

    async def converse_spoken(
        self,
        utterance: SpokenAudioType,
        *,
        plays: tuple[SpokenAudioFormat, ...],
        timeout: timedelta,  # noqa: ASYNC109 — the Protocol's own signature
        conversation_id: Identifier | None = None,
        delivery: SpokenDeliveryReport | None = None,
    ) -> SpokenTurn:
        """Run the fake's own turn, then swap in a rendering the browser can decode.

        Args:
            utterance: The recording the page uploaded.
            plays: What the page said it can render.
            timeout: The budget for the whole call.
            conversation_id: The conversation to continue, or ``None``.
            delivery: What this device played of an earlier turn.

        Returns:
            The fake's turn, with a playable rendering where it had one.
        """
        turn = await super().converse_spoken(
            utterance,
            plays=plays,
            timeout=timeout,
            conversation_id=conversation_id,
            delivery=delivery,
        )
        if turn.spoken is None:
            return turn
        chosen = self.renderings[min(self.rendered, len(self.renderings) - 1)]
        self.rendered += 1
        return turn.model_copy(
            update={"spoken": SpokenAudio(content=chosen, media_type=SpokenAudioFormat.WEBM_OPUS)}
        )


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
    engine: SpeakingEngine
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

    async def probe(self) -> dict[str, Any]:
        """What the page's Web Audio probe has recorded so far."""
        recorded = await self.page.evaluate("window.__drive")
        assert isinstance(recorded, dict)
        return recorded

    async def starts(self) -> list[dict[str, Any]]:
        """Every ``AudioBufferSourceNode.start`` the page has made, in order."""
        recorded = await self.page.evaluate("window.__drive.starts")
        assert isinstance(recorded, list)
        return recorded

    async def press(self, *, milliseconds: int = PRESS_MILLISECONDS) -> None:
        """Record for ``milliseconds``, then let the button go, as a thumb does.

        **The wait is on the recorder, and the duration is only what is recorded.**
        Holding for a fixed time from ``pointerdown`` synchronises on nothing: the
        microphone is opened asynchronously, and a release that lands before the
        recorder exists ends the press with nothing recorded and nothing sent
        (``startTalking``'s own ``mine.released`` guard). So this waits for the page
        to have started a ``MediaRecorder`` — a condition the page exposes, in
        ADR-0216 §7's sense — and only then measures out the recording.

        Args:
            milliseconds: How long the recording runs for, once it is running.
        """
        started = (await self.probe())["recordings"]
        await self.hold()
        await self.page.wait_for_function(
            "expected => window.__drive.recordings === expected", arg=started + 1
        )
        await self.page.wait_for_timeout(milliseconds)
        await self.release()

    async def hold(self) -> None:
        """Press the talk button and keep holding it."""
        await self.page.locator("#talk-button").hover()
        await self.page.mouse.down()

    async def release(self) -> None:
        """Let the talk button go."""
        await self.page.mouse.up()

    async def answer(self) -> str:
        """Everything the answer panel is currently saying."""
        return await self.page.inner_text("#answer-body")

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


@dataclass
class _Held:
    """One reusable context, and every origin a page of it has been sent to.

    Attributes:
        context: The context, carrying the microphone grant and :data:`PROBE`.
        window: The viewport it was opened at, which is also its place on the shelf.
        served: Every origin a drive has loaded in it. An origin is never served twice
            by one context; see :meth:`_Shelf.check_out`.
    """

    context: BrowserContext
    window: tuple[int, int]
    served: set[str]


class _Shelf:
    """The contexts one browser lends to the layer's drives, one per viewport.

    **What is reused, and what is not.** Opening a context, installing the probe and
    closing it again is a fixed cost every case paid before it did anything, and the
    page it held was the only thing in it a case ever touched. So a context outlives
    its case and the next drive at the same viewport is lent it, while *the page is
    still opened fresh for every case and closed at its end*. Everything a case can
    reach through its page — listeners (``page.on``), routes (``page.route``), the
    mouse a press left down, a viewport set mid-case, ``sessionStorage``, history and
    the document itself — therefore dies with the case exactly as it did when the
    context did. So do any further pages the case opened from ``page.context``: every
    page of the context is closed at check-in, not only the drive's own.

    **What a context could carry from one case to the next, and why none of it
    reaches the next case.**

    - *Cookies* are scoped to a host and not to a port, so the session cookie one
      gateway set would be sent to the next gateway on ``127.0.0.1``. They are
      cleared on every check-out of a context that has served before.
    - *Everything scoped to an origin* — ``localStorage`` (where the page keeps half
      of its session header), IndexedDB, the Cache API, service workers, the HTTP
      cache — would be visible to a later case only if that case's gateway had the
      same origin, which is to say the same port. Ports do repeat: ``gateway_ports``
      hands them out of a block of 64, round-robin. So the rule is structural rather
      than a clearing routine that has to name every store: **a context never serves
      the same origin twice.** A check-out for an origin the context has already
      served closes that context and opens a fresh one, so every origin a case sees
      is one its context has never loaded — whatever the browser keeps per origin,
      including stores nobody here thought to name.
    - *The microphone grant and the probe* are the same for every case, which is why
      they are context options and not per-page ones.

    **What would break the argument, and is therefore not done anywhere in the
    layer:** state set on the *context* itself — ``context.route``, ``context.on``,
    ``context.add_init_script``, ``context.grant_permissions`` and the like. A case
    reaches its context only to open a second page. ``test_browser_isolation.py``
    pins each half of this, and the layer is run in reverse order as well as the
    usual one before a change to it is shipped.

    **A context is lent again only after a clean exit.** A case that raised — a
    failed assertion, a timeout, a cancellation — returns a context nothing vouches
    for, so it is closed rather than shelved and the next case gets a fresh one.

    **The browser is still the one ADR-0216 §3 allows.** Nothing here launches
    anything: a context is a profile inside the session's one browser, and the shelf
    holds at most one per viewport the layer drives at. They close with the browser
    at the end of the session.
    """

    def __init__(self) -> None:
        """Start with nothing shelved."""
        self._idle: dict[tuple[int, int], _Held] = {}

    async def check_out(self, browser: Browser, viewport: ViewportSize, origin: str) -> _Held:
        """Lend a context at ``viewport`` that has never loaded ``origin``.

        Args:
            browser: The browser a fresh context is opened in, where one is needed.
            viewport: The window the drive is at.
            origin: The origin the drive is about to load.

        Returns:
            A context with no page open in it and no cookie set, whose ``served``
            already records ``origin``.
        """
        window = (viewport["width"], viewport["height"])
        idle = self._idle.pop(window, None)
        if idle is not None and origin not in idle.served:
            try:
                await idle.context.clear_cookies()
            except BrowserError:
                # A context the browser no longer has -- nothing a case should
                # inherit, and nothing to close.
                idle = None
            else:
                idle.served.add(origin)
                return idle
        if idle is not None:
            await idle.context.close()
        context = await browser.new_context(permissions=["microphone"], viewport=viewport)
        try:
            await context.add_init_script(PROBE)
        except BaseException:
            await context.close()
            raise
        return _Held(context=context, window=window, served={origin})

    async def check_in(self, held: _Held, *, reusable: bool) -> None:
        """Close every page of a lent context, then shelve it or close it.

        Args:
            held: What :meth:`check_out` lent.
            reusable: Whether the drive ended cleanly. A context whose case raised
                is closed rather than lent again.
        """
        if not reusable or held.window in self._idle:
            # The second branch is a case holding two drives at one viewport at once:
            # the shelf keeps one context per viewport, so the other is closed.
            await held.context.close()
            return
        try:
            for page in list(held.context.pages):
                await page.close()
        except BaseException:
            await held.context.close()
            raise
        self._idle[held.window] = held


#: One shelf per browser. Keyed by the browser rather than held globally so that a
#: context is never lent to a drive in a browser it does not belong to: the harness's
#: own cases (``test_browser_harness.py``) pass browsers of their own, and the
#: session's real one must never be handed a context one of them opened.
_SHELVES: WeakKeyDictionary[Browser, _Shelf] = WeakKeyDictionary()


def _shelf_of(browser: Browser) -> _Shelf:
    """The shelf ``browser``'s contexts are lent from, made on first use."""
    shelf = _SHELVES.get(browser)
    if shelf is None:
        shelf = _SHELVES[browser] = _Shelf()
    return shelf


@contextlib.asynccontextmanager
async def driving(
    browser: Browser,
    tmp_path: Path,
    *,
    renderings: tuple[str, ...] = (),
    admitted: bool = True,
    viewport: ViewportSize | None = None,
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
        renderings: The spoken renderings the engine hands out, in order. Defaults
            to one eight-second tone, which outlasts anything a case does to it.
        admitted: Whether to perform the handshake. ``False`` leaves the page on
            its bootstrap panel, which is where a case about *loading* the bundle
            wants it.
        viewport: The window this page is driven at, or ``None`` for the browser's
            own default. A case about what is on screen *before a control* is a
            case about a width — ADR-0233 §15 obliges the browser lane to drive
            the page "at a desktop width and at a phone-class viewport" — and the
            context is where a viewport is set, because this layer shares one
            browser (ADR-0216 §3).

    Yields:
        The page, the gateway and the engine behind it.
    """
    settings = Settings(gateway_port=gateway_ports.free_port(), data_dir=tmp_path)
    engine = SpeakingEngine(renderings or (rendering_of(8.0),))
    clock, timers = Clock(), Timers()
    gateway = Gateway(
        settings=settings,
        engine=engine,
        now=clock,
        defer=timers,
        bundle=packaged_bundle(),
    )
    server: asyncio.Server = await gateway.start()
    origin = f"http://127.0.0.1:{settings.gateway_port}"
    window = viewport if viewport is not None else _DEFAULT
    # A page per case in a context the layer reuses, rather than a context per case:
    # see `_Shelf` for what is reused, what is not, and why the next case cannot tell.
    # Checked out *inside* the cleanup-protected region, and checked in only if it
    # exists. `gateway.start()` above has already bound a listening socket, so a
    # refusal from `new_context()` would otherwise leave the gateway and its server
    # running for the rest of the run -- and that refusal is the realistic one,
    # because the browser is session-scoped and shared, so an earlier case may have
    # crashed or closed it (adversarial review, round 7, `major`).
    shelf = _shelf_of(browser)
    held: _Held | None = None
    clean = False
    try:
        held = await shelf.check_out(browser, window, origin)
        page = await held.context.new_page()
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
        clean = True
    finally:
        # Nested rather than sequential, which is the same defect one line over: the
        # browser is still torn down first, but a raising `close()` must not take the
        # gateway's teardown with it. It still propagates -- a context that will not
        # close is a fact about the run worth failing on -- it just no longer costs
        # every later case a live port.
        try:
            if held is not None:
                await shelf.check_in(held, reusable=clean)
        finally:
            gateway.close()
            server.close()
            # Close the connections the context did not own, or the wait below is the
            # gateway's read deadline. `wait_closed()` waits for every accepted
            # connection to end, and closing the pages ends only the browser's: a
            # `route.fetch()` goes out through Playwright's own HTTP client, in the
            # driver process, whose keep-alive socket outlives the page. Its
            # handler then sits in its read until `gateway_read_timeout` (thirty
            # seconds) and the case spends them in this `finally` -- every case that
            # fetched, once each. After `close()`, so no connection can be accepted
            # after the sweep.
            server.close_clients()
            with contextlib.suppress(Exception):
                await server.wait_closed()
