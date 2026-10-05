"""The wire session seam and gate, through a served connection (ADR-0298 §1, §2, §6, §9).

A real :class:`~ai_assistant.wire.client.HubEngineClient` talks to a real
:func:`~ai_assistant.wire.server.serve_connection` over a socket, so what is
asserted is what crosses: the outbound name the client writes into the frame, the
requesting device the server decides from it and sets for the engine, and the
refusal a device receives as a reconstructed
:class:`~ai_assistant.core.errors.DeviceRefusedError`.

**Two regimes, and both are pinned.** Without a roster — every hub until the cutover
— every request runs as the hub's own machine and nothing is refused (§9:2). With
one, the roster decides the device and the route table's roster-only rows are
checked before dispatch (§2:1, §5:6). The second regime is built and tested here so
that the change passing a roster (§9:3) changes which device is decided and not
what the gate does with it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.device_context import acting_for, current_requesting_device
from ai_assistant.core.errors import (
    DEVICE_REFUSAL_MESSAGE_BYTES,
    DeviceRefusal,
    DeviceRefusedError,
)
from ai_assistant.core.types import (
    HUB_DEVICE_ID,
    HUB_REQUESTING_DEVICE,
    ChatDevice,
    DeviceAccess,
    DeviceRole,
    RequestingDevice,
)
from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.wire import envelope as env
from ai_assistant.wire.client import HubEngineClient
from ai_assistant.wire.codec import ENVELOPE_RESERVE_BYTES, canonical_payload
from ai_assistant.wire.credential import mint_credential
from ai_assistant.wire.errors import error_payload, raise_from_payload
from ai_assistant.wire.framing import read_frame, write_frame
from ai_assistant.wire.routes import ROWS, check_request
from ai_assistant.wire.server import AdmissionRefusal, ConnectionLimits, serve_connection

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ai_assistant.core.types import (
        Identifier,
    )

_PATIENT: Final = timedelta(seconds=5)
_FRAME: Final = 1 << 20
_LIMITS: Final = ConnectionLimits(max_frame_bytes=_FRAME, read_timeout=_PATIENT, build="test")
_PHONE: Final = RequestingDevice(device_id="phone", roles=frozenset({DeviceRole.COMMANDS}))
_BARE: Final = RequestingDevice(device_id="bare")


@dataclass
class _Roster:
    """A :class:`~ai_assistant.wire.server.DeviceRoster` a case scripts and reads back.

    Attributes:
        devices: The device each name decides, ``None`` standing for no name. A name
            absent here is refused as not accepted.
        asked: Every ``(connecting, acting_for)`` pair the wire asked about.
    """

    devices: dict[str | None, RequestingDevice] = field(default_factory=dict)
    asked: list[tuple[str, str | None]] = field(default_factory=list)

    def requesting_device(self, *, connecting: str, acting_for: str | None) -> RequestingDevice:
        """Answer as scripted, recording the question."""
        self.asked.append((connecting, acting_for))
        if acting_for not in self.devices:
            msg = "that device is not accepted under this gateway"
            raise DeviceRefusedError(msg, reason=DeviceRefusal.NOT_ACCEPTED)
        return self.devices[acting_for]

    def knows(self, device_id: str) -> bool:
        """Every scripted device is known."""
        return any(device.device_id == device_id for device in self.devices.values())


class _Recording(FakeAssistantEngine):
    """An engine that writes down which device each call ran as."""

    def __init__(self) -> None:
        """Start with nothing seen."""
        super().__init__()
        self.seen: list[RequestingDevice] = []

    async def forget(self, record_id: Identifier) -> bool:
        """Record the requesting device, then forget as the fake does."""
        self.seen.append(current_requesting_device())
        return await super().forget(record_id)


@contextlib.asynccontextmanager
async def _client(
    engine: FakeAssistantEngine, roster: _Roster | None, tmp_path: Path
) -> AsyncIterator[HubEngineClient]:
    """Serve on a socket and hand back a client of it."""
    path = tmp_path / "hub.sock"

    async def _hub(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await serve_connection(engine, reader, writer, limits=_LIMITS, roster=roster)

    server = await asyncio.start_unix_server(_hub, path=str(path))
    try:
        yield HubEngineClient(path, read_timeout=_PATIENT)
    finally:
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()


# --- before the cutover (§9:2) -----------------------------------------------


async def test_without_a_roster_every_request_runs_as_the_hub(tmp_path: Path) -> None:
    """§9:2: until the cutover the requesting device of every request is ``hub``.

    Even a request that names a browser device: the name crosses, and nothing is
    decided from it until a roster is passed.
    """
    engine = _Recording()
    async with _client(engine, None, tmp_path) as client:
        await client.forget("rec-1")
        with acting_for("phone"):
            await client.forget("rec-2")
    assert engine.seen == [HUB_REQUESTING_DEVICE, HUB_REQUESTING_DEVICE]


# --- the name on the wire (§1:5) and the device it decides (§2) ---------------


async def test_the_client_writes_the_outbound_name_and_the_engine_runs_as_its_device(
    tmp_path: Path,
) -> None:
    """§1:5 and §2:1-2: the gateway's value reaches the frame, the roster decides.

    On the local socket the connecting device is ``hub`` (§2:1); the request that
    names no device is the connecting device's own.
    """
    engine = _Recording()
    roster = _Roster(devices={None: HUB_REQUESTING_DEVICE, "phone": _PHONE})
    async with _client(engine, roster, tmp_path) as client:
        with acting_for("phone"):
            await client.forget("rec-1")
        await client.forget("rec-2")
    assert roster.asked == [(HUB_DEVICE_ID, "phone"), (HUB_DEVICE_ID, None)]
    assert engine.seen == [_PHONE, HUB_REQUESTING_DEVICE]


async def test_a_name_breaking_its_conditions_is_refused_before_any_io(tmp_path: Path) -> None:
    """§1:3, on the client's side: refused locally, as ADR-0085 §9 refuses an argument."""
    engine = _Recording()
    path = tmp_path / "nothing-listening.sock"
    client = HubEngineClient(path, read_timeout=_PATIENT)
    with acting_for(" padded "), pytest.raises(ValueError, match="surrounding space"):
        await client.forget("rec-1")
    assert engine.seen == []


# --- the refusal (§6) ---------------------------------------------------------


async def test_a_refused_request_is_answered_and_the_engine_is_never_called(
    tmp_path: Path,
) -> None:
    """§6:1: refused before its operation has changed anything, with its reason."""
    engine = _Recording()
    roster = _Roster(devices={"bare": _BARE})
    async with _client(engine, roster, tmp_path) as client:
        with acting_for("bare"), pytest.raises(DeviceRefusedError) as refused:
            await client.forget("rec-1")
        with acting_for("revoked"), pytest.raises(DeviceRefusedError) as unnamed:
            await client.forget("rec-1")
    assert refused.value.reason is DeviceRefusal.NOT_ALLOWED
    assert unnamed.value.reason is DeviceRefusal.NOT_ACCEPTED
    assert engine.seen == []


async def test_a_gateway_naming_the_hub_is_refused_before_the_roster_is_asked(
    tmp_path: Path,
) -> None:
    """§3:3: no gateway may name ``hub``, whatever the roster would have said."""
    engine = _Recording()
    roster = _Roster(devices={"hub": HUB_REQUESTING_DEVICE})
    async with _client(engine, roster, tmp_path) as client:
        with acting_for(HUB_DEVICE_ID), pytest.raises(DeviceRefusedError) as refused:
            await client.forget("rec-1")
    assert refused.value.reason is DeviceRefusal.NOT_ACCEPTED
    assert roster.asked == []
    assert engine.seen == []


async def test_a_refusal_leaves_the_connection_open(tmp_path: Path) -> None:
    """§6's commentary: a gateway's connection serves other devices, so it stays up.

    Written by hand, because the shipped client opens a connection per call: one
    connection carries a refused request and then an admitted one.
    """
    engine = _Recording()
    roster = _Roster(devices={"phone": _PHONE})
    path = tmp_path / "hub.sock"

    async def _hub(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await serve_connection(engine, reader, writer, limits=_LIMITS, roster=roster)

    server = await asyncio.start_unix_server(_hub, path=str(path))
    try:
        peer = await _Peer.open(path)
        await peer.send(
            env.Envelope(
                kind=env.FrameKind.CONNECT, id="c-0", payload=env.connect_payload(client="gw")
            )
        )
        await peer.receive()
        answers = []
        for correlation, name in (("c-1", "revoked"), ("c-2", "phone")):
            await peer.send(_forget(correlation, acting_for=name))
            answers.append(await peer.receive())
        peer.writer.close()
    finally:
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()
    assert [answer.kind for answer in answers] == [env.FrameKind.ERROR, env.FrameKind.RESULT]
    assert answers[0].payload["code"] == "DeviceRefusedError"
    assert answers[0].payload["details"] == {"reason": "not_accepted"}
    assert engine.seen == [_PHONE]


async def test_the_remote_listeners_connecting_device_is_its_admitted_identity(
    tmp_path: Path,
) -> None:
    """§2:1: on the remote listener the connecting device is ``Admission.device``."""
    engine = _Recording()
    roster = _Roster(devices={None: _PHONE})
    path = tmp_path / "remote.sock"

    async def _hub(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await serve_connection(
            engine, reader, writer, limits=_LIMITS, admission=_Admitting(), roster=roster
        )

    server = await asyncio.start_unix_server(_hub, path=str(path))
    try:
        peer = await _Peer.open(path)
        await peer.send(
            env.Envelope(
                kind=env.FrameKind.CONNECT,
                id="c-0",
                payload=env.connect_payload(client="laptop", credential=mint_credential()),
            )
        )
        assert (await peer.receive()).kind is env.FrameKind.CONNECT_ACK
        await peer.send(_forget("c-1"))
        answer = await peer.receive()
        peer.writer.close()
    finally:
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()
    assert answer.kind is env.FrameKind.RESULT
    assert roster.asked == [("laptop.tailnet", None)]


def test_every_refusal_this_lane_writes_fits_unreduced_at_the_floor() -> None:
    """``DeviceRefusedError``'s required reason is safe because nothing reduces it.

    ADR-0085 §10a reduces an error payload that does not fit by dropping its
    details, and a reduced ``DeviceRefusedError`` could not be reconstructed. At
    ADR-0085 §8d's 1024-byte floor the contract limit is 512 bytes; every refusal
    the gate writes, for the longest method on the surface, fits there with its
    reason intact.
    """
    floor_limit = env.MIN_FRAME_BYTES - ENVELOPE_RESERVE_BYTES
    longest = "x" * max(len(name) for methods in ROWS.values() for name in methods)
    unknown = {"devices": (ChatDevice(device_id="stranger", access=DeviceAccess.READ),)}
    cases = [
        *((max(methods, key=len), {}, _BARE, None) for methods in ROWS.values()),
        ("next_notification", {}, _BARE, "x" * 128),
        ("set_conversation_devices", unknown, _PHONE, None),
        (longest, {}, _BARE, None),
    ]
    refusals: list[DeviceRefusedError] = []
    for method, arguments, device, name in cases:
        try:
            check_request(method, arguments, device=device, acting_for=name, knows=lambda _: False)
        except DeviceRefusedError as exc:
            refusals.append(exc)
    assert refusals
    for refusal in refusals:
        payload = error_payload(refusal, max_bytes=floor_limit)
        assert payload["reduced"] is False, str(refusal)
        assert payload["details"] == {"reason": refusal.reason.value}


@pytest.mark.parametrize("reason", list(DeviceRefusal))
@pytest.mark.parametrize("message", ["x" * DEVICE_REFUSAL_MESSAGE_BYTES, "\u0007" * 64])
def test_the_longest_refusal_crosses_unreduced_at_the_floor(
    message: str, reason: DeviceRefusal
) -> None:
    """The constructor's bound, against the wire's own measurement.

    A message at the bound — or one whose escapes take it to its 384 bytes, since the
    bound counts what the codec writes — fits ADR-0085 §8d's floor with its reason,
    and round-trips through the bytes to the reason the hub raised.
    """
    refusal = DeviceRefusedError(message, reason=reason)
    payload = error_payload(refusal, max_bytes=env.MIN_FRAME_BYTES - ENVELOPE_RESERVE_BYTES)
    assert payload["reduced"] is False
    with pytest.raises(DeviceRefusedError) as rebuilt:
        raise_from_payload(json.loads(canonical_payload(payload)))
    assert rebuilt.value.reason is reason
    assert rebuilt.value.details_elided is False


@pytest.mark.parametrize("message", ["x" * (DEVICE_REFUSAL_MESSAGE_BYTES + 1), "\u0007" * 65])
def test_a_refusal_too_long_to_cross_whole_is_refused_where_it_is_made(message: str) -> None:
    """A reduced payload would lose the required reason, so it is never built."""
    with pytest.raises(ValueError, match=str(DEVICE_REFUSAL_MESSAGE_BYTES)):
        DeviceRefusedError(message, reason=DeviceRefusal.NOT_ACCEPTED)


def test_only_the_wire_server_sets_the_requesting_device() -> None:
    """§2:4: the context value's setter is called by the wire server and nothing else."""
    source = Path(__file__).resolve().parents[2] / "src" / "ai_assistant"
    callers = sorted(
        str(module.relative_to(source))
        for module in source.rglob("*.py")
        if re.search(r"\bserving_device\(", module.read_text(encoding="utf-8"))
    )
    assert callers == ["core/device_context.py", "wire/server.py"]


# --- helpers -----------------------------------------------------------------


@dataclass
class _Peer:
    """One end of a socket, with the two frame operations a hand-written case needs."""

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter

    @classmethod
    async def open(cls, path: Path) -> _Peer:
        """Connect to a served socket."""
        reader, writer = await asyncio.open_unix_connection(str(path))
        return cls(reader, writer)

    async def send(self, frame: env.Envelope) -> None:
        """Write one frame."""
        await write_frame(self.writer, env.encode_envelope(frame), max_frame_bytes=_FRAME)

    async def receive(self) -> env.Envelope:
        """Read one frame."""
        body = await read_frame(
            self.reader, max_frame_bytes=_FRAME, timeout=_PATIENT, idle_timeout=_PATIENT
        )
        return env.decode_envelope(body)


def _forget(correlation: str, *, acting_for: str | None = None) -> env.Envelope:
    """A ``forget`` request, relayed for ``acting_for`` where one is given."""
    return env.Envelope(
        kind=env.FrameKind.REQUEST,
        id=correlation,
        payload={"record_id": "rec-1"},
        method="forget",
        acting_for=acting_for,
    )


class _Admitting:
    """An :class:`~ai_assistant.wire.server.Admission` that admits one named device."""

    def admit(self, credential: str) -> AdmissionRefusal | None:
        """Admit."""
        return None

    def is_live(self) -> bool:
        """Always live."""
        return True

    def device(self) -> str:
        """The overlay identity admission established."""
        return "laptop.tailnet"

    def record_refusal(self, code: str) -> None:
        """Nothing is refused here."""
