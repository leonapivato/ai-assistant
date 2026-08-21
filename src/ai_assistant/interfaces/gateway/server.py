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
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from importlib import resources
from typing import TYPE_CHECKING, Any, Final

import structlog

from ai_assistant.core.errors import AssistantError
from ai_assistant.core.types import Disposition, StepOutcome, TurnOutcome
from ai_assistant.interfaces.gateway.http import (
    IncompleteRequestError,
    MalformedRequestError,
    Request,
    RequestTooLargeError,
    Response,
    read_request,
    render,
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
    SessionTable,
    mint_value,
    verifier,
)
from ai_assistant.wire.errors import TransportError

if TYPE_CHECKING:  # pragma: no cover — imported for typing alone
    from collections.abc import Callable, Mapping

    from ai_assistant.core.config import Settings
    from ai_assistant.core.protocols import AssistantEngine

_log = structlog.get_logger(__name__)

#: The only address this gateway binds (ADR-0168 §2). Not a setting, deliberately.
_LOOPBACK: Final = "127.0.0.1"

#: The paths the browser-facing surface uses. ADR-0168 §12 leaves the surface to
#: this lane — "the request shapes, the paths, the document, and whether a push
#: carrier such as a WebSocket is among them… no ADR is owed for it and the
#: implementing lane decides it" — and it is deliberately three: a document, an
#: exchange, and a turn. Milestone 13 needs no server-initiated browser message,
#: and §12 declines a carrier for one before something emits it.
_SESSION_PATH: Final = "/session"
_ASK_PATH: Final = "/ask"

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
        )
        self._records = AdmissionRecorder(
            interval=settings.gateway_record_interval, now=now, defer=defer
        )
        self._connections: set[_Connection] = set()
        self._hub_in_flight = 0
        self._bootstrap: _Bootstrap | None = None
        self._authority = f"{_LOOPBACK}:{settings.gateway_port}"
        self._origin = f"http://{self._authority}"

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
        """
        self._sessions.clear()
        self._records.flush()

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
        """
        timeout = self._settings.gateway_read_timeout.total_seconds()
        while True:
            response = await self._next(reader, connection, timeout)
            if response is None:
                return
            # **The header is written from the decision, not beside it.** §8 closes
            # an unadmitted connection "once that request's response is complete"
            # whatever the response was, so a `Connection: keep-alive` on one would
            # be the rule announced and then disobeyed — and the peer would hold a
            # socket the gateway had already given up on.
            closing = response.close or not connection.admitted
            writer.write(render(replace(response, close=closing), policy=_POLICY))
            await writer.drain()
            if closing:
                return

    async def _next(
        self,
        reader: asyncio.StreamReader,
        connection: _Connection,
        timeout: float,  # noqa: ASYNC109 — ADR-0168 §8's own deadline, relayed to the read it bounds
    ) -> Response | None:
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

    async def _respond(self, request: Request, connection: _Connection) -> Response:
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
        """Which of ADR-0168 §6's four kinds this request is, decided from it alone."""
        if request.method == "GET" and request.path in self._bundle:
            return RequestClass.ASSET
        if request.method == "POST" and request.path == _SESSION_PATH:
            return RequestClass.BOOTSTRAP
        if request.method == "POST" and request.path == _ASK_PATH:
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
    ) -> Response:
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
            return await self._ask(request)
        # Admitted, and asking the assistant for nothing: answered, and the engine
        # is not reached (ADR-0168 §1's biconditional). Not a refusal on any of
        # §3 to §7's conditions, so nothing is recorded and the connection survives.
        return _fault(404, "Not Found", "no-such-path", close=False)

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
        if self._hub_in_flight >= self._settings.gateway_max_hub_connections:
            return _fault(
                503,
                "Service Unavailable",
                "hub-connection-ceiling",
                limit="gateway_max_hub_connections",
                close=False,
            )
        self._hub_in_flight += 1
        try:
            outcome = await self._engine.converse(
                utterance, timeout=_TURN_BUDGET, conversation_id=conversation
            )
        except TransportError as exc:
            return _fault(502, "Bad Gateway", "hub-unreachable", detail=str(exc), close=False)
        except AssistantError as exc:
            return _fault(
                422, "Unprocessable Content", "assistant-declined", detail=str(exc), close=False
            )
        except ValueError as exc:
            return _fault(400, "Bad Request", "rejected", detail=str(exc), close=False)
        finally:
            self._hub_in_flight -= 1
        return Response(
            200,
            "OK",
            body=_json({"outcome": _outcome_view(outcome)}),
            content_type="application/json",
            close=False,
        )

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


def _json(payload: Mapping[str, Any]) -> bytes:
    """Encode a response body."""
    return json.dumps(payload).encode("utf-8")


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
    carry. It mirrors the CLI's ``_render_turn`` exactly — the same notices, the
    same plan, the same step — because the two adapters render the same turn.
    """
    turn = outcome.turn
    plan = None if turn is None else turn.plan
    steps = () if plan is None else plan.steps
    return {
        "conversation_id": outcome.conversation_id,
        "capture_degraded": outcome.capture_degraded,
        "memory_degraded": turn is not None and turn.memory_degraded,
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
