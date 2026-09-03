"""The `tools/` egress seam: named, designated, and the one module here that transmits.

This is the seam ADR-0017 §2 anticipates and ADR-0147 §3 names:
``ai_assistant.tools.egress`` — **one module, not a package**, holding outbound
transport and nothing else. `tools/` also owns definitions, the registry and the
invocation path, and none of those has any business holding a network client;
that is why the seam is a module the boundary can be drawn *around* rather than a
package the boundary would follow wherever the code grew. Naming it is what issue
#66 asked for since the architecture review of PR #64 — a name "precise enough for
an import-linter contract to pin the module" — and the contract that pins it is
``network transports are confined to the tools egress seam`` in ``pyproject.toml``.

**This module may transmit, and it is the only one under ``ai_assistant.tools``
that may.** ADR-0154 §1 designates it, and §4 attests all fourteen of ADR-0017 §3's
conditions in code, row by row and against named tests. That is the event ADR-0147
§3 described and withheld: naming a seam is not designating it, that ADR attested
no condition of §3, and no lane could cite it — or this module's existence —
toward one. ADR-0154 is the ADR that named which module, attested how, and recorded
the transition, so ADR-0017 §1's rule as ADR-0124 §1 restates it now has all three
of its boundaries operational rather than two.

**What made a designation possible is that this module existed first.** It is the
machinery ADR-0017 §3's conditions 5, 8 and 12 are stated *about*, written so that
a designating ADR had code to attest against rather than a plan. ADR-0148 §13
scopes transport pinning out of itself in terms — "what pins the endpoint to the
connected service, and what a redirect may do, wants an HTTP client in hand" — and
issue #83's own third bullet asks "whether the client is constructed centrally at
the seam so the policy cannot be bypassed per integration. If each integration
builds its own client, this is unenforceable by construction." That question is
answerable only by a client existing here, and this is it.

**Designation is not a licence this module spends by itself.** A byte leaves only
where a deployment configured an integration (ADR-0148 §6 binds a registered tool
to at most one connected account), where the user authorised that specific call
whole (ADR-0148 §1's single route and §3's route (a), with ADR-0154 §4 admitting no
standing authorisation at this seam), and where the arguments still yield the call
the binding describes. What :class:`SmtpEgressTransport` adds on top of all of that
is the **pin**, described below.

**Exactly one place in production constructs one**, which is issue #83's third
bullet answered rather than assumed:
:func:`~ai_assistant.tools.builtin.build_send_email_integration`. The tool that
sends through it names no transport at all — it holds a one-method
:class:`~ai_assistant.tools.send_email.BoundTransport` Protocol — so a second
integration wired later comes through that same factory or through nothing.
``tests/tools/test_egress_seam.py`` holds the tree to it: one production namer,
exactly one function here that opens a connection
(:meth:`StreamOutboundTransport.open_channel`), and no tool able to reach a
transport in a deployment that configured none.

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
import unicodedata
from contextlib import suppress
from dataclasses import dataclass
from email.message import EmailMessage
from email.policy import SMTP as SMTP_POLICY
from typing import TYPE_CHECKING, Final, final

import structlog
from pydantic import ValidationError

from ai_assistant.core.errors import ConnectionStoreError, ToolError, TransportError
from ai_assistant.core.types import (
    TRANSPORT_OCTET_CEILING,
    DestinationProtocol,
    ProvisioningState,
    TransportEndpoint,
)
from ai_assistant.tools.destinations import DestinationCanonicalisationError, canonicalise
from ai_assistant.tools.destinations import DestinationProtocol as SeamProtocol

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.protocols import ByteChannel, OutboundTransport, Secrets
    from ai_assistant.core.types import EgressBinding, FrozenJson, SecretName
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

#: Message fields rendered into an RFC 5322 **header**, where a line break ends
#: the header and begins another. The body is deliberately not among them: it is
#: content, and RFC 5321 §4.5.2's transparency is what makes its line breaks safe.
#:
#: **This is refusal hygiene, not a disclosure control, and the difference is worth
#: stating.** ``EmailMessage`` already refuses a header value containing ``CR`` or
#: ``LF`` — "Header values may not contain linefeed or carriage return characters"
#: — so a smuggled ``Bcc:`` never reaches the wire whether or not this check
#: exists, and no unauthorised recipient is reachable through it. What the stdlib's
#: refusal does *not* do is arrive at the right time or in the right type: it fires
#: inside :func:`_rendered`, which runs after the credential has been presented and
#: the envelope accepted, and it escapes as a bare ``ValueError`` that ADR-0029 §3
#: records as ``INTERNAL``. ADR-0148 §1's third clause is the ground for moving it:
#: a call that cannot be performed is refused before anything is spent on it, which
#: is ADR-0145's precedent one field over. Adversarial round 4 found it.
_HEADER_TEXT_FIELDS: Final = frozenset({"subject"})

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

#: How many digits a port can be written in, derived from the bound above rather
#: than stated beside it so the two cannot drift apart. It is not a second rule:
#: no canonical decimal in ``1..65535`` is longer. It is checked **before** the
#: conversion because CPython refuses ``int()`` on a string of more than 4300
#: digits, so an endpoint whose port is five thousand digits would pass every
#: character test and then raise ``ValueError`` out of the conversion — which is
#: the very escape the ASCII rule below closes (#1147).
_MAX_PORT_DIGITS: Final = len(str(_MAX_PORT))

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
    that did not happen. The caller that honours the split is
    :func:`~ai_assistant.tools.invocation.indeterminate_failure`, which is where
    it used to be lost one layer out (issue #1602).
    """


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


@final
class _StreamChannel:
    """The one :class:`~ai_assistant.core.protocols.ByteChannel` backed by a socket.

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
        """Read one line, refusing one longer than the contract will hold.

        Returns:
            The line including its terminator, or empty bytes at end of stream —
            which is also what a tail with no terminator reports, the octets
            being discarded in its place.

        Raises:
            TransportError: If the far end sends more than
                :data:`~ai_assistant.core.types.TRANSPORT_OCTET_CEILING` octets
                without a terminator among them, which is a server buying memory
                from a client that is holding a credential. The reader is opened
                with that same ceiling as its ``limit``, and
                ``StreamReader.readuntil`` applies it to the buffer **ahead of**
                the separator — so the boundary the conformance suite pins is the
                one this implementation has, rather than one restated here.
        """
        try:
            return await self._reader.readuntil(b"\n")
        except asyncio.IncompleteReadError:
            # A line with no terminator is not a reply, whatever octets arrived —
            # reporting end of stream is what makes the caller say so.
            return b""
        except asyncio.LimitOverrunError as exc:
            msg = "the endpoint sent a reply line this channel will not buffer"
            raise TransportError(msg) from exc
        except OSError as exc:
            raise self._failed("reading a line") from exc

    async def read(self, limit: int, /) -> bytes:
        """Read at most ``limit`` octets from the same cursor :meth:`read_line` uses.

        Unused by the SMTP exchange above, which is line-oriented, and present
        because the contract has it: a second protocol built on this channel reads
        octets rather than lines, and a channel that answered only one of the two
        would make that protocol reimplement buffering (ADR-0191 §2).

        Args:
            limit: How many octets at most, in
                ``1..TRANSPORT_OCTET_CEILING`` inclusive.

        Returns:
            Between one and ``limit`` octets, or empty bytes at end of stream.

        Raises:
            ValueError: If ``limit`` is outside that range. **The refusal is the
                point rather than an argument check**: ``StreamReader.read``
                spells "until end of stream" as ``-1``, so a peer that streams
                without closing would exhaust memory through a method whose name
                says it is bounded. Refusing the whole domain outside
                ``1..ceiling`` makes that spelling unrepresentable.
        """
        if not 1 <= limit <= TRANSPORT_OCTET_CEILING:
            msg = f"read limit must be an integer in 1..{TRANSPORT_OCTET_CEILING}; got {limit}"
            raise ValueError(msg)
        try:
            return await self._reader.read(limit)
        except OSError as exc:
            raise self._failed("reading") from exc

    async def write(self, data: bytes, /) -> None:
        """Write ``data`` and flush it.

        Args:
            data: The octets to send.

        Raises:
            TransportError: If the connection could not be continued.
        """
        try:
            self._writer.write(data)
            await self._writer.drain()
        except OSError as exc:
            raise self._failed("writing") from exc

    async def start_tls(self) -> None:
        """Upgrade to TLS, verifying the certificate against the pinned host.

        Raises:
            TransportError: If the far end declined the upgrade or its certificate
                did not verify against the pinned host. :attr:`is_secure` stays
                ``False``, which is the read the seam refuses to present a
                credential on (ADR-0191 §4).
        """
        try:
            await self._writer.start_tls(_tls_context(), server_hostname=self._host)
        except OSError as exc:
            raise self._failed("upgrading to TLS") from exc
        self._secure = True

    def _failed(self, doing: str) -> TransportError:
        """The one refusal type every I/O-bearing method of this channel raises.

        ADR-0191 §1 makes ``TransportError`` the **shared** taxonomy: the
        production implementation and the canonical fake raise it, so the
        conformance suite holds both to one vocabulary and a consumer that catches
        it does not have to know this channel happens to sit on ``asyncio``.
        Leaving a raw ``ConnectionResetError`` or ``ssl.SSLError`` through would
        make the promise false for exactly the failures it exists for — both review
        lenses found that on round 1.

        ``ssl.SSLError`` is an ``OSError`` and needs no clause of its own; a
        ``CancelledError`` is a ``BaseException`` and is not converted, which is
        ADR-0060 §1's propagation rule.

        Args:
            doing: What the channel was doing, for the message. Never an octet:
                ADR-0152 §11's discipline applies to this neighbouring surface.

        Returns:
            The refusal to raise, so the caller writes ``raise … from exc``.
        """
        return TransportError(f"the connection to {self._host} failed while {doing}")

    async def close(self) -> None:
        """Close the writer, tolerating a far end that has already gone.

        Idempotent, and an ordinary release failure is logged rather than raised
        (ADR-0191 §1): a holder closes from a cleanup path, where Python would
        replace the exception in flight with one raised here — turning an honest
        ``IndeterminateTransmissionError`` into an internal failure, and recording
        a possible disclosure as one that did not happen.

        **Both halves of the release are inside the guard**, and the synchronous
        one used to be outside it: ``StreamWriter.close`` can raise on a transport
        that is already broken, and that exception replaced the one in flight by
        the route this method exists to close. Adversarial review found it on
        round 4.
        """
        try:
            self._writer.close()
        except OSError as exc:
            self._abort_after(exc)
            return
        # **The wait is held in a task of its own, and this awaits a shield of
        # it.** ``StreamWriter.wait_closed`` awaits the protocol's *shared* close
        # waiter, so a cancellation delivered while this method awaited it
        # directly would cancel that shared future — and every later ``close``
        # awaiting the same future would raise ``CancelledError`` out of a call
        # nobody cancelled, which is this contract's idempotency broken by the
        # cleanup path. Adversarial review found it on round 10.
        waiting = asyncio.ensure_future(self._writer.wait_closed())
        try:
            await asyncio.shield(waiting)
        except asyncio.CancelledError:
            # **Safe first, then re-raised** (ADR-0191 §1, ADR-0060 §1). The
            # abort is what makes it prompt: it drops the transport rather than
            # waiting on a far end that may never read again. Delivery is then
            # deferred until the wait this method started has finished — the same
            # order and the same **unbounded, documented** deferral as
            # ``open_channel``'s, bounded in practice by the abort above and as a
            # whole by ADR-0029 §4's invocation deadline.
            with suppress(OSError):
                self._writer.transport.abort()
            while not waiting.done():
                with suppress(asyncio.CancelledError):
                    await asyncio.wait((waiting,))
            if not waiting.cancelled():
                # **Retrieved, and read.** ADR-0191 §1 has an ordinary release
                # failure suppressed *and logged*, and a cancellation changes
                # which exception leaves rather than whether a release that
                # failed beside it is reported: a transport that had already
                # scheduled ``connection_lost(exc)`` when the cancellation
                # arrived is exactly that pair. So the outcome is read rather
                # than only marked retrieved — and logged **without** taking the
                # transport a second time, because the abort above has run.
                # Adversarial review found it on round 11.
                failure = waiting.exception()
                if isinstance(failure, OSError):
                    self._log_release_failure(failure)
            raise
        except OSError as exc:
            self._abort_after(exc)

    def _abort_after(self, failure: OSError) -> None:
        """Log a failed release and take the harder one.

        **Suppressing the failure is not the same as having released**, and the
        holder has already called ``close``: nothing else will try again. So the
        transport is dropped, on the same reasoning as :func:`_release` and
        suppressed on the same ground. Adversarial review found this half on
        round 7, having found the opener's on round 6.

        Args:
            failure: What the release raised, logged by type alone.
        """
        self._log_release_failure(failure)
        with suppress(OSError):
            self._writer.transport.abort()

    def _log_release_failure(self, failure: OSError) -> None:
        """Report a release that failed, by type alone.

        One site for the event, because two paths owe it: an ordinary release
        failure, and one that completed while a cancellation was in flight. Only
        the type is recorded — an ``OSError`` from a far end can carry that far
        end's own words, and ADR-0152 §11's discipline applies to this
        neighbouring surface.

        Args:
            failure: What the release raised.
        """
        _log.debug("egress_channel_close_failed", error_type=type(failure).__name__)


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


@final
class StreamOutboundTransport:
    """The one :class:`~ai_assistant.core.protocols.OutboundTransport` that connects.

    ADR-0191 §3 puts the one production implementation that reaches the network in
    this designated module and in no other module under ``src/ai_assistant``, and
    ADR-0191 §1 makes the *opener* the capability because opening is the act being
    governed: a subsystem that holds a channel already has a connection, so the
    thing that must be scarce is the ability to obtain one at all.

    **There is no module-level instance of this and no function that returns one.**
    Its predecessor was ``open_smtp_channel``, a module-level coroutine that opened
    a socket — which meant any module that could import it held a route to the
    world, and which is exactly the accessor §3 forbids. The only way to hold this
    capability is to have been handed it, and ``app/composition.py`` is the only
    place in ``src/ai_assistant`` that constructs one (§3).

    **:meth:`open_channel` is the only place in this seam that opens a socket.**
    That is issue #83's third bullet answered by construction — the client is
    constructed centrally at the seam, so no integration can build one whose policy
    differs — and ``tests/tools/test_egress_seam.py`` holds the tree to there being
    exactly one such function to find.

    **It is stateless and holds no pool.** A pooled capability is a long-lived
    connection owned by whoever opened it, and a subsystem keeping one across calls
    has a route that outlives the authorisation that produced it (ADR-0191 §3).
    """

    __slots__ = ()

    async def open_channel(self, endpoint: TransportEndpoint) -> ByteChannel:
        """Open a channel to ``endpoint``, and to nothing else.

        It performs no name resolution of its own beyond the host it was handed —
        there is no MX lookup here, so no recipient's domain selects the host a
        credential is presented to — follows no redirect or referral, and offers no
        way to reach a second host on one call (ADR-0191 §4).

        Args:
            endpoint: The host, port and TLS mode, already parsed. This method
                parses no string of its own.

        Returns:
            A connected channel, already under TLS where the endpoint's mode is
            the implicit one and verified against ``endpoint.host``.

        Raises:
            TransportError: If the endpoint could not be resolved or connected, or
                was connected and could not be verified. All three are converted
                from the standard library's own types so that every holder of the
                capability sees one taxonomy — the shared refusal type the
                canonical fake raises too — rather than ``asyncio``'s. A host
                carrying a control character is refused as one too, before
                anything resolves it (:func:`_truncating_character`).
            CancelledError: Re-raised after the release below, never absorbed.
        """
        offending = _truncating_character(endpoint.host)
        if offending is not None:
            # **The load-bearing half of the pin, and the last one before a
            # resolver sees the host** (:func:`_truncating_character`). This
            # method is the only route to ``getaddrinfo`` in ``src/``, so refusing
            # here closes the truncation for *every* endpoint however it was
            # built, not only for one this seam parsed. It is a ``TransportError``
            # because that is what this method raises for an endpoint it will not
            # connect (ADR-0191 §1), and it is raised before anything is acquired,
            # so there is nothing to release.
            #
            # The message names the code point and never the host: rendering a
            # host that carries a control character into a message is the
            # injection shape the rule exists over.
            msg = (
                f"the endpoint's host carries a control character at "
                f"U+{ord(offending):04X}, so it names a destination a resolver "
                f"would truncate"
            )
            raise TransportError(msg)
        # **Shielded, so a cancellation arriving here cannot orphan a connection.**
        # Without it there is a window ADR-0060 §1 forbids: the open completes,
        # this frame is scheduled to receive its streams, and a cancellation
        # delivered before it resumes leaves an established connection nobody
        # holds and nobody can close. The open is work this method started, so
        # this method observes it finishing and releases what it produced —
        # `_release_orphaned_streams` below. Adversarial and architecture review
        # both pressed on this window across rounds 2 to 4.
        try:
            context = _tls_context() if endpoint.implicit_tls else None
        except OSError as exc:
            # **Inside the taxonomy, because building the context touches the
            # file system.** ``ssl.create_default_context`` loads the trust store
            # and, where ``SSLKEYLOGFILE`` names an unusable path, opens that
            # too — so a deployment's environment can make this raise a raw
            # ``OSError`` before any socket exists. Constructing it in the
            # argument list left that outside every ``except`` below, which
            # adversarial review found on round 7.
            msg = f"the connection to {endpoint.host}:{endpoint.port} could not be secured"
            raise TransportError(msg) from exc
        opening = asyncio.ensure_future(
            asyncio.open_connection(
                endpoint.host,
                endpoint.port,
                ssl=context,
                server_hostname=endpoint.host if endpoint.implicit_tls else None,
                limit=TRANSPORT_OCTET_CEILING,
            )
        )
        try:
            reader, writer = await asyncio.shield(opening)
        except asyncio.CancelledError:
            # **Delivery is deferred until the release is done, and then the
            # cancellation is re-raised.** That order is ADR-0191 §1's, in as many
            # words — "releases what it acquired first", and "re-raises it after
            # the release" — and ADR-0060 §1's second clause is what permits the
            # deferral: "a method may defer delivery while it makes its resources
            # safe, but it re-raises". Both review lenses found round 5's shape
            # doing the opposite: a done-callback released *after* the caller
            # already held its cancellation, which is the orphan window read from
            # the caller's end rather than closed.
            #
            # The open itself is deliberately not cancelled. Cancelling it would
            # race its own establishment and leave *its* partial state to it,
            # whereas letting it finish gives this method one thing to observe and
            # one thing to close. So the wait is on work this method started and
            # can observe completing, and it is **unbounded** — stated as such,
            # which is the form ADR-0060 §1 requires. ADR-0029 §4's invocation
            # deadline is what bounds the call as a whole (ADR-0191 §2).
            #
            # A further cancellation arriving during that wait is suppressed and
            # the wait resumed: the caller's cancellation is already in hand and
            # is what leaves below, and abandoning the wait is the orphan again.
            while not opening.done():
                with suppress(asyncio.CancelledError):
                    await asyncio.wait((opening,))
            await _release_orphaned_streams(opening)
            raise
        except (OSError, UnicodeError) as exc:
            # ``ssl.SSLError`` is an ``OSError``, so a certificate that did not
            # verify arrives here too. ``UnicodeError`` is **not** — resolving a
            # host whose IDNA encoding fails (an empty or over-long label, a
            # zero-width joiner) raises one out of ``getaddrinfo``, and
            # ``parse_smtp_endpoint`` validates the authority no further than its
            # punctuation (#1158). Leaving that one through would break the
            # shared taxonomy for a host an operator can actually configure.
            #
            # Nothing reached this frame either way, so there is nothing to
            # release: the standard library closes what it opened before raising.
            msg = f"the endpoint {endpoint.host}:{endpoint.port} could not be connected"
            raise TransportError(msg) from exc
        try:
            return _StreamChannel(reader, writer, host=endpoint.host, secure=endpoint.implicit_tls)
        except BaseException:
            # **The release obligation, and it is not theatre.** No channel
            # reached the caller, so nothing else can ever release these streams
            # (ADR-0191 §1). A cancellation delivered here is re-raised after the
            # release rather than absorbed (ADR-0060 §1); an ordinary failure
            # constructing the channel takes the same path.
            await _release(writer)
            raise


async def _release(writer: asyncio.StreamWriter) -> None:
    """Give back streams no channel reached, and wait for the release to finish.

    **Both pre-return release paths go through here, and the guard is the point.**
    ``StreamWriter.close`` can raise on a transport that is already broken, and a
    release that raised would replace the exception in flight — turning the
    ``TransportError`` a failed establishment owes, or the caller's own
    ``CancelledError``, into an ``OSError`` from the cleanup. That is the same
    exception-replacement rule ADR-0191 §1 states for
    :meth:`~ai_assistant.core.protocols.ByteChannel.close`, applied where no
    channel exists to state it on. Adversarial review found both paths unguarded
    on round 5.

    **It waits for the release to complete, and an earlier shape did not.**
    ``StreamWriter.close`` only *starts* one: ``transport.close`` stops reading,
    flushes what is buffered and closes the socket from a later turn of the loop.
    So a caller that got its exception back the moment ``close`` returned held it
    while the connection was still up, which is ADR-0191 §1's "releases what it
    acquired first" read as an intention rather than as an order, and ADR-0060 §1
    read the same way. Architecture review found it on round 12 — and the
    asymmetry is what makes it right: :meth:`_StreamChannel.close` already defers
    delivery until its wait is done, and this is the path where *nothing else can
    ever release*, so it owed at least as much.

    **The abort is what keeps the wait bounded**, and is why the deferral here is
    not the unbounded one :meth:`_StreamChannel.close` documents. A plain close
    waits on a buffer draining to a far end that may never read again; ``abort``
    drops the transport without asking, so ``connection_lost`` — and with it the
    close waiter — is settled on the next turn of the loop. Nothing was written
    over these streams by anyone: no channel reached a holder, so there is no
    graceful close being cut short.

    Args:
        writer: The write half of a pair no holder received.

    Raises:
        CancelledError: If one was delivered *during* the release. It is deferred
            until the release has finished and then raised, replacing whatever
            exception this helper was called under — never dropped, which on the
            ordinary-failure path would report a broken endpoint for a caller that
            cancelled (ADR-0060 §1).
    """
    try:
        writer.close()
    except OSError as exc:
        _log.debug("egress_orphaned_streams_release_failed", error_type=type(exc).__name__)
        # **A close that raised may have raised before it released anything**, and
        # this is the last party that could ever give the socket back: no channel
        # reached a holder, so nothing else will try. ``abort`` is the harder
        # release the standard library keeps for exactly that — it drops the
        # transport without waiting on the far end. A failure from *it* is
        # suppressed on the same ground as the first: there is nothing further to
        # try, and raising would replace the exception in flight. Adversarial
        # review found the un-aborted path on round 6.
        with suppress(OSError):
            writer.transport.abort()
    else:
        # **Aborted on the ordinary path too, and for the wait rather than for the
        # close.** The close above has begun a graceful release of streams nobody
        # ever wrote over; what it does not do is finish one promptly, because a
        # far end that has stopped reading can hold the flush indefinitely. The
        # abort settles it on the next turn of the loop, which is what makes the
        # wait below bounded and therefore what makes waiting affordable at all.
        with suppress(OSError):
            writer.transport.abort()
    # **Then the release is waited out, and the exception in flight is delivered
    # after it.** The wait is on work this frame started — the writer's own close
    # waiter — and abandoning it is the orphan window reopened one turn later. So
    # a cancellation arriving during the wait defers rather than ends it.
    #
    # **Deferred is not absorbed, and this frame is the one that has to know the
    # difference.** ``_StreamChannel.close`` and ``open_channel``'s wait on the
    # open both run with a ``CancelledError`` already in flight, so a second one
    # swallowed there still leaves a cancellation to the caller. This helper does
    # not: it is also called while an ordinary ``TransportError`` is in flight,
    # where a swallowed cancellation would leave the caller told that the endpoint
    # broke when what happened is that the caller cancelled — ADR-0060 §1's
    # "delivered onward, never absorbed" broken by the cleanup path, which is what
    # adversarial review found on round 13. So the first one is kept and raised
    # once the release is done, replacing the exception it interrupted. The
    # *first*, on ``LoopSuspension.hold``'s reasoning: a caller cancelled twice
    # sees the cancellation it asked for rather than a later duplicate.
    waiting = asyncio.ensure_future(writer.wait_closed())
    cancellation: asyncio.CancelledError | None = None
    while not waiting.done():
        try:
            await asyncio.wait((waiting,))
        except asyncio.CancelledError as exc:
            cancellation = cancellation or exc
    if not waiting.cancelled():
        failure = waiting.exception()
        if isinstance(failure, OSError):
            # Retrieved *and* read, on ADR-0191 §1's "suppresses and logs": the
            # transport is already aborted, so there is nothing further to try,
            # and raising would replace the exception in flight.
            _log.debug("egress_orphaned_streams_release_failed", error_type=type(failure).__name__)
    if cancellation is not None:
        raise cancellation


async def _release_orphaned_streams(
    opened: asyncio.Future[tuple[asyncio.StreamReader, asyncio.StreamWriter]],
) -> None:
    """Close streams an open produced that its caller never received.

    Called by :meth:`StreamOutboundTransport.open_channel` once a cancellation has
    taken it off the open it was awaiting and that open has finished. Nothing else
    can ever release those streams — no channel reached a holder — so this is
    ADR-0060 §1's first clause at the one seam where it has bite.

    Args:
        opened: The finished open. A cancelled or failed one produced nothing to
            release; ``asyncio`` has closed whatever it had.
    """
    if opened.cancelled() or opened.exception() is not None:
        return
    _, writer = opened.result()
    await _release(writer)


def _truncating_character(host: str) -> str | None:
    r"""The first control character in ``host``, or ``None`` where there is none.

    **``getaddrinfo`` hands the host to a C library that stops at a ``NUL``**, so
    ``"127.0.0.1\x00mail.example.invalid"`` is one string to Python and two to the
    resolver: it resolves ``127.0.0.1``, a host the value does not name. Under the
    upgrade TLS mode that is a cleartext channel to the truncated destination;
    under implicit TLS the name a certificate is verified against is truncated the
    same way. Either breaks ADR-0191 §4's "opens a connection to the host and port
    of the ``TransportEndpoint`` it was handed", which is what #83 is about.
    Adversarial review found it reaching the opener on round 4.

    The rule is over control characters rather than over ``NUL`` alone: a bare
    ``\r`` or ``\n`` in a host is a header-injection shape wherever such a value is
    later written into a protocol line, and none of them is a host anything
    legitimate configures — a DNS name is letters, digits, hyphens and dots, and an
    IP literal is narrower still.

    **Enforced here rather than on the type**, at ADR-0154 §1's designated seam.
    An earlier shape put it in ``TransportEndpoint``'s own validators, where it was
    a refusal ADR-0191 §1 did not write: §1 marks exhaustiveness where it means it
    ("exactly three fields … and no others") and settles this type's construction
    rules itself, so a narrower accepted domain than the one it fixed is contract
    surface no ADR decided (golden rule 5). Architecture review found that on
    round 12. **No production path is lost by the move**: under ``src/`` the only
    thing that builds a ``TransportEndpoint`` is :func:`parse_smtp_endpoint`, and
    the only route to a resolver is
    :meth:`StreamOutboundTransport.open_channel` — both of which refuse it below.

    Args:
        host: The host to inspect.

    Returns:
        The first character whose Unicode category is ``Cc``, or ``None``.
    """
    return next((character for character in host if unicodedata.category(character) == "Cc"), None)


def parse_smtp_endpoint(endpoint: str) -> TransportEndpoint:
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
            A host :class:`~ai_assistant.core.types.TransportEndpoint` itself
            refuses arrives here as this type too, rather than as pydantic's —
            see the conversion below.
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
    # **The separator, carried rather than dropped.** ``rpartition`` puts the whole
    # authority in its *tail* when there is no separator, so the separator is the
    # only thing that tells "no port was written" apart from "a port was written
    # and is empty" — and ``_port`` was given the tail alone, which made
    # ``smtps://host:`` indistinguishable from ``smtps://host`` and defaulted it
    # (#1147). Only the second of the two is a port nobody wrote.
    written_port: str | None = port_text if colon else None
    if not colon:
        host = authority
    if not host or host.strip() != host:
        msg = "the bound transport endpoint names no host"
        raise TransportPinError(msg)
    if _truncating_character(host) is not None:
        # **The configured half of the pin** (:func:`_truncating_character`). The
        # message names neither the offending code point nor the host: this is
        # configuration rather than content, but it is still not this seam's to
        # render, and a control character reaching a log line is the injection
        # shape the rule exists over.
        msg = (
            "the bound transport endpoint names a host carrying a control "
            "character, which a resolver would truncate; it is refused before "
            "anything resolves it"
        )
        raise TransportPinError(msg)
    port = _port(written_port, scheme)
    parsed: TransportEndpoint | None = None
    try:
        parsed = TransportEndpoint(host=host, port=port, implicit_tls=scheme == "smtps")
    except ValidationError:
        parsed = None
    if parsed is None:
        # **What the type still refuses, kept in the seam's own taxonomy.**
        # ``TransportEndpoint``'s ``host`` is ``NonBlankEncodableText``, so text
        # with no UTF-8 encoding is refused there, which this grammar's
        # punctuation check does not see. (The control-character rule is the
        # clause above, at this seam, rather than on the type — see
        # :func:`_truncating_character`.)
        # A ``ValidationError`` escaping here would be the wrong type for a
        # refusal about a *binding* (ADR-0191 §4), and pydantic renders the input
        # it refused, so the endpoint an operator configured would reach whatever
        # caught it. The message below is written fresh for both reasons — and it
        # is raised **outside** the handler, with ``from None``, so the refused
        # value travels in neither ``__cause__`` nor ``__context__``. Chaining it
        # put the endpoint back into every formatted traceback, which is where
        # round 10 of adversarial review found it: a redaction the exception
        # chain undoes is not one.
        msg = (
            "the bound transport endpoint names a host this seam will not pin; "
            "text with no UTF-8 encoding is refused before anything resolves it"
        )
        raise TransportPinError(msg) from None
    return parsed


def _port(port_text: str | None, scheme: str) -> int:
    """Read the port the endpoint wrote, or this scheme's default.

    **The grammar is one to five ASCII decimal digits with no leading zero, naming
    a number in ``1..65535``** — which is every port, written exactly one way.
    ``port_text.isdigit()`` was the whole of it, and each clause added here closes
    a form it said yes to (#1147, the three cases ADR-0154 records against this
    function):

    - ``isdigit()`` is ``True`` for characters ``int()`` cannot read, so
      ``smtps://host:²`` escaped as a bare ``ValueError`` where every caller of
      this grammar is handling a refusal about a *binding* (ADR-0191 §4) — it
      reached the invoker as an internal fault rather than as a refusal.
    - ``isdigit()`` is equally ``True`` for digits ``int()`` reads perfectly well
      in another script, so a port written as two ARABIC-INDIC DIGIT FIVE
      (``U+0665``) was **accepted** as port 55 — a spelling that compares unequal
      to ``:55`` as text against the registration while opening the same port.
      ``isascii()`` closes both directions at once.
      A leading zero is that same fold inside ASCII, so ``:0465`` is refused
      rather than read as 465 — the grammar normalises a port exactly as much as
      it normalises a host, which is not at all (ADR-0148 §2's exactness default).

    Args:
        port_text: The text after the authority's last colon, or ``None`` where
            the authority carried no colon at all. ``""`` is therefore a port that
            was written and left empty, which is refused; ``None`` is a port
            nobody wrote, which takes the default.
        scheme: The endpoint's scheme, which supplies the default.

    Returns:
        A port in ``1..65535``.

    Raises:
        TransportPinError: If the port is present and is not such a number. An
            unreadable port is refused rather than defaulted, because defaulting
            would connect somewhere nobody wrote down.
    """
    if port_text is None:
        return _DEFAULT_PORTS[scheme]
    written_as_a_port_number = (
        port_text.isascii()
        and port_text.isdigit()
        and len(port_text) <= _MAX_PORT_DIGITS
        and not port_text.startswith("0")
    )
    if not written_as_a_port_number or not 1 <= int(port_text) <= _MAX_PORT:
        msg = "the bound transport endpoint's port is not a TCP port number"
        raise TransportPinError(msg)
    return int(port_text)


def _refuse_changed(message: str) -> BoundCallChangedError:
    """Build a refusal that renders nothing the ruling was taken over."""
    return BoundCallChangedError(message)


@final
class SmtpEgressTransport:
    """Transmit one bound egress call over SMTP, or refuse it (ADR-0148 §6).

    **Constructed in exactly one place, and only where a deployment configured an
    integration.** ADR-0154 §1 designates this seam, so this class now has a
    composition site — :func:`~ai_assistant.tools.builtin.build_send_email_integration`,
    the only one under ``src/ai_assistant``, which is issue #83's third bullet
    answered rather than assumed. A deployment that named no connected account and
    no endpoint builds none, registers no tool that could reach one, and opens
    nothing. The default connector is still the one function here that touches a
    socket, and a test always passes its own.

    What this class was originally *for* is unchanged, and is why a designation was
    possible at all: ADR-0017 §3's conditions 5, 8 and 12 are properties of code,
    and a designating ADR had to attest them against something.

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

    __slots__ = ("_records", "_registration", "_secrets", "_transport")

    def __init__(
        self,
        *,
        registration: EgressRegistration,
        records: ConnectionRecords,
        secrets: Secrets,
        transport: OutboundTransport,
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
            transport: The injected capability of reaching the world (ADR-0191
                §1). **Required, with no default and no ``None``-means-the-real-one
                fallback**, which is ADR-0191 §3's load-bearing clause: this
                argument used to default to the one function in ``tools`` that
                opened a socket, so production reached the world through a default
                argument and an object handed nothing had a route anyway. With the
                default gone, an object that was handed no transport cannot be
                constructed rather than being constructed with the real one — and
                a test asserting that no attempt was made is asserting that the
                route does not exist, rather than that a code path was not reached.
        """
        self._registration = registration
        self._records = records
        self._secrets = secrets
        self._transport = transport

    async def transmit(self, binding: EgressBinding, parameters: Mapping[str, FrozenJson]) -> None:
        """Send the bound call, or refuse without transmitting.

        **It takes the call's arguments, not a message somebody built from them,
        and that is the decision rather than a convenience.** An earlier signature
        accepted a rendered :class:`OutboundEmail` beside the binding and checked
        it against the description by *extent*. Adversarial review found on round 3
        that two texts of equal length are indistinguishable to such a check, so a
        message substituted after the ruling — same lengths, different words —
        passed every one of them. What is actually bound to the decision is
        ``ActionRequest.parameters``: ADR-0021 §1 binds them by
        ``parameters_digest``, ``authorises`` compares that digest, and ADR-0029 §2
        makes ``invoke`` re-run the comparison on a **revalidated, detached** copy
        before the callable is reached. ADR-0148 §4's third clause rests on exactly
        that chain and says a later lane "cannot satisfy it by re-deriving the set
        at the seam". So the message is derived here from the arguments that chain
        already protects, and there is no second, independently mutable payload for
        anyone to substitute.

        Args:
            binding: The egress binding the authorising decision carries, read
                back out of the trail by the executor (ADR-0037 §3). The account,
                the endpoint and the authorised destination set are taken from
                here and re-derived nowhere.
            parameters: The call's arguments, as ``invoke`` revalidated and
                detached them (ADR-0029 §2). The payload and the supplied
                recipient forms come from here, because these are what the
                decision's digest binds.

        Raises:
            TransportPinError: If the endpoint is not the configured one or is not
                a form this seam pins, or the far end declined TLS or answered
                with a forward path.
            BoundCallChangedError: If the reference is not connectable, the
                recorded identity is not the bound one, the record moved across
                the credential read, or the arguments do not yield the call the
                binding describes.
            IndeterminateTransmissionError: If the message was written and the
                server's verdict could not be read.
            ConnectionStoreError: If the **first** record read failed. A store
                outage asserts nothing about the call and is never converted; the
                *second* read is different, and an unanswerable one there is
                treated as a change.
        """
        # Every refusal that is decidable from the binding and the arguments alone
        # runs first, so a call that cannot be performed as bound never reaches a
        # credential read at all. ADR-0148 §6 is explicit that its clauses do not
        # guarantee that — "they do not guarantee that no credential is ever read
        # for a call that is then refused" — so this is strictly better than the
        # clause requires, and is here rather than in a docstring claiming a bound
        # nobody has.
        endpoint = self._pinned(binding)
        sender = self._sender(binding)
        message, recipients = self._authorised_message(binding, parameters)

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

    def _pinned(self, binding: EgressBinding) -> TransportEndpoint:
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

    def _authorised_message(
        self, binding: EgressBinding, parameters: Mapping[str, FrozenJson]
    ) -> tuple[OutboundEmail, tuple[str, ...]]:
        """Derive the message from the arguments and refuse it against the binding.

        The arguments carry **supplied** forms, because that is what a user typed
        and what ADR-0148 §2's fourth clause keeps in the record. The bound
        destination set carries **canonical** ones. So the supplied forms are put
        through the seam's own canonicaliser before the two are compared, which is
        both what makes the comparison meaningful and what ADR-0148 §2's sixth
        clause requires — one canonicaliser per protocol, so the answer here is the
        same answer the binder got. Adversarial review found on round 3 that
        comparing the raw argument against the canonical set refused a perfectly
        good call whose recipient was written in another case, and that the alias
        test had hidden it by pre-canonicalising its own input.

        Two refusals then follow, each the seam's half of a different clause. The
        recipient check is ADR-0148 §4's third clause — "the callable transmits to
        every member of the bound set and to no other recipient" — read as a set
        equality in **both** directions, so a member added after the ruling and a
        member silently dropped from it fail alike. The span check is §6's
        callable-side clause: "a callable that finds itself about to transmit a
        span the description does not cover refuses instead".

        Args:
            binding: The authorised binding.
            parameters: The revalidated arguments.

        Returns:
            The message with every recipient in its canonical form, and the
            envelope recipients deduplicated in argument order, which is what
            ``RCPT TO`` is issued for.

        Raises:
            BoundCallChangedError: If a recipient has no canonical form, or the
                recipients or the spans disagree with the binding.
        """
        supplied = smtp_message(parameters, tool_id=self._registration.tool_id)
        message = OutboundEmail(
            to=self._canonical(supplied.to),
            cc=self._canonical(supplied.cc),
            bcc=self._canonical(supplied.bcc),
            subject=supplied.subject,
            body=supplied.body,
        )
        bound = {
            member.canonical
            for member in binding.canonical_destination_set
            if member.protocol is DestinationProtocol.SMTP and member.canonical is not None
        }
        envelope = dict.fromkeys(message.recipients)
        if set(envelope) != bound:
            msg = (
                f"{self._registration.tool_id}: the call's {len(envelope)} envelope "
                f"recipient(s) are not the {len(bound)} member(s) of the bound "
                f"canonical destination set. The set is authorised whole and a "
                f"member is never added, dropped or substituted after the ruling "
                f"(ADR-0148 §4)"
            )
            raise _refuse_changed(msg)
        self._check_spans_cover(binding, supplied)
        return message, tuple(envelope)

    def _canonical(self, supplied: Sequence[str]) -> tuple[str, ...]:
        """Every supplied recipient in the one canonical form this seam computes.

        Args:
            supplied: Recipients as the arguments carry them.

        Returns:
            Their canonical forms, in the same order.

        Raises:
            BoundCallChangedError: If any has no canonical form. That cannot
                happen on the ordinary path — the binder refuses such a call
                before the ruling (ADR-0148 §1's third clause) — which is exactly
                why it is checked here too: "a request built by a bypass reaches
                the seam" (ADR-0145 §3).
        """
        try:
            return tuple(canonicalise(SeamProtocol.SMTP, form).canonical for form in supplied)
        except DestinationCanonicalisationError as exc:
            msg = (
                f"{self._registration.tool_id}: an argument names a recipient this "
                f"seam will not canonicalise, so it cannot be compared against the "
                f"bound destination set and nothing is transmitted (ADR-0148 §2)"
            )
            raise _refuse_changed(msg) from exc

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
        endpoint: TransportEndpoint,
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
        channel = await self._transport.open_channel(endpoint)
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


def smtp_message(parameters: Mapping[str, FrozenJson], *, tool_id: str) -> OutboundEmail:
    """Read an SMTP submission out of a call's arguments, or refuse them.

    **The five fields are SMTP's, not an integration's**, which is what keeps this
    inside the seam rather than making the seam know a particular tool's schema: a
    submission has an envelope, a subject and a body, and a transport that spoke
    some other vocabulary would be a transport for some other protocol. An
    integration that wants different argument *names* maps them before it reaches
    here; what it may not do is hand over a payload this seam did not derive from
    the arguments the decision's digest binds (:meth:`SmtpEgressTransport.transmit`).

    Every refusal here is a defect in the caller rather than a state a user can
    reach: ADR-0145 checks the arguments against the tool's schema at construction,
    before the ruling. It is checked again because "a request built by a bypass
    reaches the seam" (ADR-0145 §3), which is ADR-0029 §2's revalidation posture
    and the reason this function is total over any mapping at all.

    Args:
        parameters: The call's revalidated arguments.
        tool_id: Named in the refusal, and the only identifier that is.

    **A recipient argument may arrive as a string or as a list of them**
    (ADR-0157 §1), because that is what a destination-bearing argument may now
    declare. A string is read as the one recipient it names: SMTP's envelope takes
    a list either way, so the alternative would be a transport refusing a call the
    binder admitted and the ruling authorised.

    Returns:
        The message, with recipients in the **supplied** forms the arguments carry.

    Raises:
        BoundCallChangedError: If a key is one this seam does not transmit, a
            recipient argument is neither a string nor a list of strings, a text
            field is not a string, a header field carries a line break, or no
            recipient is named. The message renders no value, because every one of
            them is either a recipient or payload content.
    """
    unknown = set(parameters) - {"to", "cc", "bcc", "subject", "body"}
    if unknown:
        msg = (
            f"{tool_id}: the call carries {len(unknown)} argument(s) this seam does "
            f"not transmit, so a span could reach the wire that no description "
            f"covers (ADR-0148 §6)"
        )
        raise _refuse_changed(msg)
    recipients: dict[str, tuple[str, ...]] = {}
    for field in ("to", "cc", "bcc"):
        supplied = parameters.get(field, ())
        # ADR-0157 §1: a recipient argument may declare both flat forms, so a
        # string arrives here as readily as a list. It is canonicalised to the
        # one-element list SMTP's envelope needs, which is a **rendering** of an
        # already-authorised call rather than a re-derivation of one — the
        # arguments reach this seam exactly as the decision's digest binds them,
        # and what varies is how the message is built from them (ADR-0148 §4).
        value = (supplied,) if isinstance(supplied, str) else supplied
        if not isinstance(value, tuple | list) or not all(isinstance(one, str) for one in value):
            msg = (
                f"{tool_id}: the {field!r} argument is neither a recipient address "
                f"nor a list of recipient addresses"
            )
            raise _refuse_changed(msg)
        recipients[field] = tuple(str(one) for one in value)
    texts: dict[str, str] = {}
    for field in ("subject", "body"):
        text = parameters.get(field, "")
        if not isinstance(text, str):
            msg = f"{tool_id}: the {field!r} argument is not text"
            raise _refuse_changed(msg)
        if field in _HEADER_TEXT_FIELDS and ("\r" in text or "\n" in text):
            msg = (
                f"{tool_id}: the {field!r} argument carries a line break, which ends "
                f"a header and begins another, so it is refused before anything is "
                f"spent on the call (ADR-0148 §1)"
            )
            raise _refuse_changed(msg)
        texts[field] = text
    if not recipients["to"] and not recipients["cc"] and not recipients["bcc"]:
        msg = f"{tool_id}: the call names no recipient, so there is nothing to send it to"
        raise _refuse_changed(msg)
    return OutboundEmail(
        to=recipients["to"],
        cc=recipients["cc"],
        bcc=recipients["bcc"],
        subject=texts["subject"],
        body=texts["body"],
    )


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

                **``OSError`` and ``TransportError`` are caught here and
                nowhere else in this class, and the asymmetry is the decision.**
                ADR-0191 §4 requires this catch to cover the capability's own
                refusal type as well as the standard library's, for the identical
                reason: a channel that stopped answering after the terminator was
                written says nothing about what the far end did with the octets,
                whichever type it says it in. Everywhere before the payload is
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
        # The write is **inside** the window, not before it. A stream writer hands
        # octets to the transport and only then awaits the flush, so a failure
        # raised by that flush does not establish that nothing was sent — and no
        # channel this seam could be handed is able to establish it either, which
        # is why the answer is the conservative one rather than a narrower test.
        try:
            await self._channel.write(_dot_stuffed(payload))
            code, _ = await self._reply()
        except (EgressTransportError, TransportError, OSError) as exc:
            msg = (
                f"{self._tool_id}: the message reached the transport and the "
                f"endpoint's verdict could not be read, so whether it was accepted "
                f"is unknown"
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
        except (EgressTransportError, TransportError, OSError) as exc:
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
        :data:`~ai_assistant.core.types.TRANSPORT_OCTET_CEILING` while the reply
        never terminates, so a far
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
    "EgressTransportError",
    "IndeterminateTransmissionError",
    "OutboundEmail",
    "SmtpEgressTransport",
    "StreamOutboundTransport",
    "TransportPinError",
    "parse_smtp_endpoint",
    "smtp_message",
]
