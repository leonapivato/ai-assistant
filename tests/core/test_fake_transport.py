"""The canonical transport fakes pass their shared conformance suites (ADR-0191 §8).

This is what lets every other subsystem trust
:class:`~ai_assistant.testing.FakeOutboundTransport` and
:class:`~ai_assistant.testing.FakeByteChannel` as stand-ins, and what makes
milestone 25's exit arm an instrument rather than an arrangement: the fake it
reads is held to the same contract the production implementation is.

Beside the two bindings are the properties that are the *fakes' own* — the
attempt record ADR-0191 §8 states over them, and the payload discipline the same
section makes a Tier 0 clause rather than tidiness.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from transport_contract import (
    ENDPOINT,
    UPGRADE_ENDPOINT,
    ByteChannelContract,
    OutboundTransportContract,
)

from ai_assistant.core.errors import TransportError
from ai_assistant.core.types import TRANSPORT_OCTET_CEILING, TransportEndpoint
from ai_assistant.testing import FakeByteChannel, FakeOutboundTransport, TransportAttempt
from ai_assistant.testing.cancellation import settle

if TYPE_CHECKING:
    from ai_assistant.core.protocols import ByteChannel, OutboundTransport
    from ai_assistant.testing.cancellation import SuspendedCall


def _fake(channel: ByteChannel) -> FakeByteChannel:
    """Narrow the suite's Protocol-typed subject back to the fake it is.

    The suite is written against ``ByteChannel`` because it holds every
    implementation; the arming hooks are the fake's own. Asserting the type here
    rather than casting keeps a mis-wired binding a loud failure.

    Args:
        channel: The subject the suite handed back.

    Returns:
        The same object, typed as the fake.
    """
    assert isinstance(channel, FakeByteChannel)
    return channel


def _fake_transport(transport: OutboundTransport) -> FakeOutboundTransport:
    """Narrow the suite's Protocol-typed subject back to the fake it is.

    Args:
        transport: The subject the suite handed back.

    Returns:
        The same object, typed as the fake.
    """
    assert isinstance(transport, FakeOutboundTransport)
    return transport


class TestFakeByteChannelContract(ByteChannelContract):
    """The canonical channel fake, run through the channel contract."""

    @pytest.fixture
    def channel(self) -> ByteChannel:
        """A fresh channel in the clear over an empty far end.

        Returns:
            The canonical fake.
        """
        return FakeByteChannel()

    def far_end_sent(self, channel: ByteChannel, octets: bytes) -> None:
        """Put ``octets`` on the fake's inbound stream.

        The close needs no modelling here: this fake's inbound buffer is complete
        by construction, so a read past the end of it *is* end of stream.

        Args:
            channel: The subject.
            octets: Everything the far end sends.
        """
        _fake(channel).deliver(octets)

    def arm_connection_failure(self, channel: ByteChannel) -> None:
        """Arm the next read, write and upgrade to report a failed connection.

        Args:
            channel: The subject.
        """
        subject = _fake(channel)
        subject.fail_when_exhausted(TransportError("the peer reset the connection"))
        subject.fail_write_after(b"", error=TransportError("the peer reset the connection"))
        subject.fail_upgrade_with(TransportError("the endpoint declined the upgrade"))

    def arm_release_failure(self, channel: ByteChannel) -> None:
        """Arm an ordinary release failure for ``close`` to swallow.

        Args:
            channel: The subject.
        """
        _fake(channel).fail_release_with(OSError("the far end had already gone"))

    def suspend_next_close(self, channel: ByteChannel) -> SuspendedCall:
        """Arm the next ``close`` to suspend inside its release.

        Args:
            channel: The subject.

        Returns:
            The lever the suite drives.
        """
        return _fake(channel).suspend_next_close()


class TestFakeOutboundTransportContract(OutboundTransportContract):
    """The canonical opener fake, run through the opener contract."""

    @pytest.fixture
    def transport(self) -> OutboundTransport:
        """A transport that has been asked for nothing yet.

        Returns:
            The canonical fake.
        """
        return FakeOutboundTransport()

    def arm_refusal(self, transport: OutboundTransport) -> None:
        """Arm a refusal that happens before anything is acquired.

        Args:
            transport: The subject.
        """
        _fake_transport(transport).refuse_with(TransportError("the endpoint is unreachable"))

    def arm_failure_after_acquiring(self, transport: OutboundTransport) -> None:
        """Arm a failure that happens once the modelled socket exists.

        Args:
            transport: The subject.
        """
        _fake_transport(transport).fail_after_acquiring(
            TransportError("the certificate did not verify")
        )

    def suspend_next_open(self, transport: OutboundTransport) -> SuspendedCall:
        """Arm the next open to suspend while holding what it acquired.

        Args:
            transport: The subject.

        Returns:
            The lever the suite drives.
        """
        return _fake_transport(transport).suspend_next_open()

    def held_resources(self, transport: OutboundTransport) -> int:
        """The modelled sockets acquired and not released.

        Args:
            transport: The subject.

        Returns:
            The count.
        """
        return _fake_transport(transport).open_sockets


# --- the fakes' own obligations (ADR-0191 §8) -------------------------------


async def test_every_attempt_is_recorded_with_the_endpoint_it_named() -> None:
    """§8: in order, with the ``TransportEndpoint`` each attempt named."""
    transport = FakeOutboundTransport()

    await (await transport.open_channel(ENDPOINT)).close()
    await (await transport.open_channel(UPGRADE_ENDPOINT)).close()

    assert transport.attempts == (
        TransportAttempt(endpoint=ENDPOINT, served=True),
        TransportAttempt(endpoint=UPGRADE_ENDPOINT, served=True),
    )


async def test_a_refused_attempt_is_recorded_before_it_is_refused() -> None:
    """§8: "did not reach the world" and "was never asked" are different facts.

    An exit arm that could not tell them apart could not distinguish a system that
    refused from a system whose code path was never entered — which is the whole
    reading a milestone's zero has to survive. ``Connector`` in
    ``tests/world/m23_harness.py`` had the instinct first; this makes it the
    canonical shape.
    """
    transport = FakeOutboundTransport()
    transport.refuse_with(TransportError("this fake opens nothing"))

    with pytest.raises(TransportError):
        await transport.open_channel(ENDPOINT)

    assert transport.attempts == (TransportAttempt(endpoint=ENDPOINT, served=False),)


async def test_a_standing_refusal_holds_until_it_is_lifted() -> None:
    """§8: armed to refuse is an arrangement, not a one-shot.

    A transport that refuses everything is one whose recorded attempts are the
    whole account of what a system reached for, which is what a milestone arm
    wants; a one-shot arming would quietly start serving on the second call.
    """
    transport = FakeOutboundTransport()
    transport.refuse_with(TransportError("this fake opens nothing"))

    for _ in range(2):
        with pytest.raises(TransportError):
            await transport.open_channel(ENDPOINT)

    transport.serve_again()
    await (await transport.open_channel(ENDPOINT)).close()

    assert [attempt.served for attempt in transport.attempts] == [False, False, True]


def _frames(error: BaseException) -> int:
    """How many frames an exception's traceback carries.

    Args:
        error: The exception to measure.

    Returns:
        The length of its traceback chain, which is what grows without bound when
        one instance is raised more than once.
    """
    depth, frame = 0, error.__traceback__
    while frame is not None:
        depth, frame = depth + 1, frame.tb_next
    return depth


class _NarrowerTransportError(TransportError):
    """A refusal type an arrangement might arm, so the clone's type can be read.

    ``TransportError`` is the shared taxonomy (ADR-0191 §1), and nothing forbids
    an arrangement arming something narrower to assert on. A clone that flattened
    it to the base class would leave a case catching this type never firing, which
    is why the case below arms one.
    """


@pytest.mark.parametrize(
    "refusal_type",
    [
        pytest.param(TransportError, id="the-shared-type"),
        pytest.param(_NarrowerTransportError, id="a-subclass"),
    ],
)
async def test_a_standing_refusal_raises_a_fresh_error_with_a_traceback_of_its_own(
    refusal_type: type[TransportError],
) -> None:
    """A standing arming is raised many times, and one instance would grow each time.

    ``raise exc`` on an object that has already been raised sets its
    ``__traceback__`` to a new traceback whose tail is the old one, and every one
    of those frames keeps its locals alive. A milestone arm opens against a
    standing refusal repeatedly, and the caller at this seam is
    ``SmtpEgressTransport._send``, whose locals include a credential — so the
    accumulation is not only unbounded, it retains exactly what this seam is most
    careful about. Adversarial review found it on round 12.

    What a case can read is unchanged: the words **and the concrete type** are the
    arming's, which is why the subclass row is here — a clone that built a bare
    ``TransportError`` would pass the other row and silently stop firing a case
    that catches something narrower. Adversarial review noted the type on round 13
    and that the case did not check it on round 14.

    Args:
        refusal_type: What the arrangement arms.
    """
    transport = FakeOutboundTransport()
    armed = refusal_type("this fake opens nothing")
    transport.refuse_with(armed)

    raised: list[TransportError] = []
    for _ in range(3):
        with pytest.raises(refusal_type) as refusal:
            await transport.open_channel(ENDPOINT)
        raised.append(refusal.value)

    assert [type(error) for error in raised] == [refusal_type] * 3
    assert [error.args for error in raised] == [armed.args] * 3
    assert armed.__traceback__ is None  # the arming itself is never the one raised
    assert len({id(error) for error in raised}) == 3
    assert [_frames(error) for error in raised] == [_frames(raised[0])] * 3


async def test_a_failure_after_acquiring_is_recorded_as_an_unserved_attempt() -> None:
    """§8: the record distinguishes refused from served, wherever the failure fell."""
    transport = FakeOutboundTransport()
    transport.fail_after_acquiring(TransportError("the certificate did not verify"))

    with pytest.raises(TransportError):
        await transport.open_channel(ENDPOINT)

    assert transport.attempts == (TransportAttempt(endpoint=ENDPOINT, served=False),)


async def test_queued_channels_are_served_in_order() -> None:
    """The arranger decides what a case's far end says, one channel per open."""
    first, second = FakeByteChannel(secure=True), FakeByteChannel(secure=True)
    transport = FakeOutboundTransport().serve(first, second)

    assert await transport.open_channel(ENDPOINT) is first
    assert await transport.open_channel(ENDPOINT) is second
    assert transport.channels == (first, second)


async def test_two_opens_in_flight_take_their_channels_in_call_order() -> None:
    """One open, one channel, and the queue is read at the attempt.

    Adversarial review found the earlier shape on round 3: the queue was read
    *after* the suspension, so a second open started while the first was held
    walked off with the first's scripted replies. With matching TLS modes the two
    silently swapped exchanges; with differing ones both raised an arrangement
    error over channels queued in exactly the right order.
    """
    first, second = FakeByteChannel(secure=True), FakeByteChannel(secure=True)
    transport = FakeOutboundTransport().serve(first, second)
    gate = transport.suspend_next_open()

    held = asyncio.ensure_future(transport.open_channel(ENDPOINT))
    await gate.reached()
    following = asyncio.ensure_future(transport.open_channel(ENDPOINT))
    await settle()
    gate.release()

    assert await held is first
    assert await following is second


@pytest.mark.parametrize(
    "second_fails_first",
    [pytest.param(False, id="in-reservation-order"), pytest.param(True, id="in-reverse")],
)
async def test_two_reservations_given_back_keep_the_order_they_were_queued_in(
    *, second_fails_first: bool
) -> None:
    """Two opens in flight, both cancelled, and the queue must survive it.

    A reservation given back is owed to the next open — but with two of them in
    flight, pushing each onto the *head* as it unwinds reverses the pair whenever
    they unwind in the order they were taken. The next open would then be served
    the second arrangement's scripted replies while every case still read as
    though it had the first, which is the failure mode a consumer is least likely
    to notice. Adversarial review found it on round 14.

    Both unwind orders are rows because only one of them is wrong, and a case
    that ran the harmless one alone would have passed the bug.

    Args:
        second_fails_first: Whether the later reservation unwinds before the
            earlier one.
    """
    first, second = FakeByteChannel(secure=True), FakeByteChannel(secure=True)
    transport = FakeOutboundTransport().serve(first, second)

    earlier_gate = transport.suspend_next_open()
    earlier = asyncio.ensure_future(transport.open_channel(ENDPOINT))
    await earlier_gate.reached()
    later_gate = transport.suspend_next_open()
    later = asyncio.ensure_future(transport.open_channel(ENDPOINT))
    await later_gate.reached()

    unwinding = [(later, later_gate), (earlier, earlier_gate)]
    if not second_fails_first:
        unwinding.reverse()
    for opening, gate in unwinding:
        opening.cancel()
        gate.release()
        await settle()
        with pytest.raises(asyncio.CancelledError):
            await opening

    assert await transport.open_channel(ENDPOINT) is first
    assert await transport.open_channel(ENDPOINT) is second


async def test_a_cancelled_open_puts_its_queued_channel_back() -> None:
    """The open that reserved it never handed it to anybody.

    So the next open is the one it was queued for, rather than the arrangement
    silently losing an exchange a later case was counting on.
    """
    first, second = FakeByteChannel(secure=True), FakeByteChannel(secure=True)
    transport = FakeOutboundTransport().serve(first, second)
    gate = transport.suspend_next_open()
    opening = asyncio.ensure_future(transport.open_channel(ENDPOINT))
    await gate.reached()

    opening.cancel()
    gate.release()
    with pytest.raises(asyncio.CancelledError):
        await opening

    assert await transport.open_channel(ENDPOINT) is first


async def test_a_closed_channel_is_never_served() -> None:
    """§1: what an open returns is an *open* duplex channel.

    A holder handed a closed one would be testing against something no opener
    returns — the canonical fake certifying behaviour that does not exist, which
    is the one failure a canonical fake must not have.
    """
    closed = FakeByteChannel(secure=True)
    await closed.close()
    transport = FakeOutboundTransport().serve(closed)

    with pytest.raises(ValueError, match="closed channel"):
        await transport.open_channel(ENDPOINT)


async def test_the_same_channel_cannot_be_queued_twice() -> None:
    """§3: one open, one channel; this contract carries no pool.

    Queuing the same object twice would otherwise model a transport that hands two
    callers the same connection — and after the first holder closed it, an open
    that reported ``served=True`` for a channel that was already shut. Refused at
    the arrangement, where the arranger is looking, rather than at the handout.
    """
    channel = FakeByteChannel(secure=True)

    with pytest.raises(ValueError, match="queued twice"):
        FakeOutboundTransport().serve(channel, channel)


async def test_a_channel_reserved_by_an_open_in_flight_cannot_be_served_again() -> None:
    """§3: the duplicate guard covers reservations, not only completed handouts.

    Adversarial and architecture review both found the gap on round 4: a channel
    reserved by a suspended open was not yet in the served list, so a second open
    could take the same object and closing either caller's channel would close
    both.
    """
    channel = FakeByteChannel(secure=True)
    transport = FakeOutboundTransport().serve(channel)
    gate = transport.suspend_next_open()
    held = asyncio.ensure_future(transport.open_channel(ENDPOINT))
    await gate.reached()

    with pytest.raises(ValueError, match="reserved by an open in flight"):
        transport.serve(channel)
    assert transport.reserved == (channel,)

    gate.release()
    assert await held is channel


async def test_a_channel_upgraded_while_its_open_was_suspended_is_not_served() -> None:
    """§1: what is handed over is read at the handoff, not only at the reservation.

    An arrangement holds the object it queued, so it can upgrade it while the open
    is held — and the reservation's reading is stale from that moment. Serving it
    anyway would report ``served=True`` for a handout no conforming opener could
    make: a channel already under TLS for an endpoint whose mode is the upgrade
    one. Adversarial review found the gap on round 5.
    """
    channel = FakeByteChannel(secure=False)
    transport = FakeOutboundTransport().serve(channel)
    gate = transport.suspend_next_open()
    held = asyncio.ensure_future(transport.open_channel(UPGRADE_ENDPOINT))
    await gate.reached()
    await channel.start_tls()

    gate.release()

    with pytest.raises(ValueError, match="is being served"):
        await held
    assert transport.open_sockets == 0
    assert [attempt.served for attempt in transport.attempts] == [False]


async def test_a_channel_closed_while_its_open_was_suspended_is_not_served() -> None:
    """§1: the same reading, over the other mutation an arrangement can make.

    ``open_channel`` promises an *open* duplex channel; a holder handed a closed
    one would be testing against something no opener returns, and the reservation
    cannot see a close that happens after it.
    """
    channel = FakeByteChannel(secure=True)
    transport = FakeOutboundTransport().serve(channel)
    gate = transport.suspend_next_open()
    held = asyncio.ensure_future(transport.open_channel(ENDPOINT))
    await gate.reached()
    await channel.close()

    gate.release()

    with pytest.raises(ValueError, match="closed channel"):
        await held
    assert transport.open_sockets == 0
    assert transport.reserved == ()


async def test_an_armed_failure_belongs_to_the_open_that_started_next() -> None:
    """The one-shot arming is taken at the attempt, not at the completion.

    Adversarial review found the earlier shape on round 4: a second open beginning
    while the first was held consumed the failure armed for the first, so a
    concurrent case exercised the wrong call in both directions.
    """
    transport = FakeOutboundTransport().serve(
        FakeByteChannel(secure=True), FakeByteChannel(secure=True)
    )
    gate = transport.suspend_next_open()
    transport.fail_after_acquiring(TransportError("the certificate did not verify"))
    held = asyncio.ensure_future(transport.open_channel(ENDPOINT))
    await gate.reached()

    following = asyncio.ensure_future(transport.open_channel(ENDPOINT))
    await settle()
    gate.release()

    with pytest.raises(TransportError):
        await held
    assert (await following).is_secure is True


@pytest.mark.parametrize(
    ("endpoint", "secure"),
    [
        pytest.param(ENDPOINT, False, id="cleartext-channel-for-implicit-tls"),
        pytest.param(UPGRADE_ENDPOINT, True, id="secure-channel-for-an-upgrade"),
    ],
)
async def test_a_queued_channel_whose_tls_contradicts_the_endpoint_is_refused(
    endpoint: TransportEndpoint, *, secure: bool
) -> None:
    """§1: an implicit-TLS open returns a secure channel and an upgrade open does not.

    A fake that served either for the other would let a consumer be tested against
    a state the production capability can never produce — the canonical fake
    certifying behaviour that does not exist, which is the one failure a canonical
    fake must not have. Both review lenses found it on round 1.

    It is the arranger's error rather than a connection's, so it is a
    ``ValueError`` and never a ``TransportError``.
    """
    transport = FakeOutboundTransport().serve(FakeByteChannel(secure=secure))

    with pytest.raises(ValueError, match="conforming transport"):
        await transport.open_channel(endpoint)


async def test_forgetting_attempts_keeps_every_arming_in_place() -> None:
    """What a calibration needs: fire the instrument, then read from zero.

    An instrument demonstrated live must not leave its demonstration in the
    reading that follows, and re-arming after the reset would be a second
    arrangement a case could get wrong.
    """
    transport = FakeOutboundTransport()
    transport.refuse_with(TransportError("this fake opens nothing"))
    with pytest.raises(TransportError):
        await transport.open_channel(ENDPOINT)

    transport.forget_attempts()

    assert transport.attempts == ()
    with pytest.raises(TransportError):
        await transport.open_channel(ENDPOINT)


async def test_forgetting_attempts_while_one_is_in_flight_discards_it_safely() -> None:
    """A reset discards an in-flight attempt rather than raising out of its completion.

    Adversarial review found the earlier shape on round 2: the completing call
    wrote back through an *index* into the attempt list, so a reset that emptied
    the list left the open raising ``IndexError`` — having already handed its
    modelled socket to a channel nobody received, so ``open_sockets`` stayed at
    one forever.
    """
    transport = FakeOutboundTransport()
    gate = transport.suspend_next_open()
    opening = asyncio.ensure_future(transport.open_channel(ENDPOINT))
    await gate.reached()

    transport.forget_attempts()
    gate.release()
    channel = await opening

    assert transport.attempts == ()
    assert transport.open_sockets == 1
    await channel.close()
    assert transport.open_sockets == 0


def test_no_rendering_of_the_transport_names_an_endpoint_or_an_octet() -> None:
    """§8: the attempt record carries no payload and no credential.

    The transport's own rendering is counts, so a failing assertion on it prints
    nothing a connection was carrying. What each attempt named is still readable
    from :attr:`~ai_assistant.testing.TransportAttempt.endpoint` by a case that
    asks for it.
    """
    assert repr(FakeOutboundTransport()) == "FakeOutboundTransport(attempts=0, open_sockets=0)"


async def test_the_channel_records_what_was_written_without_rendering_it() -> None:
    """§8: the octets have to be recordable and must not be rendered.

    The seam's own protocol tests assert on the exact exchange, so the rule is
    about where they live and what renders them, not about whether they are
    captured.
    """
    channel = FakeByteChannel()

    await channel.write(b"AUTH PLAIN AHdvcmsAcGFzc3dvcmQ=\r\n")

    assert channel.written == b"AUTH PLAIN AHdvcmsAcGFzc3dvcmQ=\r\n"
    assert "AUTH" not in repr(channel)
    assert repr(channel) == "FakeByteChannel(secure=False, written_octets=33, closed=False)"


async def test_an_armed_write_failure_records_the_octets_before_it_raises() -> None:
    """A failing flush leaves a payload that may already be on the wire.

    A double that dropped the write would model a guarantee no real channel
    offers, and the seam's indeterminate-transmission window is stated over
    exactly this.
    """
    channel = FakeByteChannel()
    channel.fail_write_after(b"\r\n.\r\n", error=TransportError("the far end went"))

    with pytest.raises(TransportError):
        await channel.write(b"the message\r\n.\r\n")

    assert channel.written == b"the message\r\n.\r\n"


async def test_an_exhausted_far_end_can_stop_answering_either_way() -> None:
    """A clean close and a reset arrive at a caller as different types."""
    clean = FakeByteChannel()
    reset = FakeByteChannel()
    reset.fail_when_exhausted(TransportError("reset on the greeting"))

    assert await clean.read_line() == b""
    with pytest.raises(TransportError):
        await reset.read_line()


async def test_a_refused_upgrade_leaves_the_channel_in_the_clear() -> None:
    """§4: the holder's refusal is the property, and it reads ``is_secure``."""
    channel = FakeByteChannel()
    channel.fail_upgrade_with(TransportError("the endpoint declined the upgrade"))

    with pytest.raises(TransportError):
        await channel.start_tls()

    assert channel.is_secure is False


async def test_a_suppressed_release_failure_is_counted_rather_than_lost() -> None:
    """``close`` swallows it, and the fake still lets a case see that it happened."""
    channel = FakeByteChannel()
    channel.fail_release_with(OSError("the far end had already gone"))

    await channel.close()

    assert channel.suppressed_release_failures == 1
    assert channel.closed is True


async def test_the_ceiling_is_one_constant_both_halves_refuse_against() -> None:
    """§1: the fake and the production implementation refuse the same inputs.

    Held as one named constant in ``core`` rather than chosen per implementation,
    so a consumer tested against one behaves against the other.
    """
    channel = FakeByteChannel()
    channel.deliver(b"a" * (TRANSPORT_OCTET_CEILING + 1) + b"\n")

    with pytest.raises(TransportError):
        await channel.read_line()
    # Nothing was consumed: the refusal to buffer leaves the stream where a
    # caller could still observe it, which is what `asyncio` does too.
    assert await channel.read(TRANSPORT_OCTET_CEILING) == b"a" * TRANSPORT_OCTET_CEILING


async def test_a_cancelled_open_leaves_no_attempt_recorded_as_served() -> None:
    """ADR-0060 §1 read off the record rather than off the exception."""
    transport = FakeOutboundTransport()
    gate = transport.suspend_next_open()
    opening = asyncio.ensure_future(transport.open_channel(ENDPOINT))
    await gate.reached()

    opening.cancel()
    gate.release()
    with pytest.raises(asyncio.CancelledError):
        await opening

    assert transport.attempts == (TransportAttempt(endpoint=ENDPOINT, served=False),)
    assert transport.open_sockets == 0
