"""The gateway's hosted listener, end to end, behind a fake sign-in edge (ADR-0327).

**Driven through a real socket**, for ``test_gateway_remote_listener.py``'s reason:
what ADR-0327 rules is about requests a listener admits, in an order, and which
listener a session was minted on — none of which a handler call shows.

**The edge is :mod:`gateway_edge`'s fake**: a key generated per case, and the compact
JWS it signs. Each case sends the request the real edge would forward — the door's
`Host`, the page's `https://` `Origin`, and the assertion in ``Edge-Assertion`` — and
changes the one thing it is about.

**The hosted listener binds ``127.0.0.1`` on its own port**, beside the loopback
listener on ``gateway_port`` (§5:5), which is the arrangement on a box with no
container. Marked ``integration`` because loopback sockets are what they open.
"""

from __future__ import annotations

import asyncio
import contextlib
import gc
import json
import socket
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
import structlog
from gateway_edge import DOOR, DOOR_ORIGIN, HOSTED_DEVICE, SUBJECT, FakeEdge
from gateway_mint import bootstrap_value
from gateway_ports import free_port
from gateway_timing import Clock, Timers

from ai_assistant.core.config import Settings
from ai_assistant.core.device_context import current_acting_for
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.types import DEFAULT_PAGE_SIZE
from ai_assistant.interfaces.gateway.edge import ASSERTION_HEADER
from ai_assistant.interfaces.gateway.http import Request
from ai_assistant.interfaces.gateway.server import Gateway
from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.wire.overlay import MAX_OVERLAY_IDENTITY_BYTES

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ai_assistant.core.types import ConversationSummary

pytestmark = pytest.mark.integration

_NOW: Final = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)

#: Each listener's bundle, told apart by the one file the hosted one serves
#: differently (ADR-0327 §11).
_BUNDLE: Final = {
    "/": (b"<!doctype html><p>document", "text/html; charset=utf-8"),
    "/app.js": (b"'use strict';", "text/javascript; charset=utf-8"),
    "/door.js": (b"local", "text/javascript; charset=utf-8"),
}
_HOSTED_BUNDLE: Final = {**_BUNDLE, "/door.js": (b"hosted", "text/javascript; charset=utf-8")}


class _Recording(FakeAssistantEngine):
    """An engine that records the device each listing was relayed for (ADR-0298 §1:5)."""

    def __init__(self) -> None:
        """Start having relayed nothing."""
        super().__init__()
        self.relayed_for: list[str | None] = []

    async def recent_conversations(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[ConversationSummary, ...]:
        """Record the outbound ``acting_for`` this call runs inside, then answer."""
        self.relayed_for.append(current_acting_for())
        return await super().recent_conversations(limit=limit, offset=offset)


@dataclass
class Answer:
    """One parsed response."""

    status: int
    headers: dict[str, list[str]]
    body: bytes

    @property
    def payload(self) -> dict[str, Any]:
        """The body as JSON, or an empty mapping."""
        try:
            parsed = json.loads(self.body)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def header(self, name: str) -> str | None:
        """The one value of a header, or ``None``."""
        found = self.headers.get(name, [])
        return found[0] if len(found) == 1 else None


async def _read_answer(reader: asyncio.StreamReader) -> Answer:
    """Parse one HTTP response."""
    head = await reader.readuntil(b"\r\n\r\n")
    lines = head.decode().split("\r\n")
    status = int(lines[0].split(" ")[1])
    headers: dict[str, list[str]] = {}
    for line in lines[1:]:
        if line:
            name, _, value = line.partition(":")
            headers.setdefault(name.lower(), []).append(value.strip())
    length = int(headers.get("content-length", ["0"])[0])
    return Answer(status=status, headers=headers, body=await reader.readexactly(length))


@dataclass
class Hosted:
    """A gateway with its loopback and hosted listeners bound, and its fake edge."""

    gateway: Gateway
    settings: Settings
    edge: FakeEdge
    engine: _Recording
    clock: Clock
    timers: Timers
    servers: list[asyncio.Server] = field(default_factory=list)

    def assertion(self, **claims: Any) -> str:
        """One assertion the edge signs now."""
        return self.edge.sign(self.clock(), **claims)

    async def send(  # noqa: PLR0913 — one keyword per part of a request a case varies
        self,
        method: str,
        path: str,
        *,
        body: bytes = b"",
        host: str | None = DOOR,
        origin: str | None = DOOR_ORIGIN,
        assertion: str | None | tuple[str, ...] = "sign",
        session: tuple[str, str] | None = None,
        loopback: bool = False,
        extra: tuple[str, ...] = (),
    ) -> Answer:
        """Send one request, as the edge forwards it, and read the answer.

        Args:
            method: The method.
            path: The path.
            body: The body.
            host: The `Host`, or ``None`` for none.
            origin: The `Origin`, or ``None`` for none.
            assertion: ``"sign"`` for a fresh valid one, a token, a tuple of tokens
                for a repeated header, or ``None`` for none.
            session: The cookie half and the header half, or ``None``.
            loopback: Send to the loopback listener instead, with its own `Host`.
            extra: Further header lines.

        Returns:
            The parsed response.
        """
        port = self.settings.gateway_port if loopback else self.settings.gateway_hosted_port
        lines = [f"{method} {path} HTTP/1.1"]
        if loopback:
            lines.append(f"Host: 127.0.0.1:{self.settings.gateway_port}")
        elif host is not None:
            lines.append(f"Host: {host}")
        if origin is not None:
            lines.append(f"Origin: {origin}")
        tokens = (self.assertion(),) if assertion == "sign" else assertion
        if isinstance(tokens, str):
            tokens = (tokens,)
        for token in tokens or ():
            lines.append(f"Edge-Assertion: {token}")
        if session is not None:
            cookie, header = session
            name = "assistant_session" if loopback else "__Host-assistant_session"
            lines.extend((f"Cookie: {name}={cookie}", f"X-Assistant-Session: {header}"))
        lines.extend(extra)
        if body:
            lines.extend(("Content-Type: application/json", f"Content-Length: {len(body)}"))
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            writer.write(("\r\n".join(lines) + "\r\n\r\n").encode() + body)
            await writer.drain()
            return await _read_answer(reader)
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await writer.wait_closed()

    async def exchange(self) -> tuple[str, str]:
        """Mint one hosted session; return its cookie half and header half."""
        answer = await self.send("POST", "/session/edge")
        assert answer.status == 200, answer.body
        cookie = answer.header("set-cookie")
        assert cookie is not None
        return cookie.split(";")[0].partition("=")[2], answer.payload["header_half"]

    async def loopback_session(self) -> tuple[str, str]:
        """Exchange a bootstrap value on the loopback listener."""
        body = json.dumps({"bootstrap_value": bootstrap_value(self.gateway)}).encode()
        answer = await self.send("POST", "/session", body=body, loopback=True, origin=None)
        assert answer.status == 200, answer.body
        cookie = answer.header("set-cookie")
        assert cookie is not None
        return cookie.split(";")[0].partition("=")[2], answer.payload["header_half"]

    async def listing(self, session: tuple[str, str] | None, **overrides: Any) -> Answer:
        """One request asking the assistant for something."""
        return await self.send("POST", "/conversations", body=b"{}", session=session, **overrides)


@contextlib.asynccontextmanager
async def _hosted(**overrides: Any) -> AsyncIterator[Hosted]:
    """Bind the loopback and hosted listeners and tear them down afterwards."""
    edge = FakeEdge()
    settings = Settings(
        gateway_port=free_port(),
        **edge.settings(gateway_hosted_port=free_port(), **overrides),
    )
    clock, timers = Clock(reading=_NOW), Timers()
    engine = _Recording()
    gateway = Gateway(
        settings=settings,
        engine=engine,
        now=clock,
        defer=timers,
        bundle=_BUNDLE,
        hosted_bundle=_HOSTED_BUNDLE,
    )
    one = Hosted(
        gateway=gateway, settings=settings, edge=edge, engine=engine, clock=clock, timers=timers
    )
    one.servers.append(await gateway.start())
    hosted = await gateway.start_hosted()
    assert hosted is not None
    one.servers.append(hosted)
    try:
        yield one
    finally:
        gateway.close()
        for server in one.servers:
            server.close()
            server.close_clients()
            with contextlib.suppress(Exception):
                await server.wait_closed()


@pytest.fixture
async def hosted() -> AsyncIterator[Hosted]:
    """A gateway serving its hosted owner through the fake edge."""
    async with _hosted() as one:
        yield one


#: The refusal §7:6 gives every request failing the assertion, the `Host` or the
#: `Origin`, whichever it failed.
_DOOR_REFUSED: Final = (403, {"fault": "door-refused"})


def _refusal(answer: Answer) -> tuple[int, dict[str, Any]]:
    return answer.status, answer.payload


# --- §5: off unless configured on, and where it binds --------------------------------


async def test_a_gateway_with_no_hosted_configuration_binds_no_hosted_listener() -> None:
    """§5:1: "Unset, which is the default, means off."""
    gateway = Gateway(
        settings=Settings(gateway_port=free_port()),
        engine=FakeAssistantEngine(),
        now=Clock(),
        defer=Timers(),
        bundle=_BUNDLE,
    )

    assert await gateway.start_hosted() is None
    assert gateway.hosted_origin is None


async def test_the_loopback_listener_is_bound_beside_the_hosted_one(hosted: Hosted) -> None:
    """§5:7: the loopback listener stays bound "under every clause of ADR-0168 §2", and
    its bootstrap exchange is unchanged (§8:3)."""
    session = await hosted.loopback_session()

    answer = await hosted.listing(session, loopback=True, origin=None)
    assert answer.status == 200, answer.body


async def test_the_doors_origin_is_not_one_a_bootstrap_value_is_disclosed_with(
    hosted: Hosted,
) -> None:
    """§8:3: the hosted listener serves no bootstrap exchange, so its origin is not one
    of the origins a disclosure hands the owner a value for."""
    assert hosted.gateway.hosted_origin == DOOR_ORIGIN
    assert DOOR_ORIGIN not in hosted.gateway.origins


def _unheld_private_address() -> str:
    """A private-use address no interface of this machine holds, found by asking.

    Asked rather than assumed: some machines hold surprising ones (WSL puts
    ``10.255.255.254`` on its loopback interface).
    """
    for candidate in ("10.231.58.199", "172.29.201.17", "192.168.251.233", "10.77.3.5"):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((candidate, 0))
            except OSError:
                return candidate
    pytest.skip("every candidate private-use address is held by this machine")


async def test_a_hosted_address_this_machine_does_not_hold_is_refused_at_bind() -> None:
    """§5:4: a private-use address is the container's own. One no interface here holds
    is a setup fault, said as one rather than as the bind's bare ``OSError``."""
    edge = FakeEdge()
    settings = Settings(
        gateway_port=free_port(),
        **edge.settings(
            gateway_hosted_address=_unheld_private_address(), gateway_hosted_port=free_port()
        ),
    )
    gateway = Gateway(
        settings=settings, engine=FakeAssistantEngine(), now=Clock(), defer=Timers(), bundle=_BUNDLE
    )

    with pytest.raises(ConfigurationError, match="not an address of this machine"):
        await gateway.start_hosted()


def test_a_hosted_device_over_the_byte_bound_is_refused_at_start() -> None:
    """§10:3: held to ADR-0298 §1:3's invariant, the byte bound the gateway's half of
    the split — "before it binds"."""
    edge = FakeEdge()
    settings = Settings(
        gateway_port=free_port(),
        **edge.settings(
            gateway_hosted_port=free_port(),
            gateway_hosted_device="d" * (MAX_OVERLAY_IDENTITY_BYTES + 1),
        ),
    )

    with pytest.raises(ConfigurationError, match="gateway_hosted_device"):
        Gateway(
            settings=settings,
            engine=FakeAssistantEngine(),
            now=Clock(),
            defer=Timers(),
            bundle=_BUNDLE,
        )


class _OwnNode:
    """An overlay agent naming this machine, for a gateway whose hub is elsewhere."""

    def __init__(self, node: str) -> None:
        self.node = node

    async def identify(self, host: str, port: int) -> str:  # pragma: no cover — never asked
        msg = f"no peer is identified here ({host}:{port})"
        raise AssertionError(msg)

    async def own_identity(self) -> str:
        return self.node


async def test_a_hosted_device_that_is_this_machines_own_is_refused_at_bind() -> None:
    """§10:2: no request from the hosted listener "acts with the gateway's own device's
    roles" — and one whose name is that device would."""
    edge = FakeEdge()
    settings = Settings(
        gateway_port=free_port(),
        remote_hub_address="100.64.0.1",
        **edge.settings(gateway_hosted_port=free_port(), gateway_hosted_device="nTHISNODE"),
    )
    gateway = Gateway(
        settings=settings,
        engine=FakeAssistantEngine(),
        now=Clock(),
        defer=Timers(),
        bundle=_BUNDLE,
        agent=_OwnNode("nTHISNODE"),
    )
    server = await gateway.start()
    try:
        with pytest.raises(ConfigurationError, match="this gateway's own machine"):
            await gateway.start_hosted()
    finally:
        gateway.close()
        server.close()
        await server.wait_closed()


# --- §6, §7:1, §7:6: the assertion first, and one refusal for the door's checks --------


async def test_an_asset_is_served_on_a_valid_assertion(hosted: Hosted) -> None:
    """§7:4: the assets are served without a session "once the checks above pass" —
    and the hosted bundle is the one served (§11)."""
    answer = await hosted.send("GET", "/door.js", origin=None)

    assert answer.status == 200
    assert answer.body == b"hosted"


async def test_the_loopback_listener_serves_its_own_bundle(hosted: Hosted) -> None:
    """The one file that differs is the hosted listener's alone."""
    answer = await hosted.send("GET", "/door.js", loopback=True, origin=None)

    assert answer.body == b"local"


@pytest.mark.parametrize("path", ["/", "/door.js", "/session/edge", "/conversations"])
async def test_no_request_is_served_without_an_assertion(hosted: Hosted, path: str) -> None:
    """§7:1: the assertion is checked before anything — the assets and the exchange
    included."""
    method = "GET" if path in {"/", "/door.js"} else "POST"

    answer = await hosted.send(method, path, assertion=None)

    assert _refusal(answer) == _DOOR_REFUSED


def _faulty(one: Hosted) -> dict[str, str | tuple[str, ...] | None]:
    """One request's assertion per §7:7 condition, each wrong in that one way."""
    good = one.assertion()
    return {
        "assertion-absent": None,
        "assertion-malformed": "not.a.jws!",
        "assertion-signature": FakeEdge().sign(one.clock()),
        "assertion-issuer": one.assertion(iss="https://elsewhere.example"),
        "assertion-audience": one.assertion(aud="another-hub"),
        "assertion-subject": one.assertion(sub="the-operators-account"),
        "assertion-times": one.assertion(lifetime=3600),
        "repeated": (good, good),
    }


async def test_every_door_refusal_is_one_refusal_and_the_record_names_the_check(
    hosted: Hosted,
) -> None:
    """§7:6: "refused with one refusal, the same whichever of those checks it failed",
    carrying nothing about which — and §7:7: the record "names which check failed"."""
    answers: list[Answer] = []
    with structlog.testing.capture_logs() as records:
        for token in _faulty(hosted).values():
            answers.append(await hosted.send("GET", "/", origin=None, assertion=token))
        answers.append(await hosted.send("GET", "/", origin=None, host="elsewhere.example"))
        answers.append(await hosted.send("GET", "/", origin="https://elsewhere.example"))
        answers.append(await hosted.send("GET", "/", origin=f"http://{DOOR}"))
        hosted.gateway.close()

    assert {(one.status, one.body) for one in answers} == {(answers[0].status, answers[0].body)}
    assert _refusal(answers[0]) == _DOOR_REFUSED
    conditions = {
        record["condition"]: record["count"] for record in records if "condition" in record
    }
    assert conditions == {
        # The repeated header is §6:1's "carries no assertion".
        "assertion-absent": 2,
        "assertion-malformed": 1,
        "assertion-signature": 1,
        "assertion-issuer": 1,
        "assertion-audience": 1,
        "assertion-subject": 1,
        "assertion-times": 1,
        "host-not-bound": 1,
        "origin-not-own": 2,
    }


async def test_the_assertion_is_checked_before_the_host(hosted: Hosted) -> None:
    """§7:1: "before ADR-0168 §7's ``Host`` and ``Origin`` checks" — so a request
    failing both is recorded on the assertion."""
    with structlog.testing.capture_logs() as records:
        await hosted.send("GET", "/", assertion=None, host="elsewhere.example")
        hosted.gateway.close()

    assert [record["condition"] for record in records if "condition" in record] == [
        "assertion-absent"
    ]


async def test_a_door_refusal_says_nothing_of_a_live_session(hosted: Hosted) -> None:
    """§7:1: "refused without the session being consulted, and its refusal discloses
    nothing about whether a session exists"."""
    session = await hosted.exchange()

    with_session = await hosted.listing(session, assertion=None)
    without = await hosted.listing(None, assertion=None)

    assert (with_session.status, with_session.body) == (without.status, without.body)
    assert _refusal(with_session) == _DOOR_REFUSED


async def test_an_assertion_for_another_account_is_refused(hosted: Hosted) -> None:
    """§13:1: the door admits this hub's owner and no other account — the operator's
    own included."""
    answer = await hosted.send("GET", "/", origin=None, assertion=hosted.assertion(sub="operator"))

    assert _refusal(answer) == _DOOR_REFUSED


async def test_an_assertion_that_lapsed_is_refused_on_the_next_request(hosted: Hosted) -> None:
    """§6:10 with no leeway: the gateway's clock moving past ``exp`` refuses it."""
    token = hosted.assertion(lifetime=30)
    hosted.clock.advance(timedelta(seconds=30))

    answer = await hosted.send("GET", "/", origin=None, assertion=token)

    assert _refusal(answer) == _DOOR_REFUSED


# --- §8: the exchange --------------------------------------------------------------


async def test_the_exchange_mints_a_session_with_a_host_prefixed_secure_cookie(
    hosted: Hosted,
) -> None:
    """§8:1, §8:2, §8:5: two session values, nothing else, and the cookie half
    ``__Host-`` named and ``Secure`` beside every attribute ADR-0168 §6:2 requires."""
    answer = await hosted.send("POST", "/session/edge")

    assert answer.status == 200
    assert set(answer.payload) == {"header_half"}
    cookie = answer.header("set-cookie")
    assert cookie is not None
    name, _, rest = cookie.partition("=")
    assert name == "__Host-assistant_session"
    attributes = {part.strip() for part in rest.split(";")[1:]}
    assert attributes == {"HttpOnly", "SameSite=Strict", "Path=/", "Secure"}


async def test_an_exchange_with_a_body_is_refused(hosted: Hosted) -> None:
    """§8:1: "A request to it with a body … is refused" — as a failed exchange, which
    "discloses only that it failed" (§8:2)."""
    answer = await hosted.send("POST", "/session/edge", body=b'{"bootstrap_value":"x"}')

    assert answer.status == 400
    assert answer.payload == {"fault": "bootstrap-exchange-failed"}
    assert answer.header("set-cookie") is None


async def test_an_exchange_with_no_origin_is_refused(hosted: Hosted) -> None:
    """§8:1: "or with no ``Origin``". §7:3 lets an absent `Origin` by; the exchange is
    the one request that must carry it."""
    answer = await hosted.send("POST", "/session/edge", origin=None)

    assert answer.payload == {"fault": "bootstrap-exchange-failed"}


async def test_the_hosted_listener_serves_no_bootstrap_exchange(hosted: Hosted) -> None:
    """§8:3: "A bootstrap value is exchangeable on the loopback listener and on the
    remote browser listener … and on no other." The value is not read, so it is not
    spent: the loopback listener still takes it."""
    value = bootstrap_value(hosted.gateway)
    body = json.dumps({"bootstrap_value": value}).encode()

    refused = await hosted.send("POST", "/session", body=body)
    spent = await hosted.send("POST", "/session", body=body, loopback=True, origin=None)

    assert refused.payload == {"fault": "no-live-session"}
    assert refused.header("set-cookie") is None
    assert spent.status == 200


async def test_no_other_listener_serves_the_edges_exchange(hosted: Hosted) -> None:
    """The exchange is the hosted listener's alone: on the loopback listener its path
    is a request with no session like any other."""
    answer = await hosted.send("POST", "/session/edge", loopback=True, origin=None)

    assert answer.payload == {"fault": "no-live-session"}


async def test_a_mint_is_recorded_with_no_device_and_nothing_of_the_edge(hosted: Hosted) -> None:
    """§7:8: only ADR-0168 §6:11's Tier 2 facts. The hosted listener has no attested
    overlay identity to record, and the subject is never one."""
    with structlog.testing.capture_logs() as records:
        await hosted.exchange()

    mints = [record for record in records if record.get("outcome", "").startswith("session")]
    assert mints == [
        {
            "event": "gateway.admission",
            "log_level": "info",
            "instant": _NOW.isoformat(),
            "request_class": "bootstrap-exchange",
            "outcome": "session-minted",
        }
    ]


# --- §7:5, §7:7: two facts, and the session's own refusals ----------------------------


async def test_a_request_with_both_facts_is_admitted_as_the_hosted_device(hosted: Hosted) -> None:
    """§7:5 and §10:2: admitted on an assertion and a live session, and relayed naming
    the hosted browser device."""
    session = await hosted.exchange()

    answer = await hosted.listing(session)

    assert answer.status == 200, answer.body
    assert hosted.engine.relayed_for == [HOSTED_DEVICE]


async def test_a_session_alone_does_not_admit(hosted: Hosted) -> None:
    """§7:5: "Neither fact admits a request on its own" — a session without the edge's
    assertion is the door refusing."""
    session = await hosted.exchange()

    assert _refusal(await hosted.listing(session, assertion=None)) == _DOOR_REFUSED
    assert hosted.engine.relayed_for == []


async def test_an_assertion_alone_does_not_admit(hosted: Hosted) -> None:
    """§7:5 and §7:7: an assertion without a session is ADR-0168 §3:2's absent session,
    which is not the door's refusal — the page tells the two apart (§11)."""
    answer = await hosted.listing(None)

    assert (answer.status, answer.payload) == (401, {"fault": "no-live-session"})


async def test_a_cookie_half_that_does_not_match_is_its_own_fault(hosted: Hosted) -> None:
    """§7:7: ADR-0168 §6:4's distinct fault, unchanged."""
    _, header = await hosted.exchange()

    answer = await hosted.listing(("not-the-cookie-half", header))

    assert (answer.status, answer.payload) == (409, {"fault": "cookie-half-mismatch"})


async def test_a_cookie_without_its_host_prefix_is_not_the_hosted_cookie(hosted: Hosted) -> None:
    """§8:5: the hosted listener reads its ``__Host-`` cookie and no other, so the same
    value under the loopback listener's name is no cookie half at all."""
    cookie, header = await hosted.exchange()

    answer = await hosted.send(
        "POST",
        "/conversations",
        body=b"{}",
        extra=(f"Cookie: assistant_session={cookie}", f"X-Assistant-Session: {header}"),
    )

    assert answer.payload == {"fault": "cookie-half-mismatch"}


async def test_a_hosted_session_does_not_admit_on_the_loopback_listener(hosted: Hosted) -> None:
    """§10:2: a hosted session's browser is the hosted device, so on the loopback
    listener — where a browser is the gateway's own machine — it is no session."""
    session = await hosted.exchange()

    answer = await hosted.listing(session, loopback=True, origin=None)

    assert answer.payload == {"fault": "no-live-session"}


async def test_a_loopback_session_does_not_admit_on_the_hosted_listener(hosted: Hosted) -> None:
    """And the converse: a session minted for the gateway's own machine never acts as
    the hosted device."""
    session = await hosted.loopback_session()

    answer = await hosted.listing(session)

    assert answer.payload == {"fault": "no-live-session"}


# --- §8:6, §8:7: the ceiling ends that listener's oldest --------------------------------


async def test_an_exchange_at_the_ceiling_ends_the_oldest_hosted_session() -> None:
    """§8:6: "ends the oldest live session minted through the hosted listener, then
    mints", and §8:7: the mint record says so."""
    async with _hosted(gateway_max_sessions=2) as one:
        oldest = await one.exchange()
        newer = await one.exchange()
        with structlog.testing.capture_logs() as records:
            newest = await one.exchange()

        assert (await one.listing(oldest)).payload == {"fault": "no-live-session"}
        assert (await one.listing(newer)).status == 200
        assert (await one.listing(newest)).status == 200
        outcomes = [record["outcome"] for record in records if "outcome" in record]
        assert outcomes == ["session-minted-ending-oldest"]


async def test_the_ceiling_never_ends_a_session_another_listener_minted() -> None:
    """§8:6: "No session minted through another listener is ever ended by it" — the
    hosted one goes, the loopback one stays."""
    async with _hosted(gateway_max_sessions=2) as one:
        local = await one.loopback_session()
        hosted_session = await one.exchange()
        await one.exchange()

        assert (await one.listing(local, loopback=True, origin=None)).status == 200
        assert (await one.listing(hosted_session)).payload == {"fault": "no-live-session"}


async def test_an_exchange_at_a_ceiling_of_other_listeners_sessions_is_refused() -> None:
    """§8:6: "Where no live session was minted through it, the exchange is refused as
    ADR-0182 §4:2 rules" — recorded as the ceiling and answered as a failed exchange."""
    async with _hosted(gateway_max_sessions=1) as one:
        local = await one.loopback_session()
        with structlog.testing.capture_logs() as records:
            answer = await one.send("POST", "/session/edge")
            one.gateway.close()

        assert answer.payload == {"fault": "bootstrap-exchange-failed"}
        assert [record["condition"] for record in records if "condition" in record] == [
            "session-ceiling"
        ]
        del local


async def test_a_session_the_ceiling_ended_is_gone_from_the_table() -> None:
    """The ending §8:6 makes is a session's ordinary ending, announced to whatever
    holds a stream on it (ADR-0175 §7) — so the table forgets it entirely."""
    async with _hosted(gateway_max_sessions=1) as one:
        await one.exchange()
        await one.exchange()

        assert len(one.gateway._sessions) == 1


# --- §12: what stays refused ----------------------------------------------------------


@pytest.mark.parametrize("path", ["/connection/connect", "/connection/reprovision"])
async def test_credential_entry_is_refused_through_the_door(hosted: Hosted, path: str) -> None:
    """§12:1: "``connect_account`` and ``reprovision_account`` are not admitted … on a
    condition of its own, naming that credential entry is available on a loopback
    origin only"."""
    session = await hosted.exchange()

    answer = await hosted.send("POST", path, body=b'{"credential":"s3cret"}', session=session)

    assert answer.status == 403
    assert answer.payload["fault"] == "credential-entry-loopback-only"
    assert "loopback origin only" in answer.payload["detail"]


async def test_reading_the_connections_is_admitted_through_the_door(hosted: Hosted) -> None:
    """§12:2: ``connected_accounts`` is admitted as on the remote browser listener."""
    session = await hosted.exchange()

    answer = await hosted.send("POST", "/connections", body=b"{}", session=session)

    assert answer.status == 200, answer.body


# --- §4:9: no store, no transform ------------------------------------------------------


async def test_every_hosted_response_asks_for_no_store_and_no_transform(hosted: Hosted) -> None:
    """§4:9: "``Cache-Control: no-store, no-transform``" on every response — a refusal
    and an asset alike."""
    served = await hosted.send("GET", "/", origin=None)
    refused = await hosted.send("GET", "/", origin=None, assertion=None)
    local = await hosted.send("GET", "/", loopback=True, origin=None)

    assert served.header("cache-control") == "no-store, no-transform"
    assert refused.header("cache-control") == "no-store, no-transform"
    assert local.header("cache-control") == "no-store"


# --- §9: the assertion is Tier 0 -------------------------------------------------------


async def test_no_assertion_or_subject_reaches_a_log_a_record_or_a_response(
    hosted: Hosted,
) -> None:
    """§9:2: written to no log or audit record, no error or diagnostic, and placed in no
    response; §7:8: no record carries "an assertion, any part or claim of one, or the
    subject". Every path an assertion can take through the door, at once."""
    sent: list[str] = []

    def keep(token: str) -> str:
        sent.append(token)
        return token

    with structlog.testing.capture_logs() as records:
        answers = [
            await hosted.send("GET", "/", origin=None, assertion=keep(hosted.assertion())),
            await hosted.send("POST", "/session/edge", assertion=keep(hosted.assertion())),
            await hosted.listing(None, assertion=keep(hosted.assertion())),
        ]
        for token in _faulty(hosted).values():
            if isinstance(token, str):
                answers.append(await hosted.send("GET", "/", origin=None, assertion=keep(token)))
        hosted.gateway.close()

    written = json.dumps(records, default=str) + "".join(
        one.body.decode("utf-8", "replace") + json.dumps(one.headers) for one in answers
    )
    assert SUBJECT not in written
    for token in sent:
        for part in token.split("."):
            if len(part) > 8:
                assert part not in written


async def test_an_assertion_that_verified_writes_no_record(hosted: Hosted) -> None:
    """§9:8: "No record is written for an assertion that verified." """
    with structlog.testing.capture_logs() as records:
        await hosted.send("GET", "/", origin=None)
        hosted.gateway.close()

    assert records == []


class _Holding(_Recording):
    """An engine whose listing waits until a case lets it go."""

    def __init__(self) -> None:
        """Start with the listing held."""
        super().__init__()
        self.release = asyncio.Event()
        self.occupied = asyncio.Event()

    async def recent_conversations(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[ConversationSummary, ...]:
        """Hold the request inside the engine until released."""
        self.occupied.set()
        await self.release.wait()
        return await super().recent_conversations(limit=limit, offset=offset)


def _suspended_locals() -> list[object]:
    """Every local of every gateway coroutine frame suspended in this loop.

    Down each await chain, keeping the frames of the gateway's own code: the case's own
    client holds the token it sent, which is the browser's side of the hop and not the
    gateway's custody.
    """
    found: list[object] = []
    for task in asyncio.all_tasks():
        awaited: object = task.get_coro()
        while awaited is not None:
            frame = getattr(awaited, "cr_frame", None)
            if frame is None:
                break
            if "ai_assistant/interfaces/gateway/" in frame.f_code.co_filename.replace("\\", "/"):
                found.extend(frame.f_locals.values())
            awaited = getattr(awaited, "cr_await", None)
    return found


async def test_the_assertion_is_held_only_while_it_is_checked() -> None:
    """§9:2: "The gateway holds an assertion only while it checks the request that
    carried it." With an admitted request suspended inside the engine — the longest
    an ordinary request lives — no frame holds the assertion, and no request the
    process still holds carries it (adversarial review, round 1)."""
    async with _hosted() as one:
        engine = _Holding()
        one.gateway._engine = engine
        session = await one.exchange()
        token = one.assertion()

        listing = asyncio.ensure_future(one.listing(session, assertion=token))
        await engine.occupied.wait()
        try:
            held = _suspended_locals()
            live_requests = [obj for obj in gc.get_objects() if isinstance(obj, Request)]
        finally:
            engine.release.set()
        answer = await listing

        assert answer.status == 200, answer.body
        assert held, "the suspended request's frames were found"
        for local in held:
            assert not (isinstance(local, str) and token in local), local
            if isinstance(local, Request):
                assert local.header(ASSERTION_HEADER) is None
        assert live_requests
        for request in live_requests:
            assert request.header(ASSERTION_HEADER) is None
