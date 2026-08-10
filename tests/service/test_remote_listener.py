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
    """

    identity: str = _HUB_ID
    addresses: frozenset[str] = frozenset({_BIND})
    sequence: list[str] = field(default_factory=list)
    default_peer: str | None = _DEVICE
    available: bool = True

    async def hub_identity(self) -> HubOverlayIdentity:
        """What this machine is, or a refusal."""
        if not self.available:
            msg = "the overlay agent is not running"
            raise OverlayIdentityUnavailableError(msg)
        return HubOverlayIdentity(identity=self.identity, addresses=self.addresses)

    async def identify(self, host: str, port: int) -> str:
        """Who is at ``host``, taken from this machine and never from the peer."""
        del host, port
        found = self.sequence.pop(0) if self.sequence else self.default_peer
        if found is None:
            msg = "the overlay agent knows no node at that address"
            raise OverlayIdentityUnavailableError(msg)
        return found


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
