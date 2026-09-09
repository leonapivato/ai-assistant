"""A durable :class:`~ai_assistant.core.protocols.DestinationTrustStore` on SQLite.

ADR-0238 §1's store, arriving beside the recipient-grant store one module over and
built to its shape. It holds the **mirror** of the source side #2096 records: that
note keeps one fact per *source* — who may write here — and this keeps one fact per
*destination*, so milestone 31's provider and milestone 32's returned site are two
values of one rule rather than two boundaries.

**One fact and nothing else.** A row is a destination set, the instant the user
picked it, and the instant they withdrew it if they have. No tool, no account, no
payload, no description and no content — which is what makes it readable for a
destination no ``RecipientGrant`` covers, the property milestone 32 needs and a
grant-carried field could not have (§1).

**Where it departs from :mod:`ai_assistant.permissions.recipient_grants`,
deliberately.** That store is append-only and spells a revocation as a second
*record* transcribing the first. ADR-0238 §1 puts ``revoked_at`` on the record
itself and gives :meth:`~ai_assistant.core.protocols.DestinationTrustStore.revoke` a
record id and an instant, so a revocation here is an **update of exactly one
field**. The trigger below is what makes that a narrower claim than "this table is
mutable": every other byte of the stored record is frozen against ``UPDATE``, so
§1's "a revocation … **rewrites no recorded decision**" is enforced by the database
rather than by this module's care.

**The duplicate refusal is over the *live* set and is atomic with the append**
(§1). Two engines over one data directory each reading no live record over a
destination set and each appending would leave the store holding two, and the user's
revocation of the record they were shown would leave the other standing — so §1's
revocation clause would be false of the *store* rather than of any one record.
``BEGIN IMMEDIATE`` takes the write lock before the read the write depends on, which
is what closes that against the file; the :class:`asyncio.Lock` closes it within one
process.

**Two error postures, and they are not interchangeable** (§1).
:meth:`~ai_assistant.core.protocols.DestinationTrustStore.trust_of` **never raises**:
the trust of a destination is ``UNCHOSEN`` "in every other case, including … where a
record cannot be read", so the one read a policy path depends on fails *closed* by
answering. Every other member raises
:class:`~ai_assistant.core.errors.InvalidDestinationTrustError`, which is the single
class ADR-0238 §13 closes this decision's ``core/errors.py`` surface at.

Local-first (ADR-0002), and **locally only**: ADR-0238 §1 rules these records Tier 1
and applies ADR-0004 §2's residency clause to them, so nothing here may reach a
remote service. The database file is created owner-only (ADR-0004 §4, ADR-0084 §9),
before the first statement, so a rollback journal SQLite opens for it inherits that
mode rather than the process umask.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from pydantic import ValidationError

from ai_assistant.core.errors import InvalidDestinationTrustError
from ai_assistant.core.types import (
    DestinationTrust,
    DestinationTrustRecord,
    describe_untrusted,
)
from ai_assistant.permissions._detachment import field_state
from ai_assistant.permissions._transactions import transaction

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractContextManager

    from ai_assistant.core.types import CanonicalDestination

_OWNER_ONLY = 0o600

#: The sidecars SQLite may keep beside a database file. Each holds the same pages the
#: database does, so ADR-0004 §4 reaches them too — the family shares this method by
#: copy today (#506), and this store is the eighth copy rather than a new choice.
_SIDECARS = ("-journal", "-wal", "-shm")


async def _run_to_completion[T](fn: Callable[..., T], /, *args: object) -> T:
    """Run ``fn`` in a worker thread, holding on until it *physically* finishes (ADR-0054).

    The **eighth** copy of this helper rather than an import from a sibling, which is
    the tree's established position rather than a fresh choice: each SQLite store
    carries its own, and #506 and #563 already track consolidating the family. A
    private import from :mod:`ai_assistant.permissions.recipient_grants` would make
    one store's helper silently govern another's.

    The store serialises one ``sqlite3`` connection behind an :class:`asyncio.Lock`
    and runs the SQL in a worker thread. A thread cannot be interrupted, so if the
    awaiting coroutine were simply cancelled the enclosing ``async with self._lock``
    would unwind and release the lock **while the worker was still using the
    connection** — letting a second caller use the same connection concurrently,
    which SQLite refuses. The worker records its own outcome and sets a
    :class:`threading.Event` when it physically returns; this coroutine waits on
    *that* signal, so the lock is held for the whole life of the worker even under a
    blanket task cancellation.

    The completion wait is submitted **at most once** (#697): a copy that submits a
    fresh one per cancellation leaves every earlier one parked in ``Event.wait``,
    which turns one stalled store operation into a process that cannot run any thread
    work at all.
    """
    done = threading.Event()
    outcome: list[T] = []
    failure: list[BaseException] = []

    def worker() -> None:
        try:
            outcome.append(fn(*args))
        except BaseException as exc:  # relayed to the caller once the thread has finished
            failure.append(exc)
        finally:
            done.set()

    loop = asyncio.get_running_loop()
    pending: asyncio.Future[Any] = loop.run_in_executor(None, worker)
    waiting: asyncio.Future[Any] | None = None
    cancellation: asyncio.CancelledError | None = None
    while not done.is_set():
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError as exc:
            cancellation = exc
            if waiting is None:
                waiting = loop.run_in_executor(None, done.wait)
            pending = waiting
    if cancellation is not None:
        raise cancellation
    if failure:
        raise failure[0]
    return outcome[0]


#: One shape only, so far, and there is no ``_migrate`` here because version 1 is the
#: first shape this store has ever had: an unlabelled database is one this code is
#: creating now, and it is stamped rather than migrated.
_SCHEMA_VERSION = 1

#: Created first and on its own, so a database labelled with a schema this code
#: cannot read is refused *before* the ``destination_trust`` table is created or
#: read — creating a table is a write, and the refusal precedes any write.
_META_SCHEMA = "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"

_READ_SCHEMA_VERSION = "SELECT value FROM meta WHERE key = 'schema_version'"

_WRITE_SCHEMA_VERSION = "INSERT INTO meta(key, value) VALUES ('schema_version', ?)"

#: The epoch the sort keys count from. Any fixed instant would do; this one is
#: conventional.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# **The blob is the record, and every column that decides anything is derived from
# it.** ``id`` and ``revoked_at`` are ``GENERATED ALWAYS`` from the JSON, which is
# ``SqliteRecipientGrantStore``'s shape one module over and is taken for its reason: a
# stored column that merely *agreed* with the blob when it was written is a second copy
# of a value, and a store whose liveness filter reads the copy while its answer decodes
# the blob can be made to say that a revoked record is live. Derived, they cannot
# disagree.
#
# **``established_at_us`` is a plain column and decides nothing.** It exists because
# `live` and `export` sort by the instant of the user's act and SQLite cannot sort an
# ISO-8601 instant correctly — ``"…:00.000001Z"`` sorts *before* ``"…:00Z"`` by code
# point, so a generated column over ``json_extract`` would put a later record first.
# What is left on it is an ordering, and the update trigger below is what holds it.
_CREATE_TABLE = (
    "CREATE TABLE IF NOT EXISTS destination_trust("
    "established_at_us INTEGER NOT NULL, data TEXT NOT NULL, "
    "id TEXT GENERATED ALWAYS AS (json_extract(data, '$.id')) VIRTUAL, "
    "revoked_at TEXT GENERATED ALWAYS AS (json_extract(data, '$.revoked_at')) VIRTUAL)"
)

#: Keyed by name, because :data:`_OBJECTS` holds each one to its own definition and a
#: positional tuple would make that mapping a place to get wrong.
_INDEXES = {
    # The primary key `id` cannot be, because SQLite refuses a generated column in
    # one. Same constraint, same enforcement, and the derivation is kept.
    "destination_trust_id": (
        "CREATE UNIQUE INDEX IF NOT EXISTS destination_trust_id ON destination_trust(id)"
    ),
    "destination_trust_order": (
        "CREATE INDEX IF NOT EXISTS destination_trust_order "
        "ON destination_trust(established_at_us DESC, id ASC)"
    ),
}

#: **A revocation rewrites no recorded decision, said to SQLite rather than only to
#: the reader** (ADR-0238 §1). This store admits exactly one mutation — ``revoke``
#: setting ``revoked_at`` on a record that has none — and this trigger is what makes
#: that a claim the database enforces rather than one this module keeps. It compares
#: the two blobs with ``revoked_at`` removed from each, so every other field is frozen
#: against ``UPDATE``, and it refuses a change to the ordering key in the same breath:
#: ``established_at_us`` orders a listing, and a row whose key was altered to sort
#: late would be handed to a caller in the wrong place with every row on it valid.
#:
#: **What it is and is not.** It is this store's invariant enforced by the store, the
#: way a ``UNIQUE`` index enforces write-once; it is not a boundary against an actor
#: who can already run arbitrary SQL against the file, who could drop it as easily as
#: run the ``UPDATE``. ADR-0004 §4's owner-only mode is where that question is
#: answered, and ADR-0099 §1's single-user model is what scopes it.
_REVOCATION_ONLY = (
    "CREATE TRIGGER IF NOT EXISTS destination_trust_revocation_only "
    "BEFORE UPDATE ON destination_trust "
    "WHEN json_remove(NEW.data, '$.revoked_at') IS NOT json_remove(OLD.data, '$.revoked_at') "
    "OR NEW.established_at_us IS NOT OLD.established_at_us "
    "BEGIN SELECT RAISE(ABORT, 'a destination trust record is never edited in place; a "
    "revocation sets revoked_at and rewrites no recorded decision'); END"
)

#: **Every object this store defines, held to its own definition.** ``CREATE TABLE IF
#: NOT EXISTS`` is a no-op against a table already there under that name *whatever
#: shape it has*, so a file arriving with a ``destination_trust`` table of ordinary
#: columns would keep it — and both generated projections would then read as ``NULL``,
#: because :meth:`SqliteDestinationTrustStore._record_sync` writes only
#: ``established_at_us`` and ``data``. Every stored record would answer as live and the
#: id index would constrain nothing: the exact failure the generated columns exist to
#: make impossible, walked around rather than through. The index and the trigger are
#: held the same way and for the same reason.
#:
#: SQLite stores a definition verbatim but for ``IF NOT EXISTS``, so what it holds is
#: compared against these very statements rather than against a second copy of them
#: written out by hand.
_OBJECTS: Final = {
    "destination_trust": _CREATE_TABLE,
    **_INDEXES,
    "destination_trust_revocation_only": _REVOCATION_ONLY,
}

_ORDERED = "SELECT data FROM destination_trust ORDER BY established_at_us DESC, id ASC"

#: Every **live** record: the liveness filter, read off the derived column so a
#: hand-written ``revoked_at`` in an ordinary column cannot hide a revocation.
#: No instant appears in this statement at all, which is what keeps this store's read
#: and write paths free of a clock: liveness here is "not revoked" and never an
#: interval, ADR-0238 §1 giving this record no expiry.
_LIVE = (
    "SELECT data FROM destination_trust WHERE revoked_at IS NULL "
    "ORDER BY established_at_us DESC, id ASC"
)

#: Whether one id is already held, over the derived column so a hand-written ``id``
#: cannot hide a row from the duplicate check.
_ID_IS_HELD = "SELECT 1 FROM destination_trust WHERE id = ?"

#: The one mutation this store admits: set ``revoked_at`` on a record that has none.
#: The ``IS NULL`` guard in the ``WHERE`` is what makes :meth:`revoke` **idempotent
#: without restamping** — a second call matches no row, so the first instant stands.
_REVOKE = (
    "UPDATE destination_trust SET data = json_set(data, '$.revoked_at', ?) "
    "WHERE id = ? AND revoked_at IS NULL"
)


def _sort_key(instant: datetime) -> int:
    """Return ``instant`` as whole microseconds since the epoch.

    An **integer**, computed from a ``timedelta``'s integer components rather than
    from ``timestamp()``. Ordering is part of :meth:`SqliteDestinationTrustStore.live`'s
    contract, and a float epoch second carrying microsecond precision needs sixteen
    significant digits at present-day values — right at the edge of a double, so two
    records a microsecond apart could compare equal or invert. The subtraction below
    is exact.

    ``established_at`` is a ``UtcInstant``, already normalised to UTC by ``core``, so
    this is a key over *instants* — which is what makes the DST repeated hour sort
    correctly rather than by wall clock.
    """
    elapsed = instant - _EPOCH
    return (elapsed.days * 86_400 + elapsed.seconds) * 1_000_000 + elapsed.microseconds


class SqliteDestinationTrustStore:
    """A persistent, validating ``DestinationTrustStore`` (ADR-0238 §1).

    Structurally implements
    :class:`~ai_assistant.core.protocols.DestinationTrustStore`.

    **Records are stored as their JSON dump and rebuilt on every read**, which is how
    the "detached, validated snapshot" obligation is obtained here without a copy step
    to forget: serialising rebuilds every reachable value, so there is no object graph
    shared with the caller in either direction, and the store cannot hand back a
    caller-supplied subclass.

    **The write-side snapshot is taken from the instance's own field state**, not from
    ``model_dump()`` — see :func:`_revalidated`. ``model_dump`` is an ordinary
    overridable method, so a subclass whose dump reports a *wider* destination tuple
    than the instance holds would have the store append a trust record over
    destinations the user never named.

    **Atomicity** comes from an :class:`asyncio.Lock` around the whole of
    :meth:`record`, with the duplicate-id check, the duplicate-live-set refusal and
    the insert running in one worker call inside a single ``BEGIN IMMEDIATE``
    transaction.

    **No busy timeout is set here, and that is the family's posture rather than this
    store's choice** (#564): no SQLite store in this tree sets one deliberately, so
    under cross-process contention ``BEGIN IMMEDIATE`` surfaces ``SQLITE_BUSY`` after
    the driver's default.
    """

    def __init__(self, *, path: Path | str) -> None:
        """Open (or create) the destination-trust store at ``path``.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral store.
                **Required, with no default.** Durability is the whole reason this
                implementation exists — ADR-0238 §1 rules the store "local and durable
                and … never written to a remote service", so a default would let the
                ordinary construction produce a store that forgets the user's act on
                restart. An ephemeral store is available and has to be asked for. It
                lives under ``Settings.data_dir`` in a real deployment, which is the
                composition root's choice rather than this class's.

        Raises:
            InvalidDestinationTrustError: If the database cannot be opened or
                initialised.
        """
        self._path = path if path == ":memory:" else str(Path(path))
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    # --- opening ----------------------------------------------------------

    def _setup(self) -> sqlite3.Connection:
        """Connect and create the schema, never leaking a half-open connection."""
        try:
            conn = sqlite3.connect(self._path, check_same_thread=False)
        except (sqlite3.Error, OSError, ValueError) as exc:
            # e.g. the parent directory does not exist — no connection to close.
            # ``ValueError`` is named because a path carrying an embedded NUL raises
            # it out of the driver rather than a ``sqlite3.Error``, and a bad path is
            # this layer's fault to report rather than a raw builtin escaping past
            # its error boundary.
            msg = f"failed to open the destination-trust store at {self._path!r}: {exc}"
            raise InvalidDestinationTrustError(msg) from exc
        try:
            # Restricted *before* the first statement, not after the schema is built:
            # SQLite copies the database file's mode onto every rollback journal it
            # creates for it, so a journal opened while the file still carried the
            # process umask is world-readable too — and an interrupted write leaves it
            # on disk holding Tier 1 pages (#489).
            self._restrict_permissions()
            with conn:  # commits on success, rolls back on any exception
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(_META_SCHEMA)
                labelled = self._check_schema_version(conn)
                conn.execute(_CREATE_TABLE)
                # The table is held to its definition **before** the index and the
                # trigger are created over it. A file arriving with a
                # ``destination_trust`` table of ordinary columns would otherwise fail
                # on an index naming a column it does not have, and the open would
                # report a raw SQLite complaint instead of the fact — that this is not
                # this store's table and its rows cannot be trusted to say what the
                # user chose.
                self._check_objects(conn, ("destination_trust",))
                for statement in _INDEXES.values():
                    conn.execute(statement)
                conn.execute(_REVOCATION_ONLY)
                self._check_objects(conn, tuple(_OBJECTS))
                if not labelled:
                    # Stamped *after* the create above, and inside the same
                    # transaction, so a failure rolls the marker — and the ``meta``
                    # table itself — back with it rather than leaving a database
                    # falsely labelled current.
                    conn.execute(_WRITE_SCHEMA_VERSION, (str(_SCHEMA_VERSION),))
        except InvalidDestinationTrustError:
            # A refused schema version is already this layer's error; it still leaves
            # a connection to close before it propagates.
            conn.close()
            raise
        except (sqlite3.Error, OSError) as exc:
            conn.close()
            msg = f"failed to initialise the destination-trust store at {self._path!r}: {exc}"
            raise InvalidDestinationTrustError(msg) from exc
        return conn

    def _check_objects(self, conn: sqlite3.Connection, names: tuple[str, ...]) -> None:
        """Refuse a file whose ``names`` are not the objects this store defines.

        Run after the creates and **before** the marker is written, inside the same
        transaction, so a refusal leaves the file exactly as it arrived — unopened,
        unlabelled, and not carrying this store's marker over a shape that is not
        this store's. See :data:`_OBJECTS` for what each one buys.

        Args:
            conn: The connection the setup transaction is running on.
            names: Which of :data:`_OBJECTS` to check. The table alone runs first, so
                a file that is not this store's is reported as that rather than as an
                index failing on a column it does not have.

        Raises:
            InvalidDestinationTrustError: If an object is missing or is not the one
                this store defines.
        """
        held = {
            str(name): sql
            for name, sql in conn.execute("SELECT name, sql FROM sqlite_master")
            if name in names
        }
        for name in names:
            defined = _OBJECTS[name].replace(" IF NOT EXISTS", "", 1)
            if held.get(name) != defined:
                msg = (
                    f"the destination-trust store at {self._path!r} holds an object named "
                    f"{name!r} that is not the one this store defines; its rows cannot be "
                    f"trusted to say what the user chose, so it is not opened"
                )
                raise InvalidDestinationTrustError(msg)

    def _restrict_permissions(self) -> None:
        """Make the database file and any sidecar beside it owner-only (ADR-0004 §4).

        A missing sidecar is the ordinary case rather than a fault, so absence is
        tolerated one name at a time; nothing else is. A *symlink* under a sidecar's
        name is skipped rather than followed, because ``chmod`` follows links and
        restricting one would silently narrow a file this store has no business
        modifying. A no-op in memory.

        **Duplicated from the seven other SQLite stores on purpose** (#506): the
        family shares this method by copy today, and consolidating it is that issue's,
        not this lane's.
        """
        if self._path == ":memory:":
            return
        database = Path(self._path)
        database.chmod(_OWNER_ONLY)
        for suffix in _SIDECARS:
            sidecar = database.with_name(database.name + suffix)
            if sidecar.is_symlink():
                continue
            with contextlib.suppress(FileNotFoundError):
                sidecar.chmod(_OWNER_ONLY)

    def _check_schema_version(self, conn: sqlite3.Connection) -> bool:
        """Refuse a labelled schema this code cannot read; say whether one is labelled.

        Runs inside the setup transaction, after ``meta`` exists and **before** the
        ``destination_trust`` table is created or read.

        **An unlabelled database is stamped rather than migrated**: this store ships
        *with* its marker, so version 1 is the only shape it has ever written and an
        unlabelled file is one this open is creating.

        Returns:
            Whether the database already carries a ``schema_version``.

        Raises:
            InvalidDestinationTrustError: If the stored version is not one this code
                understands, is not an integer at all, or is not a single unambiguous
                value.
        """
        rows = conn.execute(_READ_SCHEMA_VERSION).fetchall()
        if not rows:
            return False
        if len(rows) > 1:
            # ``meta``'s primary key makes this unreachable for a table *this* code
            # created — but ``CREATE TABLE IF NOT EXISTS`` accepts a pre-existing
            # ``meta`` declared without one, so a corrupt or hand-built file can hold
            # conflicting markers, and reading the first row would let an unsupported
            # version through on the strength of a sibling that agrees.
            found = sorted({str(row[0]) for row in rows})
            msg = (
                f"the destination-trust store at {self._path!r} holds {len(rows)} "
                f"schema_version rows ({', '.join(repr(value) for value in found)}); "
                f"the store is corrupt"
            )
            raise InvalidDestinationTrustError(msg)
        raw = rows[0][0]
        msg = (
            f"the destination-trust store at {self._path!r} holds a non-numeric "
            f"schema_version {raw!r}"
        )
        # The marker this code writes is always TEXT, but a hand-built ``meta`` may
        # declare no type, in which case SQLite hands back whatever was stored.
        # ``int(float("inf"))`` raises ``OverflowError``, which is neither
        # ``ValueError`` nor an ``AssistantError`` and would leave this layer's
        # boundary through a hole. ``bool`` is an ``int`` in Python, so it is named
        # rather than left to read as version 1.
        if isinstance(raw, bool) or not isinstance(raw, str | int):
            raise InvalidDestinationTrustError(msg)
        try:
            stored = int(raw)
        except ValueError as exc:
            raise InvalidDestinationTrustError(msg) from exc
        if stored != _SCHEMA_VERSION:
            msg = (
                f"the destination-trust store at {self._path!r} has schema_version={stored}, "
                f"but this code supports only version {_SCHEMA_VERSION}; refusing to open it "
                f"rather than read it blindly"
            )
            raise InvalidDestinationTrustError(msg)
        return True

    def _transaction(self, what: str) -> AbstractContextManager[sqlite3.Connection]:
        """Run the block inside one transaction, translating backend failures.

        ``IMMEDIATE`` takes the write lock up front rather than at the first write,
        which is what puts :meth:`_record_sync`'s *reads* under it: the free-id check
        and the duplicate-live-set refusal both decide whether the append may happen,
        so a deferred begin would let a second process observe the same free id or the
        same absent destination set between them and the append. The ``asyncio`` lock
        closes that within one process; this closes it against the file (ADR-0238 §1).

        Raises:
            InvalidDestinationTrustError: If the backend fails at any point.
        """
        return transaction(self._conn, what, error=InvalidDestinationTrustError, immediate=True)

    # --- the write path ---------------------------------------------------

    async def record(self, record: DestinationTrustRecord) -> str:
        """Append ``record`` and return its id (ADR-0238 §1).

        Write-once, and atomic over the duplicate-id check, the duplicate-live-set
        refusal and the append.

        Raises:
            InvalidDestinationTrustError: If the record does not satisfy its own
                model, if its id is already recorded, if it duplicates a live record's
                destination set, or if the database refuses the write. Pydantic's
                ``ValidationError`` is deliberately not allowed to escape:
                ``CONTRIBUTING`` has this layer raise only from the ``AssistantError``
                hierarchy.
        """
        snapshot = _revalidated(record)
        async with self._lock:
            await _run_to_completion(self._record_sync, snapshot)
        return snapshot.id

    def _record_sync(self, snapshot: DestinationTrustRecord) -> None:
        """Validate against what is stored and insert, as one transaction."""
        with self._transaction(f"record destination trust {snapshot.id!r}") as conn:
            if conn.execute(_ID_IS_HELD, (snapshot.id,)).fetchone():
                msg = (
                    f"destination trust record {snapshot.id!r} is already recorded; the store "
                    f"is write-once, so history cannot be rewritten by replaying a write"
                )
                raise InvalidDestinationTrustError(msg)
            self._check_no_live_duplicate(conn, snapshot)
            # Only the two stored columns: ``id`` and ``revoked_at`` are derived from
            # the blob by the table's own definition, so there is nothing to write and
            # nothing that could be written disagreeing with it.
            conn.execute(
                "INSERT INTO destination_trust(established_at_us, data) VALUES (?, ?)",
                (_sort_key(snapshot.established_at), snapshot.model_dump_json()),
            )

    def _check_no_live_duplicate(
        self, conn: sqlite3.Connection, record: DestinationTrustRecord
    ) -> None:
        """Refuse a record duplicating a **live** record's destination set (ADR-0238 §1).

        Decoded and compared as tuples, which **means** set equality because the
        record's own validator pinned the one canonical spelling at construction. That
        is the whole reason ADR-0238 §1 takes ADR-0193 §1's ordering rule rather than
        stating a duplicate rule over membership: ``(Alice, Bob)`` and ``(Bob,
        Alice)`` would otherwise both be admitted over one logical set, and revoking
        the record the user was shown would leave the other standing with the
        destination still reading ``USER_CHOSEN``.

        Raises:
            InvalidDestinationTrustError: If a live record names the same set.
        """
        for held in self._decoded(conn.execute(_LIVE).fetchall()):
            if held.destinations == record.destinations:
                msg = (
                    f"destination trust record {record.id!r} names the destination set live "
                    f"record {held.id!r} already names; revoking one would leave the other "
                    f"standing and the user would have revoked nothing (ADR-0238 §1)"
                )
                raise InvalidDestinationTrustError(msg)

    async def revoke(self, record_id: str, revoked_at: datetime) -> None:
        """Withdraw ``record_id``, prospectively and idempotently (ADR-0238 §1).

        Raises:
            InvalidDestinationTrustError: If ``record_id`` names no record this store
                holds, if ``revoked_at`` is not a usable instant, or if the database
                refuses the write.
        """
        stamp = _revocation_instant(record_id, revoked_at)
        async with self._lock:
            await _run_to_completion(self._revoke_sync, record_id, stamp)

    def _revoke_sync(self, record_id: str, stamp: str) -> None:
        """Stamp the record if it is present and unrevoked, as one transaction.

        The presence check and the update are one act: the update's own ``WHERE``
        cannot tell "no such record" from "already revoked", and those are the two
        cases ADR-0238 §1 separates — the first raises and the second is a no-op that
        leaves the first instant standing.
        """
        with self._transaction(f"revoke destination trust {record_id!r}") as conn:
            if not conn.execute(_ID_IS_HELD, (record_id,)).fetchone():
                msg = (
                    f"destination trust record {describe_untrusted(record_id)} is not recorded, "
                    f"so there is nothing to revoke (ADR-0238 §1)"
                )
                raise InvalidDestinationTrustError(msg)
            conn.execute(_REVOKE, (stamp, record_id))

    # --- the read path ----------------------------------------------------

    async def trust_of(self, destinations: Sequence[CanonicalDestination]) -> DestinationTrust:
        """The recorded trust of ``destinations`` (ADR-0238 §1).

        ``USER_CHOSEN`` only where **every** member of the sequence is a member of
        **some one** live record's ``destinations``, compared as a
        :class:`~ai_assistant.core.types.CanonicalDestination` compares — every field,
        never across protocols. ``UNCHOSEN`` for an empty sequence, for a partial
        match, and for a match spanning two records.

        **This member raises for nothing**, which is §1's clause and not a swallowed
        error: the trust of a destination is ``UNCHOSEN`` "in every other case,
        including … where a record cannot be read". A store that raised here would
        make the one read a policy path depends on fail *open* into an exception
        somebody has to catch correctly at every call site, where answering
        ``UNCHOSEN`` fails closed by construction.
        """
        # **Snapshotted before the first await, and read only from the snapshot after
        # it** — ADR-0065's coherent input-observation clause, which this member is the
        # one place in this store that is not vacuously subject to. Every other
        # caller-owned argument here is a ``DestinationTrustRecord`` or a ``str``, both
        # immutable all the way down; a ``Sequence`` is not, and a caller holding the
        # list it passed can empty it while this call is suspended on the lock. Read
        # twice, the emptiness check would pass on the sequence the caller handed over
        # and the coverage check would then run ``all(...)`` over **no members** —
        # vacuously true — so an emptied query would answer ``USER_CHOSEN`` for any
        # store holding a live record. ADR-0238 §1 refuses exactly that answer, ruling
        # the trust ``UNCHOSEN`` for an empty sequence — so it would be reached with no
        # input state warranting it.
        wanted = tuple(destinations)
        if not wanted:
            return DestinationTrust.UNCHOSEN
        try:
            async with self._lock:
                rows = await _run_to_completion(self._live_sync)
            live = self._decoded(rows)
        except sqlite3.Error, OSError, ValueError, InvalidDestinationTrustError:
            # ``CancelledError`` is a ``BaseException`` and is deliberately not caught:
            # ADR-0060's clause is that a cancellation leaves this seam unchanged, and
            # reporting it as ``UNCHOSEN`` would convert one into an answer.
            return DestinationTrust.UNCHOSEN
        for held in live:
            covered = set(held.destinations)
            if all(destination in covered for destination in wanted):
                return DestinationTrust.USER_CHOSEN
        return DestinationTrust.UNCHOSEN

    async def live(self) -> list[DestinationTrustRecord]:
        """Every unrevoked record, newest act first with ``id`` as the tie-break.

        Raises:
            InvalidDestinationTrustError: If the store cannot be read, or holds a
                record that no longer validates.
        """
        async with self._lock:
            rows = await _run_to_completion(self._live_sync)
        return self._decoded(rows)

    def _live_sync(self) -> Sequence[tuple[str]]:
        with self._transaction("read live destination trust records") as conn:
            return conn.execute(_LIVE).fetchall()

    async def export(self) -> list[DestinationTrustRecord]:
        """**Every** record, revoked ones included, in :meth:`live`'s order.

        The user's export right (ADR-0004 §6), and what discharges it for this store —
        so it may omit **nothing**. An implementation that delegated this to
        :meth:`live` would silently drop every revoked record, which is precisely the
        evidence that the user once permitted a destination and then withdrew it.

        Raises:
            InvalidDestinationTrustError: If the store cannot be read, or holds a
                record that no longer validates.
        """
        async with self._lock:
            rows = await _run_to_completion(self._ordered_sync)
        return self._decoded(rows)

    def _ordered_sync(self) -> Sequence[tuple[str]]:
        with self._transaction("read every destination trust record") as conn:
            return conn.execute(_ORDERED).fetchall()

    def _decoded(self, rows: Sequence[tuple[str]]) -> list[DestinationTrustRecord]:
        """Rebuild each stored row, refusing one that no longer validates.

        Rebuilding is what makes every read a **detached** snapshot: nothing of the
        store's own state is reachable from what a caller receives, and nothing a
        caller mutates reaches the store.
        """
        return [self._decode(row[0]) for row in rows]

    def _decode(self, data: str) -> DestinationTrustRecord:
        """Rebuild one stored row.

        Raises:
            InvalidDestinationTrustError: If the row does not validate. A stored row
                that no longer satisfies its own model is a corrupt store rather than
                a caller's mistake, and reporting it as an absent record would let a
                revoked destination read as live.
        """
        try:
            return DestinationTrustRecord.model_validate_json(data)
        except ValidationError as exc:
            msg = (
                f"the destination-trust store at {self._path!r} holds a record that no longer "
                f"validates: {exc}"
            )
            raise InvalidDestinationTrustError(msg) from exc

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()


def _revalidated(record: DestinationTrustRecord) -> DestinationTrustRecord:
    """Rebuild ``record`` as a validated :class:`DestinationTrustRecord`.

    ADR-0238 §1 asks for a *validated* snapshot, not merely a detached one — the
    obligation :meth:`RecipientGrantStore.record`'s own wording states and this store
    inherits. A copy alone detaches without checking, so a record corrupted past its
    frozen model's guard would be stored and make every later read incoherent: a
    destination tuple written back out of canonical order would leave the
    duplicate-live-set refusal comparing a spelling the record's own validator
    refuses.

    Rebuilt as a ``DestinationTrustRecord`` specifically, not as ``type(record)``: a
    caller's subclass could carry extra fields, and they are refused here rather than
    allowed to vanish at serialisation and make the stored record differ from the one
    that reloads.

    **And rebuilt from the instance's field state rather than from ``model_dump()``.**
    ``model_dump`` is an ordinary overridable method, so a subclass can return a
    mapping that does not describe itself — a one-destination instance whose dump
    names two — and the store would then append **a trust record over a destination
    the user never named**. :func:`~ai_assistant.permissions._detachment.field_state`
    is that read, and it detaches *recursively*: a mapping of the instance's own field
    values would still hold the caller's ``CanonicalDestination`` objects, which
    ``frozen=True`` does not protect against a write through ``__dict__``.

    **Nothing of the caller's is read outside the guard**, the diagnostic id included:
    ``record`` is typed to take a ``DestinationTrustRecord`` and the caller is not
    obliged by anything at runtime to pass one.

    Raises:
        InvalidDestinationTrustError: If the record does not satisfy its own model,
            carries state ``DestinationTrustRecord`` declares no field for, or holds
            beneath it a model of any type other than exactly the declared one.
    """
    try:
        return DestinationTrustRecord.model_validate(field_state(DestinationTrustRecord, record))
    except ValueError as exc:
        # ``describe_untrusted`` on the cause as well: ``field_state`` re-raises a
        # ``ValueError`` the caller's own code raised, and a hostile ``__str__`` on it
        # would replace this refusal with whatever it threw — from inside the
        # ``except`` block that exists to report it.
        msg = f"destination trust record is not a valid record: {describe_untrusted(exc)}"
        raise InvalidDestinationTrustError(msg) from exc


def _revocation_instant(record_id: str, revoked_at: object) -> str:
    """Render ``revoked_at`` the way the stored record renders it, or refuse.

    Rendered through :class:`DestinationTrustRecord`'s **own** serializer rather than
    by ``isoformat()`` here, so the value written into the blob is byte-identical to
    the one a record constructed with that instant would carry — a second spelling
    would make a revoked record decode to an instant the record's own validator would
    have normalised differently. The throwaway record is built for that rendering
    alone and is never stored.

    Raises:
        InvalidDestinationTrustError: If ``revoked_at`` is not a usable UTC instant. A
            naive instant is refused for :attr:`RecipientGrant.decided_at`'s reason —
            the store is durable *and* ordered.
    """
    try:
        rendered = DestinationTrustRecord.model_validate(
            {
                "id": "probe",
                "destinations": _PROBE_DESTINATIONS,
                "trust": DestinationTrust.USER_CHOSEN,
                "established_at": revoked_at,
                "revoked_at": revoked_at,
            }
        ).model_dump(mode="json")["revoked_at"]
    except ValueError as exc:
        msg = (
            f"destination trust record {describe_untrusted(record_id)} cannot be revoked at "
            f"{describe_untrusted(revoked_at)}: {describe_untrusted(exc)}"
        )
        raise InvalidDestinationTrustError(msg) from exc
    return str(rendered)


#: A single well-formed member, so the probe record in :func:`_revocation_instant`
#: validates for every reason but the instant under test. Its content is immaterial
#: and it never leaves that function.
_PROBE_DESTINATIONS: Final = ({"protocol": "smtp", "canonical": "probe@example.invalid"},)
