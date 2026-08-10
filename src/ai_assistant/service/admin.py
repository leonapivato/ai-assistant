"""The hub-local entry point for the owner's device acts (ADR-0124 §6, §8).

> A device is enrolled only by an explicit act of the owner performed at the hub —
> on the hub's own machine, over ADR-0084 §1's loopback transport or a hub-local
> entry point.

**Why a hub-local entry point rather than the loopback transport, argued rather
than preferred.** The loopback transport's requests name a method of the promoted
engine surface, so putting an act there would add a sixteenth method — which
ADR-0085 §3 makes contract surface and ADR-0124 §9 makes a `PROTOCOL_VERSION`
bump, and §9's first clause forbids this lane from making one. So the act takes
the other door §6 offers.

**Why the door has to reach the *running* hub, which forecloses the offline-tool
shape** the re-embedding migration uses (ADR-0104 §5, ADR-0083 §10). ADR-0124 §8
requires that "revoking a device closes any connection that device currently
holds", and §11's step 7 keys its whole check on a revocation landing while the
device "holds an established connection with a request in flight". A tool that
took the instance lock would be a tool that runs only while the hub is stopped, so
there would never be a connection to close and step 7 could not be performed at
all. The act therefore happens *inside* the hub process, which is also what keeps
§6's "written by the hub alone" literally true of the record.

**What it is not.** ADR-0124 §9 is explicit that the version rule "does not reach:
adding a listener", and §10's list of what this decision does not authorise — the
hub dialling out, a delivery seam, a second hub, the client half — is untouched by
a Unix socket in ``data_dir`` that only the owner's uid can open. It carries no
engine call and never will: the surface below is three acts on the enrolment
record and nothing else.

**The credential crosses this socket exactly once and is never stored.** ADR-0124
§6 mints it, discloses it "to the owner once at enrolment and never again", and
the hub retains only a verifier. The value travels from
:class:`~ai_assistant.service.enrolment.DeviceRegistry` to the owner's terminal
and is held nowhere in between — not in the record, and not in a log, where
``core/logging.py`` would redact it in any case.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import structlog

from ai_assistant.core.clock import checked_clock
from ai_assistant.service.overlay import MAX_OVERLAY_IDENTITY_BYTES
from ai_assistant.wire.address import SOCKET_MODE, admin_socket_path, check_admin_socket_path
from ai_assistant.wire.errors import TransportError
from ai_assistant.wire.framing import read_frame, write_frame

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.core.clock import Clock
    from ai_assistant.service.enrolment import DeviceRegistry

_log = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    """The default clock: the wall clock, in UTC.

    A module-level function rather than a lambda so the seam has a name in a
    traceback, matching every other default clock in the tree.

    Returns:
        The current instant, timezone-aware.
    """
    return datetime.now(UTC)


#: The umask held while the socket is bound, so the file is never briefly wider
#: than ``0600`` — the same window :mod:`ai_assistant.service.transport` closes for
#: ``hub.sock``, closed the same way and for the same reason.
_OWNER_ONLY_UMASK: Final[int] = 0o177

#: What one act's request or reply may occupy. Generous for a listing of every
#: device ever enrolled, and small enough that a local caller cannot make the hub
#: hold a large buffer. There is no negotiation of it: both halves ship together
#: with the hub, which is what a *hub-local* entry point means.
ADMIN_FRAME_BYTES: Final[int] = 1024 * 1024

#: How long one act may stall. Short, because both ends are on this machine and the
#: work between them is a handful of SQLite rows.
ADMIN_TIMEOUT: Final[timedelta] = timedelta(seconds=10)

#: The three acts. ``list`` is not one of ADR-0124's normative requirements and is
#: here for ADR-0083's ruling 4: an owner who cannot see which devices are
#: enrolled, and which were revoked and when, cannot check what §6's record says
#: they decided. It discloses no verifier (§7).
ENROL: Final = "enrol"
REVOKE: Final = "revoke"
LIST: Final = "list"


class AdminListener:
    """The control socket, bound beside the hub's own for the length of a run.

    Attributes:
        path: ``<data_dir>/admin.sock``.
    """

    def __init__(self, registry: DeviceRegistry, *, data_dir: Path, now: Clock = _utcnow) -> None:
        """Prepare the listener; nothing is bound until :meth:`start`.

        Args:
            registry: The enrolment record the acts operate on.
            data_dir: The directory the hub owns, which locates the socket.
            now: The clock an enrolment and a revocation are dated from, guarded by
                :func:`~ai_assistant.core.clock.checked_clock` like every other
                injected clock in this tree (ADR-0026 §7).
        """
        self._registry = registry
        self._now = checked_clock(now, owner="AdminListener")
        self.path = admin_socket_path(data_dir)
        self._server: asyncio.Server | None = None
        self._connections: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        """Unlink any stale socket, bind, and begin accepting.

        Safe to unlink only because ADR-0083 §1's instance lock is already held by
        the time a hub reaches this — the same argument
        :mod:`ai_assistant.service.transport` makes for ``hub.sock``, and the same
        ordering.

        Raises:
            ConfigurationError: If the data directory's path cannot hold this
                socket. A stay-down deployment fault (ADR-0083 §5).
            OSError: If the socket cannot be bound. Left to propagate: the raw
                errno tells a stay-down access fault from a transient one.
        """
        check_admin_socket_path(self.path.parent)
        self.path.unlink(missing_ok=True)
        previous = os.umask(_OWNER_ONLY_UMASK)
        try:
            self._server = await asyncio.start_unix_server(self._accept, path=str(self.path))
        finally:
            os.umask(previous)
        self.path.chmod(SOCKET_MODE)
        _log.info("hub_admin_listening", socket=str(self.path))

    async def stop_accepting(self) -> None:
        """Close the door and remove it, at the start of ADR-0083 §4's phase A.

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
        if self._server is not None:
            self._server.close()
            self._server = None
        self.path.unlink(missing_ok=True)
        _log.info("hub_admin_stopped_accepting", socket=str(self.path))

    async def aclose(self) -> None:
        """Let go of any act still in flight once the engine has drained."""
        for task in list(self._connections):
            task.cancel()
        if self._connections:
            await asyncio.gather(*self._connections, return_exceptions=True)
        self._connections.clear()

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Serve one act: read one request frame, answer with one reply frame.

        **One act per connection, and no loop**, which is what keeps this surface
        from growing into a session. There is nothing to correlate and nothing to
        keep, so the connection is the request's scope.
        """
        task = asyncio.current_task()
        if task is not None:
            self._connections.add(task)
        try:
            async with asyncio.timeout(ADMIN_TIMEOUT.total_seconds()):
                body = await read_frame(
                    reader,
                    max_frame_bytes=ADMIN_FRAME_BYTES,
                    timeout=ADMIN_TIMEOUT,
                    idle_timeout=ADMIN_TIMEOUT,
                )
                reply = self._perform(body)
                await write_frame(
                    writer,
                    json.dumps(reply).encode("utf-8"),
                    max_frame_bytes=ADMIN_FRAME_BYTES,
                )
        except (TimeoutError, OSError, ValueError, TransportError) as exc:
            # ``TransportError`` is the project's own hierarchy and is neither an
            # ``OSError`` nor a ``ValueError``: ``read_frame`` raises
            # ``ConnectionClosedError`` when a device command is interrupted between
            # frames, which is the ordinary ending rather than a fault. Without this
            # clause it would fall to the ``except Exception`` below and print a
            # traceback for somebody pressing Ctrl-C.
            _log.info("hub_admin_act_abandoned", reason=str(exc), error_class=type(exc).__name__)
        except asyncio.CancelledError:
            raise
        except Exception:
            # One act's fault must never be the resident process's, which is the
            # same rule ``serve_connection`` keeps for a spoke.
            _log.exception("hub_admin_act_failed")
        finally:
            if task is not None:
                self._connections.discard(task)
            writer.close()
            with contextlib.suppress(ConnectionError, OSError, asyncio.CancelledError):
                await writer.wait_closed()

    def _perform(self, body: bytes) -> dict[str, Any]:  # noqa: PLR0911 — one return per way a request is malformed, plus one per act
        """Decode one request and carry out the act it names.

        Synchronous, and every act inside it is (:mod:`ai_assistant.service.enrolment`
        says why): a revocation's commit, the live view's transition and the close of
        the device's connections are one uninterrupted step, which is ADR-0124 §8's
        indivisibility.

        Args:
            body: The request frame's bytes.

        Returns:
            The reply's members.
        """
        try:
            request = json.loads(body)
        except ValueError:
            return _failed("that is not a request this hub understands")
        if not isinstance(request, dict):
            return _failed("a device act must be a JSON object")
        act = request.get("act")
        if act == LIST:
            return self._listing()
        identity = request.get("identity")
        if not isinstance(identity, str) or not identity.strip():
            return _failed("a device act must name the device's overlay identity")
        identity = identity.strip()
        # **Before the act, not after it**, and the ordering is the guarantee rather
        # than tidiness. An enrolment's reply repeats the identity beside the
        # credential ADR-0124 §6 discloses "once at enrolment and never again", so an
        # identity large enough to overflow that reply would commit a row and then
        # fail to render the one answer the act exists to produce — leaving the
        # device enrolled under a credential nobody read. The store refuses it too
        # (:func:`~ai_assistant.service.enrolment._bounded_identity`); that refusal
        # is the invariant and this one is the sentence an owner gets.
        try:
            size = len(identity.encode("utf-8"))
        except UnicodeEncodeError:
            # A lone surrogate survives ``json.loads`` and has no UTF-8 form; the
            # store refuses it too, but a ``ValueError`` raised there would reach
            # the catch-all below and close the socket without a word.
            return _failed("an overlay identity must be text that can be encoded")
        if size > MAX_OVERLAY_IDENTITY_BYTES:
            return _failed(
                f"an overlay identity is at most {MAX_OVERLAY_IDENTITY_BYTES} bytes; "
                f"use the stable identifier your overlay agent reports for the device"
            )
        if act == ENROL:
            minted = self._registry.enrol(identity, now=self._now())
            return {
                "ok": True,
                "credential": minted.credential,
                "hub_identity": minted.hub_identity,
                "overlay_identity": identity,
                "rotated": minted.rotated,
            }
        if act == REVOKE:
            return {"ok": True, "revoked": self._registry.revoke(identity, now=self._now())}
        return _failed(f"no such device act: {act!r}")

    def _listing(self) -> dict[str, Any]:
        """The newest enrolments the record holds, and this hub's own identity.

        Revoked enrolments are listed rather than hidden, because ADR-0124 §6 keeps
        them — "a revocation is recorded rather than erasing the enrolment it
        revokes, so the record says what the owner actually decided and when" — and
        a surface that dropped them would make the record's own point unreadable.

        **Bounded, and it says what it omitted.** The record only ever grows, so an
        unbounded listing would eventually build a reply larger than
        :data:`ADMIN_FRAME_BYTES` — and the surface an owner uses to *check* the
        record would be the first thing the record's own growth broke, failing as a
        closed connection rather than as an answer. ``omitted`` is what keeps the
        bound honest: a listing that quietly stopped at a limit would be ADR-0083's
        ruling 4 failure in the one place an owner goes to find out what they
        decided.

        Returns:
            The reply's members. No verifier appears in it (§7).
        """
        devices, total = self._registry.enrolments()
        return {
            "ok": True,
            "hub_identity": self._registry.hub_identity,
            "devices": [
                {
                    "overlay_identity": one.overlay_identity,
                    "enrolled_at": one.enrolled_at.isoformat(),
                    "revoked_at": None if one.revoked_at is None else one.revoked_at.isoformat(),
                    "live": one.is_live,
                }
                for one in devices
            ],
            "omitted": total - len(devices),
        }


def _failed(reason: str) -> dict[str, Any]:
    """One refused act, in the shape every reply takes."""
    return {"ok": False, "error": reason}
