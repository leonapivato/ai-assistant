"""The shared conformance suites for the transport capability (ADR-0191 §8).

Two Protocols, two suites, and no exemption is available for either: ADR-0021's
Consequences already refused to bargain over this, and ADR-0191 §8 names it again
because the obvious economy — contract the opener, leave the channel untested —
would leave the more dangerous of the two, the object that holds an open
connection, with no conformance suite at all.

Every implementation of :class:`~ai_assistant.core.protocols.OutboundTransport`
and :class:`~ai_assistant.core.protocols.ByteChannel` must pass the suite that
names it. A concrete test subclasses one and supplies the fixtures and the arming
hooks.

**Why the hooks.** Several of ADR-0191 §1's clauses are about what an
implementation does on a path a caller cannot reach from the outside: a connection
that fails under it, a release after an establishment failure, a release after a
cancellation delivered inside the acquisition, a release failure at ``close``
that must be swallowed rather than raised, and the report that swallowing owes,
which goes to an operator rather than to the holder. None of those is arrangeable through
the Protocol — a contract whose whole point is that it exposes no such lever — so
each suite takes the lever from its binding instead, in the shape
``tests/memory``'s cancellation cases already use
(``ai_assistant.testing.cancellation``).

**Every read case says what the far end sent, including when it sent nothing.**
``far_end_sent`` is called exactly once by each case that reads, with ``b""``
where the case is about end of stream, because a stream-backed implementation
cannot distinguish "nothing yet" from "nothing ever" without being told — a
subject left waiting for octets that are not coming would hang rather than fail.

**No assertion message in either suite renders an octet a channel carried.** An
SMTP exchange carries an ``AUTH`` line, and a suite that failed by printing what
was written would put a credential into pytest output and into whatever a failing
CI run keeps (ADR-0191 §8). Where a case must compare octets it compares lengths
or fixed literals of its own making, and the payload case asserts *absence* in a
rendering rather than presence.

Named ``*_contract`` (not ``test_*``) so pytest collects these only via a
``Test``-prefixed subclass, never the abstract bases directly.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import TYPE_CHECKING, Final

import pytest
import structlog

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import TransportError
from ai_assistant.core.logging import configure_logging
from ai_assistant.core.types import TRANSPORT_OCTET_CEILING, TransportEndpoint
from ai_assistant.testing.cancellation import settle

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from contextlib import AbstractContextManager

    from ai_assistant.core.protocols import ByteChannel, OutboundTransport
    from ai_assistant.testing.cancellation import SuspendedCall

#: The endpoint every case here asks for. ``.invalid`` (RFC 6761 §6.4), so a
#: subject that somehow reached a resolver would fail rather than connect.
ENDPOINT: Final = TransportEndpoint(host="mail.example.invalid", port=465, implicit_tls=True)

#: The same host with the upgrade TLS mode, for the one clause that branches on it.
UPGRADE_ENDPOINT: Final = TransportEndpoint(
    host="mail.example.invalid", port=587, implicit_tls=False
)

#: What a case writes when it needs octets that must never be rendered. Shaped
#: like the one line of an SMTP exchange that carries a credential, so a
#: regression that started printing writes prints something a reader recognises.
_SECRET_WRITE: Final = b"AUTH PLAIN AHdvcmtAZXhhbXBsZS5pbnZhbGlkAGFuLWFwcC1wYXNzd29yZA==\r\n"

#: What every binding's armed release failure says, so that "reported by type
#: alone" is assertable rather than assumed. It carries a recipient address —
#: precisely the value ADR-0152 §11 forbids a message on the neighbouring surface
#: to name — because a case can only assert that a log dropped the failure's words
#: if the failure had words worth dropping.
RELEASE_FAILURE_DETAIL: Final = "the far end named work@example.invalid on its way out"


@contextmanager
def structlog_reports(event: str) -> Iterator[list[str]]:
    """Record every ``structlog`` event named ``event``, each rendered whole.

    A convenience for bindings whose implementation reports through the project's
    logging chain, and not part of what
    :meth:`ByteChannelContract.observe_release_reports` requires: the hook owes the
    reports, and an implementation that recorded them by some other route would
    supply its own manager.

    **The level is raised for the duration.** A failed release is reported at
    ``debug`` and importing the package configures the chain at ``info``, so the
    filtering bound logger would drop the event before any processor saw it — and
    a case would then pass on a channel that reported nothing at all. It is put
    back to the import-time default afterwards, so nothing later in the session
    inherits the verbosity. ``tests/tools``' own cancellation-path case found that
    trap first.

    Args:
        event: The event name the implementation reports under.

    Yields:
        One rendering per matching event, filled in once the block has finished.
    """
    reports: list[str] = []
    configure_logging(Settings(log_level="DEBUG"))
    try:
        with structlog.testing.capture_logs() as captured:
            yield reports
        reports.extend(repr(entry) for entry in captured if entry["event"] == event)
    finally:
        configure_logging(Settings(log_level="INFO"))


class ByteChannelContract(ABC):
    """What every ``ByteChannel`` must do (ADR-0191 §1, §4).

    The subject is a channel over a far end that has sent nothing yet and whose
    TLS is not established, which is the state an upgrade endpoint's channel is
    returned in.
    """

    # --- what a binding supplies -------------------------------------------

    @pytest.fixture
    @abstractmethod
    def channel(self) -> ByteChannel:
        """The subject: an open channel, in the clear, over an empty far end."""

    @abstractmethod
    def far_end_sent(self, channel: ByteChannel, octets: bytes) -> None:
        """Make the far end have sent exactly ``octets`` and then closed.

        Called **once** by every case that reads, ``b""`` included. Both halves
        matter: the octets are what the case will read back, and the close is what
        lets a stream-backed subject answer at all rather than waiting for more.

        Args:
            channel: The subject.
            octets: Everything the far end sends, in one go.
        """

    @abstractmethod
    def arm_connection_failure(self, channel: ByteChannel) -> None:
        """Arm the connection under ``channel`` to fail on its next use.

        However this implementation's connection fails — a reset from a socket, a
        scripted refusal from a fake — the *next* read, write and upgrade must
        report it as a ``TransportError``. What the failure is underneath is the
        implementation's business; that it arrives as one type is the contract's.

        Args:
            channel: The subject.
        """

    @abstractmethod
    def arm_release_failure(self, channel: ByteChannel) -> type[BaseException]:
        """Arm an ordinary release failure that :meth:`close` must not raise.

        **The failure's message carries :data:`RELEASE_FAILURE_DETAIL`**, so that
        the case below can assert the implementation's report of it does *not*.
        A failure armed with a message of no consequence would let a channel that
        logged the whole exception pass the payload half of that case.

        Args:
            channel: The subject.

        Returns:
            The type armed. Which type an implementation's release fails with is
            its own business — ADR-0191 §1 says "an ordinary release failure" and
            names no type — so the binding says what it armed rather than the
            suite assuming it.
        """

    @abstractmethod
    def suspend_next_close(self, channel: ByteChannel) -> SuspendedCall:
        """Arm the next ``close`` to suspend inside its release.

        Args:
            channel: The subject.

        Returns:
            The lever this suite waits on and releases.
        """

    @abstractmethod
    def observe_release_reports(
        self, channel: ByteChannel
    ) -> AbstractContextManager[Sequence[str]]:
        """Record what this implementation reports about a failed release.

        The last of the levers a caller cannot reach from the outside: a report
        goes to an operator's logs and not to the holder, so the Protocol offers
        nothing to read it back with. Where the implementation reports through the
        project's logging chain the binding is one line — the event name it
        reports under, handed to :func:`structlog_reports`.

        Args:
            channel: The subject.

        Returns:
            A context manager whose value is one rendering per report the
            implementation made about a failed release while the block ran, each
            the whole of what was recorded. Whole, because which field carries the
            failure's type is the implementation's business while whether its
            message reached the log is the contract's, and a case that read named
            fields could assert only the first.
        """

    # --- §1: read_line's terminator, its end of stream, its ceiling ---------

    async def test_read_line_returns_the_line_including_its_terminator(
        self, channel: ByteChannel
    ) -> None:
        """§1: the terminator is a single ``\\n`` and the line is returned with it.

        Stripping here would be a decision about a protocol the capability does
        not speak, and two implementations disagreeing about it is exactly what
        ADR-0089 §3 says an unmarked signature block would have permitted.
        """
        self.far_end_sent(channel, b"220 ready\r\n250 ok\r\n")

        assert await channel.read_line() == b"220 ready\r\n"

    async def test_read_line_keeps_a_carriage_return_before_the_terminator(
        self, channel: ByteChannel
    ) -> None:
        """§1: a preceding ``\\r`` is the protocol's to strip and not this contract's."""
        self.far_end_sent(channel, b"hello\r\n")

        assert (await channel.read_line()).endswith(b"\r\n")

    async def test_read_line_reports_end_of_stream_as_empty_bytes(
        self, channel: ByteChannel
    ) -> None:
        """§1: empty bytes means end of stream, and means nothing else."""
        self.far_end_sent(channel, b"")

        assert await channel.read_line() == b""

    async def test_read_line_discards_an_unterminated_tail_and_reports_end_of_stream(
        self, channel: ByteChannel
    ) -> None:
        """§1: a line with no terminator is not a reply, whatever octets arrived.

        Reporting it as one would let a truncated stream stand in for an answer —
        a far end that died mid-reply would deliver its half-reply as the verdict.
        """
        self.far_end_sent(channel, b"250 the far end stopped here")

        assert await channel.read_line() == b""

    async def test_read_line_accepts_a_line_of_exactly_the_ceiling(
        self, channel: ByteChannel
    ) -> None:
        """§1: the bound is on the octets *before* the terminator.

        So exactly ``TRANSPORT_OCTET_CEILING`` octets are accepted and come back
        one longer. The suite pins this and the case below it and nothing between
        them, because those two are the only values at which an implementation can
        be off by one.
        """
        self.far_end_sent(channel, b"a" * TRANSPORT_OCTET_CEILING + b"\n")

        assert len(await channel.read_line()) == TRANSPORT_OCTET_CEILING + 1

    async def test_read_line_refuses_a_line_one_octet_past_the_ceiling(
        self, channel: ByteChannel
    ) -> None:
        """§1: a far end sending an unterminated line buys memory from a client.

        And that client is holding a credential, which is why the refusal is a
        ``TransportError`` — a fact about the connection — rather than something
        the holder has to remember to bound for itself.
        """
        self.far_end_sent(channel, b"a" * (TRANSPORT_OCTET_CEILING + 1) + b"\n")

        with pytest.raises(TransportError):
            await channel.read_line()

    # --- §1: read's bounded domain -----------------------------------------

    async def test_read_returns_at_most_the_limit(self, channel: ByteChannel) -> None:
        """§1: at least one and at most ``limit`` octets; a short read is ordinary."""
        self.far_end_sent(channel, b"0123456789")

        assert await channel.read(4) == b"0123"

    async def test_read_reports_end_of_stream_as_empty_bytes(self, channel: ByteChannel) -> None:
        """§1: the same spelling of end of stream ``read_line`` uses."""
        self.far_end_sent(channel, b"")

        assert await channel.read(TRANSPORT_OCTET_CEILING) == b""

    @pytest.mark.parametrize("limit", [0, -1, TRANSPORT_OCTET_CEILING + 1])
    async def test_read_refuses_a_limit_outside_its_domain(
        self, channel: ByteChannel, limit: int
    ) -> None:
        """§1: no spelling of ``limit`` means "read until end of stream".

        The obvious implementation delegates to ``asyncio.StreamReader.read``,
        where ``-1`` is exactly that spelling — so a peer that streams without
        closing would exhaust memory through a method whose name says it is
        bounded. Refusing the whole domain outside ``1..ceiling`` closes it by
        making the unbounded spelling unrepresentable.
        """
        self.far_end_sent(channel, b"0123456789")

        with pytest.raises(ValueError, match="limit"):
            await channel.read(limit)

    @pytest.mark.parametrize("limit", [1, TRANSPORT_OCTET_CEILING])
    async def test_read_accepts_both_ends_of_its_domain(
        self, channel: ByteChannel, limit: int
    ) -> None:
        """§1: the domain is inclusive at both ends."""
        self.far_end_sent(channel, b"0123456789")

        assert await channel.read(limit) != b""

    async def test_a_refused_limit_is_not_a_transport_error(self, channel: ByteChannel) -> None:
        """§1: the two have different subjects, so they are different types.

        A ``TransportError`` says what happened to the connection; the caller's
        own out-of-domain argument says nothing about it. A holder that caught
        ``TransportError`` around a read would otherwise swallow its own defect as
        a network condition.
        """
        self.far_end_sent(channel, b"")

        with pytest.raises(ValueError, match="limit") as raised:
            await channel.read(0)

        assert not isinstance(raised.value, TransportError)

    async def test_read_and_read_line_share_one_cursor(self, channel: ByteChannel) -> None:
        """§1: octets returned by either are never returned again by the other."""
        self.far_end_sent(channel, b"220 ready\r\n")

        assert await channel.read(4) == b"220 "
        assert await channel.read_line() == b"ready\r\n"

    # --- §1: the shared refusal taxonomy -----------------------------------

    async def test_a_failing_connection_is_reported_as_a_transport_error(
        self, channel: ByteChannel
    ) -> None:
        """§1: one type for what happened to the connection, whatever caused it.

        ``TransportError`` is the **shared** refusal type: the production
        implementation and the canonical fake raise it, so a consumer that catches
        it does not have to know which one it was handed. An implementation that
        let its backend's own exception through — a raw ``ConnectionResetError``
        out of a stream reader, say — would make the promise false for exactly the
        failures it exists for, and a holder catching ``TransportError`` around a
        read would miss every real one. Both review lenses found that on ADR-0191's
        implementation round 1.
        """
        self.far_end_sent(channel, b"")
        self.arm_connection_failure(channel)

        with pytest.raises(TransportError):
            await channel.read_line()

    async def test_a_failing_read_is_reported_as_a_transport_error(
        self, channel: ByteChannel
    ) -> None:
        """§1: ``read`` is in the shared taxonomy too, and is not covered by the case above.

        The two methods share a cursor and nothing else — a bounded read and a
        read-to-a-terminator can fail on different code paths, and an
        implementation that converted only the one this suite exercised would pass
        while leaking its backend's own exception from the other. Adversarial and
        architecture review both found that gap on ADR-0191's implementation round
        2.
        """
        self.far_end_sent(channel, b"")
        self.arm_connection_failure(channel)

        with pytest.raises(TransportError):
            await channel.read(1)

    async def test_a_failing_write_is_reported_as_a_transport_error(
        self, channel: ByteChannel
    ) -> None:
        """§1: the same type on the write half, which fails for its own reasons."""
        self.arm_connection_failure(channel)

        with pytest.raises(TransportError):
            await channel.write(b"EHLO example.invalid\r\n")

    async def test_a_refused_upgrade_is_reported_as_a_transport_error(
        self, channel: ByteChannel
    ) -> None:
        """§1, §4: a refused upgrade leaves the channel in the clear.

        The holder's obligation is to write no credential to a channel whose TLS
        state reads false, and it reads that state rather than inferring it — so an
        upgrade that failed has to be both reported *and* visible.
        """
        self.arm_connection_failure(channel)

        with pytest.raises(TransportError):
            await channel.start_tls()

        assert channel.is_secure is False

    # --- §4: the TLS state the holder reads --------------------------------

    async def test_a_channel_in_the_clear_reads_insecure_until_it_is_upgraded(
        self, channel: ByteChannel
    ) -> None:
        """§4: the obligation is the holder's, and this is what it reads.

        ``ai_assistant.tools.egress`` refuses to present a credential on exactly
        this read. It has to come from the channel's own state rather than from
        the order commands were written in, because a holder that inferred it
        would be inferring it from its own behaviour.
        """
        assert channel.is_secure is False

        await channel.start_tls()

        assert channel.is_secure is True

    # --- §1: close ---------------------------------------------------------

    async def test_close_is_idempotent(self, channel: ByteChannel) -> None:
        """§1: a holder closing in a ``finally`` need not track whether it already did."""
        await channel.close()

        await channel.close()

    async def test_close_suppresses_an_ordinary_release_failure(self, channel: ByteChannel) -> None:
        """§1: a channel that cannot be released tells its logs and not its caller.

        This is a rule about exception replacement rather than tidiness. A holder
        closes from a cleanup path, where Python replaces the exception in flight
        with one raised there — so a conforming channel that raised here would
        turn an honest "this may or may not have been delivered" into an internal
        failure, recording a possible disclosure as one that did not happen.
        """
        self.arm_release_failure(channel)

        await channel.close()

    async def test_close_reports_an_ordinary_release_failure_by_type_alone(
        self, channel: ByteChannel
    ) -> None:
        """§1: suppressed is not silent, and the report is the other half of it.

        The case above pins that the failure does not reach the caller. Without
        this one a channel could satisfy the whole suite by discarding it, which
        is the state the clause exists to prevent rather than a tidier version of
        it: an operator with a connection that will not release and no record of
        it anywhere. Deleting the report from either implementation leaves every
        other case here green.

        **By type alone.** An ordinary release failure comes from the far end and
        can carry that far end's own words — a recipient address among them — so
        ADR-0152 §11's discipline over the neighbouring surface governs what may
        be recorded: an error type may be named, a value may not. Exactly one
        report, because a channel with two paths into it has already been observed
        reporting from both.
        """
        armed = self.arm_release_failure(channel)

        with self.observe_release_reports(channel) as reports:
            await channel.close()

        assert len(reports) == 1, reports
        assert armed.__name__ in reports[0]
        assert RELEASE_FAILURE_DETAIL not in reports[0]

    async def test_close_makes_the_channel_safe_and_re_raises_a_cancellation(
        self, channel: ByteChannel
    ) -> None:
        """§1 and ADR-0060 §1: the carve-out is not a softening of the clause above.

        One rule is about a *release failure*, which the caller can do nothing
        with; the other about a *cancellation*, which is the caller's own control
        flow arriving. An earlier draft of ADR-0191 said ``close`` "raises
        nothing" flatly, which obliged a conforming channel to swallow a
        cancellation arriving while it awaited the far end — the orphaned-resource
        failure ADR-0060 exists to prevent.

        The channel is observed *afterwards* rather than the exception merely
        being observed to escape: a case asserting only that ``CancelledError``
        came out passes an implementation that abandoned the release.
        """
        gate = self.suspend_next_close(channel)
        closing = asyncio.ensure_future(channel.close())
        await gate.reached()

        closing.cancel()
        gate.release()
        await settle()

        with pytest.raises(asyncio.CancelledError):
            await closing
        # Safe first, then re-raised: a second close must find nothing to do and
        # must not raise either.
        await channel.close()

    # --- §8: what a failing assertion may render ---------------------------

    async def test_no_rendering_of_the_channel_shows_what_was_written(
        self, channel: ByteChannel
    ) -> None:
        """§8: a double that rendered everything written would print a credential.

        The octets still have to be *recordable* — the egress seam's own protocol
        tests assert on the exact exchange — so the rule is about what renders
        them, not about whether they are captured. It is stated over the whole
        contract rather than over the canonical fake because a second
        implementation printing them would put the credential in the same place.
        """
        await channel.write(_SECRET_WRITE)

        assert b"AUTH PLAIN" not in repr(channel).encode()


class OutboundTransportContract(ABC):
    """What every ``OutboundTransport`` must do (ADR-0191 §1, §3, §4).

    The subject opens channels; the release clauses are what this suite is mostly
    about, because they are the half of the contract a holder cannot check.
    """

    # --- what a binding supplies -------------------------------------------

    @pytest.fixture
    @abstractmethod
    def transport(self) -> OutboundTransport:
        """The subject: a transport that has been asked for nothing yet."""

    @abstractmethod
    def arm_refusal(self, transport: OutboundTransport) -> None:
        """Arm the next open to fail *before* anything is acquired.

        Args:
            transport: The subject.
        """

    @abstractmethod
    def arm_failure_after_acquiring(self, transport: OutboundTransport) -> None:
        """Arm the next open to raise a ``TransportError`` after the resource exists.

        The type is fixed so the case can assert on it; what is on test is the
        **release**, which is unobservable against a failure that happened before
        anything was acquired — that being what :meth:`arm_refusal` models.

        Args:
            transport: The subject.
        """

    @abstractmethod
    def suspend_next_open(self, transport: OutboundTransport) -> SuspendedCall:
        """Arm the next open to suspend while holding what it acquired.

        Args:
            transport: The subject.

        Returns:
            The lever this suite waits on and releases.
        """

    @abstractmethod
    def held_resources(self, transport: OutboundTransport) -> int:
        """How many connection resources this transport acquired and has not released.

        Args:
            transport: The subject.

        Returns:
            The count, an acquisition still inside ``open_channel`` included.
        """

    # --- §1: what an open produces -----------------------------------------

    async def test_open_channel_returns_a_channel_for_the_endpoint_it_was_given(
        self, transport: OutboundTransport
    ) -> None:
        """§1: one method, endpoint in, open duplex channel out."""
        channel = await transport.open_channel(ENDPOINT)

        try:
            assert channel.is_secure is True
        finally:
            await channel.close()

    async def test_an_upgrade_endpoint_yields_a_channel_in_the_clear(
        self, transport: OutboundTransport
    ) -> None:
        """§1, §4: TLS before the greeting where the mode says so, and not otherwise.

        The channel is cleartext until the holder upgrades it, and the capability
        neither performs the upgrade nor can compel it — so the state has to be
        readable and has to differ between the two modes.
        """
        channel = await transport.open_channel(UPGRADE_ENDPOINT)

        try:
            assert channel.is_secure is False
        finally:
            await channel.close()

    async def test_a_refused_open_raises_rather_than_returning_a_channel(
        self, transport: OutboundTransport
    ) -> None:
        """§1: a channel it could not connect or verify is raised over, not returned.

        No holder is ever handed a channel whose state it would have to
        interrogate, which is what lets every consumer treat a returned channel as
        connected.
        """
        self.arm_refusal(transport)

        with pytest.raises(TransportError):
            await transport.open_channel(ENDPOINT)

    # --- §1: the release obligation, and where it stops --------------------

    async def test_an_establishment_failure_releases_what_it_acquired(
        self, transport: OutboundTransport
    ) -> None:
        """§1: nothing else can ever release a resource no channel reached.

        The ordinary half of the clause: a connect that failed after the socket
        existed, an implicit-TLS certificate that did not verify, a channel object
        that could not be constructed. ADR-0060 §1's first clause is unsatisfiable
        at this seam any other way.
        """
        before = self.held_resources(transport)
        self.arm_failure_after_acquiring(transport)

        with pytest.raises(TransportError):
            await transport.open_channel(ENDPOINT)

        assert self.held_resources(transport) == before

    async def test_a_cancellation_inside_the_acquisition_releases_and_is_re_raised(
        self, transport: OutboundTransport
    ) -> None:
        """§1 and ADR-0060 §1, §3: cancelled inside the resource, released first.

        ADR-0060 §3 is explicit that the weaker version is worthless — a case that
        only asserts ``CancelledError`` escapes passes an implementation that
        raised correctly and orphaned the socket anyway. So the resource is read
        rather than the exception, and the assertion is about what was left behind.

        **It is read at the moment the caller's call completes**, which is the
        half a reading taken afterwards cannot make. ADR-0191 §1 fixes an order —
        "releases what it acquired first", then "re-raises it after the release" —
        and an implementation that hands the cancellation over and tidies up
        somewhere later satisfies a reading taken after everything settles while
        leaving the caller holding a cancellation over a socket that is still
        open. Both review lenses found exactly that shape in this lane's
        production binding on round 5; the snapshot below is what refuses it, and
        it constrains only the *order*, not when an implementation chooses to
        release.
        """
        before = self.held_resources(transport)
        gate = self.suspend_next_open(transport)
        opening = asyncio.ensure_future(transport.open_channel(ENDPOINT))
        await gate.reached()
        at_completion: list[int] = []
        opening.add_done_callback(lambda _: at_completion.append(self.held_resources(transport)))

        opening.cancel()
        gate.release()
        await settle()

        with pytest.raises(asyncio.CancelledError):
            await opening
        assert at_completion == [before]
        assert self.held_resources(transport) == before

    async def test_the_release_obligation_stops_at_the_return(
        self, transport: OutboundTransport
    ) -> None:
        """§1, §3: after the return the channel is closed by whoever opened it.

        The division is by *where the failure lands*, and there is no case
        belonging to both. An earlier draft of ADR-0191 offered a refused upgrade
        and a line overrun as things ``open_channel`` must clean up after — both
        of which happen on a channel the holder already has, which made the clause
        unsatisfiable for its own examples.
        """
        before = self.held_resources(transport)
        channel = await transport.open_channel(ENDPOINT)

        assert self.held_resources(transport) == before + 1

        await channel.close()

        assert self.held_resources(transport) == before
