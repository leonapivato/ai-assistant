"""A real origin that answers, and then stalls past the handshake (#2218).

**The instrument milestone 31 shipped without.** ADR-0241 §12's **Arm 4** is a
conversation whose first turn searched and answered and whose second turn's search
expires, and it has never been driven live: on production because no first search
succeeds (#2212), and on a scratch hub because the only real origin in the tree
answers nothing. :mod:`stalled_origin_harness` says so itself — "completing the
handshake and stalling after it would need a trust anchor the client's default
context would accept, and would exercise the response read, which is a stage no
shield ever covered". This module is that trust anchor and that stage.

**Nothing here is a double.** The listener is a socket, the certificate is a
certificate, and the client under test is the production
:class:`~ai_assistant.tools.egress.StreamOutboundTransport` reaching it over TLS it
actually verified. What varies is the **script**: how many requests are answered
before the origin stops, and whether stopping means holding the connection open in
silence or closing it.

**The stall is after the handshake, which is the whole point of the certificate.**
:class:`~stalled_origin_harness.StalledOrigin` stalls a client inside its
``ClientHello``, which bounds the *open*. An origin that completes TLS, reads the
request and then says nothing bounds the *response read* instead — the stage that
sits behind ``HttpsExchange._response`` and that no arm in the tree reaches. ADR-0241
§1 delivers the deadline as a cancellation, and this is where a second turn's search
spends it.

**How the production transport comes to trust it, with no change under ``src/``.**
:func:`~ai_assistant.tools.egress._tls_context` builds
``ssl.create_default_context()`` and states ``check_hostname`` and ``verify_mode``
on it; it takes no context, no ``cafile`` and no override, and ADR-0191 §3 leaves
no accessor that would return one — so there is no seam to inject a trust anchor
through, and adding one would be a decision rather than a fixture. What is left is
OpenSSL's own: ``create_default_context`` loads the default verify paths, and
``X509_STORE_set_default_paths`` reads ``SSL_CERT_FILE`` from the environment **at
the moment the context is built**. So the anchor is set on the process before the
first open, never on the seam. That is a name in OpenSSL and not a name in this
tree: no ``Settings`` field is read, none is added, and the production path is
byte-for-byte the one a deployment runs.

The ordering is load-bearing and is where an in-process case can go wrong quietly:
:func:`answering_origin` sets the variable itself, before it yields, and a case that
built a context earlier in the same process would be verifying against a store that
does not hold this certificate.

**The certificate is minted with ``cryptography``, which this project already
depends on** (``pyproject.toml``, ``cryptography>=46``, declared for ADR-0123's age
recipient). Shelling out to ``openssl`` would add a binary the test corpus does not
otherwise need and a subprocess to a case measuring a wall clock; the standard
library mints no certificate at all.

## Runbook — driving Arm 4 against a scratch hub

The in-process cases in :mod:`test_answering_origin` need none of this. It is for a
QA agent standing an origin in front of a live hub, so that the two-turn arm can be
driven in minutes rather than rebuilt from zero (#2206).

1. Start the origin, from the repository root, on a port of your choosing::

       uv run python tests/tools/answering_origin_harness.py --port 8443 --answer 1 --then stall

   It prints the endpoint and the certificate's path and then serves until it is
   interrupted. ``--answer 1`` is Arm 4's script: turn one's search is answered,
   turn two's stalls. ``--then close`` hangs up instead of holding, for the
   neighbouring fault.

2. Point the hub at it, in the hub process's own environment::

       ASSISTANT_WEB_SEARCH_ORIGIN=https://localhost:8443
       SSL_CERT_FILE=<the path the command above printed>
       ASSISTANT_SEARCH_CALL_DEADLINE_SECONDS=5

   ``SSL_CERT_FILE`` has to be set **before the hub starts**: it is read when the
   TLS context is built, and a hub already running has built one.

3. Mint the connection the searcher reads its credential from, against that origin,
   with ``assistant connect`` — the origin a connected account carries is what the
   binding names, and it has to be the same string the hub is configured with.

4. Drive two turns. The first search is answered from ``--results``; the second is
   held open until the deadline expires, which is Arm 4's fault.

**The origin listens on loopback and reaches nothing.** ``localhost`` is the one
name that resolves to the loopback interface without a resolver leaving the machine,
and it is a name rather than a literal because the searcher refuses a literal
(ADR-0231 §8: "an HTTPS host whose rightmost label is a number is an IP literal and
is refused"). Nothing here dials out, and the certificate it mints is trusted by
exactly the one process that was told about it.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
import ssl
import sys
from contextlib import asynccontextmanager, contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any, Final, Literal, final

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from stalled_origin_harness import HOST
from web_search_harness import DATE_FIELD, body, response, result

from ai_assistant.core.types import TransportEndpoint

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping, Sequence

#: OpenSSL's own name for the file its default verify paths are loaded from. It is
#: not a name in this tree and no ``Settings`` field corresponds to it, which is
#: what lets a fixture arrange trust without a code path being added for one.
_TRUST_VARIABLE: Final = "SSL_CERT_FILE"


#: The provider's request path (``web_search._PROVIDER_PATH``). This origin serves
#: whatever target it is asked for and **records** it, rather than routing on it: a
#: fixture that answered only this path would turn a searcher asking for the wrong
#: one into a transport failure, which is the least legible way to fail. The cases
#: assert the recorded target against this instead.
SEARCH_PATH: Final = "/res/v1/web/search"

#: The end of a request's field section (RFC 9112 §2.1), which is where this origin
#: stops reading. It sends no body and expects none.
_END_OF_FIELDS: Final = b"\r\n\r\n"

#: How many space-separated fields a request line carries (RFC 9112 §3): the
#: method, the request target and the version. This origin reads the second and
#: refuses a line that is not three, rather than indexing into whatever arrived.
_REQUEST_LINE_FIELDS: Final = 3

#: How long the origin waits for a client's request before treating the connection
#: as one that will not speak. Only reached by a client that opened and said
#: nothing, which no case here arranges.
_REQUEST_WAIT: Final = timedelta(seconds=30)

#: How long the minted certificate is valid either side of now. Short, because it
#: exists for the life of one test session or one QA run, and a fixture certificate
#: with a long life is one that can outlive the directory it was written to.
_VALIDITY: Final = timedelta(hours=1)

#: The clock skew the certificate tolerates. A certificate minted and verified in
#: the same second by the same machine needs none in principle; a few minutes of
#: backdating costs nothing and removes an unreproducible failure.
_BACKDATE: Final = timedelta(minutes=5)

#: What the origin answers with where a case names no results of its own. One
#: result, in :func:`web_search_harness.result`'s default shape, so that a case
#: asserting on what was minted asserts against the same spans every other search
#: case does.
DEFAULT_RESULTS: Final[tuple[Mapping[str, Any], ...]] = (result(),)

#: What the origin does once its script has run out.
After = Literal["stall", "close"]


def _mint(directory: Path) -> tuple[Path, Path]:
    """Mint a self-signed certificate for :data:`HOST` and write it beside its key.

    The certificate is its own issuer, so the file handed to ``SSL_CERT_FILE`` is
    both the leaf the origin presents and the anchor the client verifies it
    against — one file rather than a chain, which is what makes the runbook's
    second step a single path.

    It carries ``DNS:localhost`` as a subject alternative name because that is what
    verification reads: ``_tls_context`` states ``check_hostname = True``, and
    ``open_channel`` passes ``endpoint.host`` as the ``server_hostname``, so a
    certificate naming the host only in its subject would be refused by every
    client written this century.

    Args:
        directory: Where to write the two files.

    Returns:
        The certificate's path and the private key's path, in that order.
    """
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, HOST)])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _BACKDATE)
        .not_valid_after(now + _VALIDITY)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(HOST)]), critical=False)
        # ``ca=True`` because this certificate is the trust anchor as well as the
        # leaf: OpenSSL will not build a chain terminating in a certificate whose
        # basic constraints say it is not a CA, so a self-signed leaf without it
        # verifies nowhere.
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    certificate_path = directory / "origin.pem"
    key_path = directory / "origin.key"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    # The key is a secret only in form — it is minted for one process and thrown
    # away with the directory — but a world-readable private key beside a
    # certificate is a shape worth not writing even in a fixture.
    key_path.chmod(0o600)
    return certificate_path, key_path


@final
@dataclass(slots=True)
class AnsweringOrigin:
    """A listening HTTPS origin that follows a script, and the ways to name it.

    Attributes:
        endpoint: What ``open_channel`` is handed, under implicit TLS.
        origin: The same place as the origin string a connected search account is
            configured with, for an arm that drives the whole servicing path.
        certificate: The anchor a client has to trust to reach it, which is what
            ``SSL_CERT_FILE`` names.
        connections: How many connections were accepted. Counted rather than
            inferred from ``requests``, so that the two together say what a pooled
            transport would look like: ADR-0191 §3 opens a channel per call, and an
            implementation that pooled would show two requests over one connection.
        requests: The request targets read, in order, so a case can say the
            searcher asked for the provider's path and asked once per call.
        answered: How many of them were answered from the script.
        exhausted: Set the first time a request arrives past the script, so a case
            can wait for the arrangement to have actually reached the stall (or the
            hang-up) rather than asserting against a request still in flight.
        released: Set by :meth:`release`, and what every held connection is waiting
            on. Read rather than set by a case; :meth:`release` is the way to set it.
    """

    endpoint: TransportEndpoint
    origin: str
    certificate: Path
    connections: int = 0
    requests: list[str] = field(default_factory=list)
    answered: int = 0
    exhausted: asyncio.Event = field(default_factory=asyncio.Event)
    released: asyncio.Event = field(default_factory=asyncio.Event)

    def release(self) -> None:
        """Let every held connection go, closing it, without stopping the origin.

        **This is the only thing that ends a stall from outside, and a cancellation
        is not.** A client suspended in its response read is waiting on octets this
        origin has decided not to send; cancelling the client's own task asks the
        client to stop waiting, which an implementation that defers or absorbs
        cancellations is free to decline. Closing the connection is not a request —
        the read ends because there is nothing left to read from.

        That is what makes it the escape hatch a case's watchdog needs: a bound that
        can only cancel is a bound that a cancellation-deferring regression outlives,
        and the run hangs instead of failing. It is idempotent, and the context
        manager calls it on the way out.
        """
        self.released.set()


def _answer(results: Sequence[Mapping[str, Any]], *, date: str | None) -> bytes:
    """The octets one answered request gets back.

    Built from :func:`web_search_harness.body` and :func:`web_search_harness.response`
    rather than from a second spelling of the provider's shape, so that what this
    origin serves and what every scripted far end in ``test_web_search`` serves
    cannot drift apart.

    Args:
        results: The result objects to carry.
        date: The ``Date`` field's value, or ``None`` for a response declaring no
            instant — which ADR-0231 §10 reads as ``UNATTESTED``.

    Returns:
        The response's octets.
    """
    return response(date=date, payload=body(*results))


async def _read_request(reader: asyncio.StreamReader) -> str | None:
    """Read one request head and return its target.

    Args:
        reader: The connection's read half.

    Returns:
        The request target from the request line, or ``None`` where the client sent
        nothing this origin could read as a request — a connection opened and
        dropped, a request line this origin cannot read, a head past the stream's
        own limit (``asyncio``'s 64 KiB, which arrives as ``LimitOverrunError`` and
        is what bounds the buffering here), or a client that said nothing for
        :data:`_REQUEST_WAIT`.
    """
    try:
        async with asyncio.timeout(_REQUEST_WAIT.total_seconds()):
            head = await reader.readuntil(_END_OF_FIELDS)
    except TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, OSError:
        return None
    line = head.split(b"\r\n", 1)[0].decode("latin-1")
    fields = line.split(" ")
    if len(fields) != _REQUEST_LINE_FIELDS:
        return None
    return fields[1]


@asynccontextmanager
async def answering_origin(
    *,
    answer: int = 1,
    then: After = "stall",
    results: Sequence[Mapping[str, Any]] = DEFAULT_RESULTS,
    date: str | None = DATE_FIELD,
    port: int = 0,
) -> AsyncIterator[AnsweringOrigin]:
    """Bind a scripted HTTPS origin on the loopback interface for the life of the block.

    The trust anchor is installed on the process's environment **before** the block
    yields, because ``ssl.create_default_context`` reads ``SSL_CERT_FILE`` when it
    builds a context and every open under test builds its own. The previous value
    is restored on the way out, so a case that ran before this one is not left
    verifying against a directory this block deleted.

    Args:
        answer: How many requests are answered from ``results`` before the script
            runs out. ``1`` is ADR-0241 §12 Arm 4's shape; ``0`` answers nothing.
        then: What a request past the script gets — ``"stall"`` holds the
            connection open and writes nothing, ``"close"`` hangs up without
            answering.
        results: The result objects every answered request carries.
        date: The ``Date`` field's value on every answered response, or ``None``
            for a response declaring no instant.
        port: The port to bind. ``0`` — every in-process case — lets the operating
            system choose, so that concurrent test sessions cannot collide. A
            standalone run names one, because a hub is configured with the origin
            string before the origin exists.

    Yields:
        The origin, already listening and already trusted by this process. Every
        connection it is still holding is released when the block ends, and a case
        that needs one released earlier calls :meth:`AnsweringOrigin.release`.
    """
    origin: AnsweringOrigin | None = None
    served = _answer(results, date=date)

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Read one request, then follow the script.

        Args:
            reader: The read half, read exactly as far as the end of the request's
                field section.
            writer: The write half, closed when the connection is released so that
                ``Server.wait_closed`` has a handler to wait on that finishes.
        """
        assert origin is not None, "the handler cannot run before the yield below"
        origin.connections += 1
        target = await _read_request(reader)
        if target is None:
            with suppress(OSError):
                writer.close()
            return
        origin.requests.append(target)
        try:
            if origin.answered < answer:
                origin.answered += 1
                writer.write(served)
                # ADR-0231 §5's channel per call, and the framing the seam relies
                # on where a response declared no length: the connection carrying
                # an answer is finished with when the answer is written.
                with suppress(OSError):
                    await writer.drain()
                return
            origin.exhausted.set()
            if then == "stall":
                # **Nothing is written and the connection is not closed.** The
                # handshake is done and the request is read, so the client is
                # suspended in ``HttpsExchange._response`` — which is the stage
                # ADR-0241 §1's cancellation has to reach and the one
                # ``StalledOrigin`` cannot arrange.
                #
                # It ends when :meth:`AnsweringOrigin.release` is called — by a
                # case's watchdog, or by this block on its way out — and the
                # ``finally`` below then closes the connection, which is what ends
                # the client's read whether or not the client can be cancelled.
                await origin.released.wait()
        finally:
            with suppress(OSError):
                writer.close()
            with suppress(OSError):
                writer.transport.abort()

    with TemporaryDirectory(prefix="answering-origin-") as directory:
        certificate, key = _mint(Path(directory))
        server, bound = await _listen(serve, certificate=certificate, key=key, port=port)
        origin = AnsweringOrigin(
            endpoint=TransportEndpoint(host=HOST, port=bound, implicit_tls=True),
            origin=f"https://{HOST}:{bound}",
            certificate=certificate,
        )
        try:
            with _trusted(certificate):
                yield origin
        finally:
            # Released before the server is closed: ``Server.wait_closed`` waits
            # for every handler task, and a handler still holding a connection would
            # hold the teardown for as long as this arrangement holds a client.
            origin.release()
            server.close()
            await server.wait_closed()


async def _listen(
    handler: Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]],
    *,
    certificate: Path,
    key: Path,
    port: int,
) -> tuple[asyncio.Server, int]:
    """Bind one TLS listener on the loopback interface and start serving it.

    **Bound to the first address** :data:`HOST` **resolves to, and to that one
    only**, for ``stalled_origin_harness``' reason: ``localhost`` can carry both an
    IPv6 and an IPv4 address, and ``asyncio.start_server`` given a name and port 0
    binds one socket per address with a *different* ephemeral port on each — so
    there would be no single port to name. Binding the first address ourselves gives
    one port, and it is the one ``create_connection`` reaches first, since it walks
    the same ``getaddrinfo`` order this did.

    Args:
        handler: What each accepted connection is handed to.
        certificate: The certificate to present.
        key: Its private key.
        port: The port to bind, or ``0`` to let the operating system choose.

    Returns:
        The server and the port it actually bound.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key)
    family, kind, proto, _, address = socket.getaddrinfo(HOST, port, type=socket.SOCK_STREAM)[0]
    listening = socket.socket(family, kind, proto)
    listening.setblocking(False)
    listening.bind(address)
    bound = int(listening.getsockname()[1])
    return await asyncio.start_server(handler, sock=listening, ssl=context), bound


@contextmanager
def _trusted(certificate: Path) -> Iterator[None]:
    """Make ``certificate`` this process's trust anchor for the life of the block.

    **Installed by the fixture rather than by a case, and restored rather than
    deleted.** This is the one thing a caller cannot be trusted to do late: a TLS
    context built before the variable is set does not hold the anchor, and the
    failure surfaces as a certificate-verify error several frames from its cause.
    Restoring the previous value rather than unsetting it is what keeps this
    composable with an outer arrangement — and with a developer's own
    ``SSL_CERT_FILE``.

    ``os.environ`` is written directly because the name is **OpenSSL's** and not one
    ``core.config.Settings`` reads: there is no configuration surface here to go
    through, which is the whole point of arranging trust this way rather than adding
    a field for it.

    Args:
        certificate: The PEM to name.

    Yields:
        Nothing; the block runs with the anchor installed.
    """
    previous = os.environ.get(_TRUST_VARIABLE)
    os.environ[_TRUST_VARIABLE] = str(certificate)
    try:
        yield
    finally:
        if previous is None:
            del os.environ[_TRUST_VARIABLE]
        else:
            os.environ[_TRUST_VARIABLE] = previous


def _parser() -> argparse.ArgumentParser:
    """The standalone runner's arguments.

    Returns:
        The parser, for :func:`main` and for a case that reads its defaults.
    """
    parser = argparse.ArgumentParser(
        prog="answering_origin_harness",
        description=(
            "A loopback HTTPS origin that answers a scripted number of web-search "
            "requests and then stalls, for driving ADR-0241 §12 Arm 4 against a hub."
        ),
    )
    parser.add_argument("--port", type=int, default=8443, help="the port to listen on")
    parser.add_argument(
        "--answer",
        type=int,
        default=1,
        help="how many requests are answered before the script ends",
    )
    parser.add_argument(
        "--then",
        choices=("stall", "close"),
        default="stall",
        help="what a request past the script gets",
    )
    parser.add_argument(
        "--results",
        type=int,
        default=len(DEFAULT_RESULTS),
        help="how many result objects each answered response carries",
    )
    return parser


async def _serve_forever(arguments: argparse.Namespace) -> None:
    """Run one scripted origin on the named port until it is interrupted.

    Args:
        arguments: What :func:`_parser` parsed.
    """
    served = [
        result(
            title=f"Result {index + 1}",
            url=f"https://example.invalid/{index + 1}",
            description="A result this origin was told to serve.",
        )
        for index in range(arguments.results)
    ]
    async with answering_origin(
        answer=arguments.answer, then=arguments.then, results=served, port=arguments.port
    ) as origin:
        # A QA run reads these three lines and configures the hub from them, so they
        # are flushed rather than left in a buffer this process never returns from:
        # the wait below is endless, and an operator watching a pipe would otherwise
        # see nothing at all.
        for line in (
            f"ASSISTANT_WEB_SEARCH_ORIGIN={origin.origin}",
            f"{_TRUST_VARIABLE}={origin.certificate}",
            f"script: answer {arguments.answer} request(s), then {arguments.then}",
        ):
            print(line, flush=True)
        # **The certificate lives only as long as this process.** It is written to a
        # temporary directory this block deletes on the way out, so the hub has to be
        # started after these lines are printed and stopped before this is.
        await asyncio.Event().wait()


def main(argv: Sequence[str] | None = None) -> int:
    """Run the origin standalone, for a QA run in front of a live hub.

    Args:
        argv: The command line, or ``None`` for ``sys.argv``.

    Returns:
        The exit status.
    """
    with suppress(KeyboardInterrupt):
        asyncio.run(_serve_forever(_parser().parse_args(argv)))
    return 0


if __name__ == "__main__":  # pragma: no cover — the standalone runbook entry point
    sys.exit(main())
