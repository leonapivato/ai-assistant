"""The client half of the hop, driven against a real socket (ADR-0124 §1, §4, §7).

Everything ADR-0124 §1's marked clause requires of the client half, in the order
the clause puts it: the destination comes from configuration, the hub's identity is
confirmed before anything is sent, and the only two things that go out are the
connect frame §7 requires and the request the caller asked for.

**A fake overlay agent and a fake keyring, and both are load-bearing.** The agent is
what ADR-0124 §4 makes the *only* source of a peer's identity — "It may not take
that identity from anything the peer asserts" — so a test that let the server
supply it would be testing the attack rather than the defence. The keyring is the
canonical ``FakeSecretStore``, bound to ``ENROLMENT``, which is the wiring ADR-0125
§8 requires.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest

from ai_assistant.core.types import SecretScope
from ai_assistant.testing import FakeSecretStore
from ai_assistant.wire import envelope as env
from ai_assistant.wire.address import RemoteDestination
from ai_assistant.wire.codec import CONNECT_PAYLOAD_BYTES, encode_projection
from ai_assistant.wire.credential import mint_credential
from ai_assistant.wire.enrolment import credential_name, store_enrolment
from ai_assistant.wire.errors import (
    HubIdentityMismatchError,
    HubUnavailableError,
    NotEnrolledError,
    OverlayIdentityUnavailableError,
    ProtocolError,
)
from ai_assistant.wire.framing import read_frame, write_frame
from ai_assistant.wire.remote import RemoteHubEngineClient

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

_PATIENT = timedelta(seconds=5)
_FRAME = 1 << 20

#: The hub this device is enrolled at, as an overlay agent reports a stable node id.
HUB = "nQ8xYt2CNTRL"

#: Some other member of the same overlay — a printer, a phone, or an attacker who
#: has taken the address the client was pointed at.
STRANGER = "zK1mBv9QOTHR"


class FakeOverlayAgent:
    """This machine's overlay agent, as a client uses it.

    Attributes:
        answers: What the agent says about each ``host:port`` it is asked about.
        asked: Every address it was asked about, in order — which is how a case
            asserts that the question was put *before* anything was sent.
        refuse: Whether the agent declines to answer at all.
    """

    def __init__(self, identity: str = HUB, *, refuse: bool = False) -> None:
        self.identity = identity
        self.asked: list[tuple[str, int]] = []
        self.refuse = refuse

    async def identify(self, host: str, port: int) -> str:
        """Say whose device holds an address, or refuse to."""
        self.asked.append((host, port))
        if self.refuse:
            msg = "the overlay agent did not answer"
            raise OverlayIdentityUnavailableError(msg)
        return self.identity


class RecordingHub:
    """A listener that records the connect frame and answers however a case asks.

    Attributes:
        connects: Every connect payload it received, decoded.
        port: The ephemeral port it bound.
    """

    def __init__(self) -> None:
        self.connects: list[Any] = []
        self.port = 0
        self._server: asyncio.Server | None = None

    async def start(self, answer: Callable[[env.Envelope], env.Envelope] | None = None) -> None:
        """Bind an ephemeral loopback port and begin serving.

        Loopback rather than an overlay address, because what is under test is the
        client's own conduct: which questions it asks, in which order, and what it
        puts in the frame. Where the socket happens to be is
        :mod:`ai_assistant.wire.address`'s subject and is tested there.
        """
        self._answer = answer or _acknowledge
        self._server = await asyncio.start_server(self._serve, host="127.0.0.1", port=0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        """Close the listener."""
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await self._server.wait_closed()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Read the connect frame, record it, and answer."""
        body = await read_frame(
            reader, max_frame_bytes=_FRAME, timeout=_PATIENT, idle_timeout=_PATIENT
        )
        frame = env.decode_envelope(body)
        self.connects.append(frame.payload)
        await write_frame(writer, env.encode_envelope(self._answer(frame)), max_frame_bytes=_FRAME)
        writer.close()


def _acknowledge(frame: env.Envelope) -> env.Envelope:
    """The ordinary reply: this hub admits the connection."""
    return env.Envelope(
        kind=env.FrameKind.CONNECT_ACK,
        id=frame.id,
        payload=env.connect_ack_payload(build="test", max_frame_bytes=_FRAME),
    )


def _refuse(code: str, message: str) -> Callable[[env.Envelope], env.Envelope]:
    """A hub that refuses the handshake with one of ADR-0124 §7's codes."""

    def answer(frame: env.Envelope) -> env.Envelope:
        return env.Envelope(
            kind=env.FrameKind.ERROR,
            id=frame.id,
            payload={"code": code, "message": message},
        )

    return answer


@pytest.fixture
async def hub() -> AsyncIterator[RecordingHub]:
    """A listener that answers one connect and records what it was sent."""
    listener = RecordingHub()
    yield listener
    await listener.stop()


async def enrolled(hub_identity: str = HUB) -> tuple[FakeSecretStore, str]:
    """A device that holds a whole enrolment for ``hub_identity``."""
    store = FakeSecretStore(scope=SecretScope.ENROLMENT)
    credential = mint_credential()
    await store_enrolment(store, hub_identity=hub_identity, credential=credential)
    return store, credential


def client_of(
    port: int,
    store: FakeSecretStore,
    agent: FakeOverlayAgent,
    *,
    host: str = "127.0.0.1",
) -> RemoteHubEngineClient:
    """A remote client pointed at ``port``, with the two seams a case controls."""
    return RemoteHubEngineClient(
        RemoteDestination(host=host, port=port),
        read_timeout=_PATIENT,
        agent=agent,
        secrets=store,
    )


# --- the credential the connect frame carries (ADR-0124 §7) ------------------


async def test_the_connect_frame_carries_the_credential_as_a_json_string(
    hub: RecordingHub,
) -> None:
    """ADR-0124 §7: "The credential member is a JSON string, or it is absent."

    Fixing the type is what makes the two-fact rule decidable from the frame: on
    the remote listener an object or a number "would otherwise reach a verifier
    written for text, and three implementations could diverge three ways".
    """
    await hub.start()
    store, credential = await enrolled()

    await client_of(hub.port, store, FakeOverlayAgent()).probe()

    assert len(hub.connects) == 1
    payload = hub.connects[0]
    assert isinstance(payload[env.CONNECT_CREDENTIAL], str)
    assert payload[env.CONNECT_CREDENTIAL] == credential


async def test_the_connect_payload_stays_inside_the_ratified_bound(
    hub: RecordingHub,
) -> None:
    """ADR-0085 §8d's 256 bytes, which ADR-0124 §6 designs inside rather than raises.

    "A scheme whose credential does not fit — a certificate chain, a signed token
    carrying claims — is refused by this clause rather than by amending ADR-0085."
    The frame is measured as it went out, so a credential scheme that grew would
    fail here rather than at a hub that refused an oversized handshake.
    """
    await hub.start()
    store, _ = await enrolled()

    await client_of(hub.port, store, FakeOverlayAgent()).probe()

    encoded = encode_projection(hub.connects[0])
    assert len(encoded) <= CONNECT_PAYLOAD_BYTES


async def test_the_protocol_version_is_unchanged_on_this_transport(
    hub: RecordingHub,
) -> None:
    """ADR-0124 §9: the hop bumps nothing, because it adds no member and changes none.

    "A peer at version 2 on either listener exchanges exactly the frames it
    exchanges today", and ``CONNECT_CREDENTIAL`` is a member ADR-0084 §2 defined.
    """
    await hub.start()
    store, _ = await enrolled()

    await client_of(hub.port, store, FakeOverlayAgent()).probe()

    assert hub.connects[0][env.CONNECT_VERSION] == env.PROTOCOL_VERSION


# --- mutual authentication (ADR-0124 §4) ------------------------------------


async def test_a_destination_that_is_not_the_enrolled_hub_is_refused_before_sending(
    hub: RecordingHub,
) -> None:
    """§4's second clause, and §11's step 5.

    "Pointed by configuration at a different overlay member's address, the client
    refuses **before sending anything**, because the identity its own agent reports
    for that address is not the enrolled hub identity — and editing the destination
    does not move that identity."

    That the hub recorded no connect is the assertion: a client that dialled first
    and checked afterwards has already handed over the credential.
    """
    await hub.start()
    store, _ = await enrolled(hub_identity=HUB)

    with pytest.raises(HubIdentityMismatchError) as raised:
        await client_of(hub.port, store, FakeOverlayAgent(STRANGER)).probe()

    assert hub.connects == [], "the client sent a connect frame to a hub it had not confirmed"
    assert STRANGER in str(raised.value)
    assert HUB in str(raised.value)


async def test_the_identity_comes_from_this_machines_agent_and_never_from_the_peer(
    hub: RecordingHub,
) -> None:
    """§4: "It may not take that identity from anything the peer asserts."

    The hub here answers a perfectly ordinary acknowledgement and asserts nothing
    about who it is — there is nowhere in the ratified frame for it to. The client
    asks its own agent about the address it is about to dial, and the *address it
    asked about* is the one it was configured with.
    """
    await hub.start()
    store, _ = await enrolled()
    agent = FakeOverlayAgent()

    await client_of(hub.port, store, agent).probe()

    assert agent.asked == [("127.0.0.1", hub.port)]


async def test_an_agent_that_will_not_say_refuses_the_connection(hub: RecordingHub) -> None:
    """§4's fail-closed direction, mirrored from the hub's half.

    "A connection whose overlay identity cannot be obtained is refused." An agent
    that is not running is not permission to proceed unauthenticated — which is the
    direction ADR-0084 §1 already fixed for a platform with no peer-credential call.
    """
    await hub.start()
    store, _ = await enrolled()

    with pytest.raises(OverlayIdentityUnavailableError):
        await client_of(hub.port, store, FakeOverlayAgent(refuse=True)).probe()

    assert hub.connects == []


# --- what a device without a whole enrolment does (ADR-0124 §6, §8) ---------


async def test_a_device_with_no_enrolment_sends_nothing(hub: RecordingHub) -> None:
    """The state ADR-0124 §8's unenrolment leaves: "nothing to present" (§11 step 10).

    Reported from what this device knows about itself rather than by dialling and
    being refused, which is also §1's "sends only two things" honoured at the one
    moment it would be easiest to send a third.
    """
    await hub.start()
    store = FakeSecretStore(scope=SecretScope.ENROLMENT)

    with pytest.raises(NotEnrolledError):
        await client_of(hub.port, store, FakeOverlayAgent()).probe()

    assert hub.connects == []


async def test_a_half_written_enrolment_sends_nothing(hub: RecordingHub) -> None:
    """ADR-0124 §6: an incomplete enrolment "the client refuses to connect on"."""
    await hub.start()
    store, _ = await enrolled()
    await store.delete(credential_name())

    with pytest.raises(NotEnrolledError):
        await client_of(hub.port, store, FakeOverlayAgent()).probe()

    assert hub.connects == []


# --- the three refusals the listener distinguishes (ADR-0124 §7) ------------


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (env.DEVICE_NOT_ENROLLED, "this hub has no enrolment for the device you connected from"),
        (env.DEVICE_REVOKED, "this device's enrolment was revoked"),
        (env.CREDENTIAL_REJECTED, "the credential presented does not verify"),
        (env.CREDENTIAL_REQUIRED, "a credential is one of the two facts"),
    ],
)
async def test_each_refusal_renders_its_own_reason_and_its_own_code(
    hub: RecordingHub, code: str, message: str
) -> None:
    """§7 distinguishes three refusals so that an owner can act on the difference.

    "An owner who cannot tell 'I never enrolled this laptop' from 'I revoked it last
    week' from 'I pasted the wrong string' is ADR-0083's ruling 4 failure." The
    sentence carries the diagnosis and the token is what makes this screen and the
    hub's log two records of one event.
    """
    await hub.start(_refuse(code, message))
    store, _ = await enrolled()

    with pytest.raises(ProtocolError) as raised:
        await client_of(hub.port, store, FakeOverlayAgent()).probe()

    assert message in str(raised.value)
    assert code in str(raised.value)


async def test_a_refusal_code_this_client_does_not_know_still_renders(
    hub: RecordingHub,
) -> None:
    """ADR-0124's Context, as behaviour: the client renders from the message.

    "A handshake refusal an old client cannot name still renders… it does not switch
    on the code." That is what lets a hub add a refusal without every older device
    turning it into a blank failure.
    """
    await hub.start(_refuse("some_future_refusal", "a hub from the future said no"))
    store, _ = await enrolled()

    with pytest.raises(ProtocolError) as raised:
        await client_of(hub.port, store, FakeOverlayAgent()).probe()

    assert "a hub from the future said no" in str(raised.value)


# --- a closed door on the other transport too (ADR-0084 §9) -----------------


async def test_nothing_listening_is_an_instruction_naming_the_destination() -> None:
    """§9's rule, restated for an address rather than a socket path.

    It names the destination, the two settings that decide it, and says in as many
    words that nothing is started and nothing falls back in-process — because on
    this transport the tempting fallback is the *other transport*, which would serve
    the wrong store from the wrong machine.
    """
    store, _ = await enrolled()
    unbound = await _free_port()

    with pytest.raises(HubUnavailableError) as raised:
        await client_of(unbound, store, FakeOverlayAgent()).probe()

    assert f"127.0.0.1:{unbound}" in str(raised.value)
    assert "ASSISTANT_REMOTE_HUB_PORT" in str(raised.value)
    assert "never falls back" in str(raised.value)


async def test_a_version_mismatch_names_the_remote_destination(hub: RecordingHub) -> None:
    """ADR-0084 §3's exact-match handshake, on the deployment it was written for.

    A hop is where the two halves "can genuinely differ: two machines, upgraded
    separately, by hand" — so the message names which destination disagrees rather
    than a socket path that does not exist on this side.
    """

    def older(frame: env.Envelope) -> env.Envelope:
        payload = env.connect_ack_payload(build="test", max_frame_bytes=_FRAME)
        payload[env.ACK_VERSION] = env.PROTOCOL_VERSION + 1
        return env.Envelope(kind=env.FrameKind.CONNECT_ACK, id=frame.id, payload=payload)

    await hub.start(older)
    store, _ = await enrolled()

    with pytest.raises(ProtocolError) as raised:
        await client_of(hub.port, store, FakeOverlayAgent()).probe()

    assert f"127.0.0.1:{hub.port}" in str(raised.value)


async def _free_port() -> int:
    """A port nothing is listening on, obtained by binding and letting go."""
    server = await asyncio.start_server(_never, host="127.0.0.1", port=0)
    port = int(server.sockets[0].getsockname()[1])
    server.close()
    await server.wait_closed()
    return port


async def _never(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """A handler that is never invoked; the socket is closed before anything connects."""
    raise AssertionError
