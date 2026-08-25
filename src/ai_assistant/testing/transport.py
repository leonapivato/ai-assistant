"""The canonical fakes for the injected transport capability (ADR-0191 §8).

Two Protocols mean two triads, and these are their canonical implementations:
:class:`FakeOutboundTransport` for
:class:`~ai_assistant.core.protocols.OutboundTransport` and
:class:`FakeByteChannel` for
:class:`~ai_assistant.core.protocols.ByteChannel`. Neither opens anything and
neither imports a transport-bearing module — the whole point of the capability is
that a holder handed one of these has no route to the world, so a fake that could
reach one would be the thing it exists to disprove.

**They are what makes milestone 25's exit writable at all.** #1427 states the exit
over "the fake transport, not a grep": a test builds the deployment the
composition root builds, hands it one of these, drives a tool at the world, and
reads whether an attempt was recorded. Before ADR-0191 there was no such object —
only per-test doubles, each one somebody's arrangement, and a fake for a
``tools``-private Protocol could not live here at all (``ai_assistant.testing``
imports ``core`` and nothing else).

**What is recorded, and where.** :class:`FakeOutboundTransport` records *attempts*
— the endpoint each named and whether it was served or refused — and carries no
payload and no credential, because an attempt record is what a milestone arm
reads and pytest prints. The octets are held one level down by
:class:`FakeByteChannel`, which needs them (the seam's own protocol tests assert
on the exact SMTP exchange) and renders them nowhere: an SMTP exchange carries an
``AUTH`` line, so a double that printed everything written would put a credential
into pytest output and into whatever a failing CI run keeps.

**"Did not reach the world" and "was never asked" are different facts**, so the
attempt is recorded *before* the refusal that follows it. ``Connector`` in
``tests/world/m23_harness.py`` had that instinct first — "a transmission this
system began is recorded whether or not any byte could have left" — and ADR-0191
§8 makes it the canonical shape rather than one harness's arrangement.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Self, final

import structlog

from ai_assistant.core.errors import TransportError
from ai_assistant.core.types import TRANSPORT_OCTET_CEILING
from ai_assistant.testing.cancellation import LoopSuspension

if TYPE_CHECKING:
    from ai_assistant.core.protocols import ByteChannel
    from ai_assistant.core.types import TransportEndpoint

_log: Final = structlog.get_logger(__name__)

#: The line terminator :meth:`FakeByteChannel.read_line` reads to. One ``\n``,
#: because that is what the contract fixes; a preceding ``\r`` is the protocol's
#: to strip and not this channel's.
_TERMINATOR: Final = b"\n"


@final
@dataclass(frozen=True, slots=True)
class TransportAttempt:
    """One request for a channel, as :class:`FakeOutboundTransport` records it.

    **It carries the endpoint and the outcome, and nothing else** (ADR-0191 §8).
    No payload, no credential, and nothing a failing assertion would render that
    the connection was carrying — those live on the channel, which never renders
    them either.

    Attributes:
        endpoint: The :class:`~ai_assistant.core.types.TransportEndpoint` this
            attempt named.
        served: Whether a channel was produced. ``False`` where the transport was
            armed to refuse, or where establishment failed after the modelled
            socket existed — which is a different fact from never having been
            asked, and is the distinction a milestone arm reads.
    """

    endpoint: TransportEndpoint
    served: bool


@final
@dataclass(slots=True)
class _Pending:
    """One attempt while it is still being decided, and after.

    A *mutable* record, so completing an attempt does not have to find it in a
    list again — :meth:`FakeOutboundTransport.forget_attempts` may have emptied
    that list while an open was suspended, and an index into it would then be an
    ``IndexError`` raised out of a completing call. Adversarial review found that
    on ADR-0191's implementation round 2. A reset that discards an in-flight
    attempt is now exactly a reset that discards it: the holder is orphaned and
    the completion writes to nothing anybody reads.

    Attributes:
        endpoint: The endpoint this attempt named.
        served: Whether a channel was produced.
    """

    endpoint: TransportEndpoint
    served: bool = False


@final
class FakeByteChannel:
    """A :class:`~ai_assistant.core.protocols.ByteChannel` with no socket under it.

    The far end is scripted: :meth:`deliver` appends octets it will read back, and
    every octet written to it is recorded so a case can assert what reached the
    wire — including, crucially, that a credential did **not**.
    ``ScriptedChannel`` in ``tests/tools/egress_transport_harness.py`` was the seed
    of this and has been retired into it (ADR-0191 §8).

    **Nothing here renders an octet.** :meth:`__repr__` reports how many were
    written and never which, and no message this class raises interpolates one.
    The octets are held in memory for the lifetime of the object and are written
    to nothing.

    **The failure arming is by *marker* rather than by count** — see
    :meth:`fail_write_after`. A count is an artefact of how many commands an
    exchange happens to take and would silently arm the wrong write the day one
    is added.
    """

    __slots__ = (
        "_close_gate",
        "_closed",
        "_exhausted_error",
        "_inbound",
        "_release_error",
        "_secure",
        "_suppressed",
        "_tls_upgrades",
        "_upgrade_error",
        "_write_error",
        "_write_marker",
        "_written",
    )

    def __init__(self, *, secure: bool = False) -> None:
        """Open a channel over an empty far end.

        Zero arguments are enough to build one, deliberately: the Protocol-triad
        check evaluates a conformance suite's subject fixture with nothing but
        ``self``, so a canonical fake that needed arranging to exist could not be
        bound to its own suite.

        Args:
            secure: Whether TLS was established before the far end's greeting —
                ``True`` for an implicit-TLS endpoint, ``False`` where the holder
                must call :meth:`start_tls` itself.
        """
        self._inbound = bytearray()
        self._written = bytearray()
        self._secure = secure
        self._closed = False
        self._tls_upgrades = 0
        self._suppressed = 0
        self._exhausted_error: TransportError | None = None
        self._write_error: TransportError | None = None
        self._write_marker: bytes = b""
        self._upgrade_error: TransportError | None = None
        self._release_error: Exception | None = None
        self._close_gate: LoopSuspension | None = None

    # --- arranging the far end ---------------------------------------------

    def deliver(self, *octets: bytes) -> Self:
        """Append octets the far end has sent, ready to be read back.

        Args:
            octets: Chunks to append, in order. They join one stream:
                :meth:`read` and :meth:`read_line` share a cursor over it, so how
                the caller chunked them here is not observable.

        Returns:
            This channel, so an arrangement reads as one expression.
        """
        for chunk in octets:
            self._inbound += chunk
        return self

    def fail_when_exhausted(self, error: TransportError) -> None:
        """Arm a read past the end of the script to raise instead of ending cleanly.

        A far end can stop answering two ways — a clean close and a reset — and a
        caller has to be able to tell them apart. Without this a fake could only
        ever model the first.

        **The armed failure is a ``TransportError`` and cannot be anything else**
        (ADR-0191 §1). That is the shared refusal type both this fake and the
        production channel raise, so a fake armed with a raw ``OSError`` would let
        a consumer's test pass against a failure the real channel converts before
        the consumer ever sees it — which is the taxonomy clause failing in the one
        place it is supposed to be enforced.

        Args:
            error: What a read finding nothing left raises.
        """
        self._exhausted_error = error

    def fail_write_after(self, marker: bytes, *, error: TransportError) -> None:
        """Arm the write whose data ends with ``marker`` to fail once recorded.

        **The octets are recorded before the failure is raised**, which is the
        whole point: a stream writer hands data to the transport and only then
        awaits the flush, so a failing flush leaves a payload that may already be
        on the wire. A double that dropped the write would model a guarantee no
        real channel offers.

        Args:
            marker: The trailing octets that identify the write to fail. Empty
                fails the next write whatever it carries.
            error: What that write raises — a ``TransportError``, for the reason
                :meth:`fail_when_exhausted` gives.
        """
        self._write_marker = marker
        self._write_error = error

    def fail_upgrade_with(self, error: TransportError) -> None:
        """Arm :meth:`start_tls` to refuse, leaving the channel in the clear.

        Args:
            error: What the upgrade raises — a ``TransportError``, for the reason
                :meth:`fail_when_exhausted` gives. :attr:`is_secure` stays
                ``False``, which is the read a holder refuses on.
        """
        self._upgrade_error = error

    def fail_release_with(self, error: Exception) -> None:
        """Arm an ordinary release failure, which :meth:`close` must not raise.

        The contract has ``close`` suppress and log one rather than raising it,
        because a holder closes from a cleanup path where Python replaces the
        exception in flight. Arming it is how a conformance case observes the
        suppression rather than assuming it.

        Args:
            error: The release failure. **Any exception**, and deliberately not
                narrowed to ``TransportError`` like the arming above: this one is
                never raised to a caller, so no taxonomy is being promised about
                it, and the real channel's own suppressed failure is an ``OSError``
                from ``wait_closed``. It is counted in
                :attr:`suppressed_release_failures`.
        """
        self._release_error = error

    def suspend_next_close(self) -> LoopSuspension:
        """Arm the next :meth:`close` to suspend inside its release.

        ADR-0060 §1's cancellation clause is only observable from a call held open
        where the cancellation can be delivered to it; this is that lever for the
        one method of this Protocol that releases anything.

        Returns:
            The handle a case waits on and releases.
        """
        self._close_gate = LoopSuspension()
        return self._close_gate

    # --- observing ----------------------------------------------------------

    @property
    def written(self) -> bytes:
        """Every octet written to this channel, concatenated in order."""
        return bytes(self._written)

    @property
    def closed(self) -> bool:
        """Whether :meth:`close` has completed at least once."""
        return self._closed

    @property
    def tls_upgrades(self) -> int:
        """How many times :meth:`start_tls` succeeded on this channel."""
        return self._tls_upgrades

    @property
    def suppressed_release_failures(self) -> int:
        """How many armed release failures :meth:`close` swallowed and logged."""
        return self._suppressed

    def __repr__(self) -> str:
        """Describe the channel without rendering one octet it carried.

        Returns:
            The TLS state, the number of octets written and whether it is closed.
        """
        return (
            f"FakeByteChannel(secure={self._secure}, "
            f"written_octets={len(self._written)}, closed={self._closed})"
        )

    # --- the contract -------------------------------------------------------

    @property
    def is_secure(self) -> bool:
        """Whether a TLS handshake has completed on this channel.

        Returns:
            ``True`` once implicit TLS or an upgrade established one.
        """
        return self._secure

    async def read_line(self) -> bytes:
        r"""Read to the next ``\n`` inclusive, or empty bytes at end of stream.

        Returns:
            The line including its terminator, or ``b""`` at end of stream — which
            is also what a tail with no terminator reports, the octets being
            discarded in its place.

        Raises:
            TransportError: If more than
                :data:`~ai_assistant.core.types.TRANSPORT_OCTET_CEILING` octets
                stand before the terminator. Nothing is consumed: the stream is
                left where a caller could observe it, exactly as a refusal to
                buffer leaves it.
            Exception: Whatever :meth:`fail_when_exhausted` armed, where the
                stream is exhausted and one was.
        """
        found = self._inbound.find(_TERMINATOR)
        if found > TRANSPORT_OCTET_CEILING or (
            found < 0 and len(self._inbound) > TRANSPORT_OCTET_CEILING
        ):
            msg = (
                f"the far end sent more than {TRANSPORT_OCTET_CEILING} octets for one "
                f"line without terminating it"
            )
            raise TransportError(msg)
        if found < 0:
            # A line with no terminator is not a reply, whatever octets arrived.
            self._inbound.clear()
            return self._ended()
        line = bytes(self._inbound[: found + 1])
        del self._inbound[: found + 1]
        return line

    async def read(self, limit: int, /) -> bytes:
        """Read at most ``limit`` octets from the same cursor :meth:`read_line` uses.

        Args:
            limit: How many octets at most, in
                ``1..TRANSPORT_OCTET_CEILING`` inclusive.

        Returns:
            Between one and ``limit`` octets, or ``b""`` at end of stream. A short
            read is ordinary and is not an error.

        Raises:
            ValueError: If ``limit`` is outside that range, so that no spelling of
                it means "read until end of stream".
            TransportError: Whatever :meth:`fail_when_exhausted` armed, where the
                stream is exhausted and one was.
        """
        if not 1 <= limit <= TRANSPORT_OCTET_CEILING:
            msg = f"read limit must be an integer in 1..{TRANSPORT_OCTET_CEILING}; got {limit}"
            raise ValueError(msg)
        if not self._inbound:
            return self._ended()
        taken = bytes(self._inbound[:limit])
        del self._inbound[:limit]
        return taken

    async def write(self, data: bytes, /) -> None:
        """Record ``data`` as written, failing afterwards where one was armed.

        Args:
            data: The octets to send.

        Raises:
            TransportError: Whatever :meth:`fail_write_after` armed, once this
                write's octets have been recorded.
        """
        self._written += data
        if self._write_error is not None and data.endswith(self._write_marker):
            error, self._write_error = self._write_error, None
            raise error

    async def start_tls(self) -> None:
        """Mark the channel secure, as a completed handshake would.

        Raises:
            TransportError: Whatever :meth:`fail_upgrade_with` armed. The channel
                stays in the clear, so a holder reading :attr:`is_secure` still
                refuses to present a credential.
        """
        if self._upgrade_error is not None:
            error, self._upgrade_error = self._upgrade_error, None
            raise error
        self._secure = True
        self._tls_upgrades += 1

    async def close(self) -> None:
        """Release the channel, idempotently, raising no ordinary release failure.

        An armed release failure is counted and logged rather than raised. A
        cancellation delivered from outside is not that: the channel is made safe
        — it reads closed — and the cancellation is re-raised (ADR-0060 §1).
        """
        gate, self._close_gate = self._close_gate, None
        try:
            if gate is not None:
                await gate.hold()
        finally:
            self._closed = True
        if self._release_error is not None:
            error, self._release_error = self._release_error, None
            self._suppressed += 1
            _log.debug("fake_channel_release_failed", error_type=type(error).__name__)

    def _ended(self) -> bytes:
        """End of stream, or the failure armed in its place.

        Returns:
            Empty bytes.

        Raises:
            TransportError: Whatever :meth:`fail_when_exhausted` armed.
        """
        if self._exhausted_error is not None:
            error, self._exhausted_error = self._exhausted_error, None
            raise error
        return b""


def _refuse_unless_servable(
    channel: FakeByteChannel, endpoint: TransportEndpoint, *, moment: str
) -> None:
    """Refuse a channel no conforming opener could hand out for ``endpoint``.

    Read twice per open — once when the channel is reserved, once immediately
    before it is handed over — because an arrangement holds the object it queued
    and can mutate it while the open is suspended (ADR-0191 §1's "an open duplex
    channel", §3's one open one channel). A single reading at the reservation is
    stale by the handoff, which is what adversarial review found on round 5.

    Args:
        channel: The channel this open would hand out.
        endpoint: The endpoint asked for, whose mode fixes the TLS state.
        moment: Which reading this is, so the refusal says whether the
            arrangement queued something unservable or made it so mid-open.

    Raises:
        ValueError: If the channel's TLS state contradicts the endpoint's mode,
            or if it is closed. Both are the arranger's error rather than a
            connection's — hence ``ValueError`` and never ``TransportError``:

            * ADR-0191 §1 has an implicit-TLS open return a channel *already*
              under TLS and an upgrade open return one in the clear, so serving
              either for the other would let a consumer be tested against a state
              the production capability can never produce;
            * ``open_channel`` promises an *open* duplex channel, and a holder
              handed a closed one would be testing against something no opener
              returns.
    """
    if channel.is_secure is not endpoint.implicit_tls:
        state = "already under TLS" if channel.is_secure else "in the clear"
        mode = "implicit TLS" if endpoint.implicit_tls else "an upgrade"
        msg = (
            f"a channel {state} is being {moment} for an endpoint whose mode is "
            f"{mode}; a conforming transport returns a channel already under TLS "
            f"for an implicit-TLS endpoint and a cleartext one otherwise "
            f"(ADR-0191 §1)"
        )
        raise ValueError(msg)
    if channel.closed:
        msg = (
            f"a closed channel is being {moment}; a conforming transport returns "
            f"an open duplex channel or raises (ADR-0191 §1)"
        )
        raise ValueError(msg)


def _again(refusal: TransportError) -> TransportError:
    """A fresh refusal carrying the armed one's words, for a *standing* arming.

    **Re-raising one exception object grows it.** Every ``raise`` sets the
    instance's ``__traceback__`` to a new traceback whose tail is the old one, and
    each of those frames keeps its locals alive — so a transport armed to refuse
    everything hands back an exception that gets longer on every attempt, and that
    holds every earlier caller's frame. At this seam the caller is
    ``SmtpEgressTransport._send``, whose locals include a credential, and a
    milestone arm opens against a standing refusal many times over. Adversarial
    review found it on round 12.

    A fresh instance per attempt keeps the arming's message and its concrete type
    — ``type(refusal)``, so an arming with a narrower
    :class:`~ai_assistant.core.errors.TransportError` subclass is still caught by
    a case that names it — while each refusal carries only the frames of the open
    that raised it. Adversarial review noted the type on round 13.

    Args:
        refusal: What :meth:`FakeOutboundTransport.refuse_with` was armed with.

    Returns:
        A new :class:`~ai_assistant.core.errors.TransportError` with its
        arguments.
    """
    return type(refusal)(*refusal.args)


@final
class FakeOutboundTransport:
    """An :class:`~ai_assistant.core.protocols.OutboundTransport` that opens nothing.

    It records every attempt to open a channel, in order, with the endpoint each
    named and whether it was served or refused, and it can be armed to refuse — so
    a connection failure is exercisable without a network (ADR-0191 §8).

    **The record is the measurement and the refusal is not.** An attempt is
    appended *before* anything can go wrong with it, so a milestone arm reading
    zero is reading "nothing asked" rather than "something asked and failed".

    **It models the socket it does not have**, because ADR-0191 §1 puts a release
    obligation on ``open_channel`` that is otherwise unobservable:
    :attr:`open_sockets` counts what this transport acquired and has not given
    back, an in-flight acquisition included, so a conformance case can cancel a
    call inside the acquisition and read what was left behind.
    """

    __slots__ = (
        "_attempts",
        "_failure",
        "_gate",
        "_in_flight",
        "_queued",
        "_refusal",
        "_reserved",
        "_served",
    )

    def __init__(self) -> None:
        """Start with nothing attempted, nothing queued and nothing armed."""
        self._attempts: list[_Pending] = []
        self._queued: deque[FakeByteChannel] = deque()
        self._served: list[FakeByteChannel] = []
        self._reserved: list[FakeByteChannel] = []
        self._refusal: TransportError | None = None
        self._failure: TransportError | None = None
        self._gate: LoopSuspension | None = None
        self._in_flight = 0

    # --- arranging ----------------------------------------------------------

    def serve(self, *channels: FakeByteChannel) -> Self:
        """Queue channels to hand out, one per :meth:`open_channel`, in order.

        An empty queue is not an error: a call past the end is served a fresh
        :class:`FakeByteChannel` over an empty far end — already secure where the
        endpoint's TLS is the implicit kind, which is the contract's own clause
        rather than a convenience.

        **A queued channel has to be one a conforming transport could return for
        the endpoint it is served for** — open, unserved, and in that endpoint's
        TLS state — and a handout that would not raises rather than proceeding:
        see :meth:`_reserved_for`.

        Args:
            channels: The channels to hand out.

        Returns:
            This transport, so an arrangement reads as one expression.

        Raises:
            ValueError: If a channel is queued twice, or was already served or
                reserved. One open yields one channel (ADR-0191 §3), and an
                arrangement that could not be honoured is better refused here —
                where the arranger is looking — than at the handout.
        """
        held = [*self._queued, *self._served, *self._reserved]
        for channel in channels:
            if any(other is channel for other in held):
                msg = (
                    "the same channel was queued twice, or is already served or "
                    "reserved by an open in flight; one open yields one channel, and "
                    "this contract carries no pool (ADR-0191 §3)"
                )
                raise ValueError(msg)
            held.append(channel)
        self._queued.extend(channels)
        return self

    def refuse_with(self, error: TransportError) -> None:
        """Arm this transport to record every attempt and serve none.

        **Standing rather than one-shot**, because that is the arrangement a
        milestone arm wants: a transport that refuses everything is one whose
        recorded attempts are the whole account of what this system reached for.
        :meth:`serve_again` lifts it.

        **Its words are kept, its instance is not**: each refused open raises a
        fresh :class:`~ai_assistant.core.errors.TransportError` carrying this
        one's arguments, because re-raising a single object accumulates a
        traceback — and its frames' locals — on every attempt (:func:`_again`).

        Args:
            error: What every subsequent :meth:`open_channel` refuses with, after
                the attempt has been recorded.
        """
        self._refusal = error

    def serve_again(self) -> None:
        """Lift a standing refusal armed by :meth:`refuse_with`."""
        self._refusal = None

    def fail_after_acquiring(self, error: TransportError) -> None:
        """Arm the next open to fail *after* the modelled socket exists.

        ADR-0191 §1's ordinary-establishment-failure case: a connect that failed
        after the socket existed, a certificate that did not verify, a channel
        object that could not be constructed. The release obligation is what such
        a case is for, and it is unobservable against a failure that happens
        before anything was acquired — which is what :meth:`refuse_with` models.

        **Taken by the open that starts next**, before anything can suspend, so a
        second open beginning while the first is held does not walk off with it.
        Adversarial review found that on round 4.

        Args:
            error: What that open raises, one time.
        """
        self._failure = error

    def suspend_next_open(self) -> LoopSuspension:
        """Arm the next open to suspend while holding the modelled socket.

        ADR-0060 §3's shape: the call held open *inside* the resource it acquired,
        so a case can cancel it there and observe what was released.

        Returns:
            The handle a case waits on and releases.
        """
        self._gate = LoopSuspension()
        return self._gate

    def forget_attempts(self) -> None:
        """Discard the attempt record, keeping every arming in place.

        What a calibration needs: an instrument is demonstrated live by making it
        fire, and the reading that follows must not carry the demonstration.

        **An attempt still in flight is discarded like any other** and does not
        come back when it completes. That is the honest reading of a reset, and it
        is safe rather than merely tolerated: the record each open completes into
        is its own (see :class:`_Pending`), so a reset can empty the list without
        a completing call writing past its end.
        """
        self._attempts.clear()

    # --- observing ----------------------------------------------------------

    @property
    def attempts(self) -> tuple[TransportAttempt, ...]:
        """Every request for a channel, in order, served and refused alike.

        Returns:
            A frozen record per attempt, built on the read: what the transport
            holds while an open is in flight is mutable, and handing that out
            would let a reader watch an attempt change under it.
        """
        return tuple(
            TransportAttempt(endpoint=pending.endpoint, served=pending.served)
            for pending in self._attempts
        )

    @property
    def channels(self) -> tuple[FakeByteChannel, ...]:
        """Every channel handed out, in the order it was served."""
        return tuple(self._served)

    @property
    def open_sockets(self) -> int:
        """Modelled sockets acquired and not yet released.

        Returns:
            One per served channel that is not closed, plus any acquisition still
            inside :meth:`open_channel`.
        """
        return self._in_flight + sum(1 for channel in self._served if not channel.closed)

    @property
    def reserved(self) -> tuple[FakeByteChannel, ...]:
        """Channels an open in flight has taken and not yet handed to anybody."""
        return tuple(self._reserved)

    def __repr__(self) -> str:
        """Describe the transport by its counts, never by what a channel carried."""
        return (
            f"FakeOutboundTransport(attempts={len(self._attempts)}, "
            f"open_sockets={self.open_sockets})"
        )

    # --- the contract -------------------------------------------------------

    def _reserved_for(self, endpoint: TransportEndpoint) -> tuple[FakeByteChannel, bool]:
        """Take the channel this open will hand out, before it can suspend.

        **Reserved at the attempt rather than at the completion**, so two opens in
        flight at once take the queued channels in the order they were *called*
        rather than in the order they happen to finish. Dequeuing after the
        suspension let a second open walk off with the first's scripted replies,
        which adversarial review found on round 3.

        Args:
            endpoint: The endpoint asked for.

        Returns:
            The channel and whether it came off the queue, so a failed open can
            put a queued one back.

        Raises:
            ValueError: If the queued channel is not one a conforming transport
                could return for ``endpoint``. Two of the three ways are
                :func:`_refuse_unless_servable`'s — its TLS state contradicts the
                endpoint's mode, or it is closed — and are read again at the
                handoff. The third is this method's own: **it has already been
                served, or is reserved by an open still in flight.** One open, one
                channel: handing the same object to two callers models a pool this
                contract deliberately does not have (ADR-0191 §3), and closing
                either caller's channel would close both. Checking only
                *completed* handouts left the concurrent case open, which review
                found on round 4. All three are the arranger's error rather than a
                connection's — hence ``ValueError`` and never ``TransportError``.
        """
        if not self._queued:
            return FakeByteChannel(secure=endpoint.implicit_tls), False
        channel = self._queued[0]
        _refuse_unless_servable(channel, endpoint, moment="queued")
        if any(held is channel for held in (*self._served, *self._reserved)):
            msg = (
                "a channel is already served or reserved by an open in flight; one "
                "open yields one channel, and this contract carries no pool "
                "(ADR-0191 §3)"
            )
            raise ValueError(msg)
        self._queued.popleft()
        return channel, True

    async def open_channel(self, endpoint: TransportEndpoint) -> ByteChannel:
        """Record the attempt, then serve a channel or refuse.

        Args:
            endpoint: The endpoint asked for. Recorded whatever happens next.

        Returns:
            The next queued :class:`FakeByteChannel`, or a fresh one over an empty
            far end.

        Raises:
            TransportError: Whatever :meth:`refuse_with` or
                :meth:`fail_after_acquiring` armed — the shared refusal type the
                production implementation raises too (ADR-0191 §1). In the second
                case the modelled socket is released before the failure leaves, so
                :attr:`open_sockets` reads what it did before the call.
            ValueError: If the queued channel is not one a conforming transport
                could return for ``endpoint``; see :meth:`_reserved_for` and
                :func:`_refuse_unless_servable`. Raised before anything is
                acquired, or — where the arrangement mutated the channel while
                this open was suspended — after the reservation is given back, so
                nothing is left held either way.
            CancelledError: Re-raised after that same release, never absorbed
                (ADR-0060 §1).
        """
        pending = _Pending(endpoint=endpoint)
        self._attempts.append(pending)
        if self._refusal is not None:
            raise _again(self._refusal)
        # **Everything one-shot is taken at the attempt, before anything can
        # suspend**, so two opens in flight at once get what they were armed and
        # queued for in the order they were called rather than in the order they
        # finish. An arrangement error is then raised having acquired nothing.
        channel, queued = self._reserved_for(endpoint)
        self._reserved.append(channel)
        gate, self._gate = self._gate, None
        failure, self._failure = self._failure, None
        self._in_flight += 1
        try:
            if gate is not None:
                await gate.hold()
            if failure is not None:
                raise failure
            # **Read again here, and the gap this closes is the suspension
            # itself.** The reading at the reservation is made before anything
            # can suspend, and an arrangement holds the channel it queued: it can
            # upgrade or close it while this open is held, after which the
            # reservation's answer is stale and a ``served=True`` attempt would
            # report a handout no conforming opener could make. Adversarial
            # review found it on round 5. It is inside this ``try`` so that the
            # refusal releases the reservation like any other failed open.
            _refuse_unless_servable(channel, endpoint, moment="served")
        except BaseException:
            self._in_flight -= 1
            self._reserved.remove(channel)
            if queued:
                # Put it back at the head: the open that reserved it never handed
                # it to anybody, so the next open is the one it was queued for.
                self._queued.appendleft(channel)
            raise
        self._served.append(channel)
        self._reserved.remove(channel)
        self._in_flight -= 1
        pending.served = True
        return channel
