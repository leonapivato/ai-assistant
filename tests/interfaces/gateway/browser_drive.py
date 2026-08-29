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
import socket
from base64 import b64encode
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from gateway_mint import bootstrap_value
from gateway_timing import Clock, Timers

from ai_assistant.core.config import Settings
from ai_assistant.core.types import SpokenAudio, SpokenAudioFormat
from ai_assistant.interfaces.gateway.server import Gateway, packaged_bundle
from ai_assistant.models.speech_container import encode_mono
from ai_assistant.testing import FakeAssistantEngine

if TYPE_CHECKING:
    import asyncio
    from collections.abc import AsyncIterator
    from datetime import timedelta
    from pathlib import Path

    from playwright.async_api import Browser, Page

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


def rendering_of(seconds: float) -> str:
    """One playable ``audio/webm;codecs=opus`` rendering, base64 as the wire wants it.

    **Real, decodable audio rather than the canonical fake's octets.**
    ``FakeAssistantEngine`` renders a hash — deterministic, opaque, and explicitly
    "nothing about them is audio" — which is exactly right for every consumer that
    must not decode a rendering, and useless to a browser that must. So this
    encodes a tone through the same seam the hub's own synthesizer's output goes
    through, and :class:`SpeakingEngine` hands it back in the fake's place.

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
    """

    page: Page
    gateway: Gateway
    engine: SpeakingEngine
    origin: str

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


def free_port() -> int:
    """A port nothing is listening on, so two runs do not collide."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextlib.asynccontextmanager
async def driving(
    browser: Browser,
    tmp_path: Path,
    *,
    renderings: tuple[str, ...] = (),
    admitted: bool = True,
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

    Yields:
        The page, the gateway and the engine behind it.
    """
    settings = Settings(gateway_port=free_port(), data_dir=tmp_path)
    engine = SpeakingEngine(renderings or (rendering_of(8.0),))
    gateway = Gateway(
        settings=settings,
        engine=engine,
        now=Clock(),
        defer=Timers(),
        bundle=packaged_bundle(),
    )
    server: asyncio.Server = await gateway.start()
    origin = f"http://127.0.0.1:{settings.gateway_port}"
    # A context per case rather than a browser per case: it is milliseconds where a
    # launch is a quarter of a second, and it is what keeps one case's session,
    # storage and permissions out of the next one's.
    context = await browser.new_context(permissions=["microphone"])
    try:
        await context.add_init_script(PROBE)
        page = await context.new_page()
        drive = Drive(page=page, gateway=gateway, engine=engine, origin=origin)
        await page.goto(f"{origin}/")
        await page.wait_for_selector("#bootstrap-form")
        if admitted:
            await drive.admit()
        yield drive
    finally:
        await context.close()
        gateway.close()
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()
