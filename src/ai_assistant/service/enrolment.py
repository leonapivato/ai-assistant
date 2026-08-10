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
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.service.overlay import MAX_OVERLAY_IDENTITY_BYTES
from ai_assistant.wire.credential import mint_credential, verifier_for, verifies

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
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
        return bool(changed)


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

    def __init__(self, store: EnrolmentStore, *, hub_identity: str) -> None:
        """Read the record into the hub's live view.

        Args:
            store: The durable record.
            hub_identity: This hub's own overlay identity, disclosed beside every
                credential it mints (§6).
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

    @property
    def hub_identity(self) -> str:
        """This hub's own overlay identity (ADR-0124 §4, §6)."""
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
        """
        credential = mint_credential()
        verifier = verifier_for(credential)
        enrolment, rotated = self._store.enrol(identity, verifier=verifier, now=now)
        # The database has committed and these lines are the same synchronous step,
        # so no coroutine can observe the intermediate state §6 forbids: two live
        # enrolments for one identity, or none.
        self._live[identity] = (enrolment.enrolment_id, verifier)
        self._known.add(identity)
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
            hub_identity=self._hub_identity,
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


def _stamp(moment: datetime) -> str:
    """Render one instant for storage, in UTC, so two rows are comparable as text."""
    return moment.astimezone(UTC).isoformat()


def _instant(stamp: str) -> datetime:
    """Read one stored instant back."""
    return datetime.fromisoformat(stamp)
