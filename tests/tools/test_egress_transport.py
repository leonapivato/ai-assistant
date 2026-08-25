"""The SMTP exchange the seam speaks, and the order ADR-0148 §6 fixes for it.

What is *not* here is ADR-0017 §3's failure matrix, which is
:mod:`test_egress_failure_paths`'s whole subject and is kept separate because the
two are read by different people for different reasons: this file answers "does
the transport speak the protocol", and that one answers "does it refuse what it
must". Splitting them also keeps §3's last condition legible as a list a
designating ADR can walk.

**No case here opens a socket, and since ADR-0191 nothing here could.** Every one
drives :class:`~ai_assistant.tools.egress.SmtpEgressTransport` over a
:class:`~ai_assistant.testing.FakeByteChannel` served by
:class:`~ai_assistant.testing.FakeOutboundTransport` — and the seam takes that
capability as a required argument, so there is no default connector left for a
case to forget to displace.
"""

from __future__ import annotations

from typing import Final

import pytest
from egress_transport_harness import (
    CREDENTIAL,
    IDENTITY,
    REFERENCE,
    STARTTLS_ENDPOINT,
    Records,
    arguments,
    binding,
    commands,
    entry,
    implicit_tls_script,
    keyring,
    payload,
    scripted,
    starttls_script,
    transport,
)

from ai_assistant.core.types import (
    ProvisioningState,
    SecretName,
    SecretScope,
    TransportEndpoint,
)
from ai_assistant.tools.egress import (
    BoundCallChangedError,
    TransportPinError,
    parse_smtp_endpoint,
)

#: The arguments every happy-path case sends, so that what differs between them is
#: the arrangement rather than the payload. The recipient is in its **supplied**
#: form — the one `binding()` carries the canonical of — because that is what a
#: call's arguments hold and what the transport has to canonicalise for itself.
ARGUMENTS: Final = arguments()


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        (
            "smtps://mail.example.invalid",
            TransportEndpoint(host="mail.example.invalid", port=465, implicit_tls=True),
        ),
        (
            "smtps://mail.example.invalid:2465",
            TransportEndpoint(host="mail.example.invalid", port=2465, implicit_tls=True),
        ),
        (
            "smtp+starttls://mail.example.invalid",
            TransportEndpoint(host="mail.example.invalid", port=587, implicit_tls=False),
        ),
        (
            "smtp+starttls://mx.example.invalid:25",
            TransportEndpoint(host="mx.example.invalid", port=25, implicit_tls=False),
        ),
    ],
)
def test_the_endpoint_grammar_accepts_a_host_a_port_and_two_schemes(
    endpoint: str, expected: TransportEndpoint
) -> None:
    """Each scheme's default port is its own RFC's, and neither is guessed."""
    assert parse_smtp_endpoint(endpoint) == expected


@pytest.mark.parametrize(
    "endpoint",
    [
        pytest.param("smtp://mail.example.invalid", id="cleartext"),
        pytest.param("https://mail.example.invalid", id="another-protocol"),
        pytest.param("mail.example.invalid:465", id="no-scheme"),
        pytest.param("smtps://", id="no-host"),
        pytest.param("smtps://mail.example.invalid/send", id="path"),
        pytest.param("smtps://mail.example.invalid?relay=1", id="query"),
        pytest.param("smtps://user:pw@mail.example.invalid", id="userinfo"),
        pytest.param("smtps://mail.example.invalid#frag", id="fragment"),
        pytest.param("smtps://mail.example.invalid:0", id="port-zero"),
        pytest.param("smtps://mail.example.invalid:70000", id="port-out-of-range"),
        pytest.param("smtps://mail.example.invalid:submission", id="port-not-a-number"),
        pytest.param("smtps:// mail.example.invalid", id="host-with-space"),
    ],
)
def test_the_endpoint_grammar_refuses_every_form_it_will_not_pin(endpoint: str) -> None:
    """A permissive endpoint is #83's failure with the attacker writing the config.

    Each of these is a form a general URL parser would accept and this seam would
    then have to have an opinion about — a cleartext scheme, credentials in the
    authority, a path a later lane could read as a route. Refusing is cheaper than
    deciding, and an unreadable port is refused rather than defaulted, because
    defaulting connects somewhere nobody wrote down.
    """
    with pytest.raises(TransportPinError):
        parse_smtp_endpoint(endpoint)


@pytest.mark.parametrize(
    "endpoint",
    [
        pytest.param("smtps://127.0.0.1\x00mail.example.invalid:465", id="nul-under-implicit-tls"),
        pytest.param(
            "smtp+starttls://127.0.0.1\x00mail.example.invalid:587", id="nul-under-starttls"
        ),
        pytest.param("smtps://\ud800.invalid:465", id="no-utf-8-encoding"),
    ],
)
def test_a_host_the_endpoint_type_refuses_is_refused_in_this_seams_taxonomy(endpoint: str) -> None:
    """A refusal about a binding is ``TransportPinError``, whoever noticed it.

    ``TransportEndpoint`` refuses a host carrying a control character — a ``NUL``
    is what ``getaddrinfo`` truncates at, so ``127.0.0.1\x00mail.example.invalid``
    resolved to ``127.0.0.1`` until round 4 of review found it — and one with no
    UTF-8 encoding. This grammar reads the authority's punctuation and neither of
    those is punctuation, so the refusal arrives from the type. What it must not
    arrive as is pydantic's ``ValidationError``: this function's callers are
    handling a refusal about a *binding* (ADR-0191 §4), and pydantic renders the
    input it refused, so the endpoint an operator configured would travel with it.

    **Under both TLS modes, and no opener is reached in either**: the endpoint
    cannot be constructed, so there is nothing for
    ``StreamOutboundTransport.open_channel`` to be handed.

    Args:
        endpoint: A configured endpoint whose host the type refuses.
    """
    with pytest.raises(TransportPinError) as refusal:
        parse_smtp_endpoint(endpoint)

    assert "mail.example.invalid" not in str(refusal.value)


@pytest.mark.parametrize("host", ["mail.example.invalid", "MAIL.example.invalid"])
def test_the_grammar_never_normalises_the_host(host: str) -> None:
    """Two spellings of one host stay two endpoints (ADR-0148 §2's exactness default)."""
    assert parse_smtp_endpoint(f"smtps://{host}:465").host == host


async def test_a_conforming_exchange_sends_to_exactly_the_bound_recipients() -> None:
    """The happy path, stated as the command sequence RFC 5321 specifies.

    Asserted as the whole sequence rather than as "it did not raise", because
    every refusal case below is only meaningful against a known-good exchange — a
    transport that silently skipped ``MAIL FROM`` would pass a great many negative
    cases. The ``AUTH`` line is matched by its prefix because its argument is the
    credential, which is also why the transport never logs the line whole.
    """
    channel = scripted(*implicit_tls_script())
    subject = transport(channel, secrets=await keyring())

    await subject.transmit(binding(), ARGUMENTS)

    sent = commands(channel)
    assert sent[0] == "EHLO mail.example.invalid"
    assert sent[1].startswith("AUTH PLAIN ")
    assert sent[2:] == [
        "MAIL FROM:<work@example.invalid>",
        "RCPT TO:<Alice@example.invalid>",
        "DATA",
    ]
    assert channel.closed


async def test_the_credential_is_presented_only_after_the_starttls_upgrade() -> None:
    """The order is read from the channel's TLS state, not from the script.

    ADR-0017 §3's second failure-path row is stated over the credential *not
    travelling*, and the strongest form of that at this seam is that the octets
    carrying it are written after the handshake and never before it.
    """
    channel = scripted(*starttls_script(), secure=False)
    subject = transport(channel, secrets=await keyring(), endpoint=STARTTLS_ENDPOINT)

    await subject.transmit(binding(endpoint=STARTTLS_ENDPOINT), ARGUMENTS)

    written = channel.written.decode("ascii")
    assert channel.tls_upgrades == 1
    assert written.index("STARTTLS") < written.index("AUTH PLAIN")


async def test_an_endpoint_that_does_not_offer_starttls_is_refused_in_the_clear() -> None:
    """No downgrade and no cleartext fallback, and the credential stays put."""
    channel = scripted(*starttls_script(offers_starttls=False), secure=False)
    subject = transport(channel, secrets=await keyring(), endpoint=STARTTLS_ENDPOINT)

    with pytest.raises(TransportPinError, match="STARTTLS"):
        await subject.transmit(binding(endpoint=STARTTLS_ENDPOINT), ARGUMENTS)

    assert CREDENTIAL not in channel.written.decode("ascii")
    assert channel.tls_upgrades == 0
    assert channel.closed


async def test_the_record_is_read_once_before_the_credential_and_once_after() -> None:
    """ADR-0148 §6's one-step read and its post-read re-check, counted.

    Two reads and no more: a third would mean the transport re-derived something
    the ruling fixed, and one would mean the discard clause has nothing to compare
    against.
    """
    records = Records(entry())
    ring = await keyring()
    subject = transport(scripted(*implicit_tls_script()), records=records, secrets=ring)

    await subject.transmit(binding(), ARGUMENTS)

    assert records.reads == [REFERENCE, REFERENCE]
    assert [name.key for name in ring.reads] == ["conn-0001-r1"]


async def test_a_completed_rotation_of_the_same_account_refuses_nothing() -> None:
    """ADR-0125 §4's rotation case, which ADR-0148 §6 is written to preserve.

    The revision is compared only before against after, never against the binding,
    so a rotation that completed *before* the resume leaves the parked approval
    answerable — the identity is unchanged and no revision was read yet. The slot
    read is the one the record **now** names, which is what ADR-0148 §14 says an
    implementation reading a slot carried in the binding would fail.
    """
    rotated = SecretName(scope=SecretScope.INTEGRATION, key="conn-0001-r7")
    records = Records(entry(revision=7, slot=rotated))
    ring = await keyring(slot=rotated)
    subject = transport(scripted(*implicit_tls_script()), records=records, secrets=ring)

    await subject.transmit(binding(), ARGUMENTS)

    assert [name.key for name in ring.reads] == ["conn-0001-r7"]


async def test_a_blind_copy_is_an_envelope_recipient_and_appears_in_no_header() -> None:
    """A blind copy that showed up in a header would not be blind.

    It is authorised like any other member of the set (ADR-0148 §4) and receives
    the message, which is what makes it a recipient at all — the difference is
    only what the other recipients are shown.
    """
    channel = scripted(*implicit_tls_script(recipients=2))
    subject = transport(channel, secrets=await keyring())
    bound = binding(
        recipients=(
            ("Alice@example.invalid", "Alice@example.invalid"),
            ("bob@example.invalid", "bob@example.invalid"),
        )
    )

    await subject.transmit(bound, arguments(bcc=("bob@example.invalid",)))

    assert "RCPT TO:<bob@example.invalid>" in commands(channel)
    assert "bob@example.invalid" not in payload(channel)


async def test_a_body_line_beginning_with_a_dot_is_stuffed() -> None:
    """RFC 5321 §4.5.2 transparency, which a truncation would otherwise hide.

    An unstuffed leading dot ends the ``DATA`` block early: the far end accepts
    what it received and the sender believes it sent more, which is a disclosure
    that is *shorter* than the one described and is therefore invisible to every
    check comparing what was approved against what was authorised.
    """
    body = "first\n.hidden\nlast"
    channel = scripted(*implicit_tls_script())
    subject = transport(channel, secrets=await keyring())

    await subject.transmit(
        binding(body=body),
        arguments(body=body),
    )

    assert "\r\n..hidden\r\n" in payload(channel)
    assert "\r\nlast\r\n.\r\n" in payload(channel)


async def test_the_envelope_sender_is_the_bound_identity_under_the_seams_canonicaliser() -> None:
    """One canonicaliser per protocol (ADR-0148 §2), used for the sender too."""
    channel = scripted(*implicit_tls_script())
    records = Records(entry(identity="Work@Example.Invalid"))
    subject = transport(channel, records=records, secrets=await keyring())

    await subject.transmit(binding(identity="Work@Example.Invalid"), ARGUMENTS)

    assert "MAIL FROM:<Work@example.invalid>" in commands(channel)


async def test_an_account_identity_that_is_not_a_mailbox_is_refused() -> None:
    """An identity is a recognisable name, and this seam checks rather than assumes.

    ADR-0148 §6 records the identity as "the durable, user-recognisable name of
    the account". For SMTP that has to be a mailbox, and asking the seam's own
    canonicaliser is what turns that from an assumption into a refusal — the
    alternative is interpolating an arbitrary string into a ``MAIL FROM``.
    """
    ring = await keyring()
    subject = transport(None, records=Records(entry(identity="Work Account")), secrets=ring)

    with pytest.raises(BoundCallChangedError, match=r"not.*SMTP mailbox"):
        await subject.transmit(binding(identity="Work Account"), ARGUMENTS)

    assert ring.reads == []


async def test_a_reply_that_is_not_an_smtp_reply_is_refused() -> None:
    """A far end that is not speaking SMTP is not the service that was connected."""
    channel = scripted("this is not a reply")
    subject = transport(channel, secrets=await keyring())

    with pytest.raises(TransportPinError, match="not an SMTP reply"):
        await subject.transmit(binding(), ARGUMENTS)


async def test_a_pending_record_transmits_nothing_and_reads_no_credential() -> None:
    """An interrupted provisioning act leaves a reference that is not connectable.

    ADR-0148 §6 refuses that state rather than reconciling it: no lane resolves it
    by trusting the keyring, and the remedy is to run the provisioning act again.
    """
    ring = await keyring()
    subject = transport(None, records=Records(entry(state=ProvisioningState.PENDING)), secrets=ring)

    with pytest.raises(BoundCallChangedError, match="not connectable"):
        await subject.transmit(binding(), ARGUMENTS)

    assert ring.reads == []


async def test_a_keyring_holding_nothing_under_the_named_slot_transmits_nothing() -> None:
    """An act that wrote its record and died before its credential write.

    ADR-0148 §14's interrupted-provisioning case in the direction where the record
    is ahead of the keyring. The read is answered with ``None`` rather than with
    an error, so an implementation that only handled a *raising* keyring would go
    on to send with no credential at all.
    """
    ring = await keyring(holds=None)
    channel = scripted(*implicit_tls_script())
    subject = transport(channel, secrets=ring)

    with pytest.raises(BoundCallChangedError, match="keyring holds nothing"):
        await subject.transmit(binding(), ARGUMENTS)

    assert ring.reads != []
    assert channel.written == b""


async def test_the_account_identity_is_never_rendered_in_a_refusal() -> None:
    """ADR-0152 §11's discipline, applied to the neighbouring surface.

    An identity is Tier 1 and a reference is a loggable handle (ADR-0149 §3), so
    the refusal that is *about* an identity mismatch names the reference and
    neither identity — otherwise every such refusal discloses an address into a
    log.
    """
    ring = await keyring()
    records = Records(entry(identity="other@example.invalid"))
    subject = transport(None, records=records, secrets=ring)

    with pytest.raises(BoundCallChangedError) as raised:
        await subject.transmit(binding(), ARGUMENTS)

    assert REFERENCE in str(raised.value)
    assert IDENTITY not in str(raised.value)
    assert "other@example.invalid" not in str(raised.value)
