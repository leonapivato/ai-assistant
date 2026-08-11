"""ADR-0131 §2, §2a and §5 at the wire: the delivery connection's own rules.

The outbox's transitions are the engine's and are tested where they live. What is
here is the half that is *the connection's*: the two closes §2 requires in both
directions, the slot and capacity claims §5 makes one step, the release §2a states
over any cause of a close, and the close detection §2a says the existing request
loop does not have.

**§2a's finding is why the last of those is exercised with the schedule under the
test's control.** ``_serve_requests`` reads the next frame concurrently with the
dispatch — which is how it catches an overlapping request — but settles that
watcher only after ``_dispatch`` returns, so a peer's clean close was observed
within milliseconds and acted on only once the poll's budget had run out. That is
a thing a test does to its own process, not something a device can be made to do
on cue.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.core.types import DataTier, NotificationCandidate, NotificationDelivery
from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.wire import envelope as env
from ai_assistant.wire.framing import read_frame, write_frame
from ai_assistant.wire.server import ConnectionLimits, serve_connection

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

_PATIENT: Final = timedelta(seconds=5)
_FRAME: Final = 1 << 20
_LIMITS: Final = ConnectionLimits(max_frame_bytes=_FRAME, read_timeout=_PATIENT, build="test")

_CANDIDATE: Final = NotificationCandidate(
    candidate_key="k1",
    producer="a-producer",
    notification_class="calendar",
    summary="something the user did not ask for",
    noticed_at=datetime(2026, 8, 11, 12, 0, tzinfo=UTC),
    confidence=0.5,
    sensitivity=DataTier.PERSONAL,
)


@dataclass
class _Slots:
    """A :class:`~ai_assistant.wire.server.DeliveryRegistry` a test drives by hand.

    Attributes:
        capacity: How many delivery connections it will admit at once.
        held: The devices currently holding a slot, in claim order.
        releases: Every device released, so a test can assert the release happened
            on a cause of a close that is not the detected one.
    """

    capacity: int = 8
    held: list[str | None] = field(default_factory=list)
    releases: list[str | None] = field(default_factory=list)

    def claim(self, device: str | None) -> bool:
        """Take both claims, or neither."""
        if device in self.held or len(self.held) >= self.capacity:
            return False
        self.held.append(device)
        return True

    def release(self, device: str | None) -> None:
        """Give both back, in one step."""
        self.releases.append(device)
        if device in self.held:
            self.held.remove(device)


class _PollingEngine(FakeAssistantEngine):
    """An engine whose poll parks until a test releases it."""

    def __init__(self) -> None:
        """Start with nothing to deliver and nobody waiting."""
        super().__init__()
        self.release_poll = asyncio.Event()
        self.poll_entered = asyncio.Event()
        self.staged: NotificationDelivery | None = None
        self.cancelled = False

    async def next_notification(
        self, *, acknowledging: object = None, budget: timedelta = timedelta(0)
    ) -> NotificationDelivery | None:
        """Park until released, so a case can act while a poll is outstanding."""
        del acknowledging, budget
        self.poll_entered.set()
        try:
            await self.release_poll.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return self.staged


@dataclass
class _Peer:
    """The client half of one served connection."""

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter

    async def send(self, frame: env.Envelope) -> None:
        """Write one frame."""
        await write_frame(self.writer, env.encode_envelope(frame), max_frame_bytes=_FRAME)

    async def receive(self) -> env.Envelope:
        """Read one frame."""
        body = await read_frame(
            self.reader, max_frame_bytes=_FRAME, timeout=_PATIENT, idle_timeout=_PATIENT
        )
        return env.decode_envelope(body)


@contextlib.asynccontextmanager
async def _serving(
    engine: FakeAssistantEngine, slots: _Slots, tmp_path: Path, name: str = "s.sock"
) -> AsyncIterator[tuple[_Peer, asyncio.Task[None]]]:
    """Serve one connection over a real socket, so the framing is exercised too."""
    path = tmp_path / name
    accepted: asyncio.Future[tuple[asyncio.StreamReader, asyncio.StreamWriter]] = (
        asyncio.get_running_loop().create_future()
    )

    async def _accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        accepted.set_result((reader, writer))

    server = await asyncio.start_unix_server(_accept, path=str(path))
    reader, writer = await asyncio.open_unix_connection(str(path))
    hub_reader, hub_writer = await accepted
    served = asyncio.ensure_future(
        serve_connection(engine, hub_reader, hub_writer, limits=_LIMITS, delivery=slots)
    )
    try:
        yield _Peer(reader, writer), served
    finally:
        with contextlib.suppress(Exception):
            writer.close()
        served.cancel()
        await asyncio.gather(served, return_exceptions=True)
        server.close()
        await server.wait_closed()


def _connect() -> env.Envelope:
    """A loopback connect frame."""
    payload: dict[str, Any] = {
        env.CONNECT_VERSION: env.PROTOCOL_VERSION,
        env.CONNECT_CLIENT: "assistant-notifier",
    }
    return env.Envelope(kind=env.FrameKind.CONNECT, id="c-0", payload=payload)


def _poll(correlation: str = "r-0", budget: float = 30.0) -> env.Envelope:
    """A ``next_notification`` request frame."""
    return env.Envelope(
        kind=env.FrameKind.REQUEST,
        id=correlation,
        method="next_notification",
        payload={"budget": budget},
    )


def _other(correlation: str = "r-9") -> env.Envelope:
    """An ordinary request frame, for the isolation cases."""
    return env.Envelope(
        kind=env.FrameKind.REQUEST,
        id=correlation,
        method="pending_confirmations",
        payload={},
    )


async def _handshake(peer: _Peer) -> None:
    """Complete the connect exchange."""
    await peer.send(_connect())
    reply = await peer.receive()
    assert reply.kind is env.FrameKind.CONNECT_ACK


async def _closed(peer: _Peer) -> bool:
    """Whether the hub closed the connection rather than replying."""
    with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
        async with asyncio.timeout(2):
            return await peer.reader.read(1) == b""
    return False


class TestTheSlotIsClaimedBeforeDispatch:
    """ADR-0131 §2, §5: the check and the claim are one step, before dispatch."""

    async def test_a_poll_claims_the_connections_slot(self, tmp_path: Path) -> None:
        """§2: a connection becomes a delivery connection at its first poll."""
        engine = _PollingEngine()
        slots = _Slots()
        async with _serving(engine, slots, tmp_path) as (peer, _):
            await _handshake(peer)
            await peer.send(_poll())
            await asyncio.wait_for(engine.poll_entered.wait(), 2)

            assert slots.held == [None]

    async def test_a_poll_with_no_slot_available_closes_its_own_connection(
        self, tmp_path: Path
    ) -> None:
        """§2: "the hub closes **the connection that made the second request**".

        The opposite rule — newest poll wins — "lets any process that can reach the
        listener evict the owner's real notifier by polling, and the eviction would
        look to the notifier exactly like an ordinary transport failure".
        """
        engine = _PollingEngine()
        slots = _Slots(capacity=0)
        async with _serving(engine, slots, tmp_path) as (peer, _):
            await _handshake(peer)
            await peer.send(_poll())

            assert await _closed(peer)
            assert not engine.poll_entered.is_set()

    async def test_the_refused_poll_reaches_no_engine(self, tmp_path: Path) -> None:
        """§2: "The slot's check and claim are **one step**, taken before the
        request is dispatched."

        Taking the claim before dispatch is what makes "exactly one wins"
        decidable: after dispatch the losing poll would already be running and the
        rule would have to unwind it.
        """
        engine = _PollingEngine()
        slots = _Slots(capacity=0)
        async with _serving(engine, slots, tmp_path) as (peer, _):
            await _handshake(peer)
            await peer.send(_poll())
            await _closed(peer)

            assert (
                "next_notification",
                {"acknowledging": None, "budget": 30.0},
            ) not in engine.calls

    async def test_a_second_poll_on_the_same_connection_makes_no_new_claim(
        self, tmp_path: Path
    ) -> None:
        """§2a: "A later ``next_notification`` on that same connection uses the
        claims it already holds and makes no new ones."

        A connection is the unit, not a poll: a release keyed on the poll
        completing would let a device take a zero-budget poll, release its claim,
        and keep the now-idle socket.
        """
        engine = _PollingEngine()
        engine.release_poll.set()
        slots = _Slots(capacity=1)
        async with _serving(engine, slots, tmp_path) as (peer, _):
            await _handshake(peer)
            await peer.send(_poll("r-0"))
            assert (await peer.receive()).kind is env.FrameKind.RESULT

            await peer.send(_poll("r-1"))

            assert (await peer.receive()).kind is env.FrameKind.RESULT
            assert slots.held == [None]


class TestTheIsolationRuleBindsBothDirections:
    """ADR-0131 §2: "The hub enforces that in **both directions**."""

    async def test_a_poll_after_another_request_closes(self, tmp_path: Path) -> None:
        """§2: the direction a draft of the ADR left unstated.

        "The serial server accepts sequential frames happily, so that socket would
        claim a delivery slot out of the capacity §5 reserves for isolated pollers,
        with §2's 'carrying no other request for its lifetime' contradicted and
        nothing to contradict it." Found on the twenty-sixth round.
        """
        engine = _PollingEngine()
        slots = _Slots()
        async with _serving(engine, slots, tmp_path) as (peer, _):
            await _handshake(peer)
            await peer.send(_other())
            assert (await peer.receive()).kind is env.FrameKind.RESULT

            await peer.send(_poll())

            assert await _closed(peer)
            assert slots.held == []

    async def test_an_ordinary_request_on_a_delivery_connection_closes(
        self, tmp_path: Path
    ) -> None:
        """§2: "a request other than ``next_notification`` arriving on a delivery
        connection closes it"."""
        engine = _PollingEngine()
        engine.release_poll.set()
        slots = _Slots()
        async with _serving(engine, slots, tmp_path) as (peer, _):
            await _handshake(peer)
            await peer.send(_poll())
            assert (await peer.receive()).kind is env.FrameKind.RESULT

            await peer.send(_other())

            assert await _closed(peer)

    async def test_a_frame_written_while_a_poll_is_outstanding_closes(self, tmp_path: Path) -> None:
        """ADR-0084 §3's serial rule is unchanged by a poll being long.

        A correlated error would carry the second request's id, "which the mismatch
        rule separately obliges the client to reject — so the refusal could never
        be consumed".
        """
        engine = _PollingEngine()
        slots = _Slots()
        async with _serving(engine, slots, tmp_path) as (peer, _):
            await _handshake(peer)
            await peer.send(_poll("r-0"))
            await asyncio.wait_for(engine.poll_entered.wait(), 2)

            await peer.send(_poll("r-1"))

            assert await _closed(peer)


class TestTheConnectionGoingAwayEndsThePoll:
    """ADR-0131 §2a: the one place this seam reaches into the request loop."""

    async def test_a_peer_hanging_up_cancels_the_outstanding_poll(self, tmp_path: Path) -> None:
        """§2a: "While a ``next_notification`` request is outstanding, the hub
        detects its connection closing. On detecting it the poll ends without an
        answer."

        Without this the device's slot stays held by a poll nobody is listening to,
        "and the reconnect §2 calls free is closed as a second poll — the claim and
        the rule contradicting each other on the most ordinary failure a mobile
        device has".
        """
        engine = _PollingEngine()
        slots = _Slots()
        async with _serving(engine, slots, tmp_path) as (peer, served):
            await _handshake(peer)
            await peer.send(_poll())
            await asyncio.wait_for(engine.poll_entered.wait(), 2)

            peer.writer.close()

            await asyncio.wait_for(served, 5)
            assert engine.cancelled

    async def test_the_slot_is_released_when_the_connection_ends(self, tmp_path: Path) -> None:
        """§2a: "its device slot and its global delivery-capacity claim are **both
        released, in one step**".

        Stated over *any* cause of a close rather than over the detected-close path
        alone, which is what keeps a third way of closing from needing a fourth
        clause.
        """
        engine = _PollingEngine()
        slots = _Slots()
        async with _serving(engine, slots, tmp_path) as (peer, served):
            await _handshake(peer)
            await peer.send(_poll())
            await asyncio.wait_for(engine.poll_entered.wait(), 2)
            peer.writer.close()
            await asyncio.wait_for(served, 5)

            assert slots.releases == [None]
            assert slots.held == []

    async def test_the_slot_is_released_after_an_ordinary_completion(self, tmp_path: Path) -> None:
        """§2a: the release is over any cause, a clean end included."""
        engine = _PollingEngine()
        engine.release_poll.set()
        slots = _Slots()
        async with _serving(engine, slots, tmp_path) as (peer, served):
            await _handshake(peer)
            await peer.send(_poll())
            assert (await peer.receive()).kind is env.FrameKind.RESULT
            peer.writer.close()
            await asyncio.wait_for(served, 5)

            assert slots.releases == [None]


class TestALoopbackConnectionIsOneLocalDevice:
    """ADR-0131 §4: "all loopback connections count as a single local device"."""

    async def test_a_loopback_poll_claims_the_none_key(self, tmp_path: Path) -> None:
        """§4: not an approximation but the fact.

        "``admission is None`` on that listener and ADR-0084 §2 declined
        ``SO_PEERCRED`` as authorisation on it, so there is no identity to be had
        and none should be invented. Nor is one needed: ADR-0084 §1's ``0600`` bit
        means every loopback peer is the owner on the owner's own machine."
        """
        engine = _PollingEngine()
        slots = _Slots()
        async with _serving(engine, slots, tmp_path) as (peer, _):
            await _handshake(peer)
            await peer.send(_poll())
            await asyncio.wait_for(engine.poll_entered.wait(), 2)

            assert slots.held == [None]

    async def test_a_second_loopback_connection_is_the_same_device(self, tmp_path: Path) -> None:
        """§4, §2: two loopback pollers are one device, so the second closes."""
        first_engine = _PollingEngine()
        second_engine = _PollingEngine()
        slots = _Slots()
        async with (
            _serving(first_engine, slots, tmp_path, "a.sock") as (first, _),
            _serving(second_engine, slots, tmp_path, "b.sock") as (second, _),
        ):
            await _handshake(first)
            await first.send(_poll())
            await asyncio.wait_for(first_engine.poll_entered.wait(), 2)

            await _handshake(second)
            await second.send(_poll())

            assert await _closed(second)
            assert slots.held == [None]


class TestAListenerWithNoRegistryServesNoPoll:
    """A poll with nothing to claim against closes rather than claiming nothing."""

    async def test_a_poll_without_a_registry_closes(self, tmp_path: Path) -> None:
        """§2's rule could not be enforced, so the connection is not served.

        The safe direction: a listener that answered polls while enforcing no
        one-connection rule would hand out delivery slots the sub-bound cannot see.
        """
        engine = _PollingEngine()
        path = tmp_path / "n.sock"
        accepted: asyncio.Future[tuple[asyncio.StreamReader, asyncio.StreamWriter]] = (
            asyncio.get_running_loop().create_future()
        )

        async def _accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            accepted.set_result((reader, writer))

        server = await asyncio.start_unix_server(_accept, path=str(path))
        reader, writer = await asyncio.open_unix_connection(str(path))
        hub_reader, hub_writer = await accepted
        served = asyncio.ensure_future(
            serve_connection(engine, hub_reader, hub_writer, limits=_LIMITS)
        )
        try:
            peer = _Peer(reader, writer)
            await _handshake(peer)
            await peer.send(_poll())

            assert await _closed(peer)
        finally:
            writer.close()
            served.cancel()
            await asyncio.gather(served, return_exceptions=True)
            server.close()
            await server.wait_closed()


def test_the_delivery_method_is_the_one_the_protocol_declares() -> None:
    """The name the two closes turn on is the Protocol's, not a literal."""
    from ai_assistant.wire.server import DELIVERY_METHOD  # noqa: PLC0415 — asserted about
    from ai_assistant.wire.surface import METHODS  # noqa: PLC0415 — asserted about

    assert DELIVERY_METHOD in METHODS


@pytest.mark.parametrize("candidate_key", ["k1"])
def test_a_delivery_is_a_frozen_forbidding_model(candidate_key: str) -> None:
    """ADR-0131 §4: ``extra="forbid"`` is load-bearing rather than the house default.

    ``wire/client.py`` validates and *then* measures, so under pydantic's default
    an unknown member would be dropped by the validation before the measurement saw
    it — and a peer could send a conforming delivery plus a large unknown member,
    under the frame ceiling and over the contract limit.
    """
    with pytest.raises(ValueError, match="Extra inputs"):
        NotificationDelivery.model_validate(
            {
                "delivery_id": "1.abc",
                "notification": _CANDIDATE.model_dump(mode="json"),
                "smuggled": "x" * 16,
            }
        )
    assert _CANDIDATE.candidate_key == candidate_key
