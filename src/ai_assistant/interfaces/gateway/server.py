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

**The loopback listener is loopback and nothing else** (ADR-0168 §2). The address
is :data:`_LOOPBACK`, a constant of this module rather than a setting, so there is
no configuration that could have it bind a wildcard, an interface or an overlay
address — which is the stronger form of §2's "a configuration that would have it
bind anything else is refused at load rather than bound".

**A second listener may serve browsers on the owner's other devices, and it is off
unless it is configured on** (ADR-0174). It is the fourth egress boundary §1 of
that ADR authorises: the gateway's remote browser transport, bound to an overlay
address the owner configured and reachable only over an overlay satisfying
ADR-0124 §2. :data:`_LOOPBACK` stays a constant through all of it, because §2 of
ADR-0174 supersedes ADR-0168 §2 only "as it reaches a **separately configured**
remote browser listener" — the loopback listener is bound whether or not this one
is, on the same address, under every clause of ADR-0168 §2 that survives. A
gateway with no ``gateway_remote_address`` behaves byte for byte as it did.

**What the second listener adds is a fact the first one never had.** Before serving
anything on it — a static asset and the bootstrap exchange included — the gateway
asks the overlay agent on its **own** machine who holds the connecting address, and
takes that identity from nothing the peer asserts (ADR-0174 §3). Admission is then
two facts rather than one (§4): the device is one the owner listed in
``gateway_remote_browser_devices``, *and* the request carries a live web session.
The assets alone are served on overlay membership, because they are the bundle this
repository ships to anyone who installs it.

**A browser reaches a closed enumeration of thirty operations** (ADR-0177 §1,
superseding ADR-0175 §6's first clause and its figure of five). Eighteen of them
are served here today: milestone 14's ``converse``, ``converse_streaming``,
``recent_conversations``, ``conversation`` and ``forget_conversation``, together
with the grant surface — ``grantable_sources``, ``grant``, ``revoke``,
``recent_grants``, ``standing_grants`` — the belief surface — ``beliefs``,
``belief``, ``forget`` — the deferred-question surface — ``questions``,
``interrupted_questions``, ``answer``, ``forget_question`` — and ``observe``.
``next_notification`` remains the gateway's **own** poll and is none of the thirty,
because no browser request resolves to it — :class:`.delivery.DeliveryFanOut`
originates it, no browser request names it, and no browser argument reaches it
(ADR-0175 §6's second clause, bound unchanged by ADR-0177 §1).

**The residual is smaller and the enumeration is no weaker for it.** ``resume`` and
``pending_confirmations``, the notification *review* five and the five connection
operations are admitted by ADR-0177 §1 and are not served here yet; ``learn`` is
admitted by nothing and stays unreached until its own ratified decision (§11). The
form is what ADR-0168 §6 chose it for — "naming what may appear is the only form
that stays right when a later lane adds a request shape nobody has thought of yet".

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
import errno
import hmac
import json
import socket
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import partial
from importlib import resources
from typing import TYPE_CHECKING, Any, Final

import structlog

from ai_assistant.core.errors import AssistantError, ConfigurationError
from ai_assistant.core.streams import closing_stream
from ai_assistant.core.types import (
    DEFAULT_PAGE_SIZE,
    AnswerOutcome,
    Belief,
    BeliefBand,
    BeliefSummary,
    ConversationDigest,
    ConversationSummary,
    Disposition,
    Evidence,
    GrantableSource,
    GrantScope,
    MemoryKind,
    ObservationReport,
    ObservedProposal,
    Question,
    SourceGrant,
    StepOutcome,
    SuccessorLink,
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
from ai_assistant.wire.errors import OverlayIdentityUnavailableError, TransportError
from ai_assistant.wire.overlay import (
    CLIENT_AGENT_SOCKET,
    MAX_OVERLAY_IDENTITY_BYTES,
    local_agent,
)

if TYPE_CHECKING:  # pragma: no cover — imported for typing alone
    from collections.abc import Awaitable, Callable, Mapping

    from ai_assistant.core.config import Settings
    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.wire.overlay import OverlayAgent

_log = structlog.get_logger(__name__)

#: The address the **loopback** listener binds (ADR-0168 §2). Not a setting, and
#: still not one after ADR-0174: §2 of that ADR supersedes ADR-0168 §2's bind clause
#: only as it reaches "a separately configured remote browser listener", and keeps
#: the loopback listener bound "whether or not this one is, under every clause of
#: ADR-0168 §2 that this ADR does not supersede". So no configuration moves *this*
#: address, and the remote address is a second field rather than a widening of the
#: first — which is what makes ADR-0168 §2's reader right about the door they built.
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

#: ADR-0177 §6's grant surface. **Five paths for five operations, and the two
#: readings are two paths rather than one answered twice**: ADR-0139 §3's fourth
#: clause forbids a view presenting a source's configuration state as part of a
#: grant or a grant as a statement about whether a source is being read, and
#: ADR-0139 §1 is that neither answer is derivable from the other. A single
#: ``/grants`` shape that merged :data:`_SOURCES_PATH`'s answer into
#: :data:`_STANDING_PATH`'s would perform that merge in the gateway, where the
#: front end could no longer keep the two apart.
_SOURCES_PATH: Final = "/sources"
_GRANT_PATH: Final = "/grant"
_REVOKE_PATH: Final = "/revoke"
_RECENT_GRANTS_PATH: Final = "/grants/recent"
_STANDING_PATH: Final = "/grants/standing"

#: ADR-0177 §5's belief surface, in the shape the conversation surface already
#: uses: a listing, a single read, and a destruction that the single read is the
#: ceremony for. §5's second clause is why the pair is two paths and not one — the
#: render the ceremony rests on "is taken from a ``belief`` read issued immediately
#: before the confirmation is offered, and never from an entry of a ``beliefs``
#: listing the page rendered earlier".
_BELIEFS_PATH: Final = "/beliefs"
_BELIEF_PATH: Final = "/belief"
_FORGET_BELIEF_PATH: Final = "/belief/forget"

#: ADR-0078 §8's four façade methods, reached as ADR-0177 §1 admits them. The two
#: listings are separate paths because they answer different questions — one is
#: what is waiting for an answer, the other is what was begun and never recorded
#: (ADR-0078 §9) — and no single read of one question exists (#495), which is what
#: §5's ``forget_question`` ceremony is met with instead.
_QUESTIONS_PATH: Final = "/questions"
_INTERRUPTED_PATH: Final = "/questions/interrupted"
_ANSWER_PATH: Final = "/question/answer"
_FORGET_QUESTION_PATH: Final = "/question/forget"

#: ADR-0077 §8's passive half, explicit as that section makes it: "nothing triggers
#: it but a caller", and here the caller is the owner pressing a button.
_OBSERVE_PATH: Final = "/observe"

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
    ("POST", _SOURCES_PATH): "grantable_sources",
    ("POST", _GRANT_PATH): "grant",
    ("POST", _REVOKE_PATH): "revoke",
    ("POST", _RECENT_GRANTS_PATH): "recent_grants",
    ("POST", _STANDING_PATH): "standing_grants",
    ("POST", _BELIEFS_PATH): "beliefs",
    ("POST", _BELIEF_PATH): "belief",
    ("POST", _FORGET_BELIEF_PATH): "forget",
    ("POST", _QUESTIONS_PATH): "questions",
    ("POST", _INTERRUPTED_PATH): "interrupted_questions",
    ("POST", _ANSWER_PATH): "answer",
    ("POST", _FORGET_QUESTION_PATH): "forget_question",
    ("POST", _OBSERVE_PATH): "observe",
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
    # ADR-0174 §4. `403` rather than `401`, and the distinction is the one the two
    # status codes exist for: the caller is authenticated — the gateway's own agent
    # attested which device this is — and that device is not one the owner listed.
    # A `401` would invite a browser to present something, and there is nothing it
    # could present that would change the answer.
    RefusalCondition.DEVICE_NOT_LISTED: (403, "Forbidden"),
}

#: How many parts a peer address must have before its host and port can be read.
#: An IPv6 ``peername`` is a four-tuple, so this is a floor rather than a length.
_ADDRESS_PARTS: Final = 2

#: The bundle's paths and media types (ADR-0168 §10). The gateway "serves only
#: assets that shipped in the installed distribution", so the map is fixed here
#: and the files are package data — nothing is fetched, listed or resolved from a
#: path a request supplies.
_BUNDLE: Final[Mapping[str, tuple[str, str]]] = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


def _authority(host: str, port: int) -> str:
    """One ``host:port`` authority, in the form a browser writes it in a `Host`.

    Bracketed for IPv6, because that is what a browser sends and what ADR-0174 §6
    compares literally — an unbracketed ``fd7a::1:8422`` is not an authority any
    browser produces, and a set holding one would refuse every real request.

    Args:
        host: The address or name.
        port: The port.

    Returns:
        The authority.
    """
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def _refuse_an_address_this_machine_does_not_hold(address: str) -> None:
    """Check 3 of ADR-0174 §2: the address is one this machine actually holds.

    **The kernel is the only thing that knows**, and the way to ask it is to bind.
    So this binds a throwaway socket on an ephemeral port at that address and closes
    it: a success says the address is assigned to a local interface, and
    ``EADDRNOTAVAIL`` says it is not. Asked on a port of the kernel's choosing rather
    than on ``gateway_port``, so it cannot collide with the listener that follows and
    cannot turn "that port is in use" into an answer about the address.

    **Why the real bind is not left to answer it.** ``asyncio.start_server`` iterates
    the addresses ``getaddrinfo`` returns and *drops* one that answers
    ``EADDRNOTAVAIL`` — "assume the family is not enabled (bpo-30945)" — then raises
    a plain ``OSError`` with **no errno** once none is left. So the one condition
    ADR-0174 §2 has a rule about is exactly the one that arrives from there
    unidentifiable, and a gateway reading the errno would have reported it as an
    accident. Asking directly is what makes this a check rather than an
    interpretation.

    **What it is not.** It is not a claim that the address is the overlay's — that is
    check 2's, and neither check stands in for the other. Together they are §2: an
    overlay assigns each node its own address, so an address that is both on the
    overlay and assigned locally is this machine's overlay address. It is also not a
    reservation: the address could be removed between here and the bind, and then the
    bind fails with the raw errno, which is the stay-down fault
    ``service/remote.py`` leaves raw for the same reason.

    Args:
        address: The address the remote browser listener is about to bind.

    Raises:
        ConfigurationError: If the address is not one this machine holds.
        OSError: If the probe fails for any other reason, which is a fault about the
            machine rather than a statement about the configured address.
    """
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            probe.bind((address, 0))
    except OSError as exc:
        if exc.errno != errno.EADDRNOTAVAIL:
            raise
        msg = (
            f"the remote browser listener is configured to bind {address}, which is not "
            f"an address of this machine ({exc}). ADR-0174 §2 binds an address that "
            f"exists on the overlay *and* is this machine's own — the overlay agent "
            f"answers the first and only the kernel answers the second; set "
            f"ASSISTANT_GATEWAY_REMOTE_ADDRESS to the address your agent reports for "
            f"this machine, not for the device you want to browse from"
        )
        raise ConfigurationError(msg) from exc


def _check_the_remote_listener_can_serve(settings: Settings, *, agent: OverlayAgent | None) -> None:
    """Refuse a remote browser listener that could never admit anything (ADR-0174 §8).

    Two conditions, both stay-down and both cheaper here than at the door:

    - **An identity over the byte bound.** ``Settings`` refuses a blank element and
      one with no UTF-8 form; this is §8's other half, "reading the constant the wire
      seam owns" rather than restating it in ``core`` — which golden rule 2 forbids,
      because ``MAX_OVERLAY_IDENTITY_BYTES`` lives in ``ai_assistant.wire.overlay``
      and ``core`` may import nothing. An identity failing the invariant is one the
      agent can never report, so the owner's named device would be refused at every
      exchange with nothing saying why.
    - **No agent.** §3 makes the agent the sole source of a browsing device's
      identity and refuses every connection whose identity cannot be obtained, so a
      gateway configured on with no agent binds a door that answers nobody.

    Args:
        settings: The loaded configuration.
        agent: The overlay agent, or ``None``.

    Raises:
        ConfigurationError: On either condition.
    """
    if settings.gateway_remote_address is None:
        return
    if agent is None:
        msg = (
            "gateway_remote_address is set, so the gateway serves browsers on the "
            "overlay and must take each one's device identity from the overlay agent "
            "on this machine (ADR-0174 §3) — but no agent was supplied. Compose the "
            "gateway with one, or unset ASSISTANT_GATEWAY_REMOTE_ADDRESS"
        )
        raise ConfigurationError(msg)
    for position, identity in enumerate(settings.gateway_remote_browser_devices):
        size = len(identity.encode("utf-8"))
        if size > MAX_OVERLAY_IDENTITY_BYTES:
            msg = (
                f"gateway_remote_browser_devices[{position}] encodes to {size} bytes, over "
                f"the {MAX_OVERLAY_IDENTITY_BYTES} an overlay identity may occupy — no "
                f"overlay this system accepts produces one, so it could never equal an "
                f"identity the agent reports and the device it names could never exchange "
                f"a bootstrap value (ADR-0174 §8). Use the stable identity your overlay "
                f"agent reports for that device"
            )
            raise ConfigurationError(msg)


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
    """One browser connection: which door it arrived at, and who holds the far end.

    Compared by identity — ``eq=False`` — because the population §8 bounds is a
    set of *connections* and two of them in the same state are not one connection.
    ADR-0174 §8 makes that population the gateway's rather than each listener's, so
    both listeners put their connections in the same set and the ceilings are
    totals: "a connection on either listener counts against the same figure".

    "A browser connection is **admitted** from the moment it carries a request the
    gateway admitted under §4, and **unadmitted** before that… no rule of this ADR
    returns an admitted connection to the unadmitted population" (ADR-0168 §8) —
    read with ADR-0174 §4 on the remote listener, where admitting a request takes
    two facts rather than one.

    Attributes:
        admitted: Whether it has carried an admitted request.
        remote: Whether it arrived on the remote browser listener. The whole of what
            selects ADR-0174's rules, and ``False`` reproduces ADR-0168's gateway
            exactly.
        device: The overlay identity ADR-0174 §3 obtained for it, attested by the
            gateway's own agent and taken from nothing the peer asserts. ``None`` on
            a loopback connection, which has no such fact — and a remote connection
            never reaches a request with it still ``None``, because §3 refuses and
            closes one whose identity could not be obtained.
    """

    admitted: bool = False
    remote: bool = False
    device: str | None = None


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

    **Deciding to stream takes resources, and one place gives them back.** Both
    shapes take a hub connection before this is built — the answer stream directly,
    the delivery stream through the poll its first reader opens — and both are
    registered against the session that admitted them. :meth:`Gateway._write_stream`
    owns the whole of that: it registers before the first awaited write and releases
    in a ``finally``, so a peer that went away before the head landed, a session that
    ended mid-stream and an ordinary completion all take the same path out. Splitting
    it between the decision and the body is what round 2 of this PR's review found a
    window in.

    Attributes:
        handle: The session that admitted the request. ADR-0175 §7 ends every stream
            a session held at the moment that session ends, and a held-open stream
            sends no further request — so the association is what makes that clause
            reachable at all.
        head: The head to write before the first piece.
        body: Writes the pieces.
        delivery: The delivery stream this answers on, or ``None`` for an answer
            stream. Ending a delivery stream abandons it as well as closing the
            connection, so its writer stops waiting on a browser rather than on a
            socket that is about to go.
        release: Gives back what deciding to stream took — the hub slot, or the
            fan-out's registration and the poll that goes with the last reader.
            Called exactly once, on every exit.
    """

    handle: SessionHandle
    head: StreamHead
    body: Callable[[asyncio.StreamWriter], Awaitable[None]]
    release: Callable[[], None]
    delivery: DeliveryStream | None = None


class Gateway:
    """Serves one device's browsers, and reaches the hub as any spoke does."""

    def __init__(  # noqa: PLR0913 — one keyword per injected seam: config, hub, clock, timer, bundle, agent, entropy
        self,
        *,
        settings: Settings,
        engine: AssistantEngine,
        now: Callable[[], datetime],
        defer: Defer,
        bundle: Mapping[str, tuple[bytes, str]],
        agent: OverlayAgent | None = None,
        mint_value: Callable[[], str] = mint_value,
    ) -> None:
        """Build a gateway that has minted nothing and bound nothing.

        **This is "start" for ADR-0174 §8's second refusal**, and it is before the
        two things §8 names: nothing has been bound and no bootstrap value has been
        minted, let alone disclosed. §8 splits the identity invariant across two
        places "because golden rule 2 puts the bound outside ``core``" — ``Settings``
        refuses a blank element and one with no UTF-8 form, both decidable without
        importing anything, and the gateway refuses an element over
        ``MAX_OVERLAY_IDENTITY_BYTES`` by reading the constant the wire seam owns.
        Refusing in the constructor rather than in :func:`run_gateway` is what makes
        it unskippable: every composition of a gateway runs it, not just the one this
        module ships.

        Args:
            settings: The loaded configuration, read for ADR-0168 §8's ten figures,
                ADR-0175 §8's eleventh, ADR-0174 §8's three fields, and nothing else.
            engine: The hub, as the promoted ``AssistantEngine`` (ADR-0168 §1).
            now: The clock, injected.
            defer: How a session's death and a record interval's close are
                scheduled, injected for the same reason.
            bundle: The front end's assets, already read.
            agent: The overlay agent on **this** machine, which ADR-0174 §3 makes the
                sole source of a browsing device's identity. Required when
                ``gateway_remote_address`` is set and unused when it is not —
                :func:`run_gateway` builds the real one, and a test supplies a fake.
            mint_value: The entropy source for the bootstrap value and both
                session halves.

        Raises:
            ConfigurationError: If the remote browser listener is configured on with
                no agent to satisfy ADR-0174 §3, or if a listed device's identity is
                over the byte bound the wire seam holds every overlay identity to.
                Both are stay-down deployment faults (ADR-0083 §5): a gateway that
                bound the door anyway would refuse every connection on it, or refuse
                the owner's own named device at every exchange with nothing saying
                why.
        """
        _check_the_remote_listener_can_serve(settings, agent=agent)
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
        self._authority = _authority(_LOOPBACK, settings.gateway_port)
        self._origin = f"http://{self._authority}"
        self._agent = agent
        self._remote_address = settings.gateway_remote_address
        #: Read as a set, "compared for equality against the identity §3 obtained. A
        #: repeated element changes nothing and is not refused; order carries no
        #: meaning; and no element is matched by prefix, suffix, pattern or any form
        #: of partial comparison" (ADR-0174 §8).
        self._listed_devices = frozenset(settings.gateway_remote_browser_devices)
        #: What a `Host` may name on the remote listener (ADR-0174 §6): "the overlay
        #: address it bound, with the port it bound; or a name the owner configured
        #: in ``gateway_remote_host_names``, with that port". Compared literally, and
        #: nothing here is ever resolved or dialled.
        self._remote_authorities = frozenset(
            _authority(name, settings.gateway_port)
            for name in (self._remote_address, *settings.gateway_remote_host_names)
            if name is not None
        )
        #: The shapes answered whole, by path. A table rather than a chain of
        #: comparisons, so ADR-0177 §1's enumeration is one thing to read against the
        #: ADR — and so a path :data:`_ASSISTANT_PATHS` admits but nothing here
        #: serves is a ``KeyError`` in this process rather than a silent fallthrough
        #: onto whichever handler happened to be last.
        #:
        #: **One entry per operation, and never one entry performing two.** ADR-0168
        #: §1 forbids the gateway composing behaviour the promoted surface does not
        #: offer, and ADR-0177 §7 names the one place a lane would be tempted to: an
        #: amendment is ``revoke`` then ``grant``, composed in the front end as two
        #: browser requests reaching the two entries below, and there is deliberately
        #: no third entry that performs both.
        self._unary: Mapping[str, Callable[[Request], Awaitable[Response]]] = {
            _ASK_PATH: self._ask,
            _CONVERSATIONS_PATH: self._recent_conversations,
            _CONVERSATION_PATH: self._conversation,
            _FORGET_CONVERSATION_PATH: self._forget_conversation,
            _SOURCES_PATH: self._grantable_sources,
            _GRANT_PATH: self._grant,
            _REVOKE_PATH: self._revoke,
            _RECENT_GRANTS_PATH: self._recent_grants,
            _STANDING_PATH: self._standing_grants,
            _BELIEFS_PATH: self._beliefs,
            _BELIEF_PATH: self._belief,
            _FORGET_BELIEF_PATH: self._forget_belief,
            _QUESTIONS_PATH: self._questions,
            _INTERRUPTED_PATH: self._interrupted_questions,
            _ANSWER_PATH: self._answer,
            _FORGET_QUESTION_PATH: self._forget_question,
            _OBSERVE_PATH: self._observe,
        }

    @property
    def origin(self) -> str:
        """The loopback origin this gateway serves, and the one it admits there."""
        return self._origin

    @property
    def origins(self) -> tuple[str, ...]:
        """Every origin a browser can reach this gateway at, loopback first.

        More than one only where ADR-0174's remote browser listener is configured on,
        and then one per authority §6 of that ADR admits — the overlay address it
        binds, and each name the owner configured. The owner needs all of them: the
        exit test milestone 14 names is a phone, and the address to type into it is
        not the loopback one this gateway has always printed.

        Returns:
            The origins, in the order a disclosure should list them.
        """
        remote = sorted(self._remote_authorities)
        return (self._origin, *(f"http://{one}" for one in remote))

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
            partial(self._handle, remote=False), host=_LOOPBACK, port=self._settings.gateway_port
        )
        _log.info("gateway.listening", origin=self._origin, served_paths=sorted(self._bundle))
        return server

    async def start_remote(self) -> asyncio.Server | None:
        """Bind the remote browser listener, if the owner configured one (ADR-0174 §2).

        > The remote browser listener is **off unless it is configured on**. A
        > gateway with no remote-browser-listener configuration binds only ADR-0168
        > §2's loopback listener.

        **§2's bind rule is decided by three checks in three places, and neither of
        the two here claims the other's ground.** §2 admits only "an address that
        exists on that overlay" and forbids a wildcard, a physical interface, a
        loopback address and a public one.

        1. ``Settings`` refuses what ``ipaddress`` can decide — the wildcard, the
           name, the loopback, the multicast, the link-local and the globally
           routable address (ADR-0174 §8).
        2. :meth:`_confirm_the_address_is_on_the_overlay` asks the agent on this
           machine whether the overlay places a node at the address, which is the
           only way to tell an overlay address from an ``eth0`` one — nothing in
           ``192.168.1.5`` says which it is, and no conforming overlay agent
           (ADR-0124 §2) reports a node at an address that is not on the overlay.
        3. :func:`_refuse_an_address_this_machine_does_not_hold` requires the
           address to be assigned to this machine, which only the kernel knows and
           only a bind can ask.

        **The conjunction is what satisfies §2, and each check on its own does
        not** — the distinction adversarial review found on the first round of this
        PR, correctly. The agent's answer says *the overlay places a node at this
        address*; it does not say *and that node is us*, because the seam a client
        holds asks one question ("who is at this address") where the hub's own asks
        two (:class:`ai_assistant.wire.overlay.OverlayAgent`, which this lane
        consumes rather than widens). So check 3 supplies the missing half
        mechanically: an overlay assigns each node its own address, so an address
        that is both on the overlay and assigned locally is this machine's overlay
        address. Check 2 alone would admit another node's address, and check 3 alone
        would admit ``eth0``'s.

        **It is also the earliest moment the agent's absence can be reported.** Every
        connection on this listener needs §3's identity, and a connection whose
        identity cannot be obtained is refused and closed — so a gateway that bound
        this door with no reachable agent would present an open port that refuses
        everything, which is exactly the pair of failures ADR-0168 §9 refuses to
        present identically.

        Returns:
            The bound server, or ``None`` where the listener is off.

        Raises:
            ConfigurationError: If the overlay agent places no node at the configured
                address or cannot be asked, or if the address is not one this machine
                holds. Each is a stay-down deployment fault (ADR-0083 §5): restarting
                unchanged never succeeds, and what has to change is the configuration
                or the overlay.
            OSError: If the bind fails for any other reason. Left to propagate for
                the reason :mod:`ai_assistant.service.remote` leaves it — "the raw
                errno distinguishes a stay-down fault from a transient one" — and an
                address in use is exactly such a case.
        """
        address = self._remote_address
        if address is None:
            return None
        await self._confirm_the_address_is_on_the_overlay(address)
        _refuse_an_address_this_machine_does_not_hold(address)
        server = await asyncio.start_server(
            partial(self._handle, remote=True), host=address, port=self._settings.gateway_port
        )
        _log.info(
            "gateway.remote_listening",
            authorities=sorted(self._remote_authorities),
            listed_devices=len(self._listed_devices),
        )
        return server

    async def _confirm_the_address_is_on_the_overlay(self, address: str) -> None:
        """Check 2: the overlay places a node at the address (ADR-0174 §2).

        This is the half no string can decide, and §2's own words are that "the
        gateway binds an address the agent provides". It says nothing about *which*
        node — see :meth:`start_remote` for why that is check 3's job rather than a
        gap.

        Args:
            address: The address about to be bound.

        Raises:
            ConfigurationError: If the agent places no node there, or will not say.
        """
        agent = self._agent
        if agent is None:  # pragma: no cover — the constructor refuses this pairing
            msg = "the remote browser listener is configured on with no overlay agent"
            raise ConfigurationError(msg)
        try:
            await agent.identify(address, self._settings.gateway_port)
        except OverlayIdentityUnavailableError as exc:
            msg = (
                f"the remote browser listener is configured to bind {address}, and the "
                f"overlay agent on this machine places no node there ({exc}). "
                f"ADR-0174 §2 binds only an address that exists on the overlay and "
                f"forbids an address of a physical interface, so the gateway will not "
                f"bind one it cannot confirm; start the overlay agent and use the address "
                f"it reports for this machine, or unset ASSISTANT_GATEWAY_REMOTE_ADDRESS "
                f"to serve browsers over the loopback listener alone"
            )
            raise ConfigurationError(msg) from exc

    async def serve(self) -> None:
        """Bind every configured listener and serve until cancelled.

        The loopback listener is bound whether or not the remote one is (ADR-0174
        §2), and both are torn down together — with every session ended on the way
        out, whichever listener minted it (ADR-0168 §4).

        **The stack is what makes a failed second bind clean.** A gateway whose
        remote listener will not start must not leave a loopback listener answering
        behind it: the owner asked for a gateway serving two doors, and one serving
        one of them silently is a deployment that does something its configuration
        does not say.
        """
        async with contextlib.AsyncExitStack() as stack:
            # Registered first so it runs *last* — after both sockets are closed —
            # and so it runs at all when the remote bind is what fails.
            stack.callback(self.close)
            bound = [await stack.enter_async_context(await self.start())]
            remote = await self.start_remote()
            if remote is not None:
                bound.append(await stack.enter_async_context(remote))
            await asyncio.gather(*(one.serve_forever() for one in bound))

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

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *, remote: bool
    ) -> None:
        """Serve one connection under ADR-0168 §8's two ceilings and one deadline.

        **On the remote listener the identity comes first, and before the ceilings it
        does not.** ADR-0174 §3 orders the identity check "before ADR-0168 §7's
        ``Host`` and ``Origin`` checks and before any session is read", which is where
        it sits; §8's ceilings are ahead of it because a ceiling refusal *serves*
        nothing — "it refuses to accept a further connection rather than queueing it"
        — and asking the agent about a connection the gateway is closing unread would
        put a local query on the one path a flood can drive.

        Args:
            reader: The connection's reader.
            writer: The connection's writer.
            remote: Whether this is the remote browser listener's door.
        """
        connection = _Connection(remote=remote)
        if not self._admit_connection(connection):
            await _close(writer)
            return
        try:
            if remote and not await self._identify(writer, connection):
                return
            await self._serve_connection(reader, writer, connection)
        finally:
            self._connections.discard(connection)
            await _close(writer)

    async def _identify(self, writer: asyncio.StreamWriter, connection: _Connection) -> bool:
        """Take the connecting device's overlay identity from this machine's agent.

        > Before serving anything on the remote browser listener — a static asset and
        > the bootstrap exchange included — the gateway obtains the connecting
        > device's overlay identity from the overlay agent running on the gateway's
        > **own** machine, over a local interface. It may not take that identity from
        > anything the peer asserts — a header, a cookie, a query parameter, a request
        > body — and it may not obtain it by a call that leaves the machine. A
        > connection whose overlay identity cannot be obtained is refused and closed.
        > (ADR-0174 §3)

        **Nothing is recorded for a refusal here**, and §3 is explicit about why: a
        connection refused on it "reaches no clause of ADR-0168 §3, §4, §5 or §6 at
        all", so it is outside §6's recorded set exactly as §8's ceilings are. The
        warning below is a fault the owner may need to act on — their agent is not
        answering — and carries no fact about the request, which has not been read.

        **Nothing is written back either.** The peer is refused by the connection
        closing, because the gateway has not yet read a request and so has nothing to
        answer; a status line here would be a response to a request that does not
        exist.

        **A connection waiting on this query is already counted**, which is what
        bounds an agent that has stopped answering: it was admitted to
        :attr:`_connections` a line earlier, so ``gateway_max_browser_connections``
        and ``gateway_max_pending_connections`` hold while the query is out, and the
        query itself is bounded by the agent client's own five-second deadline
        (``wire.overlay``). ``gateway_read_timeout`` does not reach here, because
        there is no read yet to bound.

        Args:
            writer: The accepted connection, for its peer address.
            connection: The connection to record the identity on.

        Returns:
            Whether an identity was obtained.
        """
        agent = self._agent
        peer = writer.get_extra_info("peername")
        if agent is None or not isinstance(peer, tuple) or len(peer) < _ADDRESS_PARTS:
            _log.warning(
                "gateway.remote_peer_unaddressed",
                detail=(
                    "a connection on the remote browser listener carried no peer address "
                    "to ask the overlay agent about, so it is refused (ADR-0174 §3)"
                ),
            )
            return False
        try:
            connection.device = await agent.identify(str(peer[0]), int(peer[1]))
        except OverlayIdentityUnavailableError as exc:
            _log.warning(
                "gateway.remote_identity_unavailable",
                reason=str(exc),
                detail=(
                    "the gateway takes a browsing device's identity from its own overlay "
                    "agent and never from the peer, so a peer it cannot name is refused "
                    "(ADR-0174 §3)"
                ),
            )
            return False
        return True

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

        **The stream is registered before the first awaited write, and that ordering
        is the whole of ADR-0175 §7's reachability.** Nothing between
        :meth:`SessionTable.admit` and this line yields to the event loop — the
        decision is a chain of coroutine calls with no suspension point in it — so a
        stream registered here cannot have missed its own session's death. Registered
        one line later, after the head has drained, it could: a drain that yields
        (a paused transport is enough) lets the session's scheduled death run first,
        find no stream against that handle, and leave the one that follows with
        nothing that will ever end it. That is the window round 2 of this PR's review
        found, and it is closed by ordering rather than by a second check.

        **The release is a ``finally`` for the same reason it is not the body's.** A
        peer that went away before the head landed never reaches ``body`` at all, and
        a session ending mid-stream cancels the task driving it — so the two paths a
        body-owned release would miss are exactly the two that leak: a hub slot held
        for the process's whole life (ADR-0175 §7), and a poll left running for a
        reader that never existed, which is §4's "while and only while at least one
        delivery stream is open" broken by an error path rather than by a rule.

        Args:
            writer: The connection's writer.
            answer: What to stream.
            closing: Whether the connection is closed once this completes.

        Returns:
            Whether the connection survived. ``False`` where the peer went away,
            which is an ordinary end for a stream and not a fault to report.
        """
        held = _OpenStream(writer=writer, delivery=answer.delivery, driver=asyncio.current_task())
        self._register(answer.handle, held)
        try:
            writer.write(render_stream_head(replace(answer.head, close=closing), policy=_POLICY))
            await writer.drain()
            await answer.body(writer)
            writer.write(render_stream_end())
            await writer.drain()
        except ConnectionError, OSError:
            return False
        finally:
            self._unregister(answer.handle, held)
            answer.release()
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
        """Decide one request (ADR-0168 §3, §7, §1's biconditional; ADR-0174 §4).

        The order is §7's: "Both checks run before the session is read, and a
        request failing either is refused without the session being consulted at
        all." Classification is not a check — it decides which of §6's four classes
        a record would name — so it happens first and refuses nothing.

        **The device check sits between the assets and everything else, and that
        position is ADR-0174 §4's whole content.** §4 admits a request on the remote
        listener only when the device is listed *and* a live session is presented,
        and separates §3's two pre-session exceptions because "they are not alike in
        what they hand back": the assets are "the bundle this repository ships to
        anyone who installs it", so an overlay member obtains nothing from them they
        could not obtain from the distribution; the bootstrap exchange hands back a
        session, "and a session is the whole of what admits a browser to the device's
        authority". So the assets are answered above this line and every other class
        below it — the exchange included, which is what stops a hostile overlay
        member phishing a value from a mistyped address and spending it from its own
        device.

        The check is ahead of the session read for §3's reason one level in: an
        unlisted device is refused without the gateway consulting a session at all.
        """
        request_class = self._classify(request)
        condition = self._check_door(request, connection)
        if condition is not None:
            return self._refuse(request_class, condition, connection)
        if request_class is RequestClass.ASSET:
            body, media_type = self._bundle[request.path]
            return Response(200, "OK", body=body, content_type=media_type, close=False)
        if connection.remote and connection.device not in self._listed_devices:
            return self._refuse(request_class, RefusalCondition.DEVICE_NOT_LISTED, connection)
        if request_class is RequestClass.BOOTSTRAP:
            return self._exchange(request, connection)
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

    def _check_door(self, request: Request, connection: _Connection) -> RefusalCondition | None:
        """Run ADR-0168 §7's two checks, both decidable from the request alone.

        The `Host` check is what closes DNS rebinding — "a page the owner visits
        from a name the attacker controls can have that name re-resolve to
        `127.0.0.1`" — one step earlier than the session would, "on a fact
        decidable from the request alone rather than on the session logic being
        right". A repeated `Host` or `Origin` reads as absent
        (:meth:`Request.header`) and is refused, because a door that picked the
        first of two would let the peer choose which one it is judged on.

        **The job is unchanged on the remote listener and the set is larger**
        (ADR-0174 §6): the gateway refuses any `Host` that is not "the overlay
        address it bound, with the port it bound; or a name the owner configured in
        ``gateway_remote_host_names``, with that port. The comparison is literal
        against the configured set. **The gateway resolves nothing**". §7's reason
        survives whole — "rebinding is a property of the attacker's own name rather
        than of the target", so an attacker's name is refused on either listener
        because it is not in the owner's set. Admitting a configured name is not
        #912's posture reversed: a `Host` header is a string the browser reports
        about the URL the owner typed, never a destination anything is sent to.

        **The `Origin` is compared against the authority this request's own `Host`
        named**, which is §6's rule and, on the loopback listener, the one origin
        this gateway has always admitted — a `Host` there is admitted only when it
        equals :attr:`_authority`, so the comparison is byte for byte the one
        ADR-0168 §7 made.

        Args:
            request: The request as parsed.
            connection: The connection it arrived on, which decides which set of
                authorities its `Host` is judged against.

        Returns:
            The condition it fails, or ``None`` where it passes both.
        """
        admitted = self._remote_authorities if connection.remote else frozenset({self._authority})
        host = request.header("host")
        if host is None or host not in admitted:
            return RefusalCondition.HOST_NOT_BOUND
        origin = request.header("origin")
        if origin is not None and origin != f"http://{host}":
            return RefusalCondition.ORIGIN_NOT_OWN
        return None

    def _exchange(self, request: Request, connection: _Connection) -> Response:
        """The one exchange that mints a session (ADR-0168 §5).

        "A failed exchange discloses only that it failed — never whether the value
        was well-formed, whether one is still outstanding, or whether a session
        already exists", so every way of failing returns the same refusal on the
        same condition.

        The value is consumed by the mint it produced rather than by the attempt:
        an exchange refused at ADR-0168 §4's ceiling yielded no session, and §5
        makes the value "exchangeable for exactly one **session**".

        **On the remote listener this is reached only from a listed device**, and
        :meth:`_respond` is where that is decided — one line earlier, so an unlisted
        device's exchange is "refused without the value being read, compared or
        consumed" (ADR-0174 §4). Reading the payload here at all would break the
        first of those three; consuming it would break the third, leaving the owner
        holding a value an attacker had spent.

        Args:
            request: The exchange as parsed.
            connection: The connection it arrived on, for the identity ADR-0174 §3
                puts on the record a mint or a refusal writes.

        Returns:
            The two session values, or the refusal.
        """
        presented = _string(_payload(request), "bootstrap_value")
        held = self._bootstrap
        if (
            presented is None
            or held is None
            or held.spent
            or not hmac.compare_digest(verifier(presented), held.verifier)
        ):
            return self._refuse(
                RequestClass.BOOTSTRAP, RefusalCondition.BOOTSTRAP_EXCHANGE_FAILED, connection
            )
        values = self._sessions.mint()
        if values is None:
            return self._refuse(
                RequestClass.BOOTSTRAP, RefusalCondition.SESSION_CEILING, connection
            )
        held.spent = True
        self._records.session_minted(device=connection.device)
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
            return self._refuse(request_class, RefusalCondition.NO_LIVE_SESSION, connection)
        if outcome is Admission.COOKIE_HALF_MISMATCH:
            return self._refuse(request_class, RefusalCondition.COOKIE_HALF_MISMATCH, connection)
        connection.admitted = True
        if request_class is RequestClass.ASSISTANT:
            return await self._assistant(request, header_half, connection)
        # Admitted, and asking the assistant for nothing: answered, and the engine
        # is not reached (ADR-0168 §1's biconditional). Not a refusal on any of
        # §3 to §7's conditions, so nothing is recorded and the connection survives.
        return _fault(404, "Not Found", "no-such-path", close=False)

    async def _assistant(
        self, request: Request, header_half: str | None, connection: _Connection
    ) -> Response | _Streamed:
        """Resolve one admitted assistant request onto ADR-0177 §1's enumeration.

        **The enumeration is here and it is closed.** Every operation outside it is
        unreached from a browser, and no lane adds one without its own ratified
        decision — which is what keeps ADR-0174's permission to run a gateway on the
        hub's own machine from quietly handing a browser the connection operations
        ADR-0177 §3 splits by listener, now that a loopback-dialling gateway no
        longer meets the hub's remote refusal (ADR-0174 §11).

        **Every unary handler answers or raises** :class:`_Refused`, and this is
        where the second becomes the first. A handler therefore reads as one engine
        call with the arguments the browser supplied, which is the form ADR-0168 §1's
        biconditional is checkable in.

        Args:
            request: The admitted request.
            header_half: The value it was admitted on. The two streamed shapes need
                the session's own handle, because ADR-0175 §7 ends every stream a
                session held at the moment that session ends.
            connection: The connection it arrived on, for the record a refusal writes.

        Returns:
            The response, or the stream to write.
        """
        shape = (request.method, request.path)
        if shape not in _STREAMED_SHAPES:
            try:
                return await self._unary[request.path](request)
            except _Refused as refused:
                return refused.response
        handle = None if header_half is None else self._sessions.handle(header_half)
        if handle is None:  # pragma: no cover — admitted means a session verified it
            return self._refuse(
                RequestClass.ASSISTANT, RefusalCondition.NO_LIVE_SESSION, connection
            )
        if shape == ("POST", _ASK_STREAM_PATH):
            return self._ask_streaming(request, handle)
        return self._delivery_stream(handle)

    async def _relayed[T](self, call: Callable[[], Awaitable[T]]) -> T:
        """Make one call on the promoted surface, or refuse instead of making it.

        The whole of what every unary handler shares, in one place: the hub-connection
        ceiling ADR-0168 §8 refuses rather than queues, and ADR-0168 §9's three
        conditions, each answered as its own. §9 requires a transport failure
        "distinguishable from a request the hub received and declined" and forbids
        ever presenting one "as an answer" — and ADR-0177 §7's third clause is what
        that distinction is *for* at this surface, because a browser composing an
        amendment reads which of ADR-0139 §4's three outcomes each act got from it and
        from nothing else.

        The gateway does not retry, does not queue, and answers from nothing of its
        own. The slot is returned whichever way the call ends, the refusal included.

        Args:
            call: The one engine call this request resolves to, with the arguments
                the browser supplied already bound.

        Returns:
            Whatever the promoted surface returned.

        Raises:
            _Refused: If no hub connection was free, or the call failed.
        """
        if not self._take_hub_slot():
            raise _Refused(_ceiling())
        try:
            return await call()
        except (TransportError, AssistantError, ValueError) as exc:
            raise _Refused(_relay_fault(exc)) from exc
        finally:
            self._give_hub_slot()

    async def _ask(self, request: Request) -> Response:
        """Relay one turn to the hub and render what came back (ADR-0168 §1, §9).

        The budget is the gateway's own and no browser value reaches it: a turn budget
        is the **caller's** (ADR-0029 §4), which ADR-0177 §1 makes one of exactly two
        members of the one class of argument this adapter supplies of itself.
        """
        payload = _payload(request)
        outcome = await self._relayed(
            partial(
                self._engine.converse,
                _required_string(payload, "utterance"),
                timeout=_TURN_BUDGET,
                conversation_id=_string(payload, "conversation_id"),
            )
        )
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
            handle=handle,
            head=StreamHead(content_type=streams.MEDIA_TYPE),
            body=partial(self._pump_answer, utterance=utterance, conversation=conversation),
            release=self._give_hub_slot,
        )

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
            handle=handle,
            head=StreamHead(content_type=streams.MEDIA_TYPE),
            body=partial(write_stream, stream=opened, frame=_frame),
            release=partial(self._deliveries.close, opened),
            delivery=opened,
        )

    async def _recent_conversations(self, request: Request) -> Response:
        """List conversations, most recently active first (ADR-0074 §2, ADR-0177 §1)."""
        payload = _payload(request)
        held = await self._relayed(
            partial(
                self._engine.recent_conversations,
                limit=_page(payload, "limit", DEFAULT_PAGE_SIZE),
                offset=_page(payload, "offset", 0),
            )
        )
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
        named = _required_string(_payload(request), "conversation_id")
        digest = await self._relayed(partial(self._engine.conversation, named))
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
        named = _required_string(_payload(request), "conversation_id")
        destroyed = await self._relayed(partial(self._engine.forget_conversation, named))
        return _rendered({"destroyed": destroyed})

    # --- ADR-0177 §6: the grant surface -----------------------------------
    #
    # Five operations and five handlers. **None of them composes an amendment**
    # (§7): a browser amending a grant sends a `/revoke` and then a `/grant`, and
    # the gateway holds nothing between them — it does not know the two requests
    # are related and has nowhere to put the knowledge if it did. That is ADR-0139
    # §4's own reasoning arriving one hop out: composing the two calls client-side
    # "is what puts the intermediate state where a surface can report it".

    async def _grantable_sources(
        self,
        request: Request,  # noqa: ARG002 — one signature per entry in `_unary`
    ) -> Response:
        """Answer *what may I grant?* and nothing else (ADR-0097 §9, ADR-0139 §1).

        The location each entry carries "is on this response and on no stored record"
        (ADR-0102 §6), and it crosses because a client "renders each ``location`` and
        takes an explicit act from the user before it calls ``grant``". A gateway that
        dropped it would leave the front end unable to meet ADR-0139 §5 and therefore
        unable to grant at all.

        Args:
            request: The admitted request, which carries no argument.

        Returns:
            One entry per grantable source.
        """
        offered = await self._relayed(self._engine.grantable_sources)
        return _rendered({"sources": [_source_view(one) for one in offered]})

    async def _grant(self, request: Request) -> Response:
        """Record one grant, for the uses the browser named (ADR-0097 §2).

        ``source`` is relayed **verbatim** and normalised by nothing: ADR-0102 §2
        requires that "no implementation may strip, case-fold or otherwise normalise
        ``source`` at any point before it is compared", and an adapter that trimmed it
        here would make the gateway admit a call the in-process engine refuses.

        The scope is the browser's own, whole. This adapter neither defaults it, nor
        widens it, nor infers one member from another — ADR-0133 §2 forbids ranking
        them, and ADR-0097 §8 forbids anything deciding what the user permitted on
        their behalf.

        Args:
            request: The admitted request, carrying ``source`` and ``scope``.

        Returns:
            The recorded grant, as it was appended.
        """
        payload = _payload(request)
        recorded = await self._relayed(
            partial(
                self._engine.grant,
                _required_string(payload, "source"),
                scope=_uses(payload, "scope"),
            )
        )
        return _rendered({"grant": _grant_view(recorded)})

    async def _revoke(self, request: Request) -> Response:
        """Withdraw the live grant on one source, or report there was none.

        **No admission check, deliberately** (ADR-0102 §4): a value no reader declares
        finds no live grant and answers ``null``, which is what keeps a grant whose
        reader was later unconfigured revocable. So this handler applies none either —
        it would be the same refusal one layer out, and would make a grant permanently
        unrevokable from a browser.

        Args:
            request: The admitted request, carrying ``source``.

        Returns:
            The revoking record, or ``null`` where no live grant covered the source.
        """
        named = _required_string(_payload(request), "source")
        withdrawn = await self._relayed(partial(self._engine.revoke, named))
        return _rendered({"revoked": None if withdrawn is None else _grant_view(withdrawn)})

    async def _recent_grants(self, request: Request) -> Response:
        """List what was granted and withdrawn, newest first (ADR-0097 §4).

        **``limit`` and no ``offset``**, which is the surface's own departure from the
        other paging signatures (ADR-0102 §10) and is not repaired here: a gateway
        offering an offset it would have to implement by over-fetching and slicing
        would be composing a page the promoted surface does not offer.

        Args:
            request: The admitted request, carrying an optional ``limit``.

        Returns:
            The records, newest first.
        """
        payload = _payload(request)
        recorded = await self._relayed(
            partial(self._engine.recent_grants, limit=_page(payload, "limit", DEFAULT_PAGE_SIZE))
        )
        return _rendered({"grants": [_grant_view(one) for one in recorded]})

    async def _standing_grants(
        self,
        request: Request,  # noqa: ARG002 — one signature per entry in `_unary`
    ) -> Response:
        """Answer *what do I currently authorise?* (ADR-0139 §2).

        The second of ADR-0139 §1's two questions, and the answer to it. It is served
        on its own path because "neither answer is derivable from the other and no
        surface may present one as the other" — a gateway that annotated this set from
        ``grantable_sources``, or dropped a record because no held reader declares its
        source, would hide exactly the state this operation exists to show.

        Args:
            request: The admitted request, which carries no argument.

        Returns:
            Every grant live at the instant the response was computed.
        """
        standing = await self._relayed(self._engine.standing_grants)
        return _rendered({"standing": [_grant_view(one) for one in standing]})

    # --- ADR-0177 §5: the belief surface ----------------------------------

    async def _beliefs(self, request: Request) -> Response:
        """List what is believed, band-scoped, as summaries (ADR-0073 §1, ADR-0077 §6).

        **An absent filter and an empty one are different answers** and both cross:
        ``bands`` omitted selects every band, and ``bands: []`` selects nothing. The
        contract says so in terms, so a reader that folded the two would answer a
        question the browser did not ask.

        Args:
            request: The admitted request, carrying optional ``bands``, ``kinds``,
                ``limit`` and ``offset``.

        Returns:
            One summary per live belief the filters admit.
        """
        payload = _payload(request)
        held = await self._relayed(
            partial(
                self._engine.beliefs,
                bands=_members(payload, "bands", BeliefBand),
                kinds=_members(payload, "kinds", MemoryKind),
                limit=_page(payload, "limit", DEFAULT_PAGE_SIZE),
                offset=_page(payload, "offset", 0),
            )
        )
        return _rendered({"beliefs": [_belief_summary_view(one) for one in held]})

    async def _belief(self, request: Request) -> Response:
        """Read one belief with its citations resolved (ADR-0077 §6).

        **This is the read ADR-0177 §5's ceremony rests on**, and the reason it is a
        separate path from the listing: §5's second clause requires the render "taken
        from a ``belief`` read issued immediately before the confirmation is offered,
        and never from an entry of a ``beliefs`` listing the page rendered earlier",
        because "a page holds its listing until it is navigated away from".

        Args:
            request: The admitted request, carrying ``record_id``.

        Returns:
            The belief, or the absent-record condition as its own.
        """
        named = _required_string(_payload(request), "record_id")
        held = await self._relayed(partial(self._engine.belief, named))
        if held is None:
            return _fault(404, "Not Found", "no-such-belief", close=False)
        return _rendered({"belief": _belief_view(held)})

    async def _forget_belief(self, request: Request) -> Response:
        """Destroy one belief, permanently (ADR-0073 §5).

        The ceremony is the **front end's** and this handler is not it: ADR-0073 §5
        puts the show-then-confirm on the surface, and ADR-0177 §5 binds it at the
        browser. A gateway that refused an unconfirmed ``forget`` would be authoring a
        control the promoted surface does not have, and could not tell a confirmed
        call from an unconfirmed one anyway.

        Args:
            request: The admitted request, carrying ``record_id``.

        Returns:
            Whether a record was destroyed — ``false`` where the id named nothing
            live, which the contract states is not an error.
        """
        named = _required_string(_payload(request), "record_id")
        destroyed = await self._relayed(partial(self._engine.forget, named))
        return _rendered({"destroyed": destroyed})

    # --- ADR-0078 §8: the deferred-question surface -----------------------

    async def _questions(self, request: Request) -> Response:
        """List the questions waiting for an answer.

        Args:
            request: The admitted request, carrying optional ``limit`` and ``offset``.

        Returns:
            The answerable questions, each with what accepting would retire.
        """
        payload = _payload(request)
        waiting = await self._relayed(
            partial(
                self._engine.questions,
                limit=_page(payload, "limit", DEFAULT_PAGE_SIZE),
                offset=_page(payload, "offset", 0),
            )
        )
        return _rendered({"questions": [_question_view(one) for one in waiting]})

    async def _interrupted_questions(self, request: Request) -> Response:
        """List the questions whose answer was begun and whose outcome is unrecorded.

        A **second** listing rather than a filter on the first, because it answers a
        different question: "not 'failed' and not 'retryable': the system does **not**
        know whether the memory write landed" (ADR-0078 §9).

        Args:
            request: The admitted request, carrying optional ``limit`` and ``offset``.

        Returns:
            The interrupted questions.
        """
        payload = _payload(request)
        begun = await self._relayed(
            partial(
                self._engine.interrupted_questions,
                limit=_page(payload, "limit", DEFAULT_PAGE_SIZE),
                offset=_page(payload, "offset", 0),
            )
        )
        return _rendered({"questions": [_question_view(one) for one in begun]})

    async def _answer(self, request: Request) -> Response:
        """Answer one deferred question, and render what the answer did (ADR-0078 §5).

        ``accept`` is required and is read as a boolean and nothing else: a missing or
        mistyped member is refused rather than defaulted, because a default would be
        this adapter deciding whether the user believes something.

        Args:
            request: The admitted request, carrying ``question_id`` and ``accept``.

        Returns:
            Which of the five outcomes happened, and what it left behind.
        """
        payload = _payload(request)
        outcome = await self._relayed(
            partial(
                self._engine.answer,
                _required_string(payload, "question_id"),
                accept=_flag(payload, "accept"),
            )
        )
        return _rendered({"answered": _answer_view(outcome)})

    async def _forget_question(self, request: Request) -> Response:
        """Destroy one deferred question, so its subject can be asked again.

        The ceremony ADR-0177 §5 gives this verb at *this* surface is the front end's,
        and it is met with the two listings rather than with a single-question read
        that ADR-0078 §8 does not have (#495, cited and not absorbed).

        Args:
            request: The admitted request, carrying ``question_id``.

        Returns:
            Whether a question was destroyed.
        """
        named = _required_string(_payload(request), "question_id")
        destroyed = await self._relayed(partial(self._engine.forget_question, named))
        return _rendered({"destroyed": destroyed})

    # --- ADR-0077 §8: the passive half, driven by a caller ----------------

    async def _observe(self, request: Request) -> Response:
        """Read a bounded batch of a conversation's episodes and report what it did.

        ``conversation_id`` is "a **selector rather than a subject**", so an absent one
        selects the most recently active conversation rather than being an error.

        Args:
            request: The admitted request, carrying an optional ``conversation_id``.

        Returns:
            The proposals with their rulings, the counts kept apart, and the route.
        """
        named = _string(_payload(request), "conversation_id")
        report = await self._relayed(partial(self._engine.observe, conversation_id=named))
        return _rendered({"observation": _observation_view(report)})

    def _refuse(
        self, request_class: RequestClass, condition: RefusalCondition, connection: _Connection
    ) -> Response:
        """Record one refusal and answer it (ADR-0168 §3, §6, §8; ADR-0174 §3).

        The body carries the condition and nothing else: no assistant content, no
        fact about the hub's state, and no fact about whether the hub is
        reachable, which is what ADR-0168 §3 requires of every refusal. The
        connection is closed, because §8 requires it of a refusal on any of §3's,
        §4's, §5's, §6's, §7's and §8's conditions alike.

        The record carries the connection's attested overlay identity where there is
        one, which is ADR-0174 §3's addition to §6's enumeration and the reason it is
        worth having: ADR-0124 §7 has the hub record "each admission and each refusal
        with the device it named", and here for the first time "an owner reading a
        refusal learns *which of their devices* was refused". It never reaches the
        response — the device already knows who it is, and the enumeration governs
        the record rather than what is written back.

        Args:
            request_class: Which of ADR-0168 §6's four kinds the request was.
            condition: The single condition it was refused on.
            connection: The connection it arrived on, for the identity the record
                carries.

        Returns:
            The refusal to write.
        """
        self._records.refused(request_class, condition, device=connection.device)
        status, reason = _REFUSAL_STATUS[condition]
        return _fault(status, reason, condition.value)


class _Refused(Exception):  # noqa: N818 — it is not an error, it is the answer
    """One request the gateway answered instead of relaying (ADR-0168 §1, §3).

    Raised by a payload reader that found a member missing or of the wrong type, and
    by :meth:`Gateway._relayed` where no hub connection was free or the call failed.
    :meth:`Gateway._assistant` turns it back into the response it carries.

    **An exception rather than a returned union**, and the reason is legibility of
    the thing this module is judged on: with it, a handler is one engine call with
    the arguments the browser supplied, so ADR-0168 §1's biconditional — "the gateway
    composes no behaviour the promoted engine surface does not offer" — is read off
    the handler's shape. The alternative threads a "or the refusal" value through
    every argument position and buries the call in it.

    Attributes:
        response: What to answer instead.
    """

    def __init__(self, response: Response) -> None:
        """Carry one answer.

        Args:
            response: What to answer instead of relaying.
        """
        super().__init__(response.status)
        self.response = response


def _malformed() -> _Refused:
    """The one condition every payload reader below refuses on.

    A single condition rather than one per member, for the reason ADR-0168 §5 gives
    for the bootstrap exchange: naming *which* member was wrong tells a caller
    something about the surface's shape that it did not already have, and every
    caller of this surface ships in the same distribution as it (ADR-0168 §10) and
    therefore already knows.
    """
    return _Refused(_fault(400, "Bad Request", "malformed-request"))


def _required_string(payload: Mapping[str, Any], name: str) -> str:
    """One string member that must be there.

    Relayed **verbatim**: nothing here strips, case-folds or otherwise normalises a
    value, because ADR-0102 §2 forbids it before a ``source`` is compared and a
    reader that did it for one member would do it for all of them.

    Args:
        payload: The request's JSON object.
        name: The member to read.

    Returns:
        The value.

    Raises:
        _Refused: If the member is absent or is not a string.
    """
    value = _string(payload, name)
    if value is None:
        raise _malformed()
    return value


#: The bound ADR-0085 §9 declares for every page argument on the promoted surface,
#: and ADR-0073 §2 refuses rather than clamps. Written here because the surface
#: contract asks for it here: "an adapter that lets a user supply either **should
#: refuse an out-of-range value at its own parse boundary**", and a browser is an
#: adapter that lets a user supply both.
_PAGE_CEILING: Final = 2**63


def _page(payload: Mapping[str, Any], name: str, fallback: int) -> int:
    """One paging argument, or its default, refused at this adapter's own boundary.

    The type check is what tells a page of one from ``true`` — ``bool`` is an ``int``
    by inheritance, so ``{"limit": true}`` would otherwise be a page of one that
    nothing downstream could distinguish from a request for one.

    **The range is the surface's own and is not re-derived**: this is ADR-0085 §9's
    ``[0, 2**63)`` and nothing narrower. An operation with a tighter rule of its own —
    ``recent_grants`` requires a strictly positive ``limit`` (ADR-0102 §10) — keeps it,
    because that rule is the operation's rather than the argument's, and a bound
    invented here would be the second place ADR-0102 §2's reasoning warns about.

    Args:
        payload: The request's JSON object.
        name: The member to read.
        fallback: What an absent member means.

    Returns:
        The value, or the fallback.

    Raises:
        _Refused: If the member is present and is not an integer in ``[0, 2**63)``.
    """
    value = _integer(payload, name, fallback)
    if value is None or not 0 <= value < _PAGE_CEILING:
        raise _malformed()
    return value


def _flag(payload: Mapping[str, Any], name: str) -> bool:
    """One boolean member that must be there, read as a boolean and nothing else.

    Neither defaulted nor coerced. ``answer``'s ``accept`` is the member this exists
    for, and a truthy string arriving as an acceptance would have this adapter decide
    what the user believes — which is the one thing ADR-0097 §8's reasoning forbids a
    surface anywhere in this system.

    Args:
        payload: The request's JSON object.
        name: The member to read.

    Returns:
        The value.

    Raises:
        _Refused: If the member is absent or is not a boolean.
    """
    value = payload.get(name)
    if not isinstance(value, bool):
        raise _malformed()
    return value


def _members[T: StrEnum](
    payload: Mapping[str, Any], name: str, vocabulary: type[T]
) -> tuple[T, ...] | None:
    """One optional filter naming members of a closed vocabulary.

    **An absent member and an empty one are different answers**, which is the whole
    reason this returns ``None`` rather than an empty tuple for the first: ``bands``
    omitted means every band and ``bands: []`` "selects nothing, which is a different
    answer from ``None``" in the contract's own words.

    A value the vocabulary does not carry is refused rather than dropped. Dropping it
    would answer a narrower question than the browser asked and say nothing about
    having done so.

    Args:
        payload: The request's JSON object.
        name: The member to read.
        vocabulary: The enumeration its entries must name.

    Returns:
        The selected members, or ``None`` where the filter is absent.

    Raises:
        _Refused: If the member is present and is not a list of names the vocabulary
            carries.
    """
    if name not in payload:
        return None
    value = payload[name]
    if not isinstance(value, list):
        raise _malformed()
    known = {member.value: member for member in vocabulary}
    # **A string first, and membership second.** JSON carries objects and arrays, and
    # neither is hashable, so ``{"bands": [{}]}`` asked of the mapping directly raises
    # a ``TypeError`` this module does not catch — a request the surface has no shape
    # for arriving as a fault of the process rather than as a refusal. The type check
    # is what makes the lookup total over what a body can contain.
    if any(not isinstance(one, str) or one not in known for one in value):
        raise _malformed()
    return tuple(known[one] for one in value)


def _uses(payload: Mapping[str, Any], name: str) -> tuple[GrantScope, ...]:
    """The uses a ``grant`` authorises, as the browser named them.

    Whether the set is empty or repeats a member is **not** decided here: ADR-0097 §2
    refuses an empty scope at construction and ADR-0097 §10 refuses a duplicate, both
    locally and before any I/O, so the promoted surface answers it identically for
    every client and a second rule here could only differ from it. What this refuses
    is a member of no vocabulary at all, which is not a scope the surface has an
    answer for.

    Args:
        payload: The request's JSON object.
        name: The member to read.

    Returns:
        The uses, in the order the browser sent them; the record's own validator
        normalises them to declaration order (ADR-0097 §2).

    Raises:
        _Refused: If the member is absent, is not a list, or names a use that is not
            a member of :class:`~ai_assistant.core.types.GrantScope`.
    """
    if name not in payload:
        raise _malformed()
    selected = _members(payload, name, GrantScope)
    if selected is None:  # pragma: no cover — the membership check above precedes it
        raise _malformed()
    return selected


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


def _source_view(source: GrantableSource) -> dict[str, Any]:
    """One grantable source, as the page that offers a grant reads it (ADR-0102 §6).

    ``location`` crosses because a client "renders each ``location`` and takes an
    explicit act from the user before it calls ``grant``" (ADR-0139 §5), and it comes
    to rest nowhere: it is on this response and on no stored record, in no log and in
    no export (ADR-0097 §9a).

    ``live`` is the hub's own computation from the ``revokes`` relation and is
    relayed rather than re-derived (ADR-0102 §3). A gateway that answered it by
    walking ``recent_grants`` would report a withdrawn grant as live the moment a
    clock had been corrected backwards.
    """
    return {
        "source": source.source,
        "location": source.location,
        "live": None if source.live is None else _grant_view(source.live),
    }


def _grant_view(grant: SourceGrant) -> dict[str, Any]:
    """One grant or revocation, as the record says it happened (ADR-0097 §4).

    ``scope`` carries **exactly** the uses the record names, in the record's own
    normalised order. Nothing is added and nothing is dropped: ADR-0139 §3's third
    clause forbids a rendering that adds a use a grant does not name or omits one it
    does, and a view that padded the tuple to three members would have made that
    failure the front end's only option.

    ``revokes`` crosses because it is what distinguishes a revocation from a grant on
    a history page, and it is **not** a liveness computation: ADR-0102 §3 forbids
    presenting a record from ``recent_grants`` as live or as withdrawn on its own,
    and the front end says so rather than inferring it from this field.
    """
    return {
        "id": grant.id,
        "source": grant.source,
        "scope": [use.value for use in grant.scope],
        "decided_at": grant.decided_at.isoformat(),
        "revokes": grant.revokes,
    }


def _belief_fields(belief: Belief | BeliefSummary) -> dict[str, Any]:
    """What ADR-0073 §4 requires **both** belief views to convey.

    The band, the confidence, the kind, the content, when it was last revised, the
    end of its validity window where one is set, and the id. The three citation
    counts travel too, because §4's floor for a ``DERIVED`` belief is that the
    surface conveys "how many citations stand behind it" and must not "present a
    derived belief as carrying a warrant it cannot show" — and ADR-0107 §5 owes the
    elision ceiling beside any rendered count, which needs ``evidence_elided``.

    **The confidence is the presented one**, already lowered for support that has
    gone (ADR-0077 §6). Nothing here computes it, which is what stops two surfaces
    quoting different figures for one belief.

    ``unsupported`` is carried rather than left to the page to compute, so the one
    definition ADR-0085 §4a states holds on both types and on this surface too.
    """
    return {
        "id": belief.id,
        "band": belief.band.value,
        "kind": belief.kind.value,
        "content": belief.content,
        "confidence": belief.confidence,
        "last_updated": belief.last_updated.isoformat(),
        "valid_until": None if belief.valid_until is None else belief.valid_until.isoformat(),
        "evidence_count": belief.evidence_count,
        "lost_evidence": belief.lost_evidence,
        "evidence_elided": belief.evidence_elided,
        "unsupported": belief.unsupported,
    }


def _belief_summary_view(summary: BeliefSummary) -> dict[str, Any]:
    """One row of the listing, which ships counts and **not** citations.

    The split is the type's rather than this function's (ADR-0085 §4a): a
    :class:`~ai_assistant.core.types.BeliefSummary` has nowhere to put a citation, so
    a conforming listing cannot ship the corpus on every page and this view could not
    render one if it tried.
    """
    return _belief_fields(summary)


def _belief_view(belief: Belief) -> dict[str, Any]:
    """The single-belief view: the same fields, plus the resolved warrant.

    A citation that no longer resolves crosses as an entry whose ``content`` is
    ``null`` — a **tombstone**, never a bare id and never a silent gap (ADR-0073 §4's
    floor, ADR-0077 §6). :class:`~ai_assistant.core.types.Evidence` carries no id at
    all, so no renderer downstream can pass one off as the warrant.
    """
    return _belief_fields(belief) | {"evidence": [_evidence_view(one) for one in belief.evidence]}


def _evidence_view(evidence: Evidence) -> dict[str, Any]:
    """One citation, resolved to what it says or tombstoned (ADR-0077 §6)."""
    return {"content": evidence.content}


def _question_view(question: Question) -> dict[str, Any]:
    """One deferred question, with everything ADR-0078 §8 requires it to convey.

    What accepting would have the assistant believe and the band it **would** enter —
    carried as the conditional it is, because "a pending question is not a belief of
    any band"; why the user is being asked; why the proposal was made; what accepting
    would retire, "which is not decoration but the exact scope the answer authorises";
    when it was asked and until when it is answerable; its state, which is what tells
    an interrupted question from an open one; and any successor an answer already
    raised, with **that** question's own state (§9).
    """
    return {
        "id": question.id,
        "state": question.state.value,
        "content": question.content,
        "kind": question.kind.value,
        "band": question.band.value,
        "rationale": question.rationale,
        "reason": question.reason,
        "retires": [
            {"record_id": one.record_id, "content": one.content} for one in question.retires
        ],
        "asked_at": question.asked_at.isoformat(),
        "expires_at": None if question.expires_at is None else question.expires_at.isoformat(),
        "successor": _successor_view(question.successor),
    }


def _successor_view(successor: SuccessorLink | None) -> dict[str, Any] | None:
    """The question an answer already raised, carried **with its state** (ADR-0078 §9).

    The state is not optional decoration: only a waiting successor is something the
    user can go and answer, and naming a declined or interrupted one as "the follow-on
    question" would advertise something they cannot act on.
    """
    if successor is None:
        return None
    return {"id": successor.id, "state": successor.state.value}


def _answer_view(outcome: AnswerOutcome) -> dict[str, Any]:
    """What one answer did, as one of five outcomes (ADR-0078 §5, §9).

    ``successor_refused`` and ``disposed`` travel **beside** the outcome and never in
    place of it: a re-deferral that could queue no follow-up at all is not the same
    as one that did, and a question destroyed while its answer was being applied is a
    true statement about the bookkeeping rather than about the answer.
    """
    return {
        "kind": outcome.kind.value,
        "question_id": outcome.question_id,
        "record_id": outcome.record_id,
        "successor": _successor_view(outcome.successor),
        "successor_refused": outcome.successor_refused,
        "disposed": outcome.disposed,
    }


def _observation_view(report: ObservationReport) -> dict[str, Any]:
    """What one observation pass did (ADR-0077 §8).

    The three discard counts are kept **apart** because they are three different
    facts: what the producer could not use, what it dropped over its own limit, and
    what the write path refused for want of support. A single "not stored" figure
    would be this adapter deciding they are the same thing.

    ``route`` is absent where no model read the episodes at all, which is a fact
    about the pass rather than a missing field.
    """
    return {
        "proposals": [_proposal_view(one) for one in report.proposals],
        "discarded_unusable": report.discarded_unusable,
        "discarded_over_limit": report.discarded_over_limit,
        "dropped_unsupported": report.dropped_unsupported,
        "route": report.route,
        "conversation_id": report.conversation_id,
        "episodes_read": report.episodes_read,
    }


def _proposal_view(proposal: ObservedProposal) -> dict[str, Any]:
    """One proposal an observation pass made, with how memory folded it.

    ``decision`` is ``null`` where **no ruling was ever made** — the proposal never
    reached the write path — which is a different thing from a ruling that rejected
    it, and the two are not flattened into one.
    """
    return {
        "content": proposal.content,
        "kind": proposal.kind.value,
        "step": proposal.step.value,
        "confidence": proposal.confidence,
        "rationale": proposal.rationale,
        "decision": None if proposal.decision is None else proposal.decision.value,
        "record_id": proposal.record_id,
        "reason": proposal.reason,
        "evidence": [_evidence_view(one) for one in proposal.evidence],
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

    **Every origin is disclosed, not just the loopback one** (ADR-0174). The owner
    reads the value off this terminal and carries it to another device, and the
    address to type there is the overlay one — a disclosure naming only
    ``127.0.0.1`` would hand them a value and no door to spend it at. On a gateway
    with no remote listener this is the single origin it has always printed.

    **The agent is built only where a remote listener needs one**, from
    ``client_overlay_agent_socket`` — the field ADR-0174 §8 widens rather than
    duplicating: "a gateway may dial its hub over loopback and still serve browsers
    over the overlay, so the condition widens to cover a set
    ``gateway_remote_address``. No eleventh agent-socket field is owed, and the
    custody conditions ``wire/overlay.py`` enforces on that socket are applied
    unchanged." Those conditions are enforced by :func:`local_agent` itself, which
    refuses a configured path an untrusted user could answer on.

    Args:
        settings: The loaded configuration.
        engine: The hub, as the promoted ``AssistantEngine``. Built by whoever
            composes this process — the gateway builds no engine (ADR-0168 §1).
        disclose: How the bootstrap value and the origins reach the owner. Raising
            from it is what stops the gateway starting.
        now: The clock.

    Raises:
        AssistantError: If the bootstrap value cannot be disclosed, if the overlay
            agent's configured socket fails its custody conditions, or if the remote
            browser listener is configured in a way that could never serve.
    """
    gateway = Gateway(
        settings=settings,
        engine=engine,
        now=now,
        defer=default_defer(),
        bundle=packaged_bundle(),
        agent=_agent_for(settings),
    )
    disclose(gateway.mint_bootstrap(), ", ".join(gateway.origins))
    await gateway.serve()


def _agent_for(settings: Settings) -> OverlayAgent | None:
    """This machine's overlay agent, where a remote browser listener needs one.

    Args:
        settings: The loaded configuration.

    Returns:
        The agent, or ``None`` where no remote listener is configured and none is
        read. Building one eagerly would put a configured socket's custody check on
        the path of every gateway, including the loopback-only one ADR-0168 §2 rules
        and which never asks the agent anything.

    Raises:
        ConfigurationError: If a configured socket path fails the custody conditions
            ``wire/overlay.py`` holds both ends of ADR-0124 §4's hop to.
    """
    if settings.gateway_remote_address is None:
        return None
    return local_agent(settings.client_overlay_agent_socket, terms=CLIENT_AGENT_SOCKET)
