"""The door's parser: bounded whole, incremental, and unwilling to guess (ADR-0168 §8)."""

from __future__ import annotations

import asyncio

import pytest

from ai_assistant.interfaces.gateway.http import (
    IncompleteRequestError,
    MalformedRequestError,
    Request,
    RequestTooLargeError,
    Response,
    read_request,
    render,
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
