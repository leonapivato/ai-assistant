"""The door's parser: bounded whole, incremental, and unwilling to guess (ADR-0168 §8)."""

from __future__ import annotations

import asyncio
import sys

import pytest
from _int_str_digits import pinned_int_str_digits

from ai_assistant.interfaces.gateway.http import (
    _METHOD_FIRST_BYTES,
    _METHODS,
    IncompleteRequestError,
    MalformedRequestError,
    Request,
    RequestTooLargeError,
    Response,
    StreamHead,
    read_request,
    render,
    render_chunk,
    render_stream_end,
    render_stream_head,
)

_CAP = 4096


class _Trickle:
    """A reader that hands over one byte at a time and then stops.

    A cap "enforced incrementally and locally" is a claim about *reads*, so the
    subject has to be something that answers a read with less than was asked for
    — which a whole buffer handed over at once cannot exercise.
    """

    def __init__(self, payload: bytes, *, endless: bool = False) -> None:
        self.payload = payload
        self.endless = endless
        self.offset = 0
        self.served = 0

    async def read(self, count: int) -> bytes:
        """Serve at most one byte per call, so the loop is the thing under test."""
        if self.offset >= len(self.payload):
            if not self.endless:
                return b""
            self.served += 1
            return b"x"
        taken = self.payload[self.offset : self.offset + min(count, 1)]
        self.offset += len(taken)
        self.served += len(taken)
        return taken


def _reader(payload: bytes) -> asyncio.StreamReader:
    """A real ``StreamReader`` holding a whole request and then EOF."""
    reader = asyncio.StreamReader()
    reader.feed_data(payload)
    reader.feed_eof()
    return reader


def _request(head: str, body: bytes = b"") -> bytes:
    """Frame one request, with CRLF line endings and a blank line."""
    return head.replace("\n", "\r\n").encode() + b"\r\n" + body


async def test_a_get_is_parsed_into_method_path_and_headers() -> None:
    """The smallest thing the door has to do."""
    payload = _request("GET /app.js HTTP/1.1\nHost: 127.0.0.1:8422\n")

    request = await read_request(_reader(payload), max_bytes=_CAP)

    assert request.method == "GET"
    assert request.path == "/app.js"
    assert request.header("host") == "127.0.0.1:8422"
    assert request.body == b""


async def test_a_query_string_is_dropped_from_the_path() -> None:
    """Nothing here reads a query string, and ADR-0168 §6 keeps session values out
    of URLs entirely — so routing sees the path and no more."""
    payload = _request("GET /app.js?v=2 HTTP/1.1\nHost: h\n")

    request = await read_request(_reader(payload), max_bytes=_CAP)

    assert request.path == "/app.js"


async def test_a_post_body_is_read_to_its_declared_length() -> None:
    """The body is exactly ``Content-Length`` bytes, and no framing but that one."""
    payload = _request("POST /ask HTTP/1.1\nHost: h\nContent-Length: 5\n", b"hello")

    request = await read_request(_reader(payload), max_bytes=_CAP)

    assert request.body == b"hello"


async def test_a_request_past_the_cap_is_refused_before_it_is_buffered_past_it() -> None:
    """§8: "refusing as soon as the bytes it has read on a connection exceed the
    limit and before it buffers past it, rather than on a complete request it has
    already held".

    The reader is endless and never sends a blank line, so a parser that waited
    for a whole request would never stop. The count is what makes the claim: it
    reads one byte past the cap and refuses, rather than reading on.
    """
    trickle = _Trickle(b"GET / HTTP/1.1\r\nHost: h\r\n", endless=True)

    with pytest.raises(RequestTooLargeError):
        await read_request(trickle, max_bytes=64)  # type: ignore[arg-type] # a reader is what it reads

    assert trickle.served <= 65


def test_the_cap_bounds_the_request_whole_and_not_the_body_alone() -> None:
    """§8 bounds "its request line, its headers and its body together".

    An earlier draft that bounded the body alone "left the framing open": a peer
    inside its deadline can send an enormous request line or header, and a bound
    naming the body has nothing to say while the parser buffers it.
    """
    head = "GET /" + "a" * 200 + " HTTP/1.1\nHost: h\n"

    async def run() -> None:
        await read_request(_reader(_request(head)), max_bytes=100)

    with pytest.raises(RequestTooLargeError):
        asyncio.run(run())


async def test_a_declared_length_past_the_cap_is_refused_without_reading_the_body() -> None:
    """Knowing the request is over the limit is enough to refuse it."""
    payload = _request("POST /ask HTTP/1.1\nHost: h\nContent-Length: 100000\n")

    with pytest.raises(RequestTooLargeError):
        await read_request(_reader(payload), max_bytes=_CAP)


async def test_a_stream_that_ends_mid_request_is_incomplete_and_not_malformed() -> None:
    """Three outcomes, kept apart because the caller answers them differently."""
    reader = asyncio.StreamReader()
    reader.feed_data(b"GET / HTTP/1.1\r\nHost: h")
    reader.feed_eof()

    with pytest.raises(IncompleteRequestError):
        await read_request(reader, max_bytes=_CAP)


@pytest.mark.parametrize(
    "head",
    [
        pytest.param("PUT / HTTP/1.1\nHost: h\n", id="a method this door does not serve"),
        pytest.param(
            "DELETE / HTTP/1.1\nHost: h\n",
            id="a method whose first byte cannot begin one this door serves",
        ),
        pytest.param("GET / HTTP/1.0\nHost: h\n", id="a version it was not written against"),
        pytest.param("GET HTTP/1.1\nHost: h\n", id="a request line with two parts"),
        pytest.param("GET app.js HTTP/1.1\nHost: h\n", id="a target that is not a path"),
        pytest.param("GET / HTTP/1.1\nHost h\n", id="a header with no colon"),
        pytest.param("GET / HTTP/1.1\nHost: h\n Continued: yes\n", id="a folded header line"),
        pytest.param("GET / HTTP/1.1\n: empty\n", id="a header with no name"),
        pytest.param(
            "GET / HTTP/1.1\nHost: h\nbad name: x\n", id="a header name with a space in it"
        ),
        pytest.param(
            "GET / HTTP/1.1\nHost: h\nbad@name: x\n", id="a header name outside the token set"
        ),
        pytest.param(
            "GET / HTTP/1.1\nHost: h\nbad\tname: x\n", id="a header name with a tab in it"
        ),
        pytest.param(
            "POST /ask HTTP/1.1\nHost: h\nTransfer-Encoding: chunked\n",
            id="a second framing",
        ),
        pytest.param(
            "POST /ask HTTP/1.1\nHost: h\nContent-Length: five\n",
            id="a length that is not a number",
        ),
        pytest.param("POST /ask HTTP/1.1\nHost: h\nContent-Length: -1\n", id="a negative length"),
        pytest.param(
            "POST /ask HTTP/1.1\nHost: h\nContent-Length: 1\nContent-Length: 2\n",
            id="two lengths that disagree",
        ),
        # RFC 9110 makes `Content-Length` a `1*DIGIT`, and `int` reads three
        # spellings that grammar does not have (issue #1333). Each is refused for
        # this module's stated reason rather than because it mis-frames anything:
        # a spelling the specification does not have is a line two parsers would
        # read differently, and the door in front of every local process is where
        # that matters.
        pytest.param("POST /ask HTTP/1.1\nHost: h\nContent-Length: +5\n", id="a signed length"),
        pytest.param(
            "POST /ask HTTP/1.1\nHost: h\nContent-Length: -0\n",
            id="a signed zero, which is not negative and so passed the old check",
        ),
        pytest.param(
            "POST /ask HTTP/1.1\nHost: h\nContent-Length: 1_0\n",
            id="a Python integer separator, read as ten",
        ),
        pytest.param(
            "POST /ask HTTP/1.1\nHost: h\nContent-Length: \n",
            id="a length declared and left empty",
        ),
        pytest.param(
            "POST /ask HTTP/1.1\nHost: h\nContent-Length: 5 5\n",
            id="two lengths on one line",
        ),
    ],
)
async def test_a_request_this_door_would_have_to_guess_at_is_refused(head: str) -> None:
    """ "A request this module cannot parse is refused rather than guessed at."

    A tolerant parser at a port every local process can reach is a second
    interpretation of a request for someone to disagree with, and the session in
    front of it is only as good as the request it was decided on.
    """
    with pytest.raises(MalformedRequestError):
        await read_request(_reader(_request(head)), max_bytes=_CAP)


# --- Issue #1369: a first read that cannot begin a request ------------------

#: The opening of a TLS ClientHello: a handshake record (``0x16``) carrying TLS
#: 1.0's version number (``0x03 0x01``), then its length and the handshake's own
#: type. This is what a browser sends when the address it was given says
#: ``https://``, and it is what the milestone-14 phone QA watched stall (#1373).
_CLIENT_HELLO = b"\x16\x03\x01\x02\x00\x01" + b"\x00" * 300


async def test_a_tls_handshake_is_refused_on_its_first_byte_and_not_waited_out() -> None:
    """A ClientHello contains no blank line, so a parser that waits for one waits
    out the deadline — which is what the phone QA found: a white screen, nothing
    written back, and a fresh attempt every thirty seconds (#1369).

    The reader is endless, so a parser that read on would never stop; the count is
    what makes the claim. One byte is enough to know these bytes are not a
    request, and this door refuses what it cannot parse rather than guessing at
    it.
    """
    trickle = _Trickle(_CLIENT_HELLO, endless=True)

    with pytest.raises(MalformedRequestError):
        await read_request(trickle, max_bytes=_CAP)  # type: ignore[arg-type] # a reader is what it reads

    assert trickle.served == 1


async def test_a_request_whose_first_byte_arrives_alone_is_still_parsed() -> None:
    """The refusal above narrows nothing legitimate.

    The check reads the byte the reader has already handed over and never asks for
    another, so a peer sending one byte at a time is bounded by the caller's
    deadline exactly as it was — and a `GET` delivered that way is still a `GET`.
    """
    trickle = _Trickle(_request("GET /app.js HTTP/1.1\nHost: h\n"))

    request = await read_request(trickle, max_bytes=_CAP)  # type: ignore[arg-type] # a reader is what it reads

    assert request.method == "GET"
    assert request.path == "/app.js"


def test_the_first_byte_rule_is_derived_from_the_methods_this_door_serves() -> None:
    """Every byte it refuses is one `_parse_head` would have refused anyway.

    That equivalence is what makes the change a matter of *when* rather than of
    *what*, and it is pinned rather than described: a door that grows a method
    must not be left refusing a request it now serves, and one that loses a method
    must not be left admitting that first byte until the head is complete.
    """
    assert {chr(byte) for byte in _METHOD_FIRST_BYTES} == {method[0] for method in _METHODS}


async def test_optional_whitespace_around_a_length_is_stripped_and_not_refused() -> None:
    """The one spelling that looks like the refusals above and is not one.

    RFC 9110 §5.5 puts optional whitespace around *every* field value and has a
    recipient strip it before interpreting, so `` 5 `` is a well-formed
    ``Content-Length`` of five where ``+5`` is not a ``Content-Length`` at all.
    Issue #1333 proposed refusing both; only the second is outside the grammar, and
    a door that refused the first would be intolerant of a request the
    specification does have.
    """
    payload = _request("POST /ask HTTP/1.1\nHost: h\nContent-Length: \t 5 \t\n", b"hello")

    request = await read_request(_reader(payload), max_bytes=_CAP)

    assert request.body == b"hello"


async def test_a_length_too_long_to_convert_is_refused_and_not_raised() -> None:
    """A digit string past the interpreter's own str-to-int guard.

    Every non-digit spelling is refused before the conversion, which leaves exactly
    one way for it to fail: CPython declines to convert a decimal string longer than
    ``sys.get_int_max_str_digits()``. That is still a request this door will not
    interpret, so it is refused as one — a ``ValueError`` out of the parser would
    reach a caller that catches :class:`RequestError` and nothing else.

    The cap is raised past the default here because the header has to *fit* for the
    conversion to be attempted at all; under ``_CAP`` this same request is refused
    one condition earlier, as too large.

    The digit limit is *pinned* rather than read off the ambient interpreter, because
    it can be disabled outright — ``PYTHONINTMAXSTRDIGITS=0`` or ``-X
    int_max_str_digits=0`` makes ``sys.get_int_max_str_digits()`` return ``0``. A
    length derived from that is the single character ``9``, which converts, and the
    ``except ValueError`` branch this test exists to pin goes unexercised while the
    case fails on the *next* condition instead (#1358). Pinning holds the branch
    reachable whatever the ambient setting is.
    """
    with pinned_int_str_digits():
        absurd = "9" * (sys.get_int_max_str_digits() + 1)
        payload = _request(f"POST /ask HTTP/1.1\nHost: h\nContent-Length: {absurd}\n")

        with pytest.raises(MalformedRequestError) as refusal:
            await read_request(_reader(payload), max_bytes=len(payload) + 1)

    # *Which* condition refused it is the whole of the case. With the limit
    # disabled the ambient-limit form of this test declared a nine-byte body and
    # was refused one condition later, as too large — a refusal this case is not
    # about. The cause pins the conversion's own `ValueError`, chained by
    # `_content_length`'s `raise ... from exc`.
    assert isinstance(refusal.value.__cause__, ValueError)


async def test_bytes_past_the_declared_body_are_refused_rather_than_reframed() -> None:
    """A peer that framed a second request before the first was answered."""
    payload = _request("POST /ask HTTP/1.1\nHost: h\nContent-Length: 2\n", b"ok") + _request(
        "GET / HTTP/1.1\nHost: h\n"
    )

    with pytest.raises(MalformedRequestError):
        await read_request(_reader(payload), max_bytes=_CAP)


async def test_a_repeated_header_reads_as_absent() -> None:
    """ADR-0168 §7 decides admission on `Host` and `Origin`.

    A door that picked the first of two would let the peer choose which one it is
    judged on, so two is not a value.
    """
    payload = _request("GET / HTTP/1.1\nHost: 127.0.0.1:8422\nHost: evil.example\n")

    request = await read_request(_reader(payload), max_bytes=_CAP)

    assert request.header("host") is None


async def test_every_cookie_of_one_name_is_returned_across_every_cookie_header() -> None:
    """ADR-0168 §6 turns on there being *more than one*, so none is counted out."""
    payload = _request(
        "GET / HTTP/1.1\nHost: h\nCookie: assistant_session=one; other=x\n"
        "Cookie: assistant_session=two\n"
    )

    request = await read_request(_reader(payload), max_bytes=_CAP)

    assert request.cookies("assistant_session") == ("one", "two")


def test_every_response_carries_the_content_security_policy() -> None:
    """ "The gateway serves **every** response with a content security policy"
    (ADR-0168 §6), which is why it is applied at the writer rather than per
    handler."""
    written = render(Response(200, "OK", body=b"x"), policy="default-src 'none'")

    assert b"Content-Security-Policy: default-src 'none'" in written


def test_a_closing_response_says_so_on_the_wire() -> None:
    """ADR-0168 §8 has a refusal close the connection; the peer is told."""
    assert b"Connection: close" in render(Response(400, "Bad Request", close=True), policy="p")
    assert b"Connection: keep-alive" in render(Response(200, "OK", close=False), policy="p")


def test_a_set_cookie_appears_only_when_there_is_one() -> None:
    """The bootstrap exchange is the only response carrying one (ADR-0168 §5, §6)."""
    assert b"Set-Cookie" not in render(Response(200, "OK"), policy="p")
    assert b"Set-Cookie: a=b" in render(Response(200, "OK", set_cookie="a=b"), policy="p")


def test_a_response_declares_its_own_length() -> None:
    """Framing the answer is the writer's half of reading one."""
    written = render(Response(200, "OK", body=b"hello"), policy="p")

    assert b"Content-Length: 5" in written
    assert written.endswith(b"\r\n\r\nhello")


@pytest.mark.parametrize(
    "name", ["X-Assistant-Session", "If-None-Match", "x_odd!name", "Accept-Encoding"]
)
async def test_a_header_name_inside_the_token_set_is_admitted(name: str) -> None:
    """The refusal narrows nothing legitimate: RFC 9110's `token` is the whole set,
    and it is wider than the names this gateway happens to read."""
    payload = _request(f"GET / HTTP/1.1\nHost: h\n{name}: value\n")

    request = await read_request(_reader(payload), max_bytes=_CAP)

    assert request.header(name.lower()) == "value"


def test_a_request_reports_a_header_that_is_absent_as_none() -> None:
    """The ordinary case, pinned beside the repeated one so the two are distinct."""
    request = Request(method="GET", path="/", headers=())

    assert request.header("origin") is None
    assert request.cookies("assistant_session") == ()


# --- ADR-0175 §1: the second response shape ---------------------------------


def test_a_stream_declares_a_chunked_transfer_and_no_length() -> None:
    """§1's largest single piece of work: ``Response.body`` is ``bytes`` and every
    response carries a ``Content-Length``, which is exactly what a stream cannot do.

    A length is not merely omitted — declaring one would be a claim about a body
    whose last piece does not exist yet.
    """
    written = render_stream_head(StreamHead(content_type="application/x-ndjson"), policy="p")

    assert b"Transfer-Encoding: chunked" in written
    assert b"Content-Length" not in written
    assert written.endswith(b"\r\n\r\n")


def test_a_stream_carries_every_header_an_ordinary_response_does() -> None:
    """ADR-0168 §6 requires the policy on *every* response, "which is why the policy
    is applied here rather than by each handler that might forget one" — and a
    streamed response is the shape most easily forgotten.
    """
    streamed = render_stream_head(StreamHead(content_type="application/x-ndjson"), policy="p")
    whole = render(Response(200, "OK"), policy="p")

    for header in (
        b"Content-Security-Policy: p",
        b"X-Content-Type-Options: nosniff",
        b"Cache-Control: no-store",
    ):
        assert header in streamed, header
        assert header in whole, header


def test_a_stream_may_carry_headers_of_its_own_and_carries_none_by_default() -> None:
    """The slot a delivery stream states its keep-alive cadence in (#1442).

    A head is the one part of a streamed response that exists before its body does, so
    a fact about *how the stream will be written* belongs there rather than in a value
    on it — a value would fall under ADR-0175 §4's rule that at most one is pending per
    stream and that one still in flight when the next is due ends the stream, which is
    a rule about a browser that stopped reading and not about a preamble.

    **Empty by default**, so no stream states anything unless its handler chose to:
    the headers ADR-0168 §6 requires of every response are added by
    ``render_stream_head`` itself and are not what this slot is for.
    """
    bare = render_stream_head(StreamHead(content_type="text/plain"), policy="p")
    stated = render_stream_head(
        StreamHead(content_type="text/plain", headers=(("X-One", "1"), ("X-Two", "2"))),
        policy="p",
    )

    assert StreamHead(content_type="text/plain").headers == ()
    assert b"X-One" not in bare
    assert b"X-Two" not in bare
    assert b"X-One: 1\r\n" in stated
    assert b"X-Two: 2\r\n" in stated


def test_a_streams_own_headers_displace_nothing_the_head_owes() -> None:
    """A handler supplies values, never the shape of the head.

    The common headers ADR-0168 §6 requires come first and the transfer and connection
    lines last, with anything a handler added between them — so a header a handler
    chose can neither push one of §6's out nor change how the body is framed. The order
    is fixed in ``render_stream_head`` rather than at a call site, and
    :class:`StreamHead` is frozen.
    """
    written = render_stream_head(
        StreamHead(content_type="application/x-ndjson", headers=(("X-One", "1"),)),
        policy="p",
    )
    lines = written.split(b"\r\n")

    for header in (
        b"Content-Security-Policy: p",
        b"X-Content-Type-Options: nosniff",
        b"Cache-Control: no-store",
    ):
        assert lines.index(header) < lines.index(b"X-One: 1"), header
    assert lines.index(b"X-One: 1") < lines.index(b"Transfer-Encoding: chunked")
    assert lines.index(b"X-One: 1") < lines.index(b"Connection: keep-alive")


def test_a_stream_keeps_the_connection_by_default_and_closes_when_told() -> None:
    """A stream that finished is a response that completed, and ADR-0175 §7 restarts
    ``gateway_read_timeout`` from there rather than ending the connection."""
    assert b"Connection: keep-alive" in render_stream_head(StreamHead("t"), policy="p")
    assert b"Connection: close" in render_stream_head(StreamHead("t", close=True), policy="p")


def test_a_chunk_is_framed_by_its_own_length_in_hexadecimal() -> None:
    """Chunked transfer's own framing, so the reader needs no length up front."""
    assert render_chunk(b"hello") == b"5\r\nhello\r\n"
    assert render_chunk(b"x" * 255) == b"ff\r\n" + b"x" * 255 + b"\r\n"


def test_a_zero_length_chunk_is_refused_as_a_value() -> None:
    """It is HTTP's end-of-body marker, so one written mid-stream would end the body
    while the gateway believed it had written a value — the ending ADR-0175 §2 makes
    a *transport failure*, manufactured by the writer."""
    with pytest.raises(ValueError, match="end of a body"):
        render_chunk(b"")


def test_a_stream_ends_with_the_zero_length_chunk_and_no_trailers() -> None:
    """The clean ending, which is what lets a reader tell a stream that finished from
    one the network cut (ADR-0175 §2)."""
    assert render_stream_end() == b"0\r\n\r\n"
