"""The remote listener: where it binds, who it lets in, and what it stops writing.

The protocol half is in ``tests/wire/test_server_admission.py`` and the record's
own promises are in ``test_enrolment.py``. What is here is everything that is a
fact about *this deployment* — ADR-0124 §2's bind restriction, §4's identity from
the agent on this machine, §7's shared ceilings, and §8's expulsion — driven over
a real socket against a fake overlay agent.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
import structlog

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.service.enrolment import ENROLMENTS_FILENAME, DeviceRegistry, EnrolmentStore
from ai_assistant.service.overlay import HubOverlayIdentity, OverlayIdentityUnavailableError
from ai_assistant.service.remote import RemoteListener
from ai_assistant.service.transport import ConnectionBudget, Listener
from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.wire import HubEngineClient
from ai_assistant.wire import envelope as env
from ai_assistant.wire.errors import HubUnavailableError
from ai_assistant.wire.framing import read_frame, write_frame

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from pathlib import Path

    from ai_assistant.core.types import BeliefBand, BeliefSummary, MemoryKind

_PATIENT: Final = timedelta(seconds=5)
_FRAME: Final = 1 << 20
_MOMENT: Final = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
_HUB_ID: Final = "nHUBAAAACNTRL"
_DEVICE: Final = "nLAPTOP1CNTRL"
_STRANGER: Final = "nSTRANGRCNTRL"

#: The listener binds a loopback address in these tests, which ``Settings``
#: forbids. That refusal is ADR-0124 §2's and is pinned in ``tests/core`` where the
#: validator lives; binding a *real* overlay address is not something a test can do,
#: so the listener is handed a settings object built past the validator. The
#: agent-side half of §2 — the address must be one the agent reports — is exercised
#: here in full, which is the half a test can actually reach.
_BIND: Final = "127.0.0.1"


@dataclass
class _FakeAgent:
    """The overlay agent on this machine, as the listener uses it (ADR-0124 §4).

    Attributes:
        identity: What the agent says this machine is.
        addresses: What it says this machine's overlay addresses are.
        sequence: Who it names for each connection in turn, consumed from the front.
            A list rather than a mapping keyed on the source port, because the
            listener asks at accept and a test cannot learn the port before then —
            keying on it would make the answer a race rather than a fixture.
        default_peer: Who it names once the sequence is exhausted, or ``None`` to
            refuse — which is §4's "a connection whose overlay identity cannot be
            obtained is refused".
        available: Whether the agent answers at all.
        identified: How many peers it was asked about, so a test can assert that a
            connection the hub must not serve never reached §4's query at all.
    """

    identity: str = _HUB_ID
    addresses: frozenset[str] = frozenset({_BIND})
    sequence: list[str] = field(default_factory=list)
    default_peer: str | None = _DEVICE
    available: bool = True
    identified: int = 0

    async def hub_identity(self) -> HubOverlayIdentity:
        """What this machine is, or a refusal."""
        if not self.available:
            msg = "the overlay agent is not running"
            raise OverlayIdentityUnavailableError(msg)
        return HubOverlayIdentity(identity=self.identity, addresses=self.addresses)

    async def identify(self, host: str, port: int) -> str:
        """Who is at ``host``, taken from this machine and never from the peer."""
        del host, port
        self.identified += 1
        found = self.sequence.pop(0) if self.sequence else self.default_peer
        if found is None:
            msg = "the overlay agent knows no node at that address"
            raise OverlayIdentityUnavailableError(msg)
        return found


class _BrokenAgent(_FakeAgent):
    """An agent implementation that does not honour the seam it stands in for.

    Exactly how a leaky implementation of
    :class:`~ai_assistant.service.overlay.OverlayAgent` arrives: the Protocol
    declares one failure and this raises another, which nothing on the accept path
    is watching for.
    """

    async def identify(self, host: str, port: int) -> str:
        """Fail in a way the seam does not declare."""
        del host, port
        msg = "an agent implementation that does not honour the seam"
        raise RuntimeError(msg)


class _GatedEngine(FakeAssistantEngine):
    """An engine whose ``beliefs`` waits until the test lets it finish."""

    def __init__(self) -> None:
        """Create the two events the test drives the call with."""
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def beliefs(
        self,
        *,
        bands: Sequence[BeliefBand] | None = None,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[BeliefSummary, ...]:
        """Announce arrival, wait to be released, then answer as the fake would."""
        self.entered.set()
        await self.release.wait()
        return await super().beliefs(bands=bands, kinds=kinds, limit=limit, offset=offset)


@dataclass
class _Hub:
    """One started remote listener and the pieces a case reaches into."""

    listener: RemoteListener
    registry: DeviceRegistry
    agent: _FakeAgent
    engine: FakeAssistantEngine
    budget: ConnectionBudget


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    """Settings with the remote listener on, past the validator a test cannot satisfy."""
    settings = Settings(data_dir=tmp_path, hub_read_timeout=_PATIENT, **overrides)  # type: ignore[arg-type]
    return settings.model_copy(update={"hub_remote_address": _BIND, "hub_remote_port": 0})


@contextlib.asynccontextmanager
async def _remote(
    tmp_path: Path,
    *,
    agent: _FakeAgent | None = None,
    engine: FakeAssistantEngine | None = None,
    budget: ConnectionBudget | None = None,
    **overrides: object,
) -> AsyncIterator[_Hub]:
    """One remote listener, started on an ephemeral port and stopped after the body."""
    settings = _settings(tmp_path, **overrides)
    store = EnrolmentStore(tmp_path / ENROLMENTS_FILENAME)
    registry = DeviceRegistry(store, hub_identity=_HUB_ID)
    the_agent = agent or _FakeAgent()
    the_engine = engine or FakeAssistantEngine()
    the_budget = budget or ConnectionBudget(
        max_connections=settings.hub_max_connections,
        max_pending_handshakes=settings.hub_max_pending_handshakes,
    )
    listener = RemoteListener(
        the_engine, settings, registry=registry, agent=the_agent, budget=the_budget
    )
    await listener.start(build="test")
    listener.port = _bound_port(listener)
    try:
        yield _Hub(listener, registry, the_agent, the_engine, the_budget)
    finally:
        await listener.stop_accepting()
        await listener.aclose()
        store.close()


async def _once(predicate: Any, *, what: str) -> None:
    """Give the event loop turns until ``predicate`` holds, then stop.

    A bounded loop of bare yields rather than a sleep: accepting a connection is a
    callback the loop schedules, so a counter read on the very next line reads the
    state *before* the accept ran. The bound is what turns a broken expectation into
    a failure with a name rather than a hang.
    """
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0)
    msg = f"the loop never reached: {what}"
    raise AssertionError(msg)


def _bound_port(listener: RemoteListener) -> int:
    """Which port an ephemeral bind actually took."""
    server = listener._server  # the socket the test has to dial
    assert server is not None
    return int(server.sockets[0].getsockname()[1])


@dataclass
class _Peer:
    """A raw client speaking the ratified frames — no keyring, no client half."""

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter

    async def connect(self, credential: object | None) -> env.Envelope:
        """Send a connect frame and read whatever comes back."""
        payload: dict[str, Any] = {
            env.CONNECT_VERSION: env.PROTOCOL_VERSION,
            env.CONNECT_CLIENT: "assistant-cli",
        }
        if credential is not None:
            payload[env.CONNECT_CREDENTIAL] = credential
        await self.send(env.Envelope(kind=env.FrameKind.CONNECT, id="c-0", payload=payload))
        return await self.receive()

    async def send(self, frame: env.Envelope) -> None:
        """Write one frame."""
        await write_frame(self.writer, env.encode_envelope(frame), max_frame_bytes=_FRAME)

    async def receive(self) -> env.Envelope:
        """Read one frame."""
        body = await read_frame(
            self.reader, max_frame_bytes=_FRAME, timeout=_PATIENT, idle_timeout=_PATIENT
        )
        return env.decode_envelope(body)

    def close(self) -> None:
        """Hang up."""
        self.writer.close()


@contextlib.asynccontextmanager
async def _dialling(hub: _Hub) -> AsyncIterator[_Peer]:
    """One raw connection to the remote listener."""
    reader, writer = await asyncio.open_connection(_BIND, hub.listener.port)
    peer = _Peer(reader, writer)
    try:
        yield peer
    finally:
        peer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


# --- ADR-0124 §2: where it may bind -----------------------------------------


async def test_the_hub_refuses_to_bind_an_address_the_agent_does_not_report(
    tmp_path: Path,
) -> None:
    """ADR-0124 §2: it "may not bind… an address of a physical interface", and a
    configuration that would "is refused… rather than bound".

    This is the half a value check cannot make: a LAN address on ``eth0`` is not a
    wildcard, not loopback and not globally routable, so only the agent can say it
    is not on the overlay. The refusal is a ``ConfigurationError``, which ADR-0083
    §5 maps to a stay-down exit — restarting unchanged never succeeds.
    """
    store = EnrolmentStore(tmp_path / ENROLMENTS_FILENAME)
    try:
        listener = RemoteListener(
            FakeAssistantEngine(),
            _settings(tmp_path),
            registry=DeviceRegistry(store, hub_identity=_HUB_ID),
            agent=_FakeAgent(addresses=frozenset({"100.64.0.9"})),
            budget=ConnectionBudget(max_connections=8, max_pending_handshakes=4),
        )
        with pytest.raises(ConfigurationError, match="does not report"):
            await listener.start(build="test")
    finally:
        store.close()


async def test_the_hub_refuses_to_bind_when_the_agent_cannot_be_asked(tmp_path: Path) -> None:
    """The same clause where the agent is absent rather than disagreeing.

    Binding anyway would be the hub deciding for itself that its address is on an
    overlay it cannot see, which is the one thing §2 does not let it assume.
    """
    store = EnrolmentStore(tmp_path / ENROLMENTS_FILENAME)
    try:
        listener = RemoteListener(
            FakeAssistantEngine(),
            _settings(tmp_path),
            registry=DeviceRegistry(store, hub_identity=_HUB_ID),
            agent=_FakeAgent(available=False),
            budget=ConnectionBudget(max_connections=8, max_pending_handshakes=4),
        )
        with pytest.raises(ConfigurationError, match="could not be asked"):
            await listener.start(build="test")
    finally:
        store.close()


def test_a_listener_is_not_built_without_an_address(tmp_path: Path) -> None:
    """ADR-0124 §2: "the remote listener is off unless it is configured on".

    The hub builds none at all where the setting is unset; reaching the constructor
    without one is a wiring bug rather than a deployment state, and it says so.
    """
    store = EnrolmentStore(tmp_path / ENROLMENTS_FILENAME)
    try:
        with pytest.raises(ValueError, match="hub_remote_address"):
            RemoteListener(
                FakeAssistantEngine(),
                Settings(data_dir=tmp_path),
                registry=DeviceRegistry(store, hub_identity=_HUB_ID),
                agent=_FakeAgent(),
                budget=ConnectionBudget(max_connections=8, max_pending_handshakes=4),
            )
    finally:
        store.close()


# --- ADR-0124 §4 and §7: who gets in ----------------------------------------


async def test_an_enrolled_device_presenting_its_credential_is_served(tmp_path: Path) -> None:
    """ADR-0124 §7's admitting case, end to end over a socket.

    Every refusal below is discriminated against this: a listener that refused
    everything would satisfy them all and serve nobody, which §11's step 1 is the
    operator's version of catching.
    """
    async with _remote(tmp_path) as hub:
        minted = hub.registry.enrol(_DEVICE, now=_MOMENT)
        async with _dialling(hub) as peer:
            assert (await peer.connect(minted.credential)).kind is env.FrameKind.CONNECT_ACK
            await peer.send(
                env.Envelope(kind=env.FrameKind.REQUEST, id="r-0", payload={}, method="beliefs")
            )
            assert (await peer.receive()).kind is env.FrameKind.RESULT


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("unenrolled", env.DEVICE_NOT_ENROLLED),
        ("revoked", env.DEVICE_REVOKED),
        ("wrong", env.CREDENTIAL_REJECTED),
    ],
)
async def test_each_refusal_names_its_own_reason(case: str, code: str, tmp_path: Path) -> None:
    """ADR-0124 §7: the three are distinguished "in the error it returns and in what
    the hub logs", and §11's step 3 checks the same set on two machines.

    "Legibility wins, and it wins because §2 made the audience small."
    """
    async with _remote(tmp_path) as hub:
        minted = hub.registry.enrol(_DEVICE, now=_MOMENT)
        if case == "unenrolled":
            hub.agent.default_peer = _STRANGER
        elif case == "revoked":
            hub.registry.revoke(_DEVICE, now=_MOMENT + timedelta(minutes=1))
        credential = (
            minted.credential
            if case != "wrong"
            else hub.registry.enrol(_STRANGER, now=_MOMENT).credential
        )
        async with _dialling(hub) as peer:
            reply = await peer.connect(credential)
    assert reply.kind is env.FrameKind.ERROR
    assert reply.payload["code"] == code


async def test_a_refusal_carries_neither_the_credential_nor_the_verifier(tmp_path: Path) -> None:
    """ADR-0124 §7: a refusal "never includes the credential or the verifier in
    either" the error it returns or what the hub logs.

    Checked over the whole rendered frame rather than over one member, because a
    message that quoted "the credential you sent" would be as much a disclosure as a
    field named for it.
    """
    async with _remote(tmp_path) as hub:
        minted = hub.registry.enrol(_DEVICE, now=_MOMENT)
        wrong = hub.registry.enrol(_STRANGER, now=_MOMENT).credential
        async with _dialling(hub) as peer:
            reply = await peer.connect(wrong)
    rendered = env.encode_envelope(reply).decode()
    assert wrong not in rendered
    assert minted.credential not in rendered


async def test_a_peer_the_agent_cannot_name_is_refused_before_it_speaks(tmp_path: Path) -> None:
    """ADR-0124 §4: "a connection whose overlay identity cannot be obtained is
    refused".

    Refused *before* the handshake, which is the pre-envelope class ADR-0084 §3
    answers with a close: nothing has decoded, so there is nothing to correlate a
    typed error against, and a peer the hub cannot name is not one it can put in a
    log line either.
    """
    async with _remote(tmp_path, agent=_FakeAgent(default_peer=None)) as hub:
        hub.registry.enrol(_DEVICE, now=_MOMENT)
        async with _dialling(hub) as peer:
            assert await peer.reader.read() == b""


async def test_the_identity_comes_from_the_agent_and_never_from_the_frame(tmp_path: Path) -> None:
    """ADR-0124 §4: the hub "may not take that identity from anything the peer
    asserts".

    The peer holds a credential minted for ``_DEVICE`` and the agent says it is
    ``_STRANGER``; the agent wins, so the device is refused as unenrolled. There is
    no member in the ratified connect frame for a peer to assert an identity in —
    which is the point — so this pins that none was added and that the agent's answer
    is what the record is keyed on.
    """
    async with _remote(tmp_path, agent=_FakeAgent(default_peer=_STRANGER)) as hub:
        minted = hub.registry.enrol(_DEVICE, now=_MOMENT)
        async with _dialling(hub) as peer:
            reply = await peer.connect(minted.credential)
    assert reply.payload["code"] == env.DEVICE_NOT_ENROLLED


# --- ADR-0124 §8: revocation --------------------------------------------------


async def test_revoking_a_device_closes_the_connection_it_holds(tmp_path: Path) -> None:
    """ADR-0124 §8: "revoking a device closes any connection that device currently
    holds", and §11's step 6 is the operator's version.

    The connection is idle, which is the case a check on the request path alone
    would never reach: nothing is in flight to be refused, so only the act itself can
    end it.
    """
    async with _remote(tmp_path) as hub:
        minted = hub.registry.enrol(_DEVICE, now=_MOMENT)
        async with _dialling(hub) as peer:
            assert (await peer.connect(minted.credential)).kind is env.FrameKind.CONNECT_ACK
            hub.registry.revoke(_DEVICE, now=_MOMENT + timedelta(minutes=1))
            assert await asyncio.wait_for(peer.reader.read(), _PATIENT.total_seconds()) == b""


async def test_re_enrolling_a_connected_device_closes_its_connection(tmp_path: Path) -> None:
    """ADR-0124 §6: a re-enrolment "revokes the existing enrolment with §8's **full
    finality** — closing its connections and leaving its credential verifying against
    nothing".

    §11's step 9: "enrolling the second device again while it is enrolled and
    connected closes that connection, leaves the previous credential admitting
    nothing, and admits the new one."
    """
    async with _remote(tmp_path) as hub:
        first = hub.registry.enrol(_DEVICE, now=_MOMENT)
        async with _dialling(hub) as peer:
            assert (await peer.connect(first.credential)).kind is env.FrameKind.CONNECT_ACK
            second = hub.registry.enrol(_DEVICE, now=_MOMENT + timedelta(minutes=1))
            assert await asyncio.wait_for(peer.reader.read(), _PATIENT.total_seconds()) == b""

        async with _dialling(hub) as stale:
            assert (await stale.connect(first.credential)).payload[
                "code"
            ] == env.CREDENTIAL_REJECTED
        async with _dialling(hub) as fresh:
            assert (await fresh.connect(second.credential)).kind is env.FrameKind.CONNECT_ACK


async def test_a_revocation_during_a_request_yields_no_answer_on_that_connection(
    tmp_path: Path,
) -> None:
    """ADR-0124 §8, end to end: "the response to a request dispatched before the
    revocation… is abandoned rather than delivered".

    §11's step 7 keys its own check to exactly this schedule — "the revocation taking
    effect before the response is written" — and warns that "a run in which the
    response completed first has not exercised it". Here the engine is held inside
    the call, so the ordering is forced rather than raced for.
    """
    engine = _GatedEngine()
    async with _remote(tmp_path, engine=engine) as hub:
        minted = hub.registry.enrol(_DEVICE, now=_MOMENT)
        async with _dialling(hub) as peer:
            assert (await peer.connect(minted.credential)).kind is env.FrameKind.CONNECT_ACK
            await peer.send(
                env.Envelope(kind=env.FrameKind.REQUEST, id="r-0", payload={}, method="beliefs")
            )
            await asyncio.wait_for(engine.entered.wait(), _PATIENT.total_seconds())
            hub.registry.revoke(_DEVICE, now=_MOMENT + timedelta(minutes=1))
            engine.release.set()
            assert await asyncio.wait_for(peer.reader.read(), _PATIENT.total_seconds()) == b""


async def test_revocation_is_prospective_and_the_record_keeps_what_the_owner_decided(
    tmp_path: Path,
) -> None:
    """ADR-0124 §8: "revocation is prospective. It does not retract what the hub
    already sent to that device."

    What a test can hold of that clause is that the hub does not *try*: the answer
    already written is still in the peer's buffer after the revocation, and the
    record says what was decided and when rather than erasing the enrolment.
    """
    async with _remote(tmp_path) as hub:
        minted = hub.registry.enrol(_DEVICE, now=_MOMENT)
        async with _dialling(hub) as peer:
            assert (await peer.connect(minted.credential)).kind is env.FrameKind.CONNECT_ACK
            await peer.send(
                env.Envelope(kind=env.FrameKind.REQUEST, id="r-0", payload={}, method="beliefs")
            )
            answered = await peer.receive()
            hub.registry.revoke(_DEVICE, now=_MOMENT + timedelta(minutes=1))
            assert await asyncio.wait_for(peer.reader.read(), _PATIENT.total_seconds()) == b""
        assert answered.kind is env.FrameKind.RESULT
        ((recorded,), total) = hub.registry.enrolments()
        assert total == 1
        assert recorded.enrolled_at == _MOMENT
        assert recorded.revoked_at == _MOMENT + timedelta(minutes=1)


async def test_one_devices_revocation_leaves_another_connected(tmp_path: Path) -> None:
    """ADR-0124 §5: "revocation acts on a device".

    The discriminating half of the expulsion tests: closing every connection would
    satisfy all of them and would be an outage rather than a revocation.
    """
    agent = _FakeAgent(sequence=[_DEVICE, _STRANGER])
    async with _remote(tmp_path, agent=agent) as hub:
        laptop = hub.registry.enrol(_DEVICE, now=_MOMENT)
        phone = hub.registry.enrol(_STRANGER, now=_MOMENT)
        # Dialled one at a time and held open together: the agent names them in the
        # order they arrive, so serialising the *connects* is what makes the fixture
        # deterministic while both connections stay live for the revocation.
        async with _dialling(hub) as first:
            assert (await first.connect(laptop.credential)).kind is env.FrameKind.CONNECT_ACK
            async with _dialling(hub) as second:
                assert (await second.connect(phone.credential)).kind is env.FrameKind.CONNECT_ACK

                hub.registry.revoke(_DEVICE, now=_MOMENT + timedelta(minutes=1))
                assert await asyncio.wait_for(first.reader.read(), _PATIENT.total_seconds()) == b""

                await second.send(
                    env.Envelope(kind=env.FrameKind.REQUEST, id="r-0", payload={}, method="beliefs")
                )
                assert (await second.receive()).kind is env.FrameKind.RESULT


# --- ADR-0124 §7: the ceilings are the hub's ----------------------------------


async def test_the_remote_listener_spends_the_hubs_connection_ceiling(tmp_path: Path) -> None:
    """ADR-0124 §7: "adding it may not let the hub's total concurrent connections
    exceed ``hub_max_connections``".

    §11's step 11 is the operator's version and names the failure this catches:
    "the one an implementation fails by giving each listener its own counter, which
    every other step here would still pass". Saturated through the *remote* listener,
    refused on the *loopback* one.
    """
    budget = ConnectionBudget(max_connections=1, max_pending_handshakes=1)
    async with _remote(tmp_path, budget=budget) as hub:
        loopback = Listener(hub.engine, _settings(tmp_path), data_dir=tmp_path, budget=budget)
        await loopback.start(build="test")
        try:
            async with _dialling(hub):
                await _once(lambda: budget.serving == 1, what="the remote connection is counted")
                client = HubEngineClient(loopback.path, read_timeout=_PATIENT)
                with pytest.raises(HubUnavailableError):
                    await client.probe()
        finally:
            await loopback.stop_accepting()
            await loopback.aclose()


async def test_the_loopback_listener_spends_the_same_ceiling(tmp_path: Path) -> None:
    """The other order §11's step 11 requires: "checked in both orders,
    loopback-then-remote and remote-then-loopback".

    An implementation that shared the counter one way and not the other would pass
    the test above.
    """
    budget = ConnectionBudget(max_connections=1, max_pending_handshakes=1)
    async with _remote(tmp_path, budget=budget) as hub:
        loopback = Listener(hub.engine, _settings(tmp_path), data_dir=tmp_path, budget=budget)
        await loopback.start(build="test")
        try:
            held_reader, held_writer = await asyncio.open_unix_connection(str(loopback.path))
            try:
                await _once(lambda: budget.serving == 1, what="the loopback connection is counted")
                async with _dialling(hub) as peer:
                    assert (
                        await asyncio.wait_for(peer.reader.read(), _PATIENT.total_seconds()) == b""
                    )
            finally:
                held_writer.close()
                with contextlib.suppress(Exception):
                    await held_writer.wait_closed()
                del held_reader
        finally:
            await loopback.stop_accepting()
            await loopback.aclose()


async def test_a_pending_handshake_on_the_remote_listener_counts_against_the_hubs_figure(
    tmp_path: Path,
) -> None:
    """ADR-0124 §7: "a connection awaiting admission on the remote listener counts
    against ``hub_max_pending_handshakes``", which §11's step 11 checks "for both
    figures".

    The remote listener is where an unauthenticated peer first becomes possible at
    all, so this is the figure that most needs to be the hub's: a peer that connects
    and never sends is the cheapest state for a misbehaving one to accumulate.
    """
    budget = ConnectionBudget(max_connections=8, max_pending_handshakes=1)
    async with _remote(tmp_path, budget=budget) as hub:
        loopback = Listener(hub.engine, _settings(tmp_path), data_dir=tmp_path, budget=budget)
        await loopback.start(build="test")
        try:
            async with _dialling(hub):
                await _once(
                    lambda: budget.handshaking == 1, what="the pending handshake is counted"
                )
                client = HubEngineClient(loopback.path, read_timeout=_PATIENT)
                with pytest.raises(HubUnavailableError):
                    await client.probe()
        finally:
            await loopback.stop_accepting()
            await loopback.aclose()


async def test_an_admitted_connection_frees_the_pending_slot(tmp_path: Path) -> None:
    """The discriminating half: a pending ceiling that never settled would silently
    become the connection ceiling.

    Same ceiling, same held connection, opposite answers, and the handshake is the
    only difference — the pairing ``tests/service/test_transport.py`` already makes
    for the loopback listener, made here for the remote one.
    """
    budget = ConnectionBudget(max_connections=8, max_pending_handshakes=1)
    async with _remote(tmp_path, budget=budget) as hub:
        minted = hub.registry.enrol(_DEVICE, now=_MOMENT)
        async with _dialling(hub) as peer:
            assert (await peer.connect(minted.credential)).kind is env.FrameKind.CONNECT_ACK
            await _once(lambda: budget.handshaking == 0, what="the pending slot is given back")
            assert budget.serving == 1


async def test_a_fault_before_the_handshake_is_named_on_the_hubs_own_log(
    tmp_path: Path,
) -> None:
    """One connection's fault is never the resident process's — on the accept
    callback too, where nothing else supplies that rule.

    **What is asserted is the diagnosis, because that is what the clause buys.**
    ``asyncio`` closes the transport of its own accord when a client-connected
    callback raises, so the connection closing is not the discriminating fact and a
    test asserting only that would pass with no handler at all. The named event is:
    without it an operator meets the loop's generic "Task exception was never
    retrieved" and has to work out for themselves that the remote door is the thing
    refusing connections, which is ADR-0083's ruling 4 failure.

    The agent raises something the seam does not declare, which is how a
    non-conforming implementation of it actually arrives.
    """
    async with _remote(tmp_path, agent=_BrokenAgent()) as hub:
        hub.registry.enrol(_DEVICE, now=_MOMENT)
        with structlog.testing.capture_logs() as captured:
            async with _dialling(hub) as peer:
                assert await asyncio.wait_for(peer.reader.read(), _PATIENT.total_seconds()) == b""
    assert "hub_remote_accept_failed" in [entry["event"] for entry in captured]


async def test_a_broken_accept_gives_its_budget_slot_back(tmp_path: Path) -> None:
    """The other half: a fault must not spend a ceiling permanently.

    ADR-0124 §7 makes both ceilings the hub's totals, so a slot never given back is
    a hub that serves fewer connections after every such fault until it serves none
    — which looks from outside exactly like a hub that is down. It holds because
    :func:`~ai_assistant.service.transport.hold` returns the slot from a ``finally``
    rather than because anything here catches; asserting it is what stops a future
    edit from moving the accounting somewhere an exception can skip.
    """
    budget = ConnectionBudget(max_connections=2, max_pending_handshakes=2)
    async with _remote(tmp_path, agent=_BrokenAgent(), budget=budget) as hub:
        for _ in range(4):
            async with _dialling(hub) as peer:
                assert await asyncio.wait_for(peer.reader.read(), _PATIENT.total_seconds()) == b""
        await _once(lambda: budget.serving == 0, what="every slot is given back")


async def test_a_connection_stalled_in_the_identity_query_converges_on_shutdown(
    tmp_path: Path,
) -> None:
    """ADR-0083 §4's release must reach a connection that has not been admitted yet.

    §4's phases own accepted connections, and
    :meth:`~ai_assistant.service.remote.RemoteListener.aclose` is what lets go of
    the ones whose peers never spoke again. A connection *awaiting* ADR-0124 §4's
    identity query is the case a listener most easily loses: the identity is the
    natural key to track it under, and it does not exist yet — so tracking it there
    would leave nothing for the release to cancel, and a hub could finish draining
    with an accepted connection still live that then entered ``serve_connection``
    against an engine already closed.

    The seam is a Protocol, so "the agent answers quickly" is not something this
    listener may rest on: the fake here never answers at all.
    """
    reached = asyncio.Event()

    class _StalledAgent(_FakeAgent):
        async def identify(self, host: str, port: int) -> str:
            del host, port
            reached.set()
            await asyncio.Event().wait()
            raise AssertionError  # pragma: no cover — the wait above never returns

    settings = _settings(tmp_path)
    store = EnrolmentStore(tmp_path / ENROLMENTS_FILENAME)
    budget = ConnectionBudget(max_connections=8, max_pending_handshakes=4)
    listener = RemoteListener(
        FakeAssistantEngine(),
        settings,
        registry=DeviceRegistry(store, hub_identity=_HUB_ID),
        agent=_StalledAgent(),
        budget=budget,
    )
    await listener.start(build="test")
    try:
        reader, writer = await asyncio.open_connection(_BIND, _bound_port(listener))
        await asyncio.wait_for(reached.wait(), _PATIENT.total_seconds())
        await listener.stop_accepting()
        # The release returns rather than hanging, and the peer sees the connection
        # end — which is what "converges" means to the device on the other side.
        await asyncio.wait_for(listener.aclose(), _PATIENT.total_seconds())
        assert await asyncio.wait_for(reader.read(), _PATIENT.total_seconds()) == b""
        assert budget.serving == 0
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        store.close()


async def test_a_callback_that_runs_after_the_close_is_refused_not_served(
    tmp_path: Path,
) -> None:
    """ADR-0083 §4's release is a barrier, and this is the clause that makes it one.

    ``Server.close()`` stops future accepts and says nothing about a callback
    ``asyncio`` has *already queued* for a connection it accepted a turn earlier.
    That callback runs on some later turn — possibly after the release has finished
    and the engine and the enrolment record have been let go — and a connection
    served then would be one the hub can no longer serve at all.

    **What is asserted is the barrier's own contract rather than the scheduler's,
    and that is a deliberate limit.** Producing the exact interleaving — accepted,
    task created, task not yet run, shutdown — is not something a test can force
    without reaching into ``asyncio``'s internals, and a test that merely hoped for
    it would pin nothing. So the callback is invoked directly, in the state the
    barrier exists for: after ``stop_accepting``. The engine is never called, the
    agent is never asked who connected, the slot is given back, and the peer's
    connection ends.
    """
    async with _remote(tmp_path) as hub:
        hub.registry.enrol(_DEVICE, now=_MOMENT)
        accepted: asyncio.Future[tuple[asyncio.StreamReader, asyncio.StreamWriter]] = (
            asyncio.get_running_loop().create_future()
        )

        async def _capture(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            accepted.set_result((reader, writer))

        spare = await asyncio.start_server(_capture, host=_BIND, port=0)
        port = int(spare.sockets[0].getsockname()[1])
        client_reader, client_writer = await asyncio.open_connection(_BIND, port)
        hub_reader, hub_writer = await accepted
        try:
            await hub.listener.stop_accepting()
            await hub.listener._accept(hub_reader, hub_writer)

            assert hub.engine.calls == []
            assert hub.agent.identified == 0
            assert hub.budget.serving == 0
            assert await asyncio.wait_for(client_reader.read(), _PATIENT.total_seconds()) == b""
        finally:
            client_writer.close()
            with contextlib.suppress(Exception):
                await client_writer.wait_closed()
            spare.close()
            await spare.wait_closed()


@pytest.mark.parametrize(
    ("credential", "code"),
    [
        (None, env.CREDENTIAL_REQUIRED),
        ("", env.CREDENTIAL_REQUIRED),
        ("not-a-credential", env.CREDENTIAL_REJECTED),
        (7, env.CREDENTIAL_REJECTED),
    ],
)
async def test_every_remote_refusal_is_recorded_against_its_device(
    credential: object, code: str, tmp_path: Path
) -> None:
    """ADR-0124 §6: "each admission and each refusal with the device it named".

    That record is one of the three replacements standing in for ADR-0004 §7's gate
    over the client's bootstrap credential read — "so what the credential was used
    for is auditable even though the read that produced it is not" — and §7 requires
    the reasons distinguished "in the error it returns **and in what the hub logs**".

    The four cases here are the ones the *frame reader* refuses, before any verifier
    is consulted: they never reach the admission's own decision, so without a seam
    for them the hub would answer the peer and record nothing about who it was. The
    log carries neither the credential nor the verifier (§7).
    """
    async with _remote(tmp_path) as hub:
        hub.registry.enrol(_DEVICE, now=_MOMENT)
        with structlog.testing.capture_logs() as captured:
            async with _dialling(hub) as peer:
                reply = await peer.connect(credential)
    assert reply.payload["code"] == code
    refused = [entry for entry in captured if entry["event"] == "hub_remote_admission_refused"]
    assert [(entry["overlay_identity"], entry["reason"]) for entry in refused] == [(_DEVICE, code)]
    rendered = repr(captured)
    assert "not-a-credential" not in rendered
    assert "verifier" not in rendered


async def test_an_admission_and_its_refusal_speak_the_same_vocabulary(
    tmp_path: Path,
) -> None:
    """§7's "in the error it returns and in what the hub logs", read strictly.

    An internal name in the log and a wire token in the frame would be two records
    of one event that an owner cannot correlate — so the log carries the code the
    device was actually sent.
    """
    async with _remote(tmp_path) as hub:
        good = hub.registry.enrol(_DEVICE, now=_MOMENT)
        hub.registry.revoke(_DEVICE, now=_MOMENT + timedelta(minutes=1))
        with structlog.testing.capture_logs() as captured:
            async with _dialling(hub) as peer:
                reply = await peer.connect(good.credential)
    assert reply.payload["code"] == env.DEVICE_REVOKED
    (refused,) = [e for e in captured if e["event"] == "hub_remote_admission_refused"]
    assert refused["reason"] == env.DEVICE_REVOKED
    assert good.credential not in repr(captured)


async def test_a_version_mismatch_after_a_good_credential_is_recorded_as_a_refusal(
    tmp_path: Path,
) -> None:
    """ADR-0124 §6's record covers a refusal that arrives *after* the credential.

    A device presenting a credential that verifies can still be refused a moment
    later, and a protocol version this hub does not speak is that case. It is a use
    of the credential — the verifier really was consulted — so §6's "each admission
    and each refusal with the device it named" reaches it, and an operator otherwise
    reads a connection that presented a good credential and then vanished.

    **And no admission is logged for it**, which is the other half: an "admitted"
    line written when the two facts held would have the log asserting a connection
    that was never served.
    """
    async with _remote(tmp_path) as hub:
        minted = hub.registry.enrol(_DEVICE, now=_MOMENT)
        with structlog.testing.capture_logs() as captured:
            async with _dialling(hub) as peer:
                await peer.send(
                    env.Envelope(
                        kind=env.FrameKind.CONNECT,
                        id="c-0",
                        payload={
                            env.CONNECT_VERSION: env.PROTOCOL_VERSION + 1,
                            env.CONNECT_CLIENT: "assistant-cli",
                            env.CONNECT_CREDENTIAL: minted.credential,
                        },
                    )
                )
                reply = await peer.receive()
    assert reply.payload["code"] == env.VERSION_MISMATCH
    (refused,) = [e for e in captured if e["event"] == "hub_remote_admission_refused"]
    assert (refused["overlay_identity"], refused["reason"]) == (_DEVICE, env.VERSION_MISMATCH)
    assert [e for e in captured if e["event"] == "hub_remote_admitted"] == []
    assert minted.credential not in repr(captured)


async def test_a_served_device_is_recorded_as_admitted_once_the_handshake_completes(
    tmp_path: Path,
) -> None:
    """The discriminating half: a hub that recorded no admission at all would pass
    every refusal test above and leave §6's record telling only half the story."""
    async with _remote(tmp_path) as hub:
        minted = hub.registry.enrol(_DEVICE, now=_MOMENT)
        with structlog.testing.capture_logs() as captured:
            async with _dialling(hub) as peer:
                assert (await peer.connect(minted.credential)).kind is env.FrameKind.CONNECT_ACK
                await peer.send(
                    env.Envelope(kind=env.FrameKind.REQUEST, id="r-0", payload={}, method="beliefs")
                )
                assert (await peer.receive()).kind is env.FrameKind.RESULT
    (admitted,) = [e for e in captured if e["event"] == "hub_remote_admitted"]
    assert admitted["overlay_identity"] == _DEVICE
    assert [e for e in captured if e["event"] == "hub_remote_admission_refused"] == []
    assert minted.credential not in repr(captured)
