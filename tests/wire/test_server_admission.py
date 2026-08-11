"""The admission seam and ADR-0124 §8's finality, at the wire (not the listener).

The listener's own concerns — binding, the agent, the record — are in
``tests/service/test_remote_listener.py``. What is here is the protocol half: the
credential rule forking on which listener a frame reached, and the two liveness
checks §8 requires, exercised with the schedule under the test's control.

**§8 names the forced interleaving as this lane's obligation and this file is
where it is discharged:** "the indivisibility above is exercised by making a
revocation land between the check and the write, which is a thing a test does to
its own process and not a thing two laptops can be made to do on cue".
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.wire import envelope as env
from ai_assistant.wire.credential import mint_credential
from ai_assistant.wire.framing import read_frame, write_frame
from ai_assistant.wire.server import AdmissionRefusal, ConnectionLimits, serve_connection

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from pathlib import Path

    from ai_assistant.core.types import BeliefBand, BeliefSummary, MemoryKind

_PATIENT: Final = timedelta(seconds=5)
_FRAME: Final = 1 << 20
_LIMITS: Final = ConnectionLimits(max_frame_bytes=_FRAME, read_timeout=_PATIENT, build="test")
_VALID: Final = mint_credential()


@dataclass
class _ScriptedAdmission:
    """An :class:`~ai_assistant.wire.server.Admission` a test drives by hand.

    Attributes:
        refusal: What :meth:`admit` answers, or ``None`` to admit.
        refusals: Every code the wire recorded against this connection, so a test
            can assert that a refusal decided before :meth:`admit` was still
            recorded with its device (ADR-0124 §6).
        live: What :meth:`is_live` answers. A test flips it at the instant it wants
            a revocation to land, which is the whole point of this class.
        credentials: Every value that reached :meth:`admit`, so a test can assert
            that a malformed one never did (ADR-0124 §7).
        liveness_checks: How many times the wire asked, so a check that was quietly
            dropped from a write path fails rather than passing silently.
    """

    refusal: AdmissionRefusal | None = None
    live: bool = True
    refusals: list[str] = field(default_factory=list)
    credentials: list[str] = field(default_factory=list)
    liveness_checks: int = 0

    def admit(self, credential: str) -> AdmissionRefusal | None:
        """Record the credential and answer with whatever the case scripted."""
        self.credentials.append(credential)
        return self.refusal

    def is_live(self) -> bool:
        """Answer, and count the asking."""
        self.liveness_checks += 1
        return self.live

    def record_refusal(self, code: str) -> None:
        """Keep what the wire asked to be recorded."""
        self.refusals.append(code)

    def device(self) -> str:
        """The identity ADR-0124 §4 established, which §2 keys a slot on."""
        return "a-device"


class _GatedEngine(FakeAssistantEngine):
    """An engine whose ``beliefs`` waits until the test lets it finish.

    That is what makes §8's interleaving *forced* rather than hoped for: the
    revocation lands while the dispatch is suspended, so the write that follows is
    the one the clause is about, every run.
    """

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
class _Peer:
    """One end of a socket pair, with the two frame operations a case needs."""

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
    engine: FakeAssistantEngine,
    admission: _ScriptedAdmission | None,
    tmp_path: Path,
) -> AsyncIterator[tuple[_Peer, asyncio.Task[None]]]:
    """Serve one connection over a real socket, so the framing is exercised too."""
    path = tmp_path / "s.sock"
    accepted: asyncio.Future[tuple[asyncio.StreamReader, asyncio.StreamWriter]] = (
        asyncio.get_running_loop().create_future()
    )

    async def _accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        accepted.set_result((reader, writer))

    server = await asyncio.start_unix_server(_accept, path=str(path))
    reader, writer = await asyncio.open_unix_connection(str(path))
    hub_reader, hub_writer = await accepted
    served = asyncio.ensure_future(
        serve_connection(engine, hub_reader, hub_writer, limits=_LIMITS, admission=admission)
    )
    try:
        yield _Peer(reader, writer), served
    finally:
        writer.close()
        served.cancel()
        await asyncio.gather(served, return_exceptions=True)
        server.close()
        await server.wait_closed()


#: The default for :func:`_connect`, meaning **omit the member**.
#:
#: ``None`` cannot serve as that default, and the difference is a ruled one: ADR-0124
#: §7 refuses an absent credential with ``credential_required`` and a present
#: ``null`` — "present and… not a string" — with ``credential_rejected``, so a helper
#: whose "leave it out" spelling *is* ``None`` cannot put the second case on the wire
#: at all. Issue #917 is what that costs: the arm reached a live hub untested.
_OMITTED: Final = object()


def _connect(credential: object = _OMITTED) -> env.Envelope:
    """A connect frame carrying whatever a case needs in its credential member.

    Args:
        credential: The member's value — ``None`` included, which the codec writes
            as a JSON ``null``. :data:`_OMITTED` leaves the member out entirely.

    Returns:
        The connect frame.
    """
    payload: dict[str, Any] = {
        env.CONNECT_VERSION: env.PROTOCOL_VERSION,
        env.CONNECT_CLIENT: "assistant-cli",
    }
    if credential is not _OMITTED:
        payload[env.CONNECT_CREDENTIAL] = credential
    return env.Envelope(kind=env.FrameKind.CONNECT, id="c-0", payload=payload)


async def test_a_credential_reaches_admission_only_when_it_is_well_formed(
    tmp_path: Path,
) -> None:
    """ADR-0124 §7: a malformed credential "never reaches the verifier or the
    comparison", and is refused "as a credential that did not verify".

    The two halves are asserted together: the refusal code the peer reads, and the
    fact that ``admit`` was never called. Either alone would pass an implementation
    that hashed the malformed value and happened to get no match.
    """
    admission = _ScriptedAdmission()
    async with _serving(FakeAssistantEngine(), admission, tmp_path) as (peer, _):
        await peer.send(_connect("not-a-credential"))
        reply = await peer.receive()
    assert reply.kind is env.FrameKind.ERROR
    assert reply.payload["code"] == env.CREDENTIAL_REJECTED
    assert admission.credentials == []
    assert admission.refusals == [env.CREDENTIAL_REJECTED]
    # ADR-0124 §6: "each admission and each refusal with the device it named". A
    # refusal decided by the frame reader never reaches ``admit``, so without this
    # the hub would answer the peer and record nothing about who it was.
    assert admission.refusals == [env.CREDENTIAL_REJECTED]


async def test_a_missing_credential_is_refused_by_its_own_code(tmp_path: Path) -> None:
    """ADR-0124 §7: absent or empty is "refused, with a distinct error naming the
    reason, and the connection closes after the refusal".

    "A client admitted without presenting a credential, on a listener whose whole
    purpose is that something is checked, has been told by admission that it was
    admitted on a check that never ran."
    """
    admission = _ScriptedAdmission()
    async with _serving(FakeAssistantEngine(), admission, tmp_path) as (peer, _):
        await peer.send(_connect())
        reply = await peer.receive()
    assert reply.payload["code"] == env.CREDENTIAL_REQUIRED
    assert admission.credentials == []
    assert admission.refusals == [env.CREDENTIAL_REQUIRED]


async def test_a_refused_device_reads_the_code_the_hub_decided(tmp_path: Path) -> None:
    """The admission's own refusal reaches the frame, code and message together.

    Parametrised over the codes rather than one, because §7's whole point is that
    the three reasons are distinguishable — a wire that flattened them to one code
    would pass a single-case test.
    """
    for code in (env.DEVICE_NOT_ENROLLED, env.DEVICE_REVOKED, env.CREDENTIAL_REJECTED):
        admission = _ScriptedAdmission(refusal=AdmissionRefusal(code=code, message=f"no: {code}"))
        async with _serving(FakeAssistantEngine(), admission, tmp_path) as (peer, _):
            await peer.send(_connect(_VALID))
            reply = await peer.receive()
        assert reply.payload["code"] == code
        assert reply.payload["message"] == f"no: {code}"
        assert admission.credentials == [_VALID]


async def test_an_admitted_device_is_served(tmp_path: Path) -> None:
    """The discriminating case: a wire that refused everything would pass above."""
    admission = _ScriptedAdmission()
    async with _serving(FakeAssistantEngine(), admission, tmp_path) as (peer, _):
        await peer.send(_connect(_VALID))
        assert (await peer.receive()).kind is env.FrameKind.CONNECT_ACK
        await peer.send(
            env.Envelope(kind=env.FrameKind.REQUEST, id="r-0", payload={}, method="beliefs")
        )
        reply = await peer.receive()
    assert reply.kind is env.FrameKind.RESULT


async def test_a_revocation_that_lands_before_the_reply_writes_no_reply(tmp_path: Path) -> None:
    """ADR-0124 §8's handshake limb: "the hub writes no further frame to that device
    on any connection".

    The admission claims the enrolment and the revocation lands in the same breath,
    which is the state a rotation leaves a mid-handshake connection in. The peer
    reads a close rather than an ack.
    """

    class _RevokedOnClaim(_ScriptedAdmission):
        def admit(self, credential: str) -> AdmissionRefusal | None:
            self.live = False
            return super().admit(credential)

    async with _serving(FakeAssistantEngine(), _RevokedOnClaim(), tmp_path) as (peer, served):
        await peer.send(_connect(_VALID))
        assert await peer.reader.read() == b""
        await asyncio.wait_for(served, timeout=_PATIENT.total_seconds())


async def test_a_revocation_landing_during_a_dispatch_abandons_the_response(tmp_path: Path) -> None:
    """**ADR-0124 §8's named unit-level obligation for this lane.**

    > Once a revocation has taken effect, the hub writes no further frame to that
    > device on any connection — **including the response to a request dispatched
    > before the revocation, which is abandoned rather than delivered.**

    The schedule is forced rather than hoped for: the engine suspends inside the
    call, the revocation lands while it is suspended, and only then is the call
    released. So the write that follows is exactly the one the clause governs, on
    every run — "a request dispatched a moment before a revocation may be awaiting a
    model provider for seconds; if the rule stopped at dispatch, the hub would finish
    that work and write the answer to a device the owner has expelled".

    What is asserted is the absence of a frame, which is the whole clause: the peer
    reads end-of-stream, not a result and not an error.
    """
    engine = _GatedEngine()
    admission = _ScriptedAdmission()
    async with _serving(engine, admission, tmp_path) as (peer, served):
        await peer.send(_connect(_VALID))
        assert (await peer.receive()).kind is env.FrameKind.CONNECT_ACK
        await peer.send(
            env.Envelope(kind=env.FrameKind.REQUEST, id="r-0", payload={}, method="beliefs")
        )
        await asyncio.wait_for(engine.entered.wait(), timeout=_PATIENT.total_seconds())

        # The revocation lands here — after the dispatch began and before the reply
        # is written, which is the gap §8's second paragraph says a near-miss
        # implementation leaves open.
        admission.live = False
        engine.release.set()

        assert await peer.reader.read() == b""
        await asyncio.wait_for(served, timeout=_PATIENT.total_seconds())
    # The engine really did run: a hub that refused before dispatching would satisfy
    # the assertion above for the wrong reason, and §8 fixes the linearization at the
    # write precisely because the work may already have happened.
    assert ("beliefs", {}) in [(name, {}) for name, _ in engine.calls]


async def test_a_revocation_landing_before_a_dispatch_runs_no_engine_call(tmp_path: Path) -> None:
    """ADR-0124 §8's first limb: "no request is dispatched on such a connection, and
    the connection is closed rather than served".

    The pair with the test above is what makes both checks real: there the engine
    ran and the answer was abandoned; here the engine is never reached at all. An
    implementation holding only the write-side check would pass that one and dispatch
    here, which is the work §8 says a revoked device does not get.
    """
    engine = _GatedEngine()
    engine.release.set()
    admission = _ScriptedAdmission()
    async with _serving(engine, admission, tmp_path) as (peer, served):
        await peer.send(_connect(_VALID))
        assert (await peer.receive()).kind is env.FrameKind.CONNECT_ACK
        admission.live = False
        await peer.send(
            env.Envelope(kind=env.FrameKind.REQUEST, id="r-0", payload={}, method="beliefs")
        )
        assert await peer.reader.read() == b""
        await asyncio.wait_for(served, timeout=_PATIENT.total_seconds())
    assert engine.calls == []


async def test_the_loopback_listener_is_untouched_by_any_of_it(tmp_path: Path) -> None:
    """ADR-0124 §7: "ADR-0084 §2's rule is unchanged on the loopback transport: there
    a non-empty credential is still refused with ``credential_not_supported``."

    Driven through the same function with ``admission=None``, which is what makes
    "the two listeners hold opposite rules" a property of one code path rather than
    of two implementations that agree today. The liveness check is never asked,
    because no enrolment governs a loopback connection and there is nothing to
    revoke.
    """
    async with _serving(FakeAssistantEngine(), None, tmp_path) as (peer, _):
        await peer.send(_connect(_VALID))
        reply = await peer.receive()
    assert reply.payload["code"] == env.CREDENTIAL_NOT_SUPPORTED

    async with _serving(FakeAssistantEngine(), None, tmp_path) as (peer, _):
        await peer.send(_connect())
        assert (await peer.receive()).kind is env.FrameKind.CONNECT_ACK

    # A present ``null`` is admitted here and refused on the remote listener, and
    # both answers come from the same frozen clause: this transport refuses a
    # **non-empty** credential, and a ``null`` is a client saying it carries none.
    # Pinned at the wire because that is where the divergence would be observable —
    # the reader's half is in ``test_remote_connect.py``.
    async with _serving(FakeAssistantEngine(), None, tmp_path) as (peer, _):
        await peer.send(_connect(None))
        assert (await peer.receive()).kind is env.FrameKind.CONNECT_ACK


async def test_the_wire_asks_before_every_frame_it_writes(tmp_path: Path) -> None:
    """The ordering §8 requires, counted rather than inferred.

    An implementation that dropped either check would still pass the two revocation
    tests above if it happened to close for another reason, so the count is what
    pins that the ask is on the path: one at the connect reply, one at dispatch and
    one at the reply's write.
    """
    admission = _ScriptedAdmission()
    async with _serving(FakeAssistantEngine(), admission, tmp_path) as (peer, _):
        await peer.send(_connect(_VALID))
        assert (await peer.receive()).kind is env.FrameKind.CONNECT_ACK
        assert admission.liveness_checks == 1
        await peer.send(
            env.Envelope(kind=env.FrameKind.REQUEST, id="r-0", payload={}, method="beliefs")
        )
        assert (await peer.receive()).kind is env.FrameKind.RESULT
    assert admission.liveness_checks == 3


@pytest.mark.parametrize("credential", [1, {"a": 1}, [1], True, None])
async def test_a_credential_of_the_wrong_type_never_reaches_admission(
    credential: object, tmp_path: Path
) -> None:
    """§7's type clause, at the wire rather than at the reader.

    The reader's own refusal is pinned in ``test_remote_connect.py``; what this adds
    is that the refusal survives to a *frame* with the right code, rather than
    becoming "an uncaught type error that closes the connection with no refusal" —
    which §7 names as one of the three ways implementations diverge here.

    **``None`` is in the list and it is the case issue #917 caught in a live hub**: a
    present ``null`` is "present and… not a string", so it takes this code and not
    the absent member's — and the code is the whole of what the peer and the hub's
    own refusal record are told, which is what §7 requires distinguished.
    """
    admission = _ScriptedAdmission()
    async with _serving(FakeAssistantEngine(), admission, tmp_path) as (peer, _):
        await peer.send(_connect(credential))
        reply = await peer.receive()
    assert reply.payload["code"] == env.CREDENTIAL_REJECTED
    assert admission.credentials == []
