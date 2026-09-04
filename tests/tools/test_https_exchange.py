"""ADR-0154 §4's condition 14 for the HTTPS exchange, one section per row.

ADR-0231 §17's Lane 2 restates that condition for this transport and names the
rows itself: *"a refused redirect, a closed channel mid-response, a TLS failure, a
response that is not the shape the provider documents, a deadline, a response that
reaches the read bound, and each of §8's refusals."* Seven rows, seven sections
below, in the ADR's own order and named after its own words — which is what
``test_egress_failure_paths.py`` does for the send path, and for its reason: a
later ADR walking the list should not have to reconstruct it.

**Two of the seven read differently here than they do for SMTP, and the difference
is written down rather than papered over.** SMTP has no redirect, so that suite
tests RFC 5321 §3.4's forward-path replies as the nearest thing; HTTP has the
real one, and §5 makes it a refusal. And "a response that is not the shape the
provider documents" is split between two lanes: the **HTTP** shape is this
exchange's and is tested here, while the provider's own payload format is the
searcher's (ADR-0231 §10, §17's Lane 3) — this exchange decodes no body at all.

**Nothing here opens a socket.** Every case runs against
:class:`~ai_assistant.testing.FakeByteChannel` served by
:class:`~ai_assistant.testing.FakeOutboundTransport`, which is the canonical pair
ADR-0191 §8 puts in ``ai_assistant.testing``. Hosts are ``.invalid`` (RFC 6761
§6.4) throughout, so a case that somehow reached a resolver would fail rather than
connect. One state the canonical fake has no arrangement for — a far end that
never answers at all — is expressed by :class:`_SilentFarEnd` below, for the
deadline row alone.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final, final

import pytest

from ai_assistant.core.errors import TransportError
from ai_assistant.core.types import TRANSPORT_OCTET_CEILING, TransportEndpoint
from ai_assistant.testing import FakeByteChannel, FakeOutboundTransport
from ai_assistant.tools.egress import (
    HttpsExchange,
    HttpsRedirectRefusedError,
    HttpsResponseTooLargeError,
    MalformedHttpResponseError,
    TransportPinError,
    parse_https_origin,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import ByteChannel

pytestmark = pytest.mark.anyio

#: The connected account's origin, and the target and credential header an
#: integration would compose. What the query says is not this seam's business:
#: ADR-0231 §5 puts the path, the parameter names and the headers inside
#: ``ai_assistant.tools`` and the exchange only writes what it is handed.
ORIGIN: Final = "https://search.example.invalid"
TARGET: Final = "/v1/search?q=weather"
CREDENTIAL: Final = ("Authorization", "Bearer an-app-key")

#: A response bound generous enough that no case reaches it by accident. The
#: bound's own row supplies its own.
BOUND: Final = 64 * 1024


def response(
    *, status: str = "HTTP/1.1 200 OK", headers: Sequence[str] = (), body: bytes = b""
) -> bytes:
    """One response's octets, framed by a content length unless told otherwise.

    Args:
        status: The status line, without its terminator.
        headers: The field lines, without their terminators. Where none names a
            length or a coding, one is added for ``body``.
        body: The payload.

    Returns:
        The octets a far end would send.
    """
    fields = list(headers)
    framed = any(
        field.lower().startswith(("content-length:", "transfer-encoding:")) for field in fields
    )
    if not framed:
        fields.append(f"Content-Length: {len(body)}")
    head = "\r\n".join([status, *fields]) + "\r\n\r\n"
    return head.encode("ascii") + body


def far_end(*octets: bytes) -> FakeByteChannel:
    """A secure channel with ``octets`` already sent by the far end.

    Args:
        octets: What the far end will answer, in order.

    Returns:
        The channel, ready to be served for an implicit-TLS endpoint.
    """
    return FakeByteChannel(secure=True).deliver(*octets)


def exchange(
    *channels: FakeByteChannel, bound: int = BOUND
) -> tuple[HttpsExchange, FakeOutboundTransport]:
    """An exchange over a transport serving ``channels``, in order.

    Args:
        channels: The channels to hand out, one per open.
        bound: ``search_max_response_bytes`` for this exchange.

    Returns:
        The exchange and the transport, so a case can read the attempts back.
    """
    transport = FakeOutboundTransport().serve(*channels)
    return HttpsExchange(transport=transport, max_response_bytes=bound), transport


def request_of(channel: FakeByteChannel) -> list[str]:
    """Every line the exchange wrote, terminators stripped.

    Args:
        channel: The channel the exchange ran over.

    Returns:
        The lines, in order, including the empty one that ends the field section.
    """
    return channel.written.decode("ascii", "replace").split("\r\n")


async def drained(channel: FakeByteChannel) -> int:
    """How many octets the far end still holds, having been read to the end.

    The exchange's read bound is a claim about what it took **off** the channel,
    and the honest measurement of that is what is left on one. Reading the
    remainder here rather than wrapping the channel in a counter keeps every case
    on the canonical fake (ADR-0191 §8) instead of on a second implementation of a
    contract this project has exactly one of.

    Args:
        channel: The channel, after the exchange has finished with it.

    Returns:
        The count of octets the exchange did not take.
    """
    remaining = 0
    while chunk := await channel.read(TRANSPORT_OCTET_CEILING):
        remaining += len(chunk)
    return remaining


@final
class _SilentFarEnd:
    """A :class:`~ai_assistant.core.protocols.ByteChannel` that never answers.

    The one state :class:`~ai_assistant.testing.FakeByteChannel` has no
    arrangement for: it can end a stream cleanly, and it can be armed to raise,
    but it cannot *hang*. A deadline is only observable against a far end that
    does neither, so this expresses that and nothing else — it is not a second
    scripted channel, and no other case here uses it.

    Attributes:
        closed: Whether the holder released it, which is what the deadline row
            asserts.
    """

    def __init__(self) -> None:
        """Open a silent channel, already under TLS and never yet released."""
        self.closed = False
        self.written = bytearray()

    @property
    def is_secure(self) -> bool:
        """Whether TLS is established, which for this channel is always.

        Returns:
            ``True``.
        """
        return True

    async def read_line(self) -> bytes:
        """Never answer.

        Returns:
            Nothing; the wait does not end.
        """
        await asyncio.Event().wait()
        return b""  # pragma: no cover — the wait above never returns

    async def read(self, limit: int, /) -> bytes:
        """Never answer.

        Args:
            limit: Ignored; nothing is ever read.

        Returns:
            Nothing; the wait does not end.
        """
        await asyncio.Event().wait()
        return b""  # pragma: no cover — the wait above never returns

    async def write(self, data: bytes, /) -> None:
        """Record ``data`` as written.

        Args:
            data: The octets to send.
        """
        self.written += data

    async def start_tls(self) -> None:
        """Do nothing: this channel is secure from the first octet."""

    async def close(self) -> None:
        """Release the channel, idempotently."""
        self.closed = True


@final
class _ServesOne:
    """An :class:`~ai_assistant.core.protocols.OutboundTransport` for one channel.

    Paired with :class:`_SilentFarEnd` and used by the deadline row alone, for the
    same reason: :class:`~ai_assistant.testing.FakeOutboundTransport` serves
    :class:`~ai_assistant.testing.FakeByteChannel` and nothing else, and the state
    being expressed is not one that fake has.
    """

    def __init__(self, channel: _SilentFarEnd) -> None:
        """Hold the one channel this transport will hand out.

        Args:
            channel: What :meth:`open_channel` answers with.
        """
        self.channel = channel

    async def open_channel(self, endpoint: TransportEndpoint) -> ByteChannel:
        """Hand out the one channel.

        Args:
            endpoint: The endpoint asked for; recorded by nothing here.

        Returns:
            The channel.
        """
        assert endpoint.implicit_tls
        return self.channel


# --------------------------------------------------------------------------- #
# The exchange itself, so that every refusal below is a refusal of something     #
# --------------------------------------------------------------------------- #


async def test_the_request_names_the_pinned_host_and_closes_the_channel() -> None:
    """The request line, the ``Host`` and the per-call channel, in one assertion.

    ADR-0191 §3's channel-per-call is a property of shape rather than of a check,
    so what a test can see of it is that the exchange asked the far end for it and
    released the channel it opened.
    """
    channel = far_end(response(body=b'{"results": []}'))
    subject, transport = exchange(channel)

    answer = await subject.get(origin=ORIGIN, target=TARGET, headers=[CREDENTIAL])

    assert answer.status == 200
    assert answer.body == b'{"results": []}'
    assert request_of(channel)[:4] == [
        f"GET {TARGET} HTTP/1.1",
        "Host: search.example.invalid",
        "Connection: close",
        f"{CREDENTIAL[0]}: {CREDENTIAL[1]}",
    ]
    assert [attempt.endpoint.host for attempt in transport.attempts] == ["search.example.invalid"]
    assert transport.attempts[0].endpoint.port == 443
    assert channel.closed


async def test_a_non_default_port_is_written_into_the_host_field() -> None:
    """RFC 9110 §4.2.2: the default is omitted and anything else is not.

    Asserted because the two halves are one branch, and an implementation that
    always wrote the port would reach a virtual host nobody configured.
    """
    channel = far_end(response(body=b"{}"))
    subject, transport = exchange(channel)

    await subject.get(origin="https://search.example.invalid:8443", target=TARGET)

    assert request_of(channel)[1] == "Host: search.example.invalid:8443"
    assert transport.attempts[0].endpoint.port == 8443


async def test_a_chunked_response_is_decoded_and_its_framing_is_not_in_the_body() -> None:
    """RFC 9112 §7.1, which is what a real provider behind a CDN actually sends."""
    body = b"4\r\nabcd\r\n3\r\nefg\r\n0\r\nX-Trailer: 1\r\n\r\n"
    channel = far_end(response(headers=["Transfer-Encoding: chunked"], body=body))
    subject, _ = exchange(channel)

    answer = await subject.get(origin=ORIGIN, target=TARGET)

    assert answer.body == b"abcdefg"


async def test_a_response_framed_by_the_close_is_read_to_the_end() -> None:
    """No length and no coding: ``Connection: close`` is the framing (RFC 9112 §6.3)."""
    head = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n"
    channel = far_end(head + b'{"results": [1]}')
    subject, _ = exchange(channel)

    answer = await subject.get(origin=ORIGIN, target=TARGET)

    assert answer.body == b'{"results": [1]}'
    assert answer.headers == (("content-type", "application/json"),)


# --------------------------------------------------------------------------- #
# Row 1 — a refused redirect                                                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("status", [300, 301, 302, 304, 307, 308, 399])
async def test_a_redirect_is_a_refusal_and_never_a_second_request(status: int) -> None:
    """ADR-0231 §5: "it **follows no redirect**", stated over the whole class.

    The assertion is not only that the call refused: it is that **one** channel was
    ever asked for, so the credential reached one origin. #83's failure is a client
    that carries a credential to the host a ``Location`` names, and an
    implementation that followed one would pass a refusal-only test the moment it
    also refused the *second* response.
    """
    channel = far_end(
        response(
            status=f"HTTP/1.1 {status} Moved",
            headers=["Location: https://elsewhere.example.invalid/steal"],
            body=b"",
        )
    )
    subject, transport = exchange(channel)

    with pytest.raises(HttpsRedirectRefusedError, match=str(status)):
        await subject.get(origin=ORIGIN, target=TARGET, headers=[CREDENTIAL])

    assert len(transport.attempts) == 1
    assert [attempt.endpoint.host for attempt in transport.attempts] == ["search.example.invalid"]
    assert channel.closed


async def test_a_redirect_refusal_names_no_second_host_and_no_credential() -> None:
    """The refusal reaches a log, and both of those are things it must not carry."""
    channel = far_end(
        response(
            status="HTTP/1.1 302 Found",
            headers=["Location: https://elsewhere.example.invalid/steal"],
        )
    )
    subject, _ = exchange(channel)

    with pytest.raises(HttpsRedirectRefusedError) as raised:
        await subject.get(origin=ORIGIN, target=TARGET, headers=[CREDENTIAL])

    assert "elsewhere" not in str(raised.value)
    assert CREDENTIAL[1] not in str(raised.value)


# --------------------------------------------------------------------------- #
# Row 2 — a closed channel mid-response                                         #
# --------------------------------------------------------------------------- #


async def test_a_stream_ending_inside_the_header_section_is_refused() -> None:
    """A clean close where a line was expected is not an answer (ADR-0191 §1)."""
    channel = far_end(b"HTTP/1.1 200 OK\r\nContent-Type: appl")
    subject, _ = exchange(channel)

    with pytest.raises(MalformedHttpResponseError, match="ended the stream"):
        await subject.get(origin=ORIGIN, target=TARGET)

    assert channel.closed


async def test_a_stream_ending_before_the_declared_length_is_refused() -> None:
    """A truncated body is not a short one: the far end declared how long it was."""
    channel = far_end(b"HTTP/1.1 200 OK\r\nContent-Length: 32\r\n\r\nfour")
    subject, _ = exchange(channel)

    with pytest.raises(MalformedHttpResponseError, match="declared"):
        await subject.get(origin=ORIGIN, target=TARGET)

    assert channel.closed


async def test_a_connection_reset_mid_response_reaches_the_caller_as_itself() -> None:
    """ADR-0191 §1's own type, declared rather than converted (#1604).

    A ``TransportError`` says what happened to the **connection**, which is the
    capability's subject; restating it as one of this seam's classes would be
    claiming this seam knows something about the response, which it does not.
    """
    channel = far_end(b"HTTP/1.1 200 OK\r\nContent-Length: 32\r\n\r\nfour")
    channel.fail_when_exhausted(TransportError("the connection was reset"))
    subject, _ = exchange(channel)

    with pytest.raises(TransportError, match="reset"):
        await subject.get(origin=ORIGIN, target=TARGET)

    assert channel.closed


# --------------------------------------------------------------------------- #
# Row 3 — a TLS failure                                                         #
# --------------------------------------------------------------------------- #


async def test_a_certificate_that_does_not_verify_reaches_no_write() -> None:
    """``open_channel`` raises over rather than returns (ADR-0191 §1), so nothing is sent.

    This is the commonest real failure a deployment hits — an expired or untrusted
    certificate, or a name that does not match — and the property that matters is
    that the credential never left: no channel was served, so there is nothing it
    could have been written to.
    """
    transport = FakeOutboundTransport()
    transport.refuse_with(TransportError("the certificate did not verify"))
    subject = HttpsExchange(transport=transport, max_response_bytes=BOUND)

    with pytest.raises(TransportError, match="certificate"):
        await subject.get(origin=ORIGIN, target=TARGET, headers=[CREDENTIAL])

    assert len(transport.attempts) == 1
    assert transport.channels == ()
    assert transport.open_sockets == 0


# --------------------------------------------------------------------------- #
# Row 4 — a response that is not the shape the provider documents               #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("octets", "why"),
    [
        pytest.param(b"nonsense\r\n\r\n", "version", id="no-status-line"),
        pytest.param(b"HTTP/2 200 OK\r\n\r\n", "version", id="a-version-with-no-line-framing"),
        pytest.param(b"HTTP/1.1\r\n\r\n", "version", id="a-status-line-with-no-code"),
        pytest.param(b"HTTP/1.1 20 OK\r\n\r\n", "three-digit", id="a-two-digit-code"),
        pytest.param(b"HTTP/1.1 2000 OK\r\n\r\n", "three-digit", id="a-four-digit-code"),
        pytest.param(b"HTTP/1.1 2x0 OK\r\n\r\n", "three-digit", id="a-code-that-is-not-digits"),
        pytest.param(
            b"HTTP/1.1 200\r\n\r\n", "no space after", id="no-space-after-the-status-code"
        ),
        pytest.param(
            b"HTTP/1.1 200 O\x00K\r\n\r\n", "reason phrase", id="a-control-octet-in-the-reason"
        ),
        pytest.param(
            b"HTTP/1.1 200 OK\r\nX-Value: ok\x00bad\r\n\r\n",
            "control octet",
            id="a-control-octet-in-a-field-value",
        ),
        pytest.param(
            b"HTTP/1.1 200 OK\r\nX-Value: ok\x7f\r\n\r\n",
            "control octet",
            id="a-delete-octet-in-a-field-value",
        ),
        pytest.param(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\nX-T: a\x00b\r\n\r\n",
            "control octet",
            id="a-control-octet-in-a-trailer-value",
        ),
        pytest.param(b"HTTP/1.1 099 OK\r\n\r\n", "status class", id="a-code-below-every-class"),
        pytest.param(b"HTTP/1.1 600 OK\r\n\r\n", "status class", id="a-code-above-every-class"),
        pytest.param(b"HTTP/1.1 100 Continue\r\n\r\n", "interim", id="an-interim-response"),
        pytest.param(
            b"HTTP/1.1 200 OK\r\nnot a field\r\n\r\n", "not a header", id="a-line-that-is-no-field"
        ),
        pytest.param(
            b"HTTP/1.1 200 OK\r\n: empty\r\n\r\n", "not a header", id="a-field-with-no-name"
        ),
        pytest.param(
            b"HTTP/1.1 200 OK\r\nBad Name: x\r\n\r\n", "not a header", id="a-name-holding-a-space"
        ),
        pytest.param(
            b"HTTP/1.1 200 OK\r\n\tfolded: x\r\n\r\n", "not a header", id="an-obsolete-line-fold"
        ),
        pytest.param(
            b"HTTP/1.1 200 OK\r\nX-Caf\xc3\xa9: x\r\n\r\n", "non-ASCII", id="a-non-ascii-field"
        ),
        pytest.param(
            b"HTTP/1.1 200 OK\r\nContent-Length: 1\r\nTransfer-Encoding: chunked\r\n\r\nx",
            "two ways at once",
            id="two-framings-at-once",
        ),
        pytest.param(
            b"HTTP/1.1 200 OK\r\nContent-Length: 1\r\nContent-Length: 2\r\n\r\nx",
            "more than one",
            id="two-content-lengths",
        ),
        pytest.param(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: gzip\r\n\r\nx",
            "transfer coding",
            id="a-coding-this-seam-does-not-read",
        ),
        pytest.param(
            b"HTTP/1.1 200 OK\r\nContent-Length: 1_0\r\n\r\nx",
            "decimal number",
            id="a-length-python-would-read-and-nobody-else-would",
        ),
        pytest.param(
            b"HTTP/1.1 200 OK\r\nContent-Length: -1\r\n\r\nx",
            "decimal number",
            id="a-negative-length",
        ),
        pytest.param(
            b"HTTP/1.1 200 OK\r\nContent-Length: " + b"1" * 5000 + b"\r\n\r\nx",
            "decimal number",
            id="a-length-longer-than-python-will-convert",
        ),
        pytest.param(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\nnot a field\r\n\r\n",
            "not a header",
            id="a-trailer-that-is-not-a-header-field",
        ),
        pytest.param(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\tfolded: x\r\n\r\n",
            "not a header",
            id="a-trailer-that-is-an-obsolete-line-fold",
        ),
        pytest.param(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\nX-Caf\xc3\xa9: x\r\n\r\n",
            "non-ASCII",
            id="a-non-ascii-trailer",
        ),
        pytest.param(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nzz\r\nab\r\n0\r\n\r\n",
            "hexadecimal",
            id="a-chunk-size-that-is-not-hexadecimal",
        ),
        pytest.param(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n1_0\r\nab\r\n0\r\n\r\n",
            "hexadecimal",
            id="a-chunk-size-python-would-read-and-nobody-else-would",
        ),
        pytest.param(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n2\r\nabcd\r\n0\r\n\r\n",
            "terminate a chunk",
            id="a-chunk-longer-than-its-size",
        ),
    ],
)
async def test_a_response_this_seam_will_not_read_is_refused(octets: bytes, why: str) -> None:
    """One arm per shape, because each is a separate branch of the reader.

    Every one of these is a far end answering something HTTP/1.1 does not admit —
    or admits only under a leniency (obsolete line folding, a body framed two ways
    at once) that is what request smuggling and response splitting are built out
    of. The refusal is the same class for all of them: a caller acts identically,
    which is :class:`~ai_assistant.core.errors.EgressBindingError`'s argument one
    surface over.
    """
    channel = far_end(octets)
    subject, _ = exchange(channel)

    with pytest.raises(MalformedHttpResponseError, match=why):
        await subject.get(origin=ORIGIN, target=TARGET)

    assert channel.closed


async def test_a_provider_error_status_is_returned_rather_than_refused() -> None:
    """A ``4xx`` is the provider's answer, and reading it is the searcher's job.

    Asserted so that the row above cannot quietly grow into "every status this seam
    dislikes": ADR-0231 §17's Lane 3 is what maps a provider refusal onto a
    ``SearchRefusal``, and it cannot do that for a response it never sees.
    """
    channel = far_end(response(status="HTTP/1.1 429 Too Many Requests", body=b"slow down"))
    subject, _ = exchange(channel)

    answer = await subject.get(origin=ORIGIN, target=TARGET)

    assert (answer.status, answer.body) == (429, b"slow down")


# --------------------------------------------------------------------------- #
# Row 5 — a deadline                                                            #
# --------------------------------------------------------------------------- #


async def test_a_deadline_inside_the_read_releases_the_channel() -> None:
    """ADR-0029 §4's invocation deadline is the only bound on a hanging call.

    :class:`~ai_assistant.core.protocols.ByteChannel` "carries no timeout, no
    deadline and no retry parameter" precisely so that there is one place a call
    can be cut. What this exchange owes is that being cut there leaves nothing
    behind: the channel it opened is released, and no partial response is returned
    in place of an answer.
    """
    channel = _SilentFarEnd()
    subject = HttpsExchange(transport=_ServesOne(channel), max_response_bytes=BOUND)

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):
            await subject.get(origin=ORIGIN, target=TARGET, headers=[CREDENTIAL])

    assert channel.closed
    assert bytes(channel.written).startswith(b"GET ")


# --------------------------------------------------------------------------- #
# Row 6 — a response that reaches the read bound                                #
# --------------------------------------------------------------------------- #


async def test_a_response_of_exactly_the_bound_is_read_whole() -> None:
    """ADR-0231 §5: "a response **exactly at** the bound is read whole and parsed"."""
    head = b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\n"
    octets = head + b"0123456789"
    channel = far_end(octets)
    subject, _ = exchange(channel, bound=len(octets))

    answer = await subject.get(origin=ORIGIN, target=TARGET)

    assert answer.body == b"0123456789"
    assert await drained(channel) == 0


async def test_a_response_one_byte_over_the_bound_is_abandoned() -> None:
    """The other half of the same pair, which fails a comparison the wrong way round."""
    head = b"HTTP/1.1 200 OK\r\nContent-Length: 11\r\n\r\n"
    octets = head + b"0123456789A"
    channel = far_end(octets)
    subject, _ = exchange(channel, bound=len(octets) - 1)

    with pytest.raises(HttpsResponseTooLargeError, match=str(len(octets) - 1)):
        await subject.get(origin=ORIGIN, target=TARGET)

    assert channel.closed


async def test_the_read_stops_at_the_bound_rather_than_measuring_afterwards() -> None:
    """ADR-0231 §5's last clause, asserted over what was left on the channel.

    "No implementation buffers a whole response, parses incrementally past the
    bound, or measures a response after assembling it." A far end with far more to
    give than the bound admits is the case that tells those apart: a conforming
    exchange takes exactly one octet past the bound and leaves the rest, and one
    that read to end of stream first would leave nothing however it then refused.

    The body carries **no declared length**, so nothing but the bound could stop
    the read — ADR-0231 §18's "including one whose declared length is absent and
    whose body never ends".
    """
    head = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n"
    surplus = 40 * 1024
    bound = len(head) + 1024
    channel = far_end(head + b"x" * (1024 + surplus))
    subject, _ = exchange(channel, bound=bound)

    with pytest.raises(HttpsResponseTooLargeError):
        await subject.get(origin=ORIGIN, target=TARGET)

    assert await drained(channel) == surplus - 1
    assert channel.closed


async def test_a_bound_below_one_is_refused_at_construction() -> None:
    """``Settings`` refuses it at load; this states the same rule at the object.

    A bound of zero is a mechanism that refuses every response while appearing
    configured, which is the shape ADR-0230 §6's domain rule exists to prevent and
    ADR-0231 §5 restates for this field.
    """
    with pytest.raises(ValueError, match="at least 1"):
        HttpsExchange(transport=FakeOutboundTransport(), max_response_bytes=0)


# --------------------------------------------------------------------------- #
# Row 7 — each of ADR-0231 §8's refusals, at the exchange                       #
# --------------------------------------------------------------------------- #

#: Every form ADR-0231 §8 refuses, in §18's own order. The canonicaliser's own
#: cases live in ``test_destinations.py``; what is asserted here is the property
#: only the exchange can break — that a refused origin opens **no channel**, so
#: nothing is disclosed to a host whose canonical form this seam cannot state.
REFUSED_ORIGINS: Final = (
    "http://search.example.invalid",
    "https://user@search.example.invalid",
    "https://search.example.invalid?q=1",
    "https://search.example.invalid#f",
    "https://",
    "https://sëarch.example.invalid",
    "https://search.example.invalid.",
    "https://search..example.invalid",
    f"https://{'a' * 64}.example.invalid",
    "https://-search.example.invalid",
    "https://search-.example.invalid",
    "https://127.0.0.1",
    "https://127.1",
    "https://2130706433",
    "https://0x7f000001",
    "https://search.example.invalid:",
    "https://search.example.invalid:/",
    "https://search.example.invalid:0443",
    "https://search.example.invalid:https",
    "https://search.example.invalid:65536",
    "https://search.example.invalid/a",
    "https://search.example.invalid/b",
)


@pytest.mark.parametrize("origin", REFUSED_ORIGINS)
async def test_an_origin_this_seam_will_not_canonicalise_opens_no_channel(origin: str) -> None:
    """ADR-0148 §1's third clause at the transport: refused before anything is spent.

    A refused origin is refused **before** ``open_channel``, so a form whose
    equivalence class §8 cannot state truthfully never becomes a connection — and
    never a credential presented to whatever it would have resolved to. The
    path-bearing pair is here for §18's own reason: each is refused independently,
    and nothing asserts that either canonicalises to anything.
    """
    transport = FakeOutboundTransport()
    subject = HttpsExchange(transport=transport, max_response_bytes=BOUND)

    with pytest.raises(TransportPinError):
        await subject.get(origin=origin, target=TARGET, headers=[CREDENTIAL])

    assert transport.attempts == ()


@pytest.mark.parametrize("origin", REFUSED_ORIGINS)
def test_no_refused_origin_yields_an_endpoint(origin: str) -> None:
    """The same forms at :func:`parse_https_origin`, which is where the pin is derived.

    Stated separately from the row above because the two could come apart: an
    exchange that caught its own refusal and defaulted an endpoint would pass one
    of them.
    """
    with pytest.raises(TransportPinError):
        parse_https_origin(origin)


def test_an_accepted_origin_pins_the_host_and_the_port_it_named() -> None:
    """The other direction, so that the row above is not passing by refusing everything."""
    assert parse_https_origin("HTTPS://Search.Example.INVALID") == TransportEndpoint(
        host="search.example.invalid", port=443, implicit_tls=True
    )
    assert parse_https_origin("https://search.example.invalid:8443") == TransportEndpoint(
        host="search.example.invalid", port=8443, implicit_tls=True
    )


# --------------------------------------------------------------------------- #
# What a caller may not write, which is the request half of the same discipline #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "target",
    [
        pytest.param("v1/search", id="no-leading-slash"),
        pytest.param("/v1/search q", id="a-space"),
        pytest.param("/v1/search\r\nX-Injected: 1", id="a-request-line-injection"),
        pytest.param("/v1/séarch", id="a-non-ascii-octet"),
        pytest.param("/v1/search\x00", id="a-control-character"),
        pytest.param("/v1/search?q=weather#fragment", id="a-fragment"),
        pytest.param("/#", id="a-bare-fragment-marker"),
        pytest.param("/v1/search?q=%ZZ", id="an-escape-that-is-not-hexadecimal"),
        pytest.param("/v1/search?q=%A", id="an-escape-of-one-digit"),
        pytest.param("/v1/search?q=a%", id="a-percent-at-the-end"),
        pytest.param("/v1/search\\path", id="a-backslash"),
        pytest.param("/v1/search?q=a<b", id="an-angle-bracket"),
        pytest.param("/v1/search?q=a|b", id="a-pipe"),
        pytest.param("/v1/search?q=a`b", id="a-backtick"),
        pytest.param("/v1/search?q=a{b}", id="a-brace"),
        pytest.param('/v1/search?q="a"', id="a-quotation-mark"),
    ],
)
async def test_a_target_this_seam_will_not_write_opens_no_channel(target: str) -> None:
    """A target is percent-encoded by whoever composed it, and is refused otherwise.

    The refusal is before the open for :func:`test_an_origin_this_seam_will_not_
    canonicalise_opens_no_channel`'s reason, and the CRLF arm is the one that
    matters most: a target carrying one writes a request line this seam did not
    compose.
    """
    transport = FakeOutboundTransport()
    subject = HttpsExchange(transport=transport, max_response_bytes=BOUND)

    with pytest.raises(TransportPinError, match="target"):
        await subject.get(origin=ORIGIN, target=target, headers=[CREDENTIAL])

    assert transport.attempts == ()


@pytest.mark.parametrize(
    ("name", "value", "why"),
    [
        pytest.param("Host", "elsewhere.example.invalid", "writes itself", id="a-second-host"),
        pytest.param("Content-Length", "0", "writes itself", id="a-request-framing"),
        pytest.param("Transfer-Encoding", "chunked", "writes itself", id="a-request-coding"),
        pytest.param("Connection", "keep-alive", "writes itself", id="a-kept-alive-channel"),
        pytest.param("X-Bad Name", "x", "token", id="a-name-holding-a-space"),
        pytest.param("X-Bad:Name", "x", "token", id="a-name-holding-a-colon"),
        pytest.param("", "x", "token", id="an-empty-name"),
        pytest.param("Authorization", "Bearer x\r\nHost: e", "printable ASCII", id="a-fold"),
        pytest.param("Authorization", "Bearer ké", "printable ASCII", id="a-non-ascii-value"),
    ],
)
async def test_a_header_this_seam_will_not_write_opens_no_channel(
    name: str, value: str, why: str
) -> None:
    """The four fields this exchange owns, and the two character sets around them.

    The reserved four are the recipient and the framing: a caller able to write a
    second ``Host`` selects a virtual host no ruling saw, and one able to write a
    ``Content-Length`` frames a request body this exchange does not send. The
    character sets are the injection defence, and the credential travels in one of
    these values — which is why no message here names one.
    """
    transport = FakeOutboundTransport()
    subject = HttpsExchange(transport=transport, max_response_bytes=BOUND)

    with pytest.raises(TransportPinError, match=why) as raised:
        await subject.get(origin=ORIGIN, target=TARGET, headers=[(name, value)])

    assert value not in str(raised.value)
    assert transport.attempts == ()


async def test_a_well_formed_trailer_is_read_and_discarded() -> None:
    """The other side of the trailer arms above, so the grammar is not read as a ban.

    RFC 9112 §7.1.2 allows a trailer section and this exchange discards it: what
    the arms above assert is that it is discarded *after* being read under the
    header section's own grammar, not that a conforming one is refused.
    """
    body = b"3\r\nabc\r\n0\r\nX-Trailer: 1\r\nX-Another: 2\r\n\r\n"
    channel = far_end(response(headers=["Transfer-Encoding: chunked"], body=body))
    subject, _ = exchange(channel)

    answer = await subject.get(origin=ORIGIN, target=TARGET)

    assert answer.body == b"abc"
    assert answer.headers == (("transfer-encoding", "chunked"),)


async def test_an_oversized_body_behind_a_well_formed_head_yields_no_response() -> None:
    """ADR-0231 §5's "nothing is parsed", asserted as what a caller can observe.

    The head is valid and is read before the body's size is known — it has to be,
    since it is what says where the body ends, and §5's own last clause forbids the
    alternative ("no implementation **buffers a whole response**"). What §5 buys is
    therefore not that no octet is ever looked at, but that an over-bound response
    yields **no value at all**: no `HttpsResponse` reaches the caller, so no body
    reaches a decoder and no record can be minted from one.

    Driven with the head and the body delivered as separate chunks, so the far end
    really does answer its status and fields before the octet that passes the bound
    exists — which is the arrangement adversarial round 1 asked for.
    """
    head = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n"
    bound = len(head) + 8
    channel = far_end(head, b'{"results"', b": [1,2,3]}")
    subject, _ = exchange(channel, bound=bound)

    with pytest.raises(HttpsResponseTooLargeError):
        await subject.get(origin=ORIGIN, target=TARGET)

    assert channel.closed


async def test_a_head_alone_past_the_bound_is_refused_before_the_body_is_reached() -> None:
    """And the bound bites inside the field section too, which is the same counter.

    §5 counts "over the bytes taken off the channel", so a far end that never
    stops sending header fields buys no more than one that never stops sending a
    body. An implementation whose bound was a *body* bound with a header allowance
    beside it would read this whole head and then start counting.
    """
    head = b"HTTP/1.1 200 OK\r\n" + b"X-Filler: " + b"x" * 4000 + b"\r\n\r\n"
    channel = far_end(head + b"body")
    subject, _ = exchange(channel, bound=64)

    with pytest.raises(HttpsResponseTooLargeError):
        await subject.get(origin=ORIGIN, target=TARGET)

    assert await drained(channel) == len(head) + len(b"body") - 65
    assert channel.closed


async def test_an_empty_reason_phrase_is_read_rather_than_refused() -> None:
    """The boundary the status-line grammar deliberately leaves open.

    RFC 9112 §4 writes the reason phrase as ``1*(...)``, but `HTTP/1.1 200 ` with
    nothing after the space is what several ordinary front ends send, and refusing
    it would be refusing a far end nobody would call malformed. What is refused is
    the missing **space**, and a control octet inside the phrase — not its absence.
    """
    channel = far_end(b"HTTP/1.1 200 \r\nContent-Length: 2\r\n\r\nhi")
    subject, _ = exchange(channel)

    answer = await subject.get(origin=ORIGIN, target=TARGET)

    assert (answer.status, answer.body) == (200, b"hi")


async def test_a_field_value_keeps_its_interior_spacing_and_loses_its_edges() -> None:
    """RFC 9110 §5.5: the surrounding whitespace is framing, the interior is content.

    Asserted beside the control-octet arms above so the new check cannot quietly
    become a stricter one: a value with tabs and spaces *inside* it is ordinary
    (`text/html; charset=utf-8` is the everyday case), and only its edges move.
    """
    channel = far_end(b"HTTP/1.1 200 OK\r\nContent-Type: \ttext/html; charset=utf-8 \r\n\r\n")
    subject, _ = exchange(channel)

    answer = await subject.get(origin=ORIGIN, target=TARGET)

    assert answer.headers == (("content-type", "text/html; charset=utf-8"),)


@pytest.mark.parametrize(
    ("octets", "status"),
    [
        pytest.param(
            b"HTTP/1.1 204 No Content\r\nContent-Length: 3\r\n\r\nbad", 204, id="204-with-a-length"
        ),
        pytest.param(b"HTTP/1.1 204 No Content\r\n\r\n", 204, id="204-with-no-framing-at-all"),
        pytest.param(
            b"HTTP/1.1 205 Reset Content\r\nContent-Length: 3\r\n\r\nbad",
            205,
            id="205-with-a-length",
        ),
        pytest.param(
            b"HTTP/1.1 205 Reset Content\r\nTransfer-Encoding: chunked\r\n"
            b"\r\n3\r\nbad\r\n0\r\n\r\n",
            205,
            id="205-with-a-coding",
        ),
        pytest.param(b"HTTP/1.1 205 Reset Content\r\n\r\nbad", 205, id="205-framed-by-the-close"),
        pytest.param(
            b"HTTP/1.1 204 No Content\r\nContent-Length: 1\r\nTransfer-Encoding: chunked\r\n\r\nx",
            204,
            id="204-framed-two-ways-at-once",
        ),
    ],
)
async def test_a_status_that_admits_no_content_is_framed_by_the_header_section(
    octets: bytes, status: int
) -> None:
    """RFC 9112 §6.3's first rule, which decides the framing before any field does.

    "Any response to a HEAD request and any response with a 1xx, 204, or 304 status
    code is always terminated by the first empty line after the header fields,
    **regardless of the header fields present** in the message." So the octets
    after the header section are not this response's body, and returning them would
    hand a caller bytes it would read as provider payload — which is what
    adversarial round 3 found.

    The two-framings arm is here deliberately: on such a status the standard states
    the framing itself, so there is nothing to resolve and nothing to refuse — the
    refusal for a body framed two ways governs a response that *has* one.

    **``205`` is here on a different rule and the arms say so.** RFC 9112 §6.3's
    list does not hold it; RFC 9110 §15.3.6 does the work instead — "a server MUST
    NOT generate content in a ``205`` response" — so a ``205`` carrying a length, a
    coding or bare octets is a server breaking that, and the octets are declined
    rather than handed back as payload. All three of those framings are driven,
    because a set-membership fix that missed one would pass a single-arm test.

    **The other two members of §6.3's list are covered where they are actually
    refused**: an interim status is a malformed shape (above), and ``304`` is
    inside the ``3xx`` class this seam refuses whole, which the redirect row
    asserts for it by name. A test driving a ``304`` through the body reader would
    be asserting over a path no response can take.
    """
    channel = far_end(octets)
    subject, _ = exchange(channel)

    answer = await subject.get(origin=ORIGIN, target=TARGET)

    assert (answer.status, answer.body) == (status, b"")


async def test_a_header_value_may_carry_the_octet_a_target_may_not() -> None:
    """The two character sets are drawn from one repertoire and are not each other.

    ``#`` is excluded from a request target because RFC 9112 §3.2.1's origin-form
    carries no fragment; it is ordinary inside a field value, and an ``ETag`` or a
    ``Content-Disposition`` filename can hold one. Asserted in both directions, so
    that narrowing the target set cannot silently narrow the header set with it.
    """
    channel = far_end(response(headers=['ETag: "v1#2"'], body=b"{}"))
    subject, _ = exchange(channel)

    answer = await subject.get(origin=ORIGIN, target=TARGET, headers=[("If-Match", '"v1#2"')])

    assert ("etag", '"v1#2"') in answer.headers
    assert 'If-Match: "v1#2"' in request_of(channel)


@pytest.mark.parametrize(
    "target",
    [
        pytest.param("/", id="the-root"),
        pytest.param("/v1/search?q=a%20b%2Fc", id="well-formed-escapes"),
        pytest.param("/v1/search?q=a%2f%2F", id="escapes-in-either-case"),
        pytest.param("/a-b_c.~/x?y=z&w=1", id="unreserved-and-sub-delims"),
        pytest.param("/v1/search?q=!$&'()*+,;=:@/?", id="every-literal-the-grammar-admits"),
    ],
)
async def test_an_origin_form_target_is_written_exactly_as_it_was_given(target: str) -> None:
    """The other side of the target refusals, so the grammar is not read as a ban.

    Every character RFC 3986 admits literally in a path or a query is admitted
    here, and a well-formed escape passes in either case — an implementation that
    refused `%2F` while accepting `%2f`, or that re-encoded what it was handed,
    would fail this. The target is written **byte for byte**: encoding is the
    composer's, and a seam that touched it would be composing a different request
    from the one it was asked for.
    """
    channel = far_end(response(body=b"{}"))
    subject, _ = exchange(channel)

    await subject.get(origin=ORIGIN, target=target)

    assert request_of(channel)[0] == f"GET {target} HTTP/1.1"
