"""The gateway's remote browser listener, end to end (ADR-0174).

**Driven through a real socket**, for ``test_gateway.py``'s reason: half of what
ADR-0174 rules is about *connections* — which are identified before anything is
served, which are closed unread, and which door a `Host` is judged against — and
none of that is visible from a handler call.

**The listener binds ``127.0.0.2`` here, and that address is applied past the
validator.** ``Settings`` refuses a loopback address for
``gateway_remote_address`` (ADR-0174 §2), and binding a *real* overlay address is
not something a test can do; the refusal itself is pinned in
``tests/core/test_gateway_settings.py`` where the validator lives, and
``tests/service/test_remote_listener.py`` took exactly this shape for the hub's own
remote listener. What is exercised here in full is everything the refusal cannot
reach: the agent-side half of §2, §3's attested identity, §4's two facts, §6's
authorities and §8's shared ceilings.

``127.0.0.2`` rather than ``127.0.0.1`` so both listeners can be bound at once on
one ``gateway_port``, which is what §8's "totals across both listeners" needs a
test to be able to say.

**Named ``test_gateway_remote_listener``, not ``test_remote_listener``**, because
the test tree carries no packages and the hub's own remote listener already holds
the shorter name — two modules of one name is a `mypy` refusal rather than a
preference (the reason ``gateway_timing.py`` gives for not being a second
``conftest.py``).

Marked ``integration`` because loopback sockets are what they open.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
import structlog
from gateway_mint import bootstrap_value
from gateway_timing import Clock, Timers

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.interfaces.gateway.server import Gateway
from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.wire.errors import OverlayIdentityUnavailableError
from ai_assistant.wire.overlay import MAX_OVERLAY_IDENTITY_BYTES

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ai_assistant.core.types import EncodableText, Identifier, TurnOutcome

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("hermetic_assistant_env")]

#: The address the remote browser listener binds in these tests. See the module
#: docstring: a stand-in for an overlay address, applied past the validator.
_OVERLAY = "127.0.0.2"

#: Three overlay identities of the shape an agent reports — the gateway's own
#: machine, the owner's phone, and a device on the overlay the owner never listed.
_GATEWAY_NODE = "nGATEWAYCNTRL"
_PHONE = "nPHONE01CNTRL"
_STRANGER = "nSTRANGRCNTRL"

#: A name the owner may configure as an additional authority (ADR-0174 §6). It is
#: never resolved and never dialled; it only ever appears in a `Host` header.
_NAME = "phone.example.ts.net"

#: An address ``Settings`` admits — RFC 5737's TEST-NET-1 is private in
#: ``ipaddress``'s sense, so it passes all five refusals — and which no machine
#: assigns to an interface. It stands for the overlay address of a *different* node:
#: on the overlay by check 2's lights, and refused by the kernel at check 3.
_NOT_THIS_MACHINE = "192.0.2.1"

_BUNDLE = {
    "/": (b"<!doctype html><p>document", "text/html; charset=utf-8"),
    "/app.css": (b"body{}", "text/css; charset=utf-8"),
    "/app.js": (b"'use strict';", "text/javascript; charset=utf-8"),
}


@dataclass
class _FakeAgent:
    """The overlay agent on the gateway's **own** machine (ADR-0174 §3).

    **Two questions are asked of it, and it tells them apart by the address**, not
    by call order: the bind confirmation asks about the exact ``(address, port)``
    pair the listener is about to take, and every other question is a peer's. The
    two cannot collide — a connection whose source was the listener's own bound pair
    would be that socket connected to itself — and keying on order instead would let
    the fake return "yes, that address is fine" for a question about something else,
    which is the mistake adversarial review found the first version of this fake
    encoding.

    Attributes:
        bound_at: The ``(address, port)`` the listener binds, set by the harness.
        bound: Who the overlay places at ``bound_at``, or ``None`` for an agent that
            places no node there — ADR-0174 §2's physical-interface case, which is
            the one a string cannot decide.
        peers: Who the agent names for each connection in turn, consumed from the
            front. A list rather than a mapping keyed on the source port, because
            the gateway asks at accept and a test cannot learn the port before then.
        default_peer: Who it names once ``peers`` is exhausted, or ``None`` to
            refuse — §3's "a connection whose overlay identity cannot be obtained".
        asked: Every question, so a case can assert that a connection the gateway
            must not serve never reached §3's query at all.
    """

    bound_at: tuple[str, int] | None = None
    bound: str | None = _GATEWAY_NODE
    peers: list[str] = field(default_factory=list)
    default_peer: str | None = _PHONE
    asked: list[tuple[str, int]] = field(default_factory=list)

    async def identify(self, host: str, port: int) -> str:
        """Who is at ``host``, taken from this machine and never from the peer."""
        self.asked.append((host, port))
        if (host, port) == self.bound_at:
            return _named(self.bound, "the agent places no node at that address")
        found = self.peers.pop(0) if self.peers else self.default_peer
        return _named(found, "the overlay agent knows no node at that address")


class _SilentAgent(_FakeAgent):
    """An agent that is not running: it answers nothing, ever."""

    async def identify(self, host: str, port: int) -> str:
        """Refuse every question, which is what an absent daemon amounts to."""
        self.asked.append((host, port))
        msg = "the overlay agent is not running"
        raise OverlayIdentityUnavailableError(msg)


def _named(identity: str | None, refusal: str) -> str:
    """One agent answer, or the failure the seam declares."""
    if identity is None:
        raise OverlayIdentityUnavailableError(refusal)
    return identity


class _Blocking(FakeAssistantEngine):
    """An engine that holds every turn open until a test releases it."""

    def __init__(self) -> None:
        """Start with nothing released and nothing in flight."""
        super().__init__()
        self.release = asyncio.Event()
        self.occupied = asyncio.Event()

    async def converse(
        self,
        utterance: EncodableText,
        *,
        timeout: timedelta,  # noqa: ASYNC109 — the Protocol's own signature
        conversation_id: Identifier | None = None,
    ) -> TurnOutcome:
        """Occupy a hub connection until released, so the ceiling can be reached."""
        self.occupied.set()
        await self.release.wait()
        return await super().converse(utterance, timeout=timeout, conversation_id=conversation_id)


@dataclass
class Answer:
    """One parsed response."""

    status: int
    headers: dict[str, list[str]]
    body: bytes
    closed: bool

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
    """Parse one HTTP response, then see whether the peer closed."""
    head = await reader.readuntil(b"\r\n\r\n")
    lines = head.decode().split("\r\n")
    status = int(lines[0].split(" ")[1])
    headers: dict[str, list[str]] = {}
    for line in lines[1:]:
        if not line:
            continue
        name, _, value = line.partition(":")
        headers.setdefault(name.lower(), []).append(value.strip())
    length = int(headers.get("content-length", ["0"])[0])
    body = await reader.readexactly(length)
    closed = headers.get("connection", [""])[0] == "close"
    if closed:
        assert await reader.read(1) == b""
    return Answer(status=status, headers=headers, body=body, closed=closed)


@dataclass
class Remote:
    """A gateway with both listeners bound, and the pieces a case reaches into."""

    gateway: Gateway
    loopback: asyncio.Server
    remote: asyncio.Server
    settings: Settings
    agent: _FakeAgent
    engine: FakeAssistantEngine
    clock: Clock
    timers: Timers

    @property
    def authority(self) -> str:
        """The `Host` the remote listener admits for the address it bound."""
        return f"{_OVERLAY}:{self.settings.gateway_port}"

    @property
    def loopback_authority(self) -> str:
        """The `Host` the loopback listener admits, unchanged by any of this."""
        return f"127.0.0.1:{self.settings.gateway_port}"

    async def connect(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Open one connection to the remote listener."""
        return await asyncio.open_connection(_OVERLAY, self.settings.gateway_port)

    async def connect_loopback(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Open one connection to the loopback listener."""
        return await asyncio.open_connection("127.0.0.1", self.settings.gateway_port)

    async def send(
        self,
        head: str,
        body: bytes = b"",
        *,
        connection: tuple[asyncio.StreamReader, asyncio.StreamWriter] | None = None,
    ) -> Answer:
        """Send one raw request to the remote listener and read the answer back.

        Args:
            head: The request line and headers, newline-separated, without the
                trailing blank line. ``{host}`` is filled in with the bound
                authority.
            body: The request body.
            connection: An open connection to reuse, or ``None`` to open one.

        Returns:
            The parsed response.
        """
        opened = connection or await self.connect()
        reader, writer = opened
        framed = head.format(host=self.authority).replace("\n", "\r\n").encode()
        writer.write(framed + b"\r\n\r\n" + body)
        await writer.drain()
        return await _read_answer(reader)


def _free_port() -> int:
    """A port free on every local address, so both listeners can take it."""
    with socket.socket() as probe:
        probe.bind(("", 0))
        return int(probe.getsockname()[1])


def _settings(**overrides: Any) -> Settings:
    """Settings with the remote browser listener on, past the validator.

    Built with a *real* overlay address so every clause of ADR-0174 §8 that judges
    the configuration as a whole actually runs — the stranded-list refusal included —
    and only then swapped for the bindable stand-in. Constructing it at ``127.0.0.2``
    directly would skip the model's own validation of everything beside it.
    """
    settings = Settings(gateway_port=_free_port(), gateway_remote_address="100.64.0.9", **overrides)
    return settings.model_copy(update={"gateway_remote_address": _OVERLAY})


def _gateway(
    settings: Settings,
    *,
    agent: _FakeAgent | None,
    engine: FakeAssistantEngine,
    clock: Clock,
    timers: Timers,
) -> Gateway:
    """One gateway, built but nothing bound and nothing minted.

    The fake agent is pointed at the pair the listener will ask about, so its answer
    turns on the address rather than on how many questions have come before.
    """
    if agent is not None:
        agent.bound_at = (str(settings.gateway_remote_address), settings.gateway_port)
    return Gateway(
        settings=settings,
        engine=engine,
        now=clock,
        defer=timers,
        bundle=_BUNDLE,
        agent=agent,
    )


@contextlib.asynccontextmanager
async def _remote(
    *,
    agent: _FakeAgent | None = None,
    engine: FakeAssistantEngine | None = None,
    devices: tuple[str, ...] = (_PHONE,),
    **overrides: Any,
) -> AsyncIterator[Remote]:
    """Bind both listeners on one free port and tear them down afterwards."""
    settings = _settings(gateway_remote_browser_devices=devices, **overrides)
    clock, timers = Clock(), Timers()
    the_agent = agent if agent is not None else _FakeAgent()
    behind = engine or FakeAssistantEngine()
    gateway = _gateway(settings, agent=the_agent, engine=behind, clock=clock, timers=timers)
    loopback = await gateway.start()
    remote = await gateway.start_remote()
    assert remote is not None
    try:
        yield Remote(
            gateway=gateway,
            loopback=loopback,
            remote=remote,
            settings=settings,
            agent=the_agent,
            engine=behind,
            clock=clock,
            timers=timers,
        )
    finally:
        gateway.close()
        for server in (loopback, remote):
            server.close()
            with contextlib.suppress(Exception):
                await server.wait_closed()


@pytest.fixture
async def remote() -> AsyncIterator[Remote]:
    """A gateway serving one listed device over the overlay."""
    async with _remote() as one:
        yield one


async def _start_session(one: Remote) -> tuple[str, str]:
    """Exchange the bootstrap value from a listed device; return the two halves."""
    value = bootstrap_value(one.gateway)
    body = json.dumps({"bootstrap_value": value}).encode()
    answer = await one.send(
        f"POST /session HTTP/1.1\nHost: {{host}}\nContent-Length: {len(body)}\n"
        f"Content-Type: application/json",
        body,
    )
    assert answer.status == 200, answer.body
    cookie = answer.header("set-cookie")
    assert cookie is not None
    return cookie.split(";")[0].partition("=")[2], answer.payload["header_half"]


def _ask(one: Remote, *, header_half: str | None, cookie_half: str | None) -> tuple[str, bytes]:
    """Frame one `/ask` at the remote listener's own authority."""
    body = json.dumps({"utterance": "what is on today"}).encode()
    lines = [
        "POST /ask HTTP/1.1",
        "Host: {host}",
        f"Origin: http://{one.authority}",
        "Content-Type: application/json",
        f"Content-Length: {len(body)}",
    ]
    if header_half is not None:
        lines.append(f"X-Assistant-Session: {header_half}")
    if cookie_half is not None:
        lines.append(f"Cookie: assistant_session={cookie_half}")
    return "\n".join(lines), body


# --- ADR-0174 §2: off unless configured on, and the loopback listener is untouched ---


async def test_a_gateway_with_no_remote_configuration_binds_no_second_listener() -> None:
    """§2: "The remote browser listener is **off unless it is configured on**. A
    gateway with no remote-browser-listener configuration binds only ADR-0168 §2's
    loopback listener."

    The default is what almost every deployment gets, so this is the case that must
    behave byte for byte as milestone 13's gateway did — including asking its agent
    nothing, because it has none and needs none.
    """
    settings = Settings(gateway_port=_free_port())
    clock, timers = Clock(), Timers()
    gateway = _gateway(
        settings, agent=None, engine=FakeAssistantEngine(), clock=clock, timers=timers
    )

    server = await gateway.start()
    try:
        assert await gateway.start_remote() is None
        assert gateway.origins == (gateway.origin,)
    finally:
        gateway.close()
        server.close()


async def test_the_loopback_listener_is_bound_whether_or_not_the_remote_one_is(
    remote: Remote,
) -> None:
    """§2: "that loopback listener is bound whether or not this one is, under every
    clause of ADR-0168 §2 that this ADR does not supersede".

    The loopback door still serves its assets to a browser on the gateway's own
    machine with no session, no device list and no agent involved — §3's identity
    check is the remote listener's alone, and asking the agent about a loopback peer
    would be a query with no clause behind it.
    """
    asked_before = len(remote.agent.asked)
    reader, writer = await remote.connect_loopback()
    writer.write(f"GET / HTTP/1.1\r\nHost: {remote.loopback_authority}\r\n\r\n".encode())
    await writer.drain()

    answer = await _read_answer(reader)

    assert answer.status == 200
    assert answer.body == _BUNDLE["/"][0]
    assert len(remote.agent.asked) == asked_before
    writer.close()


async def test_the_loopback_authority_is_not_admitted_on_the_remote_listener(
    remote: Remote,
) -> None:
    """The two doors admit two sets of authorities, and neither leaks into the other.

    A `Host` naming ``127.0.0.1`` on the overlay door is refused under ADR-0174 §6
    exactly as an attacker's rebound name is: it is not in the set this listener
    bound.
    """
    answer = await remote.send(f"GET / HTTP/1.1\nHost: {remote.loopback_authority}")

    assert answer.status == 421
    assert answer.payload["fault"] == "host-not-bound"


async def test_every_origin_is_disclosed_so_the_owner_can_reach_the_second_door(
    remote: Remote,
) -> None:
    """Milestone 14's exit test is a phone, and the address to type into it is the
    overlay one — a disclosure naming only the loopback origin would hand the owner a
    bootstrap value and no door to spend it at."""
    assert remote.gateway.origins == (
        f"http://{remote.loopback_authority}",
        f"http://{remote.authority}",
    )


async def test_a_configured_name_is_disclosed_as_an_origin_too() -> None:
    """§6 admits a configured name as an authority, so it is one an owner can open."""
    async with _remote(gateway_remote_host_names=(_NAME,)) as one:
        assert f"http://{_NAME}:{one.settings.gateway_port}" in one.gateway.origins


# --- ADR-0174 §2 and §8: what a gateway refuses to start with -----------------


async def test_a_gateway_refuses_to_bind_an_address_the_overlay_does_not_place() -> None:
    """§2's check 2 — the physical-interface limb, which no string can decide.

    ``Settings`` admits ``192.168.1.5``, because nothing about the value says whether
    it is an overlay address or an ``eth0`` one. The agent is what knows, and §2's own
    words are that "the gateway binds an address the agent provides" — so a gateway
    whose agent places no node there stays down rather than opening a door on the LAN.

    The address here is one this machine genuinely *does* hold, so check 3 would pass
    it: this is check 2 refusing on its own ground, which is what makes the two
    independent rather than one dressed as two.
    """
    settings = _settings()
    agent = _FakeAgent(bound=None)
    gateway = _gateway(
        settings, agent=agent, engine=FakeAssistantEngine(), clock=Clock(), timers=Timers()
    )

    with pytest.raises(ConfigurationError, match="places no node there"):
        await gateway.start_remote()


async def test_a_gateway_refuses_to_bind_an_overlay_address_that_is_not_its_own() -> None:
    """§2's check 3, and the gap adversarial review found on this PR's first round.

    The agent's answer is *the overlay places a node at this address*; it is not *and
    that node is us*, because the seam a client holds asks one question where the
    hub's own asks two. So an address that is genuinely on the overlay but belongs to
    a **different** node passes check 2 — and it is the kernel that refuses it, with
    ``EADDRNOTAVAIL``, because an overlay assigns each node its own address.

    That errno is turned into a refusal naming §2 rather than left raw, because it is
    the one bind failure that is a statement about the configured address rather than
    about the machine's state — and the mistake it catches is a real one an owner will
    make: typing the address of the device they want to *browse from*.
    """
    settings = Settings(gateway_port=_free_port(), gateway_remote_address="100.64.0.9")
    elsewhere = settings.model_copy(update={"gateway_remote_address": _NOT_THIS_MACHINE})
    gateway = _gateway(
        elsewhere,
        agent=_FakeAgent(),
        engine=FakeAssistantEngine(),
        clock=Clock(),
        timers=Timers(),
    )

    with pytest.raises(ConfigurationError, match="not an address of this machine"):
        await gateway.start_remote()


async def test_a_gateway_refuses_to_bind_when_its_agent_is_not_answering() -> None:
    """The same refusal for the same reason, arriving as an absent daemon.

    Every connection on this listener needs §3's identity and one whose identity
    cannot be obtained is closed — so a gateway that bound this door with an agent it
    cannot reach would present an open port that refuses everything, which is exactly
    the pair of failures ADR-0168 §9 refuses to present identically.
    """
    settings = _settings()
    gateway = _gateway(
        settings,
        agent=_SilentAgent(),
        engine=FakeAssistantEngine(),
        clock=Clock(),
        timers=Timers(),
    )

    with pytest.raises(ConfigurationError, match="ASSISTANT_GATEWAY_REMOTE_ADDRESS"):
        await gateway.start_remote()


def test_a_gateway_configured_on_with_no_agent_does_not_get_built() -> None:
    """§3 makes the agent the sole source of a browsing device's identity, so a
    gateway configured on without one could admit nothing at all.

    Refused in the constructor rather than at the bind, because that is before the
    two things §8's second refusal names — nothing bound, and no bootstrap value
    minted, let alone disclosed.
    """
    settings = _settings()

    with pytest.raises(ConfigurationError, match="no agent was supplied"):
        _gateway(settings, agent=None, engine=FakeAssistantEngine(), clock=Clock(), timers=Timers())


def test_a_listed_device_over_the_byte_bound_is_refused_at_start() -> None:
    """§8's half of the split identity check, "reading the constant the wire seam
    owns" rather than restating it in ``core``.

    An identity over the bound is one no overlay this system accepts produces, so it
    could never equal an identity the agent reports — and without this the owner's
    named device would be refused at every exchange with nothing saying why.
    """
    settings = _settings(gateway_remote_browser_devices=("n" * (MAX_OVERLAY_IDENTITY_BYTES + 1),))

    with pytest.raises(ConfigurationError, match="over the 128"):
        _gateway(
            settings,
            agent=_FakeAgent(),
            engine=FakeAssistantEngine(),
            clock=Clock(),
            timers=Timers(),
        )


def test_an_identity_at_the_byte_bound_is_admitted() -> None:
    """The refusal narrows nothing legitimate: the bound is "at most", not "under"."""
    listed = "n" * MAX_OVERLAY_IDENTITY_BYTES

    gateway = _gateway(
        _settings(gateway_remote_browser_devices=(listed,)),
        agent=_FakeAgent(),
        engine=FakeAssistantEngine(),
        clock=Clock(),
        timers=Timers(),
    )

    assert gateway.origins


def test_a_loopback_only_gateway_is_not_held_to_any_of_it() -> None:
    """None of §8's start-time refusals reaches a gateway with no remote listener.

    The clauses are conditioned on ``gateway_remote_address`` being set, so a
    milestone-13 deployment builds exactly as it did — with no agent, and with the
    ``Settings`` model refusing a device list it could never read anyway.
    """
    gateway = _gateway(
        Settings(gateway_port=_free_port()),
        agent=None,
        engine=FakeAssistantEngine(),
        clock=Clock(),
        timers=Timers(),
    )

    assert gateway.origins == (gateway.origin,)


# --- ADR-0174 §3: the identity is obtained, and taken from nothing asserted ---


async def test_the_device_is_identified_before_anything_is_served(remote: Remote) -> None:
    """§3: "Before serving anything on the remote browser listener — a static asset
    and the bootstrap exchange included — the gateway obtains the connecting device's
    overlay identity from the overlay agent running on the gateway's **own** machine".

    The asset is the weakest request there is, and it is still behind the query: one
    question per connection, asked before a byte of the request was read.
    """
    asked_before = len(remote.agent.asked)

    answer = await remote.send("GET /app.css HTTP/1.1\nHost: {host}")

    assert answer.status == 200
    assert len(remote.agent.asked) == asked_before + 1


async def test_a_connection_whose_identity_cannot_be_obtained_is_closed_unread() -> None:
    """§3: "A connection whose overlay identity cannot be obtained is refused and
    closed."

    Nothing is written back, because the gateway has not read a request and so has
    nothing to answer — a status line here would be a response to a request that does
    not exist.
    """
    async with _remote(agent=_FakeAgent(default_peer=None)) as one:
        reader, writer = await one.connect()

        assert await asyncio.wait_for(reader.read(), timeout=5) == b""
        writer.close()


async def test_a_refusal_on_the_identity_records_nothing() -> None:
    """§3: a connection refused on it "reaches no clause of ADR-0168 §3, §4, §5 or §6
    at all", so it is outside §6's recorded set exactly as §8's ceilings are.

    A refusal that *did* record would hand a peer that cannot be named a way to drive
    the record stream, which is the population the rate bound cannot key on.
    """
    async with _remote(agent=_FakeAgent(default_peer=None)) as one:
        with structlog.testing.capture_logs() as records:
            reader, writer = await one.connect()
            assert await asyncio.wait_for(reader.read(), timeout=5) == b""
            writer.close()
            one.gateway.close()

        assert [record for record in records if record["event"] == "gateway.admission"] == []


async def test_the_identity_is_the_agents_and_never_a_header_the_peer_sets() -> None:
    """§3: the gateway "may not take that identity from anything the peer asserts — a
    header, a cookie, a query parameter, a request body".

    The peer here announces itself as the listed device in every way a request can,
    and the agent says otherwise. The agent wins, which is ADR-0124 §4's rule arriving
    at the third door of this system to face it.
    """
    async with _remote(agent=_FakeAgent(default_peer=_STRANGER)) as one:
        answer = await one.send(
            f"POST /session HTTP/1.1\nHost: {{host}}\nX-Device: {_PHONE}\n"
            f"Cookie: device={_PHONE}\nContent-Length: 0"
        )

        assert answer.status == 403
        assert answer.payload["fault"] == "device-not-listed"


async def test_a_connection_refused_at_a_ceiling_never_reaches_the_agent() -> None:
    """§8's ceilings are ahead of §3's query, and the ordering is deliberate.

    A ceiling refusal *serves* nothing — "it refuses to accept a further connection
    rather than queueing it" — so asking the agent about a connection the gateway is
    closing unread would put a local query on the one path a flood can drive.
    """
    async with _remote(
        gateway_max_browser_connections=1,
        gateway_max_pending_connections=1,
        gateway_read_timeout=timedelta(seconds=5),
    ) as one:
        held_reader, held_writer = await one.connect()
        # The handler registers the connection on the loop's next turn, and the
        # ceiling is about connections the gateway is *holding* — so the second dial
        # has to come after that, not merely after the TCP handshake.
        await asyncio.sleep(0.05)
        asked_before = len(one.agent.asked)

        reader, writer = await one.connect()

        assert await asyncio.wait_for(reader.read(), timeout=5) == b""
        assert len(one.agent.asked) == asked_before
        assert held_reader is not None
        held_writer.close()
        writer.close()


# --- ADR-0174 §4: two facts, and only the assets on membership alone ---------


async def test_the_assets_are_served_to_any_device_of_the_overlay() -> None:
    """§4: "The front end's own **static assets** are served to any device of the
    overlay the gateway's agent serves."

    They are "the bundle this repository ships to anyone who installs it", so an
    overlay member obtains from them nothing they could not obtain from the
    distribution — and listing a device before it may fetch a stylesheet would be
    ceremony consuming a decision nobody asked for.
    """
    async with _remote(agent=_FakeAgent(default_peer=_STRANGER)) as one:
        answer = await one.send("GET /app.js HTTP/1.1\nHost: {host}")

        assert answer.status == 200
        assert answer.body == _BUNDLE["/app.js"][0]


async def test_a_bootstrap_exchange_from_an_unlisted_device_is_refused() -> None:
    """§4: "a bootstrap exchange arriving from any other overlay identity is refused
    without the value being read, compared or consumed".

    This is the clause that stops a hostile overlay member phishing a value from a
    mistyped address and spending it from its own device — the attack adversarial
    review found in the draft that served both pre-session exceptions on membership
    alone.
    """
    async with _remote(agent=_FakeAgent(default_peer=_STRANGER)) as one:
        value = bootstrap_value(one.gateway)
        body = json.dumps({"bootstrap_value": value}).encode()

        answer = await one.send(
            f"POST /session HTTP/1.1\nHost: {{host}}\nContent-Length: {len(body)}",
            body,
        )

        assert answer.status == 403
        assert answer.payload["fault"] == "device-not-listed"


async def test_a_value_refused_at_an_unlisted_device_is_not_consumed() -> None:
    """ "Without the value being read, compared or **consumed**" — the last word is
    the one with teeth.

    ADR-0168 §5 makes a value "exchangeable for exactly one **session**", and a
    gateway that spent it on the attacker's refused attempt would have left the owner
    holding a value that no longer works, with nothing saying why.
    """
    async with _remote(agent=_FakeAgent(peers=[_STRANGER], default_peer=_PHONE)) as one:
        value = bootstrap_value(one.gateway)
        body = json.dumps({"bootstrap_value": value}).encode()
        head = f"POST /session HTTP/1.1\nHost: {{host}}\nContent-Length: {len(body)}"
        assert (await one.send(head, body)).status == 403

        answer = await one.send(head, body)

        assert answer.status == 200
        assert answer.payload["header_half"]


async def test_a_listed_device_exchanges_and_then_reaches_the_assistant(
    remote: Remote,
) -> None:
    """§4's two facts held together, which is the whole path the exit test walks."""
    cookie_half, header_half = await _start_session(remote)

    head, body = _ask(remote, header_half=header_half, cookie_half=cookie_half)
    answer = await remote.send(head, body)

    assert answer.status == 200
    assert remote.engine.calls
    assert answer.payload["outcome"]["conversation_id"]


async def test_a_session_alone_does_not_admit_an_unlisted_device() -> None:
    """§4: "Neither fact admits a request on its own."

    The session here is genuinely live and genuinely this gateway's — it was minted
    for the owner's own phone — and the request arrives from a device the owner never
    listed. ADR-0168 §4's sole-admitter clause would have admitted it, which is why
    ADR-0174 §12 records that clause as partially superseded rather than added to.
    """
    agent = _FakeAgent(peers=[_PHONE], default_peer=_STRANGER)
    async with _remote(agent=agent) as one:
        cookie_half, header_half = await _start_session(one)

        head, body = _ask(one, header_half=header_half, cookie_half=cookie_half)
        answer = await one.send(head, body)

        assert answer.status == 403
        assert answer.payload["fault"] == "device-not-listed"
        assert one.engine.calls == []


async def test_a_listed_device_without_a_session_is_still_refused(remote: Remote) -> None:
    """The other half of "neither fact admits a request on its own"."""
    head, body = _ask(remote, header_half=None, cookie_half=None)

    answer = await remote.send(head, body)

    assert answer.status == 401
    assert answer.payload["fault"] == "no-live-session"
    assert remote.engine.calls == []


async def test_an_empty_device_list_means_no_device_may_exchange() -> None:
    """§8: "Empty is the default and means **no device may exchange**, so a gateway
    configured on serves its assets and mints no remote session until the owner names
    a device."
    """
    async with _remote(devices=()) as one:
        assert (await one.send("GET / HTTP/1.1\nHost: {host}")).status == 200

        value = bootstrap_value(one.gateway)
        body = json.dumps({"bootstrap_value": value}).encode()
        answer = await one.send(
            f"POST /session HTTP/1.1\nHost: {{host}}\nContent-Length: {len(body)}", body
        )

        assert answer.status == 403


async def test_a_listed_device_is_matched_whole_and_never_by_prefix() -> None:
    """§8: "no element is matched by prefix, suffix, pattern or any form of partial
    comparison"."""
    async with _remote(devices=(_PHONE,), agent=_FakeAgent(default_peer=_PHONE[:-1])) as one:
        value = bootstrap_value(one.gateway)
        body = json.dumps({"bootstrap_value": value}).encode()

        answer = await one.send(
            f"POST /session HTTP/1.1\nHost: {{host}}\nContent-Length: {len(body)}", body
        )

        assert answer.status == 403


# --- ADR-0174 §6: `Host` and `Origin` on a listener that is not loopback ------


async def test_the_bound_address_is_admitted_as_a_host(remote: Remote) -> None:
    """§6's first authority: "the overlay address it bound, with the port it bound"."""
    assert (await remote.send("GET / HTTP/1.1\nHost: {host}")).status == 200


async def test_a_configured_name_is_admitted_as_a_host() -> None:
    """§6's second: "a name the owner configured in ``gateway_remote_host_names``,
    with that port".

    The phone is what decides this. "An owner typing an address into a laptop's URL
    bar reads it out of ``tailscale status`` once; an owner typing one into a phone
    does it on a soft keyboard, repeatedly, and will reach for the MagicDNS name."
    """
    async with _remote(gateway_remote_host_names=(_NAME,)) as one:
        reader, writer = await one.connect()
        authority = f"{_NAME}:{one.settings.gateway_port}"
        writer.write(f"GET / HTTP/1.1\r\nHost: {authority}\r\n\r\n".encode())
        await writer.drain()

        answer = await _read_answer(reader)

        assert answer.status == 200
        writer.close()


async def test_a_name_the_owner_did_not_configure_is_refused(remote: Remote) -> None:
    """§6's reason survives whole: "rebinding is a property of the attacker's own name
    rather than of the target", so the attacker's name is refused because it is not in
    the owner's set — one step before the session logic, exactly as ADR-0168 §7 has
    it."""
    reader, writer = await remote.connect()
    writer.write(
        f"GET / HTTP/1.1\r\nHost: evil.example:{remote.settings.gateway_port}\r\n\r\n".encode()
    )
    await writer.drain()

    answer = await _read_answer(reader)

    assert answer.status == 421
    assert answer.payload["fault"] == "host-not-bound"


async def test_the_bound_address_at_the_wrong_port_is_refused(remote: Remote) -> None:
    """ "With the port it bound" — the authority is the pair, not the address."""
    reader, writer = await remote.connect()
    writer.write(f"GET / HTTP/1.1\r\nHost: {_OVERLAY}:1\r\n\r\n".encode())
    await writer.drain()

    answer = await _read_answer(reader)

    assert answer.status == 421


async def test_an_origin_that_is_not_this_requests_own_authority_is_refused() -> None:
    """§6: "an ``Origin`` that is not the origin of the authority its own ``Host``
    header named".

    The second admitted authority is the case worth pinning: a page loaded at the
    configured name is a different origin from one loaded at the bound address, and a
    gateway comparing against a single origin would either refuse one of its own pages
    or admit a cross-origin request between them.
    """
    async with _remote(gateway_remote_host_names=(_NAME,)) as one:
        answer = await one.send(
            f"GET / HTTP/1.1\nHost: {{host}}\nOrigin: http://{_NAME}:{one.settings.gateway_port}"
        )

        assert answer.status == 403
        assert answer.payload["fault"] == "origin-not-own"


async def test_the_requests_own_origin_is_admitted(remote: Remote) -> None:
    """The discriminating half, and the ordinary case a front end produces."""
    answer = await remote.send(f"GET / HTTP/1.1\nHost: {{host}}\nOrigin: http://{remote.authority}")

    assert answer.status == 200


async def test_no_cross_origin_header_is_ever_sent(remote: Remote) -> None:
    """ADR-0168 §7, unchanged by a second listener: the gateway "sends no cross-origin
    resource sharing header and honours no preflight"."""
    answer = await remote.send("GET / HTTP/1.1\nHost: {host}")

    assert not [name for name in answer.headers if name.startswith("access-control-")]


async def test_the_content_security_policy_is_origin_relative(remote: Remote) -> None:
    """ADR-0174 §5: the CSP's rule is unchanged and "the origin it names is now
    whichever authority §6 below admits the request on".

    ``'self'`` is what makes that true with no arithmetic: a policy naming a literal
    loopback origin would forbid the page's own assets on this listener.
    """
    answer = await remote.send("GET / HTTP/1.1\nHost: {host}")

    policy = answer.header("content-security-policy") or ""
    assert "script-src 'self'" in policy
    assert "127.0.0.1" not in policy


# --- ADR-0174 §8: the ceilings are the gateway's, not each listener's ---------


async def test_one_connection_ceiling_spans_both_listeners() -> None:
    """§8: "a connection on either listener counts against the same figure".

    ADR-0124 §7 spent a clause on exactly this because "a second listener is the
    natural place to double a budget by accident", and its validation plan names the
    failure as one "every other step here would still pass": an implementation that
    gives each listener its own counter.
    """
    async with _remote(
        gateway_max_browser_connections=1,
        gateway_max_pending_connections=1,
        gateway_read_timeout=timedelta(seconds=5),
    ) as one:
        held_reader, held_writer = await one.connect_loopback()
        # The handler registers the connection on the loop's next turn, so the second
        # dial has to come after that rather than merely after the TCP handshake.
        await asyncio.sleep(0.05)

        reader, writer = await one.connect()

        assert await asyncio.wait_for(reader.read(), timeout=5) == b""
        assert held_reader is not None
        held_writer.close()
        writer.close()


async def test_one_session_ceiling_spans_both_listeners() -> None:
    """§8: "a session minted through either counts against the same ceiling".

    One mint per gateway process (ADR-0168 §5) already makes the second exchange
    impossible, so what this pins is that the *table* is one — the session the remote
    listener minted is the session the loopback listener admits, and the ceiling
    counts it once.
    """
    async with _remote(gateway_max_sessions=1) as one:
        cookie_half, header_half = await _start_session(one)

        reader, writer = await one.connect_loopback()
        body = json.dumps({"utterance": "hello"}).encode()
        head = (
            f"POST /ask HTTP/1.1\r\nHost: {one.loopback_authority}\r\n"
            f"Origin: http://{one.loopback_authority}\r\n"
            f"X-Assistant-Session: {header_half}\r\n"
            f"Cookie: assistant_session={cookie_half}\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n"
        )
        writer.write(head.encode() + body)
        await writer.drain()

        assert (await _read_answer(reader)).status == 200
        writer.close()


async def test_one_hub_connection_ceiling_spans_both_listeners() -> None:
    """§8: "the gateway's hub connections are counted once across both".

    A turn held open on the overlay door occupies the gateway's only hub connection,
    and the loopback door then refuses one naming the limit rather than opening a
    second — which is the whole of "a second listener is the natural place to double
    a budget by accident".
    """
    engine = _Blocking()
    async with _remote(engine=engine, gateway_max_hub_connections=1) as one:
        cookie_half, header_half = await _start_session(one)
        head, body = _ask(one, header_half=header_half, cookie_half=cookie_half)
        held = asyncio.create_task(one.send(head, body))
        await asyncio.wait_for(engine.occupied.wait(), timeout=5)

        reader, writer = await one.connect_loopback()
        second = json.dumps({"utterance": "and now"}).encode()
        writer.write(
            (
                f"POST /ask HTTP/1.1\r\nHost: {one.loopback_authority}\r\n"
                f"Origin: http://{one.loopback_authority}\r\n"
                f"X-Assistant-Session: {header_half}\r\n"
                f"Cookie: assistant_session={cookie_half}\r\n"
                f"Content-Type: application/json\r\nContent-Length: {len(second)}\r\n\r\n"
            ).encode()
            + second
        )
        await writer.drain()
        answer = await _read_answer(reader)

        assert answer.status == 503
        assert answer.payload["limit"] == "gateway_max_hub_connections"
        engine.release.set()
        assert (await asyncio.wait_for(held, timeout=5)).status == 200
        writer.close()


async def test_the_request_bound_binds_a_request_on_either_listener() -> None:
    """§8: "``gateway_read_timeout`` and ``gateway_max_request_bytes`` bind a
    connection and a request on either listener identically"."""
    async with _remote(gateway_max_request_bytes=200) as one:
        body = b"x" * 500

        answer = await one.send(
            f"POST /ask HTTP/1.1\nHost: {{host}}\nContent-Length: {len(body)}", body
        )

        assert answer.status == 413
        assert answer.payload == {
            "fault": "request-too-large",
            "limit": "gateway_max_request_bytes",
        }
        assert one.engine.calls == []


async def test_an_asset_leaves_a_remote_connection_unadmitted(remote: Remote) -> None:
    """§8's admitted-versus-unadmitted rule, "read with §4 above": a connection is
    admitted "from the moment it carries a request admitted under §4".

    An asset is served on membership alone and carries no session, so it is not a
    request §4 admitted — and an unadmitted connection is closed once its response is
    complete, whatever the response was. A gateway that counted an asset as admission
    would hand any overlay member a connection it could hold indefinitely.
    """
    answer = await remote.send("GET / HTTP/1.1\nHost: {host}")

    assert answer.status == 200
    assert answer.closed


async def test_the_one_bootstrap_value_is_the_gateways_and_not_each_listeners(
    remote: Remote,
) -> None:
    """ADR-0174 §9: "ADR-0168 §5 is unchanged by this ADR. A gateway process still
    mints one bootstrap value… and mints no further session after that value is
    exchanged until the process is restarted."

    Spent at the overlay door, it is spent at the loopback one too — a second value
    per listener is exactly the relaxation §9 refuses, and the cost it states is that
    "a laptop browser and a phone browser cannot both be admitted without a restart".
    """
    value = await _spend_the_bootstrap_value(remote)

    reader, writer = await remote.connect_loopback()
    body = json.dumps({"bootstrap_value": value}).encode()
    writer.write(
        (
            f"POST /session HTTP/1.1\r\nHost: {remote.loopback_authority}\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n"
        ).encode()
        + body
    )
    await writer.drain()
    answer = await _read_answer(reader)

    assert answer.status == 400
    assert answer.payload["fault"] == "bootstrap-exchange-failed"


async def _spend_the_bootstrap_value(one: Remote) -> str:
    """Exchange the one value at the overlay door, and hand it back spent."""
    value = bootstrap_value(one.gateway)
    body = json.dumps({"bootstrap_value": value}).encode()
    answer = await one.send(
        f"POST /session HTTP/1.1\nHost: {{host}}\nContent-Length: {len(body)}\n"
        f"Content-Type: application/json",
        body,
    )
    assert answer.status == 200, answer.body
    return value


async def test_one_record_interval_spans_both_listeners() -> None:
    """§8 names ``gateway_record_interval`` among the gateway's totals, and this is
    what that means in practice: one interval, one timer, one flush.

    Two refusals at two doors are two records because ADR-0174 §3 keys them on the
    device, not because there are two recorders.
    """
    async with _remote() as one:
        await one.send(f"GET / HTTP/1.1\nHost: {one.loopback_authority}")
        reader, writer = await one.connect_loopback()
        writer.write(b"GET / HTTP/1.1\r\nHost: nowhere:1\r\n\r\n")
        await writer.drain()
        await _read_answer(reader)
        writer.close()

        with structlog.testing.capture_logs() as records:
            one.timers.fire_all()

        emitted = [record for record in records if record["event"] == "gateway.admission"]
        assert len(emitted) == 2
        assert {record.get("device") for record in emitted} == {None, _PHONE}


# --- ADR-0174 §3: what the record carries ------------------------------------


async def test_a_remote_refusal_records_which_device_was_refused() -> None:
    """§3: "an owner reading a refusal learns *which of their devices* was refused",
    which ADR-0168 §6 could record no such thing about a loopback peer."""
    async with _remote(agent=_FakeAgent(default_peer=_STRANGER)) as one:
        value = bootstrap_value(one.gateway)
        body = json.dumps({"bootstrap_value": value}).encode()
        await one.send(f"POST /session HTTP/1.1\nHost: {{host}}\nContent-Length: {len(body)}", body)

        with structlog.testing.capture_logs() as records:
            one.timers.fire_all()

        emitted = [record for record in records if record["event"] == "gateway.admission"]
        assert [record["device"] for record in emitted] == [_STRANGER]
        assert emitted[0]["condition"] == "device-not-listed"


async def test_a_remote_mint_records_the_device_it_was_exchanged_from(
    remote: Remote,
) -> None:
    """The admission half of ADR-0124 §7's "each admission and each refusal with the
    device it named", arriving at the gateway's door for the first time."""
    with structlog.testing.capture_logs() as records:
        await _start_session(remote)

    minted = [record for record in records if record.get("outcome") == "session-minted"]
    assert [record["device"] for record in minted] == [_PHONE]


async def test_no_record_ever_carries_the_device_the_peer_claimed(remote: Remote) -> None:
    """The enumeration stays exclusive (ADR-0174 §12), so nothing a request carried
    reaches a record — the header the peer set included, and the path it asked for."""
    with structlog.testing.capture_logs() as records:
        await remote.send("GET /nowhere HTTP/1.1\nHost: {host}\nX-Device: whoever")
        remote.timers.fire_all()

    emitted = [record for record in records if record["event"] == "gateway.admission"]
    for record in emitted:
        assert "whoever" not in json.dumps(record)
        assert "/nowhere" not in json.dumps(record)
