"""ADR-0017 §3's last condition, one test per row of the matrix it names.

> **Failure paths are tested, not just the happy path** — at minimum: denial
> performs no credential read and no network I/O; a hostile base URL and a
> cross-host redirect are both refused without the credential travelling;
> canonicalisation boundaries resolve as the protocol says; a failed resolution
> does not fall through to a send; destination, payload and transport cannot
> change between authorisation and transmission; a multi-recipient call with one
> unauthorised member fails entirely; a crash-pending record is reconcilable.

Seven rows, seven sections below, in §3's own order and named after its own words,
so that the ADR designating the seam can walk the list rather than reconstruct it.
#93 item 6 restates the same matrix and adds "a timeout is distinguishable from a
success", which is the seventh section's second half.

**Two of the seven are stated differently for SMTP than #83 states them for HTTP,
and the difference is written down rather than papered over.** SMTP has no base
URL and no redirect. The nearest thing to a hostile base URL is a bound endpoint
that is not the tool's configured one, and the nearest thing to a redirect is RFC
5321 §3.4's ``251``/``551`` forward path — a reply naming a mailbox at a *different*
host. Both are tested here as what they are; neither is dressed up as the HTTP
shape it is analogous to.

Nothing here opens a socket: see :mod:`egress_transport_harness`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest
from egress_transport_harness import (
    CREDENTIAL,
    ENDPOINT,
    IDENTITY,
    REFERENCE,
    SLOT,
    TOOL_ID,
    Records,
    ScriptedChannel,
    binding,
    entry,
    implicit_tls_script,
    keyring,
    transport,
)

from ai_assistant.core.errors import ConnectionStoreError
from ai_assistant.core.types import (
    ActionRequest,
    DataTier,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    ToolCall,
)
from ai_assistant.tools.destinations import DestinationCanonicalisationError, canonicalise
from ai_assistant.tools.destinations import DestinationProtocol as SeamProtocol
from ai_assistant.tools.egress import (
    BoundCallChangedError,
    EgressTransportError,
    IndeterminateTransmissionError,
    OutboundEmail,
    TransportPinError,
)
from ai_assistant.tools.send_email import SEND_EMAIL, SendEmail, UndesignatedSeamError

if TYPE_CHECKING:
    from egress_transport_harness import Keyring

    from ai_assistant.tools.egress import SmtpEgressTransport

#: The one message the rows send or try to send, so that what differs between them
#: is the arrangement rather than the payload.
MESSAGE: Final = OutboundEmail(
    to=("Alice@example.invalid",), subject="quarterly report", body="attached, as promised"
)

#: A host that is not the pinned one, used wherever a case needs a second host.
OTHER_HOST: Final = "relay.attacker.invalid"

#: A fixed instant: nothing here reads a clock (`CONTRIBUTING.md`, determinism).
DECIDED_AT: Final = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)


async def _refusing(
    *, records: Records | None = None, holds: str | None = CREDENTIAL
) -> tuple[SmtpEgressTransport, Keyring]:
    """A transport whose connector fails the test if it is ever called.

    Args:
        records: The connection store; defaults to one active record.
        holds: What the keyring holds under the record's slot.

    Returns:
        The transport and the recording keyring, so a case can assert on both.
    """
    ring = await keyring(holds=holds)
    return transport(None, records=records, secrets=ring), ring


# --------------------------------------------------------------------------- #
# 1. "denial performs no credential read and no network I/O"
# --------------------------------------------------------------------------- #


def test_a_denial_performs_no_credential_read_and_no_network_io() -> None:
    """The property is a consequence of where the read is, not a rule to remember.

    ADR-0148 §7 makes this structural rather than procedural: a ``DENY`` produces
    no ``ToolCall`` (ADR-0029 §2), so no callable runs, so nothing on the far side
    of ``invoke`` reads anything. This asserts the load-bearing half — that the
    call is **unconstructable** — because a test that merely showed a denied call
    reading nothing would be testing an implementation's manners.

    The transport is where the credential read and the socket both live, and it
    is reached from nowhere but a callable, so an unconstructable call is a
    credential unread and a connection unopened by construction.
    """
    request = ActionRequest(
        tool=SEND_EMAIL,
        parameters={"to": ["a@example.invalid"], "subject": "s", "body": "b"},
        step_id="step-1",
    )
    denied = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.DENY, reason="the user said no"),
        id="d-1",
        decided_at=DECIDED_AT,
    )

    with pytest.raises(ValueError, match="authoris"):
        ToolCall(request=request, decision=denied)


async def test_the_undesignated_callable_still_refuses_without_reading_anything() -> None:
    """The other half of the same row: the *registered* path transmits nothing.

    ``SendEmail`` is what a registry would bind, and it still refuses — this lane
    wires no transport into it, because the seam is undesignated and ADR-0017 §2's
    fourteen conditions are the designating ADR's to attest.
    """
    with pytest.raises(UndesignatedSeamError, match="undesignated"):
        await SendEmail()({"to": ["a@example.invalid"]}, idempotency_key=None)


# --------------------------------------------------------------------------- #
# 2. "a hostile base URL and a cross-host redirect are both refused without the
#     credential travelling"
# --------------------------------------------------------------------------- #


async def test_a_bound_endpoint_that_is_not_the_configured_one_is_refused() -> None:
    """SMTP's form of #83's hostile base URL, refused before anything is read.

    The comparison is textual and happens before the endpoint is even parsed, so a
    binding naming another host cannot reach a parser, a resolver or a socket. It
    is the first thing ``transmit`` does for exactly that reason.
    """
    subject, ring = await _refusing()

    with pytest.raises(TransportPinError, match=r"not.*configured to use"):
        await subject.transmit(binding(endpoint=f"smtps://{OTHER_HOST}:465"), MESSAGE)

    assert ring.reads == []


async def test_a_cross_host_forward_path_is_refused_and_never_followed() -> None:
    """RFC 5321 §3.4's ``551``: SMTP's only in-protocol analogue of a redirect.

    **What "the credential does not travel" means here, stated honestly.** By the
    time a ``RCPT TO`` draws a forward path the credential has already been
    presented to the *pinned* endpoint, which is where the ruling said it should
    go. What must not happen is it travelling to the host the forward path names,
    and that is what is asserted: no second connection is opened, no octet
    mentioning that host is ever written, and no ``DATA`` follows.
    """
    channel = ScriptedChannel(
        "220 mail.example.invalid ESMTP ready",
        "250-mail.example.invalid\n250 AUTH PLAIN",
        "235 2.7.0 authentication succeeded",
        "250 2.1.0 sender ok",
        f"551 5.1.6 User not local; please try <alice@{OTHER_HOST}>",
        "221 2.0.0 closing connection",
    )
    subject = transport(channel, secrets=await keyring())

    with pytest.raises(TransportPinError, match="forward path"):
        await subject.transmit(binding(), MESSAGE)

    written = channel.written.decode("ascii")
    assert OTHER_HOST not in written
    assert "DATA" not in written
    assert channel.closed


async def test_the_other_forward_path_reply_is_refused_the_same_way() -> None:
    """``251`` is the accepting form of the same indirection and is refused too.

    It reads as a success — "User not local; will forward" — which is exactly why
    it needs its own row: an implementation branching on ``2xx`` would treat it as
    delivery to the approved recipient and record a disclosure that went
    elsewhere.
    """
    channel = ScriptedChannel(
        "220 mail.example.invalid ESMTP ready",
        "250-mail.example.invalid\n250 AUTH PLAIN",
        "235 2.7.0 authentication succeeded",
        "250 2.1.0 sender ok",
        f"251 2.1.5 User not local; will forward to <alice@{OTHER_HOST}>",
    )
    subject = transport(channel, secrets=await keyring())

    with pytest.raises(TransportPinError, match="forward path"):
        await subject.transmit(binding(), MESSAGE)

    assert "DATA" not in channel.written.decode("ascii")


# --------------------------------------------------------------------------- #
# 3. "canonicalisation boundaries resolve as the protocol says"
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("supplied", "canonical"),
    [
        pytest.param("Alice@Example.Invalid", "Alice@example.invalid", id="domain-folds"),
        pytest.param("alice@EXAMPLE.INVALID", "alice@example.invalid", id="domain-folds-whole"),
        pytest.param("ALICE@example.invalid", "ALICE@example.invalid", id="local-part-does-not"),
    ],
)
def test_canonicalisation_folds_the_domain_and_never_the_local_part(
    supplied: str, canonical: str
) -> None:
    """RFC 5321 §2.4 exactly: the domain is not case sensitive and the local part is.

    #93 item 3 names both directions of the error and this is the boundary between
    them — folding the local part lets a grant for one address authorise another,
    and refusing to fold the domain gives the inverse failure.
    """
    assert canonicalise(SeamProtocol.SMTP, supplied).canonical == canonical


@pytest.mark.parametrize(
    "supplied",
    [
        pytest.param("#team", id="a-name-needing-resolution"),
        pytest.param('"quoted local"@example.invalid', id="quoted-local-part"),
        pytest.param("alice@[192.0.2.1]", id="address-literal"),
        pytest.param("alice@example.invalid, bob@example.invalid", id="two-in-one"),
        pytest.param("Alice <alice@example.invalid>", id="display-name"),
    ],
)
def test_a_form_whose_equivalence_is_unproven_has_no_canonical_form(supplied: str) -> None:
    """ADR-0148 §2's exactness default, in its refusing direction.

    Each of these is a form whose equivalence to another the protocol does not
    establish, so the seam refuses rather than asserting one. ADR-0148 §1's third
    clause then refuses the whole request **before the ruling**, which is why no
    user is ever asked about a call carrying one.
    """
    with pytest.raises(DestinationCanonicalisationError):
        canonicalise(SeamProtocol.SMTP, supplied)


async def test_the_wire_carries_the_canonical_form_and_the_record_keeps_the_supplied_one() -> None:
    """ADR-0148 §14's alias case, read at the seam that transmits.

    The binding carries both forms per occurrence; the envelope carries the
    canonical one. An implementation that had dropped the supplied form would
    still pass this — which is why the binding is asserted too, and why ADR-0148
    §14 states the reconstruction failure separately.
    """
    channel = ScriptedChannel(*implicit_tls_script())
    subject = transport(channel, secrets=await keyring())
    bound = binding(recipients=(("Alice@Example.Invalid", "Alice@example.invalid"),))

    await subject.transmit(
        bound,
        OutboundEmail(
            to=("Alice@example.invalid",), subject="quarterly report", body="attached, as promised"
        ),
    )

    assert "RCPT TO:<Alice@example.invalid>" in channel.commands()
    assert [span.destination.supplied for span in bound.spans if span.destination] == [
        "Alice@Example.Invalid"
    ]


# --------------------------------------------------------------------------- #
# 4. "a failed resolution does not fall through to a send"
# --------------------------------------------------------------------------- #


async def test_an_unresolved_name_cannot_reach_the_wire_even_in_a_message() -> None:
    """The seam's half of ADR-0148 §5's third clause.

    Resolution is a registered egress call of its own (§5), so a *failed* one
    produces no identifier, and a request that would have consumed it is refused
    before the ruling — which is the binder's half and is tested there. What is
    left for this seam is the substitution the same clause forbids: "no component
    substitutes the unresolved name, a cached value, or a default". So a message
    carrying the unresolved name against a binding that does not is refused, no
    credential is read, and no connection is opened.
    """
    subject, ring = await _refusing()

    with pytest.raises(BoundCallChangedError, match="bound canonical destination set"):
        await subject.transmit(
            binding(),
            OutboundEmail(to=("#team",), subject="quarterly report", body="attached, as promised"),
        )

    assert ring.reads == []


# --------------------------------------------------------------------------- #
# 5. "destination, payload and transport cannot change between authorisation and
#     transmission"
# --------------------------------------------------------------------------- #


async def test_a_recipient_added_after_the_ruling_is_refused_rather_than_transmitted() -> None:
    """#93 item 1's substitution, and ADR-0148 §4's third clause at the seam."""
    subject, ring = await _refusing()
    added = OutboundEmail(
        to=("Alice@example.invalid", "mallory@example.invalid"),
        subject="quarterly report",
        body="attached, as promised",
    )

    with pytest.raises(BoundCallChangedError, match="bound canonical destination set"):
        await subject.transmit(binding(), added)

    assert ring.reads == []


async def test_a_recipient_dropped_after_the_ruling_is_refused_too() -> None:
    """Both directions, because only one of them is the obvious one.

    ADR-0148 §4's second clause forbids narrowing as well as widening: "a message
    approved as *to Alice and Bob* is a different message from the same text *to
    Alice only* — a reply-all that quietly becomes a reply is a disclosure
    decision made by a filter", and the audit record of the narrowed call is
    perfectly consistent with itself.
    """
    subject, ring = await _refusing()
    bound = binding(
        recipients=(
            ("Alice@example.invalid", "Alice@example.invalid"),
            ("bob@example.invalid", "bob@example.invalid"),
        )
    )

    with pytest.raises(BoundCallChangedError, match="bound canonical destination set"):
        await subject.transmit(bound, MESSAGE)

    assert ring.reads == []


async def test_a_payload_span_the_description_does_not_cover_is_refused() -> None:
    """ADR-0148 §6's callable-side clause: no approver saw the extra span.

    "A callable that finds itself about to transmit a span the description does
    not cover refuses instead, and no approver is shown a description narrower
    than the payload." The binding here describes the subject and not the body,
    which is the omission that would otherwise reach the wire unaccounted for.
    """
    subject, ring = await _refusing()

    with pytest.raises(BoundCallChangedError, match="does not cover"):
        await subject.transmit(binding(describes=("subject",)), MESSAGE)

    assert ring.reads == []


async def test_a_second_undescribed_span_cannot_borrow_another_spans_extent() -> None:
    """The coverage check is a multiset, and this is why.

    A body and a subject of equal length would let a single described span cover
    both if extents were matched as a set. They are matched as a multiset, so a
    payload carrying two spans against a description carrying one is refused
    however the lengths line up.
    """
    subject, _ = await _refusing()
    same = "identical"

    with pytest.raises(BoundCallChangedError, match="does not cover"):
        await subject.transmit(
            binding(subject=same, body=same, describes=("subject",)),
            OutboundEmail(to=("Alice@example.invalid",), subject=same, body=same),
        )


async def test_a_transport_endpoint_that_moved_is_refused() -> None:
    """The third axis of the same row, and the one ADR-0148 §6 moved into the binding.

    An earlier draft of that section left the endpoint outside the request, so
    "nothing compared it and no refusal could fire". It is compared here.
    """
    subject, ring = await _refusing()

    with pytest.raises(TransportPinError):
        await subject.transmit(binding(endpoint="smtps://mail.example.invalid:2525"), MESSAGE)

    assert ring.reads == []


async def test_a_reprovisioning_landing_inside_the_credential_read_discards_it() -> None:
    """ADR-0148 §6's post-read clause, on the interleaving it is written for.

    The revision moves across the read, so the credential in hand may be the
    predecessor's. It is discarded and nothing is transmitted — and the *identity*
    is unchanged in this arrangement on purpose, because an implementation
    comparing identities alone would pass.
    """
    ring = await keyring()
    records = Records(entry(revision=1), entry(revision=2))
    subject = transport(None, records=records, secrets=ring)

    with pytest.raises(BoundCallChangedError, match="changed across the credential read"):
        await subject.transmit(binding(), MESSAGE)

    assert records.reads == [REFERENCE, REFERENCE]


async def test_an_a_to_b_to_a_sequence_across_the_read_is_caught_by_the_revision() -> None:
    """ADR-0148 §6's round-4 repair: the ABA problem, which the revision closes.

    The account is provisioned away and back again across the credential read, so
    both identity comparisons see the bound account. Only the revision — never
    reused, never decreasing — records that anything happened.
    """
    ring = await keyring()
    records = Records(entry(revision=1), entry(revision=3))
    subject = transport(None, records=records, secrets=ring)

    with pytest.raises(BoundCallChangedError, match="changed across the credential read"):
        await subject.transmit(binding(), MESSAGE)


async def test_a_second_read_that_cannot_be_answered_is_treated_as_a_change() -> None:
    """ "A read that cannot be answered is treated as a changed one" (ADR-0148 §6).

    Fail-closed, and deliberately *unlike* the first read, whose store error
    propagates untouched: by this point the credential is in hand, so a caller
    that saw the store's error and retried would retry with a live credential and
    no verified account.
    """
    ring = await keyring()
    records = Records(entry(), ConnectionStoreError("the store is unreadable"))
    subject = transport(None, records=records, secrets=ring)

    with pytest.raises(BoundCallChangedError, match="changed across the credential read"):
        await subject.transmit(binding(), MESSAGE)


# --------------------------------------------------------------------------- #
# 6. "a multi-recipient call with one unauthorised member fails entirely"
# --------------------------------------------------------------------------- #


async def test_a_far_end_refusing_one_recipient_fails_the_whole_call() -> None:
    """No ``DATA`` follows a refused ``RCPT TO``, and no remainder is delivered to.

    #93 item 2: "Delivering to the authorised subset silently sends a message the
    user never approved the shape of, and partial success is the hardest failure
    to notice afterwards." The second recipient is refused by the endpoint, and
    the first — already accepted — receives nothing, because the message is never
    sent at all.
    """
    channel = ScriptedChannel(
        "220 mail.example.invalid ESMTP ready",
        "250-mail.example.invalid\n250 AUTH PLAIN",
        "235 2.7.0 authentication succeeded",
        "250 2.1.0 sender ok",
        "250 2.1.5 recipient ok",
        "550 5.1.1 no such user",
        "221 2.0.0 closing connection",
    )
    subject = transport(channel, secrets=await keyring())
    bound = binding(
        recipients=(
            ("Alice@example.invalid", "Alice@example.invalid"),
            ("bob@example.invalid", "bob@example.invalid"),
        )
    )

    with pytest.raises(BoundCallChangedError, match="authorised whole"):
        await subject.transmit(
            bound,
            OutboundEmail(
                to=("Alice@example.invalid", "bob@example.invalid"),
                subject="quarterly report",
                body="attached, as promised",
            ),
        )

    assert "DATA" not in channel.written.decode("ascii")


async def test_no_narrower_set_is_constructed_from_the_remainder() -> None:
    """The refusal is total: nothing retries with the members that were accepted.

    Asserted over the channel rather than over the exception, because "fails
    entirely" is a claim about what was *not* written and an implementation that
    raised after quietly sending would satisfy a type assertion.
    """
    channel = ScriptedChannel(
        "220 mail.example.invalid ESMTP ready",
        "250-mail.example.invalid\n250 AUTH PLAIN",
        "235 2.7.0 authentication succeeded",
        "250 2.1.0 sender ok",
        "250 2.1.5 recipient ok",
        "550 5.1.1 no such user",
    )
    subject = transport(channel, secrets=await keyring())
    bound = binding(
        recipients=(
            ("Alice@example.invalid", "Alice@example.invalid"),
            ("bob@example.invalid", "bob@example.invalid"),
        )
    )

    with pytest.raises(BoundCallChangedError):
        await subject.transmit(
            bound,
            OutboundEmail(
                to=("Alice@example.invalid", "bob@example.invalid"),
                subject="quarterly report",
                body="attached, as promised",
            ),
        )

    written = channel.written.decode("ascii")
    assert written.count("MAIL FROM") == 1
    assert written.count("RCPT TO") == 2
    assert "DATA" not in written


# --------------------------------------------------------------------------- #
# 7. "a crash-pending record is reconcilable, and a timeout is distinguishable
#     from a success"
# --------------------------------------------------------------------------- #


async def test_a_send_interrupted_after_the_payload_is_indeterminate() -> None:
    """The one window in which acceptance is unknowable, reported as itself.

    ADR-0017 §3: "Otherwise a timeout is indistinguishable from a successful
    disclosure." The message and its terminator are written and the endpoint's
    verdict never arrives, so the honest answer is that nobody knows — and
    ADR-0148 §9 maps that onto the step's ``INDETERMINATE``, which ADR-0014 §4's
    recovery scan is the reconciliation path for. A designated seam adds no
    reconciliation path of its own, which is why nothing here invents a store.
    """
    channel = ScriptedChannel(*implicit_tls_script()[:-2])
    subject = transport(channel, secrets=await keyring())

    with pytest.raises(IndeterminateTransmissionError, match="unknown"):
        await subject.transmit(binding(), MESSAGE)

    assert channel.payload().endswith("\r\n.\r\n")


async def test_indeterminate_is_not_a_refusal_and_cannot_be_caught_as_one() -> None:
    """The type split is the whole of what makes the distinction usable.

    Every :class:`~ai_assistant.tools.egress.EgressTransportError` is a refusal
    that transmitted nothing; an indeterminate send transmitted something nobody
    can account for. Collapsing the second into the first would let a caller's
    ``except EgressTransportError`` read an unknown disclosure as one that did not
    happen, which is precisely the confusion ADR-0017 §3's last clause exists to
    prevent.
    """
    assert not issubclass(IndeterminateTransmissionError, EgressTransportError)
    assert issubclass(BoundCallChangedError, EgressTransportError)
    assert issubclass(TransportPinError, EgressTransportError)


async def test_a_refused_send_is_distinguishable_from_an_indeterminate_one() -> None:
    """Both halves of the distinction, exercised against one arrangement.

    A ``DATA`` the endpoint refuses is a refusal — no octet of the payload was
    written — while a verdict that never arrives is indeterminate. An
    implementation that reported both the same way would leave an auditor unable
    to tell a rejected message from a possibly-delivered one.
    """
    refusing = ScriptedChannel(
        "220 mail.example.invalid ESMTP ready",
        "250-mail.example.invalid\n250 AUTH PLAIN",
        "235 2.7.0 authentication succeeded",
        "250 2.1.0 sender ok",
        "250 2.1.5 recipient ok",
        "552 5.3.4 message too large",
    )
    subject = transport(refusing, secrets=await keyring())

    with pytest.raises(BoundCallChangedError, match="nothing was sent"):
        await subject.transmit(binding(), MESSAGE)

    assert refusing.payload() == ""


async def test_a_non_250_verdict_after_the_payload_is_also_indeterminate() -> None:
    """A rejection *after* the message was written is not a clean failure.

    The octets left this device. Whether the endpoint queued them for any
    recipient before answering is not knowable from here, so this is reported the
    same way a missing verdict is — the conservative direction, and the one
    ADR-0029 §4 takes for a side-effecting call whose effect is unknown.
    """
    channel = ScriptedChannel(*implicit_tls_script()[:-2], "451 4.3.0 try again later")
    subject = transport(channel, secrets=await keyring())

    with pytest.raises(IndeterminateTransmissionError, match="unknown"):
        await subject.transmit(binding(), MESSAGE)


# --------------------------------------------------------------------------- #
# What no row above would catch on its own
# --------------------------------------------------------------------------- #


async def test_no_refusal_message_renders_a_credential_a_recipient_or_a_slot() -> None:
    """ADR-0152 §11's discipline, over every refusal this suite can produce.

    A refusal is the failure path most likely to be logged and least likely to be
    read before it is, so the values it may name are enumerated rather than left
    to each message's author: the tool id, the connection reference, an endpoint
    host, a reply code and a count.
    """
    forbidden = (CREDENTIAL, SLOT.key, IDENTITY, "Alice@example.invalid")
    subject, _ = await _refusing()

    for arrangement in (
        (binding(endpoint=f"smtps://{OTHER_HOST}:465"), MESSAGE),
        (
            binding(),
            OutboundEmail(
                to=("mallory@example.invalid",),
                subject="quarterly report",
                body="attached, as promised",
            ),
        ),
        (binding(describes=()), MESSAGE),
    ):
        with pytest.raises(EgressTransportError) as raised:
            await subject.transmit(*arrangement)
        message = str(raised.value)
        assert TOOL_ID in message
        assert not any(value in message for value in forbidden), message


def test_the_tool_the_registry_would_bind_still_declares_what_it_discloses() -> None:
    """A transmitting tool declares a non-empty ``discloses`` (ADR-0148 §8).

    Without it, ADR-0021 §5's floor does not bite, the call can be auto-granted,
    and the approver ADR-0017 §3 requires is nobody. It is checked here rather
    than left to the declaration's own tests because this suite is what a
    designating ADR reads, and a tool that transmits while declaring nothing is
    the evasion §8 calls "otherwise available and undetectable".
    """
    assert SEND_EMAIL.discloses == (DataTier.PERSONAL,)
    assert SEND_EMAIL.side_effecting
    assert ENDPOINT.startswith("smtps://")
