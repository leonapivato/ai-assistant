"""The seam's own channel and opener, held to the contract they implement.

ADR-0191 §1 fixes one buffering ceiling in ``core`` "so the canonical fake and the
production implementation refuse the same inputs and a consumer tested against one
behaves against the other". ``tests/core/test_fake_transport.py`` holds the fake to
it through the shared conformance suite; this module holds the production pair —
``_StreamChannel`` and :class:`~ai_assistant.tools.egress.StreamOutboundTransport`
— to the same boundaries.

**Why these are cases here rather than a second binding of ``ByteChannelContract``.**
The suite's subject is a channel whose far end has already sent what a case wants
to read, and it takes the octets through a ``deliver`` hook after the subject
exists. An ``asyncio.StreamReader`` cannot model that: a case that delivers nothing
needs the reader already at end of stream, and one that delivers something needs it
*not* to be — so a single fixture cannot serve both, and a binding that fed end of
stream eagerly would hang every case that then delivered. What is on test is the
boundary arithmetic and the refusals, and those are the same assertions either way.

**Nothing here opens a socket.** The reader is fed in memory and the writer is a
double, so ``_StreamChannel`` is exercised whole while
``asyncio.open_connection`` is reached only through a substitute that raises.
"""

from __future__ import annotations

import asyncio
import ssl
from typing import TYPE_CHECKING, Final, cast, final

import pytest

from ai_assistant.core.errors import TransportError
from ai_assistant.core.types import TRANSPORT_OCTET_CEILING, TransportEndpoint
from ai_assistant.tools import egress
from ai_assistant.tools.egress import StreamOutboundTransport

if TYPE_CHECKING:
    from ai_assistant.core.protocols import ByteChannel

#: The endpoint the opener cases ask for. ``.invalid`` (RFC 6761 §6.4), so a case
#: that somehow reached a resolver would fail rather than connect.
ENDPOINT: Final = TransportEndpoint(host="mail.example.invalid", port=465, implicit_tls=True)


@final
class _Writer:
    """The write half, without a transport under it.

    Enough of ``asyncio.StreamWriter`` for the channel to drive: what it wrote,
    whether it was closed, whether TLS was started, and an armable failure from
    ``wait_closed`` — which is the ordinary release failure ADR-0191 §1 has
    ``close`` swallow.
    """

    def __init__(self, *, fails_to_close: bool = False) -> None:
        """Start open, having written nothing.

        Args:
            fails_to_close: Whether ``wait_closed`` raises, as a far end that has
                already gone makes it.
        """
        self.written = bytearray()
        self.closed = False
        self.drains = 0
        self.tls: str | None = None
        self._fails_to_close = fails_to_close

    def write(self, data: bytes) -> None:
        """Record ``data``."""
        self.written += data

    async def drain(self) -> None:
        """Record that the caller flushed."""
        self.drains += 1

    async def start_tls(self, context: ssl.SSLContext, *, server_hostname: str) -> None:
        """Record which host the certificate would have been verified against."""
        assert context.check_hostname is True
        assert context.verify_mode is ssl.CERT_REQUIRED
        self.tls = server_hostname

    def close(self) -> None:
        """Record that the writer was closed."""
        self.closed = True

    async def wait_closed(self) -> None:
        """Wait for the close, failing where a far end had already gone.

        Raises:
            OSError: Where this writer was armed to fail.
        """
        if self._fails_to_close:
            msg = "the far end had already gone"
            raise OSError(msg)


def _channel(
    *fed: bytes, end_of_stream: bool = True, writer: _Writer | None = None
) -> tuple[ByteChannel, _Writer]:
    """A production channel over a reader that has already been fed.

    Args:
        fed: Octets the far end sent, in order.
        end_of_stream: Whether the far end then closed. ``False`` leaves the
            stream open, which is only useful for a case that reads less than it
            was fed.
        writer: The write half, or a fresh one.

    Returns:
        The channel and its writer, so a case can read what was written.
    """
    reader = asyncio.StreamReader(limit=TRANSPORT_OCTET_CEILING)
    for chunk in fed:
        reader.feed_data(chunk)
    if end_of_stream:
        reader.feed_eof()
    half = writer if writer is not None else _Writer()
    channel = egress._StreamChannel(
        reader,
        cast("asyncio.StreamWriter", half),
        host=ENDPOINT.host,
        secure=False,
    )
    return channel, half


# --- §1: read_line's terminator, end of stream and ceiling ------------------


async def test_read_line_returns_the_line_including_its_terminator() -> None:
    """§1: the line comes back with its ``\\n``, and with the ``\\r`` before it."""
    channel, _ = _channel(b"220 ready\r\n250 ok\r\n")

    assert await channel.read_line() == b"220 ready\r\n"


async def test_read_line_reports_end_of_stream_as_empty_bytes() -> None:
    """§1: empty bytes means end of stream and means nothing else."""
    channel, _ = _channel()

    assert await channel.read_line() == b""


async def test_read_line_discards_an_unterminated_tail() -> None:
    """§1: a line with no terminator is not a reply, whatever octets arrived."""
    channel, _ = _channel(b"250 the far end stopped here")

    assert await channel.read_line() == b""


async def test_read_line_accepts_a_line_of_exactly_the_ceiling() -> None:
    """§1: the bound is on the octets **before** the terminator.

    So the production channel and the canonical fake agree at the one value an
    implementation can be off by one at. ``StreamReader.readuntil`` applies its
    ``limit`` to the buffer ahead of the separator, which is why the channel states
    the boundary rather than re-deriving it.
    """
    channel, _ = _channel(b"a" * TRANSPORT_OCTET_CEILING + b"\n")

    assert len(await channel.read_line()) == TRANSPORT_OCTET_CEILING + 1


async def test_read_line_refuses_a_line_one_octet_past_the_ceiling() -> None:
    """§1: the refusal is a ``TransportError`` and not the seam's own pin error.

    ``TransportError``'s subject is what happened to the connection, and a far end
    buying memory from a client that is holding a credential is exactly that. The
    seam converts it where its own ordering requires — inside the window
    ``_SmtpSession.data`` owns — and nowhere else.
    """
    channel, _ = _channel(b"a" * (TRANSPORT_OCTET_CEILING + 1) + b"\n")

    with pytest.raises(TransportError):
        await channel.read_line()


# --- §1: read's bounded domain ----------------------------------------------


@pytest.mark.parametrize("limit", [0, -1, TRANSPORT_OCTET_CEILING + 1])
async def test_read_refuses_a_limit_outside_its_domain(limit: int) -> None:
    """§1: no spelling of ``limit`` means "read until end of stream".

    ``-1`` is exactly that spelling for ``StreamReader.read``, so the refusal is
    what stops a peer that streams without closing from exhausting memory through
    a method whose name says it is bounded.
    """
    channel, _ = _channel(b"0123456789")

    with pytest.raises(ValueError, match="limit"):
        await channel.read(limit)


@pytest.mark.parametrize("limit", [1, TRANSPORT_OCTET_CEILING])
async def test_read_accepts_both_ends_of_its_domain(limit: int) -> None:
    """§1: the domain is inclusive at both ends."""
    channel, _ = _channel(b"0123456789")

    assert await channel.read(limit) != b""


async def test_read_reports_end_of_stream_as_empty_bytes() -> None:
    """§1: the same spelling of end of stream ``read_line`` uses."""
    channel, _ = _channel()

    assert await channel.read(TRANSPORT_OCTET_CEILING) == b""


async def test_read_and_read_line_share_one_cursor() -> None:
    """§1: octets returned by either are never returned again by the other."""
    channel, _ = _channel(b"220 ready\r\n")

    assert await channel.read(4) == b"220 "
    assert await channel.read_line() == b"ready\r\n"


# --- §1, §4: TLS state, writing and release ---------------------------------


async def test_write_flushes_and_start_tls_verifies_against_the_pinned_host() -> None:
    """§4: the certificate is verified against the endpoint, never against a reply."""
    channel, writer = _channel()

    await channel.write(b"EHLO mail.example.invalid\r\n")
    assert channel.is_secure is False

    await channel.start_tls()

    assert writer.written == b"EHLO mail.example.invalid\r\n"
    assert writer.drains == 1
    assert writer.tls == ENDPOINT.host
    assert channel.is_secure is True


async def test_close_is_idempotent_and_suppresses_an_ordinary_release_failure() -> None:
    """§1: a channel that cannot be released tells its logs and not its caller.

    The seam closes from a ``finally``, where Python replaces the exception in
    flight with one raised there — so a channel that raised here would turn an
    ``IndeterminateTransmissionError`` into an internal failure and record a
    possible disclosure as one that did not happen.
    """
    channel, writer = _channel(writer=_Writer(fails_to_close=True))

    await channel.close()
    await channel.close()

    assert writer.closed is True


# --- §1: what the opener converts -------------------------------------------


@pytest.mark.parametrize(
    "raised",
    [ConnectionRefusedError("nothing is listening"), ssl.SSLError("the certificate is not valid")],
)
async def test_the_opener_converts_a_connection_failure_into_a_transport_error(
    monkeypatch: pytest.MonkeyPatch, raised: Exception
) -> None:
    """§1: one taxonomy for every holder of the capability.

    A ``TransportError`` is the shared refusal type the canonical fake raises too,
    so a consumer written against one behaves against the other — and a holder does
    not have to know that this implementation happens to sit on ``asyncio``.
    """

    async def refuses(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise raised

    monkeypatch.setattr(asyncio, "open_connection", refuses)

    with pytest.raises(TransportError) as failure:
        await StreamOutboundTransport().open_channel(ENDPOINT)

    assert failure.value.__cause__ is raised
    # The message names the condition an operator can act on and no octet.
    assert (
        str(failure.value) == f"the endpoint {ENDPOINT.host}:{ENDPOINT.port} could not be connected"
    )


async def test_the_opener_asks_for_the_endpoint_it_was_handed_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§4: the host and port are the ones handed in, with the ceiling as the limit.

    No name resolution beyond that host, no redirect, no second host on one call —
    all of which this implementation gets by having nothing else to resolve from.
    """
    seen: dict[str, object] = {}

    async def records(
        host: str, port: int, **kwargs: object
    ) -> tuple[asyncio.StreamReader, object]:
        seen.update(host=host, port=port, **kwargs)
        return asyncio.StreamReader(), _Writer()

    monkeypatch.setattr(asyncio, "open_connection", records)

    channel = await StreamOutboundTransport().open_channel(ENDPOINT)

    assert seen["host"] == ENDPOINT.host
    assert seen["port"] == ENDPOINT.port
    assert seen["limit"] == TRANSPORT_OCTET_CEILING
    assert seen["server_hostname"] == ENDPOINT.host
    assert channel.is_secure is True


async def test_an_upgrade_endpoint_is_connected_in_the_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§1, §4: TLS before the greeting only where the endpoint's mode says so.

    Where it does not, the channel is returned cleartext and the obligation is the
    holder's — the seam refuses to present a credential on a channel whose TLS
    state reads false, which is the property rather than the endpoint's mode.
    """
    upgrade = TransportEndpoint(host=ENDPOINT.host, port=587, implicit_tls=False)
    seen: dict[str, object] = {}

    async def records(
        host: str, port: int, **kwargs: object
    ) -> tuple[asyncio.StreamReader, object]:
        seen.update(host=host, port=port, **kwargs)
        return asyncio.StreamReader(), _Writer()

    monkeypatch.setattr(asyncio, "open_connection", records)

    channel = await StreamOutboundTransport().open_channel(upgrade)

    assert seen["ssl"] is None
    assert seen["server_hostname"] is None
    assert channel.is_secure is False


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
