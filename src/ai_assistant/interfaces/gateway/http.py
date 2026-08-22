"""The one HTTP/1.1 door the browser gateway speaks (ADR-0168 §2, §8).

**Hand-written, and the resource clauses are why.** ADR-0168 §8 bounds a browser
request *whole* — "its request line, its headers and its body together, not its
body alone" — and requires the bound "enforced incrementally and locally,
refusing as soon as the bytes it has read on a connection exceed the limit and
before it buffers past it, rather than on a complete request it has already
held". That is a property of the reader, not of a handler above one, and it is
ADR-0084 §3's own shape at this door: `hub_max_frame_bytes` bounds the whole
frame and its reader "never allocates the declared length up front" but "reads
incrementally against the cap".

The surface is deliberately the smallest one that serves a page and takes a
request: two methods, one framing, no chunked transfer, no continuation lines. A
request this module cannot parse is refused rather than guessed at — ADR-0168
§6's session exists because this port is reachable by every local process, and a
tolerant parser at that door is a second interpretation of a request for someone
to disagree with.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:  # pragma: no cover — imported for typing alone
    import asyncio

#: How many bytes are taken from the socket at a time. It bounds nothing on its
#: own — :func:`read_request` never asks for more than the cap leaves — and exists
#: only so a small request costs one read rather than one per byte.
_CHUNK_BYTES: Final = 4096

#: The end of a request's head. The body, where there is one, follows it and is
#: `Content-Length` bytes long.
_HEAD_TERMINATOR: Final = b"\r\n\r\n"

#: The only version this gateway speaks. ADR-0084 §3's exact-match reasoning read
#: at a different door: client and server here are a browser and a process the
#: owner started, and a version this module has not been written against is a
#: request it would be guessing at.
_HTTP_VERSION: Final = "HTTP/1.1"

#: The methods the gateway serves. Everything else is a request it will not
#: interpret, which is a malformed request as far as this door is concerned.
_METHODS: Final = frozenset({"GET", "POST"})

#: The bytes a request line may begin with — the first character of every method
#: in :data:`_METHODS`, derived rather than written out so a method added there
#: cannot leave this set behind. It is what lets :func:`read_request` reach the
#: verdict :func:`_parse_head` would have reached anyway, on the first byte
#: instead of on a head that may never arrive
#: (:func:`_refuse_unless_a_method_can_begin`).
_METHOD_FIRST_BYTES: Final = frozenset(ord(method[0]) for method in _METHODS)

#: A request line is a method, a target and a version, and nothing else.
_REQUEST_LINE_PARTS: Final = 3

#: The characters a header name may be made of — RFC 9110's `token`. Checked
#: rather than assumed, because "refused rather than guessed at" is the rule this
#: module is built on and a name with a space in it is a line two parsers would
#: read differently.
_TOKEN = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!#$%&'*+-.^_`|~")

#: The characters a `Content-Length` value may be made of — RFC 9110's `1*DIGIT`.
#: Checked for the same reason `_TOKEN` is: `int` reads spellings that grammar does
#: not have, and this door refuses rather than guesses (:func:`_content_length`).
_DIGITS = frozenset("0123456789")


class RequestError(Exception):
    """A browser request this door will not interpret.

    Carries no request content: what a refusal may say is ADR-0168 §3's subject,
    and the caller decides it. This type exists to separate "the stream ended" and
    "the bytes are past the cap" from "the request is not one we parse", because
    the three are answered differently.
    """


class IncompleteRequestError(RequestError):
    """The peer stopped sending before a whole request arrived."""


class MalformedRequestError(RequestError):
    """The bytes are not a request this door parses."""


class RequestTooLargeError(RequestError):
    """The request passed ``gateway_max_request_bytes`` (ADR-0168 §8)."""


@dataclass(frozen=True)
class Request:
    """One browser request, parsed no further than routing needs.

    Attributes:
        method: The request method, upper-case and one of :data:`_METHODS`.
        path: The request target with any query string removed. Routing reads
            this; nothing in this gateway reads a query string, and ADR-0168 §6
            forbids a session value ever appearing in a URL.
        headers: Every header, in arrival order, with names lower-cased. A
            sequence rather than a mapping because ADR-0168 §6 turns on there
            being *more than one* cookie of the gateway's own name, which a
            mapping would have already discarded.
        body: The request body, exactly ``Content-Length`` bytes.
    """

    method: str
    path: str
    headers: tuple[tuple[str, str], ...]
    body: bytes = b""

    def header(self, name: str) -> str | None:
        """The single value of ``name``, or ``None`` where it is absent or repeated.

        A repeated header is reported as absent rather than resolved, because
        every header this gateway reads decides an admission: ADR-0168 §7 refuses
        on `Host` and `Origin`, and a door that picked the first of two would let
        a peer choose which one it is judged on.

        Args:
            name: The header name, lower-case.

        Returns:
            The value, or ``None`` if the header is absent or appears more than
            once.
        """
        found = [value for header, value in self.headers if header == name]
        return found[0] if len(found) == 1 else None

    def cookies(self, name: str) -> tuple[str, ...]:
        """Every cookie called ``name``, across every ``Cookie`` header.

        ADR-0168 §6 makes "more than one cookie of the gateway's own name" a
        refusal of its own, so this returns them all and counts nothing out.

        Args:
            name: The cookie's name.

        Returns:
            The values presented under that name, in arrival order.
        """
        values: list[str] = []
        for header, value in self.headers:
            if header != "cookie":
                continue
            values.extend(
                pair.partition("=")[2].strip()
                for pair in value.split(";")
                if pair.partition("=")[0].strip() == name
            )
        return tuple(values)


@dataclass(frozen=True)
class Response:
    """What the gateway sends back, and whether the connection survives it.

    Attributes:
        status: The status line's code.
        reason: The status line's phrase.
        body: The payload, already encoded.
        content_type: The payload's media type.
        close: Whether the connection is closed once this is written. ADR-0168 §8
            requires it of every refusal and permits it of anything else; §9's
            report that the hub is unreachable "is not a refusal and closes
            nothing".
        set_cookie: A ``Set-Cookie`` value, or ``None``. The bootstrap exchange is
            the only response that carries one (ADR-0168 §5, §6).
    """

    status: int
    reason: str
    body: bytes = b""
    content_type: str = "text/plain; charset=utf-8"
    close: bool = True
    set_cookie: str | None = None


@dataclass(frozen=True)
class StreamHead:
    """The head of a response whose body the gateway writes in pieces (ADR-0175 §1).

    **The second response shape, and it is the largest single piece of work
    ADR-0175 creates** — its Consequences say so in terms: ``Response.body`` is
    ``bytes`` and every response carries a ``Content-Length``, which is exactly what
    a streamed answer and a delivery stream cannot do. A stream's length is unknown
    when its head is written and its whole purpose is that the browser reads the
    first piece before the last one exists.

    **Chunked transfer, and not "write and hang up".** Closing the connection to
    mark the end would make a stream that ended cleanly indistinguishable from one
    the network cut — and ADR-0175 §2 requires a reader to tell those apart. The
    terminal *value* is the primary signal, and the zero-length chunk below it is
    HTTP's own; a body that stops without either is the transport failure the front
    end reports as one.

    Attributes:
        content_type: The media type the stream is served with.
        status: The status line's code. Always a success: everything decidable
            before the engine is reached — an unadmitted request, a malformed body,
            a ceiling — is an ordinary :class:`Response` with its own status, and a
            stream's head is written only once the gateway has committed to
            answering on one.
        reason: The status line's phrase.
        close: Whether the connection is closed once the stream ends. ``False`` by
            default: a stream that finished is a response that completed, and
            ADR-0175 §7 restarts ``gateway_read_timeout`` from there.
    """

    content_type: str
    status: int = 200
    reason: str = "OK"
    close: bool = False


@dataclass
class _Reading:
    """The bytes taken off one connection so far, and the cap they are read against."""

    limit: int
    buffer: bytearray = field(default_factory=bytearray)

    async def fill(self, reader: asyncio.StreamReader) -> None:
        """Take one more chunk, never buffering past the cap (ADR-0168 §8).

        The chunk is sized so the buffer can reach exactly one byte past the
        limit and no further — enough to *know* the request is over it, which is
        what "before it buffers past it" leaves room for.

        Args:
            reader: The connection's reader.

        Raises:
            RequestTooLargeError: If the bytes already read are past the limit.
            IncompleteRequestError: If the peer stopped sending.
        """
        if len(self.buffer) > self.limit:
            raise RequestTooLargeError
        want = min(_CHUNK_BYTES, self.limit + 1 - len(self.buffer))
        chunk = await reader.read(want)
        if not chunk:
            raise IncompleteRequestError
        self.buffer.extend(chunk)
        if len(self.buffer) > self.limit:
            raise RequestTooLargeError


async def read_request(reader: asyncio.StreamReader, *, max_bytes: int) -> Request:
    """Read exactly one request, bounded whole and incrementally (ADR-0168 §8).

    Args:
        reader: The connection's reader.
        max_bytes: ``gateway_max_request_bytes``, bounding the request line, the
            headers and the body together.

    Returns:
        The parsed request.

    Raises:
        RequestTooLargeError: If the request passes ``max_bytes``. Raised as soon as
            the bytes read exceed it, not once a whole request has been held.
        IncompleteRequestError: If the peer stopped sending mid-request.
        MalformedRequestError: If the bytes are not a request this door parses —
            a first byte no method this door serves can begin with included, which
            is refused as soon as it is read rather than waited out
            (:func:`_refuse_unless_a_method_can_begin`).
    """
    reading = _Reading(limit=max_bytes)
    while _HEAD_TERMINATOR not in reading.buffer:
        await reading.fill(reader)
        _refuse_unless_a_method_can_begin(reading.buffer)
    head, _, body = bytes(reading.buffer).partition(_HEAD_TERMINATOR)
    method, path, headers = _parse_head(head)
    length = _content_length(headers)
    # The declared length is checked against the cap *before* a byte of it is
    # read: knowing the request is over the limit is enough to refuse, and reading
    # a megabyte to reach the same conclusion is what §8's "before it buffers past
    # it" is against.
    if len(head) + len(_HEAD_TERMINATOR) + length > max_bytes:
        raise RequestTooLargeError
    if len(body) > length:
        # Bytes past the declared body are a second request sent before the first
        # was answered. Refused rather than buffered: this door answers one request
        # at a time, and a peer that framed two is a peer this parser would be
        # guessing at — the thing every refusal in this module exists to avoid.
        raise MalformedRequestError
    while len(body) < length:
        chunk = await reader.read(min(_CHUNK_BYTES, length - len(body)))
        if not chunk:
            raise IncompleteRequestError
        body += chunk
    return Request(method=method, path=path, headers=headers, body=body)


def _refuse_unless_a_method_can_begin(buffer: bytearray) -> None:
    """Refuse a first byte no method this door serves can begin with (issue #1369).

    **The verdict is unchanged; only the moment is.** :data:`_METHOD_FIRST_BYTES`
    is derived from :data:`_METHODS`, and :func:`_parse_head` already refuses any
    request line whose method is not one of those — so every byte refused here is
    one that would have been refused as malformed at the end of the head. Nothing
    this door accepted becomes a refusal, and no refusal changes its condition.
    What changes is that the refusal no longer waits for a
    :data:`_HEAD_TERMINATOR` the peer is never going to send.

    **That wait is the fault, and it is not hypothetical.** A browser given
    ``https://`` for this listener by hand sends a TLS ClientHello — a record
    beginning ``0x16 0x03`` — which contains no blank line, so the loop above read
    on until ``gateway_read_timeout`` and the connection was then closed with
    nothing written and nothing recorded. The browser had no fault to show and
    retried, once every thirty seconds, which is what the milestone-14 phone QA
    found (#1373). A refusal on the first byte is what lets it fail at once.

    **It is checked against the methods rather than against the token charset**,
    because the tighter rule is the one this module already states: "a request
    this module cannot parse is refused rather than guessed at". A first byte
    inside RFC 9110's `token` but outside this set — ``DELETE``, ``OPTIONS`` — is
    a request this door does not serve either, and refusing it here rather than a
    kilobyte later reaches the same answer sooner. The set is derived, so that
    stays true of whatever :data:`_METHODS` holds.

    **It costs a legitimate slow peer nothing.** The check reads the byte the
    reader has already handed over and never waits for another, so a request whose
    first byte arrives late is bounded by the caller's deadline exactly as before,
    and one whose first byte arrives at all is judged on it and no sooner.

    Args:
        buffer: The bytes read from the connection so far. It is never empty here
            — :meth:`_Reading.fill` raises rather than return nothing — and an
            empty one is read as "nothing to judge yet" rather than as a refusal.

    Raises:
        MalformedRequestError: If the first byte cannot begin a request line.
    """
    if buffer and buffer[0] not in _METHOD_FIRST_BYTES:
        raise MalformedRequestError


def _parse_head(head: bytes) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    """Split a request's head into its method, path and headers.

    Args:
        head: The bytes before the blank line.

    Returns:
        The method, the path with any query string removed, and the headers with
        names lower-cased.

    Raises:
        MalformedRequestError: If the head is not one this door parses — a bad
            encoding, an unknown method or version, a folded header line, or a
            header without a name.
    """
    try:
        lines = head.decode("ascii").split("\r\n")
    except UnicodeDecodeError as exc:
        raise MalformedRequestError from exc
    parts = lines[0].split(" ")
    if len(parts) != _REQUEST_LINE_PARTS or parts[0] not in _METHODS or parts[2] != _HTTP_VERSION:
        raise MalformedRequestError
    if not parts[1].startswith("/"):
        raise MalformedRequestError
    return parts[0], parts[1].partition("?")[0], _parse_headers(lines[1:])


def _parse_headers(lines: list[str]) -> tuple[tuple[str, str], ...]:
    """Parse header lines, refusing anything this door would have to guess at.

    Args:
        lines: The head's lines after the request line.

    Returns:
        The headers, names lower-cased, in arrival order.

    Raises:
        MalformedRequestError: If a line is folded, carries no colon, or has an
            empty or non-token name.
    """
    headers: list[tuple[str, str]] = []
    for line in lines:
        if not line:
            continue
        if line[0] in " \t":
            raise MalformedRequestError
        name, sep, value = line.partition(":")
        if not sep or not name or not _TOKEN.issuperset(name):
            raise MalformedRequestError
        headers.append((name.lower(), value.strip()))
    return tuple(headers)


def _content_length(headers: tuple[tuple[str, str], ...]) -> int:
    """How many body bytes follow the head.

    ``Transfer-Encoding`` is refused rather than implemented: a chunked body is a
    second framing, and ADR-0168 §8's cap has to bound whatever framing arrives.
    One framing is one thing to bound.

    Args:
        headers: The parsed headers.

    Returns:
        The declared body length, or ``0`` where none is declared.

    **The value is checked against the grammar before it is converted**, exactly as
    a header name is checked against `token` above. RFC 9110 makes this field value
    `1*DIGIT`, and :func:`int` accepts three spellings that grammar does not have —
    a sign, an underscore separator, and a digit outside ASCII. A signed length is
    still read to exactly that many bytes and still bounded by
    ``gateway_max_request_bytes``, so nothing is mis-framed by accepting one; what
    it costs is this module's own rule, which is that a request it cannot parse is
    refused rather than guessed at. A spelling the specification does not have is a
    line two parsers would read differently, and this door is the one place a
    browser's framing is decided (issue #1333).

    Args:
        headers: The parsed headers.

    Returns:
        The declared body length, or ``0`` where none is declared.

    Raises:
        MalformedRequestError: If a transfer encoding is declared, or the length is
            absent-by-repetition, empty, or anything but ASCII decimal digits.
    """
    if any(name == "transfer-encoding" for name, _ in headers):
        raise MalformedRequestError
    declared = [value for name, value in headers if name == "content-length"]
    if not declared:
        return 0
    if len(declared) != 1:
        raise MalformedRequestError
    value = declared[0]
    if not value or not _DIGITS.issuperset(value):
        raise MalformedRequestError
    try:
        return int(value)
    except ValueError as exc:
        # Every spelling `int` rejects has been refused above, so what is left is
        # the interpreter's own guard on converting a very long digit string
        # (`sys.int_info.str_digits_check_threshold`). A value that long is still a
        # request this door will not interpret, and it is refused as one rather
        # than raised as a `ValueError` nobody up the stack is catching.
        raise MalformedRequestError from exc


def render(response: Response, *, policy: str) -> bytes:
    """Serialise a response, with the content security policy ADR-0168 §6 requires.

    "The gateway serves every response with a content security policy that permits
    scripts, styles, fonts, images, media and connections from its own origin
    alone, and permits no inline script" — *every* response, which is why the
    policy is applied here rather than by each handler that might forget one.

    Args:
        response: What to send.
        policy: The content security policy value.

    Returns:
        The bytes to write.
    """
    lines = [
        *_status_and_common(response.status, response.reason, response.content_type, policy),
        f"Content-Length: {len(response.body)}",
        f"Connection: {'close' if response.close else 'keep-alive'}",
    ]
    if response.set_cookie is not None:
        lines.append(f"Set-Cookie: {response.set_cookie}")
    return _head(lines) + response.body


def render_stream_head(head: StreamHead, *, policy: str) -> bytes:
    """Serialise the head of a streamed response (ADR-0175 §1).

    The same policy and the same sniffing and caching headers every other response
    carries — ADR-0168 §6 requires them of *every* response, which is why they are
    built here rather than by each handler — with ``Transfer-Encoding: chunked`` in
    place of the ``Content-Length`` a stream cannot state.

    Args:
        head: What is being streamed, and whether the connection survives it.
        policy: The content security policy value.

    Returns:
        The bytes to write before the first chunk.
    """
    return _head(
        [
            *_status_and_common(head.status, head.reason, head.content_type, policy),
            "Transfer-Encoding: chunked",
            f"Connection: {'close' if head.close else 'keep-alive'}",
        ]
    )


def render_chunk(payload: bytes) -> bytes:
    """Frame one piece of a streamed body.

    Args:
        payload: The bytes to send. Must not be empty — a zero-length chunk is
            HTTP's end-of-body marker, and one written mid-stream would end the body
            while the gateway believed it had written a value.

    Returns:
        The framed chunk.

    Raises:
        ValueError: If ``payload`` is empty.
    """
    if not payload:
        msg = "a zero-length chunk is the end of a body, not a value on one"
        raise ValueError(msg)
    return f"{len(payload):x}\r\n".encode("ascii") + payload + b"\r\n"


def render_stream_end() -> bytes:
    """The end of a chunked body: the zero-length chunk and no trailers.

    Returns:
        The bytes that complete the response.
    """
    return b"0\r\n\r\n"


def _status_and_common(status: int, reason: str, content_type: str, policy: str) -> list[str]:
    """The status line and the headers every response carries, streamed or not."""
    return [
        f"{_HTTP_VERSION} {status} {reason}",
        f"Content-Type: {content_type}",
        f"Content-Security-Policy: {policy}",
        "X-Content-Type-Options: nosniff",
        "Cache-Control: no-store",
    ]


def _head(lines: list[str]) -> bytes:
    """Terminate a head's lines and encode them."""
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")
