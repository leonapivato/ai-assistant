"""The seam's own channel and opener, run through the shared conformance suites.

ADR-0191 §1 fixes one buffering ceiling and one refusal type in ``core`` "so the
canonical fake and the production implementation refuse the same inputs and a
consumer tested against one behaves against the other", and ``CONTRIBUTING.md``
makes the shared suite what every implementation is held to. So the two production
implementations — ``_StreamChannel`` and
:class:`~ai_assistant.tools.egress.StreamOutboundTransport` — are bound to
``ByteChannelContract`` and ``OutboundTransportContract`` here, exactly as
``tests/core/test_fake_transport.py`` binds the canonical fakes.

**Nothing here opens a socket.** The read half is an ``asyncio.StreamReader`` fed
in memory, the write half is a double, and ``asyncio.open_connection`` is
substituted by a ledger that models the acquisition and the release without one.
The substitution is what lets the opener's release obligations be observed at all:
the resource ``open_channel`` acquires is a pair of streams, and nothing on the
public surface says whether they were given back.

Beside the two bindings are the properties that are the *seam's own* rather than
the contract's — which endpoint the opener asks for, and that the capability holds
nothing between calls.
"""

from __future__ import annotations

import asyncio
import ssl
from typing import TYPE_CHECKING, Final, cast, final

import pytest
import structlog
from transport_contract import ENDPOINT, ByteChannelContract, OutboundTransportContract

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import TransportError
from ai_assistant.core.logging import configure_logging
from ai_assistant.core.types import TRANSPORT_OCTET_CEILING, TransportEndpoint
from ai_assistant.testing.cancellation import LoopSuspension, settle
from ai_assistant.tools import egress
from ai_assistant.tools.egress import StreamOutboundTransport

if TYPE_CHECKING:
    from ai_assistant.core.protocols import ByteChannel, OutboundTransport
    from ai_assistant.testing.cancellation import SuspendedCall

#: The upgrade-mode endpoint, for the cases that branch on the TLS mode.
UPGRADE: Final = TransportEndpoint(host=ENDPOINT.host, port=587, implicit_tls=False)


@final
class _Writer:
    """The write half, without a transport under it.

    Enough of ``asyncio.StreamWriter`` for the channel to drive, plus the two
    levers ``ByteChannelContract`` needs: an armable connection failure and a
    suspension inside ``wait_closed``, which is where a cancellation delivered to
    ``close`` actually lands.
    """

    def __init__(self, *, ledger: _Sockets | None = None) -> None:
        """Start open, having written nothing.

        Args:
            ledger: The acquisition ledger to report this writer's release to, for
                the opener's cases. ``None`` for the channel's own cases, which
                have nothing to count.
        """
        self.written = bytearray()
        self.closed = False
        self.drains = 0
        self.tls: str | None = None
        self.fails = False
        self.fails_to_close = False
        self.releases_before_it_fails = True
        self.aborts = 0
        self.close_gate: LoopSuspension | None = None
        self.holds_the_close_waiter = False
        self.released = False
        self._waiter: asyncio.Future[None] | None = None
        self._ledger = ledger

    @property
    def close_waiter(self) -> asyncio.Future[None]:
        """The **shared** future ``wait_closed`` awaits, as the standard library has.

        ``StreamWriter.wait_closed`` awaits the protocol's one close waiter rather
        than a fresh awaitable per call, which is why a cancellation delivered
        there is not confined to the call that took it: the future itself ends up
        cancelled and every later ``wait_closed`` raises. A double that suspended
        on something private per call could not reproduce that, and round 10 of
        review is where it mattered.

        Returns:
            The waiter, made on first use so it belongs to the running loop.
        """
        if self._waiter is None:
            self._waiter = asyncio.get_running_loop().create_future()
        return self._waiter

    @property
    def transport(self) -> _Transport:
        """The transport under this writer, for the abort path.

        ``StreamWriter.close`` delegates to it, and production reaches past the
        writer to it when a close raises — a close that failed may have failed
        *before* releasing anything, and no channel reached a holder, so nothing
        else will ever try again.

        Returns:
            A stand-in that gives the socket back when it is aborted.
        """
        return _Transport(self)

    def write(self, data: bytes) -> None:
        """Record ``data``."""
        self.written += data

    async def drain(self) -> None:
        """Record that the caller flushed, or fail as a reset connection would.

        Raises:
            ConnectionResetError: Where this writer was armed to fail.
        """
        if self.fails:
            msg = "the peer reset the connection"
            raise ConnectionResetError(msg)
        self.drains += 1

    async def start_tls(self, context: ssl.SSLContext, *, server_hostname: str) -> None:
        """Record which host the certificate would have been verified against.

        Args:
            context: The TLS settings, asserted here so a later weakening of
                ``_tls_context`` fails a case rather than a deployment.
            server_hostname: The name the certificate is verified against.

        Raises:
            ssl.SSLError: Where this writer was armed to fail.
        """
        assert context.check_hostname is True
        assert context.verify_mode is ssl.CERT_REQUIRED
        if self.fails:
            msg = "the certificate did not verify"
            raise ssl.SSLError(msg)
        self.tls = server_hostname

    def close(self) -> None:
        """Record that the writer was closed, and give its socket back.

        **Whether it gives the socket back before it fails is armable**, and the
        harder arrangement is the honest one: a close that raised may have raised
        on its first statement, having released nothing. A double that always
        released first would let an unguarded caller pass a case about the guard.
        Adversarial review found that on round 6.

        Raises:
            OSError: Where this writer was armed to fail *synchronously*, which a
                transport that is already broken does. The channel's ``close``
                must swallow it like any other release failure, and an earlier
                draft called it outside the guard.
        """
        if self.fails_to_close and not self.releases_before_it_fails:
            msg = "the transport was already broken"
            raise OSError(msg)
        if self.holds_the_close_waiter:
            # A far end that has stopped reading: the socket is closing and the
            # waiter stays unsettled until something drops the transport.
            self.closed = True
            return
        self.give_the_socket_back()
        if self.fails_to_close:
            msg = "the transport was already broken"
            raise OSError(msg)

    def give_the_socket_back(self) -> None:
        """Report this writer's release to the ledger, once, and settle the waiter.

        Settling it is what the standard library's ``connection_lost`` does, and
        it is why an ``abort`` unblocks a ``wait_closed`` that a far end was
        holding open.
        """
        if not self.released and self._ledger is not None:
            self._ledger.open -= 1
        self.released = True
        self.closed = True
        if self._waiter is not None and not self._waiter.done():
            self._waiter.set_result(None)

    async def wait_closed(self) -> None:
        """Wait for the close, suspending or failing where this writer was armed.

        Raises:
            OSError: Where this writer was armed to fail, which is the ordinary
                release failure ADR-0191 §1 has ``close`` swallow.
        """
        gate, self.close_gate = self.close_gate, None
        if gate is not None:
            await gate.hold()
        if self.fails or self.fails_to_close:
            msg = "the far end had already gone"
            raise OSError(msg)
        if self.released:
            return
        await self.close_waiter


@final
class _Transport:
    """What a writer delegates its release to, so an ``abort`` can be observed.

    Only the one method production reaches for, and it releases unconditionally:
    that is what ``abort`` is — the release that does not wait on a far end and
    does not fail for one.

    Attributes:
        writer: The writer whose socket this gives back.
    """

    def __init__(self, writer: _Writer) -> None:
        """Bind this transport to its writer.

        Args:
            writer: The write half above it.
        """
        self.writer = writer

    def abort(self) -> None:
        """Drop the connection, giving the socket back however close went."""
        self.writer.aborts += 1
        self.writer.give_the_socket_back()


@final
class _Handoff:
    """A suspension a cancellation does not reach, and that completes on release.

    :class:`~ai_assistant.testing.cancellation.LoopSuspension` defers a
    cancellation and then re-raises it, which models work the caller's own task
    owns. What is wanted here is the opposite: production *shields* the open, so
    the open is not cancelled and finishes normally while the caller is already
    gone. This is that shape, and it is the arrangement under which the release
    being measured can only be production's.
    """

    def __init__(self) -> None:
        """Create an unreached, unreleased handoff."""
        self._entered = asyncio.Event()
        self._released = asyncio.Event()

    async def held(self) -> None:
        """Announce arrival and wait, uncancellably from the caller's side."""
        self._entered.set()
        await self._released.wait()

    async def reached(self) -> None:
        """Wait until the open has arrived at its suspension point."""
        async with asyncio.timeout(5.0):
            await self._entered.wait()

    def release(self) -> None:
        """Let the open finish."""
        self._released.set()


@final
class _Sockets:
    """A stand-in for ``asyncio.open_connection`` that counts what it hands out.

    The opener's release clauses are stated over a resource the production
    ``open_channel`` obtains from the standard library and gives back by closing
    the writer. Nothing on the public surface reports that, so the suite's
    ``held_resources`` hook needs a ledger — and this is the smallest thing that
    is one.

    **It also models where the cancellation window actually is.** The window
    ADR-0060 §1 has bite over is not inside ``open_connection`` — a cancellation
    there is one CPython cleans up after — but *between* the open completing and
    ``open_channel`` receiving its streams. Production shields the open for
    exactly that reason, and this substitute reproduces the window by suspending
    while its streams exist and then completing normally, cleaning nothing up.

    Attributes:
        open: Pairs of streams handed out and not yet closed.
        refuses: Whether the next open fails before anything is acquired.
        asked: The arguments the last open was called with.
        gate: A suspension to hold the next open at, after its socket exists.
        breaks_on_close: Whether the writer it hands out raises from its
            *synchronous* ``close``, as one over an already-broken transport
            does.
        releases_before_it_fails: Whether that failing close gives the socket
            back before it raises. ``False`` is the harder and more honest
            arrangement — a close can fail on its first statement — and it is
            what makes a case about the abort path bite.
        handed: The last writer it handed out, for the cases that read what
            happened to it.
    """

    def __init__(self) -> None:
        """Start having opened nothing, refusing nothing and holding nothing."""
        self.open = 0
        self.refuses = False
        self.asked: dict[str, object] = {}
        self.gate: _Handoff | None = None
        self.breaks_on_close = False
        self.releases_before_it_fails = True
        self.handed: _Writer | None = None

    async def __call__(
        self, host: str, port: int, **kwargs: object
    ) -> tuple[asyncio.StreamReader, _Writer]:
        """Hand out a pair of streams, or refuse as an unreachable endpoint would.

        Args:
            host: The host asked for.
            port: The port asked for.
            kwargs: Whatever else the caller passed, recorded for the cases that
                assert on it.

        Returns:
            A reader fed nothing and a writer that reports its release here.

        Raises:
            ConnectionRefusedError: Where this ledger was armed to refuse. Nothing
                is acquired first, which is what distinguishes it from
                ``arm_failure_after_acquiring``.
        """
        self.asked = {"host": host, "port": port, **kwargs}
        if self.refuses:
            msg = "nothing is listening"
            raise ConnectionRefusedError(msg)
        self.open += 1
        writer = _Writer(ledger=self)
        writer.fails_to_close = self.breaks_on_close
        writer.releases_before_it_fails = self.releases_before_it_fails
        self.handed = writer
        gate, self.gate = self.gate, None
        if gate is not None:
            # Held *after* the streams exist and released into a normal return.
            # It cleans nothing up on the caller's cancellation, deliberately: a
            # substitute that tidied after itself would be the thing the
            # conformance case measured.
            await gate.held()
        return asyncio.StreamReader(limit=TRANSPORT_OCTET_CEILING), writer


def _reader_of(channel: ByteChannel) -> asyncio.StreamReader:
    """The read half under ``channel``.

    Args:
        channel: The subject, which is a ``_StreamChannel``.

    Returns:
        Its reader, so a binding can say what the far end sent.
    """
    assert isinstance(channel, egress._StreamChannel)
    return channel._reader


def _writer_of(channel: ByteChannel) -> _Writer:
    """The write half under ``channel``.

    Args:
        channel: The subject, which is a ``_StreamChannel``.

    Returns:
        Its writer double, so a binding can arm it.
    """
    assert isinstance(channel, egress._StreamChannel)
    # The channel's annotation says ``StreamWriter``; what it was handed is the
    # double above, which cannot be a subclass of one and so cannot be narrowed by
    # ``isinstance``. The cast is the seam between the two, and a channel handed
    # anything else fails on the attribute rather than silently.
    writer = cast("_Writer", channel._writer)
    assert isinstance(writer.written, bytearray)
    return writer


def _channel(*, secure: bool = False, ledger: _Sockets | None = None) -> ByteChannel:
    """One production channel over an in-memory read half and a writer double.

    Args:
        secure: Whether TLS was established before the greeting.
        ledger: Where the writer reports its release, for a case that counts.

    Returns:
        The channel.
    """
    return cast(
        "ByteChannel",
        egress._StreamChannel(
            asyncio.StreamReader(limit=TRANSPORT_OCTET_CEILING),
            cast("asyncio.StreamWriter", _Writer(ledger=ledger)),
            host=ENDPOINT.host,
            secure=secure,
        ),
    )


class TestStreamChannelContract(ByteChannelContract):
    """The production channel, run through the channel contract."""

    @pytest.fixture
    async def channel(self) -> ByteChannel:
        """A channel in the clear over a reader nothing has been fed to yet.

        **Asynchronous where the canonical fake's binding is synchronous**, because
        ``asyncio.StreamReader`` binds the running loop at construction and there
        is none inside a synchronous fixture. The canonical fake's binding has to
        stay synchronous — ``tests/core/test_protocol_triad.py`` evaluates a
        subject fixture to prove the fake reached the suite — and this one has no
        such obligation.

        Returns:
            The one production ``ByteChannel``.
        """
        return _channel()

    def far_end_sent(self, channel: ByteChannel, octets: bytes) -> None:
        """Feed ``octets`` to the read half and then close it.

        The close is not decoration: a ``StreamReader`` that has been fed nothing
        and told nothing is a stream still waiting, so a case about end of stream
        would hang instead of failing.

        Args:
            channel: The subject.
            octets: Everything the far end sends.
        """
        reader = _reader_of(channel)
        if octets:
            reader.feed_data(octets)
        reader.feed_eof()

    def arm_connection_failure(self, channel: ByteChannel) -> None:
        """Arm the connection under ``channel`` to fail as a reset one does.

        Raw ``OSError`` subclasses on purpose — a ``ConnectionResetError`` from
        the reader, another from the flush, an ``ssl.SSLError`` from the upgrade —
        because what the contract requires is that *this* implementation converts
        them. Arming it with a ``TransportError`` would be arming the answer.

        Args:
            channel: The subject.
        """
        _reader_of(channel).set_exception(ConnectionResetError("the peer reset the connection"))
        _writer_of(channel).fails = True

    def arm_release_failure(self, channel: ByteChannel) -> None:
        """Arm **both** halves of the release to fail.

        ``close`` is synchronous and ``wait_closed`` is not, and an earlier draft
        armed only the second — which left the synchronous half outside the
        channel's guard and untested for two rounds.

        Args:
            channel: The subject.
        """
        writer = _writer_of(channel)
        writer.fails = True
        writer.fails_to_close = True

    def suspend_next_close(self, channel: ByteChannel) -> SuspendedCall:
        """Arm the next ``close`` to suspend inside ``wait_closed``.

        Which is where a cancellation delivered to ``close`` actually lands: the
        writer is closed synchronously first, so the channel is already safe by the
        time the suspension is reached — and that is the property, not a detail.

        Args:
            channel: The subject.

        Returns:
            The lever the suite drives.
        """
        gate = LoopSuspension()
        _writer_of(channel).close_gate = gate
        return gate


class TestStreamOutboundTransportContract(OutboundTransportContract):
    """The production opener, run through the opener contract.

    **The cancellation case is armed where production is the only party that can
    release anything**, which took four rounds of review to locate. The
    substituted opener suspends *after* its streams exist and completes normally
    when released — it cleans up nothing — so what the case measures is
    ``open_channel``'s own shield-and-release path: the cancellation takes this
    frame off the open, the open is waited out rather than cancelled, and the
    streams it produced are released *before* the cancellation is delivered on.
    An implementation without that path leaves them held and the case fails,
    which is the whole point. Round 5 of both lenses is why the suite reads the
    ledger at the moment the caller's call completes rather than afterwards: the
    shape that released from a done-callback passed the later reading while the
    caller held a cancellation over an open socket.
    """

    @pytest.fixture(autouse=True)
    def _sockets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Substitute the standard library's opener with a counting one.

        Args:
            monkeypatch: pytest's own, so every substitution is undone per case.
        """
        self.sockets = _Sockets()
        self.patch = monkeypatch
        monkeypatch.setattr(asyncio, "open_connection", self.sockets)

    @pytest.fixture
    def transport(self) -> OutboundTransport:
        """The subject.

        Returns:
            The one production ``OutboundTransport``.
        """
        return StreamOutboundTransport()

    def arm_refusal(self, transport: OutboundTransport) -> None:
        """Arm the next open to fail before anything is acquired.

        Args:
            transport: The subject, which holds no state of its own.
        """
        del transport
        self.sockets.refuses = True

    def arm_failure_after_acquiring(self, transport: OutboundTransport) -> None:
        """Arm the next open to fail once the pair of streams exists.

        ADR-0191 §1 names "a channel object that could not be constructed" among
        the establishment failures the release clause covers, and that is the one
        step of ``open_channel`` that runs after the acquisition — so substituting
        the channel's constructor models the ADR's own named case rather than
        inventing one.

        Args:
            transport: The subject, which holds no state of its own.
        """
        del transport

        def refuses(*args: object, **kwargs: object) -> object:
            del args, kwargs
            msg = "the channel could not be constructed"
            raise TransportError(msg)

        self.patch.setattr(egress, "_StreamChannel", refuses)

    def suspend_next_open(self, transport: OutboundTransport) -> SuspendedCall:
        """Hold the next open where its streams already exist.

        Args:
            transport: The subject, which holds no state of its own.

        Returns:
            The lever the suite drives.
        """
        del transport
        self.sockets.gate = _Handoff()
        return self.sockets.gate

    def held_resources(self, transport: OutboundTransport) -> int:
        """Pairs of streams acquired and not given back.

        Args:
            transport: The subject, which holds no state of its own.

        Returns:
            The ledger's count.
        """
        del transport
        return self.sockets.open


# --- what is the seam's own rather than the contract's ----------------------


async def test_the_opener_asks_for_the_endpoint_it_was_handed_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§4: the host and port are the ones handed in, with the ceiling as the limit.

    No name resolution beyond that host, no redirect, no second host on one call —
    all of which this implementation gets by having nothing else to resolve from.
    The ``limit`` is asserted because it is what makes ``read_line``'s ceiling the
    contract's rather than this call site's.
    """
    sockets = _Sockets()
    monkeypatch.setattr(asyncio, "open_connection", sockets)

    channel = await StreamOutboundTransport().open_channel(ENDPOINT)

    assert sockets.asked["host"] == ENDPOINT.host
    assert sockets.asked["port"] == ENDPOINT.port
    assert sockets.asked["limit"] == TRANSPORT_OCTET_CEILING
    assert sockets.asked["server_hostname"] == ENDPOINT.host
    assert channel.is_secure is True


async def test_an_upgrade_endpoint_is_connected_in_the_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§1, §4: TLS before the greeting only where the endpoint's mode says so."""
    sockets = _Sockets()
    monkeypatch.setattr(asyncio, "open_connection", sockets)

    channel = await StreamOutboundTransport().open_channel(UPGRADE)

    assert sockets.asked["ssl"] is None
    assert sockets.asked["server_hostname"] is None
    assert channel.is_secure is False


@pytest.mark.parametrize(
    "raised",
    [
        pytest.param(ConnectionRefusedError("nothing is listening"), id="refused"),
        pytest.param(ssl.SSLError("the certificate is not valid"), id="unverified"),
        pytest.param(
            UnicodeEncodeError("idna", "\u200d.invalid", 0, 1, "label empty"), id="unresolvable"
        ),
    ],
)
async def test_the_opener_names_the_endpoint_and_no_octet_in_its_refusal(
    monkeypatch: pytest.MonkeyPatch, raised: Exception
) -> None:
    """§1: the message states a condition an operator can act on, and nothing else.

    ``ssl.SSLError`` is an ``OSError``, so a certificate that did not verify and a
    connection that was refused arrive by one path and leave as one type — which is
    the point of the taxonomy and is why there is no second clause for it.

    **A ``UnicodeError`` is not an ``OSError`` and needed one.** ``getaddrinfo``
    raises one for a host whose IDNA encoding fails — an empty or over-long label,
    a zero-width joiner — and ``parse_smtp_endpoint`` validates the authority no
    further than its punctuation (#1147, #1158), so such a host is one an operator
    can actually configure. Adversarial review found it escaping raw on round 3.
    """

    async def refuses(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise raised

    monkeypatch.setattr(asyncio, "open_connection", refuses)

    with pytest.raises(TransportError) as failure:
        await StreamOutboundTransport().open_channel(ENDPOINT)

    assert failure.value.__cause__ is raised
    assert str(failure.value) == (
        f"the endpoint {ENDPOINT.host}:{ENDPOINT.port} could not be connected"
    )


async def test_a_host_the_resolver_refuses_is_a_transport_error_not_a_unicode_one() -> None:
    """The same clause against the real resolver rather than a substitute.

    ``TransportEndpoint`` accepts this host — it is neither blank nor whitespace —
    and the endpoint grammar would too, so nothing upstream of ``open_channel``
    stops it. The case runs against the standard library's own ``getaddrinfo``
    because the point is that its exception type is not the one the ``except``
    clause obviously wants; a substitute would be asserting the arrangement.
    """
    unresolvable = TransportEndpoint(host="\u200d.invalid", port=465, implicit_tls=True)

    with pytest.raises(TransportError) as failure:
        await StreamOutboundTransport().open_channel(unresolvable)

    assert isinstance(failure.value.__cause__, UnicodeError)


async def test_the_channel_upgrades_against_the_pinned_host_and_never_a_reply() -> None:
    """§4: the certificate is verified against the endpoint that was handed in.

    Not against anything the far end says about itself — there is no reply this
    channel could learn a hostname from, because it keeps the one it was opened
    with and offers no way to name a second.
    """
    channel = _channel()

    await channel.write(b"STARTTLS\r\n")
    await channel.start_tls()

    assert channel.is_secure is True
    assert _writer_of(channel).tls == ENDPOINT.host
    assert _writer_of(channel).written == b"STARTTLS\r\n"
    assert _writer_of(channel).drains == 1


async def test_an_establishment_failure_survives_a_release_that_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure the caller owes is the one that leaves, not the cleanup's.

    ``StreamWriter.close`` can raise on a transport that is already broken. On
    the pre-return release paths that exception would *replace* the one in
    flight — so a ``TransportError`` saying the channel could not be established
    would reach the seam as an ``OSError`` from the tidy-up, which is the
    exception-replacement rule ADR-0191 §1 states for ``ByteChannel.close``
    arriving one layer up. Adversarial review found both paths unguarded on
    round 5.
    """
    sockets = _Sockets()
    sockets.breaks_on_close = True
    monkeypatch.setattr(asyncio, "open_connection", sockets)

    def refuses(*args: object, **kwargs: object) -> object:
        del args, kwargs
        msg = "the channel could not be constructed"
        raise TransportError(msg)

    monkeypatch.setattr(egress, "_StreamChannel", refuses)

    with pytest.raises(TransportError, match="could not be constructed"):
        await StreamOutboundTransport().open_channel(ENDPOINT)

    assert sockets.open == 0


async def test_a_cancellation_survives_a_release_that_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The caller's own control flow arrives, whatever the cleanup did.

    The same guard read from the other pre-return path: a release that raised
    here would convert a ``CancelledError`` into an ``OSError``, which ADR-0060
    §1 forbids in the strongest terms — the caller would be told the endpoint
    broke when what happened is that the caller cancelled.
    """
    sockets = _Sockets()
    sockets.breaks_on_close = True
    gate = _Handoff()
    sockets.gate = gate
    monkeypatch.setattr(asyncio, "open_connection", sockets)
    opening = asyncio.ensure_future(StreamOutboundTransport().open_channel(ENDPOINT))
    await gate.reached()

    opening.cancel()
    gate.release()
    await settle()

    with pytest.raises(asyncio.CancelledError):
        await opening
    assert sockets.open == 0


async def test_the_channels_close_aborts_a_release_that_failed_before_releasing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same rule one layer up: the holder called ``close`` and will not again.

    ADR-0191 §1 has ``close`` suppress an ordinary release failure rather than
    raise it — which says what the *caller* is told, not that the socket was given
    back. A ``StreamWriter.close`` that raises on its first statement has released
    nothing, and the holder has already made its one call. Adversarial review
    found this half on round 7, having found the opener's on round 6; the
    conformance hook arms the easier ordering, so this case arms the harder one.
    """
    sockets = _Sockets()
    monkeypatch.setattr(asyncio, "open_connection", sockets)
    channel = await StreamOutboundTransport().open_channel(ENDPOINT)
    writer = _writer_of(channel)
    writer.fails_to_close = True
    writer.releases_before_it_fails = False

    await channel.close()

    assert writer.aborts == 1
    assert sockets.open == 0


async def test_a_cancelled_close_releases_and_leaves_the_channel_closeable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§1: safe first, re-raised second — and still idempotent afterwards.

    ``StreamWriter.wait_closed`` awaits the protocol's **shared** close waiter, so
    a cancellation delivered while this method awaited it directly cancelled that
    future for good: the socket could stay held by a far end that had stopped
    reading, and every later ``close`` awaiting the same future raised
    ``CancelledError`` out of a call nobody cancelled. That is the idempotency
    ADR-0191 §1 requires, broken by the cleanup path. Adversarial review found it
    on round 10, and the conformance hook could not: its suspension is per-call
    and absorbs the cancellation until it is released.

    So the double now holds the shared waiter the standard library holds, and the
    arrangement is a far end that has stopped reading: the close is under way and
    the waiter settles only when something drops the transport.
    """
    sockets = _Sockets()
    monkeypatch.setattr(asyncio, "open_connection", sockets)
    channel = await StreamOutboundTransport().open_channel(ENDPOINT)
    writer = _writer_of(channel)
    writer.holds_the_close_waiter = True
    closing = asyncio.ensure_future(channel.close())
    await settle()

    closing.cancel()
    await settle()

    with pytest.raises(asyncio.CancelledError):
        await closing
    assert writer.aborts == 1
    assert sockets.open == 0
    assert writer.close_waiter.cancelled() is False

    await channel.close()


async def test_a_release_that_fails_beside_a_cancellation_is_still_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§1's two clauses meeting on one call: re-raised, and still reported.

    ADR-0191 §1 has ``close`` suppress **and log** an ordinary release failure,
    and the cancellation carve-out beside it decides only which exception leaves.
    So a ``wait_closed`` that completes with an ``OSError`` while a cancellation
    is in flight — a transport that had already scheduled ``connection_lost(exc)``
    when the caller went away — owes an ``egress_channel_close_failed`` event just
    as the uncancelled path does. The earlier code retrieved that outcome only so
    ``asyncio`` would not report it unread, and then discarded it. Adversarial
    review found it on round 11, and neither existing case could: they arm the
    cancellation and the failing release separately.

    The arrangement is the two together — a far end that has stopped reading, so
    the close is under way and the wait is what the cancellation lands on, and a
    release that then fails once the gate lets it finish.

    The level is raised for the duration because a failed release is logged at
    ``debug`` and importing the package configures the chain at ``info``, so the
    filtering bound logger would drop the event before any processor saw it — the
    case would then pass on a channel that logged nothing at all. It is put back
    to the import-time default afterwards, so nothing later in the session
    inherits the verbosity.
    """
    sockets = _Sockets()
    monkeypatch.setattr(asyncio, "open_connection", sockets)
    channel = await StreamOutboundTransport().open_channel(ENDPOINT)
    writer = _writer_of(channel)
    writer.holds_the_close_waiter = True
    writer.fails_to_close = True
    gate = LoopSuspension()
    writer.close_gate = gate

    configure_logging(Settings(log_level="DEBUG"))
    try:
        with structlog.testing.capture_logs() as captured:
            closing = asyncio.ensure_future(channel.close())
            await gate.reached()
            closing.cancel()
            await settle()
            gate.release()
            await settle()

            with pytest.raises(asyncio.CancelledError):
                await closing
    finally:
        configure_logging(Settings(log_level="INFO"))

    assert writer.aborts == 1
    assert sockets.open == 0
    failures = [entry for entry in captured if entry["event"] == "egress_channel_close_failed"]
    assert failures, [entry["event"] for entry in captured]
    assert failures[0]["error_type"] == "OSError"


async def test_a_tls_context_that_cannot_be_built_is_a_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§1: one taxonomy, including the step before any socket exists.

    Building the context is file-system work — ``ssl.create_default_context``
    loads the trust store, and ``SSLKEYLOGFILE`` naming an unusable path makes it
    open that too — so a deployment's environment can make it raise. Constructing
    it in the opener's argument list put that outside every ``except``, and a raw
    ``OSError`` reaching a holder is the shared refusal type broken for a case an
    operator can actually configure.
    """
    sockets = _Sockets()
    monkeypatch.setattr(asyncio, "open_connection", sockets)

    def unusable() -> ssl.SSLContext:
        msg = "SSLKEYLOGFILE names a directory that does not exist"
        raise FileNotFoundError(msg)

    monkeypatch.setattr(egress, "_tls_context", unusable)

    with pytest.raises(TransportError, match="could not be secured"):
        await StreamOutboundTransport().open_channel(ENDPOINT)

    assert sockets.asked == {}
    assert sockets.open == 0


async def test_a_release_that_fails_before_releasing_anything_is_aborted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Suppressing a failed release is not the same as having released.

    A close that raises may have raised on its first statement, having given
    nothing back — and on this path no channel reached a holder, so nothing else
    will ever try again: the socket is ownerless. ``abort`` is the harder release
    the standard library keeps for exactly that. Adversarial review found the
    suppression standing alone on round 6, and the case that missed it did so
    because the writer double released *before* it raised.
    """
    sockets = _Sockets()
    sockets.breaks_on_close = True
    sockets.releases_before_it_fails = False
    monkeypatch.setattr(asyncio, "open_connection", sockets)

    def refuses(*args: object, **kwargs: object) -> object:
        del args, kwargs
        msg = "the channel could not be constructed"
        raise TransportError(msg)

    monkeypatch.setattr(egress, "_StreamChannel", refuses)

    with pytest.raises(TransportError, match="could not be constructed"):
        await StreamOutboundTransport().open_channel(ENDPOINT)

    assert sockets.handed is not None
    assert sockets.handed.aborts == 1
    assert sockets.open == 0


def test_the_capability_holds_no_state_between_calls() -> None:
    """§3: no pool, no cache, no keep-alive, so no route outlives a call.

    A pooled capability is a long-lived connection owned by whoever opened it, and
    a subsystem keeping one across calls has a route that outlives the
    authorisation that produced it. ``__slots__`` being empty is that property
    stated where an edit would have to notice it.
    """
    assert StreamOutboundTransport.__slots__ == ()
    with pytest.raises(AttributeError):
        StreamOutboundTransport().anything = 1  # type: ignore[attr-defined]  # the point of the case
