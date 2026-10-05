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
engine call and never will: the surface below is the owner's acts on the
enrolment record and the device roster beside it, and nothing else.

**Bound wherever the hub runs** (ADR-0298 §4:13), not only where the remote
listener is configured: a gateway on the hub's own machine serves listed browsers
whether or not the hub has a remote listener, and those browser devices need roles,
which are given here (§4:12). A hub with no remote listener refuses an enrolment in
a sentence — there is no hub identity to disclose and no door to arrive at — and
performs every roster act. ADR-0124 §2:3's "binds only ADR-0084 §1's loopback
socket" is read as the network posture it states: this socket is §6's hub-local
entry point, on the hub's own machine and owner-only, and no door off it.

**Revoking a device removes it from "my devices" and from every conversation's
devices** (ADR-0298 §4:10, ADR-0296 §3:6), each removal a change the other devices
see. The removal comes first, on the conversation store through the engine, with
the device withheld — refused every request and named in no set — and the record's
act follows in the same block, synchronous as ever: the commit, the live view's
transition and the close of the device's connections are one step (ADR-0124 §8).
A removal that fails revokes nothing and says so, so the owner runs the act again.
The acts are performed one at a time, so no other act lands while a revocation
awaits the store, and an act once begun runs to its end even where the owner's
command stopped waiting for the reply.

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
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import structlog

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.errors import AssistantError
from ai_assistant.core.types import DeviceRole
from ai_assistant.service.enrolment import RosterActError
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

#: Removes a revoked device from "my devices" and every conversation's devices,
#: answering whether any set named it (ADR-0298 §4:10). The hub passes the engine's.
type RemoveDevice = Callable[[str], Awaitable[bool]]

#: The acts. ``list`` is not one of ADR-0124's normative requirements and is here
#: for ADR-0083's ruling 4: an owner who cannot see which devices are enrolled, and
#: which were revoked and when, cannot check what §6's record says they decided. It
#: discloses no verifier (§7). ADR-0298 §4:6 makes it list the registrations too.
ENROL: Final = "enrol"
REVOKE: Final = "revoke"
LIST: Final = "list"
#: The roster's acts (ADR-0298 §4:8, §4:9, §4:12): restoring a revoked
#: registration, and giving or taking one role.
RESTORE: Final = "restore"
ASSIGN: Final = "assign"
WITHDRAW: Final = "withdraw"


class AdminListener:
    """The control socket, bound beside the hub's own for the length of a run.

    Attributes:
        path: ``<data_dir>/admin.sock``.
    """

    def __init__(
        self,
        registry: DeviceRegistry,
        *,
        data_dir: Path,
        remove_device: RemoveDevice,
        now: Clock = _utcnow,
    ) -> None:
        """Prepare the listener; nothing is bound until :meth:`start`.

        Args:
            registry: The enrolment record the acts operate on.
            data_dir: The directory the hub owns, which locates the socket.
            remove_device: What removes a revoked device from "my devices" and every
                conversation's devices (ADR-0298 §4:10). **Required**: a revocation
                that left the device an end of its conversations would be half of
                the act the owner asked for.
            now: The clock an enrolment and a revocation are dated from, guarded by
                :func:`~ai_assistant.core.clock.checked_clock` like every other
                injected clock in this tree (ADR-0026 §7).
        """
        self._registry = registry
        self._remove_device = remove_device
        # One act at a time. Every act but a revocation is synchronous and so atomic
        # on the one event loop already; a revocation awaits the conversation store
        # between deciding what it will do and doing it, and another act landing in
        # that gap — a restore, an enrolment — would change what it decided on.
        self._acting = asyncio.Lock()
        # The acts under way, each run to completion whatever happens to the
        # connection that asked for it (:meth:`_act_to_completion`).
        self._acts: set[asyncio.Task[dict[str, Any]]] = set()
        self._now = checked_clock(now, owner="AdminListener")
        self.path = admin_socket_path(data_dir)
        self._server: asyncio.Server | None = None
        self._closing = False
        self._connections: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        """Unlink any stale socket, bind, and begin accepting.

        Safe to unlink only because ADR-0083 §1's instance lock is already held by
        the time a hub reaches this — the same argument
        :mod:`ai_assistant.service.transport` makes for ``hub.sock``, and the same
        ordering.

        **Bound here, serving only at :meth:`begin_serving`.** ADR-0083 §14.2 —
        "the transport must not accept before readiness" — is about the hub not
        answering a request it might then fail to have started for. A hub that binds
        several doors answers that by binding *all* of them before *any* of them
        accepts: otherwise a door opened early can serve a turn during a startup
        that the next bind then fails, and the request was carried out by a hub that
        never came up.

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
            self._server = await asyncio.start_unix_server(
                self._accept, path=str(self.path), start_serving=False
            )
        finally:
            os.umask(previous)
        self.path.chmod(SOCKET_MODE)
        _log.info("hub_admin_bound", socket=str(self.path))

    async def begin_serving(self) -> None:
        """Start accepting on the socket :meth:`start` bound (ADR-0083 §3 step 6)."""
        if self._server is not None:
            await self._server.start_serving()
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
        # The same barrier the remote listener sets, for the same reason: a callback
        # ``asyncio`` queued before the close still runs afterwards, and an act
        # performed then would touch a record the release has already closed.
        self._closing = True
        if self._server is not None:
            self._server.close()
            self._server = None
        self.path.unlink(missing_ok=True)
        _log.info("hub_admin_stopped_accepting", socket=str(self.path))

    async def aclose(self) -> None:
        """Let go of any act still in flight once the engine has drained."""
        for task in [*self._connections, *self._acts]:
            task.cancel()
        if self._connections or self._acts:
            await asyncio.gather(*self._connections, *self._acts, return_exceptions=True)
        self._connections.clear()
        self._acts.clear()

    async def _act_to_completion(self, body: bytes) -> dict[str, Any]:
        """Perform one act, alone, and to its end even if its asker stops waiting.

        **One act at a time.** Every act but a revocation is synchronous and so atomic
        on the one event loop already; a revocation awaits the conversation store
        between deciding what it will do and doing it, and another act landing in
        that gap — a restore, an enrolment — would change what it decided on.

        **Once begun, an act finishes.** The wait for the lock is cancellable — an act
        whose asker gave up before it began never runs — but the act itself is a task
        of its own, shielded from the connection's deadline: a revocation whose reply
        timed out still revokes the device after emptying its sets, and holds the
        device withheld and the lock until it has, rather than stopping between the
        two with the device admitted and its memberships gone.

        Args:
            body: The request frame's bytes.

        Returns:
            The reply's members.
        """
        await self._acting.acquire()
        act = asyncio.ensure_future(self._perform_holding(body))
        self._acts.add(act)
        act.add_done_callback(self._settled)
        return await asyncio.shield(act)

    async def _perform_holding(self, body: bytes) -> dict[str, Any]:
        """Perform one act with the lock already held, and release it at the end."""
        try:
            return await self._perform(body)
        finally:
            self._acting.release()

    def _settled(self, act: asyncio.Task[dict[str, Any]]) -> None:
        """Forget a finished act, logging a fault nobody was left waiting to see."""
        self._acts.discard(act)
        if not act.cancelled() and (fault := act.exception()) is not None:
            _log.error("hub_admin_act_failed", error_class=type(fault).__name__, reason=str(fault))

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
            if self._closing:
                _log.info("hub_admin_act_refused", reason="the hub has stopped accepting")
                return
            async with asyncio.timeout(ADMIN_TIMEOUT.total_seconds()):
                body = await read_frame(
                    reader,
                    max_frame_bytes=ADMIN_FRAME_BYTES,
                    timeout=ADMIN_TIMEOUT,
                    idle_timeout=ADMIN_TIMEOUT,
                )
                reply = await self._act_to_completion(body)
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

    async def _perform(self, body: bytes) -> dict[str, Any]:
        """Decode one request and carry out the act it names.

        Every act on the record is synchronous (:mod:`ai_assistant.service.enrolment`
        says why): a revocation's commit, the live view's transition and the close of
        the device's connections are one uninterrupted step, which is ADR-0124 §8's
        indivisibility. The one suspension is after it: a revocation's removal of
        the device from "my devices" and its conversations (ADR-0298 §4:10).

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
        if not isinstance(act, str) or act not in _NAMING_ACTS:
            return _failed(f"no such device act: {act!r}")
        try:
            return await self._act(act, request)
        except (_MalformedError, RosterActError) as exc:
            return _failed(str(exc))

    async def _act(self, act: str, request: dict[str, Any]) -> dict[str, Any]:
        """Perform one act that names a device.

        Args:
            act: Which act, one of :data:`_NAMING_ACTS`.
            request: The decoded request.

        Returns:
            The reply's members.

        Raises:
            _MalformedError: If a member the act needs is missing or malformed.
            RosterActError: If the record will not perform the act.
        """
        # **Every name is checked before the act, not after it**, and the ordering is
        # the guarantee rather than tidiness. An enrolment's reply repeats the
        # identity beside the credential ADR-0124 §6 discloses "once at enrolment and
        # never again", so an identity large enough to overflow that reply would
        # commit a row and then fail to render the one answer the act exists to
        # produce — leaving the device enrolled under a credential nobody read. The
        # store refuses it too (:func:`~ai_assistant.service.enrolment._bounded_identity`);
        # that refusal is the invariant and this one is the sentence an owner gets.
        identity = _name(request.get("identity"), what="the device's overlay identity")
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
            return await self._revoke(identity, request)
        if act == RESTORE:
            gateway = _name(request.get("gateway"), what="the gateway's device")
            restored = self._registry.restore_registration(
                identity, gateway=gateway, now=self._now()
            )
            return {
                "ok": True,
                "restored": restored,
                "roles": sorted(role.value for role in self._registry.roles_of(identity)),
            }
        role = _role(request.get("role"))
        if act == ASSIGN:
            changed = self._registry.assign(identity, role)
        else:
            changed = self._registry.withdraw(identity, role)
        return {
            "ok": True,
            "changed": changed,
            "roles": sorted(held.value for held in self._registry.roles_of(identity)),
        }

    async def _revoke(self, identity: str, request: dict[str, Any]) -> dict[str, Any]:
        """Revoke a whole device, or one registration of it, and its memberships.

        ADR-0298 §4:10: revoking a device revokes its enrolment and every
        registration of it, clears its roles, and removes it from "my devices" and
        every conversation's devices. Revoking **one** registration removes the
        memberships only where it leaves the device admitted by nothing — the rule the
        record keeps for roles (a device holds a role only while something admits
        it), applied to the sets: a phone still listed at a second gateway keeps its
        place in the conversations it reads.

        **The memberships go first, with the device withheld** (:meth:`~ai_assistant.
        service.enrolment.DeviceRegistry.withheld`), and the record's act follows in
        the same block. While the removal awaits the store the device is refused
        every request and named in no set, so it cannot put itself back; and no state
        is left to finish: a removal that fails has revoked nothing — the owner is
        told, and runs the act again — and a crash between the two has only emptied
        the sets of a device that is still admitted. Removing after the record would
        leave the opposite residue, a revoked device still an end of its
        conversations, which a later naming by another gateway would re-admit into.

        Args:
            identity: The device.
            request: The decoded request, which may name a gateway.

        Returns:
            The reply's members.

        Raises:
            _MalformedError: If a gateway member is present and malformed.
            RosterActError: For ``hub``, which is never revoked (§3:4), checked before
                anything is removed.
        """
        held = request.get("gateway")
        gateway = None if held is None else _name(held, what="the gateway's device")
        self._registry.check_revocable(identity, gateway=gateway)
        empties = gateway is None or not self._registry.admitted_apart_from(
            identity, gateway=gateway
        )
        with self._registry.withheld(identity):
            removed = False
            if empties:
                try:
                    removed = await self._remove_device(identity)
                except (AssistantError, RuntimeError, ValueError) as exc:
                    _log.warning(
                        "hub_admin_device_memberships_unremoved",
                        device=identity,
                        reason=str(exc),
                        error_class=type(exc).__name__,
                    )
                    return _failed(
                        f"nothing was revoked: removing {identity} from your devices and its "
                        f"conversations failed ({type(exc).__name__}: {exc}); run the same "
                        f"revoke again"
                    )
                if removed:
                    _log.info("hub_admin_device_memberships_removed", device=identity)
            if gateway is None:
                revocation = self._registry.revoke_device(identity, now=self._now())
                return {
                    "ok": True,
                    "enrolment": revocation.enrolment,
                    "registrations": revocation.registrations,
                    "roles": sorted(role.value for role in revocation.roles),
                    "memberships": removed,
                }
            revoked = self._registry.revoke_registration(identity, gateway=gateway, now=self._now())
            return {"ok": True, "revoked": revoked, "memberships": removed}

    def _listing(self) -> dict[str, Any]:
        """The newest enrolments, devices and registrations, and this hub's identity.

        Revoked enrolments are listed rather than hidden, because ADR-0124 §6 keeps
        them — "a revocation is recorded rather than erasing the enrolment it
        revokes, so the record says what the owner actually decided and when" — and
        a surface that dropped them would make the record's own point unreadable.
        Revoked registrations are listed for the same reason, and because ADR-0298
        §4:6 lists them "so the owner can see every machine each gateway has named".

        **Bounded, and it says what it omitted.** The record only ever grows, so an
        unbounded listing would eventually build a reply larger than
        :data:`ADMIN_FRAME_BYTES` — and the surface an owner uses to *check* the
        record would be the first thing the record's own growth broke, failing as a
        closed connection rather than as an answer. Each ``*_omitted`` is what keeps
        its bound honest: a listing that quietly stopped at a limit would be
        ADR-0083's ruling 4 failure in the one place an owner goes to find out what
        they decided.

        Returns:
            The reply's members. No verifier appears in it (§7).
        """
        enrolments, enrolled = self._registry.enrolments()
        devices, held = self._registry.roster()
        registrations, registered = self._registry.registrations()
        return {
            "ok": True,
            "hub_identity": self._registry.hub_identity,
            "enrolments": [
                {
                    "overlay_identity": one.overlay_identity,
                    "enrolled_at": one.enrolled_at.isoformat(),
                    "revoked_at": None if one.revoked_at is None else one.revoked_at.isoformat(),
                    "live": one.is_live,
                }
                for one in enrolments
            ],
            "enrolments_omitted": enrolled - len(enrolments),
            "devices": [
                {
                    "device": one.device_id,
                    "kind": one.kind.value,
                    "roles": sorted(role.value for role in one.roles),
                    "admitted": self._registry.is_known(one.device_id),
                }
                for one in devices
            ],
            "devices_omitted": held - len(devices),
            "registrations": [
                {
                    "device": one.device_id,
                    "gateway": one.gateway,
                    "registered_at": one.registered_at.isoformat(),
                    "revoked_at": None if one.revoked_at is None else one.revoked_at.isoformat(),
                    "live": one.is_live,
                }
                for one in registrations
            ],
            "registrations_omitted": registered - len(registrations),
        }


#: The acts that name a device, and so carry an ``identity`` member.
_NAMING_ACTS: Final = frozenset({ENROL, REVOKE, RESTORE, ASSIGN, WITHDRAW})


class _MalformedError(ValueError):
    """A request member an act needs is missing or malformed; its message is the reply."""


def _name(value: object, *, what: str) -> str:
    """Read one device name from a request, bounded as the record bounds it.

    Args:
        value: The member as decoded.
        what: What the member names, for the sentence a refusal carries.

    Returns:
        The name, stripped of surrounding space.

    Raises:
        _MalformedError: If it is not non-blank text the record could hold.
    """
    if not isinstance(value, str) or not value.strip():
        msg = f"a device act must name {what}"
        raise _MalformedError(msg)
    name = value.strip()
    try:
        size = len(name.encode("utf-8"))
    except UnicodeEncodeError:
        # A lone surrogate survives ``json.loads`` and has no UTF-8 form; the store
        # refuses it too, but a ``ValueError`` raised there would reach the
        # catch-all and close the socket without a word.
        msg = "an overlay identity must be text that can be encoded"
        raise _MalformedError(msg) from None
    if size > MAX_OVERLAY_IDENTITY_BYTES:
        msg = (
            f"an overlay identity is at most {MAX_OVERLAY_IDENTITY_BYTES} bytes; "
            f"use the stable identifier your overlay agent reports for the device"
        )
        raise _MalformedError(msg)
    return name


def _role(value: object) -> DeviceRole:
    """Read one role from a request.

    Args:
        value: The member as decoded.

    Returns:
        The role.

    Raises:
        _MalformedError: If it names no role the roster holds.
    """
    for role in DeviceRole:
        if value == role.value:
            return role
    named = ", ".join(role.value for role in DeviceRole)
    msg = f"a role is one of {named}, not {value!r}"
    raise _MalformedError(msg)


def _failed(reason: str) -> dict[str, Any]:
    """One refused act, in the shape every reply takes."""
    return {"ok": False, "error": reason}
