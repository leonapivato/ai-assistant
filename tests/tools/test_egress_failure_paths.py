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
    arguments,
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
    TransportPinError,
)
from ai_assistant.tools.send_email import SEND_EMAIL, SendEmail

if TYPE_CHECKING:
    from egress_transport_harness import Keyring

    from ai_assistant.tools.egress import SmtpEgressTransport

#: The arguments the rows send or try to send, so that what differs between them is
#: the arrangement rather than the payload. The recipient is in its **supplied**
#: form, which is what a call's arguments carry.
ARGUMENTS: Final = arguments()

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


async def test_the_registered_callable_can_read_a_credential_only_through_its_transport() -> None:
    """The other half of the same row: a denial reads nothing, by *position*.

    This case used to assert that ``SendEmail`` refused outright, on the ground
    that the seam was undesignated. ADR-0154 §1 designates it and the callable now
    transmits, so what has to be checked instead is the property the refusal was
    standing in for: ADR-0148 §7 gates a credential read **by position** — inside a
    callable reached by ``ToolInvoker.invoke`` after ADR-0029 §2's three checks —
    and a ``DENY`` constructs no ``ToolCall`` at all (the case above), so no
    callable runs and no keyring is touched.

    What makes that a property rather than a coincidence is that ``SendEmail``
    holds *nothing else*: no ``Secrets`` face, no store, no endpoint, no reference.
    The only object in reach of a keyring is the transport it was handed, so a call
    that never reaches ``transmit`` cannot read a credential by any route — which
    is checked here by reaching ``transmit`` and watching the read happen only
    there.
    """
    assert SendEmail.__slots__ == ("_transport",), (
        "a second attribute here would be a second route to a keyring, outside the "
        "position ADR-0148 §7 gates the read at"
    )

    subject, ring = await _refusing()
    tool = SendEmail(subject)
    assert ring.reads == []

    # Reaching the transport is what reads; the endpoint is wrong, so it refuses
    # before it gets there, and the keyring is still untouched.
    with pytest.raises(TransportPinError):
        await tool.invoke_bound(
            ARGUMENTS,
            idempotency_key=None,
            egress_binding=binding(endpoint=f"smtps://{OTHER_HOST}:465"),
        )

    assert ring.reads == []


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
        await subject.transmit(binding(endpoint=f"smtps://{OTHER_HOST}:465"), ARGUMENTS)

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
        await subject.transmit(binding(), ARGUMENTS)

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
        await subject.transmit(binding(), ARGUMENTS)

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

    await subject.transmit(bound, arguments(to=("Alice@Example.Invalid",)))

    assert "RCPT TO:<Alice@example.invalid>" in channel.commands()
    assert [span.destination.supplied for span in bound.spans if span.destination] == [
        "Alice@Example.Invalid"
    ]


# --------------------------------------------------------------------------- #
# 4. "a failed resolution does not fall through to a send"
# --------------------------------------------------------------------------- #


async def test_an_unresolved_name_cannot_reach_the_wire_even_in_an_argument() -> None:
    """The seam's half of ADR-0148 §5's third clause, refused twice over.

    Resolution is a registered egress call of its own (§5), so a *failed* one
    produces no identifier, and the request that would have consumed it is refused
    before the ruling — the binder's half, tested there. What is left for this seam
    is the substitution the same clause forbids: "no component substitutes the
    unresolved name, a cached value, or a default".

    An unresolved name is refused here at the **first** of the two gates it would
    have to pass: it has no canonical form at all, so it never reaches the
    comparison against the bound set. Both refusals are real and the earlier one
    is the one that fires, which is worth knowing — an implementation that only
    compared strings would refuse it too, but would also refuse a *resolved*
    recipient written in another case, which is the round-3 defect one row up.
    """
    subject, ring = await _refusing()

    with pytest.raises(BoundCallChangedError, match="will not canonicalise"):
        await subject.transmit(binding(), arguments(to=("#team",)))

    assert ring.reads == []


# --------------------------------------------------------------------------- #
# 5. "destination, payload and transport cannot change between authorisation and
#     transmission"
# --------------------------------------------------------------------------- #


async def test_a_recipient_added_after_the_ruling_is_refused_rather_than_transmitted() -> None:
    """#93 item 1's substitution, and ADR-0148 §4's third clause at the seam."""
    subject, ring = await _refusing()
    added = arguments(to=("Alice@Example.Invalid", "mallory@example.invalid"))

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
        await subject.transmit(bound, ARGUMENTS)

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
        await subject.transmit(binding(describes=("subject",)), ARGUMENTS)

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
            arguments(subject=same, body=same),
        )


async def test_the_payload_is_the_arguments_and_there_is_no_second_copy_to_substitute() -> None:
    """The round-3 blocker, closed structurally rather than by a better check.

    An earlier signature took a rendered message beside the binding and checked it
    against the description by **extent**, which two texts of equal length pass
    identically: a body substituted after the ruling — same length, different
    words — reached the wire. The repair is not a stronger comparison; it is
    removing the second copy. The message is derived here from
    ``ActionRequest.parameters``, which ADR-0021 §1 binds by ``parameters_digest``,
    ``authorises`` compares, and ADR-0029 §2 re-checks on a revalidated detached
    copy before the callable is reached — so there is nothing left to substitute.

    Asserted by sending two calls whose payloads differ only in content, and
    reading what each put on the wire.
    """
    for body in ("attached, as promised", "aTTACHED, AS pROMISED"):
        channel = ScriptedChannel(*implicit_tls_script())
        subject = transport(channel, secrets=await keyring())

        await subject.transmit(binding(body=body), arguments(body=body))

        assert body in channel.payload()


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"attachment": "x"}, id="an-argument-this-seam-does-not-transmit"),
        pytest.param({"to": "alice@example.invalid"}, id="recipients-not-a-list"),
        pytest.param({"to": [1]}, id="a-recipient-that-is-not-text"),
        pytest.param({"subject": 7}, id="a-subject-that-is-not-text"),
        pytest.param({"body": ["a", "b"]}, id="a-body-that-is-not-text"),
        pytest.param({"to": []}, id="no-recipient-at-all"),
    ],
)
async def test_arguments_that_are_not_a_submission_are_refused(payload: dict[str, object]) -> None:
    """The seam re-establishes every shape it depends on, rather than assuming it.

    ADR-0145 checks the arguments against the tool's schema at construction, before
    the ruling, so none of these is reachable on the ordinary path. They are
    checked anyway because "a request built by a bypass reaches the seam" (ADR-0145
    §3) — which is ADR-0029 §2's revalidation posture, and is why an argument this
    seam does not transmit is a refusal rather than a silently ignored key. A key
    nobody transmits is a span no description covers.
    """
    subject, ring = await _refusing()
    call = {**ARGUMENTS, **payload}

    with pytest.raises(BoundCallChangedError):
        await subject.transmit(binding(), call)  # type: ignore[arg-type]  # deliberately ill-shaped

    assert ring.reads == []


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("ok\r\nBcc: mallory@example.invalid", id="crlf"),
        pytest.param("ok\nBcc: mallory@example.invalid", id="bare-lf"),
        pytest.param("ok\rBcc: mallory@example.invalid", id="bare-cr"),
        pytest.param("\nleading", id="leading-lf"),
    ],
)
async def test_a_header_field_carrying_a_line_break_is_refused_before_anything_is_spent(
    text: str,
) -> None:
    r"""Refusal hygiene, not a disclosure control, and the distinction is the point.

    **This is not header injection, and that was checked rather than assumed.**
    ``EmailMessage`` already refuses a header value containing ``CR`` or ``LF`` —
    "Header values may not contain linefeed or carriage return characters", for
    ``\r\n`` and for a bare ``\n`` alike — so a smuggled ``Bcc:`` never reached the
    wire and no unauthorised recipient was ever reachable this way. Had the stdlib
    accepted it, this would be a blocker about an added recipient rather than a
    major about a refusal's type and timing.

    What the stdlib's refusal does not do is arrive well. It fires inside the
    renderer, which runs **after** the credential has been presented and the
    envelope accepted, and it escapes as a bare ``ValueError`` that ADR-0029 §3
    records as ``INTERNAL`` — so the call reads as a broken tool rather than as a
    refused one, and a credential was spent on a call that could never be
    performed. ADR-0148 §1's third clause is the ground for moving it earlier: a
    request that cannot be completed is "refused **before the ruling**", and
    ADR-0145's precedent is the same move one field over.

    So the assertions are about *where* and *what*, not merely that it failed: the
    refusal is typed, and no record is read, no credential fetched, no connection
    opened. Found by adversarial review on round 4.
    """
    subject, ring = await _refusing()

    with pytest.raises(BoundCallChangedError, match="line break"):
        await subject.transmit(binding(subject=text), arguments(subject=text))

    assert ring.reads == []


async def test_a_body_may_carry_line_breaks_because_a_body_is_not_a_header() -> None:
    """The other half, without which the check above would be a defect of its own.

    A body is content, and RFC 5321 §4.5.2's transparency is what makes its line
    breaks safe. Refusing them would leave the seam unable to send an ordinary
    multi-line email, so the header-field list is narrow on purpose and this is
    what holds it narrow.
    """
    body = "first line\nsecond line\n.third looks like a terminator"
    channel = ScriptedChannel(*implicit_tls_script())
    subject = transport(channel, secrets=await keyring())

    await subject.transmit(binding(body=body), arguments(body=body))

    assert "second line" in channel.payload()
    assert "\r\n..third" in channel.payload()


async def test_a_binding_naming_another_connection_is_refused_on_the_same_identity() -> None:
    """The reference is compared, not only the identity (ADR-0148 §6).

    Two connectable records can hold one identity — ``BoundAccount``'s own
    docstring says so, and is why ADR-0148 §6 binds an account by **two** facts.
    Where they do, a binding for account B's connection checked by identity alone
    passes against account A's record, and the message goes out under A's
    credential although the approval named B. The identity comparison cannot see
    it, because it is comparing the right identity against the wrong record: the
    record is read *by the registration's* reference.

    Found by adversarial review on round 1, which also named what no case varied —
    the binding's reference alone. This is that case.
    """
    subject, ring = await _refusing()

    with pytest.raises(TransportPinError, match="not registered for"):
        await subject.transmit(binding(reference="conn-0002"), ARGUMENTS)

    assert ring.reads == []


async def test_a_transport_endpoint_that_moved_is_refused() -> None:
    """The third axis of the same row, and the one ADR-0148 §6 moved into the binding.

    An earlier draft of that section left the endpoint outside the request, so
    "nothing compared it and no refusal could fire". It is compared here.
    """
    subject, ring = await _refusing()

    with pytest.raises(TransportPinError):
        await subject.transmit(binding(endpoint="smtps://mail.example.invalid:2525"), ARGUMENTS)

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
        await subject.transmit(binding(), ARGUMENTS)

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
        await subject.transmit(binding(), ARGUMENTS)


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
        await subject.transmit(binding(), ARGUMENTS)


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
            arguments(to=("Alice@example.invalid", "bob@example.invalid")),
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
            arguments(to=("Alice@example.invalid", "bob@example.invalid")),
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
        await subject.transmit(binding(), ARGUMENTS)

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
        await subject.transmit(binding(), ARGUMENTS)

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
        await subject.transmit(binding(), ARGUMENTS)


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(ConnectionResetError("the peer reset the connection"), id="reset"),
        pytest.param(TimeoutError("the read timed out"), id="timeout"),
        pytest.param(OSError("the socket went away"), id="oserror"),
    ],
)
async def test_a_read_that_raises_after_the_payload_is_indeterminate_too(
    failure: Exception,
) -> None:
    """A socket error after the terminator is not evidence about the far end.

    Found by adversarial review on round 1: only ``EgressTransportError`` was
    caught, so a ``ConnectionResetError`` from the channel escaped, and the
    invocation seam classifies an escaped exception as ``FAILED``/``INTERNAL``
    (ADR-0029 §3) — a possibly-completed disclosure recorded as a call that
    failed. The exception says this end stopped listening and says nothing about
    what the endpoint did with the octets it already has.

    Three types because they arrive from three real places and only one of them
    is obvious; ``TimeoutError`` is a subclass of ``OSError`` and is included so
    that a later narrowing of the ``except`` clause fails here rather than in
    production.
    """
    channel = ScriptedChannel(*implicit_tls_script()[:-2], on_exhausted=failure)
    subject = transport(channel, secrets=await keyring())

    with pytest.raises(IndeterminateTransmissionError, match="unknown"):
        await subject.transmit(binding(), ARGUMENTS)

    assert channel.payload().endswith("\r\n.\r\n")


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(ConnectionResetError("the peer reset during the flush"), id="reset"),
        pytest.param(TimeoutError("the flush timed out"), id="timeout"),
    ],
)
async def test_a_write_that_fails_while_sending_the_payload_is_indeterminate(
    failure: Exception,
) -> None:
    """The window opens at the write, not after it.

    Found by adversarial review on round 2, after round 1's repair had covered
    only the *read*. A stream writer queues octets to the transport and then
    awaits the flush, so an exception from that flush does not establish that
    nothing left this device — and no channel this seam could be handed can
    establish it either. Reporting it as a failure would let a retry duplicate a
    disclosure that already happened, which is the harm ADR-0017 §3's fourth
    outcome exists to keep visible.

    So the conservative answer is the only honest one: the message reached the
    transport, and what the endpoint did with it is unknown.
    """
    channel = ScriptedChannel(*implicit_tls_script(), on_payload_write=failure)
    subject = transport(channel, secrets=await keyring())

    with pytest.raises(IndeterminateTransmissionError, match="unknown"):
        await subject.transmit(binding(), ARGUMENTS)

    assert channel.payload().endswith("\r\n.\r\n")


async def test_a_socket_error_before_the_payload_stays_a_failure() -> None:
    """The other side of the same asymmetry, which is what makes it a decision.

    Before any octet of the payload is written, a reset is a call that provably
    did nothing, and ADR-0029 §4's classification of it as a failure is correct.
    Converting *that* into an indeterminate outcome would make every network blip
    an unresolvable step, which is the opposite error and is just as expensive.
    """
    channel = ScriptedChannel(on_exhausted=ConnectionResetError("reset on the greeting"))
    subject = transport(channel, secrets=await keyring())

    with pytest.raises(ConnectionResetError):
        await subject.transmit(binding(), ARGUMENTS)

    assert channel.payload() == ""


async def test_an_unterminated_multi_line_reply_is_refused_rather_than_buffered() -> None:
    """A far end cannot buy unbounded memory from a client holding a credential.

    Found by adversarial review on round 1. Every line here is well under the
    per-line octet bound, so that bound does not cover this input at all: what is
    unbounded is the *count*. The reply never terminates, and an implementation
    that only limited line length would accumulate until the process died — while
    the credential sat in hand, one command away from being presented.
    """
    channel = ScriptedChannel(
        "220 mail.example.invalid ESMTP ready",
        "\n".join(f"250-EXT{index}" for index in range(500)),
    )
    subject = transport(channel, secrets=await keyring())

    with pytest.raises(TransportPinError, match="continuation lines"):
        await subject.transmit(binding(), ARGUMENTS)

    assert CREDENTIAL not in channel.written.decode("ascii")


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
        (binding(endpoint=f"smtps://{OTHER_HOST}:465"), ARGUMENTS),
        (binding(), arguments(to=("mallory@example.invalid",))),
        (binding(describes=()), ARGUMENTS),
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
