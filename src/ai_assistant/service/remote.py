"""The remote listener: the third egress boundary's hub-side half (ADR-0124).

It sits beside :class:`~ai_assistant.service.transport.Listener` rather than
replacing it. ADR-0124 §2: "A hub with no remote-listener configuration binds only
ADR-0084 §1's loopback socket, and the loopback socket is bound whether or not the
remote listener is." Neither listener knows about the other; what they share is
one :class:`~ai_assistant.service.transport.ConnectionBudget`, because §7 makes
both ceilings the hub's totals.

**Where it may bind is checked twice, and neither check is redundant.**
:class:`~ai_assistant.core.config.Settings` refuses at load what is decidable from
the value — a name, a wildcard, a loopback, link-local or multicast address, or a
globally-routable one — and this module refuses to bind an address the overlay
agent does not report as this machine's own. The first alone would pass a LAN
address on a physical interface, which §2 names explicitly; the second alone would
let a wildcard reach a process that has already opened its stores. Together they
are §2's "refused… rather than bound".

**Who is at the other end comes from the agent on this machine, never from the
peer** (§4). The identity is obtained before a byte of the protocol is read, so a
connection the hub cannot name is closed before it has cost anything but the
accept — the same pre-envelope class the two ceilings refuse in, and the answer §4
requires: "A connection whose overlay identity cannot be obtained is refused."

**The admission rule and the revocation rule are one object per connection**
(:class:`_DeviceAdmission`), which is what lets ADR-0124 §8's checks be synchronous
at the two points the wire calls them.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.service.enrolment import Refusal
from ai_assistant.service.overlay import OverlayIdentityUnavailableError
from ai_assistant.service.transport import hold, refuse
from ai_assistant.wire import envelope as env
from ai_assistant.wire import serve_connection
from ai_assistant.wire.server import AdmissionRefusal, ConnectionLimits

if TYPE_CHECKING:
    from ai_assistant.core.config import Settings
    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.service.enrolment import DeviceRegistry
    from ai_assistant.service.overlay import OverlayAgent
    from ai_assistant.service.transport import ConnectionBudget

_log = structlog.get_logger(__name__)

#: ADR-0124 §7's three refusals, as the codes and the sentences an owner reads.
#: The messages name the act that fixes each one, which is ADR-0083's ruling 4
#: applied to the one surface where the hub is unreachable on purpose. **None of
#: them carries the credential or the verifier** (§7).
_REFUSALS: dict[Refusal, AdmissionRefusal] = {
    Refusal.NOT_ENROLLED: AdmissionRefusal(
        code=env.DEVICE_NOT_ENROLLED,
        message=(
            "this hub has no enrolment for the device you connected from. Being on the "
            "overlay is not admission on its own; enrol the device at the hub, which is "
            "the decision only the owner can make there"
        ),
    ),
    Refusal.REVOKED: AdmissionRefusal(
        code=env.DEVICE_REVOKED,
        message=(
            "this device's enrolment was revoked, and a revoked credential is never "
            "reinstated. Enrol the device again at the hub to mint a new one"
        ),
    ),
    Refusal.CREDENTIAL: AdmissionRefusal(
        code=env.CREDENTIAL_REJECTED,
        message=(
            "the credential presented does not verify against this device's enrolment. "
            "A credential is shown once at enrolment and never again; if it was lost, "
            "enrol the device again, which rotates it in one act"
        ),
    ),
}


class RemoteListener:
    """The hub's second door: one TCP socket on the overlay, admitting two facts.

    Attributes:
        address: The overlay address it binds.
        port: The port it binds.
    """

    def __init__(
        self,
        engine: AssistantEngine,
        settings: Settings,
        *,
        registry: DeviceRegistry,
        agent: OverlayAgent,
        budget: ConnectionBudget,
    ) -> None:
        """Prepare the listener; nothing is bound and nothing is asked until :meth:`start`.

        Args:
            engine: The in-process engine this hub owns.
            settings: The deployment's ceilings, deadline and overlay address.
            registry: The enrolment record's live view (ADR-0124 §6, §8).
            agent: The overlay agent on this machine (§4).
            budget: The hub's shared ceilings (§7).

        Raises:
            ValueError: If ``hub_remote_address`` is unset. A hub with no remote
                configuration constructs no remote listener at all (§2), so
                reaching here without one is a wiring bug rather than a deployment
                state to tolerate.
        """
        if settings.hub_remote_address is None:
            msg = "a remote listener cannot be built without hub_remote_address (ADR-0124 §2)"
            raise ValueError(msg)
        self._engine = engine
        self._settings = settings
        self._registry = registry
        self._agent = agent
        self._budget = budget
        self.address = settings.hub_remote_address
        self.port = settings.hub_remote_port
        self._server: asyncio.Server | None = None
        self._closing = False
        self._tasks: set[asyncio.Task[None]] = set()
        self._writers: dict[str, set[asyncio.StreamWriter]] = {}
        self._build = ""
        registry.when_expelled(self.expel)

    async def start(self, *, build: str) -> None:
        """Confirm the address is the overlay's, then bind and begin accepting.

        The order is the rule: ADR-0124 §2 forbids binding "an address of a physical
        interface", and the only thing that can tell an overlay address from a LAN
        one is the agent — so the question is asked before the socket exists rather
        than after, and a hub that cannot ask stays down.

        Args:
            build: This build's identifier, published in every connect reply.

        Raises:
            ConfigurationError: If the agent does not report the configured address
                as this machine's own, or cannot be asked. A stay-down deployment
                fault (ADR-0083 §5): restarting unchanged never succeeds, and what
                has to change is the configuration or the overlay.
            OSError: If the socket cannot be bound. Left to propagate for the same
                reason the loopback listener leaves it: the raw errno distinguishes
                a stay-down fault from a transient one.
        """
        try:
            reported = await self._agent.hub_identity()
        except OverlayIdentityUnavailableError as exc:
            msg = (
                f"the remote listener is configured to bind {self.address}, and the overlay "
                f"agent on this machine could not be asked whether that address is on the "
                f"overlay ({exc}). ADR-0124 §2 binds only an overlay address, so the hub "
                f"will not bind one it cannot confirm; start the overlay agent, or unset "
                f"ASSISTANT_HUB_REMOTE_ADDRESS to serve the loopback socket alone"
            )
            raise ConfigurationError(msg) from exc
        if self.address not in reported.addresses:
            msg = (
                f"the remote listener is configured to bind {self.address}, which the "
                f"overlay agent does not report as one of this machine's overlay addresses "
                f"({sorted(reported.addresses)}). ADR-0124 §2 forbids binding an address of "
                f"a physical interface; set ASSISTANT_HUB_REMOTE_ADDRESS to one of those"
            )
            raise ConfigurationError(msg)

        self._server = await asyncio.start_server(self._accept, host=self.address, port=self.port)
        self._build = build
        _log.info(
            "hub_remote_listening",
            address=self.address,
            port=self.port,
            hub_overlay_identity=reported.identity,
            max_connections=self._budget.max_connections,
        )

    async def stop_accepting(self) -> None:
        """Close the door, at the start of ADR-0083 §4's phase A.

        **``wait_closed`` is deliberately not awaited**, and the reason is ADR-0083
        §4's ordering rather than impatience. On this runtime
        ``Server.wait_closed()`` does not return until every handler task has
        finished, so awaiting it here would make *closing the door* wait for the
        connections the drain has not run yet — the phases inverted, and a stop that
        appears to hang for as long as the slowest peer holds a socket. ``close()``
        is what stops the accepting, which is all this step is for;
        :meth:`aclose` is what converges the handlers, after the drain, where §4 puts
        it.
        """
        # Set **before** the close and synchronously, which is what makes it a
        # barrier rather than a hint. ``Server.close()`` stops future accepts but
        # says nothing about a callback ``asyncio`` has already queued for a
        # connection it accepted a moment ago; that callback runs on some later turn
        # of the loop, which may be after ADR-0083 §4's release has finished and the
        # engine and the record have been let go. A connection arriving then is one
        # this hub can no longer serve, so it is closed rather than identified.
        self._closing = True
        if self._server is not None:
            self._server.close()
            self._server = None
        _log.info("hub_remote_stopped_accepting", serving=len(self._tasks))

    async def aclose(self) -> None:
        """Let go of any connection still open once the engine has drained."""
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        self._writers.clear()

    def expel(self, identity: str, reason: str) -> None:
        """Close every connection a device holds, because it holds none by right.

        ADR-0124 §8: "Revoking a device closes any connection that device currently
        holds." Called **synchronously from inside the act**, after the record has
        been written and the live view has flipped — so a connection closed here
        cannot have written a frame in between, and one whose close has not yet been
        felt is stopped by :meth:`~ai_assistant.wire.server.Admission.is_live` at
        its next write instead. The two together make the finality unconditional
        rather than prompt.

        **The transport is closed rather than the task cancelled**, which is what
        ADR-0124 §8 means by "implementable without cancellation machinery, since
        the connection is being closed anyway": closing feeds the reader EOF, so an
        idle connection ends at once, while a request already dispatched finishes in
        the engine and simply has nowhere to be delivered. Cancelling would instead
        reach *into* engine work whose bookkeeping ADR-0042 §2 owns, to buy nothing
        the liveness check has not already bought.

        Args:
            identity: The device whose enrolment stopped being live.
            reason: Why — ``revoked`` or ``rotated`` — for the log.
        """
        held = self._writers.get(identity, set())
        for writer in list(held):
            writer.close()
        if held:
            _log.info("hub_remote_device_expelled", reason=reason, connections=len(held))

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Serve one accepted connection, and name any fault the steps before it hit.

        **One connection's fault is never the resident process's**, which
        :func:`~ai_assistant.wire.serve_connection` keeps for everything after the
        handshake (ADR-0084 §3's "the reason is robustness, not secrecy"). The steps
        *before* it — the ceilings and §4's identity query — run in a callback
        ``asyncio`` invokes directly, and this clause is what gives them the same
        rule.

        **What it buys is the diagnosis, and being exact about that matters.**
        ``asyncio`` does close the transport when a client-connected callback raises,
        and the budget slot is returned by :func:`~ai_assistant.service.transport.hold`'s
        own ``finally``, so this is not repairing a leak. What it replaces is the
        loop's generic "Task exception was never retrieved" with a named event on
        the hub's own log — which is the difference between an operator seeing that
        the remote door is refusing connections and seeing a stack trace from
        somewhere in ``asyncio``. The seam declares one failure
        (:class:`~ai_assistant.service.overlay.OverlayIdentityUnavailableError`) and
        an implementation of it may still raise another; ADR-0083's ruling 4 is why
        that arrives as a sentence rather than as a traceback.

        **The connection joins the shutdown's set here, on the first line, and that
        placement is the decision.** Tracking it after §4's identity query — which is
        where the identity is first known and therefore the tempting place — would
        leave a connection *awaiting* that query invisible to
        :meth:`aclose`: nothing would cancel it, so ADR-0083 §4's release would
        finish with an accepted connection still live, which could then enter
        ``serve_connection`` against an engine that had already drained. The seam is
        a Protocol and an implementation of it need not bound its own answer, so
        "the agent replies quickly" is not something this listener may rest on.
        """
        task = asyncio.current_task()
        if task is not None:
            self._tasks.add(task)
        try:
            if self._closing:
                # Registered first and refused second, in that order: a callback that
                # runs during the release must be something :meth:`aclose` can still
                # cancel, as well as something that never reaches the engine.
                await refuse(writer, "hub_remote_closing", "the hub has stopped accepting")
                return
            await self._accepted(reader, writer)
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.exception("hub_remote_accept_failed")
            await refuse(writer, "hub_remote_accept_failed", "the connection was abandoned")
        finally:
            if task is not None:
                self._tasks.discard(task)
            # Closed here as well as in ``serve_connection``'s own hang-up, because a
            # connection cancelled *before* it got that far has never reached one. A
            # second close is a no-op.
            writer.close()

    async def _accepted(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Refuse against the two ceilings and §4's identity, then serve.

        Three refusals happen here rather than in the protocol, and all three are
        the pre-envelope class ADR-0084 §3 answers with a close: the two shared
        ceilings, and a peer whose overlay identity the agent will not give (§4).
        """
        if self._budget.at_connection_ceiling():
            await refuse(writer, "hub_connection_ceiling", self._budget.max_connections)
            return
        if self._budget.at_handshake_ceiling():
            await refuse(writer, "hub_handshake_ceiling", self._budget.max_pending_handshakes)
            return

        # The slot is taken *before* the agent is asked, so a daemon that answers
        # slowly occupies a pending-handshake slot rather than an unbounded number
        # of them. That is exactly what §7 makes that ceiling count.
        with hold(self._budget) as settled:
            identity = await self._identify(writer)
            if identity is None:
                return
            admission = _DeviceAdmission(self._registry, identity)
            self._writers.setdefault(identity, set()).add(writer)

            def _handshaken() -> None:
                """Settle the budget and record the admission, in that order.

                The wire calls this once the handshake has completed, which is the
                only moment at which both are true: the connection has left the
                pending ceiling, and the device really is being served.
                """
                settled()
                admission.record_admission()

            try:
                await serve_connection(
                    self._engine,
                    reader,
                    writer,
                    limits=ConnectionLimits(
                        max_frame_bytes=self._settings.hub_max_frame_bytes,
                        read_timeout=self._settings.hub_read_timeout,
                        build=self._build,
                    ),
                    on_handshake=_handshaken,
                    admission=admission,
                )
            finally:
                held = self._writers.get(identity, set())
                held.discard(writer)
                if not held:
                    self._writers.pop(identity, None)

    async def _identify(self, writer: asyncio.StreamWriter) -> str | None:
        """Ask this machine's overlay agent who connected, or refuse the connection.

        Args:
            writer: The connection, so a refusal can close it.

        Returns:
            The peer's overlay identity, or ``None`` if it could not be obtained.
        """
        peer = writer.get_extra_info("peername")
        if not isinstance(peer, tuple) or len(peer) < 2:  # noqa: PLR2004 - host and port
            await refuse(writer, "hub_remote_peer_unaddressed", "no peer address")
            return None
        host, port = str(peer[0]), int(peer[1])
        try:
            return await self._agent.identify(host, port)
        except OverlayIdentityUnavailableError as exc:
            _log.warning(
                "hub_remote_identity_unavailable",
                reason=str(exc),
                detail=(
                    "the hub takes an identity from its own overlay agent and never from "
                    "the peer, so a peer it cannot name is refused (ADR-0124 §4)"
                ),
            )
            await refuse(writer, "hub_remote_unidentified_peer", "overlay identity unavailable")
            return None


class _DeviceAdmission:
    """One connection's half of ADR-0124 §7's rule and §8's finality.

    Implements :class:`~ai_assistant.wire.server.Admission`. Both methods are
    synchronous and neither touches the database: the registry answers from the
    live view it keeps, which is what lets the wire put a check immediately before
    a write with no suspension point between them.
    """

    def __init__(self, registry: DeviceRegistry, identity: str) -> None:
        """Bind the rule to one device.

        Args:
            registry: The enrolment record's live view.
            identity: The overlay identity the agent gave for this peer.
        """
        self._registry = registry
        self._identity = identity
        self._enrolment_id: int | None = None

    def admit(self, credential: str) -> AdmissionRefusal | None:
        """Decide the two facts, and claim the enrolment they name.

        The claim is the generation half of ADR-0124 §8's compare-and-claim: a
        re-enrolment mints a new enrolment id, so a connection admitted under the
        previous one stops being live the instant the rotation lands — which is §6's
        "leaving its credential verifying against nothing" seen from the connection
        rather than from the record.

        Args:
            credential: A well-formed credential the connect frame carried.

        Returns:
            ``None`` to admit, or why not.
        """
        verdict = self._registry.verify(self._identity, credential)
        if verdict.refusal is not None:
            # Returned rather than recorded here: the wire records **every** refusal
            # through :meth:`record_refusal`, including the ones the frame reader
            # decides before this method is reached, so one call site holds the
            # obligation and no refusal is written twice.
            return _REFUSALS[verdict.refusal]
        self._enrolment_id = verdict.enrolment_id
        return None

    def record_admission(self) -> None:
        """Record that this device completed the handshake and is being served.

        **Fired when the handshake completes, not when the two facts hold**, and the
        difference is one an operator reads. A device whose credential verifies can
        still be refused a moment later — a protocol version this hub does not speak
        is the case — and an "admitted" line written at the claim would leave the log
        asserting a connection that was never served. ADR-0124 §6 wants the record to
        say what the credential was used *for*.
        """
        _log.info(
            "hub_remote_admitted",
            overlay_identity=self._identity,
            enrolment_id=self._enrolment_id,
        )

    def record_refusal(self, code: str) -> None:
        """Record one refusal against the device the agent named (ADR-0124 §6, §7).

        **The code is the wire's token rather than an internal name**, so what an
        owner reads in the log is the same vocabulary the device was sent — which is
        what §7's "in the error it returns and in what the hub logs" asks for, and
        what makes two records of one event correlatable.

        Args:
            code: The lowercase refusal token.
        """
        _log.info("hub_remote_admission_refused", overlay_identity=self._identity, reason=code)

    def is_live(self) -> bool:
        """Whether the enrolment this connection was admitted under is still live.

        Returns:
            Whether a frame may still be written to this device. ``False`` before
            :meth:`admit` has claimed one, which is the safe direction: nothing has
            been admitted, so nothing may be written.
        """
        if self._enrolment_id is None:
            return False
        return self._registry.is_live(self._identity, self._enrolment_id)
