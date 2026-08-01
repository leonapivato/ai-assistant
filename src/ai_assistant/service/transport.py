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


class Listener:
    """The hub's door: one Unix socket, and the connections it is serving.

    Attributes:
        path: Where it listens.
    """

    def __init__(self, engine: AssistantEngine, settings: Settings, *, data_dir: Path) -> None:
        """Prepare a listener; nothing is bound until :meth:`start`.

        Args:
            engine: The in-process engine this hub owns and every request runs on.
            settings: The deployment's transport ceilings and deadline.
            data_dir: The directory the hub owns, which locates the socket.
        """
        self._engine = engine
        self._settings = settings
        self.path = socket_path(data_dir)
        self._server: asyncio.Server | None = None
        self._connections: set[asyncio.Task[None]] = set()
        self._handshaking = 0
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
        """
        if len(self._connections) >= self._settings.hub_max_connections:
            await _refuse(writer, "hub_connection_ceiling", self._settings.hub_max_connections)
            return
        if self._handshaking >= self._settings.hub_max_pending_handshakes:
            await _refuse(
                writer, "hub_handshake_ceiling", self._settings.hub_max_pending_handshakes
            )
            return

        task = asyncio.current_task()
        if task is not None:
            self._connections.add(task)
        self._handshaking += 1
        settled = False

        def _handshake_done() -> None:
            nonlocal settled
            if not settled:
                settled = True
                self._handshaking -= 1

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
                on_handshake=_handshake_done,
            )
        finally:
            _handshake_done()
            if task is not None:
                self._connections.discard(task)


async def _refuse(writer: asyncio.StreamWriter, event: str, ceiling: int) -> None:
    """Close a connection the hub has no budget for, and say so in the log."""
    _log.warning(
        event,
        ceiling=ceiling,
        detail="refused rather than queued, so the client reads a refusal rather than a hang",
    )
    writer.close()
    with contextlib.suppress(ConnectionError, OSError, asyncio.CancelledError):
        await writer.wait_closed()
