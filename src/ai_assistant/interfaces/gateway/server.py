"""The browser gateway: a spoke that serves one device's browsers (ADR-0168).

**What this is.** "The browser gateway is a spoke under ADR-0094 §1 — an
attachment reaching the hub across a process boundary over ADR-0084's wire — and
it is a spoke of the **client** profile, carrying a person" (ADR-0168 §1). It
obtains the hub only through the promoted ``AssistantEngine``, by the same client
the CLI uses and the same selection between transports; it builds no engine and
never falls back from one transport to another.

**What it may not do.** "The gateway holds no assistant logic: it composes no
behaviour the promoted engine surface does not offer, authors no permission
ruling, mints no confirmation, and opens no store" (ADR-0168 §1). The one thing it
adds that is not translation is its own door policy, "which is the same class of
thing as the CLI's exit code — a property of the adapter, not of the assistant".

**The routing rule is a biconditional, and it is checkable here.** "A browser
request reaches the promoted engine surface **if and only if** the gateway has
admitted it under §4 *and* it asks the assistant for something." :meth:`Gateway.
_respond` is where that holds: a static asset, the bootstrap exchange, an
unadmitted request and a refused one each return before :meth:`Gateway._ask`, the
only method on this class that touches the engine.

**The listener is loopback and nothing else** (ADR-0168 §2). The address is
:data:`_LOOPBACK`, a constant of this module rather than a setting, so there is no
configuration that could have it bind a wildcard, an interface or an overlay
address — which is the stronger form of §2's "a configuration that would have it
bind anything else is refused at load rather than bound".

**A browser reaches a closed enumeration of five operations** (ADR-0175 §6):
``converse``, ``converse_streaming``, ``recent_conversations``, ``conversation``
and ``forget_conversation``. ``next_notification`` is the **sixth** operation this
gateway calls and is deliberately not one of the five, because no browser request
resolves to it — :class:`.delivery.DeliveryFanOut` originates the poll, no browser
request names it, and no browser argument reaches it. Everything else the promoted
surface carries is unreached from a browser, and adding one costs a ratified
decision: ``resume`` and ``pending_confirmations``, the grant surface, the belief
and question surfaces, and the notification *review* surface are milestone 15's.

**Two of those shapes answer on a stream** (ADR-0175 §1): the body of the response
to the request the browser made, written in pieces, with no socket, no upgrade and
nothing an ``EventSource`` reaches. The reason is mechanical rather than
architectural — ADR-0168 §6 requires the header half of a session on every admitted
request and requires it to travel "only as a request header the front end sets",
and a `WebSocket` handshake and an `EventSource` request are the two requests a page
cannot set a header on at all. :mod:`.streams` carries what a stream value is and
:mod:`.delivery` carries the one poll and its fan-out.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from functools import partial
from importlib import resources
from typing import TYPE_CHECKING, Any, Final

import structlog

from ai_assistant.core.errors import AssistantError
from ai_assistant.core.streams import closing_stream
from ai_assistant.core.types import (
    DEFAULT_PAGE_SIZE,
    ConversationDigest,
    ConversationSummary,
    Disposition,
    StepOutcome,
    TurnOutcome,
)
from ai_assistant.interfaces.gateway import streams
from ai_assistant.interfaces.gateway.delivery import DeliveryFanOut, DeliveryStream, write_stream
from ai_assistant.interfaces.gateway.http import (
    IncompleteRequestError,
    MalformedRequestError,
    Request,
    RequestTooLargeError,
    Response,
    StreamHead,
    read_request,
    render,
    render_chunk,
    render_stream_end,
    render_stream_head,
)
from ai_assistant.interfaces.gateway.records import (
    AdmissionRecorder,
    RefusalCondition,
    RequestClass,
)
from ai_assistant.interfaces.gateway.sessions import (
    Admission,
    Cancellable,
    Defer,
    SessionHandle,
    SessionTable,
    mint_value,
    verifier,
)
from ai_assistant.wire.errors import TransportError

if TYPE_CHECKING:  # pragma: no cover — imported for typing alone
    from collections.abc import Awaitable, Callable, Mapping

    from ai_assistant.core.config import Settings
    from ai_assistant.core.protocols import AssistantEngine

_log = structlog.get_logger(__name__)

#: The only address this gateway binds (ADR-0168 §2). Not a setting, deliberately.
_LOOPBACK: Final = "127.0.0.1"

#: The paths the browser-facing surface uses. ADR-0168 §12 leaves the surface to
#: this lane — "the request shapes, the paths, the document, and whether a push
#: carrier such as a WebSocket is among them… no ADR is owed for it and the
#: implementing lane decides it" — and ADR-0175 §2 restates that division for the
#: two shapes it adds: "the exact framing of a value on a stream, the media type a
#: stream is served with, and the paths the surface uses are the implementing
#: lane's".
#:
#: **Every argument travels in a JSON request body, and none in a URL.** No path
#: here carries a parameter and no handler reads a query string, which is why
#: :class:`.http.Request` still discards one: a door built on "a request this module
#: cannot parse is refused rather than guessed at" gains a path-template parser and
#: a query parser for nothing, since every one of these is a same-origin ``fetch``
#: the front end writes. ADR-0168 §6 separately forbids a session value ever
#: appearing in a URL, and a surface with no URL arguments at all cannot acquire one
#: by accident.
_SESSION_PATH: Final = "/session"
_ASK_PATH: Final = "/ask"

#: ADR-0175 §3's streamed turn. A **second** entry beside :data:`_ASK_PATH` rather
#: than a replacement, and keeping the non-streaming one is a decision rather than
#: inertia: ADR-0173 §5 makes a provider that cannot stream "a ``ModelError`` from
#: the call — before any delta", degrading to ``reply`` ``None`` with
#: ``reply_degraded`` ``True``, so a browser offered only the streaming entry would
#: answer nothing at all on a build where the CLI on the same machine answered
#: normally. The gateway never chooses between them and never falls back from one to
#: the other — ADR-0168 §9 forbids it retrying silently and ADR-0173 §7 refuses the
#: same fallback one layer in. A second attempt is the front end asking again.
_ASK_STREAM_PATH: Final = "/ask/stream"

#: ADR-0175 §4's delivery stream. ``GET`` because it carries no argument: the poll
#: is the gateway's own and takes none from a browser.
_DELIVERIES_PATH: Final = "/deliveries"

#: ADR-0175 §6's three conversation operations. "Resume" in milestone 14's own line
#: is resuming a *conversation* — reading it and continuing it — which is these two
#: plus a turn call carrying a ``conversation_id``. ``AssistantEngine.resume`` is a
#: different method that resumes a parked **turn**, and ADR-0175 §10 defers it with
#: ``pending_confirmations`` and the CONFIRM prompt to milestone 15.
_CONVERSATIONS_PATH: Final = "/conversations"
_CONVERSATION_PATH: Final = "/conversation"
_FORGET_CONVERSATION_PATH: Final = "/conversation/forget"

#: Which method admits which path. A mapping rather than a chain of comparisons,
#: because ADR-0168 §6 classifies "from its method and path alone" and the set of
#: shapes the surface has is now large enough that reading it off one table is what
#: keeps ADR-0175 §6's enumeration checkable.
_ASSISTANT_PATHS: Final[Mapping[tuple[str, str], str]] = {
    ("POST", _ASK_PATH): "converse",
    ("POST", _ASK_STREAM_PATH): "converse_streaming",
    ("GET", _DELIVERIES_PATH): "delivery-stream",
    ("POST", _CONVERSATIONS_PATH): "recent_conversations",
    ("POST", _CONVERSATION_PATH): "conversation",
    ("POST", _FORGET_CONVERSATION_PATH): "forget_conversation",
}

#: The two shapes that answer on a stream (ADR-0175 §1). They are held apart from
#: the rest because only they outlive the request that established them, so only
#: they need the handle of the session that admitted them (§7).
_STREAMED_SHAPES: Final = frozenset({("POST", _ASK_STREAM_PATH), ("GET", _DELIVERIES_PATH)})

#: The cookie the gateway sets, and the header the front end sends. Two values
#: rather than one because "a cookie is not scoped to a port" (ADR-0168 §6).
_COOKIE_NAME: Final = "assistant_session"
_SESSION_HEADER: Final = "x-assistant-session"

#: The policy every response carries (ADR-0168 §6): scripts, styles, fonts,
#: images, media and connections from the gateway's own origin alone, and no
#: inline script. `default-src 'none'` is what makes the enumeration exhaustive
#: rather than a list someone has to keep abreast of.
_POLICY: Final = (
    "default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; "
    "img-src 'self'; media-src 'self'; connect-src 'self'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)

#: The budget one turn is given, mirroring the CLI's own ``--timeout`` default. It
#: is a constant rather than an eleventh `Settings` field on purpose: ADR-0168 §8
#: names the ten figures this milestone owes and ADR-0172 adds none, and a turn
#: budget is the *caller's* budget (ADR-0029 §4) rather than one of the gateway's
#: resource bounds. Whoever measures that a browser needs its own buys the field.
_TURN_BUDGET: Final = timedelta(seconds=60)

#: What a refusal answers with. Each condition keeps its own status, because
#: ADR-0168 §6 requires the cookie-half fault "reported to the owner as its own
#: condition, and never flattened into an expiry, a ceiling refusal or an ordinary
#: absent session" — and a status shared with another condition is that flattening
#: performed by the response rather than by the record.
_REFUSAL_STATUS: Final[Mapping[RefusalCondition, tuple[int, str]]] = {
    RefusalCondition.HOST_NOT_BOUND: (421, "Misdirected Request"),
    RefusalCondition.ORIGIN_NOT_OWN: (403, "Forbidden"),
    RefusalCondition.NO_LIVE_SESSION: (401, "Unauthorized"),
    RefusalCondition.COOKIE_HALF_MISMATCH: (409, "Conflict"),
    RefusalCondition.SESSION_CEILING: (429, "Too Many Requests"),
    RefusalCondition.BOOTSTRAP_EXCHANGE_FAILED: (400, "Bad Request"),
}

#: The bundle's paths and media types (ADR-0168 §10). The gateway "serves only
#: assets that shipped in the installed distribution", so the map is fixed here
#: and the files are package data — nothing is fetched, listed or resolved from a
#: path a request supplies.
_BUNDLE: Final[Mapping[str, tuple[str, str]]] = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


def packaged_bundle() -> Mapping[str, tuple[bytes, str]]:
    """Read the front end out of the installed distribution (ADR-0168 §10).

    Read once, at start, rather than per request: the bundle ships with the
    package and cannot change under a running process, and a gateway that read a
    file per request would have a filesystem in its request path for no gain.

    Returns:
        Each served path's bytes and media type.
    """
    root = resources.files(__package__) / "assets"
    return {
        path: ((root / name).read_bytes(), media_type)
        for path, (name, media_type) in _BUNDLE.items()
    }


@dataclass(eq=False)
class _Connection:
    """One browser connection, and the only fact §8's ceilings turn on.

    Compared by identity — ``eq=False`` — because the population §8 bounds is a
    set of *connections* and two of them in the same state are not one connection.

    "A browser connection is **admitted** from the moment it carries a request the
    gateway admitted under §4, and **unadmitted** before that… no rule of this ADR
    returns an admitted connection to the unadmitted population" (ADR-0168 §8).
    """

    admitted: bool = False


@dataclass
class _Bootstrap:
    """The one value a gateway process mints, and whether it is still good.

    Attributes:
        verifier: A digest of the disclosed value, compared in constant time. The
            value itself is not retained here for the reason a session half is
            not (ADR-0168 §4).
        spent: Whether it has been exchanged for a session. "The exchange consumes
            it, and after it the gateway mints no further session until its
            process is restarted" (ADR-0168 §5).
    """

    verifier: bytes
    spent: bool = False


@dataclass(eq=False)
class _OpenStream:
    """One stream a session admitted, and how the gateway ends it (ADR-0175 §7).

    "A stream ends no later than the session that admitted it, and the gateway ends
    every stream a session held at the moment that session ends." A held-open stream
    sends no further request, so the gateway would otherwise learn of the session's
    death only from a request that never comes.

    Ending it is closing the connection the response body is being written on, which
    *is* the stream (§1). A delivery stream is abandoned first, so its writer stops
    waiting on a browser rather than on a socket that is about to go.

    Compared by identity, because two streams in the same state are not one stream.
    """

    writer: asyncio.StreamWriter
    delivery: DeliveryStream | None = None
    driver: asyncio.Task[Any] | None = None

    def end(self) -> None:
        """End this stream now, tolerating a connection that is already gone.

        **Closing the writer is not enough on its own, and the case that shows it is
        an answer stream waiting on its first value.** ``converse_streaming`` may be
        composing when the session expires; a closed socket does not interrupt an
        ``async for``, so the iteration — and with it the hub connection ADR-0175 §7
        counts against ``gateway_max_hub_connections`` — would outlive the session by
        however long the turn took. Cancelling the task that drives the stream is what
        makes §7's "the gateway ends every stream a session held at the moment that
        session ends" true of the resources as well as of the bytes: the cancellation
        unwinds through ``closing_stream``, which closes the engine's iterator, and
        through the body's own ``finally``, which gives the slot back.

        The driver is the connection's handler task, so cancelling it ends the
        connection too — which is right, because the stream *is* the response body on
        it. A task never cancels itself: a request that finds its own session expired
        is being served on a connection that has no stream open, so the guard is
        belt-and-braces rather than load-bearing, and it is cheaper than reasoning
        about it again later.
        """
        if self.delivery is not None:
            self.delivery.abandon()
        if self.driver is not None and self.driver is not asyncio.current_task():
            self.driver.cancel()
        with contextlib.suppress(ConnectionError, OSError):
            self.writer.close()


@dataclass(frozen=True)
class _Streamed:
    """A response whose body the connection handler writes itself (ADR-0175 §1).

    The second thing :meth:`Gateway._respond` can decide. Everything decidable
    before the engine is reached — an unadmitted request, a malformed body, a
    ceiling — is still an ordinary :class:`.http.Response` carrying its own status;
    a stream's head is written only once the gateway has committed to answering on
    one, and every fault after that travels as the stream's terminal value.

    Attributes:
        head: The head to write before the first piece.
        body: Writes the pieces. It owns everything it registered and releases it on
            every exit, early ones included.
        abandon: Releases what *deciding* to stream took, for the one path on which
            ``body`` never runs — a peer that went away before the head could be
            written. The two are mutually exclusive: the head either reaches the
            browser and ``body`` owns the release, or it does not and this does.
            Without it a browser that hangs up at exactly the wrong moment leaks the
            hub slot ADR-0175 §7 counts, and on a delivery stream leaves a poll
            running for a stream nobody is reading — which is the "while and only
            while" of §4 quietly broken by an error path.
    """

    head: StreamHead
    body: Callable[[asyncio.StreamWriter], Awaitable[None]]
    abandon: Callable[[], None]


class Gateway:
    """Serves one device's browsers, and reaches the hub as any spoke does."""

    def __init__(  # noqa: PLR0913 — one keyword per injected seam: config, hub, clock, timer, bundle, entropy
        self,
        *,
        settings: Settings,
        engine: AssistantEngine,
        now: Callable[[], datetime],
        defer: Defer,
        bundle: Mapping[str, tuple[bytes, str]],
        mint_value: Callable[[], str] = mint_value,
    ) -> None:
        """Build a gateway that has minted nothing and bound nothing.

        Args:
            settings: The loaded configuration, read for ADR-0168 §8's ten figures
                and for nothing else.
            engine: The hub, as the promoted ``AssistantEngine`` (ADR-0168 §1).
            now: The clock, injected.
            defer: How a session's death and a record interval's close are
                scheduled, injected for the same reason.
            bundle: The front end's assets, already read.
            mint_value: The entropy source for the bootstrap value and both
                session halves.
        """
        self._settings = settings
        self._engine = engine
        self._now = now
        self._defer = defer
        self._bundle = bundle
        self._mint_value = mint_value
        self._sessions = SessionTable(
            max_sessions=settings.gateway_max_sessions,
            ttl=settings.gateway_session_ttl,
            idle_timeout=settings.gateway_session_idle_timeout,
            now=now,
            defer=defer,
            mint_value=mint_value,
            on_ended=self._session_ended,
        )
        self._records = AdmissionRecorder(
            interval=settings.gateway_record_interval, now=now, defer=defer
        )
        self._connections: set[_Connection] = set()
        self._hub_in_flight = 0
        self._open_streams: dict[SessionHandle, set[_OpenStream]] = {}
        self._deliveries = DeliveryFanOut(
            engine=engine,
            budget=settings.gateway_notification_budget,
            acquire=self._take_hub_slot,
            release=self._give_hub_slot,
        )
        self._bootstrap: _Bootstrap | None = None
        self._authority = f"{_LOOPBACK}:{settings.gateway_port}"
        self._origin = f"http://{self._authority}"
        #: The four shapes answered whole, by path. A table rather than a chain of
        #: comparisons, so ADR-0175 §6's enumeration is one thing to read against the
        #: ADR — and so a path :data:`_ASSISTANT_PATHS` admits but nothing here
        #: serves is a ``KeyError`` in this process rather than a silent fallthrough
        #: onto whichever handler happened to be last.
        self._unary: Mapping[str, Callable[[Request], Awaitable[Response]]] = {
            _ASK_PATH: self._ask,
            _CONVERSATIONS_PATH: self._recent_conversations,
            _CONVERSATION_PATH: self._conversation,
            _FORGET_CONVERSATION_PATH: self._forget_conversation,
        }

    @property
    def origin(self) -> str:
        """The one origin this gateway serves, and the one it admits."""
        return self._origin

    def mint_bootstrap(self) -> str:
        """Mint the one bootstrap value of this process's life (ADR-0168 §5).

        Returns:
            The value to disclose, exactly once, on standard output. The caller
            discloses it; a gateway that cannot "does not start, and reports why",
            which is why the disclosure happens before anything is bound.

        Raises:
            RuntimeError: If a value has already been minted. One per process life
                is the rule the single-use argument rests on, and a second mint
                would quietly widen it.
        """
        if self._bootstrap is not None:
            msg = "a gateway process mints one bootstrap value (ADR-0168 §5)"
            raise RuntimeError(msg)
        value = self._mint_value()
        self._bootstrap = _Bootstrap(verifier=verifier(value))
        return value

    async def start(self) -> asyncio.Server:
        """Bind the loopback listener (ADR-0168 §2, §9).

        The listener is bound **whether or not the hub is reachable**, and nothing
        here probes it: "a gateway that refused to start without a hub would
        present the two failures identically", so serving regardless is what turns
        a stopped hub into a message a browser can read (ADR-0168 §9).

        Separate from :meth:`serve` so that the bind and the serving loop can be
        driven apart — which is what a test needs to send a request and read the
        answer rather than wait for a signal.

        Returns:
            The bound server, whose lifetime the caller owns.
        """
        server = await asyncio.start_server(
            self._handle, host=_LOOPBACK, port=self._settings.gateway_port
        )
        _log.info("gateway.listening", origin=self._origin, served_paths=sorted(self._bundle))
        return server

    async def serve(self) -> None:
        """Bind and serve until cancelled, ending every session on the way out."""
        server = await self.start()
        try:
            async with server:
                await server.serve_forever()
        finally:
            self.close()

    def close(self) -> None:
        """End every session and flush the interval in progress (ADR-0168 §4, §6).

        "Every session ends when the gateway process ends", and the interval's
        counters are emitted rather than dropped so a gateway stopping does not
        swallow the refusals it had counted.

        Clearing the table announces every handle, so each session's streams end
        with it (ADR-0175 §7); the fan-out is then shut down for the streams no
        session held — there are none, but a shutdown that depended on that would be
        one more invariant to keep true.
        """
        self._sessions.clear()
        self._deliveries.shutdown()
        self._records.flush()

    def _session_ended(self, handle: SessionHandle) -> None:
        """End every stream one session held, the moment it ends (ADR-0175 §7)."""
        for stream in self._open_streams.pop(handle, set()):
            stream.end()

    def _register(self, handle: SessionHandle, stream: _OpenStream) -> None:
        """Hold a stream against the session that admitted it (ADR-0175 §7)."""
        self._open_streams.setdefault(handle, set()).add(stream)

    def _unregister(self, handle: SessionHandle, stream: _OpenStream) -> None:
        """Drop a stream that has ended, and the session's entry with the last one."""
        held = self._open_streams.get(handle)
        if held is None:
            return
        held.discard(stream)
        if not held:
            del self._open_streams[handle]

    def _take_hub_slot(self) -> bool:
        """Take one of ``gateway_max_hub_connections``, or report the ceiling.

        The delivery poll counts against it exactly as a turn does (ADR-0175 §7,
        ADR-0131 §5): no lane gives delivery its own budget at this door. A gateway
        serving a delivery stream therefore holds one of the eight permanently, so
        the ceiling is one smaller for turns than it reads — no figure moves, and a
        gateway configured with a ceiling of one can serve a delivery stream or a
        turn and not both.
        """
        if self._hub_in_flight >= self._settings.gateway_max_hub_connections:
            return False
        self._hub_in_flight += 1
        return True

    def _give_hub_slot(self) -> None:
        """Give one back."""
        self._hub_in_flight -= 1

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Serve one connection under ADR-0168 §8's two ceilings and one deadline."""
        connection = _Connection()
        if not self._admit_connection(connection):
            await _close(writer)
            return
        try:
            await self._serve_connection(reader, writer, connection)
        finally:
            self._connections.discard(connection)
            await _close(writer)

    def _admit_connection(self, connection: _Connection) -> bool:
        """Take a connection, or refuse it at either ceiling (ADR-0168 §8).

        Refusing is closing without reading: "while that many exist it refuses to
        accept a further connection rather than queueing it". A refusal here
        records nothing — §8's conditions are outside §6's recorded set.

        Args:
            connection: The connection being accepted.

        Returns:
            Whether it was taken.
        """
        pending = sum(1 for held in self._connections if not held.admitted)
        if len(self._connections) >= self._settings.gateway_max_browser_connections:
            return False
        if pending >= self._settings.gateway_max_pending_connections:
            return False
        self._connections.add(connection)
        return True

    async def _serve_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        connection: _Connection,
    ) -> None:
        """Read, answer, and decide whether the connection survives the answer.

        **The deadline bounds idleness, and the clock starts when the gateway has
        finished answering.** ADR-0168 §8 states it as
        ``gateway_read_timeout`` "after the last complete request it carried"; read
        as wall-clock from the request's arrival it would close a connection while
        the gateway was still working on that very request, which is the request
        the deadline exists to make room for. The hub's own clause is a *read*
        deadline — "how long a connection may stall — mid-frame, or waiting for the
        next frame's prefix" (ADR-0084 §3) — and this is that rule at this door.

        **That reading is what ADR-0175 §7 makes a ruling, and this loop is already
        it.** §7 supersedes §8's read-deadline sentence "only as it reaches a
        connection carrying a response the gateway has not finished writing", keying
        the deadline on the completion of the last *response* in place of the last
        complete request — and the deadline here is armed around the read alone,
        which begins once the previous response has been written and drained. So no
        deadline runs while a stream is open, and none can cut one: a reader holding
        only §8 would have ended every stream ADR-0175 §1 defines thirty seconds
        after its request arrived, which is not a stricter gateway but one on which
        the surface cannot exist. Nothing here changes for it; PR #1331 disclosed the
        reading and §7 ratified it.
        """
        timeout = self._settings.gateway_read_timeout.total_seconds()
        while True:
            answer = await self._next(reader, connection, timeout)
            if answer is None:
                return
            # **The header is written from the decision, not beside it.** §8 closes
            # an unadmitted connection "once that request's response is complete"
            # whatever the response was, so a `Connection: keep-alive` on one would
            # be the rule announced and then disobeyed — and the peer would hold a
            # socket the gateway had already given up on.
            closing = answer.head.close if isinstance(answer, _Streamed) else answer.close
            closing = closing or not connection.admitted
            if isinstance(answer, _Streamed):
                if not await self._write_stream(writer, answer, closing=closing):
                    return
            else:
                writer.write(render(replace(answer, close=closing), policy=_POLICY))
                await writer.drain()
            if closing:
                return

    async def _write_stream(
        self, writer: asyncio.StreamWriter, answer: _Streamed, *, closing: bool
    ) -> bool:
        """Write one streamed response whole (ADR-0175 §1).

        The head, then whatever the body writes, then the zero-length chunk that
        ends a chunked body. A body that stops without that marker and without a
        terminal value is what ADR-0175 §2 makes a **transport failure** the front
        end reports as one, so a connection that dies mid-stream is legible at the
        browser rather than looking like a stream that finished with nothing to say.

        Args:
            writer: The connection's writer.
            answer: What to stream.
            closing: Whether the connection is closed once this completes.

        **The head is written in its own attempt**, because a peer that went away
        before it landed is the one path on which ``body`` never runs — and ``body``
        is what releases the hub slot and unregisters the delivery stream that
        *deciding* to answer already took. Losing that release is not a slow leak: a
        browser hanging up at that instant would hold one of
        ``gateway_max_hub_connections`` for the process's whole life (ADR-0175 §7),
        and on a delivery stream would leave a poll running for a reader that never
        existed, which is §4's "while and only while at least one delivery stream is
        open" broken by an error path rather than by a rule.

        Args:
            writer: The connection's writer.
            answer: What to stream.
            closing: Whether the connection is closed once this completes.

        Returns:
            Whether the connection survived. ``False`` where the peer went away,
            which is an ordinary end for a stream and not a fault to report.
        """
        try:
            writer.write(render_stream_head(replace(answer.head, close=closing), policy=_POLICY))
            await writer.drain()
        except ConnectionError, OSError:
            answer.abandon()
            return False
        try:
            await answer.body(writer)
            writer.write(render_stream_end())
            await writer.drain()
        except ConnectionError, OSError:
            return False
        return True

    async def _next(
        self,
        reader: asyncio.StreamReader,
        connection: _Connection,
        timeout: float,  # noqa: ASYNC109 — ADR-0168 §8's own deadline, relayed to the read it bounds
    ) -> Response | _Streamed | None:
        """The answer to the next request, or ``None`` where there is nothing to answer."""
        try:
            request = await asyncio.wait_for(
                read_request(reader, max_bytes=self._settings.gateway_max_request_bytes),
                timeout=timeout,
            )
        except TimeoutError, IncompleteRequestError:
            return None
        except RequestTooLargeError:
            return _fault(
                413,
                "Content Too Large",
                "request-too-large",
                limit="gateway_max_request_bytes",
            )
        except MalformedRequestError:
            return _fault(400, "Bad Request", "malformed-request")
        return await self._respond(request, connection)

    async def _respond(self, request: Request, connection: _Connection) -> Response | _Streamed:
        """Decide one request (ADR-0168 §3, §7, §1's biconditional).

        The order is §7's: "Both checks run before the session is read, and a
        request failing either is refused without the session being consulted at
        all." Classification is not a check — it decides which of §6's four classes
        a record would name — so it happens first and refuses nothing.
        """
        request_class = self._classify(request)
        condition = self._check_door(request)
        if condition is not None:
            return self._refuse(request_class, condition)
        if request_class is RequestClass.ASSET:
            body, media_type = self._bundle[request.path]
            return Response(200, "OK", body=body, content_type=media_type, close=False)
        if request_class is RequestClass.BOOTSTRAP:
            return self._exchange(request)
        return await self._session_bound(request, connection, request_class)

    def _classify(self, request: Request) -> RequestClass:
        """Which of ADR-0168 §6's four kinds this request is, decided from it alone.

        **Still four, and ADR-0175 adds no fifth** (§12): "A streamed turn and a
        delivery stream both 'ask the assistant for something' and are
        ``assistant-request``", so the six shapes of :data:`_ASSISTANT_PATHS` share
        one class and §6's enumeration is untouched. A fifth value for a delivery
        stream would supersede an enumeration that says every request is "of exactly
        one class, out of four" while buying no rule the four cannot carry.
        """
        if request.method == "GET" and request.path in self._bundle:
            return RequestClass.ASSET
        if request.method == "POST" and request.path == _SESSION_PATH:
            return RequestClass.BOOTSTRAP
        if (request.method, request.path) in _ASSISTANT_PATHS:
            return RequestClass.ASSISTANT
        return RequestClass.OTHER

    def _check_door(self, request: Request) -> RefusalCondition | None:
        """Run ADR-0168 §7's two checks, both decidable from the request alone.

        The `Host` check is what closes DNS rebinding — "a page the owner visits
        from a name the attacker controls can have that name re-resolve to
        `127.0.0.1`" — one step earlier than the session would, "on a fact
        decidable from the request alone rather than on the session logic being
        right". A repeated `Host` or `Origin` reads as absent
        (:meth:`Request.header`) and is refused, because a door that picked the
        first of two would let the peer choose which one it is judged on.

        Args:
            request: The request as parsed.

        Returns:
            The condition it fails, or ``None`` where it passes both.
        """
        if request.header("host") != self._authority:
            return RefusalCondition.HOST_NOT_BOUND
        origin = request.header("origin")
        if origin is not None and origin != self._origin:
            return RefusalCondition.ORIGIN_NOT_OWN
        return None

    def _exchange(self, request: Request) -> Response:
        """The one exchange that mints a session (ADR-0168 §5).

        "A failed exchange discloses only that it failed — never whether the value
        was well-formed, whether one is still outstanding, or whether a session
        already exists", so every way of failing returns the same refusal on the
        same condition.

        The value is consumed by the mint it produced rather than by the attempt:
        an exchange refused at ADR-0168 §4's ceiling yielded no session, and §5
        makes the value "exchangeable for exactly one **session**".
        """
        presented = _string(_payload(request), "bootstrap_value")
        held = self._bootstrap
        if (
            presented is None
            or held is None
            or held.spent
            or not hmac.compare_digest(verifier(presented), held.verifier)
        ):
            return self._refuse(RequestClass.BOOTSTRAP, RefusalCondition.BOOTSTRAP_EXCHANGE_FAILED)
        values = self._sessions.mint()
        if values is None:
            return self._refuse(RequestClass.BOOTSTRAP, RefusalCondition.SESSION_CEILING)
        held.spent = True
        self._records.session_minted()
        return Response(
            200,
            "OK",
            body=_json({"header_half": values.header_half}),
            content_type="application/json",
            # `HttpOnly` so no script reads it, `SameSite=Strict` so no other site
            # causes it to be sent, `Path=/` and no `Domain` so a second cookie of
            # this name is detectable as the anomaly it is, and no persistent
            # expiry — none of which the guarantee rests on, because "a session's
            # lifetime is decided by the gateway alone" (ADR-0168 §6).
            set_cookie=f"{_COOKIE_NAME}={values.cookie_half}; HttpOnly; SameSite=Strict; Path=/",
            close=True,
        )

    async def _session_bound(
        self, request: Request, connection: _Connection, request_class: RequestClass
    ) -> Response | _Streamed:
        """Everything ADR-0168 §3 serves only to an admitted browser."""
        header_half = request.header(_SESSION_HEADER)
        outcome = self._sessions.admit(
            header_half=header_half, cookie_halves=request.cookies(_COOKIE_NAME)
        )
        if outcome is Admission.NO_LIVE_SESSION:
            return self._refuse(request_class, RefusalCondition.NO_LIVE_SESSION)
        if outcome is Admission.COOKIE_HALF_MISMATCH:
            return self._refuse(request_class, RefusalCondition.COOKIE_HALF_MISMATCH)
        connection.admitted = True
        if request_class is RequestClass.ASSISTANT:
            return await self._assistant(request, header_half)
        # Admitted, and asking the assistant for nothing: answered, and the engine
        # is not reached (ADR-0168 §1's biconditional). Not a refusal on any of
        # §3 to §7's conditions, so nothing is recorded and the connection survives.
        return _fault(404, "Not Found", "no-such-path", close=False)

    async def _assistant(self, request: Request, header_half: str | None) -> Response | _Streamed:
        """Resolve one admitted assistant request onto ADR-0175 §6's five operations.

        **The enumeration is here and it is closed.** Every other operation the
        promoted surface carries is unreached from a browser, and no lane adds one
        without its own ratified decision — which is what keeps ADR-0174's permission
        to run a gateway on the hub's own machine from quietly handing a browser
        milestone 15's connection operations, now that a loopback-dialling gateway no
        longer meets the hub's remote refusal (ADR-0174 §11).

        Args:
            request: The admitted request.
            header_half: The value it was admitted on. The two streamed shapes need
                the session's own handle, because ADR-0175 §7 ends every stream a
                session held at the moment that session ends.

        Returns:
            The response, or the stream to write.
        """
        shape = (request.method, request.path)
        if shape not in _STREAMED_SHAPES:
            return await self._unary[request.path](request)
        handle = None if header_half is None else self._sessions.handle(header_half)
        if handle is None:  # pragma: no cover — admitted means a session verified it
            return self._refuse(RequestClass.ASSISTANT, RefusalCondition.NO_LIVE_SESSION)
        if shape == ("POST", _ASK_STREAM_PATH):
            return self._ask_streaming(request, handle)
        return self._delivery_stream(handle)

    async def _ask(self, request: Request) -> Response:
        """Relay one turn to the hub and render what came back (ADR-0168 §1, §9).

        Every failure mode is kept apart, because §9 requires a transport failure
        "distinguishable from a request the hub received and declined" and forbids
        ever presenting one "as an answer". The gateway does not retry, does not
        queue, and answers from nothing of its own.
        """
        payload = _payload(request)
        utterance = _string(payload, "utterance")
        conversation = _string(payload, "conversation_id")
        if utterance is None:
            return _fault(400, "Bad Request", "malformed-request")
        if not self._take_hub_slot():
            return _ceiling()
        try:
            outcome = await self._engine.converse(
                utterance, timeout=_TURN_BUDGET, conversation_id=conversation
            )
        except (TransportError, AssistantError, ValueError) as exc:
            return _relay_fault(exc)
        finally:
            self._give_hub_slot()
        return _rendered({"outcome": _outcome_view(outcome)})

    def _ask_streaming(self, request: Request, handle: SessionHandle) -> Response | _Streamed:
        """Relay one turn as a stream, one value per instalment (ADR-0175 §3).

        "A browser's streamed turn is one request, answered by a stream carrying the
        values ADR-0173 §1's frames carry, in the order they arrived: one value per
        ``ReplyChunk``, then one terminal value carrying the ``TurnOutcome``, or one
        terminal value carrying the fault the exchange ended in."

        The hub slot is taken **before** the head is written and given back when the
        body finishes, so a stream held open for a minute is a connection accounted
        for the whole time (§7). What cannot be decided before the head is written
        travels as the stream's terminal value instead of as a status.

        Args:
            request: The admitted request.
            handle: The session that admitted it (§7).

        Returns:
            The stream, or a refusal decidable before the engine is reached.
        """
        payload = _payload(request)
        utterance = _string(payload, "utterance")
        conversation = _string(payload, "conversation_id")
        if utterance is None:
            return _fault(400, "Bad Request", "malformed-request")
        if not self._take_hub_slot():
            return _ceiling()
        return _Streamed(
            head=StreamHead(content_type=streams.MEDIA_TYPE),
            body=partial(
                self._answer_body, handle=handle, utterance=utterance, conversation=conversation
            ),
            abandon=self._give_hub_slot,
        )

    async def _answer_body(
        self,
        writer: asyncio.StreamWriter,
        *,
        handle: SessionHandle,
        utterance: str,
        conversation: str | None,
    ) -> None:
        """Write one streamed turn, releasing everything it took on every exit.

        The driver is this connection's own task, recorded so that ending the session
        that admitted the stream can cancel an iteration that is still waiting on its
        first value (ADR-0175 §7, :meth:`_OpenStream.end`).
        """
        held = _OpenStream(writer=writer, driver=asyncio.current_task())
        self._register(handle, held)
        try:
            await self._pump_answer(writer, utterance=utterance, conversation=conversation)
        finally:
            self._unregister(handle, held)
            self._give_hub_slot()

    async def _pump_answer(
        self, writer: asyncio.StreamWriter, *, utterance: str, conversation: str | None
    ) -> None:
        """Drive ``converse_streaming`` onto the stream (ADR-0175 §3).

        **Every engine stream this gateway opens is closed, on every exit and early
        ones included**, through :func:`ai_assistant.core.streams.closing_stream` —
        the seam that exists because "Python does not close an abandoned async
        iterator at the point of abandonment". This surface is the first consumer
        that will routinely abandon one: a browser that navigated away and a write
        that failed are each an early exit here, where the CLI drives every stream to
        exhaustion. A lane consuming this with a bare ``async for`` and a ``break``
        leaks a turn's resources on the most common path this surface has.

        **A stream that ends without a terminal value is a transport failure and is
        left as one** (§2). The contract yields exactly one ``TurnOutcome`` unless it
        raises, so there is no third ending to invent a value for: a body that stops
        early is what the front end reports as a transport failure, which is
        ADR-0168 §9's distinction reaching the browser.
        """
        try:
            answering = self._engine.converse_streaming(
                utterance, timeout=_TURN_BUDGET, conversation_id=conversation
            )
            async with closing_stream(answering) as pieces:
                async for produced in pieces:
                    if isinstance(produced, TurnOutcome):
                        await _write_value(writer, streams.outcome(_outcome_view(produced)))
                        return
                    await _write_value(writer, streams.chunk(produced))
        except (TransportError, AssistantError, ValueError) as exc:
            await _write_value(writer, _stream_fault(exc))

    def _delivery_stream(self, handle: SessionHandle) -> Response | _Streamed:
        """Open one delivery stream, and the poll with the first (ADR-0175 §4).

        Returns:
            The stream, or the ceiling refusal where the poll's own hub connection
            would take ``gateway_max_hub_connections`` past its bound (§7).
        """
        opened = self._deliveries.open()
        if opened is None:
            return _ceiling()
        return _Streamed(
            head=StreamHead(content_type=streams.MEDIA_TYPE),
            body=partial(self._delivery_body, handle=handle, stream=opened),
            abandon=partial(self._deliveries.close, opened),
        )

    async def _delivery_body(
        self, writer: asyncio.StreamWriter, *, handle: SessionHandle, stream: DeliveryStream
    ) -> None:
        """Write one delivery stream, closing the poll with the last one (§4, §5)."""
        held = _OpenStream(writer=writer, delivery=stream, driver=asyncio.current_task())
        self._register(handle, held)
        try:
            await write_stream(writer, stream, frame=_frame)
        finally:
            self._unregister(handle, held)
            self._deliveries.close(stream)

    async def _recent_conversations(self, request: Request) -> Response:
        """List conversations, most recently active first (ADR-0074 §2, ADR-0175 §6)."""
        payload = _payload(request)
        limit = _integer(payload, "limit", DEFAULT_PAGE_SIZE)
        offset = _integer(payload, "offset", 0)
        if limit is None or offset is None:
            return _fault(400, "Bad Request", "malformed-request")
        if not self._take_hub_slot():
            return _ceiling()
        try:
            held = await self._engine.recent_conversations(limit=limit, offset=offset)
        except (TransportError, AssistantError, ValueError) as exc:
            return _relay_fault(exc)
        finally:
            self._give_hub_slot()
        return _rendered({"conversations": [_summary_view(one) for one in held]})

    async def _conversation(self, request: Request) -> Response:
        """Show what destroying one conversation would destroy (ADR-0074 §8).

        ADR-0073 §5's show-then-confirm at the unit the user thinks in, and the
        reason ADR-0175 §6 admits a destructive operation without adding a ceremony
        clause: "a front-end confirmation before a forget is not a control and is not
        required here", because the origin-resident script the residual is about
        defeats one. What the front end does about it is a rendering decision, and
        the CLI's own order — read the conversation, then forget it — is the pattern
        this pair makes available.
        """
        named = _string(_payload(request), "conversation_id")
        if named is None:
            return _fault(400, "Bad Request", "malformed-request")
        if not self._take_hub_slot():
            return _ceiling()
        try:
            digest = await self._engine.conversation(named)
        except (TransportError, AssistantError, ValueError) as exc:
            return _relay_fault(exc)
        finally:
            self._give_hub_slot()
        if digest is None:
            return _fault(404, "Not Found", "no-such-conversation", close=False)
        return _rendered({"conversation": _digest_view(digest)})

    async def _forget_conversation(self, request: Request) -> Response:
        """Destroy one conversation and the episodes its turns index (ADR-0175 §6).

        **This widens what a script on the gateway's own origin can spend, by less
        than what is already there**, and ADR-0175 §6 states the accounting rather
        than hiding it: ADR-0168 §6's residual — "script running on the gateway's own
        origin defeats both halves… it can simply issue requests the browser will
        authenticate" — has covered ``converse`` since milestone 13, and a turn can
        approve a tool, execute it and durably commit a non-idempotent effect. So
        this adds a destructive operation to a surface that already carried a more
        destructive one, and adds no new class of residual.
        """
        named = _string(_payload(request), "conversation_id")
        if named is None:
            return _fault(400, "Bad Request", "malformed-request")
        if not self._take_hub_slot():
            return _ceiling()
        try:
            destroyed = await self._engine.forget_conversation(named)
        except (TransportError, AssistantError, ValueError) as exc:
            return _relay_fault(exc)
        finally:
            self._give_hub_slot()
        return _rendered({"destroyed": destroyed})

    def _refuse(self, request_class: RequestClass, condition: RefusalCondition) -> Response:
        """Record one refusal and answer it (ADR-0168 §3, §6, §8).

        The body carries the condition and nothing else: no assistant content, no
        fact about the hub's state, and no fact about whether the hub is
        reachable, which is what ADR-0168 §3 requires of every refusal. The
        connection is closed, because §8 requires it of a refusal on any of §3's,
        §4's, §5's, §6's, §7's and §8's conditions alike.
        """
        self._records.refused(request_class, condition)
        status, reason = _REFUSAL_STATUS[condition]
        return _fault(status, reason, condition.value)


def _payload(request: Request) -> Mapping[str, Any]:
    """The request's JSON object, or an empty mapping where there is not one.

    A body that is not an object is not distinguished from an absent one on
    purpose: every caller of this reads named members and refuses where one is
    missing, so a second failure mode would be a second way to say the same thing.
    """
    try:
        parsed = json.loads(request.body.decode("utf-8"))
    except UnicodeDecodeError, json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _string(payload: Mapping[str, Any], name: str) -> str | None:
    """One string member of a payload, or ``None`` where it is absent or not one."""
    value = payload.get(name)
    return value if isinstance(value, str) else None


def _integer(payload: Mapping[str, Any], name: str, fallback: int) -> int | None:
    """One integer member of a payload, its default where absent, ``None`` where wrong.

    ``bool`` is excluded rather than coerced, for the reason ``Settings`` excludes it
    from every count it holds: it is an ``int`` by inheritance, so ``{"limit": true}``
    would otherwise be a page of one that nothing downstream could tell from a
    request for a page of one.

    Args:
        payload: The request's JSON object.
        name: The member to read.
        fallback: What an absent member means.

    Returns:
        The value, the fallback, or ``None`` where the member is present and is not
        an integer.
    """
    if name not in payload:
        return fallback
    value = payload[name]
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _json(payload: Mapping[str, Any]) -> bytes:
    """Encode a response body."""
    return json.dumps(payload).encode("utf-8")


def _frame(value: Mapping[str, Any]) -> bytes:
    """One stream value, framed as a chunk of a chunked body (ADR-0175 §1, §2)."""
    return render_chunk(streams.encode(value))


async def _write_value(writer: asyncio.StreamWriter, value: Mapping[str, Any]) -> None:
    """Write one value on a stream and wait for it to leave.

    The drain is awaited rather than fired and forgotten, because it is what applies
    the browser's own backpressure to the turn: a page that cannot keep up should
    slow the writer down rather than have the gateway buffer an answer on its behalf.
    An answer stream "has one reader and nothing to protect from it", so ADR-0175
    §4's abandonment clause does not reach one and there is nothing here to race the
    drain against.
    """
    writer.write(_frame(value))
    await writer.drain()


def _rendered(payload: Mapping[str, Any]) -> Response:
    """A successful answer the engine returned, rendered as JSON (ADR-0168 §1)."""
    return _json_response(200, "OK", payload)


def _json_response(status: int, reason: str, payload: Mapping[str, Any]) -> Response:
    """One JSON body on a connection that survives it."""
    return Response(
        status, reason, body=_json(payload), content_type="application/json", close=False
    )


def _ceiling() -> Response:
    """``gateway_max_hub_connections`` reached, named as ADR-0168 §8 requires.

    "A browser request needing one beyond it is refused, naming the limit — never
    queued, and never served by opening a further connection." A gateway serving a
    delivery stream holds one of these permanently (ADR-0175 §7), so this is one
    request nearer than the figure reads.
    """
    return _fault(
        503,
        "Service Unavailable",
        "hub-connection-ceiling",
        limit="gateway_max_hub_connections",
        close=False,
    )


def _relay_fault(exc: Exception) -> Response:
    """One failed relay, kept apart from the other two (ADR-0168 §9).

    §9 requires a transport failure "distinguishable from a request the hub received
    and declined" and forbids ever presenting one "as an answer". The gateway does
    not retry, does not queue, and answers from nothing of its own.
    """
    if isinstance(exc, TransportError):
        return _fault(502, "Bad Gateway", "hub-unreachable", detail=str(exc), close=False)
    if isinstance(exc, AssistantError):
        return _fault(
            422, "Unprocessable Content", "assistant-declined", detail=str(exc), close=False
        )
    return _fault(400, "Bad Request", "rejected", detail=str(exc), close=False)


def _stream_fault(exc: Exception) -> dict[str, Any]:
    """The same three conditions, as a stream's terminal value (ADR-0175 §2, §3).

    The names match :func:`_relay_fault`'s exactly, so the page describes a fault
    that arrived on a stream with the words it already has for one that arrived as a
    response — which is what keeps ADR-0168 §9's distinction alive on this carrier
    rather than leaving it at the status code a stream cannot revise.
    """
    if isinstance(exc, TransportError):
        return streams.fault("hub-unreachable", detail=str(exc))
    if isinstance(exc, AssistantError):
        return streams.fault("assistant-declined", detail=str(exc))
    return streams.fault("rejected", detail=str(exc))


def _fault(  # noqa: PLR0913 — one parameter per member a fault body may carry, and the enumeration is the point
    status: int,
    reason: str,
    fault: str,
    *,
    detail: str | None = None,
    limit: str | None = None,
    close: bool = True,
) -> Response:
    """A machine-readable refusal or failure the front end renders as its own condition."""
    body: dict[str, Any] = {"fault": fault}
    if detail is not None:
        body["detail"] = detail
    if limit is not None:
        body["limit"] = limit
    return Response(status, reason, body=_json(body), content_type="application/json", close=close)


def _outcome_view(outcome: TurnOutcome) -> dict[str, Any]:
    """Translate one turn into what the page renders, member by member.

    An enumeration rather than a dump of the model, for ADR-0168 §6's reason one
    level out: the page renders what this returns, so what may appear in it is
    decided here rather than by whatever a future ``TurnOutcome`` happens to
    carry.

    **The answer is carried in addition to the step account, never in place of
    it** (ADR-0170 §6). ``reply`` and ``reply_degraded`` sit beside the notices,
    the plan and the step, and none of those is dropped on the ground that a reply
    is now present: the deterministic account is what this system guarantees about
    what it did, the composed answer is not, and where the two disagree the
    account is correct by construction. ``reply_degraded`` is carried rather than
    inferred from a ``None`` ``reply``, because §4 gives ``reply`` three ``None``
    shapes and only one of them is a composition that failed — the flag is what
    lets the page tell "no answer was owed" from "an answer was owed and could not
    be composed".

    The answer crosses to the page verbatim and is neutralised *there*, by being
    inserted as text and never as markup (ADR-0168 §6). That is this adapter's
    half of ADR-0170 §8's rule that every adapter neutralises engine-supplied
    text for its own output — what :func:`interfaces.cli._safe` is on the CLI's
    side, applied to the same value the plan's rationale already crosses under.

    It carries what the CLI's ``_render_turn`` renders, because the two adapters
    render the same turn — but that is a resemblance, not a mechanism, and this
    docstring used to claim the two mirrored each other *exactly*. They cannot:
    the enumeration above is what the page may see, so a member added to
    ``TurnOutcome`` reaches a browser only when it is added here as well.
    ``reply`` reached the CLI when ADR-0170 landed and did not reach this view
    until issue #1337 — a turn's answer was composed, returned, and dropped one
    layer short of the person who asked for it.
    """
    turn = outcome.turn
    plan = None if turn is None else turn.plan
    steps = () if plan is None else plan.steps
    return {
        "conversation_id": outcome.conversation_id,
        "capture_degraded": outcome.capture_degraded,
        "memory_degraded": turn is not None and turn.memory_degraded,
        "reply": outcome.reply,
        "reply_degraded": outcome.reply_degraded,
        "rationale": None if plan is None else plan.rationale,
        "steps": [{"intent": one.intent, "capability": one.capability} for one in steps],
        "step": _step_view(outcome.step),
    }


def _step_view(step: StepOutcome | None) -> dict[str, Any] | None:
    """Translate the step this pass drove, keeping the gate's verdict apart from the outcome.

    **The disposition is the gate's verdict; the named step's ``status`` and
    ``failure`` are the outcome** — the rule ``AssistantEngine.converse`` states
    and issue #531 is the cost of ignoring. A ``status`` of ``None`` therefore
    means "not known here", never "fine": it is the parked step, the step the gate
    did not execute, and the execution record that could not be addressed.
    """
    if step is None:
        return None
    view: dict[str, Any] = {
        "disposition": step.disposition.value,
        "tool_id": step.tool_id,
        "awaiting_confirmation": step.confirmation is not None,
        "status": None,
        "failure": None,
    }
    if step.confirmation is not None or step.disposition is not Disposition.EXECUTED:
        return view
    named = [one for one in step.state.steps if one.step_id == step.step_id]
    if not named:
        return view
    execution = named[0]
    view["status"] = execution.status.value
    if execution.failure is not None:
        view["failure"] = {
            "message": execution.failure.message,
            "kind": None if execution.failure.kind is None else execution.failure.kind.value,
        }
    return view


def _summary_view(summary: ConversationSummary) -> dict[str, Any]:
    """One conversation, as a person choosing which to continue reads it (ADR-0074 §2).

    An enumeration for ``_outcome_view``'s reason: what may appear on the page is
    decided here rather than by whatever a future ``ConversationSummary`` carries.

    **Both instants cross, and they are different facts.** ``last_active_at`` is when
    someone was last here and is the listing's sort key; ``last_turn_at`` is when a
    turn was last *recorded*, and is what tells an empty conversation from one whose
    first turn landed instantly. A page showing only one of them would be unable to
    render that distinction, and ADR-0074 §2 is explicit that ordering by "has a turn
    landed" sinks a conversation the user opened a minute ago below one they
    abandoned last week.
    """
    return {
        "id": summary.id,
        "started_at": summary.started_at.isoformat(),
        "last_active_at": summary.last_active_at.isoformat(),
        "last_turn_at": None if summary.last_turn_at is None else summary.last_turn_at.isoformat(),
    }


def _digest_view(digest: ConversationDigest) -> dict[str, Any]:
    """What a person is shown before consenting to destroy one (ADR-0074 §8).

    "The count and the span" rather than a transcript — printing every turn would be
    something nobody can read, and printing nothing would be consent to destroy
    something unseen. ``recorded_turns`` counts recorded turns and not surviving
    episodes, which is the ceremony's own fact rather than a report on content.
    """
    return {
        "id": digest.id,
        "started_at": digest.started_at.isoformat(),
        "last_turn_at": None if digest.last_turn_at is None else digest.last_turn_at.isoformat(),
        "recorded_turns": digest.recorded_turns,
    }


async def _close(writer: asyncio.StreamWriter) -> None:
    """Close one connection, tolerating a peer that closed first."""
    writer.close()
    with contextlib.suppress(ConnectionError, OSError):
        await writer.wait_closed()


def default_defer() -> Defer:
    """Schedule on the running event loop.

    The gateway's own scheduling seam, injected rather than reached for so a test
    drives a twelve-hour session in an instant. This is the production half.

    Returns:
        A callable scheduling one callback after a delay.
    """

    def defer(delay: float, callback: Callable[[], None]) -> Cancellable:
        return asyncio.get_running_loop().call_later(delay, callback)

    return defer


def utcnow() -> datetime:
    """The wall-clock reading a gateway process stamps its records with.

    The same module-level clock convention every subsystem uses, named so that
    :func:`run_gateway` composes it and a test substitutes it.
    """
    return datetime.now(UTC)


async def run_gateway(
    *,
    settings: Settings,
    engine: AssistantEngine,
    disclose: Callable[[str, str], None],
    now: Callable[[], datetime] = utcnow,
) -> None:
    """Mint, disclose, then serve — in that order, which ADR-0168 §5 fixes.

    "A gateway that cannot disclose its bootstrap value does not start, and
    reports why", so the disclosure happens **before** the listener is bound: a
    gateway that bound first and then failed to print would be answering a port
    with a value nobody can present.

    Args:
        settings: The loaded configuration.
        engine: The hub, as the promoted ``AssistantEngine``. Built by whoever
            composes this process — the gateway builds no engine (ADR-0168 §1).
        disclose: How the bootstrap value and the origin reach the owner. Raising
            from it is what stops the gateway starting.
        now: The clock.

    Raises:
        AssistantError: If the bootstrap value cannot be disclosed.
    """
    gateway = Gateway(
        settings=settings,
        engine=engine,
        now=now,
        defer=default_defer(),
        bundle=packaged_bundle(),
    )
    disclose(gateway.mint_bootstrap(), gateway.origin)
    await gateway.serve()
