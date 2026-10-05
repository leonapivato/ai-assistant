"""The enrolment record: who is admitted, since when, and until what act.

ADR-0124 §6 fixes what is stored and where, and leaves the choice of store to this
lane "under ADR-0083 §6's discipline":

> The enrolment record — a device's overlay identity, its credential verifier,
> when it was enrolled and when it was revoked — is durable state the hub owns,
> held inside ``data_dir`` under ADR-0083's layout, written by the hub alone, and
> surviving a hub restart.

SQLite, because every other durable thing in this directory is SQLite and the
record is a handful of rows with one uniqueness rule that a schema can hold better
than an implementation can.

**Uniqueness is in the schema, not in the code, and ADR-0124 §6 explains what
rests on it.** At most one enrolment of an identity is live at any instant,
because §8's promise depends on "a device" naming exactly one record: "if an
identity could carry two live enrolments, 'its credential' would name two values
and an implementation revoking the record it happened to find would leave the
other one admitting the very device the owner just expelled". A partial unique
index over the live rows is that clause, enforced by the database.

**Nothing here is written in a thread, and that is ADR-0124 §8's mechanism rather
than an oversight.** The corpus's stores hand SQLite to :func:`asyncio.to_thread`
because they sit on the request path with real volume; this one holds a handful of
operator-made rows. What a thread would cost is the thing §8 is about: an ``await``
between the commit and the in-memory transition, so that "a revocation that has
taken effect on the enrolment record" and "a revocation the admission path can
see" would be two instants with a gap between them. Running synchronously makes
them one.

**A revocation is recorded, never erased** (§6), so the record says what the owner
actually decided and when; and re-enrolling is one act that rotates rather than two
acts an implementation could interleave.

**The device roster lives in the same file** (ADR-0298 §4): each device's id and
kind, the two roles the roster holds — source of commands and queries, host of
spokes — and each registration of a machine as a browser device under a gateway.
One file, so that one transaction revokes a device's enrolment, every registration
of it and its roles together, and so that ADR-0126's deletion takes the roster with
the enrolment record, first. The user's end of conversations is not here: it is
membership of "my devices" and of conversations, which the conversation store keeps
(ADR-0293 §3).

**The roster records and answers; it refuses no request.** Which request needs
which role, and the refusal, are the wire server's and the engine's (ADR-0298 §5,
§6), reading this record through :class:`~ai_assistant.service.roster.HubRoster`,
which both listeners hold (§9:3). What is here is the record those checks read —
synchronously, from a live view, for the reason the enrolments are read that way.

**One invariant the roster keeps for itself: a device holds a role only while it is
admitted**, by a live enrolment or a live registration. Every act that leaves a
device with neither clears its roles in the same transaction, which is how §4's "a
device re-admitted after revocation, by re-enrolment or by a restored registration,
holds no role until the user gives it one" holds without the re-admitting act having
to remember it.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.errors import AssistantError
from ai_assistant.core.types import HUB_DEVICE_ID, DeviceRole
from ai_assistant.service.overlay import MAX_OVERLAY_IDENTITY_BYTES
from ai_assistant.wire.credential import mint_credential, verifier_for, verifies

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

_log = structlog.get_logger(__name__)

#: What the registry calls when a device stops being admitted, with the identity
#: and why. The listener registers one (:meth:`DeviceRegistry.when_expelled`).
type ExpelCallback = Callable[[str, str], None]


class Refusal(StrEnum):
    """Why a device was not admitted (ADR-0124 §7).

    The three are distinguished "in the error it returns and in what the hub logs",
    against the login-surface reflex of saying only "no" — because §2 has already
    made the audience the owner's own devices, and "an owner who cannot tell 'I
    never enrolled this laptop' from 'I revoked it last week' from 'I pasted the
    wrong string' is ADR-0083's ruling 4 failure".
    """

    NOT_ENROLLED = "not_enrolled"
    REVOKED = "revoked"
    CREDENTIAL = "credential"


@dataclass(frozen=True, slots=True)
class Verdict:
    """The outcome of ADR-0124 §7's two-fact test.

    Attributes:
        enrolment_id: The live enrolment the connection is admitted under, and the
            generation §8's later checks compare against.
        refusal: Why not, where it was not.
    """

    enrolment_id: int | None = None
    refusal: Refusal | None = None


#: The id of the hub's own machine, in every configuration and whether or not the
#: hub has an overlay identity (ADR-0298 §3:1). It is never enrolled, registered or
#: revoked, and it holds every role by rule rather than by a row (§3:2, §3:4).
HUB_DEVICE: Final = HUB_DEVICE_ID


class DeviceKind(StrEnum):
    """The two kinds of device ADR-0296 §1 admits.

    A machine enrolled at the hub is a hub device, admitted by ADR-0124's two facts;
    a machine a gateway names, and that is not already a device, is a browser
    device, admitted by that gateway. A machine is one device however it is admitted
    (ADR-0296 §1:4), so a browser device later enrolled becomes a hub device and
    keeps its id, its roles and its registrations.
    """

    HUB = "hub_device"
    BROWSER = "browser_device"


#: Every role, which the hub's own machine holds by rule (ADR-0298 §3:2).
#:
#: The roles are ``core``'s :class:`~ai_assistant.core.types.DeviceRole` (§10:1), the
#: enum the requesting device the wire server builds carries, so a role read here
#: reaches the checks without a mapping. Its values are the record's stored text, so
#: the roster's rows read back as that enum unchanged.
EVERY_ROLE: Final[frozenset[DeviceRole]] = frozenset(DeviceRole)

#: How many live registrations one gateway may hold (ADR-0298 §4:7: "a figure the
#: implementing change names"). A gateway names only what its owner listed there,
#: and a household's phones, tablets, watches and laptops fit well inside it; what
#: the bound is for is the other case — a gateway naming machine after machine,
#: which §8 accepts it can do, and which the owner should see stop rather than
#: fill the roster. A naming beyond it is refused, and nothing is registered.
MAX_REGISTRATIONS_PER_GATEWAY: Final[int] = 32


class NamingRefusal(StrEnum):
    """Why the hub does not accept a gateway's name for a browser device (ADR-0298 §6:2).

    All three are the first of §6's reasons — "the device named is not accepted under
    that gateway" — told apart so the owner can see which.
    """

    #: The owner revoked this machine's registration under this gateway; it stays
    #: revoked until the owner restores it (§4:9).
    REVOKED = "revoked"
    #: ``hub``, or the hub's own overlay identity, which no gateway may name (§3:3).
    RESERVED = "reserved"
    #: The gateway already holds :data:`MAX_REGISTRATIONS_PER_GATEWAY` live
    #: registrations, and this naming would add one (§4:7).
    BOUND = "bound"


@dataclass(frozen=True, slots=True)
class NamingVerdict:
    """What the roster made of one gateway naming one machine (ADR-0298 §4:2).

    Attributes:
        refusal: Why the name is not accepted, or ``None`` where it is.
        registered: Whether this naming registered the machine under the gateway —
            the first naming does, and every later one finds the registration.
    """

    refusal: NamingRefusal | None = None
    registered: bool = False

    @property
    def accepted(self) -> bool:
        """Whether the hub accepts the name, so the request acts as that device."""
        return self.refusal is None


class RosterActError(AssistantError):
    """An owner's act on the roster that the record will not perform.

    The message is the whole diagnostic and is printed to the owner by
    ``ai-assistant-device``, so it is written for one: what was refused, and what to
    do instead.
    """


#: The record's file inside ``data_dir`` (ADR-0124 §6, ADR-0083's layout).
ENROLMENTS_FILENAME: Final[str] = "devices.db"

#: How many enrolments one listing carries, newest first. The record only ever
#: grows (ADR-0124 §6 keeps every revocation), so the surface that reads it is
#: bounded and says what it omitted rather than eventually failing to answer at
#: all. Named here rather than left to the caller, following ADR-0083 §7's rule
#: that "a 'bounded default' with no figure" is two callers disagreeing.
LISTING_LIMIT: Final[int] = 200

#: Owner-only, which is ADR-0004 §4's posture. The directory is ``0700`` and
#: validated (:mod:`ai_assistant.service.datadir`); this states the file's own mode
#: rather than inheriting whatever umask the process happened to hold.
_OWNER_ONLY_FILE: Final[int] = 0o600

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS enrolments (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    overlay_identity  TEXT    NOT NULL,
    verifier          TEXT    NOT NULL,
    enrolled_at       TEXT    NOT NULL,
    revoked_at        TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_live_enrolment_per_identity
    ON enrolments (overlay_identity) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS devices (
    device_id       TEXT    PRIMARY KEY,
    kind            TEXT    NOT NULL CHECK (kind IN ('hub_device', 'browser_device')),
    first_known_at  TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS device_roles (
    device_id  TEXT  NOT NULL REFERENCES devices (device_id),
    role       TEXT  NOT NULL CHECK (role IN ('commands', 'spokes')),
    PRIMARY KEY (device_id, role)
);
CREATE TABLE IF NOT EXISTS registrations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id      TEXT    NOT NULL REFERENCES devices (device_id),
    gateway        TEXT    NOT NULL,
    registered_at  TEXT    NOT NULL,
    revoked_at     TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_live_registration_per_gateway
    ON registrations (device_id, gateway) WHERE revoked_at IS NULL;
"""

#: The roster's migration from a record written before it existed: every machine the
#: record has ever enrolled is a hub device, with no role (ADR-0298 §9:4 — "a role is
#: never inferred from what a device could reach before"). Idempotent, so it runs on
#: every open rather than behind a version: a row it would add is a row it added.
_BACKFILL: Final = """
INSERT OR IGNORE INTO devices (device_id, kind, first_known_at)
    SELECT overlay_identity, 'hub_device', MIN(enrolled_at)
    FROM enrolments GROUP BY overlay_identity;
"""

#: A device's roles, cleared where nothing admits it any more — the invariant the
#: module docstring states, as one statement every act that can end an admission
#: runs inside its own transaction.
_CLEAR_ROLES_IF_UNADMITTED: Final = """
DELETE FROM device_roles WHERE device_id = :device
    AND NOT EXISTS (
        SELECT 1 FROM enrolments WHERE overlay_identity = :device AND revoked_at IS NULL
    )
    AND NOT EXISTS (
        SELECT 1 FROM registrations WHERE device_id = :device AND revoked_at IS NULL
    )
"""


@dataclass(frozen=True, slots=True)
class Enrolment:
    """One row of the record, as anything outside this module sees it.

    **The verifier is not on it.** ADR-0124 §7 forbids a refusal from including "the
    credential or the verifier" in what it returns or logs, and the surest way to
    keep a value out of a message is for the value not to be in the object the
    message is rendered from. The verifier stays inside :class:`DeviceRegistry`,
    where the comparison happens.

    Attributes:
        enrolment_id: The row's identity, and the generation ADR-0124 §8's
            compare-and-claim is against. A re-enrolment mints a new one, so a
            connection admitted under the previous enrolment can tell.
        overlay_identity: The device, as the overlay agent names it (§5).
        enrolled_at: When the owner performed the act.
        revoked_at: When the owner revoked it, or ``None`` while it is live.
    """

    enrolment_id: int
    overlay_identity: str
    enrolled_at: datetime
    revoked_at: datetime | None

    @property
    def is_live(self) -> bool:
        """Whether this enrolment still admits its device."""
        return self.revoked_at is None


@dataclass(frozen=True, slots=True)
class MintedEnrolment:
    """What one enrolment act produced, for the owner to read once.

    ADR-0124 §6 makes the two values travel together — "the client holds both, and
    holding the credential without the hub identity is an incomplete enrolment the
    client refuses to connect on" — so they are returned together rather than
    discovered separately.

    Attributes:
        enrolment: The record the hub kept.
        credential: The value disclosed to the owner **once**. The hub retains only
            a verifier, so this object is the only place it exists in this process
            and it is never written anywhere.
        hub_identity: The hub's own overlay identity, which §4 makes the thing the
            client's destination has to match. Not a secret.
        rotated: Whether this act also revoked a live enrolment of the same
            identity — §6's single act, reported so the surface can say what it did.
    """

    enrolment: Enrolment
    credential: str
    hub_identity: str
    rotated: bool


@dataclass(frozen=True, slots=True)
class Registration:
    """One registration of a machine as a browser device under a gateway (ADR-0298 §4).

    Attributes:
        registration_id: The row's identity.
        device_id: The machine, as its overlay identity names it.
        gateway: The connecting device of the request that registered it — an
            enrolled hub device's overlay identity, or :data:`HUB_DEVICE` for a
            gateway on the local socket (§4:4).
        registered_at: When the first naming, or the owner's restoring act, made it.
        revoked_at: When the owner revoked it, or ``None`` while it is live.
    """

    registration_id: int
    device_id: str
    gateway: str
    registered_at: datetime
    revoked_at: datetime | None

    @property
    def is_live(self) -> bool:
        """Whether this registration still admits its machine under its gateway."""
        return self.revoked_at is None


@dataclass(frozen=True, slots=True)
class RosterDevice:
    """One device the roster holds, as the owner's listing shows it.

    Attributes:
        device_id: The machine's id: its overlay identity.
        kind: Which of ADR-0296 §1's two kinds it is.
        roles: The roles the owner has given it.
        first_known_at: When the roster first held it.
    """

    device_id: str
    kind: DeviceKind
    roles: frozenset[DeviceRole]
    first_known_at: datetime


@dataclass(frozen=True, slots=True)
class DeviceRevocation:
    """What revoking a whole device did (ADR-0298 §4:10).

    Attributes:
        enrolment: Whether a live enrolment was revoked.
        registrations: How many live registrations were revoked.
        roles: The roles the device held, and holds no longer.
    """

    enrolment: bool
    registrations: int
    roles: frozenset[DeviceRole]


class EnrolmentStore:
    """The durable half: rows, and the one uniqueness rule over them.

    Attributes:
        path: The database file inside ``data_dir``.
    """

    def __init__(self, path: Path) -> None:
        """Open, or create, the enrolment record.

        Args:
            path: Where it lives.

        Raises:
            sqlite3.Error: If the database cannot be opened or built. Left to
                propagate: a hub that cannot open its own state is a startup fault,
                and the raw class is what ADR-0083 §5's classifier reads.
        """
        self.path = path
        existed = path.exists()
        self._conn = sqlite3.connect(path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.executescript(_BACKFILL)
        if not existed:
            path.chmod(_OWNER_ONLY_FILE)

    def close(self) -> None:
        """Let go of the connection."""
        self._conn.close()

    def recent_enrolments(self, *, limit: int) -> tuple[Sequence[Enrolment], int]:
        """The newest enrolments the record holds, revoked ones included (§6).

        **Bounded in the query rather than after it, because the record only ever
        grows.** ADR-0124 §6 keeps every revocation — "a revocation is recorded
        rather than erasing the enrolment it revokes" — so a deployment that
        re-enrols a device on a schedule accumulates rows without end. An unbounded
        read would eventually build a reply too large for the frame it has to
        travel in, and the surface an owner uses to *check* the record would be the
        first thing the record's own growth broke.

        The total is returned beside the rows so a caller can say what it did not
        show. A listing that silently stopped at a limit would be the shortfall
        ADR-0083's ruling 4 exists to prevent, in the one place an owner goes to
        find out what they decided.

        Args:
            limit: How many rows to return, newest first.

        Returns:
            The rows, **newest first**, and how many the record holds in total.
        """
        rows = self._conn.execute(
            "SELECT id, overlay_identity, enrolled_at, revoked_at FROM enrolments "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        (total,) = self._conn.execute("SELECT count(*) FROM enrolments").fetchone()
        return [_as_enrolment(row) for row in rows], int(total)

    def known_identities(self) -> set[str]:
        """Every device the record has ever held an enrolment for.

        Its own query rather than a walk over
        :meth:`recent_enrolments`, for the reason that method is bounded: the set is
        what ADR-0124 §7's unenrolled/revoked distinction is decided from, and it
        has to be complete however long the history is. ``DISTINCT`` keeps it
        proportional to the number of *devices* rather than to the number of acts.

        Returns:
            The identities.
        """
        rows = self._conn.execute("SELECT DISTINCT overlay_identity FROM enrolments").fetchall()
        return {row["overlay_identity"] for row in rows}

    def live_enrolments(self) -> list[Enrolment]:
        """Every live enrolment, complete and unbounded (ADR-0126 §7).

        Its own query rather than a walk over :meth:`recent_enrolments`, for the
        reason :meth:`known_identities` has one: that method is bounded, and this
        answer may not be. ADR-0126 §7 requires the whole-store delete's report to
        enumerate "every live enrolment with no bound, no page and no omission
        count", because "a report that named the first two hundred devices and
        counted the rest would be a delete presenting itself as complete for every
        device it did not name".

        Rather than :meth:`live_verifiers`, which is the same set, because that one
        carries the verifier and this answer is *printed*. ADR-0124 §7 keeps the
        verifier out of anything rendered to an operator, and :class:`Enrolment`
        exists so that "the surest way to keep a value out of a message is for the
        value not to be in the object the message is rendered from".

        Returns:
            The live enrolments, ordered by the device's overlay identity so two
            runs over one record read the same way.
        """
        rows = self._conn.execute(
            "SELECT id, overlay_identity, enrolled_at, revoked_at FROM enrolments "
            "WHERE revoked_at IS NULL ORDER BY overlay_identity"
        ).fetchall()
        return [_as_enrolment(row) for row in rows]

    def live_verifiers(self) -> dict[str, tuple[int, str]]:
        """The live enrolments, as the admission path needs them.

        Returns:
            Each live device's overlay identity, mapped to its enrolment id and
            its credential verifier.
        """
        rows = self._conn.execute(
            "SELECT id, overlay_identity, verifier FROM enrolments WHERE revoked_at IS NULL"
        ).fetchall()
        return {row["overlay_identity"]: (row["id"], row["verifier"]) for row in rows}

    def enrol(self, identity: str, *, verifier: str, now: datetime) -> tuple[Enrolment, bool]:
        """Record one enrolment, revoking any live one for the same device.

        **One transaction, because ADR-0124 §6 requires one act.** "The two halves
        are not separable, and no intermediate state has two live enrolments for one
        identity, or none." A pair of statements outside a transaction would have
        both intermediate states available to a crash; ``BEGIN IMMEDIATE`` leaves
        the record with exactly one of the two outcomes.

        Args:
            identity: The device's overlay identity.
            verifier: The verifier for the credential just minted.
            now: The instant to record.

        Returns:
            The new enrolment, and whether it displaced a live one.

        Raises:
            ValueError: If the identity is over
                :data:`~ai_assistant.service.overlay.MAX_OVERLAY_IDENTITY_BYTES`.
                **Checked here, before the transaction**, because that ordering is
                the whole of the guarantee: ADR-0124 §6 requires an enrolment to
                disclose its credential once, and an act that committed a row and
                then failed to render its answer would have minted a credential
                nobody ever read and left the device enrolled under it.
        """
        _bounded_identity(identity)
        stamp = _stamp(now)
        with self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            rotated = bool(
                self._conn.execute(
                    "UPDATE enrolments SET revoked_at = ? "
                    "WHERE overlay_identity = ? AND revoked_at IS NULL",
                    (stamp, identity),
                ).rowcount
            )
            cursor = self._conn.execute(
                "INSERT INTO enrolments (overlay_identity, verifier, enrolled_at, revoked_at) "
                "VALUES (?, ?, ?, NULL)",
                (identity, verifier, stamp),
            )
            # The roster's half of the same act: an enrolled machine is a hub device
            # (ADR-0296 §1:1), and one already known as a browser device becomes one
            # keeping its id, roles and registrations (§1:4).
            self._conn.execute(
                "INSERT INTO devices (device_id, kind, first_known_at) VALUES (?, ?, ?) "
                "ON CONFLICT (device_id) DO UPDATE SET kind = excluded.kind",
                (identity, DeviceKind.HUB.value, stamp),
            )
        enrolment_id = cursor.lastrowid
        assert enrolment_id is not None  # noqa: S101 - a fresh AUTOINCREMENT row always has one
        return (
            Enrolment(
                enrolment_id=enrolment_id,
                overlay_identity=identity,
                enrolled_at=now,
                revoked_at=None,
            ),
            rotated,
        )

    def revoke(self, identity: str, *, now: datetime) -> bool:
        """Record a revocation of whatever live enrolment a device holds.

        Args:
            identity: The device's overlay identity.
            now: The instant to record.

        Returns:
            Whether a live enrolment was revoked. ``False`` means the device had
            none, which is not an error — the owner asked for a state that already
            holds.
        """
        with self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            changed = self._conn.execute(
                "UPDATE enrolments SET revoked_at = ? "
                "WHERE overlay_identity = ? AND revoked_at IS NULL",
                (_stamp(now), identity),
            ).rowcount
            self._conn.execute(_CLEAR_ROLES_IF_UNADMITTED, {"device": identity})
        return bool(changed)

    # --- the device roster (ADR-0298 §4) ---------------------------------------

    def device_kinds(self) -> dict[str, DeviceKind]:
        """Every device the roster holds, with its kind, complete and unbounded.

        Returns:
            Each device's id, mapped to its kind.
        """
        rows = self._conn.execute("SELECT device_id, kind FROM devices").fetchall()
        return {row["device_id"]: DeviceKind(row["kind"]) for row in rows}

    def device_roles(self) -> dict[str, frozenset[DeviceRole]]:
        """Every role the roster holds, complete and unbounded.

        Returns:
            Each device holding at least one role, mapped to its roles.
        """
        held: dict[str, set[DeviceRole]] = {}
        for row in self._conn.execute("SELECT device_id, role FROM device_roles"):
            held.setdefault(row["device_id"], set()).add(DeviceRole(row["role"]))
        return {device: frozenset(roles) for device, roles in held.items()}

    def registration_pairs(self) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
        """Every registration's state, as the live view needs it.

        Returns:
            The ``(device, gateway)`` pairs holding a live registration, and the
            pairs whose registration the owner revoked and has not restored.
        """
        live: set[tuple[str, str]] = set()
        ever: set[tuple[str, str]] = set()
        for row in self._conn.execute("SELECT device_id, gateway, revoked_at FROM registrations"):
            pair = (row["device_id"], row["gateway"])
            ever.add(pair)
            if row["revoked_at"] is None:
                live.add(pair)
        return live, ever - live

    def register(self, device: str, *, gateway: str, now: datetime) -> int:
        """Register a machine under a gateway, as the first naming does (ADR-0298 §4:2).

        A machine that is not yet a device becomes a browser device with no role; a
        machine that is already one keeps its kind and its roles (§4:3). One
        transaction, so a crash leaves either both rows or neither.

        Args:
            device: The machine the gateway named.
            gateway: The connecting device of the request that named it.
            now: The instant to record.

        Returns:
            The new registration's id.
        """
        _bounded_identity(device)
        stamp = _stamp(now)
        with self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.execute(
                "INSERT OR IGNORE INTO devices (device_id, kind, first_known_at) VALUES (?, ?, ?)",
                (device, DeviceKind.BROWSER.value, stamp),
            )
            cursor = self._conn.execute(
                "INSERT INTO registrations (device_id, gateway, registered_at, revoked_at) "
                "VALUES (?, ?, ?, NULL)",
                (device, gateway, stamp),
            )
        registration_id = cursor.lastrowid
        assert registration_id is not None  # noqa: S101 - a fresh AUTOINCREMENT row always has one
        return registration_id

    def revoke_registration(self, device: str, *, gateway: str, now: datetime) -> bool:
        """Revoke one machine's live registration under one gateway (ADR-0298 §4:8).

        Args:
            device: The machine.
            gateway: The gateway it is registered under.
            now: The instant to record.

        Returns:
            Whether a live registration was revoked.
        """
        with self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            changed = self._conn.execute(
                "UPDATE registrations SET revoked_at = ? "
                "WHERE device_id = ? AND gateway = ? AND revoked_at IS NULL",
                (_stamp(now), device, gateway),
            ).rowcount
            self._conn.execute(_CLEAR_ROLES_IF_UNADMITTED, {"device": device})
        return bool(changed)

    def restore_registration(self, device: str, *, gateway: str, now: datetime) -> None:
        """Record a new live registration where the owner revoked one (ADR-0298 §4:9).

        A new row rather than an erased revocation, for the reason an enrolment's
        revocation is never erased: the record says what the owner decided and when.
        The caller has established that the pair holds a revoked registration and no
        live one; the schema's partial unique index refuses a second live one anyway.

        Args:
            device: The machine.
            gateway: The gateway it was registered under.
            now: The instant to record.
        """
        with self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.execute(
                "INSERT INTO registrations (device_id, gateway, registered_at, revoked_at) "
                "VALUES (?, ?, ?, NULL)",
                (device, gateway, _stamp(now)),
            )

    def revoke_device(self, device: str, *, now: datetime) -> DeviceRevocation:
        """Revoke a whole device, in one transaction (ADR-0298 §4:10).

        Its enrolment, if it has one, every registration of it, and its roles — so
        no instant has a device whose enrolment is revoked and whose browser
        registration still admits it with the roles it held.

        Args:
            device: The machine.
            now: The instant to record.

        Returns:
            What the act revoked.
        """
        stamp = _stamp(now)
        with self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            enrolment = self._conn.execute(
                "UPDATE enrolments SET revoked_at = ? "
                "WHERE overlay_identity = ? AND revoked_at IS NULL",
                (stamp, device),
            ).rowcount
            registrations = self._conn.execute(
                "UPDATE registrations SET revoked_at = ? "
                "WHERE device_id = ? AND revoked_at IS NULL",
                (stamp, device),
            ).rowcount
            roles = frozenset(
                DeviceRole(row["role"])
                for row in self._conn.execute(
                    "SELECT role FROM device_roles WHERE device_id = ?", (device,)
                )
            )
            self._conn.execute("DELETE FROM device_roles WHERE device_id = ?", (device,))
        return DeviceRevocation(enrolment=bool(enrolment), registrations=registrations, roles=roles)

    def assign_role(self, device: str, role: DeviceRole) -> bool:
        """Give a device one role.

        Args:
            device: A device the roster holds; the caller has established that it is
                admitted, which the roster's invariant requires.
            role: The role.

        Returns:
            Whether the device did not already hold it.
        """
        with self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            changed = self._conn.execute(
                "INSERT OR IGNORE INTO device_roles (device_id, role) VALUES (?, ?)",
                (device, role.value),
            ).rowcount
        return bool(changed)

    def withdraw_role(self, device: str, role: DeviceRole) -> bool:
        """Take one role from a device.

        Args:
            device: The device.
            role: The role.

        Returns:
            Whether the device held it.
        """
        with self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            changed = self._conn.execute(
                "DELETE FROM device_roles WHERE device_id = ? AND role = ?",
                (device, role.value),
            ).rowcount
        return bool(changed)

    def recent_devices(self, *, limit: int) -> tuple[Sequence[RosterDevice], int]:
        """The devices the roster holds, newest first, bounded as the enrolments are.

        Args:
            limit: How many to return.

        Returns:
            The devices and how many the roster holds in all.
        """
        rows = self._conn.execute(
            "SELECT device_id, kind, first_known_at FROM devices "
            "ORDER BY first_known_at DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
        roles = self.device_roles()
        (total,) = self._conn.execute("SELECT count(*) FROM devices").fetchone()
        return [
            RosterDevice(
                device_id=row["device_id"],
                kind=DeviceKind(row["kind"]),
                roles=roles.get(row["device_id"], frozenset()),
                first_known_at=_instant(row["first_known_at"]),
            )
            for row in rows
        ], int(total)

    def recent_registrations(self, *, limit: int) -> tuple[Sequence[Registration], int]:
        """The registrations the record holds, revoked ones included, newest first.

        Bounded for :meth:`recent_enrolments`' reason: a revocation is kept, so the
        record only grows.

        Args:
            limit: How many to return.

        Returns:
            The registrations and how many the record holds in all.
        """
        rows = self._conn.execute(
            "SELECT id, device_id, gateway, registered_at, revoked_at FROM registrations "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        (total,) = self._conn.execute("SELECT count(*) FROM registrations").fetchone()
        return [_as_registration(row) for row in rows], int(total)


class DeviceRegistry:
    """The hub's live view of the record, and the instant a revocation takes effect.

    **This class is where ADR-0124 §8's linearization point actually is.** The
    admission path and the write path both ask it synchronous questions
    (:meth:`admit`, :meth:`is_live`), and the two acts that change an answer
    (:meth:`enrol`, :meth:`revoke`) commit to the database and update this view
    inside one uninterrupted step. On a system that "composes on one event loop"
    that is what makes "a revocation that has taken effect on the enrolment record"
    one instant rather than a window.

    **The in-memory view is not a cache with an invalidation problem**, because the
    record has exactly one writer: ADR-0124 §6 requires the acts to be performed "at
    the hub" and ADR-0083 §1's instance lock means one hub per data directory. A
    second writer would be a different design, and the store's schema would still
    hold the uniqueness rule if one ever appeared.
    """

    def __init__(
        self,
        store: EnrolmentStore,
        *,
        hub_identity: str | None,
        max_registrations_per_gateway: int = MAX_REGISTRATIONS_PER_GATEWAY,
    ) -> None:
        """Read the record into the hub's live view.

        Args:
            store: The durable record.
            hub_identity: This hub's own overlay identity, disclosed beside every
                credential it mints (§6) — or ``None`` on a hub with no remote
                listener, which asks no overlay agent what it is and so enrols
                nothing (:meth:`enrol`), while its roster acts still work
                (ADR-0298 §4:13).
            max_registrations_per_gateway: ADR-0298 §4:7's bound. A parameter so a
                test can reach it without naming dozens of machines; the hub passes
                nothing.
        """
        self._store = store
        self._hub_identity = hub_identity
        self._live = store.live_verifiers()
        # Every identity the record has ever held, so that ADR-0124 §7's
        # unenrolled/revoked distinction costs the admission path no query. It
        # matters beyond speed: a synchronous verdict is what lets §8's checks be
        # synchronous, and a database read on the admission path would be one more
        # place an ``await`` could be introduced later without anyone noticing.
        self._known = store.known_identities()
        self._on_expelled: list[ExpelCallback] = []
        # The roster's live view, for the same reason: a gateway's naming is decided
        # on every request it relays (ADR-0298 §2:1), so it costs no query either.
        self._max_per_gateway = max_registrations_per_gateway
        self._kinds = store.device_kinds()
        self._roles = store.device_roles()
        self._registered, self._withdrawn = store.registration_pairs()
        self._per_gateway = Counter(gateway for _, gateway in self._registered)
        # Devices an owner's revocation is removing from "my devices" and their
        # conversations right now (:meth:`withheld`). In memory only: a revocation in
        # flight when the hub stops has revoked nothing yet, so nothing outlives it.
        self._withheld: Counter[str] = Counter()
        if hub_identity is not None and hub_identity in self._live:
            # A record written before ADR-0298 §3:4 refused it can hold a live
            # enrolment of the hub's own overlay identity. Nothing here revokes it on
            # the owner's behalf — an upgrade is not an owner's act — so the owner is
            # told, at every start, what to run.
            _log.warning(
                "device_hub_identity_enrolled",
                overlay_identity=hub_identity,
                detail=(
                    "the hub's own overlay identity holds a live enrolment, which "
                    "ADR-0298 §3 no longer allows: the hub's own machine reaches it "
                    "through the local socket alone. Revoke it with "
                    "'ai-assistant-device revoke <identity>'"
                ),
            )

    @property
    def hub_identity(self) -> str | None:
        """This hub's own overlay identity (ADR-0124 §4, §6), where it has one."""
        return self._hub_identity

    def when_expelled(self, callback: ExpelCallback) -> None:
        """Register what to do to a device's connections when it loses its enrolment.

        ADR-0124 §8: "Revoking a device closes any connection that device currently
        holds." The registry owns *when*; the listener owns *what* — it is the only
        thing that knows which connections exist — so the two are joined here rather
        than by one importing the other.

        Args:
            callback: Called synchronously, inside the act, with the identity whose
                enrolment has just stopped being live.
        """
        self._on_expelled.append(callback)

    def live_enrolment_id(self, identity: str) -> int | None:
        """Which enrolment of a device is live right now.

        Args:
            identity: The device's overlay identity.

        Returns:
            The live enrolment's id, or ``None`` if the device has none.
        """
        found = self._live.get(identity)
        return None if found is None else found[0]

    def verify(self, identity: str, credential: str) -> Verdict:
        """Decide ADR-0124 §7's two facts, in the order it states them.

        Args:
            identity: The device's overlay identity, as §4 obtained it — never as
                the peer asserted it.
            credential: A well-formed credential the connect frame carried.

        Returns:
            Which of the three refusals applies, or the live enrolment's id.
        """
        found = self._live.get(identity)
        if found is None:
            known = identity in self._known
            return Verdict(refusal=Refusal.REVOKED if known else Refusal.NOT_ENROLLED)
        enrolment_id, verifier = found
        if not verifies(credential, verifier):
            return Verdict(refusal=Refusal.CREDENTIAL)
        return Verdict(enrolment_id=enrolment_id)

    def is_live(self, identity: str, enrolment_id: int) -> bool:
        """Whether the enrolment a connection was admitted under is still live.

        Synchronous, and every caller puts it immediately before a write with no
        ``await`` between (ADR-0124 §8).

        Args:
            identity: The device's overlay identity.
            enrolment_id: The enrolment the connection claimed at admission.

        Returns:
            Whether that same enrolment is still the live one.
        """
        found = self._live.get(identity)
        return found is not None and found[0] == enrolment_id

    def enrol(self, identity: str, *, now: datetime) -> MintedEnrolment:
        """Perform ADR-0124 §6's enrolment act, rotating a live one if there is one.

        Args:
            identity: The device to enrol.
            now: The instant to record.

        Returns:
            The credential to show the owner once, the hub identity beside it, and
            the record that was kept.

        Raises:
            RosterActError: On a hub with no overlay identity, which has nothing to
                disclose beside the credential (§6) and no listener for the device to
                arrive on; and for ``hub`` or the hub's own overlay identity, which
                ADR-0298 §3:4 never enrols. Checked before anything is minted.
        """
        hub_identity = self._hub_identity
        if hub_identity is None:
            msg = (
                "this hub has no remote listener, so an enrolment would have no hub "
                "identity to disclose beside its credential and no door for the device "
                "to arrive at; set ASSISTANT_HUB_REMOTE_ADDRESS, restart the hub, and "
                "enrol again"
            )
            raise RosterActError(msg)
        self._refuse_the_hub(identity, act="enrolled")
        credential = mint_credential()
        verifier = verifier_for(credential)
        enrolment, rotated = self._store.enrol(identity, verifier=verifier, now=now)
        # The database has committed and these lines are the same synchronous step,
        # so no coroutine can observe the intermediate state §6 forbids: two live
        # enrolments for one identity, or none.
        self._live[identity] = (enrolment.enrolment_id, verifier)
        self._known.add(identity)
        self._kinds[identity] = DeviceKind.HUB
        if rotated:
            self._expel(identity, reason="rotated")
        _log.info(
            "device_enrolled",
            overlay_identity=identity,
            enrolment_id=enrolment.enrolment_id,
            rotated=rotated,
        )
        return MintedEnrolment(
            enrolment=enrolment,
            credential=credential,
            hub_identity=hub_identity,
            rotated=rotated,
        )

    def revoke(self, identity: str, *, now: datetime) -> bool:
        """Perform ADR-0124 §8's revocation act.

        The order inside is the rule: the record is written, the live view flips in
        the same step, and only then are the device's connections closed. A close
        that ran first would leave a window in which the device could reconnect and
        be admitted by a record that still said it was live.

        Args:
            identity: The device to revoke.
            now: The instant to record.

        Returns:
            Whether a live enrolment was revoked.
        """
        revoked = self._store.revoke(identity, now=now)
        self._live.pop(identity, None)
        self._settle_roles(identity)
        if revoked:
            self._expel(identity, reason="revoked")
            _log.info("device_revoked", overlay_identity=identity)
        return revoked

    def enrolments(self, *, limit: int = LISTING_LIMIT) -> tuple[Sequence[Enrolment], int]:
        """The newest enrolments the record holds, and how many it holds in all.

        Args:
            limit: How many to return, newest first.

        Returns:
            The rows and the total, so a surface can say what it did not show.
        """
        return self._store.recent_enrolments(limit=limit)

    # --- the device roster (ADR-0298 §3, §4) -----------------------------------

    def accept_naming(self, gateway: str, name: str, *, now: datetime) -> NamingVerdict:
        """Decide whether the hub accepts a gateway's name for a browser device.

        ADR-0298 §4:2: "the first request on which a gateway names a machine
        registers it under that gateway", so this is both the check and, the first
        time, the registration — and the registration stands whatever the request
        it rode on is then refused for (§6:1). The hub refuses the name only for a
        registration the owner revoked under that gateway (§4:9), for ``hub`` and
        the hub's own overlay identity (§3:3), and beyond the gateway's bound
        (§4:7).

        Synchronous, like :meth:`verify`, and answered from the live view: the first
        naming writes one transaction, and every later one reads nothing.

        Args:
            gateway: The connecting device of the request: an enrolled hub device's
                overlay identity on the remote listener, or :data:`HUB_DEVICE` on the
                local socket (§4:4). The caller's to establish; the roster takes it as
                given, as the wire server takes ``Admission.device``.
            name: The machine the gateway named. The wire decoder has already held it
                to ADR-0298 §1:3's form.
            now: The instant a registration is recorded at.

        Returns:
            Whether the name is accepted, why not where it is not, and whether this
            naming registered the machine.

        Raises:
            ValueError: If a name that would be registered has no UTF-8 form or is
                over :data:`~ai_assistant.service.overlay.MAX_OVERLAY_IDENTITY_BYTES`
                — a name the wire decoder refuses first, refused here too so the
                record cannot hold one it could not report.
        """
        if name in self._reserved():
            return NamingVerdict(refusal=NamingRefusal.RESERVED)
        pair = (name, gateway)
        if pair in self._registered:
            return NamingVerdict()
        if pair in self._withdrawn:
            return NamingVerdict(refusal=NamingRefusal.REVOKED)
        if self._per_gateway[gateway] >= self._max_per_gateway:
            _log.warning(
                "device_registration_refused",
                device=name,
                gateway=gateway,
                reason=NamingRefusal.BOUND.value,
                bound=self._max_per_gateway,
            )
            return NamingVerdict(refusal=NamingRefusal.BOUND)
        registration_id = self._store.register(name, gateway=gateway, now=now)
        self._registered.add(pair)
        self._per_gateway[gateway] += 1
        self._kinds.setdefault(name, DeviceKind.BROWSER)
        _log.info(
            "device_registered",
            device=name,
            gateway=gateway,
            registration_id=registration_id,
            kind=self._kinds[name].value,
        )
        return NamingVerdict(registered=True)

    def roles_of(self, device: str) -> frozenset[DeviceRole]:
        """The roles a device holds, as the checks read them at dispatch.

        Args:
            device: The device's id.

        Returns:
            :data:`EVERY_ROLE` for :data:`HUB_DEVICE` (ADR-0298 §3:2); otherwise the
            roles the owner gave it, which is none for a device the roster does not
            hold or that nothing admits.
        """
        if device == HUB_DEVICE:
            return EVERY_ROLE
        return self._roles.get(device, frozenset())

    def is_known(self, device: str) -> bool:
        """Whether the hub knows a device, as "my devices" and a conversation's devices need.

        ADR-0298 §4:11: "``hub``, an enrolled hub device whose enrolment is live, or a
        browser device with a live registration".

        Args:
            device: The device's id.

        Returns:
            Whether it is one of those.
        """
        return device == HUB_DEVICE or self._is_admitted(device)

    def kind_of(self, device: str) -> DeviceKind | None:
        """Which kind of device the roster holds a machine as.

        Args:
            device: The device's id.

        Returns:
            Its kind, or ``None`` for a machine the roster has never held — and for
            :data:`HUB_DEVICE`, which is not a row.
        """
        return self._kinds.get(device)

    def assign(self, device: str, role: DeviceRole) -> bool:
        """Give a device one role, as the owner's act at the hub (ADR-0298 §4:12).

        Args:
            device: The device.
            role: The role.

        Returns:
            Whether the device did not already hold it.

        Raises:
            RosterActError: For the hub's own machine, which holds every role by rule;
                and for a machine nothing admits, because a role is held only while a
                device is admitted and a machine never named or enrolled is no
                device yet.
        """
        self._refuse_the_hub(device, act="given a role")
        if not self._is_admitted(device):
            msg = (
                f"{device} is not a device this hub admits: enrol it, or let a gateway "
                f"that lists it name it once, then give it the role. A device whose "
                f"registrations and enrolment were all revoked holds no role until it is "
                f"admitted again"
            )
            raise RosterActError(msg)
        changed = self._store.assign_role(device, role)
        self._roles[device] = self._roles.get(device, frozenset()) | {role}
        if changed:
            _log.info("device_role_assigned", device=device, role=role.value)
        return changed

    def withdraw(self, device: str, role: DeviceRole) -> bool:
        """Take one role from a device.

        Args:
            device: The device.
            role: The role.

        Returns:
            Whether the device held it.

        Raises:
            RosterActError: For the hub's own machine, whose roles are not a row.
        """
        self._refuse_the_hub(device, act="stripped of a role")
        changed = self._store.withdraw_role(device, role)
        remaining = self._roles.get(device, frozenset()) - {role}
        if remaining:
            self._roles[device] = remaining
        else:
            self._roles.pop(device, None)
        if changed:
            _log.info("device_role_withdrawn", device=device, role=role.value)
        return changed

    def revoke_device(self, device: str, *, now: datetime) -> DeviceRevocation:
        """Revoke a whole device: its enrolment, every registration of it, its roles.

        ADR-0298 §4:10. Its removal from "my devices" and from every conversation's
        devices, and the end of its open change streams, are the same clause's other
        half, and belong to the conversation store and the session: the owner's act
        (:class:`~ai_assistant.service.admin.AdminListener`) removes it from the sets
        once this has returned, and a browser device's next request is refused here
        (:meth:`accept_naming`). A revoked enrolment closes the device's connections
        here, as ADR-0124 §8 requires, after the record and the live view have both
        moved.

        Args:
            device: The device.
            now: The instant to record.

        Returns:
            What was revoked.

        Raises:
            RosterActError: For ``hub``, which is never revoked (§3:4).
        """
        # ``hub`` alone, not the hub's own overlay identity as well: §3:4 refuses that
        # identity *as an enrolment*, and a record written before ADR-0298 can hold
        # one — the owner's revocation is the only act that ends it, and revoking
        # can only take access away.
        if device == HUB_DEVICE:
            self._refuse_the_hub(device, act="revoked")
        revocation = self._store.revoke_device(device, now=now)
        self._live.pop(device, None)
        self._roles.pop(device, None)
        for pair in [pair for pair in self._registered if pair[0] == device]:
            self._registered.discard(pair)
            self._withdrawn.add(pair)
            self._per_gateway[pair[1]] -= 1
        if revocation.enrolment:
            self._expel(device, reason="revoked")
        _log.info(
            "device_revoked_whole",
            device=device,
            enrolment=revocation.enrolment,
            registrations=revocation.registrations,
            roles=sorted(role.value for role in revocation.roles),
        )
        return revocation

    def revoke_registration(self, device: str, *, gateway: str, now: datetime) -> bool:
        """Revoke one machine's registration under one gateway (ADR-0298 §4:8).

        It stays revoked: the gateway naming the machine again is refused and
        registers nothing (§4:9), until :meth:`restore_registration`.

        Args:
            device: The machine.
            gateway: The gateway.
            now: The instant to record.

        Returns:
            Whether a live registration was revoked.

        Raises:
            RosterActError: For the hub's own machine, which is never registered.
        """
        self._refuse_the_hub(device, act="registered or revoked")
        revoked = self._store.revoke_registration(device, gateway=gateway, now=now)
        pair = (device, gateway)
        if pair in self._registered:
            self._registered.discard(pair)
            self._withdrawn.add(pair)
            self._per_gateway[gateway] -= 1
        self._settle_roles(device)
        if revoked:
            _log.info("device_registration_revoked", device=device, gateway=gateway)
        return revoked

    def restore_registration(self, device: str, *, gateway: str, now: datetime) -> bool:
        """Restore a registration the owner revoked — the only way one comes back (§4:9).

        A device this re-admits holds no role, because the act that left it
        unadmitted cleared them (§4:11's "holds no role until the user gives it
        one"); a device something else still admitted keeps the roles it held.

        **Held to the gateway's bound**, as a naming is (§4:7): the bound is on the
        *live* registrations under one gateway, and a restore that took the gateway
        past it would leave more machines than the figure accepted under it.

        Args:
            device: The machine.
            gateway: The gateway it was registered under.
            now: The instant to record.

        Returns:
            Whether a registration was restored; ``False`` where it is already live.

        Raises:
            RosterActError: For the hub's own machine; where no registration of the
                machine under that gateway was ever revoked — restoring is not a way to
                register a machine its gateway never named; and where the gateway
                already holds its bound of live registrations.
        """
        self._refuse_the_hub(device, act="registered or revoked")
        pair = (device, gateway)
        if pair in self._registered:
            return False
        if pair not in self._withdrawn:
            msg = (
                f"{device} has no revoked registration under {gateway} to restore; a "
                f"machine is registered by its gateway naming it, not by an act here"
            )
            raise RosterActError(msg)
        if self._per_gateway[gateway] >= self._max_per_gateway:
            msg = (
                f"{gateway} already holds {self._max_per_gateway} live registrations, "
                f"the most one gateway may hold; revoke one it no longer needs, then "
                f"restore this one"
            )
            raise RosterActError(msg)
        self._store.restore_registration(device, gateway=gateway, now=now)
        self._withdrawn.discard(pair)
        self._registered.add(pair)
        self._per_gateway[gateway] += 1
        _log.info("device_registration_restored", device=device, gateway=gateway)
        return True

    def roster(self, *, limit: int = LISTING_LIMIT) -> tuple[Sequence[RosterDevice], int]:
        """The newest devices the roster holds, and how many it holds in all.

        Args:
            limit: How many to return, newest first.

        Returns:
            The devices and the total.
        """
        return self._store.recent_devices(limit=limit)

    def registrations(self, *, limit: int = LISTING_LIMIT) -> tuple[Sequence[Registration], int]:
        """The newest registrations the record holds, and how many it holds in all.

        ADR-0298 §4:6: "``ai-assistant-device`` lists the registrations, so the owner
        can see every machine each gateway has named."

        Args:
            limit: How many to return, newest first.

        Returns:
            The registrations and the total.
        """
        return self._store.recent_registrations(limit=limit)

    @contextmanager
    def withheld(self, device: str) -> Iterator[None]:
        """Refuse a device everything while its revocation empties its memberships.

        ADR-0298 §4:10's revocation removes the device from "my devices" and every
        conversation's devices — on the conversation store, which is a suspension
        away — and then revokes it here. For that removal to be the last word, the
        device must not be able to put itself back meanwhile, and nobody may name it
        in a set: so while this block runs the roster refuses its every request and
        knows it as no device (:class:`~ai_assistant.service.roster.HubRoster`).
        Removing first is what leaves no state to finish: a removal that fails has
        revoked nothing, and a revocation whose record step fails has only taken the
        memberships of a device that is still admitted.

        Args:
            device: The device being revoked.

        Yields:
            Nothing; the device is withheld for the block's duration.
        """
        self._withheld[device] += 1
        try:
            yield
        finally:
            self._withheld[device] -= 1
            if not self._withheld[device]:
                del self._withheld[device]

    def is_withheld(self, device: str) -> bool:
        """Whether an owner's revocation of the device is in flight (:meth:`withheld`).

        Args:
            device: The device's id.

        Returns:
            Whether its requests are refused while its memberships are removed.
        """
        return device in self._withheld

    def check_revocable(self, device: str, *, gateway: str | None) -> None:
        """Refuse, before anything is changed anywhere, a revocation the record refuses.

        The record's own acts refuse these too; this is for the owner's act that
        removes the device from its memberships *before* the record moves, so it must
        not empty the hub's own machine's sets first and be refused after.

        Args:
            device: The device.
            gateway: The registration's gateway, or ``None`` for the whole device.

        Raises:
            RosterActError: For ``hub`` (§3:4), and for the hub's own overlay identity
                as a registration — a whole-device revocation of a legacy enrolment of
                it is the owner's way to end that enrolment (#2726).
        """
        if gateway is None:
            if device == HUB_DEVICE:
                self._refuse_the_hub(device, act="revoked")
            return
        self._refuse_the_hub(device, act="registered or revoked")

    def admitted_apart_from(self, device: str, *, gateway: str) -> bool:
        """Whether a device stays admitted once one registration of it is revoked.

        Args:
            device: The device.
            gateway: The gateway whose registration of it would be revoked.

        Returns:
            Whether a live enrolment or a live registration under another gateway
            still admits it.
        """
        return device in self._live or any(
            pair[0] == device and pair[1] != gateway for pair in self._registered
        )

    def _reserved(self) -> frozenset[str]:
        """The names no gateway may give and no act may enrol (ADR-0298 §3:3, §3:4)."""
        if self._hub_identity is None:
            return frozenset({HUB_DEVICE})
        return frozenset({HUB_DEVICE, self._hub_identity})

    def _refuse_the_hub(self, device: str, *, act: str) -> None:
        """Refuse an owner's act on the hub's own machine, in the owner's words."""
        if device in self._reserved():
            msg = (
                f"{device} is the hub's own machine, which is never {act}: it holds every "
                f"role through the local socket, and reaches the hub through nothing else"
            )
            raise RosterActError(msg)

    def _is_admitted(self, device: str) -> bool:
        """Whether a live enrolment or a live registration admits a device."""
        return device in self._live or any(pair[0] == device for pair in self._registered)

    def _settle_roles(self, device: str) -> None:
        """Mirror the record's invariant: a device nothing admits holds no role."""
        if not self._is_admitted(device):
            self._roles.pop(device, None)

    def _expel(self, identity: str, *, reason: str) -> None:
        """Close whatever connections a device holds, now that it holds none by right."""
        for callback in self._on_expelled:
            callback(identity, reason)


def _bounded_identity(identity: str) -> None:
    """Refuse an overlay identity too large to travel in an answer about it.

    Args:
        identity: The candidate.

    Raises:
        ValueError: If it exceeds the bound.
    """
    try:
        size = len(identity.encode("utf-8"))
    except UnicodeEncodeError as exc:
        msg = (
            "an overlay identity with no UTF-8 form cannot be recorded or compared; "
            "a lone surrogate survives a JSON decode and has no encoded form at all"
        )
        raise ValueError(msg) from exc
    if size > MAX_OVERLAY_IDENTITY_BYTES:
        msg = (
            f"an overlay identity of {size} bytes is over the "
            f"{MAX_OVERLAY_IDENTITY_BYTES}-byte bound; no overlay this hub accepts "
            f"produces one, and an enrolment recorded under it could not be reported"
        )
        raise ValueError(msg)


def _as_enrolment(row: sqlite3.Row) -> Enrolment:
    """Rebuild one row as an :class:`Enrolment`."""
    revoked = row["revoked_at"]
    return Enrolment(
        enrolment_id=row["id"],
        overlay_identity=row["overlay_identity"],
        enrolled_at=_instant(row["enrolled_at"]),
        revoked_at=None if revoked is None else _instant(revoked),
    )


def _as_registration(row: sqlite3.Row) -> Registration:
    """Rebuild one row as a :class:`Registration`."""
    revoked = row["revoked_at"]
    return Registration(
        registration_id=row["id"],
        device_id=row["device_id"],
        gateway=row["gateway"],
        registered_at=_instant(row["registered_at"]),
        revoked_at=None if revoked is None else _instant(revoked),
    )


def _stamp(moment: datetime) -> str:
    """Render one instant for storage, in UTC, so two rows are comparable as text."""
    return moment.astimezone(UTC).isoformat()


def _instant(stamp: str) -> datetime:
    """Read one stored instant back."""
    return datetime.fromisoformat(stamp)
