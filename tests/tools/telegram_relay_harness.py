"""A fake relay on the loopback, behind real TLS, for a relayed Telegram line (ADR-0330 §12:6).

ADR-0330 §12:6: "Relayed mode is tested against a fake relay, never a real one." This is
that relay. **Nothing about the channel is a double**: the listener is a socket, the
certificates are certificates minted here, and the client reaches it through the
production :class:`~ai_assistant.tools.egress.StreamOutboundTransport` anchored on
:class:`~ai_assistant.tools.egress.TrustAnchors` — so a certificate outside the
configured set, or one issued for another host, is refused by the TLS stack the hub
runs, before the request is written. What is scripted is the relay's **answers**: it
serves the three Bot API methods as the private repository's relay does (§4), reading
each request and recording it, and answering it as the case arranged.

**Three certificate authorities' worth of trust, minted once per process.** The
relay's own CA, which a case configures; a leaf for ``localhost`` it issued, which a
healthy relay presents; a leaf it issued for another name, which a misnamed relay
presents (§7:5); and a stranger CA's leaf for ``localhost``, which a relay the hub does
not trust presents (§7:1). Every certificate carries the extensions the standard
library's strict X.509 checks ask of a chain, as the relay's own do (its
``src/relay/certs.py``): a critical ``basicConstraints``, a ``keyUsage``, both key
identifiers, and a ``subjectAltName`` on the leaf.

**It runs on a thread of its own, with its own event loop.** The case's loop is the
client's alone, so nothing the relay does — a handshake, a stall — can be scheduled
behind the call it is answering, and a fixture's loop and a case's need not agree.

**``localhost`` is the relay's host name.** It is a single label, as the box's
``telegram-relay`` is, and it is the one name that resolves to the loopback without a
resolver leaving the machine. The canonicaliser admits it, and refuses the literal
``127.0.0.1`` (ADR-0231 §8), as it would refuse any IP literal for a relay (§3:4).

**Minted with ``cryptography``**, which this project already depends on, for
``answering_origin_harness``' reason.
"""

from __future__ import annotations

import asyncio
import json
import socket
import ssl
import threading
from collections import deque
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Final, Literal, final

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from ai_assistant.core.types import TransportEndpoint

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from ai_assistant.core.protocols import ByteChannel, OutboundTransport

#: The relay's host: one label, resolving to the loopback alone.
RELAY_HOST: Final = "localhost"

#: The name the misnamed relay's leaf is issued for instead.
OTHER_HOST: Final = "other-relay"

#: The relay credential the hub holds: ``<16 hex>_<43 base64url>``, the relay's own
#: shape, with no ``:`` (ADR-0330 §6:2). Its secret half is what every leak case seeks.
RELAY_CREDENTIAL: Final = "0123456789abcdef_Zm9vYmFyLXJlbGF5LXNlY3JldC1wYXJ0LW9mLWNyZWQtMA"
RELAY_SECRET_PART: Final = RELAY_CREDENTIAL.split("_", 1)[1]

#: How long a minted certificate is valid either side of now.
_VALIDITY: Final = timedelta(hours=2)

#: The end of a request's field section (RFC 9112 §2.1).
_END_OF_FIELDS: Final = b"\r\n\r\n"

#: What a relay presents: its own leaf, a leaf for another host, or a stranger's leaf.
Presenting = Literal["own", "other-host", "stranger"]

#: What a scripted answer can be besides octets: hold the connection open in silence,
#: or close it having answered nothing.
Stall = Literal["stall", "close"]


@final
@dataclass(frozen=True, slots=True)
class Minted:
    """The certificates a fake relay and its hub are configured with.

    Attributes:
        ca_pem: The relay's CA certificate, in PEM: what ``relay cert show`` prints.
        stranger_ca_pem: Another CA's certificate, which no hub here configures.
        directory: Where every leaf and key is written, PEM, for the listener.
    """

    ca_pem: str
    stranger_ca_pem: str
    directory: Path

    def configured(self, pem: str | None = None) -> str:
        """One certificate as ``Settings.telegram_relay_certificates`` holds it.

        Args:
            pem: The PEM text, or ``None`` for the relay's CA.

        Returns:
            The base64 of its DER: the PEM body with its armour and line breaks gone.
        """
        text = self.ca_pem if pem is None else pem
        return "".join(line for line in text.splitlines() if not line.startswith("-----"))

    def leaf(self, presenting: Presenting) -> tuple[Path, Path]:
        """The certificate chain and key a relay presenting ``presenting`` serves.

        Args:
            presenting: Which leaf.

        Returns:
            The chain's PEM file (the leaf, then its CA) and the key's.
        """
        return self.directory / f"{presenting}.pem", self.directory / f"{presenting}-key.pem"


def _key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def _pem(certificate: x509.Certificate) -> bytes:
    return certificate.public_bytes(serialization.Encoding.PEM)


def _ca(name: str) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    """A CA, as the relay's ``init_ca`` makes one."""
    key = _key()
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _VALIDITY)
        .not_valid_after(now + _VALIDITY)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    return key, certificate


def _leaf(
    host: str, ca_key: ec.EllipticCurvePrivateKey, ca: x509.Certificate
) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    """A server leaf for ``host``, as the relay's ``issue_leaf`` makes one."""
    key = _key()
    now = datetime.now(UTC)
    ca_ski = ca.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value
    certificate = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)]))
        .issuer_name(ca.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _VALIDITY)
        .not_valid_after(now + _VALIDITY)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(ca_ski), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    return key, certificate


_HELD: list[TemporaryDirectory[str]] = []


@cache
def minted() -> Minted:
    """Mint the relay's CA, a stranger's CA and the three leaves, once per process.

    Returns:
        The certificates, their files under a directory removed at interpreter exit.
    """
    held = TemporaryDirectory(prefix="telegram-relay-")
    _HELD.append(held)
    directory = Path(held.name)
    ca_key, ca = _ca("Fake Relay CA")
    stranger_key, stranger = _ca("Stranger CA")
    for name, (key, leaf), issuer in (
        ("own", _leaf(RELAY_HOST, ca_key, ca), ca),
        ("other-host", _leaf(OTHER_HOST, ca_key, ca), ca),
        ("stranger", _leaf(RELAY_HOST, stranger_key, stranger), stranger),
    ):
        (directory / f"{name}.pem").write_bytes(_pem(leaf) + _pem(issuer))
        (directory / f"{name}-key.pem").write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
    return Minted(
        ca_pem=_pem(ca).decode("ascii"),
        stranger_ca_pem=_pem(stranger).decode("ascii"),
        directory=directory,
    )


def bot_api(payload: object, *, status: int = 200) -> bytes:
    """A Bot API answer: its JSON in an HTTP/1.1 response framed by its length."""
    body = json.dumps(payload).encode("utf-8")
    head = [
        f"HTTP/1.1 {status} {'OK' if status == 200 else 'Refused'}",
        "Content-Type: application/json",
        f"Content-Length: {len(body)}",
        "Connection: close",
        "",
        "",
    ]
    return "\r\n".join(head).encode("ascii") + body


def done(result: object) -> bytes:
    """``{"ok": true, "result": ...}``."""
    return bot_api({"ok": True, "result": result})


def refused(code: int, *, retry_after: int | None = None) -> bytes:
    """``{"ok": false, "error_code": ...}``, with a rate limit's wait where given."""
    payload: dict[str, object] = {"ok": False, "error_code": code, "description": "relay said no"}
    if retry_after is not None:
        payload["parameters"] = {"retry_after": retry_after}
    return bot_api(payload, status=code)


@final
@dataclass(frozen=True, slots=True)
class RelayRequest:
    """One request that reached the relay, decrypted: what it read off the channel.

    Attributes:
        method: The Bot API method the target named.
        credential: The credential in the token's place.
        body: The JSON body, decoded.
    """

    method: str
    credential: str
    body: Mapping[str, object]


@final
@dataclass(slots=True)
class FakeRelay:
    """A relay on the loopback serving the Bot API's three calls, scripted.

    Attributes:
        port: The port it listens on.
        context: The TLS context it serves under, whose leaf :meth:`present` swaps.
        requests: Every request it read, in order.
        answers: The answer per method when nothing is scripted.
        script: Answers for the next requests, whatever their method, taken first:
            octets, ``"stall"`` to hold the connection until the client hangs up, or
            ``"close"`` to hang up having answered nothing.
    """

    port: int
    context: ssl.SSLContext
    requests: list[RelayRequest] = field(default_factory=list)
    answers: dict[str, bytes] = field(default_factory=dict)
    script: deque[bytes | Stall] = field(default_factory=deque)

    @property
    def origin(self) -> str:
        """Its canonical origin, ``https://localhost:<port>``."""
        return f"https://{RELAY_HOST}:{self.port}"

    @property
    def endpoint(self) -> TransportEndpoint:
        """The endpoint its origin pins to."""
        return TransportEndpoint(host=RELAY_HOST, port=self.port, implicit_tls=True)

    def present(self, presenting: Presenting) -> None:
        """Present another leaf to every connection from now on.

        Args:
            presenting: Which.
        """
        chain, key = minted().leaf(presenting)
        self.context.load_cert_chain(chain, key)

    async def serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Read one request, record it, and answer it as scripted."""
        try:
            request = await _read_request(reader)
            if request is None:
                return
            self.requests.append(request)
            answer = self.script.popleft() if self.script else self.answers[request.method]
            if answer == "stall":
                # Until the client hangs up: at its bound, or cancelled.
                await reader.read(1)
                return
            if answer == "close":
                return
            writer.write(answer)
            await writer.drain()
        except OSError, asyncio.IncompleteReadError, ssl.SSLError:
            return
        finally:
            writer.close()
            with suppress(OSError, ssl.SSLError):
                await writer.wait_closed()


async def _read_request(reader: asyncio.StreamReader) -> RelayRequest | None:
    """One HTTP/1.1 ``POST`` with a ``Content-Length`` body, or ``None`` for none."""
    try:
        head = await reader.readuntil(_END_OF_FIELDS)
    except asyncio.IncompleteReadError:
        return None
    lines = head.decode("ascii").split("\r\n")
    target = lines[0].split(" ")[1]
    length = next(
        int(line.split(":", 1)[1]) for line in lines if line.lower().startswith("content-length:")
    )
    body = await reader.readexactly(length)
    _, credential, method = target.split("/")
    return RelayRequest(
        method=method, credential=credential.removeprefix("bot"), body=json.loads(body)
    )


#: How long the relay's thread is given to start or to stop.
_THREAD_WAIT: Final = 10.0


@contextmanager
def fake_relay(
    *,
    presenting: Presenting = "own",
    tls_ceiling: ssl.TLSVersion | None = None,
) -> Iterator[FakeRelay]:
    """Run a fake relay on the loopback, on a thread of its own, for the block.

    Args:
        presenting: The leaf it presents.
        tls_ceiling: The highest TLS version it will speak, or ``None`` for any.

    Yields:
        The relay, answering every method as a healthy relay would until scripted.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    if tls_ceiling is not None:
        context.maximum_version = tls_ceiling
    chain, key = minted().leaf(presenting)
    context.load_cert_chain(chain, key)
    family, kind, proto, _, address = socket.getaddrinfo(RELAY_HOST, 0, type=socket.SOCK_STREAM)[0]
    listening = socket.socket(family, kind, proto)
    listening.setblocking(False)
    listening.bind(address)
    relay = FakeRelay(port=int(listening.getsockname()[1]), context=context)
    relay.answers.update(
        {
            "sendMessage": done({"message_id": 1, "chat": {"id": 1, "type": "private"}}),
            "sendChatAction": done(True),
            "getUpdates": done([]),
            # ADR-0361 §4:12: the card's edit and a callback's answer, which a relay
            # passes on as it does the line's other calls (ADR-0330 §4:16).
            "editMessageText": done({"message_id": 1, "chat": {"id": 1, "type": "private"}}),
            "answerCallbackQuery": done(True),
        }
    )
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, name="fake-relay", daemon=True)
    thread.start()
    server = asyncio.run_coroutine_threadsafe(
        asyncio.start_server(relay.serve, sock=listening, ssl=context), loop
    ).result(_THREAD_WAIT)

    async def stop() -> None:
        server.close()
        server.close_clients()
        await server.wait_closed()

    try:
        yield relay
    finally:
        asyncio.run_coroutine_threadsafe(stop(), loop).result(_THREAD_WAIT)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(_THREAD_WAIT)
        loop.close()


def closed_port() -> int:
    """A loopback port nothing listens on, for a relay that cannot be reached."""
    family, kind, proto, _, address = socket.getaddrinfo(RELAY_HOST, 0, type=socket.SOCK_STREAM)[0]
    with socket.socket(family, kind, proto) as probe:
        probe.bind(address)
        return int(probe.getsockname()[1])


@final
class RecordingTransport:
    """An outbound transport that records each endpoint, then opens it through another.

    Wraps the production transport so a case can read every origin the client reached
    for — the relay's, and never Telegram's — without displacing the TLS it verifies.
    """

    def __init__(self, inner: OutboundTransport) -> None:
        """Record in front of ``inner``."""
        self._inner = inner
        self.endpoints: list[TransportEndpoint] = []

    async def open_channel(self, endpoint: TransportEndpoint) -> ByteChannel:
        """Record ``endpoint``, then open it through the wrapped transport."""
        self.endpoints.append(endpoint)
        return await self._inner.open_channel(endpoint)

    def origins(self) -> tuple[str, ...]:
        """Every endpoint reached for, as a canonical origin."""
        return tuple(f"https://{one.host}:{one.port}" for one in self.endpoints)


@final
class _SilentChannel:
    """A secure channel that records what is written and never answers."""

    def __init__(self) -> None:
        self.written = bytearray()

    @property
    def is_secure(self) -> bool:
        return True

    async def read_line(self) -> bytes:  # pragma: no cover — the exchange reads by `read`
        await asyncio.Event().wait()
        return b""

    async def read(self, limit: int, /) -> bytes:
        del limit
        await asyncio.Event().wait()
        return b""  # pragma: no cover — the wait never ends

    async def write(self, data: bytes, /) -> None:
        self.written += data

    async def start_tls(self) -> None:
        """Nothing to upgrade."""

    async def close(self) -> None:
        """Release it."""


@final
class SilentRelayTransport:
    """A relay's endpoint that takes a request and never answers, with no handshake.

    **For the one arrangement whose outcome turns on a deadline.** A send cut off by
    its bound is *unknown* only once its request was written, and over real TLS the
    write waits on a handshake whose duration a loaded machine decides. Here the channel
    is open the moment it is asked for, so the request is written at once and the bound
    always falls after it. Certificate verification is the real relay's to show, and is.
    """

    def __init__(self) -> None:
        """Start with nothing opened."""
        self.endpoints: list[TransportEndpoint] = []
        self.channels: list[_SilentChannel] = []

    async def open_channel(self, endpoint: TransportEndpoint) -> ByteChannel:
        """Open a silent channel to ``endpoint``."""
        self.endpoints.append(endpoint)
        channel = _SilentChannel()
        self.channels.append(channel)
        return channel

    def origins(self) -> tuple[str, ...]:
        """Every endpoint reached for, as a canonical origin."""
        return tuple(f"https://{one.host}:{one.port}" for one in self.endpoints)

    def requests(self) -> tuple[RelayRequest, ...]:
        """Every request written, as the relay would have read it."""
        read: list[RelayRequest] = []
        for channel in self.channels:
            head, _, body = bytes(channel.written).partition(_END_OF_FIELDS)
            if not body:
                continue
            target = head.split(b"\r\n", 1)[0].split(b" ")[1].decode("ascii")
            _, credential, method = target.split("/")
            read.append(
                RelayRequest(
                    method=method,
                    credential=credential.removeprefix("bot"),
                    body=json.loads(body),
                )
            )
        return tuple(read)
