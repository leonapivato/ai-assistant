"""The server half: one connection, driven against an ``AssistantEngine``.

The *listener* is the hub's (:mod:`ai_assistant.service.transport`) — where to
bind, when to start accepting, how many connections to hold — because those are
deployment facts and ADR-0083 §8 owns them. What lives here is the protocol
itself, which is the same on both sides of the socket and depends on ``core``
alone: the handshake, the frame loop, the dispatch onto the fifteen methods, and
the mapping from a declared failure to an error frame.

**Two classes of failure, and the boundary is the envelope** (ADR-0084 §3):

* **If no envelope decodes, the connection is closed without a response.** There
  is no correlation id to quote and "**no agreed encoding to reply in** — a peer
  that has already violated the framing is not one to write more framed bytes at".
* **A frame that decodes gets a typed error** — the handshake's own refusals, and
  the ordinary correlated failures of a call.

**The one exception is a second request arriving while one is outstanding**, which
closes. A correlated error would carry the *second* request's id, "which the
mismatch rule separately obliges the client to reject — so the refusal could never
be consumed. A rule whose own response violates the adjacent rule is not a rule."
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol

import structlog

from ai_assistant.core.errors import AssistantError
from ai_assistant.wire import envelope as env
from ai_assistant.wire.codec import ENVELOPE_RESERVE_BYTES
from ai_assistant.wire.errors import (
    ConnectionClosedError,
    CredentialNotSupportedError,
    CredentialRejectedError,
    CredentialRequiredError,
    DeviceExpelledError,
    ProtocolError,
    UndecodableFrameError,
    error_payload,
)
from ai_assistant.wire.framing import read_frame, write_frame
from ai_assistant.wire.surface import METHODS, argument_adapter, parameters

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import timedelta

    from ai_assistant.core.protocols import AssistantEngine

_log = structlog.get_logger(__name__)

#: How many turns of the event loop the overlap watcher is given to observe a frame
#: that is already buffered (:func:`_settle`). **One is enough today** — measured:
#: with zero the refusal is missed, with one it fires — and three is headroom for a
#: watcher path that grows a suspension point, which is free because the loop stops
#: the moment the watcher settles. Zero is the case the tests pin, so a change that
#: removed the yielding would fail rather than become intermittent.
_SETTLE_TURNS: Final[int] = 3


@dataclass(frozen=True, slots=True)
class ConnectionLimits:
    """What a served connection is held to (ADR-0084 §3).

    Grouped rather than passed one by one because they travel together everywhere:
    the listener reads all three from ``Settings``, and every function below needs
    the frame ceiling and the deadline in the same breath. It also keeps
    :attr:`payload_limit` derived in one place, so no caller can subtract the
    envelope reserve differently.

    Attributes:
        max_frame_bytes: The hub's effective frame ceiling — what the length prefix
            counts, envelope and payload together.
        read_timeout: How long a peer may stall, mid-frame or between frames.
        build: This build's identifier, published in the connect reply.
    """

    max_frame_bytes: int
    read_timeout: timedelta
    build: str

    @property
    def payload_limit(self) -> int:
        """The contract limit: the frame ceiling less ADR-0085 §8b's reserve."""
        return self.max_frame_bytes - ENVELOPE_RESERVE_BYTES


@dataclass(frozen=True, slots=True)
class AdmissionRefusal:
    """Why a device is not admitted, in the two things the refusal has to carry.

    Attributes:
        code: One of ADR-0124 §7's lowercase tokens.
        message: What an owner reads. It never includes the credential or the
            verifier (§7), and the three reasons are distinguished in it exactly as
            they are in the code.
    """

    code: str
    message: str


class Admission(Protocol):
    """The remote listener's half of ADR-0124's two-fact rule, per connection.

    **Both methods are synchronous, and that is the mechanism rather than a
    style.** ADR-0124 §8 requires the liveness check and the write it authorises to
    be "one step with respect to a revocation: an implementation in which a
    revocation may take effect between the two does not satisfy this clause" — and
    the clause's own commentary is explicit that placing a read *near* a write is
    not enough, because "whether anything may [interleave] is a property of where
    the awaits fall — not of how few lines apart the read and the write are
    written". A synchronous check followed by a synchronous ``write`` has no
    suspension point between them, on a system that "composes on one event loop",
    so no revocation can land in the gap because there is no gap.

    That is §8's **compare-and-claim on a generation the revocation bumps**, of the
    three mechanisms it names; ADR-0083 §6 leaves the choice to this lane with the
    store in hand, and this one is the one that costs no lock across I/O.

    **``wire`` declares the seam and the hub implements it**, because the enrolment
    record is deployment state (ADR-0083 §8) and ``wire`` depends on ``core``
    alone. It is a local ``Protocol``, not ``core/protocols.py`` surface: ADR-0124
    §10 decides none, and a listener's own collaborator is not a contract between
    subsystems (the precedent is :mod:`ai_assistant.service.scheduler`'s).
    """

    def admit(self, credential: str) -> AdmissionRefusal | None:
        """Decide ADR-0124 §7's two facts and claim the enrolment they name.

        Args:
            credential: A well-formed credential, already checked against the
                scheme by :func:`~ai_assistant.wire.envelope.read_remote_connect`.

        Returns:
            ``None`` to admit, or why not.
        """

    def is_live(self) -> bool:
        """Whether the enrolment this connection was admitted under is still live.

        Returns:
            Whether a frame may still be written to this device.
        """

    def device(self) -> str:
        """The identity ADR-0124 §4 established for this connection at admission.

        **Never read from a payload**, which ADR-0124 §4 forbids in terms — the hub
        "may not take that identity from anything the peer asserts" — and which is
        why ADR-0131 §4 gives ``next_notification`` no device argument and forbids
        a lane adding one. It is held per connection by the listener, and this is
        how the delivery rules that *are* per-device reach it.

        Returns:
            The overlay identity, stable for this connection's life.
        """

    def record_refusal(self, code: str) -> None:
        """Record a refusal this connection took, against the device it named.

        **Every refusal on the remote listener is recorded with its device, and the
        ones decided before :meth:`admit` are why this method exists.** ADR-0124 §6
        makes a hub-side record of each use one of the three replacements standing in
        for ADR-0004 §7's gate — "every use of the credential is recorded at the hub,
        each admission and each refusal with the device it named" — and §7 requires
        the reasons distinguished "in the error it returns **and in what the hub
        logs**". A credential that is absent, empty, of the wrong type or malformed is
        refused by the frame reader, before any verifier is consulted; without this
        the hub would answer that peer and record nothing about who it was.

        Args:
            code: The lowercase refusal token the peer is being sent. Never the
                credential and never the verifier (§7).
        """


#: The ``AssistantEngine`` method a delivery connection exists to carry
#: (ADR-0131 §1). Named here rather than derived because §2's two closes are rules
#: about *this* method and no other, and a predicate over the whole method set
#: would be a rule with no subject.
DELIVERY_METHOD: Final[str] = "next_notification"


class DeliveryRegistry(Protocol):
    """The hub's per-device delivery slot and its global capacity (ADR-0131 §3).

    **One registry per hub, constructed once and shared by every listener**, which
    is ADR-0131 §3's clause and the mistake it exists to forbid: "Give each its own
    registry and eight loopback polls and eight remote polls each pass a local
    ``hub_max_delivery_connections`` of 8, yielding sixteen delivery connections."
    That is ADR-0124 §7's warning — "a second listener is the natural place to
    double a budget by accident" — arriving one layer up, and the instrument is the
    one the tree already uses for the ceilings this sits beside,
    :class:`ai_assistant.service.transport.ConnectionBudget`.

    **``wire`` declares the seam and the hub implements it**, exactly as
    :class:`Admission` is: the registry is deployment state (ADR-0083 §8) and
    ``wire`` depends on ``core`` alone. It is a local ``Protocol``, not
    ``core/protocols.py`` surface — a listener's own collaborator is not a
    contract between subsystems.

    **Both methods are synchronous, and that is the mechanism rather than a
    style.** ADR-0131 §5 requires the global capacity check and its claim to
    happen "in the **same step** as §2's per-device check and claim, over both
    parts of the connection registry at once", because a bound checked separately
    is a bound that can be passed twice: with seven of eight slots held, two
    devices polling concurrently can each pass the capacity check and each claim
    its own per-device slot, leaving nine. A synchronous check-and-claim has no
    suspension point inside it, on a system that composes on one event loop, so
    there is no gap for a second claimant to land in.
    """

    def claim(self, device: str | None) -> bool:
        """Take this device's delivery slot and one unit of global capacity.

        Both or neither: "A poll dispatches only if it obtains both; one that
        obtains neither or only one claims nothing and its connection closes under
        §2" (ADR-0131 §5).

        Args:
            device: ADR-0124 §4's identity for this connection, or ``None`` on the
                loopback listener. ``None`` is an identity rather than a missing
                one: ADR-0131 §4 rules that "all loopback connections count as a
                single local device", which is not an approximation but the fact —
                ADR-0084 §1's ``0600`` bit means every loopback peer is the owner
                on the owner's own machine.

        Returns:
            Whether both claims were obtained.
        """

    def release(self, device: str | None) -> None:
        """Give back this connection's slot and its capacity unit, in one step.

        ADR-0131 §2a: "Neither is released without the other, and a closed
        connection holds neither." Stating the release over *any* cause of a close
        rather than over the detected-close path alone is what keeps a third way of
        closing from needing a fourth clause — so this is called from one place,
        the connection's own teardown.

        Args:
            device: The identity the claim was taken under.
        """


async def serve_connection(  # noqa: PLR0913 — the engine, the two stream halves, and one keyword per policy the listener supplies
    engine: AssistantEngine,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    limits: ConnectionLimits,
    on_handshake: Callable[[], None] | None = None,
    admission: Admission | None = None,
    delivery: DeliveryRegistry | None = None,
) -> None:
    """Drive one accepted connection to its end.

    Returns normally on every ordinary ending — a client that hung up, a peer that
    broke the protocol, a deadline that expired — because none of those is the
    *hub's* failure and a resident process must not treat a misbehaving spoke as a
    fault of its own (ADR-0084 §3's "the reason is robustness, not secrecy").

    **``admission`` is what makes this the same protocol on two listeners.**
    ADR-0124 §9 rests on that being literally true — "what differs between the two
    listeners is which connect frames are admitted, which is policy reported in the
    ratified error frame rather than a change to what a frame is" — so the frame
    loop, the dispatch and the error mapping below are one code path and only the
    connect frame's credential rule forks.

    Args:
        engine: The in-process engine this hub owns.
        reader: The connection's reader.
        writer: The connection's writer.
        limits: The frame ceiling, the deadline and the build identifier.
        on_handshake: Called once the handshake completes, so a listener can move
            this connection off its *pending* ceiling and onto its total. The
            listener owns both figures (ADR-0084 §3, ADR-0124 §7's shared budget)
            and the handshake happens here, so one of the two has to tell the other.
        admission: The remote listener's two-fact rule, or ``None`` on the loopback
            listener, where ADR-0084 §2's opposite rule stands unchanged.
        delivery: The hub's one delivery registry (ADR-0131 §3), or ``None`` where
            a caller serves no delivery — which makes every ``next_notification``
            close the connection under §2 rather than silently claiming nothing.
    """
    claimed: list[str | None] = []
    try:
        if not await _handshake(reader, writer, limits=limits, admission=admission):
            return
        if on_handshake is not None:
            on_handshake()
        await _serve_requests(
            engine,
            reader,
            writer,
            limits=limits,
            admission=admission,
            delivery=delivery,
            claimed=claimed,
        )
    except DeviceExpelledError as exc:
        # Its own clause, above the protocol faults, because it is not one: the
        # owner revoked the device and §8's finality is being honoured. Logged at
        # info with its own event so an operator reading two logs can tell an
        # expulsion from a spoke that misbehaved.
        _log.info("hub_connection_expelled", reason=str(exc))
    except (ConnectionClosedError, UndecodableFrameError, ProtocolError) as exc:
        _log.info("hub_connection_closed", reason=str(exc), error_class=type(exc).__name__)
    except asyncio.CancelledError:
        raise
    except Exception:
        # One connection's fault must never be the resident process's. The engine
        # declares its failures and they are answered above as error frames; what
        # reaches here is an undeclared one — including the ``RuntimeError`` a
        # shutting-down engine raises, which a client is not meant to observe
        # (ADR-0085 §1) and which ADR-0084 §1 answers by having already unlinked
        # the socket.
        _log.exception("hub_connection_failed")
    finally:
        # **Released here and nowhere else**, which is ADR-0131 §2a's clause taken
        # literally: the claims track the *connection* and not the poll, and the
        # release is stated "over any other cause" of a close so that a third way
        # of closing does not need a fourth clause. A release keyed on the poll
        # completing would let eight devices each take a zero-budget poll, keep the
        # now-idle socket, and fill `hub_max_connections` while holding no delivery
        # slot the sub-bound could see.
        if delivery is not None:
            for device in claimed:
                delivery.release(device)
        await _hang_up(writer)


async def _handshake(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    limits: ConnectionLimits,
    admission: Admission | None,
) -> bool:
    """Run ADR-0084 §2's one-frame-each connect exchange, under §7's rule for it.

    **The credential rule is decided before the version is**, on both listeners,
    and that order is the one already in the tree rather than a new choice: a
    non-empty credential on loopback is refused before the version is looked at,
    and the remote listener keeps the shape. It is also the stronger posture — the
    hub says nothing about itself to a peer it has not admitted.

    Args:
        reader: The connection's reader.
        writer: The connection's writer.
        limits: The frame ceiling, the deadline and the build identifier.
        admission: ADR-0124 §7's two-fact rule, or ``None`` on loopback.

    Returns:
        Whether the connection may go on to carry requests.

    Raises:
        UndecodableFrameError: If the connect frame does not decode, which closes.
        DeviceExpelledError: If a revocation took effect before the reply was
            written, which closes without one (ADR-0124 §8).
    """
    body = await read_frame(
        reader,
        max_frame_bytes=limits.max_frame_bytes,
        timeout=limits.read_timeout,
        idle_timeout=limits.read_timeout,
    )
    frame = env.decode_envelope(body)
    if frame.kind is not env.FrameKind.CONNECT:
        msg = f"a connection opened with a {frame.kind.value} frame rather than a connect"
        raise UndecodableFrameError(msg)

    try:
        version, client = _read_connect(frame.payload, admission=admission)
    except (
        CredentialNotSupportedError,
        CredentialRequiredError,
        CredentialRejectedError,
        _AdmissionRefusedError,
    ) as exc:
        # §2's credential refusal: "a version mismatch and a non-empty credential
        # are members of an envelope that parsed, so they are reported properly and
        # only then does the connection close." ADR-0124 §7 gives its own refusals
        # "the decoded-frame treatment ADR-0084 §3 gives the handshake's own
        # refusals", which is the same sentence applied to four more codes.
        #
        # **Caught by their own types, never as a ``ProtocolError``.**
        # ``UndecodableFrameError`` is a ``ProtocolError`` too, and a broad clause
        # here quietly turned an oversized handshake — which must close with no
        # response — into a credential refusal. The narrow clause lets it propagate
        # to the close it is owed.
        code = _refusal_code(exc)
        if admission is not None:
            admission.record_refusal(code)
        await _refuse(writer, frame.id, code=code, message=str(exc), limits=limits)
        return False

    if version != env.PROTOCOL_VERSION:
        # Recorded like every other refusal on this listener (ADR-0124 §6). It is
        # reached *after* the credential verified, which is what makes it a use of
        # the credential and not merely a rejected frame — an operator otherwise
        # reads a connection that presented a good credential and then vanished.
        if admission is not None:
            admission.record_refusal(env.VERSION_MISMATCH)
        await _refuse(
            writer,
            frame.id,
            code=env.VERSION_MISMATCH,
            message=(
                f"this hub speaks protocol version {env.PROTOCOL_VERSION} and the client "
                f"speaks version {version}; the two halves are installed and upgraded "
                f"together, so finish the upgrade and restart both"
            ),
            limits=limits,
        )
        return False

    reply = env.encode_envelope(
        env.Envelope(
            kind=env.FrameKind.CONNECT_ACK,
            id=frame.id,
            payload=env.connect_ack_payload(
                build=limits.build, max_frame_bytes=limits.max_frame_bytes
            ),
        )
    )
    _check_live(admission)
    await write_frame(writer, reply, max_frame_bytes=limits.max_frame_bytes)
    _log.debug("hub_client_connected", client=client, protocol_version=version)
    return True


class _AdmissionRefusedError(Exception):
    """One device's admission refused, carrying ADR-0124 §7's code and message.

    Private and never seen outside this module: it exists so that the four ways a
    connect frame can be refused on the remote listener reach one ``except`` clause
    and one reply path, rather than forking the handshake into two shapes.
    """

    def __init__(self, refusal: AdmissionRefusal) -> None:
        """Wrap a refusal the hub already decided.

        Args:
            refusal: The code and the message it carries.
        """
        super().__init__(refusal.message)
        self.refusal = refusal


#: Which lowercase token each frame-level credential fault is reported under
#: (ADR-0124 §7). A malformed or non-string credential shares
#: ``credential_rejected`` with one that simply did not verify, deliberately: §7
#: refuses it "as a credential that did not verify", so a peer learns nothing from
#: the shape of its own mistake.
_CREDENTIAL_CODES: Final[dict[type[Exception], str]] = {
    CredentialNotSupportedError: env.CREDENTIAL_NOT_SUPPORTED,
    CredentialRequiredError: env.CREDENTIAL_REQUIRED,
    CredentialRejectedError: env.CREDENTIAL_REJECTED,
}


def _refusal_code(exc: Exception) -> str:
    """The error code one refused handshake is reported under."""
    if isinstance(exc, _AdmissionRefusedError):
        return exc.refusal.code
    return _CREDENTIAL_CODES[type(exc)]


def _read_connect(payload: object, *, admission: Admission | None) -> tuple[int, str]:
    """Apply whichever listener's credential rule governs this connection.

    The one fork ADR-0124 §9 permits, and it is a fork in *policy* rather than in
    the frame: both branches read the same members from the same payload, and the
    two listeners "hold opposite rules, and a hub running both applies each rule to
    its own listener" (§7).

    Args:
        payload: The connect frame's payload, as decoded.
        admission: The remote rule, or ``None`` for loopback's.

    Returns:
        The version the client claims, and its identifier.

    Raises:
        CredentialNotSupportedError: On loopback, if a credential was carried.
        CredentialRequiredError: On the remote listener, if none was.
        CredentialRejectedError: On the remote listener, if it was not a
            well-formed value of the scheme.
        _AdmissionRefusedError: If the two facts do not both hold.
    """
    if admission is None:
        return env.read_connect(payload)
    version, client, credential = env.read_remote_connect(payload)
    refusal = admission.admit(credential)
    if refusal is not None:
        raise _AdmissionRefusedError(refusal)
    return version, client


def _check_live(admission: Admission | None) -> None:
    """Refuse to write a frame to a device whose enrolment is no longer live.

    **Every call site puts this immediately before a write, with no ``await``
    between the two**, which is ADR-0124 §8's indivisibility discharged by ordering
    rather than by a lock across I/O: "an implementation that reads the record,
    awaits, and then writes has satisfied the letter of 'check immediately before'
    and none of the rule."

    It is called even where a claim a moment earlier already established liveness —
    at the connect reply — because the property being kept is a property of the
    *ordering*, and a check that is only correct while nobody inserts a suspension
    point above it is one an edit can silently remove. Here the cost is a dictionary
    lookup and the guarantee is local to the two lines.

    Args:
        admission: The connection's admission, or ``None`` on loopback, where no
            enrolment governs and there is nothing to revoke.

    Raises:
        DeviceExpelledError: If a revocation has taken effect.
    """
    if admission is not None and not admission.is_live():
        msg = (
            "this device's enrolment was revoked, so the frame that would have gone to it "
            "is abandoned and the connection is closed rather than served"
        )
        raise DeviceExpelledError(msg)


async def _serve_requests(  # noqa: PLR0913 — the engine, the two stream halves, and one keyword per policy the connection carries
    engine: AssistantEngine,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    limits: ConnectionLimits,
    admission: Admission | None,
    delivery: DeliveryRegistry | None = None,
    claimed: list[str | None] | None = None,
) -> None:
    """Read requests one at a time, and refuse a second one that overlaps.

    **The overlap check is why the next frame is read concurrently rather than
    after the reply.** Serving sequentially would *queue* a second request, which
    ADR-0084 §3 forbids in as many words — "not queued, not run concurrently" — and
    a server that queued would look conforming while giving a buggy client a
    concurrency the engine does not offer.

    The watcher runs with **no idle deadline**, because the hub is not idle while a
    request is in flight: a ``converse`` may legitimately take longer than
    ``hub_read_timeout``, and closing a working connection because the reply was
    slow would be the deadline defeating the purpose it was added for. The idle
    deadline applies where the hub genuinely is idle — waiting for the *first*
    frame of the next request.

    **ADR-0124 §8's linearization is the pair of checks below**, and where each one
    sits is the decision rather than the code. The first is at **dispatch**, which
    §8 defends against the tempting alternative: fixing it at admission "would
    demand that the whole handshake be atomic against a revocation, which is a much
    larger obligation on an implementation and buys nothing: a device that completes
    a handshake and is then refused every request has learned only that it
    connected." The second is at the **write**, because "a request dispatched a
    moment before a revocation may be awaiting a model provider for seconds; if the
    rule stopped at dispatch, the hub would finish that work and write the answer to
    a device the owner has expelled."

    Both are also on the loopback listener's path and both are no-ops there
    (``admission is None``), which is what keeps this one code path rather than two.

    **ADR-0131 §2 adds a second connection-level rule and it is enforced in both
    directions**, which is the clause a draft of that ADR stated only about the
    client. A poll on a connection that has carried anything else closes, and
    anything else on a delivery connection closes — because the serial server
    accepts *sequential* frames happily, so a socket that completed a ``converse``
    and then polled would claim a delivery slot out of the capacity §5 reserves for
    isolated pollers, with §2's "carrying no other request for its lifetime"
    contradicted and nothing to contradict it. Both are closes rather than typed
    errors for the reason ADR-0084 §3 gives: a decoded frame gets a typed error
    "provided it is not itself a violation of the connection's own rules", and this
    is such a violation. ADR-0131 §9 records the partial supersession that costs.
    """
    is_delivery = False
    carried_other = False
    while True:
        try:
            frame = await _read_request(reader, limits=limits, idle=limits.read_timeout)
        except ConnectionClosedError:
            return

        _check_live(admission)
        polling = frame.method == DELIVERY_METHOD
        if polling and carried_other:
            msg = (
                "a next_notification arrived on a connection that has already carried "
                "another request; ADR-0131 §2 gives a delivery connection to that alone, "
                "because a poll outstanding for a minute makes the owner's next request a "
                "violation of the serial rule — so this claims nothing and closes"
            )
            raise ProtocolError(msg)
        if is_delivery and not polling:
            msg = (
                f"a {frame.method!r} arrived on a delivery connection; ADR-0131 §2 gives "
                f"that connection to next_notification for its lifetime, and a client "
                f"wanting an ordinary session while polling opens a second connection"
            )
            raise ProtocolError(msg)
        if polling and not is_delivery:
            _claim_delivery(delivery, admission, claimed)
            is_delivery = True

        watcher = asyncio.ensure_future(_read_request(reader, limits=limits, idle=None))
        if polling:
            reply = await _dispatch_poll(engine, frame, watcher, limit=limits.payload_limit)
            if reply is None:
                return
        else:
            try:
                reply = await _dispatch(engine, frame, limit=limits.payload_limit)
            finally:
                overlapped = await _settle(watcher)
            if overlapped:
                msg = (
                    "a peer wrote a second frame while a request was outstanding; this "
                    "connection is serial, and a correlated error would carry an id the "
                    "client must itself reject, so the connection is closed instead — with "
                    "no reply to either, since a peer that has broken the rule is not one "
                    "to write more framed bytes at"
                )
                raise ProtocolError(msg)
            carried_other = True
        body = env.encode_envelope(reply)
        _check_live(admission)
        await write_frame(writer, body, max_frame_bytes=limits.max_frame_bytes)


def _claim_delivery(
    delivery: DeliveryRegistry | None,
    admission: Admission | None,
    claimed: list[str | None] | None,
) -> None:
    """Take this connection's device slot and capacity unit, or close (§2, §5).

    **The check and the claim are one step, taken before the request is
    dispatched** (ADR-0131 §2). "Already has one outstanding" is a read, so a claim
    that depended on it without being the same step would let two delivery
    connections opened at once both observe no outstanding slot before either
    recorded one: both dispatch, the device holds two, neither is the second, and
    §2's rule fails without any implementation disobeying a word of it. Taking the
    claim *before* dispatch is also what makes "exactly one wins" decidable — after
    dispatch the losing poll would already be running and the rule would have to
    unwind it.

    **The offender closes and the incumbent does not**, which is the direction that
    cannot be used as a weapon: newest-poll-wins would let any process that can
    reach the listener evict the owner's real notifier by polling, and the eviction
    would look to the notifier exactly like an ordinary transport failure. Closing
    the second connection costs its caller nothing it can complain about — the
    client is stateless (ADR-0084 §7), so reconnecting is free, and the entry it was
    after is still in the outbox.

    Raises:
        ProtocolError: If no registry is wired, or either claim is unavailable.
    """
    if delivery is None or claimed is None:
        msg = (
            "a next_notification arrived on a listener that serves no delivery registry, "
            "so no slot could be claimed for it and ADR-0131 §2's one-connection rule "
            "could not be enforced; the connection is closed rather than served"
        )
        raise ProtocolError(msg)
    device = None if admission is None else admission.device()
    if not delivery.claim(device):
        msg = (
            "this device already holds a delivery connection, or the hub is at "
            "hub_max_delivery_connections; ADR-0131 §2 closes the connection that asked "
            "second and leaves the one already polling untouched, so a poller cannot "
            "evict the owner's notifier"
        )
        raise ProtocolError(msg)
    claimed.append(device)


async def _dispatch_poll(
    engine: AssistantEngine,
    frame: env.Envelope,
    watcher: asyncio.Future[env.Envelope],
    *,
    limit: int,
) -> env.Envelope | None:
    """Run a long poll, watching for the connection going away underneath it.

    **The existing path does not detect the close, and that is the one place this
    seam genuinely reaches into the request loop** (ADR-0131 §2a).
    :func:`_serve_requests` reads the next frame concurrently with the dispatch —
    which is how it catches an overlapping request — but settles that watcher only
    *after* ``_dispatch`` returns. For every request the hub has ever served that
    ordering is correct and invisible, because the dispatch is short. A long poll is
    the first for which it is not: the watcher observes the peer's clean close
    within milliseconds and nothing acts on it until the poll's budget has run out,
    so the device's slot stays held by a poll nobody is listening to, and the
    reconnect §2 calls free is closed as a second poll — the claim and the rule
    contradicting each other on the most ordinary failure a mobile device has.

    **Cancelling the dispatch is what "the poll ends without an answer" means**, and
    ADR-0131 §2a already prices both outcomes: "A close detected before that step
    runs cancels the poll and takes no entry. A close detected after it leaves the
    lease standing, and the entry returns to the outbox when the lease expires." The
    engine's selection is one indivisible durable step, so a cancellation either
    lands before it commits or after — never inside it — and both are conforming.

    Returns:
        The reply to write, or ``None`` where the connection went away and this
        connection is over.

    Raises:
        ProtocolError: If the peer wrote a frame while the poll was outstanding.
    """
    dispatch = asyncio.ensure_future(_dispatch(engine, frame, limit=limit))
    try:
        return await _await_poll(dispatch, watcher)
    finally:
        # **Every exit, including a cancellation from outside.** ``asyncio.wait``
        # cancels nothing it waits on, so a ``serve_connection`` task cancelled here
        # — which is what shutdown does — unwound past both and left the dispatch
        # running: the slot was released and the socket closed while an orphaned
        # ``next_notification`` could still claim and lease for a connection that no
        # longer existed. ADR-0131 §2a ends a poll on *any* close and takes no entry.
        # The non-poll branch of `_serve_requests` has had this shape all along; this
        # is the same guarantee on the branch that owns a second task.
        #
        # Reaching here with either still pending means an abnormal unwind — the
        # ordinary paths below have already settled both — so whatever they raise on
        # the way out is dropped rather than allowed to mask the original.
        for task in (dispatch, watcher):
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task


async def _await_poll(
    dispatch: asyncio.Future[env.Envelope],
    watcher: asyncio.Future[env.Envelope],
) -> env.Envelope | None:
    """Wait out one poll, returning its reply or ``None`` where the connection went.

    Args:
        dispatch: The engine call this poll is running.
        watcher: The read that notices the peer writing or hanging up.

    Returns:
        The reply to write, or ``None`` where the connection went away.

    Raises:
        ProtocolError: If the peer wrote a frame while the poll was outstanding.
    """
    await asyncio.wait({dispatch, watcher}, return_when=asyncio.FIRST_COMPLETED)
    if not dispatch.done():
        # The watcher settled first, so the peer either hung up or wrote a frame.
        # Either way this poll has no future, and the dispatch is cancelled before
        # the distinction is drawn so that the engine is not left running for a
        # connection that has already ended.
        dispatch.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await dispatch
        if await _settle(watcher):
            msg = (
                "a peer wrote a second frame while a next_notification was outstanding; a "
                "delivery connection carries that request alone (ADR-0131 §2), and the "
                "serial rule is unchanged besides — so the connection is closed with no "
                "reply to either"
            )
            raise ProtocolError(msg)
        _log.debug("hub_delivery_poll_abandoned")
        return None
    reply = dispatch.result()
    if await _settle(watcher):
        msg = (
            "a peer wrote a second frame while a next_notification was outstanding; a "
            "delivery connection carries that request alone (ADR-0131 §2), and the serial "
            "rule is unchanged besides — so the connection is closed with no reply to either"
        )
        raise ProtocolError(msg)
    return reply


async def _settle(watcher: asyncio.Future[env.Envelope]) -> bool:
    """Stop watching for an overlapping frame, and say whether one arrived.

    A watcher that is still running has seen nothing, and cancelling it can only
    discard bytes a conforming client could not have sent — it may write again only
    after the reply, and the reply has not been written yet.

    **The subject is a *frame*, not a well-formed request, and that distinction is
    the whole of this function.** A peer that writes anything at all before its
    reply has violated the serial rule, so a watcher that ends in an
    :class:`~ai_assistant.wire.errors.UndecodableFrameError` is reporting a
    violation just as surely as one that ends with an envelope — and treating that
    as "no overlap" would be worse than missing it, because the malformed bytes have
    already been consumed: the reply would be written to a peer that has already
    violated the framing, and ADR-0084 §3 is explicit that such a peer "is not one
    to write more framed bytes at".

    **The one ending that is not a violation is a clean close.** A client that hung
    up while its request was running is the ordinary case — a cancelled command —
    and closing on it says nothing new.

    **The loop of bare yields is what makes the observation deterministic**, and it
    is not a sleep in disguise. A client that pipelined two requests writes both
    before the first reply, so by the time the dispatch returns the second frame is
    already in the reader's buffer — but the watcher only *sees* it once the event
    loop has given it a turn, and a dispatched call that never suspends (a
    ``forget`` that misses, say) returns without the loop ever running. Without
    these turns the refusal would fire or not depending on whether the method
    happened to await, which is a property of the method rather than of the
    protocol.

    Returns:
        Whether anything arrived while a request was outstanding.
    """
    for _ in range(_SETTLE_TURNS):
        if watcher.done():
            break
        await asyncio.sleep(0)
    if not watcher.done():
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await watcher
        return False
    if watcher.cancelled():  # pragma: no cover — nothing else cancels this future
        return False
    return not isinstance(watcher.exception(), ConnectionClosedError)


async def _read_request(
    reader: asyncio.StreamReader, *, limits: ConnectionLimits, idle: timedelta | None
) -> env.Envelope:
    """Read one frame and require it to be a request."""
    body = await read_frame(
        reader,
        max_frame_bytes=limits.max_frame_bytes,
        timeout=limits.read_timeout,
        idle_timeout=idle,
    )
    frame = env.decode_envelope(body)
    if frame.kind is not env.FrameKind.REQUEST:
        msg = f"a served connection carried a {frame.kind.value} frame where a request belongs"
        raise UndecodableFrameError(msg)
    return frame


async def _dispatch(engine: AssistantEngine, frame: env.Envelope, *, limit: int) -> env.Envelope:
    """Run one request against the engine and render its answer as a frame.

    Args:
        engine: The engine to call.
        frame: The request.
        limit: The contract limit an error payload must fit inside.

    Returns:
        The result or error frame to write back.

    Raises:
        UndecodableFrameError: If the request names no known method or carries
            arguments the surface does not declare. **Closing rather than replying
            is deliberate**: ADR-0085 §10a fixes the wire's error vocabulary as
            "exactly the ``AssistantError`` subtree", so there is no ratified code
            for "no such method", and inventing one would be this lane authoring
            contract surface it may not author. The two halves ship together
            (ADR-0084 §3), so a request naming a method this build does not have is
            a bug rather than a version to tolerate.
    """
    method = frame.method
    if method is None or method not in METHODS:
        msg = f"a request names {method!r}, which this build's engine surface does not declare"
        raise UndecodableFrameError(msg)
    arguments = _decode_arguments(method, frame.payload)
    try:
        result = await getattr(engine, method)(**arguments)
    except AssistantError as exc:
        return env.Envelope(
            kind=env.FrameKind.ERROR,
            id=frame.id,
            payload=error_payload(exc, max_bytes=limit),
        )
    return env.Envelope(kind=env.FrameKind.RESULT, id=frame.id, payload=result)


def _decode_arguments(method: str, payload: object) -> dict[str, Any]:
    """Validate a request's argument object into the method's declared types.

    ADR-0087 §7's order, on the receiving side: **decode, then validate, then
    measure**. The engine measures — it enforces the contract limit itself, in both
    directions (ADR-0084 §4) — so what this owes is the validation that must
    precede it, "because a value with no canonical form must not reach the
    measurement step".

    **An argument the client did not send is absent, not ``null``** (ADR-0085 §10),
    so it simply does not appear here and the engine applies its own declared
    default — which is why the page-size default is a contract clause rather than a
    signature detail.

    Args:
        method: The method being called.
        payload: The request payload, as decoded.

    Returns:
        The keyword arguments to call the engine with.

    Raises:
        UndecodableFrameError: If the payload is not an object, names an argument
            the method does not declare, or carries a value its declared type
            refuses. The last of those is a client that failed to refuse locally
            what ADR-0085 §9 obliges it to refuse locally, which is a bug on that
            side rather than a request to answer.
    """
    if not isinstance(payload, dict):
        msg = f"a request payload must be an object, got {type(payload).__name__}"
        raise UndecodableFrameError(msg)
    declared = set(parameters(method))
    unknown = sorted(set(payload) - declared)
    if unknown:
        msg = f"a request to {method}() names arguments it does not declare: {unknown}"
        raise UndecodableFrameError(msg)
    decoded: dict[str, Any] = {}
    for name, value in payload.items():
        try:
            decoded[name] = argument_adapter(method, name).validate_python(value)
        except Exception as exc:
            msg = f"a request to {method}() carries a {name!r} its declared type refuses: {exc}"
            raise UndecodableFrameError(msg) from exc
    return decoded


async def _refuse(
    writer: asyncio.StreamWriter,
    correlation: str,
    *,
    code: str,
    message: str,
    limits: ConnectionLimits,
) -> None:
    """Report a handshake refusal properly, and only then close.

    "Ruling 4 would be poorly served by a silent close on a version mismatch, and
    it does not get one."
    """
    await write_frame(
        writer,
        env.encode_envelope(
            env.Envelope(
                kind=env.FrameKind.ERROR,
                id=correlation,
                payload={"code": code, "message": message, "details": None, "reduced": False},
            )
        ),
        max_frame_bytes=limits.max_frame_bytes,
    )
    _log.info("hub_connection_refused", reason=code)


async def _hang_up(writer: asyncio.StreamWriter) -> None:
    """Close one connection, tolerating a peer that has already gone."""
    writer.close()
    with contextlib.suppress(ConnectionError, OSError, asyncio.CancelledError):
        await writer.wait_closed()
