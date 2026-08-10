"""The listener: where the hub binds, when it accepts, and how many it holds.

The protocol itself is :mod:`ai_assistant.wire.server`'s — it is the same on both
sides of the socket and depends on ``core`` alone. What is here is everything that
is a fact about *this deployment*: the address, the ordering against ADR-0083 §3's
startup sequence and §4's shutdown, the file mode, and the two ceilings.

**The bind is not the instance guard, and the ordering is what keeps that true.**
ADR-0083 §14.4: "single-instance enforcement is the lock, not the bind". A stale
``hub.sock`` survives a ``SIGKILL`` and binding over it requires unlinking it
first — which is only safe because ADR-0083 §1's exclusive ``flock`` is already
held by then, and a held lock always means a live holder. So the order is fixed:
take the lock at step 2, and only afterwards unlink any stale socket and bind.
"Unlinking before the lock would let a losing contender delete a live hub's
socket, which is exactly the failure the lock exists to prevent."

**Accepting begins at step 6 and stops at the start of phase A**, which discharges
ADR-0083 §14.2 ("the transport must not accept before readiness") and §4. The
socket file is unlinked at the *start* of the drain rather than the end,
deliberately: "it makes 'draining' indistinguishable from 'not running' to a *new*
client, which is the correct answer — a new request cannot be served either way,
and ruling 4's legibility is served by one clear message rather than by a
connection that hangs for the length of an unbounded phase B."
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.wire import serve_connection
from ai_assistant.wire.address import SOCKET_MODE, socket_path
from ai_assistant.wire.server import ConnectionLimits

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from ai_assistant.core.config import Settings
    from ai_assistant.core.protocols import AssistantEngine

_log = structlog.get_logger(__name__)

#: The umask held while the socket is bound, so the file is never briefly wider
#: than ``0600``. An explicit ``chmod`` follows it: the umask closes the window
#: between ``bind`` and ``chmod``, and the ``chmod`` states the intended mode
#: whatever the umask did. The data directory is ``0700`` and validated
#: (:mod:`ai_assistant.service.datadir`), so even that window is inside a directory
#: no other user can traverse.
_OWNER_ONLY_UMASK: Final[int] = 0o177


class ConnectionBudget:
    """The hub's two ceilings, held once and shared by every listener it binds.

    **A figure per listener is the mistake ADR-0124 §7 exists to forbid**, and it
    says so:

    > Adding it may not let the hub's total concurrent connections exceed
    > ``hub_max_connections``, and a connection awaiting admission on the remote
    > listener counts against ``hub_max_pending_handshakes``.
    >
    > …Two listeners each honouring the figure independently would mean the hub
    > honours neither.

    ADR-0084 §3 set both ceilings against "a *resident* process being held down by a
    peer that connects and stops sending", and that is a property of the process
    rather than of a socket — so the counters are the process's.

    **The counting is synchronous and holds no lock**, because the loop is single
    threaded and a check followed by an increment inside one step is already
    indivisible; a lock would add a suspension point where the whole value of this
    object is that there is none.

    Attributes:
        max_connections: What the hub serves at once, across every listener.
        max_pending_handshakes: How many of those may be awaiting admission.
    """

    def __init__(self, *, max_connections: int, max_pending_handshakes: int) -> None:
        """Hold the deployment's two figures.

        Args:
            max_connections: ``hub_max_connections``.
            max_pending_handshakes: ``hub_max_pending_handshakes``.
        """
        self.max_connections = max_connections
        self.max_pending_handshakes = max_pending_handshakes
        self._serving = 0
        self._handshaking = 0

    @property
    def serving(self) -> int:
        """How many connections the hub currently holds, across every listener."""
        return self._serving

    @property
    def handshaking(self) -> int:
        """How many of those have not completed a handshake."""
        return self._handshaking

    def at_connection_ceiling(self) -> bool:
        """Whether another connection would exceed ``hub_max_connections``."""
        return self._serving >= self.max_connections

    def at_handshake_ceiling(self) -> bool:
        """Whether another pending handshake would exceed its ceiling."""
        return self._handshaking >= self.max_pending_handshakes

    def opened(self) -> None:
        """Count a connection the hub has accepted and not yet handshaken."""
        self._serving += 1
        self._handshaking += 1

    def handshake_settled(self) -> None:
        """Move one connection off the pending ceiling and onto the total alone."""
        self._handshaking -= 1

    def closed(self) -> None:
        """Give one connection's slot back."""
        self._serving -= 1


class Listener:
    """The hub's door: one Unix socket, and the connections it is serving.

    Attributes:
        path: Where it listens.
    """

    def __init__(
        self,
        engine: AssistantEngine,
        settings: Settings,
        *,
        data_dir: Path,
        budget: ConnectionBudget | None = None,
    ) -> None:
        """Prepare a listener; nothing is bound until :meth:`start`.

        Args:
            engine: The in-process engine this hub owns and every request runs on.
            settings: The deployment's transport ceilings and deadline.
            data_dir: The directory the hub owns, which locates the socket.
            budget: The hub's shared ceilings (ADR-0124 §7). Defaulted from
                ``settings`` for a hub that binds this listener alone, so a caller
                that has no second listener does not have to construct one.
        """
        self._engine = engine
        self._settings = settings
        self.path = socket_path(data_dir)
        self._server: asyncio.Server | None = None
        self._connections: set[asyncio.Task[None]] = set()
        self._budget = budget or ConnectionBudget(
            max_connections=settings.hub_max_connections,
            max_pending_handshakes=settings.hub_max_pending_handshakes,
        )
        self._build = ""

    async def start(self, *, build: str) -> None:
        """Unlink any stale socket, bind, and begin accepting (ADR-0083 §3 step 6).

        Args:
            build: This build's identifier, published in every connect reply.

        Raises:
            OSError: If the socket cannot be bound. Left to propagate: the raw
                errno is what distinguishes a stay-down filesystem access fault
                from a transient one (ADR-0083 §3 step 3, §5).
        """
        # Safe only because the instance lock is already held (ADR-0084 §1).
        self.path.unlink(missing_ok=True)
        previous = os.umask(_OWNER_ONLY_UMASK)
        try:
            self._server = await asyncio.start_unix_server(self._accept, path=str(self.path))
        finally:
            os.umask(previous)
        self.path.chmod(SOCKET_MODE)
        _log.info(
            "hub_listening",
            socket=str(self.path),
            max_frame_bytes=self._settings.hub_max_frame_bytes,
            max_connections=self._settings.hub_max_connections,
        )
        self._build = build

    async def stop_accepting(self) -> None:
        """Close the door and remove it, at the start of phase A (ADR-0084 §1)."""
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await self._server.wait_closed()
            self._server = None
        self.path.unlink(missing_ok=True)
        _log.info("hub_stopped_accepting", socket=str(self.path), serving=len(self._connections))

    async def aclose(self) -> None:
        """Let go of any connection still open once the engine has drained.

        The *engine* calls a connection made are tracked work and ADR-0083 §4's
        phases own them; what is left here after the drain is a connection whose
        peer has neither hung up nor sent anything, which nothing else will ever
        end. Cancelling those is what stops a hub that has finished draining from
        staying alive because a spoke forgot to close a socket.
        """
        for task in list(self._connections):
            task.cancel()
        if self._connections:
            await asyncio.gather(*self._connections, return_exceptions=True)
        self._connections.clear()

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Serve one accepted connection, or refuse it against a ceiling.

        **The two ceilings are separate and the handshake one is lower on purpose**
        (ADR-0084 §3). A per-frame deadline bounds each connection but says nothing
        about how many there may be, so without a connection ceiling "a client in a
        crash loop — or a script that forgot to close — exhausts descriptors and
        reader tasks while every individual connection is still inside its
        deadline". And a connection that has not completed the handshake "has cost
        the hub a descriptor and a task while telling it nothing, which is the
        cheapest state for a misbehaving peer to accumulate".

        **Beyond a ceiling the listener refuses rather than queueing**, so the
        client reads a refusal "instead of waiting on something it cannot tell apart
        from a hung hub". The refusal is a close before the handshake, which is the
        pre-envelope class: nothing has decoded, so there is nothing to correlate a
        typed error against.

        **Both figures are the hub's rather than this socket's** (ADR-0124 §7), so
        a remote listener saturating either ceiling is felt here — which is what
        §11's step 11 checks, "in both orders… and for both figures".
        """
        if self._budget.at_connection_ceiling():
            await refuse(writer, "hub_connection_ceiling", self._budget.max_connections)
            return
        if self._budget.at_handshake_ceiling():
            await refuse(writer, "hub_handshake_ceiling", self._budget.max_pending_handshakes)
            return

        task = asyncio.current_task()
        if task is not None:
            self._connections.add(task)
        try:
            with hold(self._budget) as settled:
                await serve_connection(
                    self._engine,
                    reader,
                    writer,
                    limits=ConnectionLimits(
                        max_frame_bytes=self._settings.hub_max_frame_bytes,
                        read_timeout=self._settings.hub_read_timeout,
                        build=self._build,
                    ),
                    on_handshake=settled,
                )
        finally:
            if task is not None:
                self._connections.discard(task)


@contextlib.contextmanager
def hold(budget: ConnectionBudget) -> Iterator[Callable[[], None]]:
    """Occupy one slot of the hub's budget for the length of a connection.

    Yields the callback a listener hands to
    :func:`~ai_assistant.wire.serve_connection` as ``on_handshake``, which moves
    this connection off the *pending* ceiling and onto the total alone. Calling it
    twice is harmless — the block's exit calls it again — because the handshake can
    settle either by completing or by the connection ending before it did, and a
    listener should not have to tell those apart to keep a counter straight.

    Args:
        budget: The hub's shared ceilings.

    Yields:
        The settle callback.
    """
    budget.opened()
    settled = False

    def settle() -> None:
        nonlocal settled
        if not settled:
            settled = True
            budget.handshake_settled()

    try:
        yield settle
    finally:
        settle()
        budget.closed()


async def refuse(writer: asyncio.StreamWriter, event: str, ceiling: int | str) -> None:
    """Close a connection the hub has no budget for, and say so in the log.

    Shared with :mod:`ai_assistant.service.remote`, which refuses against the same
    ceilings and in the same pre-envelope class: nothing has decoded, so there is
    nothing to correlate a typed error against.

    Args:
        writer: The connection to close.
        event: The log event naming which refusal this is.
        ceiling: The figure it was judged against, or a short reason where the
            refusal is not a ceiling's.
    """
    _log.warning(
        event,
        ceiling=ceiling,
        detail="refused rather than queued, so the client reads a refusal rather than a hang",
    )
    writer.close()
    with contextlib.suppress(ConnectionError, OSError, asyncio.CancelledError):
        await writer.wait_closed()
