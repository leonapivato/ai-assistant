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
import string
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


# --- The HTTPS exchange (ADR-0231 §5) --------------------------------------- #
# **Built here, over the injected byte channel, and deliberately not an HTTP
# client library.** ADR-0191 §2 fixes :class:`~ai_assistant.core.protocols.
# ByteChannel` as "deliberately **not** an HTTP client: it carries no URL, no
# request or response model, no redirect handling and no notion of a method or a
# header, and a protocol — SMTP, HTTP, JSON-RPC or anything else — is built on top
# of it by the module that holds it and never inside the capability". This is that
# protocol for HTTP/1.1, in the one module ADR-0154 §1 designates, and ADR-0231 §5
# is what commissions it: "The transport is an **HTTPS exchange built inside that
# module**, over the injected ``OutboundTransport`` ADR-0191 §1 contracts".
#
# **No dependency is adopted, because the ADR adopts none.** §5 says in terms that
# "This ADR authorises no dependency and chooses none", so ADR-0147 §3's
# import-linter contract is unchanged and its forbidden set gains nothing. A later
# lane that does adopt one extends that set in the same change, which is what §5's
# own clause already requires of "any lane adding a transport-bearing dependency".


class HttpsExchangeError(ToolError):
    """This seam's HTTPS exchange will not hand back a response it read.

    **Not an** :class:`EgressTransportError`, and the split is the same one
    :class:`IndeterminateTransmissionError` is on the other side of. Every member
    of that hierarchy "is raised **before any byte of the payload reached the
    wire**", and for a search the payload *is* the query: the request carrying it
    is written before any of these can be raised, so calling one of them a refusal
    that transmitted nothing would be false.

    **It is not** :class:`IndeterminateTransmissionError` **either, and for a
    reason about the far end rather than about this class.** That type exists
    because an SMTP message may or may not have been accepted, and ADR-0014 §4's
    recovery scan is the reconciliation path for the difference. A search changes
    nothing at the far end — ADR-0231 §5 decides ``reversibility=REVERSIBLE`` on
    exactly that ground, "a search is a **read** of a remote index: nothing at the
    far end changes" — so there is no effect to reconcile. What did happen, in
    every case below, is that the query was disclosed; that is carried by the
    declaration's ``discloses`` and by the ruling, not by an exception class.

    **No message any of these raises renders a credential, a header value, a
    request target or a byte of a response body.** It may name a status code, a
    count, a bound and a rule. That is :class:`EgressTransportError`'s discipline
    applied to the neighbouring surface, and it matters more here: a response body
    is a third party's text, and a refusal message reaches a log.
    """


class HttpsRedirectRefusedError(HttpsExchangeError):
    """The far end answered with a redirect, which is a refusal (ADR-0231 §5).

    "It **follows no redirect** — a redirect response is a refusal and never a
    second request." This is #83's own failure written for the protocol that has
    it: a client that followed one would carry the account's credential to a host
    no ruling named and no grant covered. SMTP's analogue is RFC 5321 §3.4's
    forward-path replies, which :class:`SmtpEgressTransport` refuses the same way.

    Raised **after** the status line has been read and **before** anything else is
    done with the response: no ``Location`` is parsed, no second endpoint is
    derived, no second channel is opened, and the one channel is closed on the way
    out.
    """


class HttpsResponseTooLargeError(HttpsExchangeError):
    """The response passed ``search_max_response_bytes`` and was abandoned (§5).

    ADR-0231 §5: "The response bound is enforced **while the response is read and
    before any part of it is parsed**, counted over the bytes taken off the
    channel. A response **over** the bound is **abandoned and refused** — the read
    stops as soon as one byte past the bound has been taken, the channel is closed,
    nothing is parsed and no record is minted — while a response **exactly at** the
    bound is read whole and parsed."

    That is a property of :class:`_BoundedReader`, which never asks the channel for
    more than the allowance plus one octet, rather than of a check somewhere: an
    implementation that read to end of stream and then compared a length would
    satisfy the sentence and not the rule, and is the thing §5's last clause names.
    """


class MalformedHttpResponseError(HttpsExchangeError):
    """The far end did not answer in the shape HTTP/1.1 documents (ADR-0231 §5).

    A status line that is not one, a header line with no field name, a framing this
    exchange will not read — two ways of declaring a body's length at once, a
    transfer coding other than ``chunked``, a chunk size that is not hexadecimal —
    or a stream that ended in the middle of any of them.

    **This is the transport half of ADR-0231 §10's "a response whose top-level
    shape is not the one the provider documents".** The other half is the
    provider's own payload format, which this exchange does not parse at all: it
    hands back the body's octets and decodes none of them, so which JSON shape a
    provider documents — and what a response failing it costs — is the searcher's
    (ADR-0231 §17's Lane 3).
    """


#: The scheme an HTTPS origin names, in the one case ADR-0231 §8 renders it in.
HTTPS_SCHEME: Final = "https"

#: The port the ``Host`` header omits, RFC 9110 §4.2.2's default for the scheme.
#: It is written into the header only where the endpoint is on some other port,
#: which is what every ordinary client does and what a virtual host expects.
_HTTPS_DEFAULT_PORT: Final = 443

#: HTTP/1.1's line terminator (RFC 9112 §2.2), and the terminator this exchange
#: both writes and requires. A bare ``\n`` is not one: reading it as a line ending
#: is the leniency request smuggling is built out of, and this seam refuses the
#: response rather than guessing at where a far end meant a line to end.
_CRLF: Final = b"\r\n"

#: The versions this exchange will read a reply in. HTTP/2 and HTTP/3 are not
#: line-framed at all and could not arrive here; a far end answering ``HTTP/0.9``
#: sends no status line, which the status-line parse refuses on its own terms.
_HTTP_VERSIONS: Final = frozenset({b"HTTP/1.0", b"HTTP/1.1"})

#: The lowest and highest status codes RFC 9110 §15 defines a class for. A
#: three-digit number outside them is not a status this seam will act on.
_MIN_STATUS: Final = 100
_MAX_STATUS: Final = 599

#: RFC 9110 §15.4's redirection class, which ADR-0231 §5 makes a refusal.
_MIN_REDIRECT: Final = 300
_MAX_REDIRECT: Final = 399

#: RFC 9112 §6.3: a response with one of these statuses "is always terminated by
#: the first empty line after the header fields, **regardless of the header fields
#: present** in the message". A ``1xx`` is in that list too and never reaches the
#: body reader, since :meth:`HttpsExchange._response` refuses an interim status
#: outright, so these two are the whole of it here. Adversarial review found a
#: ``204`` carrying a ``Content-Length`` being read as provider payload on round 3.
_NO_CONTENT_STATUSES: Final = frozenset({204, 304})

#: The first class RFC 9110 §15.2 defines, which is *interim*: a client is meant
#: to keep reading for the real response. This exchange sends no ``Expect``, so a
#: conforming far end sends none — and reading one would mean a second response on
#: one channel, so it is refused as a shape rather than looped over.
_MAX_INTERIM_STATUS: Final = 199

#: The characters a request target may hold: printable ASCII excluding space
#: (RFC 3986's whole character repertoire). A space, a control character or any
#: non-ASCII octet is refused before a channel is opened, because each of them is
#: a request-line injection and none of them is a target anything legitimate
#: composes — a target is percent-encoded by the integration that built it.
_TARGET_CHARACTERS: Final = frozenset(chr(code) for code in range(0x21, 0x7F))

#: RFC 9110 §5.6.2's ``token``, which a header field name is. Checked so that a
#: name carrying a separator — a colon above all — cannot write a second field.
_FIELD_NAME_CHARACTERS: Final = frozenset(string.ascii_letters + string.digits + "!#$%&'*+-.^_`|~")

#: What a header field value may hold: printable ASCII, plus space and horizontal
#: tab, which RFC 9110 §5.5 admits inside a value. ``CR`` and ``LF`` are excluded,
#: which is the whole point — a value carrying either writes a field this seam did
#: not, and the credential travels in one of these values.
_FIELD_VALUE_CHARACTERS: Final = _TARGET_CHARACTERS | {" ", "\t"}

#: The header fields this exchange writes itself, and which a caller therefore may
#: not supply. Two of them frame the response and one names the recipient: a
#: caller able to write a second ``Host`` would be selecting a virtual host the
#: ruling never saw, and one able to write a ``Content-Length`` or a
#: ``Transfer-Encoding`` would be framing a request body this exchange does not
#: send. ``Connection`` is here because ADR-0191 §3's per-call channel is not a
#: thing a caller may ask to keep alive.
_RESERVED_FIELD_NAMES: Final = frozenset(
    {"host", "connection", "content-length", "transfer-encoding"}
)

#: The most decimal digits a ``Content-Length`` may be written in. ``Settings``
#: bounds ``search_max_response_bytes`` below ``2**63``, so a length needing more
#: digits than that names no response any configured bound could read whole. It is
#: checked **before** the conversion for :func:`_port`'s reason (#1147): CPython
#: refuses ``int()`` on a string of more than 4300 digits, so a header of five
#: thousand ASCII digits would otherwise satisfy every character test and raise a
#: bare ``ValueError`` out of the conversion — an exception no ``Raises`` block on
#: this path declares, arriving from a far end that chose the header's length.
#: Adversarial review found it on round 1.
_MAX_CONTENT_LENGTH_DIGITS: Final = len(str(2**63 - 1))

#: The most hexadecimal digits a chunk size may be written in. ``int(text, 16)``
#: on a very long string is the same denial-of-service ``_MAX_PORT_DIGITS`` closes
#: for a port (#1147), and no chunk this exchange could accept needs more: the
#: response bound is a 64-bit quantity at most.
_MAX_CHUNK_SIZE_DIGITS: Final = 16

#: ASCII hexadecimal digits, for the chunk-size grammar. ``int(text, 16)`` is
#: itself far more permissive than the grammar — it accepts a sign, surrounding
#: whitespace and ``_`` separators, so ``int(b"1_0", 16)`` is 16 — which is why
#: the text is checked before it is converted rather than after.
_HEX_DIGITS: Final = frozenset(string.hexdigits)


@final
@dataclass(frozen=True, slots=True)
class HttpsResponse:
    """One HTTPS response, as this seam read it off a channel it opened.

    Frozen and slotted for the reason every value at this seam is: what a caller
    acts on must not be something a later holder can rewrite.

    **The body is octets and is decoded by nothing here.** ADR-0231 §10 makes the
    provider's payload format the searcher's business, and a transport that
    decoded it would be the second place a response's shape is decided.

    Attributes:
        status: The three-digit status the far end sent, in ``100..599``. Never a
            redirect: :class:`HttpsRedirectRefusedError` is raised instead of one
            being returned (ADR-0231 §5).
        headers: Every field the far end sent, in the order it sent them, with the
            name ASCII-lowercased and the value's surrounding whitespace stripped
            as RFC 9110 §5.5 directs. Carried rather than interpreted: this
            exchange reads only the two that frame the body, and what a
            ``reported_at`` is read from is ADR-0231 §10's question.
        body: The payload's octets, exactly as they arrived, with any chunked
            framing removed. Its length is bounded by construction: the whole
            response, this field included, took at most
            ``search_max_response_bytes`` off the channel.
    """

    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes


class _BoundedReader:
    """Reads a response off a channel, taking at most one octet past the bound.

    ADR-0231 §5's read bound as a property of the reader rather than as a check
    after the fact: every fill asks the channel for **the allowance plus one**, so
    the count of octets taken can reach ``bound + 1`` and can never exceed it. The
    moment it does, the read stops and :class:`HttpsResponseTooLargeError` is
    raised — before the octets that carried it past the bound are looked at.

    The plus-one is what makes the boundary decidable rather than approximate: a
    response of exactly ``bound`` octets is read whole and then answers end of
    stream, while one of ``bound + 1`` is stopped on the octet that made it so.

    **The count is over every octet taken off the channel**, the status line and
    the headers included, which is §5's "counted over the bytes taken off the
    channel" read as it is written. It is not a body bound with a header allowance
    beside it, and nothing here subtracts one from the other.

    **Framing is read incrementally, and that is §5 as written rather than against
    it.** §5 says the bound is enforced "while the response is read and before any
    part of it is parsed", and its last clause says what that rules out: "No
    implementation buffers a whole response, parses incrementally past the bound,
    or measures a response after assembling it." All three are properties of this
    reader. Nothing is parsed **past** the bound, because the fill that would pass
    it raises before its octets reach the buffer; nothing is measured after
    assembly, because the count is taken on the read; and nothing buffers a whole
    response, which is the clause a "read it all, then parse" implementation would
    breach — and it could not be satisfied anyway for the close-framed response
    this exchange's own ``Connection: close`` asks for, whose length is not knowable
    without reading to end of stream. What §5's "nothing is parsed" buys is that an
    over-bound response yields **no value at all**: no :class:`HttpsResponse` is
    returned, no body reaches a decoder, and no record can be minted from it.
    Reading the status line and the field section is what tells this reader where
    the body ends, so it is the bound being enforced rather than a step ahead of it
    (adversarial round 1 read the clause the other way; the direction it gave is
    the clause's own first prohibition).
    """

    __slots__ = ("_bound", "_buffer", "_channel", "_ended", "_taken")

    def __init__(self, channel: ByteChannel, *, bound: int) -> None:
        """Read ``channel`` under ``bound``.

        Args:
            channel: The channel the response arrives on.
            bound: ``search_max_response_bytes``, in octets.
        """
        self._channel = channel
        self._bound = bound
        self._buffer = bytearray()
        self._taken = 0
        self._ended = False

    @property
    def taken(self) -> int:
        """How many octets have been taken off the channel so far.

        Returns:
            The count, which never exceeds the bound by more than one.
        """
        return self._taken

    async def _fill(self) -> bool:
        """Take one more chunk off the channel.

        Returns:
            Whether anything arrived. ``False`` means end of stream, and the
            channel is not read again.

        Raises:
            HttpsResponseTooLargeError: If the chunk took the count past the bound.
            TransportError: If the connection could not be continued (ADR-0191 §1).
        """
        if self._ended:
            return False
        allowance = self._bound - self._taken + 1
        chunk = await self._channel.read(min(allowance, TRANSPORT_OCTET_CEILING))
        if not chunk:
            self._ended = True
            return False
        self._taken += len(chunk)
        if self._taken > self._bound:
            # Stopped **on** the octet that passed the bound, before this chunk is
            # put in the buffer and so before any part of it could be read. The
            # buffer is abandoned with it; the caller closes the channel.
            msg = (
                f"the response passed the {self._bound}-byte bound this seam reads "
                f"under; it was abandoned unparsed (ADR-0231 §5)"
            )
            raise HttpsResponseTooLargeError(msg)
        self._buffer += chunk
        return True

    async def line(self) -> bytes:
        """The next CRLF-terminated line, without its terminator.

        Returns:
            The line's octets. An empty result is the empty line that ends a
            header section, not end of stream — a stream that ends where a line
            was expected is a malformed response and is raised over.

        Raises:
            MalformedHttpResponseError: If the stream ended before a terminator.
            HttpsResponseTooLargeError: If reading it passed the bound.
            TransportError: If the connection could not be continued.
        """
        while True:
            found = self._buffer.find(_CRLF)
            if found >= 0:
                line = bytes(self._buffer[:found])
                del self._buffer[: found + len(_CRLF)]
                return line
            if not await self._fill():
                msg = "the far end ended the stream in the middle of a response line"
                raise MalformedHttpResponseError(msg)

    async def take(self, count: int) -> bytes:
        """Exactly ``count`` octets.

        Args:
            count: How many to take, which a far end's own declared length or
                chunk size supplies. A count larger than the bound is not
                special-cased: the fill that would pass the bound refuses first,
                so nothing is allocated for it.

        Returns:
            The octets.

        Raises:
            MalformedHttpResponseError: If the stream ended first.
            HttpsResponseTooLargeError: If reading them passed the bound.
            TransportError: If the connection could not be continued.
        """
        while len(self._buffer) < count:
            if not await self._fill():
                msg = "the far end ended the stream before the length it declared"
                raise MalformedHttpResponseError(msg)
        taken = bytes(self._buffer[:count])
        del self._buffer[:count]
        return taken

    async def rest(self) -> bytes:
        """Everything up to end of stream.

        Returns:
            The remaining octets.

        Raises:
            HttpsResponseTooLargeError: If reading them passed the bound.
            TransportError: If the connection could not be continued.
        """
        while await self._fill():
            pass
        remaining = bytes(self._buffer)
        self._buffer.clear()
        return remaining


def parse_https_origin(origin: str) -> TransportEndpoint:
    """The endpoint a channel to ``origin`` is opened to (ADR-0231 §5, §8).

    **One grammar, and it is the canonicaliser's.** The origin is put through
    :func:`~ai_assistant.tools.destinations.canonicalise` and the endpoint is split
    out of the **canonical** form, which is ``https://host:port`` by construction —
    so this function parses a string this seam itself produced and never a supplied
    one. A second grammar here is exactly ADR-0148 §2's sixth clause forbids, and
    it is how a destination the ruling compared one way comes to be connected to
    another (#83, #1158).

    **No control-character check of its own**, deliberately: ADR-0231 §8's host
    grammar admits only ASCII letters, digits, ``-`` and ``.``, so the truncating
    character :func:`_truncating_character` exists for cannot survive
    canonicalisation, and :meth:`StreamOutboundTransport.open_channel` applies that
    rule again on the one path to a resolver. A third copy would be a rule with
    three homes and no single one to read.

    Args:
        origin: A supplied HTTPS origin, in any form ADR-0231 §8 canonicalises.

    Returns:
        The endpoint, always with ``implicit_tls`` — HTTPS is TLS from the first
        octet and this seam has no cleartext form, exactly as ``smtps`` has none.

    Raises:
        TransportPinError: If ``origin`` is not a form this seam will canonicalise,
            and so not one it will pin. The message states the rule that was broken
            and never the origin: the canonicaliser's refusals name no value (see
            :mod:`ai_assistant.tools.destinations`), which is what makes
            interpolating one safe here as it is in ``tools/egress_binder.py``.
    """
    try:
        canonical = canonicalise(SeamProtocol.HTTPS, origin).canonical
    except DestinationCanonicalisationError as exc:
        msg = f"the origin has no canonical form, so this seam will not pin it — {exc}"
        raise TransportPinError(msg) from exc
    host, _, port = canonical.removeprefix(f"{HTTPS_SCHEME}://").rpartition(":")
    return TransportEndpoint(host=host, port=int(port), implicit_tls=True)


@final
class HttpsExchange:
    """One HTTPS request per call, to one origin, over the injected transport.

    ADR-0231 §5's five properties, each of which is a property of this class's
    shape rather than of a check inside it:

    1. **One origin.** :meth:`get` derives its endpoint from the origin it is
       given through :func:`parse_https_origin`, hands it to
       :meth:`~ai_assistant.core.protocols.OutboundTransport.open_channel`, and
       has no other way to reach a host — ADR-0191 §1's "its shape is what pins the
       destination". No caller-supplied header may name a ``Host``.
    2. **No redirect.** A ``3xx`` is :class:`HttpsRedirectRefusedError` and the
       method returns; there is no loop, no ``Location`` read and no second
       :meth:`open_channel` call anywhere in this class.
    3. **A channel per call.** :meth:`get` opens one and closes it in a ``finally``,
       and this object's ``__slots__`` hold no channel, no pool and no cache
       (ADR-0191 §3). A second call opens a second channel.
    4. **The credential to that origin and nothing else.** The credential rides in
       a caller-supplied header, which is written to the channel this call opened
       and to nothing else — and only after :attr:`ByteChannel.is_secure` reads
       ``True``, which is read from the channel's own state rather than inferred
       from the endpoint having asked for TLS. Since nothing is written before that
       check, a channel that somehow arrived in the clear carries no credential.
    5. **The read bound.** :class:`_BoundedReader`, above.

    **It reads a credential from nowhere and holds none.** ADR-0231 §5 puts the
    ``Secrets`` read inside ``WebSearcher.search``, after its three checks; this
    object is handed the header that carries the result and never the face that
    would produce one.

    **A GET, and no other method.** ADR-0231 §5 leaves "which path, which parameter
    names, which headers and which body shape a provider request takes" to the
    integration, and this exchange narrows the last of those to *none*: a search is
    a read of a remote index, which is the ground §5 gives for
    ``reversibility=REVERSIBLE``, and a seam able to send a body is a seam able to
    write. A later lane needing a body-bearing search endpoint widens this
    deliberately rather than by default (issue filed alongside this change).

    **Nothing constructs one yet.** ADR-0231 §17's Lane 2 is a transport nothing
    drives, "reviewable against a real exchange before anything is minted"; the
    searcher that drives it, its declaration and its registration are Lane 3's.
    """

    __slots__ = ("_bound", "_transport")

    def __init__(self, *, transport: OutboundTransport, max_response_bytes: int) -> None:
        """Bind an exchange to the capability it reaches the world through.

        Args:
            transport: The injected capability (ADR-0191 §1). **Required, with no
                default and no ``None``-means-the-real-one fallback** — ADR-0191
                §3's load-bearing clause, for :class:`SmtpEgressTransport`'s
                reason: an object handed no transport cannot be constructed rather
                than being constructed with the real one.
            max_response_bytes: ``Settings.search_max_response_bytes``. Passed in
                rather than read here, because a seam reading configuration is a
                second place a bound is decided.

        Raises:
            ValueError: If ``max_response_bytes`` is below 1. ``Settings`` refuses
                that at load (ADR-0231 §5), and this states the same rule at the
                one place a bound of zero would silently mean "refuse everything".
        """
        if max_response_bytes < 1:
            msg = f"max_response_bytes is an integer of at least 1; got {max_response_bytes}"
            raise ValueError(msg)
        self._transport = transport
        self._bound = max_response_bytes

    async def get(
        self, *, origin: str, target: str, headers: Sequence[tuple[str, str]] = ()
    ) -> HttpsResponse:
        """Fetch ``target`` from ``origin``, or refuse.

        The order is the decision rather than an implementation detail:

        1. The origin is canonicalised and pinned, and the target and every header
           are checked, **before a channel is opened** — so a request that could
           not be made spends no connection and discloses nothing (ADR-0148 §1's
           third clause, ADR-0145's precedent).
        2. The channel is opened to that endpoint and to nothing else.
        3. :attr:`ByteChannel.is_secure` is read, and nothing is written unless it
           is ``True``.
        4. The request is written, whole, in one write.
        5. The response is read under the bound, and a redirect is refused.
        6. The channel is closed, on every path out including a cancellation.

        Args:
            origin: The recipient, in any form ADR-0231 §8 canonicalises. This is
                the value a ruling and a grant range over.
            target: The origin-form request target — a path, with a query where
                there is one, already percent-encoded by whoever composed it. It
                begins with ``/`` and holds only printable ASCII other than space.
            headers: The fields to send, in order, as name-value pairs. Names are
                compared case-insensitively against the four this exchange writes
                itself and are refused where they collide. The credential rides
                here where the integration's provider takes one.

        Returns:
            The response, whose ``status`` is never a redirect.

        Raises:
            TransportPinError: If ``origin`` is not a form this seam will pin, if
                ``target`` is not an origin-form target, or if a header is not one
                this exchange will write. Every one of these is raised **before**
                a channel is opened, so nothing was disclosed.
            HttpsRedirectRefusedError: If the far end answered ``3xx``.
            HttpsResponseTooLargeError: If the response passed the bound.
            MalformedHttpResponseError: If it was not an HTTP/1.1 response this
                exchange will read.
            TransportError: If the channel could not be opened, could not be
                verified, or could not be continued (ADR-0191 §1). It is declared
                rather than converted: what it says is what happened to the
                *connection*, which is the capability's subject and not this
                seam's to restate (#1604 names the omission this avoids).
            CancelledError: Re-raised after the channel is released (ADR-0060 §1).
        """
        endpoint = parse_https_origin(origin)
        request = self._request(endpoint, target=target, headers=headers)
        channel = await self._transport.open_channel(endpoint)
        try:
            if not channel.is_secure:  # pragma: no cover — no conforming transport
                # Read from the channel's own state rather than inferred from the
                # endpoint having asked for implicit TLS, which is the distinction
                # ADR-0191 §1 states `is_secure` exists for. Nothing has been
                # written, so the credential in `headers` has not travelled.
                #
                # **Unreachable through a conforming transport, and stated rather
                # than asserted for `_occurrence`'s reason** (``egress_binder.py``):
                # ADR-0191 §1 requires ``open_channel`` to return a channel
                # "already under TLS where ``endpoint.implicit_tls`` is ``True``",
                # and :class:`~ai_assistant.testing.FakeOutboundTransport` refuses
                # to hand out one that is not — so no case here can drive it. But
                # the transport is an **injected** Protocol, a type checker cannot
                # see the clause, and a guard whose failure mode is a credential on
                # a cleartext channel is not one to leave to a contract somebody
                # else implements.
                msg = (
                    "the channel to the origin is not under TLS, so nothing was "
                    "written to it; this seam has no cleartext form"
                )
                raise TransportPinError(msg)
            await channel.write(request)
            return await self._response(channel)
        finally:
            await channel.close()

    def _request(
        self, endpoint: TransportEndpoint, *, target: str, headers: Sequence[tuple[str, str]]
    ) -> bytes:
        """Render the request line, the fields this exchange owns, and ``headers``.

        **Every refusal here happens before a channel exists**, which is what makes
        them refusals rather than outcomes. The character sets are the whole of the
        injection defence: a target or a value carrying ``CR`` or ``LF`` would
        write a request line or a field this seam did not compose, and the
        credential travels in one of these values.

        Args:
            endpoint: The endpoint the channel will be opened to, which supplies
                the ``Host`` field.
            target: The origin-form request target.
            headers: The caller's fields, in order.

        Returns:
            The request's octets, terminated by the empty line that ends the field
            section. There is no body: this exchange sends none.

        Raises:
            TransportPinError: If the target or a field is not one this exchange
                will write.
        """
        if not target.startswith("/") or any(
            character not in _TARGET_CHARACTERS for character in target
        ):
            msg = (
                "the request target is an origin-form path beginning with '/' and "
                "holding only printable ASCII other than space; it is refused "
                "rather than encoded, and the value is not named"
            )
            raise TransportPinError(msg)
        lines = [f"GET {target} HTTP/1.1"]
        authority = (
            endpoint.host
            if endpoint.port == _HTTPS_DEFAULT_PORT
            else f"{endpoint.host}:{endpoint.port}"
        )
        lines.append(f"Host: {authority}")
        # ADR-0191 §3's per-call channel, said to the far end as well as held to
        # here: nothing is pooled, so a far end keeping the connection alive would
        # be holding a route this seam has no intention of using again — and where
        # the response declares no length, the close is what frames it.
        lines.append("Connection: close")
        for name, value in headers:
            self._check_field(name, value)
            lines.append(f"{name}: {value}")
        return _CRLF.join(line.encode("ascii") for line in [*lines, "", ""])

    def _check_field(self, name: str, value: str) -> None:
        """Refuse a field this exchange will not write.

        Args:
            name: The field name, in any case.
            value: The field value.

        Raises:
            TransportPinError: If the name is not an RFC 9110 §5.6.2 token, names
                one of the four fields this exchange writes itself, or the value
                holds a character outside :data:`_FIELD_VALUE_CHARACTERS`. **The
                message names neither**: a value here may be the credential.
        """
        if not name or any(character not in _FIELD_NAME_CHARACTERS for character in name):
            msg = "a request header's name is an RFC 9110 §5.6.2 token; the value is not named"
            raise TransportPinError(msg)
        if name.lower() in _RESERVED_FIELD_NAMES:
            msg = (
                f"a request header may not name one of the {len(_RESERVED_FIELD_NAMES)} "
                f"fields this seam writes itself; the recipient and the framing are "
                f"not a caller's to choose"
            )
            raise TransportPinError(msg)
        if any(character not in _FIELD_VALUE_CHARACTERS for character in value):
            msg = (
                "a request header's value holds only printable ASCII, space and "
                "tab; a line break would write a field this seam did not compose, "
                "and the value is not named"
            )
            raise TransportPinError(msg)

    async def _response(self, channel: ByteChannel) -> HttpsResponse:
        """Read one response off ``channel``, under the bound.

        Args:
            channel: The channel the request was written to.

        Returns:
            The response.

        Raises:
            HttpsRedirectRefusedError: On a ``3xx``, raised before anything else is
                read from the response and before any second request could exist.
            HttpsResponseTooLargeError: If the response passed the bound.
            MalformedHttpResponseError: If it is not a shape this exchange reads.
            TransportError: If the connection could not be continued.
        """
        reader = _BoundedReader(channel, bound=self._bound)
        status = _status_of(await reader.line())
        if _MIN_REDIRECT <= status <= _MAX_REDIRECT:
            msg = (
                f"the far end answered {status}, a redirect; this seam follows none "
                f"and opened no second channel (ADR-0231 §5)"
            )
            raise HttpsRedirectRefusedError(msg)
        if status <= _MAX_INTERIM_STATUS:
            msg = f"the far end answered the interim status {status}, which this seam does not read"
            raise MalformedHttpResponseError(msg)
        headers = await _headers_of(reader)
        body = await _body_of(reader, headers, status=status)
        return HttpsResponse(status=status, headers=headers, body=body)


def _status_of(line: bytes) -> int:
    """The status code a status line carries (RFC 9112 §4).

    Args:
        line: The first line of the response, without its terminator.

    Returns:
        The code, in ``100..599``.

    Raises:
        MalformedHttpResponseError: If the line is not a status line this exchange
            reads — no version it knows, no space after the status code, no
            three-digit code, a code outside every class, or a reason phrase
            carrying an octet the grammar does not admit. The message names the
            defect and never the line: a far end's octets are a third party's
            text, and a refusal reaches a log.
    """
    version, versioned, rest = line.partition(b" ")
    if not versioned or version not in _HTTP_VERSIONS:
        msg = "the far end's first line names no HTTP version this seam reads"
        raise MalformedHttpResponseError(msg)
    code, coded, reason = rest.partition(b" ")
    if not coded:
        # RFC 9112 §4's grammar is ``HTTP-version SP status-code SP
        # [reason-phrase]``: the second space is required and the phrase after it
        # is not. Reading a line without it would be the leniency this module
        # refuses everywhere else, and it is the one shape a status-line parser
        # written as "take the first field after the version" admits without
        # noticing (adversarial round 2).
        msg = (
            "the far end's status line puts no space after its status code, so it "
            "is not a status line (RFC 9112 §4)"
        )
        raise MalformedHttpResponseError(msg)
    if len(code) != len(b"000") or not code.isascii() or not code.isdigit():
        msg = "the far end's status line carries no three-digit status code"
        raise MalformedHttpResponseError(msg)
    if not reason.isascii() or any(chr(octet) not in _FIELD_VALUE_CHARACTERS for octet in reason):
        # An **empty** phrase is admitted and only its octets are checked: RFC 9112
        # §4 writes ``1*(...)`` but ``HTTP/1.1 200 \r\n`` is what several ordinary
        # front ends send, and refusing it would be refusing a far end nobody would
        # call malformed. A control octet in it is a different thing, and it is
        # third-party text on its way to a log.
        msg = "the far end's reason phrase carries an octet RFC 9112 §4 does not admit"
        raise MalformedHttpResponseError(msg)
    status = int(code)
    if not _MIN_STATUS <= status <= _MAX_STATUS:
        msg = f"the far end answered {status}, which names no status class (RFC 9110 §15)"
        raise MalformedHttpResponseError(msg)
    return status


async def _headers_of(reader: _BoundedReader) -> tuple[tuple[str, str], ...]:
    """Every field of the header section, in order, names lowercased.

    Args:
        reader: The bounded reader, positioned after the status line.

    Returns:
        The fields. The empty line ending the section is consumed and not
        returned.

    Raises:
        MalformedHttpResponseError: If a line is not a field, or carries an octet
            outside ASCII. Obsolete line folding (a field continued on a line
            beginning with space or tab) is refused with them: RFC 9112 §5
            deprecates it, and reading it is the leniency response splitting is
            built out of.
        HttpsResponseTooLargeError: If reading the section passed the bound.
        TransportError: If the connection could not be continued.
    """
    fields: list[tuple[str, str]] = []
    while True:
        line = await reader.line()
        if not line:
            return tuple(fields)
        fields.append(_field_of(line))


def _field_of(line: bytes) -> tuple[str, str]:
    """One header field, name lowercased and value stripped (RFC 9110 §5).

    Shared by the header section and the trailer section, so that the two cannot
    be read under different grammars — which is the whole of what makes the
    trailer's discard safe. Adversarial review found the trailer accepting
    arbitrary octets on round 1.

    Args:
        line: The field line, without its terminator.

    Returns:
        The name, ASCII-lowercased, and the value with its surrounding space and
        horizontal tab removed as RFC 9110 §5.5 directs.

    Raises:
        MalformedHttpResponseError: If the line is not a field, carries an octet
            outside ASCII, or carries a control octet in its value. Obsolete line
            folding — a field continued on a
            line beginning with space or tab — is refused with them: RFC 9112 §5
            deprecates it, and reading it is the leniency response splitting is
            built out of. The message names the defect and never the line: a far
            end's octets are a third party's text, and a refusal reaches a log.
    """
    if not line.isascii():
        msg = "the far end sent a header line carrying a non-ASCII octet"
        raise MalformedHttpResponseError(msg)
    name, separator, value = line.decode("ascii").partition(":")
    if (
        not separator
        or not name
        or any(character not in _FIELD_NAME_CHARACTERS for character in name)
    ):
        msg = "the far end sent a line that is not a header field"
        raise MalformedHttpResponseError(msg)
    content = value.strip(" \t")
    if any(character not in _FIELD_VALUE_CHARACTERS for character in content):
        # **The same set the request side is written under**, and the asymmetry is
        # what made this worth closing: :meth:`HttpsExchange._check_field` refuses a
        # control octet in a value this seam *writes*, and a value it *reads* went
        # into :attr:`HttpsResponse.headers` unchecked — third-party control data
        # handed on to whatever reads a field next (adversarial round 2). RFC 9110
        # §5.5 admits visible ASCII, space and horizontal tab in field content and
        # nothing else; ``CR`` and ``LF`` cannot arrive here at all, since the line
        # was framed on them.
        msg = "the far end sent a header field whose value carries a control octet"
        raise MalformedHttpResponseError(msg)
    return name.lower(), content


async def _body_of(
    reader: _BoundedReader, headers: tuple[tuple[str, str], ...], *, status: int
) -> bytes:
    """The payload's octets, with any chunked framing removed.

    **A status with no content is framed by the header section and by nothing
    else**, which is RFC 9112 §6.3's first rule and the reason this takes a status
    at all. §6.3 decides it "regardless of the header fields present in the
    message", so a ``Content-Length`` or a ``Transfer-Encoding`` on a ``204`` or a
    ``304`` is neither read nor resolved: the standard states the framing, and
    reading a body such a response does not have would hand a caller octets it
    would take for provider payload. Nothing is desynchronised by leaving them,
    because ``Connection: close`` means there is no next response on this channel.

    Otherwise three framings, in §6.3's own precedence and no other: a
    ``Transfer-Encoding``, a ``Content-Length``, or the connection's close — which
    is why the request says ``Connection: close``.

    **A response declaring its length two ways is refused rather than resolved.**
    Choosing between them is what request smuggling is, and a seam that picked one
    would be picking the same one an intermediary might not.

    Args:
        reader: The bounded reader, positioned after the header section.
        headers: The fields, as :func:`_headers_of` returned them.
        status: The status the response carried, which §6.3's first rule turns on.

    Returns:
        The octets, which are empty for a status that admits no content.

    Raises:
        MalformedHttpResponseError: On two framings at once, a transfer coding
            other than ``chunked``, a ``Content-Length`` that is not one decimal
            number this seam will read, or a stream ending inside any of them.
        HttpsResponseTooLargeError: If reading it passed the bound.
        TransportError: If the connection could not be continued.
    """
    if status in _NO_CONTENT_STATUSES:
        return b""
    coding = _one_of(headers, "transfer-encoding")
    length = _one_of(headers, "content-length")
    if coding is not None and length is not None:
        msg = (
            "the far end framed the response two ways at once, with both a "
            "transfer coding and a content length; it is refused rather than "
            "resolved in favour of either"
        )
        raise MalformedHttpResponseError(msg)
    if coding is not None:
        if coding.lower().strip() != "chunked":
            msg = "the far end named a transfer coding this seam does not read"
            raise MalformedHttpResponseError(msg)
        return await _chunked(reader)
    if length is not None:
        if not length.isascii() or not length.isdigit() or len(length) > _MAX_CONTENT_LENGTH_DIGITS:
            msg = "the far end's content length is not a decimal number of octets"
            raise MalformedHttpResponseError(msg)
        return await reader.take(int(length))
    return await reader.rest()


def _one_of(headers: tuple[tuple[str, str], ...], name: str) -> str | None:
    """The one value ``name`` carries, or ``None`` where it is absent.

    Args:
        headers: The fields, names already lowercased.
        name: The field to read, lowercased.

    Returns:
        The value, or ``None``.

    Raises:
        MalformedHttpResponseError: If the field appears more than once. Both
            fields this is used for frame the body, and a far end sending two of
            either is the smuggling shape a client that took the first would let
            through.
    """
    values = [value for field, value in headers if field == name]
    if len(values) > 1:
        msg = f"the far end sent more than one {name!r} field, which frames the response twice"
        raise MalformedHttpResponseError(msg)
    return values[0] if values else None


async def _chunked(reader: _BoundedReader) -> bytes:
    """Decode a chunked body, trailers and all (RFC 9112 §7.1).

    Args:
        reader: The bounded reader, positioned at the first chunk size.

    Returns:
        The chunks' octets, joined, with every size line, terminator and trailer
        removed.

    Raises:
        MalformedHttpResponseError: On a chunk size that is not hexadecimal, a
            chunk not followed by its terminator, a trailer line that is not a
            header field, or a stream ending inside any of them.
        HttpsResponseTooLargeError: If reading it passed the bound.
        TransportError: If the connection could not be continued.
    """
    body = bytearray()
    while True:
        size = _chunk_size(await reader.line())
        if size == 0:
            break
        body += await reader.take(size)
        if await reader.line():
            msg = "the far end did not terminate a chunk where its size said it ends"
            raise MalformedHttpResponseError(msg)
    # The trailer section, which RFC 9112 §7.1.2 allows and this seam discards:
    # a trailer is a header field arriving after the body, and nothing here reads
    # one. It is still *read*, because the octets are on the channel either way and
    # the bound counts them — and it is read under the **same grammar** the header
    # section is, because a section this exchange would refuse before the body is
    # not one it accepts after it. Discarding without validating would have made
    # the trailer the one place arbitrary octets were admitted, which is the
    # leniency this module refuses everywhere else (adversarial round 1).
    while line := await reader.line():
        _field_of(line)
    return bytes(body)


def _chunk_size(line: bytes) -> int:
    """The size a chunk-size line declares, in octets (RFC 9112 §7.1).

    ``int(text, 16)`` is checked against rather than trusted: it accepts a sign,
    surrounding whitespace and ``_`` separators, so ``int(b"1_0", 16)`` is 16 and a
    far end could declare a size in a spelling no other reader agrees on. The
    length is checked before the conversion, for :func:`_port`'s reason (#1147).

    Args:
        line: The chunk-size line, without its terminator. A chunk extension —
            everything from the first ``;`` — is dropped, which RFC 9112 §7.1.1
            allows a recipient to do.

    Returns:
        The size, in octets.

    Raises:
        MalformedHttpResponseError: If the line declares no hexadecimal size.
    """
    size = line.partition(b";")[0]
    if (
        not size
        or len(size) > _MAX_CHUNK_SIZE_DIGITS
        or any(chr(octet) not in _HEX_DIGITS for octet in size)
    ):
        msg = "the far end declared a chunk size that is not a hexadecimal number"
        raise MalformedHttpResponseError(msg)
    return int(size, 16)


__all__ = [
    "HTTPS_SCHEME",
    "IMPLICIT_TLS_SCHEME",
    "STARTTLS_SCHEME",
    "BoundCallChangedError",
    "EgressTransportError",
    "HttpsExchange",
    "HttpsExchangeError",
    "HttpsRedirectRefusedError",
    "HttpsResponse",
    "HttpsResponseTooLargeError",
    "IndeterminateTransmissionError",
    "MalformedHttpResponseError",
    "OutboundEmail",
    "SmtpEgressTransport",
    "StreamOutboundTransport",
    "TransportPinError",
    "parse_https_origin",
    "parse_smtp_endpoint",
    "smtp_message",
]
