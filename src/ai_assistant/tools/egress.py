"""The `tools/` egress seam: named, approved, undesignated, transmitting nothing.

This is the seam ADR-0017 §2 anticipates and ADR-0147 §3 names:
``ai_assistant.tools.egress`` — **one module, not a package**, holding outbound
transport and nothing else. `tools/` also owns definitions, the registry and the
invocation path, and none of those has any business holding a network client;
that is why the seam is a module the boundary can be drawn *around* rather than a
package the boundary would follow wherever the code grew. Naming it is what issue
#66 asked for since the architecture review of PR #64 — a name "precise enough for
an import-linter contract to pin the module" — and the contract that pins it is
``network transports are confined to the tools egress seam`` in ``pyproject.toml``.

**Nothing here authorises a byte to leave this device.** ADR-0147 §3 says so in a
marked clause: naming the seam is not designating it, that ADR designates nothing
and attests no condition of ADR-0017 §3, and all fourteen of §3's conditions stand
exactly as written and undischarged. No lane may cite ADR-0147 — or the existence
of this module — toward any of them. The seam is **approved and undesignated**, and
an approved boundary transmits nothing. It becomes designated, and only then
transmits, when every one of those conditions holds in code *and* a later ADR names
which, attests how, and records the transition.

**So what is this module, if it may not transmit?** It is the machinery ADR-0017
§3's conditions 5, 8 and 12 are stated *about*, written so that a designating ADR
has code to attest against rather than a plan. ADR-0148 §13 scopes transport
pinning out of itself in terms — "what pins the endpoint to the connected service,
and what a redirect may do, wants an HTTP client in hand" — and issue #83's own
third bullet asks "whether the client is constructed centrally at the seam so the
policy cannot be bypassed per integration. If each integration builds its own
client, this is unenforceable by construction." That question is answerable only by
a client existing here, and this is it.

**And it transmits nothing, because nothing in production constructs it.**
:class:`SmtpEgressTransport` appears in no composition root, in no registry, and in
no callable any registered tool can reach: :class:`~ai_assistant.tools.send_email.
SendEmail` still raises :class:`~ai_assistant.tools.send_email.
UndesignatedSeamError` and is still absent from
:func:`~ai_assistant.tools.builtin.build_default_registry`. The one function in
this module that opens a socket, :func:`open_smtp_channel`, is reached only through
a constructor argument that no production caller supplies because no production
caller exists. ``tests/tools/test_egress_seam.py`` holds the module to that — it
used to pin the seam's syntax tree to a single node, and it now pins the properties
that emptiness was standing in for: no production construction site, no reachable
callable, and exactly one place a connection is opened.

**Why the pin is what it is, for SMTP, stated honestly.** #83 is written about an
HTTP client — "a configurable API base URL, or … a cross-host redirect" — and SMTP
has neither a base URL nor a redirect. What it has, and what this transport
therefore pins, is:

- **The endpoint.** :attr:`~ai_assistant.core.types.EgressBinding.
  transport_endpoint` is compared against the endpoint the tool's registration
  configures, and the connection is opened to that host and port and to no other.
  ADR-0148 §6 binds the endpoint and states in a marked clause that it does not
  pin it; this is the pin, and it is the half #83's last bullet asks for.
- **No MX lookup, and therefore no DNS indirection over the recipient's domain.**
  A mail submission client resolving a recipient's MX record would let a
  destination the user approved select the host the credential is presented to,
  which is #83's failure with the attacker on the other side of a DNS answer. This
  transport connects to the pinned submission endpoint and lets the far end route.
- **No cleartext fallback and no downgrade.** ``smtp+starttls`` refuses to proceed
  where the greeting does not advertise ``STARTTLS``, rather than continuing in
  the clear; the credential is presented only over a channel that has completed a
  verified TLS handshake, and :meth:`ByteChannel.is_secure` is what that is read
  from rather than an assumption about the order commands were written in.
- **The two forward-path replies, refused rather than followed.** RFC 5321 §3.4's
  ``251`` and ``551`` carry a forward-path naming a *different* mailbox at a
  *different* host, and following one would deliver to a recipient no ruling
  covered. They are SMTP's only in-protocol analogue of a redirect, and this
  transport treats both as refusals of the whole call.

**What it does not pin, said rather than glossed.** TLS verification is the
platform trust store's — a certificate authority that mis-issues for the pinned
host defeats it, and no certificate pinning is attempted here. And the transport
cannot tell whether the *account* whose credential it presents is the account the
identity names; ADR-0148 §6 already states that residue ("a party that writes
account B's credential directly into the keyring under a slot recorded as account
A defeats the check") and nothing here narrows it.

Two clauses of ADR-0147 §3 govern what may be written here, and they reach
different distances:

- **The rule.** No module under ``ai_assistant.tools`` other than this one opens a
  network connection or launches a subprocess, by any route: a client library, an
  HTTP or socket API, a standard-library module, or a wrapper around any of them.
  That binds an author and a reviewer; it is not a claim about what a check can see.
- **The check.** The import-linter contract forbids an *enumerated* set of modules
  to every `tools/` module but this one. ADR-0017 §4 is why the two are stated
  separately rather than collapsed: "an import contract is a net, not a proof. It
  matches module names, so it cannot see a subsystem reaching the network through
  ``urllib``, a raw socket, a library added after the contract was written, or an
  internal wrapper." The enumeration names ``urllib`` and the raw socket module, so
  the first two of those examples are inside the net; what stays outside is a
  dependency nobody added to the list. A clause claiming the contract pinned the
  *universal* rule would be claiming exactly the proof §4 denies.

When transport for a second protocol eventually lands here, MCP protocol handling —
the JSON-RPC message shapes, discovery, the mapping from a declaration to a
``ToolDefinition`` and from a result to a ``ToolResult`` — stays **outside** this
module and holds no transport of its own (ADR-0147 §3). It receives a connected
channel from the seam and never constructs one. A module holding both is a module
whose egress boundary extends wherever the protocol code grows, which is the
property #66 asks a contract to be able to pin.
"""

from __future__ import annotations

import asyncio
import base64
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.policy import SMTP as SMTP_POLICY
from typing import TYPE_CHECKING, Final, Protocol, final

import structlog

from ai_assistant.core.errors import ConnectionStoreError, ToolError
from ai_assistant.core.types import DestinationProtocol, ProvisioningState
from ai_assistant.tools.destinations import DestinationCanonicalisationError, canonicalise
from ai_assistant.tools.destinations import DestinationProtocol as SeamProtocol

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from ai_assistant.core.protocols import Secrets
    from ai_assistant.core.types import EgressBinding, SecretName
    from ai_assistant.tools.connection_store import ConnectionEntry, StoredEntry
    from ai_assistant.tools.egress_binder import ConnectionRecords, EgressRegistration

_log = structlog.get_logger(__name__)

#: The scheme naming a submission endpoint reached over TLS from the first byte.
IMPLICIT_TLS_SCHEME: Final = "smtps"

#: The scheme naming a submission endpoint upgraded by ``STARTTLS`` (RFC 3207).
STARTTLS_SCHEME: Final = "smtp+starttls"

#: Default ports, per scheme: RFC 8314 §3.3's implicit-TLS submission port and RFC
#: 6409's submission port. A binding may state a port explicitly; where it does
#: not, these are what is connected to, and neither is guessed from the other.
_DEFAULT_PORTS: Final[dict[str, int]] = {IMPLICIT_TLS_SCHEME: 465, STARTTLS_SCHEME: 587}

#: How many octets of a reply line this transport will read before refusing. A
#: server that never sends a line terminator would otherwise buy unbounded memory
#: from a client holding a credential; RFC 5321 §4.5.3.1.5 caps a reply line at
#: 512, and this leaves room for a non-conforming but honest server.
_MAX_REPLY_LINE_OCTETS: Final = 4096

#: How many lines of one reply this transport will hold. RFC 5321 places no bound
#: on continuation lines, so this one is ours: the largest real ``EHLO`` responses
#: run to a couple of dozen extensions, and a far end needing more than this is not
#: a submission service. See :meth:`_SmtpSession._reply` for why a per-line bound
#: does not imply this one and why neither is a deadline.
_MAX_REPLY_LINES: Final = 64

#: RFC 5321 §3.4's two forward-path replies. Both name a mailbox at another host,
#: and both are refused rather than followed — SMTP's only in-protocol redirect.
_FORWARD_PATH_REPLIES: Final = frozenset({251, 551})

#: The highest TCP port number, which is where an endpoint's port has to sit.
_MAX_PORT: Final = 65535

#: The reply codes RFC 5321 and RFC 4954 define for the steps this seam takes.
#: Named rather than written inline so a reader can see that every branch below
#: turns on a code the protocol assigns, not on a number somebody remembered.
_READY: Final = 220
"""RFC 5321 §4.2.1: the service is ready, on the greeting and after ``STARTTLS``."""

_COMPLETED: Final = 250
"""RFC 5321 §4.2.1: the requested action was taken."""

_AUTHENTICATED: Final = 235
"""RFC 4954 §6: authentication succeeded."""

_START_MAIL_INPUT: Final = 354
"""RFC 5321 §4.2.1: send the message, ending with ``CRLF.CRLF``."""

#: RFC 5321 §4.2's reply prefix: three digits and one separator, ``-`` on a line
#: another follows and a space on the last. A line shorter than that is not one.
_REPLY_PREFIX: Final = 4


class EgressTransportError(ToolError):
    """A transmission through the seam did not happen, and definitely did not.

    Every subclass below is raised **before any byte of the payload reached the
    wire**, which is what lets a caller treat it as a refusal rather than as an
    outcome: ADR-0029 §3's taxonomy would otherwise have to report the call
    ``INDETERMINATE``. The one case where that is not knowable has its own type,
    :class:`IndeterminateTransmissionError`, which is deliberately **not** a
    subclass of this one.

    Raised rather than returned, for :class:`~ai_assistant.tools.send_email.
    UndesignatedSeamError`'s reason: a bound call that cannot be performed as
    bound is not a tool failing, and ``ToolFailureKind`` carries a ``retryable``
    an executor would otherwise act on.

    **No message any of these raises renders a payload span, a credential, an
    account identity, a recipient address or a credential slot** (ADR-0152 §11's
    discipline, applied to the neighbouring surface). It may name the tool id, the
    connection reference, an endpoint host, an SMTP reply code and a count.
    """


class TransportPinError(EgressTransportError):
    """The connection would not have been to the service the ruling named (#83).

    Four grounds, deliberately one type: the binding's endpoint is not the one the
    registration configures; the endpoint is not a form this seam will pin at all;
    the far end declined the TLS the scheme requires; or it answered with RFC 5321
    §3.4's forward path, which this transport refuses rather than follows. All
    four end the same way and the credential travels in none of them.
    """


class BoundCallChangedError(EgressTransportError):
    """Something the ruling fixed does not hold at the moment of transmission.

    ADR-0148 §6's four pre-transmission refusals and its post-read discard clause,
    plus §4's third clause read at the seam: the reference is not connectable, the
    identity currently recorded for it is not the bound one, the record moved
    across the credential read, or the message would reach a recipient the bound
    canonical destination set does not carry — or carry a span the payload
    description does not cover.
    """


class IndeterminateTransmissionError(ToolError):
    """The message may or may not have been accepted, and this seam cannot say.

    Raised in exactly one window: the message body and its terminating ``.`` have
    been written, and the reply that would say whether the server accepted it
    could not be read. ADR-0017 §3 names the distinction this exists for —
    "otherwise a timeout is indistinguishable from a successful disclosure" — and
    ADR-0148 §9 maps it onto the step's ``INDETERMINATE`` outcome, which ADR-0014
    §4's recovery scan is the reconciliation path for.

    **Not** an :class:`EgressTransportError`, and the split is the whole point:
    every member of that hierarchy is a refusal that transmitted nothing, and
    collapsing this into it would let a caller treat an unknown disclosure as one
    that did not happen.
    """


@final
@dataclass(frozen=True, slots=True)
class SmtpEndpoint:
    """A submission endpoint this seam will pin a connection to.

    Attributes:
        host: The host the connection is opened to and the name the certificate
            is verified against. Never derived from a recipient's domain.
        port: The TCP port, explicit in the endpoint or this scheme's default.
        implicit_tls: ``True`` where TLS is established before the greeting;
            ``False`` where RFC 3207's ``STARTTLS`` upgrade is required. There is
            no third value, and in particular no cleartext one.
    """

    host: str
    port: int
    implicit_tls: bool


@final
@dataclass(frozen=True, slots=True)
class OutboundEmail:
    """The message an integration would have this transport send.

    Built by the integration from the call's arguments, and checked here against
    the binding rather than trusted: ADR-0148 §4's third clause makes the seam the
    party that refuses a recipient the ruling did not cover, and §6 makes it the
    party that refuses a span the description does not cover. A message that
    agrees with its binding is transmitted; one that does not raises
    :class:`BoundCallChangedError` and no byte leaves.

    Attributes:
        to: Recipients in the ``To`` header, in the order they were supplied.
        cc: Recipients in the ``Cc`` header.
        bcc: Recipients that receive the message and appear in no header, which
            is what makes a blind copy blind. They are envelope recipients like
            any other and are authorised like any other (ADR-0148 §4).
        subject: The ``Subject`` header's text.
        body: The message body, as ``text/plain``.
    """

    to: tuple[str, ...]
    cc: tuple[str, ...] = ()
    bcc: tuple[str, ...] = ()
    subject: str = ""
    body: str = ""

    @property
    def recipients(self) -> tuple[str, ...]:
        """Every envelope recipient, headers and blind copies alike.

        Returns:
            ``to``, then ``cc``, then ``bcc``, with duplicates kept — the envelope
            is what is compared against the bound set, and deduplicating here
            would hide a message naming one recipient twice from that comparison.
        """
        return (*self.to, *self.cc, *self.bcc)

    @property
    def texts(self) -> tuple[str, ...]:
        """Every span of this message that is not a recipient.

        Returns:
            The subject and the body, which are what the binding's non-destination
            spans have to cover.
        """
        return (self.subject, self.body)


class ByteChannel(Protocol):
    """A duplex byte stream to one pinned endpoint, with its own TLS state.

    Narrow on purpose. The transport below drives SMTP over *this*, so the only
    thing that has to open a socket is :func:`open_smtp_channel`, and a test
    exercises every command, every reply and every refusal against a local double
    without a network in reach. That is the shape ADR-0017 §8 wants generally — an
    injected transport capability — applied at one boundary rather than ratified
    across `core`, which is the move ADR-0147 §3 records itself making.
    """

    @property
    def is_secure(self) -> bool:
        """Whether a TLS handshake has completed on this channel."""
        ...

    async def read_line(self) -> bytes:
        """Read one CRLF-terminated line, or empty bytes at end of stream."""
        ...

    async def write(self, data: bytes, /) -> None:
        """Write ``data`` and flush it."""
        ...

    async def start_tls(self) -> None:
        """Upgrade this channel to TLS, verifying the pinned host's certificate."""
        ...

    async def close(self) -> None:
        """Release the channel, whatever state it is in."""
        ...


@final
class _StreamChannel:
    """The one :class:`ByteChannel` backed by a real socket.

    Thin by construction: it owns the streams, the TLS context and nothing else,
    so that everything a reviewer has to reason about — the pin, the ordering, the
    refusals — lives in :class:`SmtpEgressTransport` where it is testable.
    """

    __slots__ = ("_host", "_reader", "_secure", "_writer")

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        *,
        host: str,
        secure: bool,
    ) -> None:
        """Wrap an open pair of streams.

        Args:
            reader: The read half.
            writer: The write half.
            host: The pinned host, kept for a later ``STARTTLS`` upgrade so the
                certificate is verified against the endpoint rather than against
                anything the far end says about itself.
            secure: Whether TLS was established before the greeting.
        """
        self._reader = reader
        self._writer = writer
        self._host = host
        self._secure = secure

    @property
    def is_secure(self) -> bool:
        """Whether a TLS handshake has completed on this channel.

        Returns:
            ``True`` once implicit TLS or ``STARTTLS`` has succeeded.
        """
        return self._secure

    async def read_line(self) -> bytes:
        """Read one line, refusing one longer than this seam will hold.

        Returns:
            The line including its terminator, or empty bytes at end of stream.

        Raises:
            TransportPinError: If the far end sends a line without a terminator
                inside the bound, which is a server buying memory from a client
                that is holding a credential.
        """
        try:
            return await self._reader.readuntil(b"\n")
        except asyncio.IncompleteReadError:
            # A line with no terminator is not a reply, whatever octets arrived —
            # reporting end of stream is what makes the caller say so.
            return b""
        except asyncio.LimitOverrunError as exc:
            msg = "the endpoint sent a reply line this seam will not buffer"
            raise TransportPinError(msg) from exc

    async def write(self, data: bytes, /) -> None:
        """Write ``data`` and flush it.

        Args:
            data: The octets to send.
        """
        self._writer.write(data)
        await self._writer.drain()

    async def start_tls(self) -> None:
        """Upgrade to TLS, verifying the certificate against the pinned host."""
        await self._writer.start_tls(_tls_context(), server_hostname=self._host)
        self._secure = True

    async def close(self) -> None:
        """Close the writer, tolerating a far end that has already gone."""
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except OSError as exc:  # pragma: no cover — the far end closed first.
            _log.debug("egress_channel_close_failed", error_type=type(exc).__name__)


def _tls_context() -> ssl.SSLContext:
    """The TLS settings every connection this seam opens is made under.

    Certificate and hostname verification are the defaults and are stated rather
    than left implicit, because ``create_default_context`` is the one call whose
    behaviour a later edit could quietly weaken and #83's whole subject is a
    credential reaching the wrong host.

    Returns:
        A context verifying the peer's certificate chain and its hostname.
    """
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


async def open_smtp_channel(endpoint: SmtpEndpoint) -> ByteChannel:
    """Open a channel to ``endpoint``, and to nothing else.

    **This is the only function in `tools/` that opens a socket**, which is issue
    #83's third bullet answered by construction: the client is constructed
    centrally at the seam, so no integration can build one whose policy differs.
    It performs no name resolution of its own beyond the host it was handed —
    there is no MX lookup here, so no recipient's domain selects the host a
    credential is presented to.

    Args:
        endpoint: The pinned host, port and TLS mode.

    Returns:
        A connected channel, already under TLS where the scheme is implicit-TLS.

    Raises:
        OSError: If the connection could not be made. Not converted: a network
            that is down asserts nothing about the call's authorisation.
        ssl.SSLError: If the certificate did not verify against ``endpoint.host``.
    """
    reader, writer = await asyncio.open_connection(
        endpoint.host,
        endpoint.port,
        ssl=_tls_context() if endpoint.implicit_tls else None,
        server_hostname=endpoint.host if endpoint.implicit_tls else None,
        limit=_MAX_REPLY_LINE_OCTETS,
    )
    return _StreamChannel(reader, writer, host=endpoint.host, secure=endpoint.implicit_tls)


def parse_smtp_endpoint(endpoint: str) -> SmtpEndpoint:
    """Read an endpoint this seam will pin a connection to, or refuse it.

    The grammar is deliberately narrow and hand-read rather than handed to a
    general URL parser: every form a general parser accepts is a form this
    transport would then have to decide about, and a permissive endpoint is
    exactly #83's failure with the attacker supplying the configuration. Two
    schemes, a host, an optional port, and nothing else — no userinfo, no path,
    no query, no fragment, and no cleartext scheme.

    Args:
        endpoint: :attr:`~ai_assistant.core.types.EgressBinding.
            transport_endpoint`, as the binding carries it.

    Returns:
        The parsed endpoint.

    Raises:
        TransportPinError: If ``endpoint`` is not a form this seam will pin. The
            message names the defect and never the endpoint, which is
            configuration rather than content but is not this seam's to render.
    """
    scheme, separator, authority = endpoint.partition("://")
    if not separator or scheme not in _DEFAULT_PORTS:
        msg = (
            f"the bound transport endpoint names no scheme this seam pins; it is "
            f"{IMPLICIT_TLS_SCHEME}:// or {STARTTLS_SCHEME}://, and there is no "
            f"cleartext form"
        )
        raise TransportPinError(msg)
    if any(character in authority for character in "/?#@"):
        msg = (
            "the bound transport endpoint carries a path, a query, a fragment or "
            "userinfo; this seam pins a host and a port and nothing else"
        )
        raise TransportPinError(msg)
    host, colon, port_text = authority.rpartition(":")
    if not colon:
        host, port_text = authority, ""
    if not host or host.strip() != host:
        msg = "the bound transport endpoint names no host"
        raise TransportPinError(msg)
    return SmtpEndpoint(host=host, port=_port(port_text, scheme), implicit_tls=scheme == "smtps")


def _port(port_text: str, scheme: str) -> int:
    """Read the port, or this scheme's default.

    Args:
        port_text: The text after the last colon of the authority, possibly empty.
        scheme: The endpoint's scheme, which supplies the default.

    Returns:
        A port in ``1..65535``.

    Raises:
        TransportPinError: If the port is present and is not such a number. An
            unreadable port is refused rather than defaulted, because defaulting
            would connect somewhere nobody wrote down.
    """
    if not port_text:
        return _DEFAULT_PORTS[scheme]
    if not port_text.isdigit() or not 1 <= int(port_text) <= _MAX_PORT:
        msg = "the bound transport endpoint's port is not a TCP port number"
        raise TransportPinError(msg)
    return int(port_text)


def _refuse_changed(message: str) -> BoundCallChangedError:
    """Build a refusal that renders nothing the ruling was taken over."""
    return BoundCallChangedError(message)


@final
class SmtpEgressTransport:
    """Transmit one bound egress call over SMTP, or refuse it (ADR-0148 §6).

    **Constructed nowhere in production.** The seam is undesignated, so this class
    has no composition site, no registered callable reaches it, and its default
    connector is never called outside a designating ADR's future. What it is for
    is that ADR-0017 §3's conditions 5, 8 and 12 are properties of code, and a
    designating ADR has to attest them against something.

    The order in :meth:`transmit` is the decision, not an implementation detail,
    and every step of it is one of ADR-0148 §6's marked clauses:

    1. The binding's connection reference is the registration's, and its transport
       endpoint is the one the tool is configured to use. Neither is re-derived.
    2. The message is checked against the binding — every envelope recipient is a
       member of the bound canonical destination set, every member is a recipient,
       and every text span the message carries is covered by a span of the payload
       description. A member added, removed or substituted after the ruling is
       refused here rather than transmitted (§4's third clause).
    3. The connection record for the bound reference is read **once**, and the
       credential is read for the slot that record names with **no ``await`` in
       between** — ADR-0097 §5a's rule transposed onto the pair §6 binds.
    4. The record is re-read before any byte is transmitted, and the credential is
       discarded unless the record is still active, still carries the bound
       identity, and still carries the revision read before the credential read. A
       read that cannot be answered is treated as a changed one.
    5. Only then is a connection opened, and only to the pinned endpoint.

    **A denial never reaches step 3, because it never reaches this object.** A
    ``DENY`` constructs no ``ToolCall`` (ADR-0029 §2), so no callable runs, so
    nothing here reads a credential or opens a socket. ADR-0148 §7 makes that a
    consequence of where the read is rather than a rule anyone has to remember,
    and this class holds its ``Secrets`` face for exactly that reason: it is
    injected at the tool that needs one (ADR-0125 §8), and it is read from inside
    the callable and nowhere else.
    """

    __slots__ = ("_connect", "_records", "_registration", "_secrets")

    def __init__(
        self,
        *,
        registration: EgressRegistration,
        records: ConnectionRecords,
        secrets: Secrets,
        connect: Callable[[SmtpEndpoint], Awaitable[ByteChannel]] = open_smtp_channel,
    ) -> None:
        """Bind a transport to one registered tool and one connected account.

        Args:
            registration: The tool's egress registration — its connection
                reference and the endpoint it is configured to use. ADR-0148 §6
                binds a registered tool to at most one connected account, and this
                is that binding as `tools/` holds it.
            records: The connection records this transport reads. Exactly one read
                before the credential and one after, and no other store.
            secrets: The ``INTEGRATION``-scoped reading face ADR-0125 §8 injects
                at the tool that needs one. Never a ``SecretStore``: provisioning
                is not this object's, and a transport handed a writing face could
                delete the credential it reads.
            connect: How a channel is obtained. Defaults to the one function that
                opens a socket; a test supplies a local double, which is the whole
                reason this is a parameter.
        """
        self._registration = registration
        self._records = records
        self._secrets = secrets
        self._connect = connect

    async def transmit(self, binding: EgressBinding, message: OutboundEmail) -> None:
        """Send ``message`` under ``binding``, or refuse without transmitting.

        Args:
            binding: The egress binding the authorising decision carries, read
                back out of the trail by the executor (ADR-0037 §3). Every fact
                the transmission rests on is taken from here; nothing is
                re-derived, and nothing is taken from the call's arguments.
            message: What the integration would send.

        Raises:
            TransportPinError: If the endpoint is not the configured one or is not
                a form this seam pins, or the far end declined TLS or answered
                with a forward path.
            BoundCallChangedError: If the reference is not connectable, the
                recorded identity is not the bound one, the record moved across
                the credential read, or the message departs from the binding.
            IndeterminateTransmissionError: If the message was written and the
                server's verdict could not be read.
            ConnectionStoreError: If the **first** record read failed. A store
                outage asserts nothing about the call and is never converted; the
                *second* read is different, and an unanswerable one there is
                treated as a change.
        """
        # Every refusal that is decidable from the binding alone runs first, so a
        # call that cannot be performed as bound never reaches a credential read
        # at all. ADR-0148 §6 is explicit that its clauses do not guarantee that —
        # "they do not guarantee that no credential is ever read for a call that
        # is then refused" — so this is strictly better than the clause requires
        # and is here rather than in a docstring claiming a bound nobody has.
        endpoint = self._pinned(binding)
        sender = self._sender(binding)
        recipients = self._checked_message(binding, message)

        before = await self._records.latest(self._registration.reference)
        slot = self._slot_of(before, binding)
        credential = await self._secrets.get(slot)

        self._check_unchanged(await self._reread(), before, binding)
        if credential is None:
            msg = (
                f"{self._registration.tool_id}: the connection record for "
                f"{self._registration.reference!r} names a credential slot the "
                f"keyring holds nothing under; re-run the provisioning act"
            )
            raise _refuse_changed(msg)

        await self._send(
            endpoint,
            sender=sender,
            recipients=recipients,
            secret=credential.get_secret_value(),
            message=message,
        )

    def _pinned(self, binding: EgressBinding) -> SmtpEndpoint:
        """Refuse a binding this tool is not the registration for (ADR-0148 §6, #83).

        **Two of §6's four pre-transmission refusals, and the first is the one an
        implementation forgets.** That clause requires that "the connection
        reference the binding carries names the connection record it consults" —
        so the reference has to be compared against the registration's *before*
        the record is read, because the record is read **by the registration's**
        reference. Without it, a binding for account B's connection is checked
        against account A's record: where the two accounts share an identity, both
        record checks pass, and the message goes out under A's credential although
        the approval named B. The identity comparison cannot see it, because it is
        comparing the right identity against the wrong record.

        The endpoint is compared as text **before** it is parsed, so that two
        spellings of one host are two different endpoints here rather than one: a
        transmission to an endpoint that merely resolves the same way is a
        transmission nobody wrote down.

        Args:
            binding: The authorised binding.

        Returns:
            The parsed endpoint.

        Raises:
            TransportPinError: If the binding names another connection, is not for
                the configured endpoint, or names one this seam will not pin.
        """
        if binding.account.reference != self._registration.reference:
            msg = (
                f"{self._registration.tool_id}: the binding names a connection this "
                f"tool is not registered for, so the record consulted would not be "
                f"the one the ruling was taken over (ADR-0148 §6). This tool is "
                f"registered for {self._registration.reference!r}"
            )
            raise TransportPinError(msg)
        if binding.transport_endpoint != self._registration.transport_endpoint:
            msg = (
                f"{self._registration.tool_id}: the bound transport endpoint is not "
                f"the one this tool is configured to use, so the connection would "
                f"not be to the service the ruling named (ADR-0148 §6, issue #83)"
            )
            raise TransportPinError(msg)
        return parse_smtp_endpoint(binding.transport_endpoint)

    def _sender(self, binding: EgressBinding) -> str:
        """The envelope sender: the bound account's identity, as a mailbox.

        Derived from the binding rather than from configuration, and *checked*
        rather than assumed to be an address: this seam's own canonicaliser is
        asked, so an account whose identity is not a mailbox is refused instead of
        being interpolated into a ``MAIL FROM`` command. That is ADR-0148 §2's
        sixth clause used where it happens to be useful — one canonicaliser per
        protocol, so the sender and the recipients are read by the same rules.

        Args:
            binding: The authorised binding.

        Returns:
            The canonical form of the bound identity.

        Raises:
            BoundCallChangedError: If the bound identity is not an SMTP mailbox.
        """
        try:
            return canonicalise(SeamProtocol.SMTP, binding.account.identity).canonical
        except DestinationCanonicalisationError as exc:
            msg = (
                f"{self._registration.tool_id}: the bound account's identity is not "
                f"an SMTP mailbox, so this transport has no envelope sender for it"
            )
            raise _refuse_changed(msg) from exc

    def _checked_message(self, binding: EgressBinding, message: OutboundEmail) -> tuple[str, ...]:
        """Refuse a message that departs from what was authorised.

        Two checks, and they are the seam's half of two different clauses. The
        recipient check is ADR-0148 §4's third clause — "the callable transmits to
        every member of the bound set and to no other recipient" — read as a set
        equality in both directions, so a member added after the ruling and a
        member silently dropped from it fail alike. The span check is §6's
        callable-side clause: "a callable that finds itself about to transmit a
        span the description does not cover refuses instead".

        Spans are matched two ways because the binding holds them two ways. A span
        carrying a destination is matched by that destination's **canonical** form,
        which is what the envelope carries. A span carrying none is payload text,
        whose canonical form is nothing at all, so it is matched by **extent** — as
        a multiset, so a second undescribed body of the same length as the subject
        cannot borrow the subject's span.

        Args:
            binding: The authorised binding.
            message: What the integration would send.

        Returns:
            The envelope recipients, deduplicated and ordered as the message
            supplied them, which is what ``RCPT TO`` is issued for.

        Raises:
            BoundCallChangedError: If the recipients or the spans disagree.
        """
        bound = {
            member.canonical
            for member in binding.canonical_destination_set
            if member.protocol is DestinationProtocol.SMTP and member.canonical is not None
        }
        envelope = dict.fromkeys(message.recipients)
        if set(envelope) != bound:
            msg = (
                f"{self._registration.tool_id}: the message's {len(envelope)} "
                f"envelope recipient(s) are not the {len(bound)} member(s) of the "
                f"bound canonical destination set. The set is authorised whole and "
                f"a member is never added, dropped or substituted after the ruling "
                f"(ADR-0148 §4)"
            )
            raise _refuse_changed(msg)
        self._check_spans_cover(binding, message)
        return tuple(envelope)

    def _check_spans_cover(self, binding: EgressBinding, message: OutboundEmail) -> None:
        """Refuse a payload span the description does not cover (ADR-0148 §6).

        Args:
            binding: The authorised binding.
            message: What the integration would send.

        Raises:
            BoundCallChangedError: If a text span has no covering description.
        """
        remaining = [span.extent for span in binding.spans if span.destination is None]
        for extent in sorted(len(text) for text in message.texts if text):
            if extent not in remaining:
                msg = (
                    f"{self._registration.tool_id}: the message carries a payload "
                    f"span of {extent} code point(s) that the approved payload "
                    f"description does not cover, so no approver saw it "
                    f"(ADR-0148 §6)"
                )
                raise _refuse_changed(msg)
            remaining.remove(extent)

    def _slot_of(self, stored: StoredEntry | None, binding: EgressBinding) -> SecretName:
        """Read the record's slot, refusing a reference that is not connectable.

        **Synchronous, and that is the point.** ADR-0148 §6 makes the check and
        the credential read one step — "no ``await`` occurs between reading the
        identity, revision, provisioning state and slot recorded for the bound
        reference and calling ``Secrets.get`` for **that** slot" — so everything
        this decides has to be decidable without suspending. A helper that awaited
        anything here would reopen the window ADR-0097 §5a closes.

        Args:
            stored: The record read for the bound reference, or ``None``.
            binding: The authorised binding.

        Returns:
            The slot the record names, which is never carried in the binding
            (ADR-0148 §6) and is therefore never compared against one.

        Raises:
            BoundCallChangedError: If the reference is not connectable, or the
                identity currently recorded for it is not the bound one.
        """
        entry = _entry_of(stored)
        if entry is None or entry.state is not ProvisioningState.ACTIVE or entry.slot is None:
            state = "absent" if entry is None or entry.state is None else entry.state.value
            msg = (
                f"{self._registration.tool_id}: connection "
                f"{self._registration.reference!r} is not connectable — its record is "
                f"{state}. Nothing transmits under it; re-running the provisioning "
                f"act is the remedy (ADR-0148 §6)"
            )
            raise _refuse_changed(msg)
        if entry.identity != binding.account.identity:
            msg = (
                f"{self._registration.tool_id}: connection "
                f"{self._registration.reference!r} is recorded for a different account "
                f"than the ruling was taken over, so nothing transmits under it "
                f"(ADR-0148 §6)"
            )
            raise _refuse_changed(msg)
        return entry.slot

    async def _reread(self) -> StoredEntry | None:
        """Re-read the connection record, treating an unanswerable read as changed.

        Returns:
            The record, or ``None`` where the read could not be answered — which
            :meth:`_check_unchanged` refuses exactly as it refuses a change.

        The store's own failure is **not** propagated here, unlike the first read.
        ADR-0148 §6's discard clause says "a read that cannot be answered is
        treated as a changed one", and it says so because the credential is
        already in hand at this point: a caller that saw the store's error and
        retried would be retrying with a live credential and no verified account.
        """
        try:
            return await self._records.latest(self._registration.reference)
        except ConnectionStoreError as exc:
            _log.warning(
                "egress_record_reread_unanswerable",
                reference=self._registration.reference,
                error_type=type(exc).__name__,
            )
            return None

    def _check_unchanged(
        self, after: StoredEntry | None, before: StoredEntry | None, binding: EgressBinding
    ) -> None:
        """Discard the credential unless the record is exactly as it was.

        ADR-0148 §6's post-read clause, with its revision rule stated as that
        section states it: the revision is compared **only** before against after,
        across the credential read, and never against a value the binding carries.
        A completed rotation between the ruling and the resume therefore refuses
        nothing on the revision's account, while one landing *inside* the read
        refuses that read — and the A → B → A sequence an identity comparison
        alone cannot see is caught, because a revision is never reused.

        Args:
            after: The record as it stands now, or ``None`` for an unanswerable
                read.
            before: The record read immediately before the credential.
            binding: The authorised binding.

        Raises:
            BoundCallChangedError: If anything moved. The credential is dropped by
                falling out of scope with the frame, and no byte is transmitted.
        """
        first, second = _entry_of(before), _entry_of(after)
        if (
            second is None
            or first is None
            or second.state is not ProvisioningState.ACTIVE
            or second.identity != binding.account.identity
            or second.revision != first.revision
        ):
            msg = (
                f"{self._registration.tool_id}: connection "
                f"{self._registration.reference!r} changed across the credential "
                f"read, so the credential is discarded and nothing is transmitted "
                f"(ADR-0148 §6)"
            )
            raise _refuse_changed(msg)

    async def _send(
        self,
        endpoint: SmtpEndpoint,
        *,
        sender: str,
        recipients: Sequence[str],
        secret: str,
        message: OutboundEmail,
    ) -> None:
        """Open the pinned connection and run the submission exchange.

        Args:
            endpoint: The pinned host, port and TLS mode.
            sender: The envelope sender.
            recipients: Every bound recipient, and no other.
            secret: The credential, presented only over a verified TLS channel.
            message: What to send.

        Raises:
            TransportPinError: If TLS was declined or a forward path was offered.
            BoundCallChangedError: If the exchange was refused before the payload.
            IndeterminateTransmissionError: If the payload was written and the
                verdict could not be read.
        """
        channel = await self._connect(endpoint)
        try:
            session = _SmtpSession(channel, host=endpoint.host, tool_id=self._registration.tool_id)
            await session.open(implicit_tls=endpoint.implicit_tls)
            await session.authenticate(identity=sender, secret=secret)
            await session.envelope(sender=sender, recipients=recipients)
            await session.data(_rendered(sender, message))
            await session.quit()
        finally:
            await channel.close()


def _entry_of(stored: StoredEntry | None) -> ConnectionEntry | None:
    """The entry a store read yielded, or ``None``.

    The store pairs an entry with its compare-and-swap sequence; this transport
    performs no write, so it wants the entry and never the token — and saying so
    in one place keeps every reader of the checks above from having to.

    Args:
        stored: What ``ConnectionRecords.latest`` returned.

    Returns:
        The entry, or ``None`` where the read found nothing.
    """
    return None if stored is None else stored.entry


def _rendered(sender: str, message: OutboundEmail) -> bytes:
    """Serialise ``message`` for ``DATA``, with blind copies in no header.

    Args:
        sender: The envelope sender, which is also the ``From`` header.
        message: What to send.

    Returns:
        The RFC 5322 message, CRLF-terminated, ready to be dot-stuffed.
    """
    document = EmailMessage()
    document["From"] = sender
    if message.to:
        document["To"] = ", ".join(message.to)
    if message.cc:
        document["Cc"] = ", ".join(message.cc)
    document["Subject"] = message.subject
    document.set_content(message.body)
    return document.as_bytes(policy=SMTP_POLICY)


def _dot_stuffed(payload: bytes) -> bytes:
    """Apply RFC 5321 §4.5.2's transparency and terminate the ``DATA`` block.

    A body line beginning with ``.`` would otherwise end the message early, which
    is a truncated disclosure rather than a failure — the far end accepts what it
    received and the sender believes it sent more.

    Args:
        payload: The serialised message.

    Returns:
        The stuffed payload followed by ``CRLF.CRLF``.
    """
    body = payload.replace(b"\r\n.", b"\r\n..")
    if body.startswith(b"."):
        body = b"." + body
    if not body.endswith(b"\r\n"):
        body += b"\r\n"
    return body + b".\r\n"


@final
class _SmtpSession:
    """The SMTP command exchange, over a channel somebody else opened.

    Split from :class:`SmtpEgressTransport` because the two answer different
    questions: that class decides whether this call may be made at all, and this
    one speaks the protocol. Everything security-relevant that is *about SMTP*
    rather than about the binding lives here — the TLS requirement, the refusal to
    present a credential in the clear, and the two forward-path replies.
    """

    __slots__ = ("_channel", "_host", "_tool_id")

    def __init__(self, channel: ByteChannel, *, host: str, tool_id: str) -> None:
        """Drive ``channel`` as an SMTP submission session.

        Args:
            channel: The open channel.
            host: The pinned host, sent in ``EHLO`` and never learned from a reply.
            tool_id: Named in every refusal, and the only identifier that is.
        """
        self._channel = channel
        self._host = host
        self._tool_id = tool_id

    async def open(self, *, implicit_tls: bool) -> frozenset[str]:
        """Read the greeting, greet, and upgrade where the scheme requires it.

        Args:
            implicit_tls: Whether TLS was already established on connect.

        Returns:
            The extension keywords the far end advertises, upper-cased.

        Raises:
            TransportPinError: If the greeting is not a 220, or the far end does
                not offer ``STARTTLS`` where the scheme requires it, or declines
                the upgrade. There is no cleartext fallback.
        """
        await self._expect(_READY, "the endpoint did not greet this connection")
        extensions = await self._ehlo()
        if implicit_tls:
            return extensions
        if "STARTTLS" not in extensions:
            msg = (
                f"{self._tool_id}: the endpoint does not offer STARTTLS, and this "
                f"seam has no cleartext form to fall back to (issue #83)"
            )
            raise TransportPinError(msg)
        await self._command("STARTTLS")
        await self._expect(_READY, "the endpoint declined the STARTTLS upgrade")
        await self._channel.start_tls()
        return await self._ehlo()

    async def _ehlo(self) -> frozenset[str]:
        """Send ``EHLO`` and read the extensions offered.

        Returns:
            The first word of each continuation line, upper-cased.

        Raises:
            TransportPinError: If the far end did not accept the greeting.
        """
        await self._command(f"EHLO {self._host}")
        _, text = await self._expect(_COMPLETED, "the endpoint refused EHLO")
        return frozenset(
            line.split(None, 1)[0].upper() for line in text.splitlines()[1:] if line.strip()
        )

    async def authenticate(self, *, identity: str, secret: str) -> None:
        """Present the credential, and only over a verified TLS channel.

        Args:
            identity: The authentication identity — the bound account's mailbox.
            secret: The credential.

        Raises:
            TransportPinError: If the channel is not secure. The credential does
                not travel, which is the property #83's second failure-path row
                is stated over, and it is read from the channel's own TLS state
                rather than inferred from the order commands were written in.
            BoundCallChangedError: If the far end refused the credential.
        """
        if not self._channel.is_secure:
            msg = (
                f"{self._tool_id}: the channel is not under TLS, so the credential "
                f"is not presented and nothing is transmitted (issue #83)"
            )
            raise TransportPinError(msg)
        token = base64.b64encode(f"\0{identity}\0{secret}".encode()).decode("ascii")
        await self._command(f"AUTH PLAIN {token}", redacted="AUTH PLAIN")
        code, _ = await self._reply()
        if code != _AUTHENTICATED:
            msg = (
                f"{self._tool_id}: the endpoint refused the connected account's "
                f"credential with {code}; nothing is transmitted"
            )
            raise _refuse_changed(msg)

    async def envelope(self, *, sender: str, recipients: Sequence[str]) -> None:
        """Issue ``MAIL FROM`` and one ``RCPT TO`` per bound recipient.

        A recipient the far end refuses fails the **whole** call: ADR-0148 §4's
        second clause forbids removing the uncovered member and sending to the
        remainder, and "partial success is the hardest failure to notice
        afterwards" (#93 item 2). No ``DATA`` follows a refusal here.

        Args:
            sender: The envelope sender.
            recipients: Every bound recipient, in order.

        Raises:
            TransportPinError: If a recipient draws RFC 5321 §3.4's forward-path
                reply, which names a mailbox at another host and is not followed.
            BoundCallChangedError: If the sender or any recipient was refused.
        """
        await self._command(f"MAIL FROM:<{sender}>")
        code, _ = await self._reply()
        if code != _COMPLETED:
            msg = f"{self._tool_id}: the endpoint refused the envelope sender with {code}"
            raise _refuse_changed(msg)
        for recipient in recipients:
            await self._command(f"RCPT TO:<{recipient}>")
            code, _ = await self._reply()
            if code in _FORWARD_PATH_REPLIES:
                msg = (
                    f"{self._tool_id}: the endpoint answered {code}, offering a "
                    f"forward path to another host. This seam does not follow one — "
                    f"delivery there was covered by no ruling (issue #83)"
                )
                raise TransportPinError(msg)
            if code != _COMPLETED:
                msg = (
                    f"{self._tool_id}: the endpoint refused a bound recipient with "
                    f"{code}. The set is authorised whole, so the call fails rather "
                    f"than delivering to the remainder (ADR-0148 §4)"
                )
                raise _refuse_changed(msg)

    async def data(self, payload: bytes) -> None:
        """Send the message, and be honest about the one unknowable window.

        Args:
            payload: The serialised message.

        Raises:
            BoundCallChangedError: If ``DATA`` was refused, which happens before
                any octet of the payload is written.
            IndeterminateTransmissionError: If the payload and its terminator were
                written and the verdict could not be read. This is the case
                ADR-0017 §3 names — "a timeout is indistinguishable from a
                successful disclosure" — and it is reported as itself rather than
                as a failure, so ADR-0014 §4's recovery scan has something true to
                reconcile.

                **``OSError`` is caught here and nowhere else in this class, and
                the asymmetry is the decision.** Everywhere before the payload is
                written, a reset or a timeout is a call that provably did nothing,
                and ADR-0029 §4's classification of it as a failure is correct.
                Once the terminator is on the wire the same exception says only
                that this end stopped listening, which is not evidence about what
                the far end did with the octets — so letting it escape would have
                the invocation seam record ``INTERNAL`` for a disclosure that may
                have happened. That is the exact confusion this window exists to
                prevent, arriving through the one exception type nobody thinks of
                as an outcome.
        """
        await self._command("DATA")
        code, _ = await self._reply()
        if code != _START_MAIL_INPUT:
            msg = f"{self._tool_id}: the endpoint refused DATA with {code}; nothing was sent"
            raise _refuse_changed(msg)
        await self._channel.write(_dot_stuffed(payload))
        try:
            code, _ = await self._reply()
        except (EgressTransportError, OSError) as exc:
            msg = (
                f"{self._tool_id}: the message was written and the endpoint's verdict "
                f"could not be read, so whether it was accepted is unknown"
            )
            raise IndeterminateTransmissionError(msg) from exc
        if code != _COMPLETED:
            msg = (
                f"{self._tool_id}: the message was written and the endpoint answered "
                f"{code}, so whether any recipient received it is unknown"
            )
            raise IndeterminateTransmissionError(msg)

    async def quit(self) -> None:
        """Close the session politely, and never let that change the outcome."""
        try:
            await self._command("QUIT")
            await self._reply()
        except (EgressTransportError, OSError) as exc:
            _log.debug("egress_quit_failed", tool_id=self._tool_id, error_type=type(exc).__name__)

    async def _command(self, command: str, *, redacted: str | None = None) -> None:
        """Write one command line.

        Args:
            command: The command, without its terminator.
            redacted: What to log in its place where the command carries a
                credential. ``AUTH PLAIN``'s argument is the credential, so the
                command is never logged whole.
        """
        _log.debug("egress_smtp_command", command=redacted or command.split(":", 1)[0])
        await self._channel.write(command.encode("ascii") + b"\r\n")

    async def _expect(self, code: int, complaint: str) -> tuple[int, str]:
        """Read a reply and require ``code``.

        Args:
            code: The reply code this step requires.
            complaint: What to say if it is something else.

        Returns:
            The reply.

        Raises:
            TransportPinError: If the reply is not ``code``.
        """
        reply = await self._reply()
        if reply[0] != code:
            msg = f"{self._tool_id}: {complaint} (reply {reply[0]})"
            raise TransportPinError(msg)
        return reply

    async def _reply(self) -> tuple[int, str]:
        """Read one reply, following RFC 5321 §4.2's continuation form.

        Returns:
            The reply code and the joined text of every line.

        The line **count** is bounded as well as the line length, and the second
        bound is not implied by the first: every continuation line can sit under
        :data:`_MAX_REPLY_LINE_OCTETS` while the reply never terminates, so a far
        end that answers ``EHLO`` with endless ``250-`` lines buys unbounded memory
        from a client that is about to present it a credential. Neither bound is a
        *deadline*, deliberately — ADR-0029 §4 puts the deadline on the invocation
        seam ("the seam owns the deadline"), and a second watchdog inside a
        callable is the shape ``tools/invocation.py`` records ADR-0029 §10 warning
        against. What is closed here is the resource exhaustion, which a deadline
        would not close anyway: memory grows for as long as the deadline allows.

        Raises:
            TransportPinError: If the stream ended, a line is not a reply, or the
                reply does not terminate inside :data:`_MAX_REPLY_LINES`.
        """
        lines: list[str] = []
        while len(lines) < _MAX_REPLY_LINES:
            raw = await self._channel.read_line()
            if not raw:
                msg = f"{self._tool_id}: the endpoint closed the connection mid-reply"
                raise TransportPinError(msg)
            line = raw.decode("ascii", "replace").rstrip("\r\n")
            if len(line) < _REPLY_PREFIX or not line[:3].isdigit() or line[3] not in "- ":
                msg = f"{self._tool_id}: the endpoint sent something that is not an SMTP reply"
                raise TransportPinError(msg)
            lines.append(line[4:])
            if line[3] == " ":
                return int(line[:3]), "\n".join(lines)
        msg = (
            f"{self._tool_id}: the endpoint sent more than {_MAX_REPLY_LINES} "
            f"continuation lines without terminating the reply"
        )
        raise TransportPinError(msg)


__all__ = [
    "IMPLICIT_TLS_SCHEME",
    "STARTTLS_SCHEME",
    "BoundCallChangedError",
    "ByteChannel",
    "EgressTransportError",
    "IndeterminateTransmissionError",
    "OutboundEmail",
    "SmtpEgressTransport",
    "SmtpEndpoint",
    "TransportPinError",
    "open_smtp_channel",
    "parse_smtp_endpoint",
]
