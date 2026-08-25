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
from ai_assistant.core.types import TRANSPORT_OCTET_CEILING
from ai_assistant.testing import FakeByteChannel, FakeOutboundTransport, TransportAttempt

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

    def deliver(self, channel: ByteChannel, octets: bytes) -> None:
        """Append ``octets`` to what the far end has sent.

        Args:
            channel: The subject.
            octets: What arrives on the stream.
        """
        _fake(channel).deliver(octets)

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


async def test_a_failure_after_acquiring_is_recorded_as_an_unserved_attempt() -> None:
    """§8: the record distinguishes refused from served, wherever the failure fell."""
    transport = FakeOutboundTransport()
    transport.fail_after_acquiring(TransportError("the certificate did not verify"))

    with pytest.raises(TransportError):
        await transport.open_channel(ENDPOINT)

    assert transport.attempts == (TransportAttempt(endpoint=ENDPOINT, served=False),)


async def test_queued_channels_are_served_in_order() -> None:
    """The arranger decides what a case's far end says, one channel per open."""
    first, second = FakeByteChannel(), FakeByteChannel()
    transport = FakeOutboundTransport().serve(first, second)

    assert await transport.open_channel(ENDPOINT) is first
    assert await transport.open_channel(ENDPOINT) is second
    assert transport.channels == (first, second)


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
    channel.fail_write_after(b"\r\n.\r\n", error=ConnectionResetError("the far end went"))

    with pytest.raises(ConnectionResetError):
        await channel.write(b"the message\r\n.\r\n")

    assert channel.written == b"the message\r\n.\r\n"


async def test_an_exhausted_far_end_can_stop_answering_either_way() -> None:
    """A clean close and a reset arrive at a caller as different types."""
    clean = FakeByteChannel()
    reset = FakeByteChannel()
    reset.fail_when_exhausted(ConnectionResetError("reset on the greeting"))

    assert await clean.read_line() == b""
    with pytest.raises(ConnectionResetError):
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
