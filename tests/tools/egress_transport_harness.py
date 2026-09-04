"""Arranging a bound egress call, and a channel that is not a network.

Shared by :mod:`test_egress_transport` and :mod:`test_egress_failure_paths`, which
ask different questions of the same seam: the first that the SMTP exchange is the
one the protocol specifies, the second that ADR-0017 §3's failure matrix holds.

**Nothing here opens a socket, and since ADR-0191 that is a property of the design
rather than of the arrangement.** :class:`~ai_assistant.tools.egress.
SmtpEgressTransport` takes the outbound-transport capability as a **required**
argument with no default, so an arrangement that forgot to pass one would not
construct rather than quietly reaching the network. Every command, every reply and
every refusal below is exercised against
:class:`~ai_assistant.testing.FakeByteChannel` served by
:class:`~ai_assistant.testing.FakeOutboundTransport`, and the only thing left
untested is :meth:`~ai_assistant.tools.egress.StreamOutboundTransport.open_channel`'s
own call into ``asyncio``. Hosts are ``.invalid`` (RFC 6761 §6.4) throughout, so a
case that somehow did reach a resolver would fail rather than connect.

**The two doubles this module used to declare are gone into the canonical fakes**
(ADR-0191 §8, Consequences). ``ScriptedChannel`` was the seed of
``FakeByteChannel``; what it lacked was a home ``ai_assistant.testing`` could hold
and a conformance suite holding it to a contract. What is left here is arrangement
— :func:`scripted` scripts an SMTP endpoint's replies onto the canonical fake, and
:func:`commands` and :func:`payload` read its record back the way this seam's cases
want it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from pydantic import SecretStr

from ai_assistant.core.errors import TransportError
from ai_assistant.core.types import (
    BoundAccount,
    DestinationProtocol,
    DiscloserProvenance,
    EgressBinding,
    EgressDestination,
    EgressSpan,
    ProvisioningState,
    SecretName,
    SecretScope,
    SpanCoverage,
)
from ai_assistant.testing import FakeByteChannel, FakeOutboundTransport
from ai_assistant.testing.secrets import FakeSecretStore
from ai_assistant.tools.connection_store import ConnectionEntry, StoredEntry
from ai_assistant.tools.egress import SmtpEgressTransport
from ai_assistant.tools.egress_binder import EgressRegistration

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from ai_assistant.core.protocols import Secrets
    from ai_assistant.core.types import FrozenJson

#: The registered tool, its connection record and the account it is bound to.
TOOL_ID: Final = "send_email@work"
REFERENCE: Final = "conn-0001"
IDENTITY: Final = "work@example.invalid"

#: The endpoint the registration configures. Implicit TLS, so the happy path is
#: three commands shorter; :data:`STARTTLS_ENDPOINT` exercises the upgrade.
ENDPOINT: Final = "smtps://mail.example.invalid:465"
STARTTLS_ENDPOINT: Final = "smtp+starttls://mail.example.invalid:587"

#: The slot the record names. A binding never carries one (ADR-0148 §6), so a
#: transport that read a slot from anywhere but the record would fail every case.
SLOT: Final = SecretName(scope=SecretScope.INTEGRATION, key="conn-0001-r1")

#: What the keyring holds under that slot.
CREDENTIAL: Final = "an-app-password"


def entry(
    *,
    identity: str = IDENTITY,
    revision: int = 1,
    state: ProvisioningState | None = ProvisioningState.ACTIVE,
    slot: SecretName | None = SLOT,
    sequence: int = 1,
) -> StoredEntry:
    """One connection-store entry, as a provisioning act would have written it.

    Args:
        identity: The account identity recorded for the reference.
        revision: ADR-0148 §6's monotonic revision.
        state: The provisioning state, or ``None`` for a removal entry.
        slot: The credential slot this act wrote to, or ``None`` on a removal.
        sequence: The store's own append order, which no reader here uses.

    Returns:
        The entry paired with its sequence, exactly as ``latest`` returns one.
    """
    removal = state is None
    return StoredEntry(
        sequence,
        ConnectionEntry(
            reference=REFERENCE,
            revision=revision,
            identity=None if removal else identity,
            state=state,
            slot=None if removal else slot,
        ),
    )


class Records:
    """A ``ConnectionRecords`` face whose answers are scripted read by read.

    The transport reads the record **twice** per call — once immediately before
    the credential and once immediately after — and almost every case in ADR-0148
    §6 is about the two answers differing. So the script is a list consumed in
    order, with the last entry repeating: a one-element script is a store that
    never changes, and a two-element one is a store that changed across exactly
    the window the clause is about.

    An element that is an exception is raised rather than returned, which is how
    the first read's propagation and the second read's unanswerable-is-changed
    rule are told apart.

    Attributes:
        reads: Every reference read, in order. A case asserting that nothing was
            read at all reads this rather than trusting the absence of an effect.
    """

    def __init__(self, *script: StoredEntry | None | Exception) -> None:
        """Arrange the answers this store gives, in order.

        Args:
            script: One element per read; the last repeats. An empty script is a
                store with no record for the reference.
        """
        self._script: list[StoredEntry | None | Exception] = list(script) or [None]
        self.reads: list[str] = []

    async def latest(self, reference: str, /) -> StoredEntry | None:
        """The reference's latest entry, per this store's script.

        Args:
            reference: The connection to read.

        Returns:
            The scripted entry, or ``None``.

        Raises:
            Exception: Where the script's element for this read is one.
        """
        self.reads.append(reference)
        answer = self._script[min(len(self.reads) - 1, len(self._script) - 1)]
        if isinstance(answer, Exception):
            raise answer
        return answer


class Keyring:
    """The canonical ``Secrets`` fake, with every name it was asked for recorded.

    A wrapper rather than a second fake: :class:`~ai_assistant.testing.secrets.
    FakeSecretStore` is what ADR-0125 §11 binds both conformance suites to, so the
    behaviour every case rests on is the contract's. What is added is the record —
    "a denial performs no credential read" is a claim about a call that did **not**
    happen, and only a recording subject can distinguish that from a read whose
    result was discarded.

    Attributes:
        reads: Every name passed to :meth:`get`, in order.
    """

    def __init__(self) -> None:
        """Start empty, holding nothing and having answered nothing."""
        self.store = FakeSecretStore(scope=SecretScope.INTEGRATION)
        self.reads: list[SecretName] = []

    async def get(self, name: SecretName) -> SecretStr | None:
        """Read ``name``, recording that it was asked for.

        Args:
            name: The entry to read.

        Returns:
            The value, or ``None`` where the keyring holds nothing under it.
        """
        self.reads.append(name)
        return await self.store.get(name)


async def keyring(*, holds: str | None = CREDENTIAL, slot: SecretName = SLOT) -> Keyring:
    """A recording keyring holding ``holds`` under ``slot``.

    Args:
        holds: The credential to store, or ``None`` for a keyring with no entry —
            which is what an interrupted provisioning act leaves behind.
        slot: Where to store it.

    Returns:
        The keyring.
    """
    ring = Keyring()
    if holds is not None:
        await ring.store.set(slot, SecretStr(holds))
    return ring


def scripted(
    *replies: str,
    secure: bool = True,
    on_exhausted: TransportError | None = None,
    on_payload_write: TransportError | None = None,
) -> FakeByteChannel:
    """An SMTP endpoint's scripted replies, on the canonical channel fake.

    Arrangement over :class:`~ai_assistant.testing.FakeByteChannel` rather than a
    second implementation of the contract (ADR-0191 §8): what varies per case is
    which reply lines the far end sends and where it stops answering, and none of
    that is a property of the channel.

    Args:
        replies: One reply per element, multi-line where the reply is. Each line
            is delivered CRLF-terminated, as RFC 5321 §4.2 requires.
        secure: Whether TLS was established before the greeting — ``True`` for an
            implicit-TLS endpoint.
        on_exhausted: Raised once the script runs out, instead of the empty bytes
            that stand for a clean end of stream. A far end can stop answering
            either way, and a caller has to be able to tell them apart. It is a
            ``TransportError`` because that is what a conforming channel raises
            for a connection that could not be continued (ADR-0191 §1): the raw
            ``ConnectionResetError`` this used to be armed with is what
            ``_StreamChannel`` now converts *before* the seam sees it.
        on_payload_write: Raised by the write of the ``DATA`` block, after the
            octets have been recorded. Armed against the block's ``CRLF.CRLF``
            terminator rather than against a write *count*, because the count is
            an artefact of how many commands the exchange happens to take and
            would silently arm the wrong write the day one is added.

    Returns:
        The channel, ready to be served by :func:`transport`.
    """
    subject = FakeByteChannel(secure=secure)
    for reply in replies:
        for line in reply.splitlines():
            if line:
                subject.deliver(line.encode("ascii") + b"\r\n")
    if on_exhausted is not None:
        subject.fail_when_exhausted(on_exhausted)
    if on_payload_write is not None:
        subject.fail_write_after(b"\r\n.\r\n", error=on_payload_write)
    return subject


def commands(subject: FakeByteChannel) -> list[str]:
    """Every command line the transport wrote, before the ``DATA`` payload.

    Args:
        subject: The channel the exchange ran over.

    Returns:
        The lines, in order, up to and including ``DATA``. What follows a ``DATA``
        is the message rather than a command, and :func:`payload` reads that.
    """
    sent: list[str] = []
    for line in subject.written.decode("ascii", "replace").split("\r\n"):
        if not line:
            continue
        sent.append(line)
        if line == "DATA":
            break
    return sent


def payload(subject: FakeByteChannel) -> str:
    """Everything written after ``DATA`` was accepted.

    Args:
        subject: The channel the exchange ran over.

    Returns:
        The dot-stuffed message and its terminator, or the empty string where no
        payload was ever written.
    """
    text = subject.written.decode("ascii", "replace")
    marker = "DATA\r\n"
    return text.split(marker, 1)[1] if marker in text else ""


def implicit_tls_script(*, recipients: int = 1) -> tuple[str, ...]:
    """A conforming implicit-TLS endpoint's replies for one accepted message.

    Args:
        recipients: How many ``RCPT TO`` commands to accept.

    Returns:
        Greeting, ``EHLO``, ``AUTH``, ``MAIL FROM``, one reply per recipient,
        ``DATA``, the accepted message, and the ``QUIT`` farewell.
    """
    return (
        "220 mail.example.invalid ESMTP ready",
        "250-mail.example.invalid\n250 AUTH PLAIN LOGIN",
        "235 2.7.0 authentication succeeded",
        "250 2.1.0 sender ok",
        *("250 2.1.5 recipient ok" for _ in range(recipients)),
        "354 end data with <CR><LF>.<CR><LF>",
        "250 2.0.0 queued as ABC123",
        "221 2.0.0 closing connection",
    )


def starttls_script(*, offers_starttls: bool = True, recipients: int = 1) -> tuple[str, ...]:
    """A conforming submission endpoint's replies, upgrade included.

    Args:
        offers_starttls: Whether the first ``EHLO`` advertises the extension. A
            ``False`` here is the downgrade case, and the transport refuses it
            rather than continuing in the clear.
        recipients: How many ``RCPT TO`` commands to accept.

    Returns:
        The replies, in order.
    """
    offered = "250-mail.example.invalid\n250-STARTTLS\n250 AUTH PLAIN"
    declined = "250-mail.example.invalid\n250 AUTH PLAIN"
    if not offers_starttls:
        return ("220 mail.example.invalid ESMTP ready", declined)
    return (
        "220 mail.example.invalid ESMTP ready",
        offered,
        "220 2.0.0 ready to start TLS",
        declined,
        "235 2.7.0 authentication succeeded",
        "250 2.1.0 sender ok",
        *("250 2.1.5 recipient ok" for _ in range(recipients)),
        "354 end data with <CR><LF>.<CR><LF>",
        "250 2.0.0 queued as ABC123",
        "221 2.0.0 closing connection",
    )


def arguments(  # noqa: PLR0913 — one keyword per argument the tool declares.
    *,
    to: Sequence[str] = ("Alice@Example.Invalid",),
    cc: Sequence[str] = (),
    bcc: Sequence[str] = (),
    subject: str = "quarterly report",
    body: str = "attached, as promised",
    extra: Mapping[str, FrozenJson] | None = None,
) -> dict[str, FrozenJson]:
    """One call's arguments, as ``invoke`` would hand them to a callable.

    Recipients default to the **supplied** form :func:`binding` carries, not its
    canonical one, because that is what a user types and what the arguments a
    decision's digest binds actually hold. A test that pre-canonicalised its own
    input would hide the very step the transport has to perform — which is how
    adversarial round 3 found a refusal of a perfectly good call.

    Args:
        to: Recipients in the ``To`` header.
        cc: Recipients in the ``Cc`` header.
        bcc: Recipients that receive the message and appear in no header.
        subject: The subject text.
        body: The body text.
        extra: Further keys, for the cases about arguments this seam refuses.

    Returns:
        The mapping.
    """
    built: dict[str, FrozenJson] = {"to": list(to), "subject": subject, "body": body}
    if cc:
        built["cc"] = list(cc)
    if bcc:
        built["bcc"] = list(bcc)
    return built | dict(extra or {})


def binding(  # noqa: PLR0913 — one keyword per fact a ruling fixes; grouping them
    # into a value would be a second shape a case has to build before it can vary one.
    *,
    recipients: Sequence[tuple[str, str]] = (("Alice@Example.Invalid", "Alice@example.invalid"),),
    identity: str = IDENTITY,
    reference: str = REFERENCE,
    endpoint: str = ENDPOINT,
    subject: str = "quarterly report",
    body: str = "attached, as promised",
    describes: Iterable[str] = ("subject", "body"),
    indexed: bool = True,
) -> EgressBinding:
    """One authorised binding, as a ruling fixed it.

    Every recipient is given as ``(supplied, canonical)`` because ADR-0148 §14's
    alias case fails an implementation that keeps only one of the two, so the
    default pair deliberately differs in domain case — which is the one
    transformation RFC 5321 §2.4 licenses.

    Args:
        recipients: The ``to`` occurrences, supplied form beside canonical.
        identity: The bound account's identity.
        reference: The bound connection reference.
        endpoint: The bound transport endpoint.
        subject: The subject the payload carries.
        body: The body the payload carries.
        describes: Which payload **arguments** the description covers, by name.
            Named rather than given by value so that a case in which the subject
            and the body are the same text can still describe exactly one of them
            — which is the arrangement the multiset coverage check exists for.
        indexed: Whether each recipient span carries its position. ``False`` is
            what the binder derives for a **string-valued** destination argument,
            which ADR-0157 §1 makes declarable: ADR-0150 §4 gives a string one
            span with no index, and an array one span per element with its index
            (ADR-0157 §3). Only meaningful with a single recipient, since a string
            names exactly one.

    Returns:
        A binding a policy could have ruled on.
    """
    covered = frozenset(describes)
    text_of = {"subject": subject, "body": body}
    spans = [
        *(
            EgressSpan(
                argument=argument,
                provenance=DiscloserProvenance.USER_AUTHORED,
                extent=len(text_of[argument]),
            )
            # Ordered by argument name, which is what `EgressBinding` requires:
            # "body" precedes "subject" precedes "to" by Unicode code point.
            for argument in sorted(covered)
        ),
        *(
            EgressSpan(
                argument="to",
                index=index if indexed else None,
                provenance=DiscloserProvenance.USER_AUTHORED,
                extent=len(supplied),
                destination=EgressDestination(
                    protocol=DestinationProtocol.SMTP, supplied=supplied, canonical=canonical
                ),
            )
            for index, (supplied, canonical) in enumerate(recipients)
        ),
    ]
    return EgressBinding(
        spans=tuple(spans),
        account=BoundAccount(identity=identity, reference=reference),
        transport_endpoint=endpoint,
        planned_with_external_content=False,
        coverage=SpanCoverage.NOT_COVERED,
    )


def transport(
    served: FakeByteChannel | None,
    *,
    records: Records | None = None,
    secrets: Secrets,
    endpoint: str = ENDPOINT,
    reference: str = REFERENCE,
) -> SmtpEgressTransport:
    """Wire the seam over a scripted channel, a scripted store and a keyring.

    Args:
        served: The channel the capability hands out. ``None`` arms the capability
            to refuse, which is how "no network I/O" is asserted rather than
            assumed: the attempt is still recorded, so a case that wanted the
            distinction between "never asked" and "asked and refused" could read
            it (ADR-0191 §8).
        records: The connection store; defaults to one active record.
        secrets: The ``INTEGRATION``-scoped reading face.
        endpoint: The endpoint the registration configures.
        reference: The connection reference the registration carries.

    Returns:
        The seam's transport, holding the capability and nothing else that could
        reach the world.
    """
    capability = FakeOutboundTransport()
    if served is None:
        capability.refuse_with(
            TransportError("this harness opens nothing; the attempt has been recorded")
        )
    else:
        capability.serve(served)
    return SmtpEgressTransport(
        registration=EgressRegistration(
            tool_id=TOOL_ID, reference=reference, transport_endpoint=endpoint
        ),
        records=Records(entry()) if records is None else records,
        secrets=secrets,
        transport=capability,
    )
